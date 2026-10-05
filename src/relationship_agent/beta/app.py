"""Authenticated Persona AI HTTP application. No user-facing model configuration."""
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
import secrets
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select
from .config import Settings
from .database import Database, users
from .auth import Auth, AccessError, verify
from .store import ScopedStore, Missing, Busy
from .service import Service

ASSETS=Path(__file__).resolve().parents[1]/'persona_web'
class Payload(BaseModel):
    model_config=ConfigDict(extra='forbid')
class Credentials(Payload):
    username:str=Field(min_length=3,max_length=40)
    password:str=Field(min_length=12,max_length=128)
    invite:str=Field(default='',max_length=200)
    consent:bool=False
    adult:bool=False
class SessionInput(Payload):
    title:str=Field(default='',max_length=100)
    language:str='zh'
    person_id:str|None=None
class Message(Payload):
    session_id:str=Field(max_length=64)
    message:str=Field(min_length=1,max_length=6000)
    person_id:str|None=None
    idempotency_key:str=Field(min_length=16,max_length=64)
class Person(Payload):
    nickname:str=Field(min_length=1,max_length=40)
    aliases:str=Field(default='',max_length=120)
    relationship:str=Field(default='',max_length=100)
    age:str=Field(default='',max_length=30)
    height:str=Field(default='',max_length=30)
    occupation:str=Field(default='',max_length=100)
    zodiac:str=Field(default='',max_length=50)
    background:str=Field(default='',max_length=600)
    impression:str=Field(default='',max_length=600)
class Memory(Payload):
    text:str=Field(min_length=1,max_length=3000)
    kind:str='account'
    status:str='confirmed'
    occurred_at:str=Field(default='',max_length=64)
class Feedback(Payload):
    category:str
    note:str=Field(default='',max_length=1500)
    consent:bool=False
class Password(Payload):
    password:str=Field(min_length=12,max_length=128)


def create_app(settings=None,client_factory=None,start_workers=True):
    settings=settings or Settings.env();settings.validate()
    db=Database(settings.database_url);auth=Auth(db,settings);service=Service(db,settings,client_factory)
    @asynccontextmanager
    async def lifespan(app):
        if start_workers:service.start()
        yield
        service.stop()
    app=FastAPI(title='Persona AI',version='0.3.0',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.state.db=db;app.state.service=service;app.state.settings=settings

    @app.middleware('http')
    async def boundaries(request,call_next):
        expected=urlsplit(settings.origin).netloc
        if request.headers.get('host')!=expected:
            # Health checks carry no data and may use an internal host.
            if request.url.path not in ('/healthz','/readyz'):return JSONResponse({'error':'Invalid host'},403)
        if request.method not in ('GET','HEAD','OPTIONS'):
            if request.headers.get('origin')!=settings.origin:return JSONResponse({'error':'Invalid origin'},403)
            if not request.headers.get('content-type','').startswith('application/json'):
                return JSONResponse({'error':'JSON required'},415)
            chunks=[];size=0
            async for chunk in request.stream():
                size+=len(chunk)
                if size>40000:return JSONResponse({'error':'Request too large'},413)
                chunks.append(chunk)
            request._body=b''.join(chunks)
        try:response=await call_next(request)
        except Exception:
            # Exceptions must not echo user content, SQL bindings, provider errors or secrets.
            import logging
            logging.getLogger('persona').error('request_failed path=%s',request.url.path.split('/')[1:3])
            return JSONResponse({'error':'服务暂时不可用 / Service unavailable'},503)
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if settings.production:response.headers['Strict-Transport-Security']='max-age=31536000'
        return response

    @app.exception_handler(Missing)
    async def missing(req,exc):return JSONResponse({'error':str(exc)},404)
    @app.exception_handler(Busy)
    async def busy(req,exc):return JSONResponse({'error':str(exc)},409)
    @app.exception_handler(ValueError)
    async def invalid(req,exc):return JSONResponse({'error':str(exc)[:200]},400)
    from fastapi.exceptions import RequestValidationError
    @app.exception_handler(RequestValidationError)
    async def validation(req,exc):return JSONResponse({'error':'输入格式或长度不符合要求 / Invalid input'},422)

    def current(request:Request):
        try:user=auth.authenticate(request.cookies.get('persona_session',''))
        except AccessError:raise HTTPException(401,'请登录 / Please sign in')
        if request.method not in ('GET','HEAD') and not secrets.compare_digest(request.headers.get('x-csrf-token',''),user['csrf']):
            raise HTTPException(403,'Invalid CSRF token')
        return user
    def store(user):return ScopedStore(db,user['user_id'])

    @app.get('/')
    def index():return FileResponse(ASSETS/'index.html')
    @app.get('/app.js')
    def js():return FileResponse(ASSETS/'app.js',media_type='text/javascript')
    @app.get('/style.css')
    def css():return FileResponse(ASSETS/'style.css',media_type='text/css')
    @app.get('/healthz')
    def health():return {'status':'ok','version':'0.3.0'}
    @app.get('/readyz')
    def ready():
        with db.read() as c:c.execute(select(1))
        return {'status':'ready'}
    @app.get('/api/public')
    def public():return {'name':'Persona AI','mode':settings.mode,'invite_required':bool(settings.invite_code),'provider':settings.provider_label,'privacy_contact':settings.privacy_contact,'consent_version':'2026-10-v1'}

    @app.post('/api/auth/{action}')
    def sign_in(action:str,payload:Credentials,request:Request):
        if action not in ('login','register'):raise HTTPException(404)
        try:
            auth.throttle(request.client.host if request.client else 'unknown',payload.username.lower())
            token,csrf=auth.login(**payload.model_dump(),register=action=='register')
        except AccessError as exc:raise HTTPException(400,str(exc))
        response=JSONResponse({'csrf':csrf})
        response.set_cookie('persona_session',token,httponly=True,secure=settings.production,samesite='strict',max_age=7*86400,path='/')
        return response
    @app.post('/api/logout')
    def logout(request:Request,user=Depends(current)):
        auth.logout(request.cookies.get('persona_session',''))
        r=JSONResponse({'ok':True});r.delete_cookie('persona_session',path='/');return r
    @app.get('/api/me')
    def me(user=Depends(current)):
        return {'username':user['username'],'csrf':user['csrf'],'sessions':store(user).sessions(),'people':store(user).people()}
    @app.delete('/api/account')
    def delete_account(payload:Password,user=Depends(current)):
        with db.read() as c:hashed=c.execute(select(users.c.password_hash).where(users.c.id==user['user_id'])).scalar()
        if not verify(payload.password,hashed):raise HTTPException(400,'密码错误 / Invalid password')
        store(user).delete_account()
        r=JSONResponse({'ok':True});r.delete_cookie('persona_session',path='/');return r
    @app.get('/api/export')
    def export(user=Depends(current)):
        return JSONResponse(store(user).export(),headers={'Content-Disposition':'attachment; filename="persona-export.json"'})
    @app.get('/api/people')
    def list_people(user=Depends(current)):return store(user).people()
    @app.post('/api/people')
    def add_person(payload:Person,user=Depends(current)):return store(user).save_person(payload.model_dump())
    @app.get('/api/people/{pid}')
    def get_person(pid:str,user=Depends(current)):return {'person':store(user).person(pid),'events':store(user).list_events(pid)}
    @app.patch('/api/people/{pid}')
    def edit_person(pid:str,payload:Person,user=Depends(current)):return store(user).save_person(payload.model_dump(),pid)
    @app.delete('/api/people/{pid}')
    def remove_person(pid:str,user=Depends(current)):
        store(user).delete_person(pid);return {'ok':True}
    @app.post('/api/people/{pid}/events')
    def add_event(pid:str,payload:Memory,user=Depends(current)):return {'id':store(user).save_event(pid,payload.model_dump())}
    @app.patch('/api/people/{pid}/events/{eid}')
    def edit_event(pid:str,eid:str,payload:Memory,user=Depends(current)):return {'id':store(user).save_event(pid,payload.model_dump(),eid)}
    @app.delete('/api/events/{eid}')
    def remove_event(eid:str,user=Depends(current)):
        store(user).delete_event(eid);return {'ok':True}
    @app.post('/api/sessions')
    def add_session(payload:SessionInput,user=Depends(current)):return store(user).create_session(**payload.model_dump())
    @app.get('/api/sessions/{sid}')
    def get_session(sid:str,user=Depends(current)):
        s=store(user);session=s.session(sid)
        return {'session':session,'runs':[service.public_run(user['user_id'],r['id']) for r in s.runs(sid)]}
    @app.delete('/api/sessions/{sid}')
    def remove_session(sid:str,user=Depends(current)):
        store(user).delete_session(sid);return {'ok':True}
    @app.post('/api/message',status_code=202)
    def message(payload:Message,user=Depends(current)):
        return {'run_id':service.submit(user['user_id'],payload.session_id,payload.message,payload.person_id,payload.idempotency_key)}
    @app.get('/api/runs/{rid}')
    def get_run(rid:str,user=Depends(current)):return service.public_run(user['user_id'],rid)
    @app.post('/api/runs/{rid}/resume',status_code=202)
    def resume(rid:str,user=Depends(current)):return {'run_id':service.resume(user['user_id'],rid)}
    @app.post('/api/runs/{rid}/feedback')
    def rate(rid:str,payload:Feedback,user=Depends(current)):
        service.feedback(user['user_id'],rid,**payload.model_dump());return {'ok':True}
    return app


def main():
    import argparse
    import uvicorn
    from dotenv import load_dotenv
    load_dotenv()
    parser=argparse.ArgumentParser(description='Persona AI invite beta')
    parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=int(__import__('os').getenv('PORT','8770')))
    args=parser.parse_args()
    settings=Settings.env()
    if not settings.production and args.host not in ('127.0.0.1','localhost'):
        raise SystemExit('Local demo must listen on loopback; configure production for public access')
    print(f'Persona AI: {settings.origin} ({settings.mode})',flush=True)
    uvicorn.run(create_app(settings),host=args.host,port=args.port,access_log=False)

if __name__=='__main__':main()
