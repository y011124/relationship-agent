"""One explicitly requested, capped, synthetic live-model workflow (normally two calls)."""
import tempfile
from pathlib import Path
from dotenv import load_dotenv
from relationship_agent.beta.config import Settings
from relationship_agent.beta.database import Database
from relationship_agent.beta.auth import Auth
from relationship_agent.beta.store import ScopedStore
from relationship_agent.beta.service import Service
from relationship_agent.beta.ops import stats
import json

load_dotenv()
settings=Settings.env()
if settings.mode!='api':raise SystemExit('Configure API mode locally first; no call was made.')
# Never use real users' database for a smoke test.
with tempfile.TemporaryDirectory() as root:
 settings.database_url='sqlite:///'+root+'/smoke.db';settings.production=False
 settings.global_daily_calls=settings.user_daily_calls=4
 settings.daily_budget_usd=max(settings.request_reserve_usd*4,.01)
 db=Database(settings.database_url);auth=Auth(db,settings)
 token,_=auth.login('synthetic_live','synthetic-test-pass',register=True,adult=True,consent=True,invite=settings.invite_code)
 uid=auth.authenticate(token)['user_id'];store=ScopedStore(db,uid)
 person=store.save_person({'nickname':'小林','occupation':'设计师'})
 store.save_event(person['id'],{'text':'小林昨天提前告诉我，他因工作需要改约会时间。'})
 sid=store.create_session()['id'];svc=Service(db,settings)
 rid=svc.submit(uid,sid,'我因为小林改时间有点失落，只想聊聊。',person['id']);svc.execute(svc.claim())
 run=svc.public_run(uid,rid);report={'synthetic':True,'live_call_cap':4,'run':run,'metrics':stats(db),'human_quality_review':'pending'}
 Path('outputs').mkdir(exist_ok=True);Path('outputs/live-smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
 print(json.dumps({'status':run['status'],'model_attempts':report['metrics']['model_attempts'],'report':'outputs/live-smoke.json'},ensure_ascii=False))
 db.close()
 raise SystemExit(0 if run['status']=='complete' else 1)
