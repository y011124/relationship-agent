import tempfile
import unittest
import asyncio
import sys
import os
from pathlib import Path
from sqlalchemy import select
from cryptography.fernet import Fernet, InvalidToken
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from relationship_agent.beta.database import Database, users, tokens
from relationship_agent.beta.config import Settings
from relationship_agent.beta.auth import Auth
from relationship_agent.beta.store import ScopedStore
from relationship_agent.beta.ops import backup,restore,stats,review
from relationship_agent.beta.service import Service

class OpsTests(unittest.TestCase):
 def test_encrypted_backup_restores_relations_without_login_tokens(self):
  with tempfile.TemporaryDirectory() as d:
   a=Database('sqlite:///'+d+'/a.db');auth=Auth(a,Settings());token,_=auth.login('alice','backup-password-123',register=True,adult=True,consent=True);uid=auth.authenticate(token)['user_id'];s=ScopedStore(a,uid)
   person=s.save_person({'nickname':'Synthetic person'});s.save_event(person['id'],{'text':'Synthetic event'})
   sid=s.create_session()['id'];service=Service(a,Settings());rid=service.submit(uid,sid,'hello');service.execute(service.claim())
   key=Fernet.generate_key();path=backup(a,Path(d)/'backup.enc',key)
   self.assertNotIn(b'Synthetic event',path.read_bytes())
   b=Database('sqlite:///'+d+'/b.db');restore(b,path,key)
   restored=ScopedStore(b,uid);self.assertEqual(restored.people()[0]['profile']['nickname'],'Synthetic person');self.assertEqual(restored.list_events(person['id'])[0]['text'],'Synthetic event')
   self.assertEqual(stats(b)['jobs']['complete'],1)
   with b.read() as c:self.assertEqual(c.execute(select(tokens)).all(),[])
   with self.assertRaises(ValueError):restore(b,path,key)
   a.close();b.close()
 def test_review_rejects_unconsented_conversation(self):
  with tempfile.TemporaryDirectory() as d:
   db=Database('sqlite:///'+d+'/a.db');auth=Auth(db,Settings());token,_=auth.login('alice','backup-password-123',register=True,adult=True,consent=True);uid=auth.authenticate(token)['user_id'];s=ScopedStore(db,uid);sid=s.create_session()['id'];svc=Service(db,Settings());rid=svc.submit(uid,sid,'hello');svc.execute(svc.claim());svc.feedback(uid,rid,'helpful','private note',False)
   from relationship_agent.beta.database import feedback
   with db.read() as c:fid=c.execute(select(feedback.c.id)).scalar()
   with self.assertRaises(ValueError):review(db,fid)
   self.assertNotIn('private note',str(stats(db)));db.close()
 def test_mcp_is_scoped_to_one_confirmed_person(self):
  from mcp import ClientSession, StdioServerParameters
  from mcp.client.stdio import stdio_client
  with tempfile.TemporaryDirectory() as d:
   url='sqlite:///'+d+'/a.db';db=Database(url);auth=Auth(db,Settings());token,_=auth.login('alice','backup-password-123',register=True,adult=True,consent=True);uid=auth.authenticate(token)['user_id'];s=ScopedStore(db,uid);p=s.save_person({'nickname':'Lin'});s.save_event(p['id'],{'text':'Confirmed synthetic memory'})
   other=s.save_person({'nickname':'Alex'});s.save_event(other['id'],{'text':'MUST NOT LEAK'})
   async def check():
    params=StdioServerParameters(command=sys.executable,args=['-m','relationship_agent.beta.mcp_server','--username','alice','--person-id',p['id']],env={'DATABASE_URL':url,'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'src')})
    async with stdio_client(params) as (rd,wr):
     async with ClientSession(rd,wr) as client:
      await client.initialize();tools=await client.list_tools();self.assertEqual({x.name for x in tools.tools},{'get_person_profile','search_person_events'})
      result=await client.call_tool('search_person_events',{'query':''});text=str(result)
      self.assertIn('Confirmed synthetic memory',text);self.assertNotIn('MUST NOT LEAK',text)
   asyncio.run(check());db.close()
if __name__=='__main__':unittest.main()
