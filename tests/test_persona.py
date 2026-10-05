"""Real HTTP/DB boundaries; no paid calls. Also runs against disposable Postgres."""
import os
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fastapi.testclient import TestClient
from sqlalchemy import select, update, delete
from relationship_agent.beta.app import create_app
from relationship_agent.beta.config import Settings
from relationship_agent.beta.database import meta, users, tokens, runs, events, attempts, quota, feedback, stamp
from relationship_agent.beta.store import ScopedStore, Missing
from relationship_agent.beta.auth import verify
from relationship_agent.beta.service import Service, PersonaDemo, safety_response
from relationship_agent.providers import ModelError, APIClient

class PersonaTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  self.settings=Settings(database_url=os.getenv('PERSONA_TEST_DATABASE_URL','sqlite:///'+self.tmp.name+'/test.sqlite'),origin='http://testserver')
  self.app=create_app(self.settings,start_workers=False)
  self.db=self.app.state.db
  if os.getenv('PERSONA_TEST_DATABASE_URL'):
   # CI uses a dedicated disposable database. Never set this URL to production.
   with self.db.tx() as c:
    c.execute(delete(users));c.execute(delete(quota))
  self.service=self.app.state.service
  self.a=self.client('alice');self.b=self.client('bravo')
  self.aid=self.a.get('/api/me').json();self.auid=self.user_id(self.a)
 def tearDown(self):
  self.a.close();self.b.close();self.db.close();self.tmp.cleanup()
 def user_id(self,client):
  name=client.get('/api/me').json()['username']
  with self.db.read() as c:return c.execute(select(users.c.id).where(users.c.username==name)).scalar()
 def client(self,name):
  c=TestClient(self.app);c.headers['origin']='http://testserver'
  r=c.post('/api/auth/register',json={'username':name,'password':'test-password-123','consent':True,'adult':True})
  self.assertEqual(r.status_code,200,r.text);c.headers['x-csrf-token']=r.json()['csrf'];return c
 def person(self,c=None,name='小林'):
  r=(c or self.a).post('/api/people',json={'nickname':name,'occupation':'设计师','aliases':'林同学' if name=='小林' else ''})
  self.assertEqual(r.status_code,200,r.text);return r.json()['id']
 def session(self,c=None):return (c or self.a).post('/api/sessions',json={}).json()['id']
 def submit(self,text='小林昨天取消约会，我很失望。',sid=None,pid=None,c=None,key=None):
  import uuid
  r=(c or self.a).post('/api/message',json={'session_id':sid or self.session(c),'message':text,'person_id':pid,'idempotency_key':key or uuid.uuid4().hex})
  self.assertEqual(r.status_code,202,r.text);return r.json()['run_id']
 def execute(self,rid,c=None):
  job=self.service.claim();self.assertEqual(job['id'],rid);self.service.execute(job)
  r=(c or self.a).get('/api/runs/'+rid).json();self.assertEqual(r['status'],'complete',r);return r
 def event(self,pid,text='昨天取消约会',c=None):
  r=(c or self.a).post('/api/people/'+pid+'/events',json={'text':text});self.assertEqual(r.status_code,200,r.text);return r.json()['id']

 def test_password_and_cookie_security(self):
  with self.db.read() as c:
   row=c.execute(select(users).where(users.c.id==self.auid)).mappings().one()
   auth=c.execute(select(tokens).where(tokens.c.user_id==self.auid)).mappings().one()
  self.assertNotIn('test-password',row['password_hash']);self.assertTrue(verify('test-password-123',row['password_hash']))
  self.assertNotEqual(auth['digest'],self.a.cookies.get('persona_session'))
  r=self.a.post('/api/auth/login',json={'username':'alice','password':'test-password-123'})
  self.assertIn('HttpOnly',r.headers['set-cookie']);self.assertIn('SameSite=strict',r.headers['set-cookie'])
 def test_consent_invite_and_unauthenticated(self):
  c=TestClient(self.app);c.headers['origin']='http://testserver'
  self.assertEqual(c.get('/api/me').status_code,401)
  self.assertEqual(c.post('/api/auth/register',json={'username':'young','password':'test-password-123'}).status_code,400)
  self.settings.invite_code='a-long-private-invite'
  self.assertEqual(c.post('/api/auth/register',json={'username':'newperson','password':'test-password-123','adult':True,'consent':True}).status_code,400)
 def test_csrf_origin_host_and_body_limit(self):
  self.assertEqual(self.a.post('/api/people',json={'nickname':'X'},headers={'x-csrf-token':'bad'}).status_code,403)
  self.assertEqual(self.a.post('/api/people',json={'nickname':'X'},headers={'origin':'https://evil.test'}).status_code,403)
  self.assertEqual(self.a.get('/api/me',headers={'host':'evil.test'}).status_code,403)
  self.assertEqual(self.a.post('/api/people',content='x'*40001,headers={'content-type':'application/json'}).status_code,413)
 def test_auth_rate_limit(self):
  c=TestClient(self.app);c.headers['origin']='http://testserver'
  results=[c.post('/api/auth/login',json={'username':'unknown','password':'incorrect-pass'}).json() for _ in range(11)]
  self.assertIn('Too many',str(results[-1]))
 def test_profile_ownership_all_paths(self):
  pid=self.person();eid=self.event(pid)
  self.assertEqual(self.b.get('/api/people/'+pid).status_code,404)
  self.assertEqual(self.b.patch('/api/people/'+pid,json={'nickname':'hack'}).status_code,404)
  self.assertEqual(self.b.request('DELETE','/api/people/'+pid,json={}).status_code,404)
  self.assertEqual(self.b.post('/api/people/'+pid+'/events',json={'text':'hack'}).status_code,404)
  self.assertEqual(self.b.request('DELETE','/api/events/'+eid,json={}).status_code,404)
  self.assertEqual(self.b.post('/api/sessions',json={'person_id':pid}).status_code,404)
 def test_run_session_feedback_ownership(self):
  pid=self.person();sid=self.session();rid=self.submit(sid=sid,pid=pid);self.execute(rid)
  for path in ['/api/sessions/'+sid,'/api/runs/'+rid]:self.assertEqual(self.b.get(path).status_code,404)
  self.assertEqual(self.b.post('/api/runs/'+rid+'/resume',json={}).status_code,404)
  self.assertEqual(self.b.post('/api/runs/'+rid+'/feedback',json={'category':'helpful'}).status_code,404)
  self.assertEqual(self.b.post('/api/message',json={'session_id':sid,'message':'hello','idempotency_key':'1234567890123456'}).status_code,404)
  self.assertEqual(self.b.get('/api/me').json()['sessions'],[])
 def test_pending_memory_not_retrieved_until_confirmed(self):
  pid=self.person();rid=self.submit(pid=pid);result=self.execute(rid)['result'];proposal=result['memory_proposal'];store=ScopedStore(self.db,self.auid,[pid]);sid=self.session()
  self.assertEqual(len(store.context(sid)),1)
  r=self.a.patch(f'/api/people/{pid}/events/{proposal["id"]}',json={'text':proposal['text']});self.assertEqual(r.status_code,200)
  self.assertEqual(len(store.context(sid)),2)
  self.assertNotIn('memory_proposal',self.a.get('/api/runs/'+rid).json()['result'])
 def test_cross_session_person_retrieval_and_alias(self):
  p=self.person();other=self.person(name='阿泽');self.event(p,'小林送了一本书');self.event(other,'阿泽失约')
  rid=self.submit('林同学今天给我发消息了。');r=self.execute(rid)
  self.assertEqual(r['person_ids'],[p]);self.assertIn('送了一本书',r['result']['reply']);self.assertNotIn('阿泽失约',r['result']['reply'])
 def test_ambiguity_and_focus_override(self):
  p=self.person();self.person(name='阿泽')
  rid=self.submit('小林和阿泽都联系我了，他什么意思？');r=self.execute(rid)
  self.assertEqual(r['result']['kind'],'clarification');self.assertNotIn('memory_proposal',r['result'])
  rid=self.submit('小林和阿泽都联系我了。',pid=p);r=self.execute(rid);self.assertNotIn('memory_proposal',r['result'])
 def test_new_explicit_person_overrides_old_focus(self):
  p=self.person();other=self.person(name='阿泽')
  rid=self.submit('阿泽今天联系我了。',pid=p);self.assertEqual(self.execute(rid)['person_ids'],[other])
 def test_correction_excludes_stale_conversation_and_updates_retrieval(self):
  p=self.person();e=self.event(p,'小林取消了约会');sid=self.session();rid=self.submit(sid=sid,pid=p);self.execute(rid)
  self.a.patch(f'/api/people/{p}/events/{e}',json={'text':'更正：是我先改了时间'})
  store=ScopedStore(self.db,self.auid,[p]);self.assertEqual(store.conversation(sid),[])
  texts=[x['text'] for x in store.context(sid)];self.assertIn('更正：是我先改了时间',texts);self.assertNotIn('小林取消了约会',texts)
 def test_delete_event_purges_dependent_history(self):
  p=self.person();e=self.event(p,'敏感已删除内容');sid=self.session();rid=self.submit(sid=sid,pid=p);self.execute(rid)
  self.assertEqual(self.a.request('DELETE','/api/events/'+e,json={}).status_code,200)
  self.assertEqual(self.a.get('/api/sessions/'+sid).status_code,404)
  self.assertNotIn('敏感已删除内容',self.a.get('/api/export').text)
 def test_submit_rejects_context_corrected_during_preparation(self):
  p=self.person();eid=self.event(p,'旧事件');sid=self.session()
  original=ScopedStore.context
  def racing_context(store,*args,**kwargs):
   context=original(store,*args,**kwargs)
   store.save_event(p,{'text':'更正后的事件'},eid)
   return context
  with patch.object(ScopedStore,'context',racing_context):
   r=self.a.post('/api/message',json={'session_id':sid,'message':'小林之前怎么样？','idempotency_key':'context-race-123456789'})
  self.assertEqual(r.status_code,409,r.text)
  self.assertEqual(ScopedStore(self.db,self.auid).runs(sid),[])
 def test_delete_mentioned_person_purges_multi_person_conversation(self):
  a=self.person();b=self.person(name='阿泽');self.event(a,'小林的独立经历')
  sid=self.session();rid=self.submit('小林和阿泽一起联系我了。',sid=sid,pid=a);self.execute(rid)
  self.assertEqual(self.a.request('DELETE','/api/people/'+b,json={}).status_code,200)
  self.assertEqual(self.a.get('/api/sessions/'+sid).status_code,404)
  self.assertEqual(self.a.get('/api/people/'+a).json()['events'][0]['text'],'小林的独立经历')
 def test_failed_job_keeps_deletion_dependencies_after_correction(self):
  a=self.person();b=self.person(name='阿泽');sid=self.session()
  rid=self.submit('小林和阿泽一起联系我了。',sid=sid,pid=a)
  job=self.service.claim();store=ScopedStore(self.db,self.auid,worker=job['worker'])
  store.fail(rid,'synthetic interruption')
  self.event(a,'更正后的独立经历')
  self.assertNotIn('context',store.run(rid)['state'])
  self.a.request('DELETE','/api/people/'+b,json={})
  self.assertEqual(self.a.get('/api/sessions/'+sid).status_code,404)
 def test_delete_person_and_account_cascade(self):
  p=self.person();self.event(p);sid=self.session();rid=self.submit(sid=sid,pid=p);self.execute(rid)
  self.assertEqual(self.a.request('DELETE','/api/people/'+p,json={}).status_code,200)
  self.assertEqual(self.a.get('/api/runs/'+rid).status_code,404)
  self.assertEqual(self.a.request('DELETE','/api/account',json={'password':'test-password-123'}).status_code,200)
  self.assertEqual(self.a.get('/api/me').status_code,401);self.assertEqual(self.b.get('/api/me').status_code,200)
 def test_delete_conversation_removes_its_event_sources(self):
  p=self.person();sid=self.session();rid=self.submit(sid=sid,pid=p);self.execute(rid)
  self.a.request('DELETE','/api/sessions/'+sid,json={})
  self.assertEqual(self.a.get('/api/people/'+p).json()['events'],[])
 def test_busy_mutation_is_rejected(self):
  p=self.person();rid=self.submit(pid=p)
  self.assertEqual(self.a.patch('/api/people/'+p,json={'nickname':'changed'}).status_code,409)
  self.execute(rid)
 def test_idempotency_does_not_create_duplicate_event(self):
  p=self.person();sid=self.session();key='same-message-123456789';rid=self.submit(sid=sid,pid=p,key=key)
  self.assertEqual(self.submit(sid=sid,pid=p,key=key),rid);self.execute(rid)
  self.assertEqual(self.submit(sid=sid,pid=p,key=key),rid)
  self.assertEqual(len(self.a.get('/api/people/'+p).json()['events']),1)
 def test_two_users_can_have_active_jobs_and_exclusive_claims(self):
  a=self.submit('hello');b=self.submit('hello',c=self.b)
  with ThreadPoolExecutor(max_workers=2) as pool:claims=list(pool.map(lambda _:self.service.claim(),range(2)))
  self.assertEqual({j['id'] for j in claims},{a,b});self.assertIsNone(self.service.claim())
  for j in claims:self.service.execute(j)
 def test_lease_expiry_is_resumable_but_old_worker_cannot_write(self):
  rid=self.submit();job=self.service.claim()
  with self.db.tx() as c:c.execute(update(runs).where(runs.c.id==rid).values(lease_until=stamp()-1))
  self.assertIsNone(self.service.claim());self.assertEqual(self.a.get('/api/runs/'+rid).json()['status'],'failed')
  self.assertEqual(self.a.post('/api/runs/'+rid+'/resume',json={}).status_code,202)
  newer=self.service.claim();old=ScopedStore(self.db,job['user_id'],worker=job['worker'])
  with self.assertRaises(ValueError):old.checkpoint(rid,{})
  self.service.execute(newer);self.assertEqual(self.a.get('/api/runs/'+rid).json()['status'],'complete')
 def test_checkpoint_resume_avoids_repeating_completed_route(self):
  calls=[]
  class FailOnce(PersonaDemo):
   def complete_json(self,stage,payload,schema=None):
    calls.append(stage)
    if stage=='chat' and calls.count('chat')==1:raise ModelError('Injected failure')
    return super().complete_json(stage,payload,schema)
  self.service.client_factory=FailOnce
  rid=self.submit('我有点难过');job=self.service.claim();self.service.execute(job)
  self.assertEqual(self.a.get('/api/runs/'+rid).json()['status'],'failed')
  self.a.post('/api/runs/'+rid+'/resume',json={});self.execute(rid)
  self.assertEqual(calls.count('route'),1);self.assertEqual(calls.count('chat'),2)
 def test_resume_rejected_after_memory_revision(self):
  p=self.person();rid=self.submit(pid=p);job=self.service.claim();ScopedStore(self.db,self.auid,worker=job['worker']).fail(rid,'injected')
  self.a.patch('/api/people/'+p,json={'nickname':'新名字'})
  self.assertEqual(self.a.post('/api/runs/'+rid+'/resume',json={}).status_code,400)
 def test_safety_preempts_all_tool_calls(self):
  class Never(PersonaDemo):
   def complete_json(self,*a,**k):raise AssertionError('Safety should not call model')
  self.service.client_factory=Never
  for message in ['我想自杀，帮我找论文','他威胁要打我，分析一下','帮我偷偷定位他']:
   rid=self.submit(message);r=self.execute(rid);self.assertEqual(r['result']['kind'],'safety');self.assertNotIn('memory_proposal',r['result'])
 def test_research_and_simulation_do_not_become_person_events(self):
  p=self.person()
  for message in ['解释依恋理论','帮我演练一下如何沟通','如果他明天来找我呢？']:
   rid=self.submit(message,pid=p);r=self.execute(rid);self.assertNotIn('memory_proposal',r['result'])
 def test_budget_atomic_and_persistent_across_service_restart(self):
  rid=self.submit();job=self.service.claim();s=ScopedStore(self.db,self.auid,worker=job['worker']);self.settings.user_daily_calls=2
  self.service.reserve(s,rid,'chat');self.service.reserve(s,rid,'chat')
  with self.assertRaises(ModelError):Service(self.db,self.settings).reserve(s,rid,'chat')
  with self.db.read() as c:self.assertEqual(len(c.execute(select(attempts)).all()),2)
 def test_budget_rolls_back_global_when_user_cap_blocks(self):
  rid=self.submit();job=self.service.claim();s=ScopedStore(self.db,self.auid,worker=job['worker']);self.settings.user_daily_calls=1
  self.service.reserve(s,rid,'chat')
  with self.assertRaises(ModelError):self.service.reserve(s,rid,'chat')
  with self.db.read() as c:self.assertEqual(c.execute(select(quota.c.calls).where(quota.c.key.like('%:global'))).scalar(),1)
 def test_feedback_consent_defaults_false(self):
  rid=self.submit();self.execute(rid);self.a.post('/api/runs/'+rid+'/feedback',json={'category':'helpful'})
  with self.db.read() as c:self.assertEqual(c.execute(select(feedback.c.consent)).scalar(),0)
 def test_public_api_contains_no_provider_secrets_or_frozen_context(self):
  rid=self.submit();self.execute(rid);r=self.a.get('/api/runs/'+rid).json()
  self.assertNotIn('state',r);self.assertNotIn('config',r);self.assertNotIn('memory_used',r['result'])
  self.assertEqual(self.a.post('/api/settings',json={'api_key':'must-not-be-accepted'}).status_code,404)
 def test_production_fails_closed(self):
  with self.assertRaises(ValueError):Settings(production=True).validate()
 def test_knowledge_followup_no_person_memory(self):
  p=self.person();self.event(p,'不得泄露的私人事件')
  rid=self.submit('解释依恋',pid=p);r=self.execute(rid)
  self.assertNotIn('不得泄露',json.dumps(r['result'],ensure_ascii=False))

 def test_pronoun_without_focus_requires_clarification(self):
  self.person();self.person(name='阿泽');rid=self.submit('他今天没有联系我。');r=self.execute(rid)
  self.assertEqual(r['result']['kind'],'clarification');self.assertNotIn('memory_proposal',r['result'])
 def test_unknown_cost_is_not_reported_as_zero(self):
  from relationship_agent.beta.ops import stats
  rid=self.submit();job=self.service.claim();store=ScopedStore(self.db,self.auid,worker=job['worker'])
  ticket=self.service.reserve(store,rid,'chat');self.service.usage(store,ticket,{'prompt_tokens':100,'completion_tokens':20})
  self.assertIsNone(stats(self.db)['estimated_model_usd'])
 def test_model_http_retries_share_persistent_budget(self):
  import io,urllib.error
  rid=self.submit();job=self.service.claim();store=ScopedStore(self.db,self.auid,worker=job['worker'])
  client=APIClient(api_key='synthetic-fixture',protocol='chat-completions')
  client.before_request=lambda stage:self.service.reserve(store,rid,stage)
  client.after_request=lambda ticket,usage:self.service.usage(store,ticket,usage)
  class Response:
   def __enter__(self):return self
   def __exit__(self,*a):pass
   def read(self,*a):return json.dumps({'choices':[{'message':{'content':'{"reply":"hello"}'}}],'usage':{'prompt_tokens':12,'completion_tokens':4}}).encode()
  class Opener:
   calls=0
   def open(self,*a,**k):
    self.calls+=1
    if self.calls==1:raise urllib.error.HTTPError('https://fixture.test',503,'',{},io.BytesIO())
    return Response()
  with patch('urllib.request.build_opener',return_value=Opener()),patch('time.sleep'):
   self.assertEqual(client.complete_json('chat',{'language':'en','user_message':'hello'})['reply'],'hello')
  with self.db.read() as c:self.assertEqual(len(c.execute(select(attempts)).all()),2)
 def test_search_scrubs_known_names_before_external_transport(self):
  from relationship_agent.beta.service import PrivateSearch
  pid=self.person(name='Alice')
  service=PrivateSearch(ScopedStore(self.db,self.auid))
  captured=[]
  with patch('relationship_agent.academic.AcademicSearch.search',side_effect=lambda query,enabled=True:captured.append(query) or {}):
   service.search('Alice attachment uncertainty person@example.com 18888888888')
  self.assertEqual(captured,['attachment uncertainty'])
 def test_invalid_budgets_fail_closed(self):
  for x in (float('nan'),float('inf'),-1):
   with self.assertRaises(ValueError):Settings(daily_budget_usd=x).validate()

if __name__=='__main__':unittest.main()
