"""Paired memory/no-memory evaluation. Structural results are not quality scores."""
import argparse
import json
import os
import tempfile
import time
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from persona_cases import cases
from relationship_agent.beta.config import Settings
from relationship_agent.beta.database import Database, runs
from relationship_agent.beta.auth import Auth
from relationship_agent.beta.store import ScopedStore
from relationship_agent.beta.service import Service
from relationship_agent.beta.ops import stats
from sqlalchemy import select, update

def main():
 from dotenv import load_dotenv
 load_dotenv()
 p=argparse.ArgumentParser();p.add_argument('--mode',choices=['mock','api'],default='mock');p.add_argument('--limit',type=int,default=40);p.add_argument('--max-calls',type=int,default=10);p.add_argument('--output',default='outputs/persona-eval.json');a=p.parse_args()
 if not 1<=a.max_calls<=20:raise SystemExit('max-calls must be 1–20; deliberately bound live evaluation cost')
 results=[]
 with tempfile.TemporaryDirectory() as root:
  settings=Settings(database_url='sqlite:///'+root+'/eval.sqlite',mode=a.mode,user_daily_calls=a.max_calls,global_daily_calls=a.max_calls,daily_budget_usd=1,request_reserve_usd=.05)
  db=Database(settings.database_url);auth=Auth(db,settings);svc=Service(db,settings)
  for case in cases()[:a.limit]:
   for memory_on in (False,True):
    token,_=auth.login(case['id']+('_mem' if memory_on else '_base'),'synthetic-eval-pass',register=True,adult=True,consent=True)
    user=auth.authenticate(token);store=ScopedStore(db,user['user_id'])
    person=store.save_person({'nickname':'小林' if case['language']=='zh' else 'Lin','aliases':'林同学' if case['language']=='zh' else 'Linny','occupation':'Designer'})
    store.save_person({'nickname':'阿泽' if case['language']=='zh' else 'Alex'})
    if memory_on:
     store.save_event(person['id'],{'text':'小林上周取消过一次约会。' if case['language']=='zh' else 'Lin cancelled one date last week.'})
    sid=store.create_session(language=case['language'])['id'];turns=[]
    for text in case['turns']:
     started=time.monotonic()
     rid=svc.submit(user['user_id'],sid,text)
     job=svc.claim();svc.execute(job)
     run=svc.public_run(user['user_id'],rid)
     turns.append({'input':text,'status':run['status'],'result':run['result'],'error':run['error'],'elapsed_seconds':round(time.monotonic()-started,3)})
    results.append({'id':case['id'],'variant':'person_memory' if memory_on else 'profile_only','language':case['language'],'rubric':case['rubric'],'human_scores':{'empathy':None,'groundedness':None,'usefulness':None,'person_accuracy':None},'human_review':'pending','turns':turns})
  metrics=stats(db);db.close()
 output={'mode':a.mode,'case_count':min(a.limit,len(cases())),'variant_runs':len(results),'engineering_complete':sum(all(t['status']=='complete' for t in r['turns']) for r in results),'quality_status':'NOT_EVALUATED: human review required; mock text is not model capability evidence','live_api_call_cap':a.max_calls,'metrics':metrics,'results':results}
 target=Path(a.output);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({k:v for k,v in output.items() if k!='results'},ensure_ascii=False,indent=2))
 return 0 if output['engineering_complete']==len(results) else 1
if __name__=='__main__':raise SystemExit(main())
