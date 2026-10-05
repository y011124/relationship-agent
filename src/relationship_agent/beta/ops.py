"""Local operator tools. Database access is an operator privilege, never an HTTP route."""
import argparse
import json
import os
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone
from sqlalchemy import select, insert, update, delete
from cryptography.fernet import Fernet
from .database import Database, meta, users, tokens, runs, attempts, feedback, versions, locks, stamp
from .auth import password_hash

def backup(db,path,key):
    tables=[t for t in meta.sorted_tables if t not in (tokens,versions,locks)]
    with db.tx() as c:
        payload={'version':1,'created':stamp(),'tables':{t.name:[dict(r) for r in c.execute(select(t)).mappings()] for t in tables}}
    encrypted=Fernet(key).encrypt(json.dumps(payload,ensure_ascii=False).encode())
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as f:f.write(encrypted)
    return path

def restore(db,path,key):
    payload=json.loads(Fernet(key).decrypt(Path(path).read_bytes()))
    if payload['version']!=1:raise ValueError('Unsupported backup schema')
    with db.tx() as c:
        if c.execute(select(users.c.id).limit(1)).first():raise ValueError('Restore only into an empty isolated database')
        for t in meta.sorted_tables:
            rows=payload['tables'].get(t.name,[])
            if rows:c.execute(insert(t),rows)
        c.execute(update(runs).where(runs.c.status.in_(['queued','running'])).values(status='failed',worker=None,lease_until=0,error='从备份恢复；请确认后续删除请求后再继续 / Restored; check deletion requests before resuming'))
        c.execute(delete(tokens))

def stats(db):
    with db.read() as c:
        jobs=[dict(r) for r in c.execute(select(runs.c.status,runs.c.created,runs.c.finished)).mappings()]
        reviews=[dict(r) for r in c.execute(select(feedback.c.category,feedback.c.consent)).mappings()]
        billing=[dict(r) for r in c.execute(select(attempts.c.usage,attempts.c.estimated_usd)).mappings()]
    latency=sorted(r['finished']-r['created'] for r in jobs if r['status']=='complete' and r['finished'])
    return {'jobs':dict(Counter(r['status'] for r in jobs)),
      'feedback':dict(Counter(r['category'] for r in reviews)),
      'latency_seconds':{'p50':latency[int((len(latency)-1)*.5)] if latency else None,'p95':latency[int((len(latency)-1)*.95)] if latency else None},
      'model_attempts':len(billing),'attempts_with_reported_usage':sum(bool(r['usage']) for r in billing),
      'attempts_with_unknown_cost':sum(r['estimated_usd'] is None for r in billing),
      'estimated_known_model_usd':round(sum(r['estimated_usd'] or 0 for r in billing),6),
      'estimated_model_usd':None if any(r['estimated_usd'] is None for r in billing) else round(sum(r['estimated_usd'] or 0 for r in billing),6),
      'cost_note':'Configured prices; estimates exclude search fees and provider-side unreported/timeout charges.'}

def review(db,fid):
    with db.read() as c:
        f=c.execute(select(feedback).where(feedback.c.id==fid)).mappings().first()
        if not f or not f['consent']:raise ValueError('No explicit consent to inspect conversation')
        r=c.execute(select(runs.c.input,runs.c.result).where(runs.c.id==f['run_id'],runs.c.user_id==f['user_id'])).mappings().first()
        return {'note':f['note'],'conversation':dict(r) if r else None}

def main():
    from dotenv import load_dotenv
    load_dotenv()
    p=argparse.ArgumentParser(description='Persona operator tools; never point test/restore at a live production database')
    p.add_argument('command',choices=['stats','feedback','review','backup','restore','reset-password','purge-old-backups'])
    p.add_argument('--path');p.add_argument('--id');p.add_argument('--username')
    args=p.parse_args();db=Database(os.getenv('DATABASE_URL','sqlite:///memory/persona.sqlite3'))
    if args.command=='stats':print(json.dumps(stats(db),indent=2))
    elif args.command=='feedback':
        with db.read() as c:print(json.dumps([dict(x) for x in c.execute(select(feedback.c.id,feedback.c.category,feedback.c.consent,feedback.c.created)).mappings()],indent=2))
    elif args.command=='review':print(json.dumps(review(db,args.id),ensure_ascii=False,indent=2))
    elif args.command=='backup':
        filename=args.path or 'backups/persona-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'.enc'
        backup(db,filename,os.environ['PERSONA_BACKUP_KEY']);print('Encrypted backup created. Store its key separately.')
    elif args.command=='restore':restore(db,args.path,os.environ['PERSONA_BACKUP_KEY']);print('Restored into an empty database. Auth sessions revoked; review post-backup deletion requests before release.')
    elif args.command=='purge-old-backups':
        root=Path(args.path or 'backups');removed=0
        for f in root.glob('persona-*.enc'):
            if f.stat().st_mtime<stamp()-7*86400:f.unlink();removed+=1
        print('Expired backups removed:',removed)
    elif args.command=='reset-password':
        import getpass
        password=getpass.getpass('New password (verify account ownership out of band first): ')
        if not 12<=len(password)<=128:raise ValueError('Password must be 12–128 characters')
        with db.tx() as c:
            uid=c.execute(select(users.c.id).where(users.c.username==args.username)).scalar()
            if not uid:raise ValueError('Unknown username')
            c.execute(update(users).where(users.c.id==uid).values(password_hash=password_hash(password)))
            c.execute(delete(tokens).where(tokens.c.user_id==uid))
        print('Password reset; existing logins revoked.')
    db.close()

if __name__=='__main__':main()
