import hashlib
import hmac
import secrets
import re
from sqlalchemy import select, insert, delete, update
from .database import users, tokens, quota, ident, stamp

class AccessError(ValueError): pass

def digest(value): return hashlib.sha256(value.encode()).hexdigest()
def password_hash(value):
    salt = secrets.token_bytes(16)
    return salt.hex() + ':' + hashlib.scrypt(value.encode(), salt=salt, n=16384, r=8, p=1).hex()
def verify(value, stored):
    try:
        salt, expected = stored.split(':')
        actual = hashlib.scrypt(value.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError): return False

class Auth:
    def __init__(self, db, settings):
        self.db, self.settings = db, settings
        self.dummy = password_hash('dummy-timing-password')

    def throttle(self, ip, username):
        minute = int(stamp()//600)
        with self.db.tx() as c:
            for key, cap in [(f'auth-ip:{digest(ip)}:{minute}', 30), (f'auth-user:{digest(username)}:{minute}', 10)]:
                row = c.execute(select(quota).where(quota.c.key==key)).mappings().first()
                if row and row['calls'] >= cap: raise AccessError('尝试过多，请十分钟后重试 / Too many attempts')
                if row: c.execute(update(quota).where(quota.c.key==key).values(calls=row['calls']+1))
                else: c.execute(insert(quota).values(key=key,calls=1,reserved_usd=0))

    def login(self, username, password, *, register=False, invite='', consent=False, adult=False):
        username = username.strip().lower()
        if not re.fullmatch(r'[a-z0-9_\-]{3,40}', username) or not 12 <= len(password) <= 128:
            raise AccessError('用户名需3–40位字母/数字，密码需12–128位 / Invalid username or password length')
        if register:
            if not consent or not adult: raise AccessError('请确认年满18岁并阅读数据说明 / Adult consent required')
            if self.settings.invite_code and not hmac.compare_digest(invite, self.settings.invite_code):
                raise AccessError('邀请码无效 / Invalid invitation')
            hashed = password_hash(password)
            with self.db.tx() as c:
                if c.execute(select(users.c.id).where(users.c.username==username)).first():
                    raise AccessError('无法注册该用户名 / Username unavailable')
                uid = ident()
                c.execute(insert(users).values(id=uid,username=username,password_hash=hashed,created=stamp(),epoch=0,consent_version='2026-10-v1'))
        else:
            with self.db.read() as c: row = c.execute(select(users).where(users.c.username==username)).mappings().first()
            if not verify(password, row['password_hash'] if row else self.dummy) or not row:
                raise AccessError('用户名或密码错误 / Invalid credentials')
            uid = row['id']
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.db.tx() as c:
            c.execute(delete(tokens).where(tokens.c.expires < stamp()))
            if not c.execute(select(users.c.id).where(users.c.id==uid)).first(): raise AccessError('Account unavailable')
            c.execute(insert(tokens).values(digest=digest(token),user_id=uid,csrf=csrf,expires=stamp()+7*86400))
        return token, csrf

    def authenticate(self, token):
        with self.db.read() as c:
            row = c.execute(select(tokens.c.user_id, tokens.c.csrf, users.c.username).join(users,users.c.id==tokens.c.user_id)
                .where(tokens.c.digest==digest(token),tokens.c.expires>stamp())).mappings().first()
        if not row: raise AccessError('请登录 / Please sign in')
        return dict(row)

    def logout(self, token):
        with self.db.tx() as c: c.execute(delete(tokens).where(tokens.c.digest==digest(token)))
