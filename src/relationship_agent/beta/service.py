"""Durable job claims, bounded model spending, and person-aware workflow execution."""
import os
import re
import time
import threading
import logging
from datetime import datetime, timezone
from sqlalchemy import select, insert, update
from .database import runs, users, quota, attempts, feedback, ident, stamp
from .store import ScopedStore, Busy, Missing
from ..engine import RelationshipAgent
from ..providers import build_model_client, ModelError
from ..demo import MockModelClient
from ..academic import AcademicSearch

PROMPT_VERSION='persona-1'

class PrivateSearch(AcademicSearch):
    def __init__(self, store):
        super().__init__()
        self.names = [name.strip() for p in store.people() for name in [p['profile']['nickname'], *re.split(r'[,，、\n]',p['profile'].get('aliases',''))] if name.strip()]

    def search(self, query, enabled=True):
        # A second, deterministic boundary after the model's de-identification instruction.
        for name in sorted(self.names, key=len, reverse=True):
            pattern = re.escape(name)
            if name.isascii(): pattern = r'(?<!\w)' + pattern + r'(?!\w)'
            query = re.sub(pattern, '', query, flags=re.I)
        query = re.sub(r'https?://\S+|\S+@\S+|\d{5,}', '', query)
        query = ' '.join(query.split())[:200]
        return super().search(query, enabled=enabled) if query else {'query':'','documents':[],'providers':[],'cached':False}

def safety_response(message,language):
    m=message.lower()
    danger=any(x in m for x in ('想自杀','准备自杀','想死','不想活了','伤害自己','威胁要打','威胁打我','正在打我','kill myself','end my life','hurt myself','threatened to hit','threatens to hurt'))
    if danger:
        return ('I hear how painful or frightening this feels. Are you in immediate danger right now? If you may hurt yourself or someone is threatening you, move to a safer place if you can, contact local emergency services, and reach a trusted person who can stay with you. We can focus on getting you through this moment.' if language=='en' else '听起来你现在承受着很大的痛苦或恐惧。你此刻是否安全、有没有马上受伤的危险？如果你可能伤害自己，或有人正在威胁你，请尽可能去安全的地方，联系当地紧急救援，并找一个信任的人陪着你。我们可以先一起把眼前这一刻撑过去。')
    harassment=any(x in m for x in ('绕过拉黑','换号骚扰','偷偷定位','跟踪他','跟踪她','bypass their block','secretly track'))
    if harassment:
        return ('It sounds difficult to sit with this uncertainty. I cannot help bypass someone’s boundaries or secretly track them. We can work on a message you do not send, or a plan for managing the urge to contact them.' if language=='en' else '这种不确定感可能很难熬。我不能帮助绕过拉黑、秘密定位或跟踪别人。我们可以先整理一段不发送的话，或一起想想如何度过特别想联系对方的时刻。')
    return None

class PersonaDemo(MockModelClient):
    def complete_json(self,stage,payload,schema=None):
        if stage=='chat':
            en=payload.get('language')=='en'
            records=[r for r in payload.get('observations',[]) if r.get('kind')=='account']
            message=payload.get('user_message','')
            if records:
                fact=records[0]['text'][:180]
                return {'reply':f'You previously recorded: “{fact}”. That is your account, and it does not tell us their motives. What feels most important about today’s situation?' if en else f'你之前确认记录过：“{fact}”。这能帮助我们理解背景，但还不能说明对方的动机。关于这次的情况，你最想让我听见的是什么？'}
            return {'reply':f'I hear that “{message[:100]}” matters to you. We can take it slowly. What would you most like to talk through?' if en else f'听到你说“{message[:100]}”，我想先了解这件事对你的影响。可以慢慢说，你现在最想聊的是哪一部分？'}
        return super().complete_json(stage,payload,schema)

class Service:
    def __init__(self,db,settings,client_factory=None):
        self.db,self.settings=db,settings
        self.client_factory=client_factory
        self.stop_event=threading.Event();self.threads=[]

    def client(self):
        if self.client_factory: return self.client_factory()
        if self.settings.mode=='mock': return PersonaDemo()
        return build_model_client('api',api_key=os.getenv('PERSONA_API_KEY') or os.getenv('GLM_API_KEY'))

    def submit(self,user_id,sid,message,person_id=None,idempotency_key=None):
        if not isinstance(message,str) or not 1<=len(message.strip())<=6000: raise ValueError('消息需1–6000字 / Invalid message length')
        store=ScopedStore(self.db,user_id,idempotency_key=idempotency_key)
        session=store.session(sid)
        if idempotency_key:
            with self.db.read() as c:
                existing=c.execute(select(runs).where(runs.c.user_id==user_id,runs.c.idempotency_key==idempotency_key)).mappings().first()
            if existing:
                if existing['input']!=message.strip() or existing['session_id']!=sid: raise ValueError('Idempotency key conflict')
                return existing['id']
        with self.db.read() as c: context_epoch=store.epoch(c)
        scope,choices=store.resolve(message,person_id)
        named_scope,all_choices=store.resolve(message,None)
        mentioned_ids=named_scope or [p['id'] for p in all_choices]
        # Never use hidden session defaults after a user clears the visible person tag.
        store.person_ids=scope
        language=session['language'];client=self.client()
        agent=RelationshipAgent(client,store)
        state={'language':language,'context':store.context(sid,query=message),'conversation':store.conversation(sid),
               'prompt_version':PROMPT_VERSION,'multi_person':len(all_choices)>1,
               'context_epoch':context_epoch,'mentioned_person_ids':mentioned_ids}
        safe=safety_response(message,language)
        if safe: state['direct_reply']=safe;state['direct_kind']='safety';state['context']=[];state['conversation']=[]
        elif choices:
            names=' / '.join(p['profile']['nickname'] for p in choices)
            state['direct_reply']=f'为了准确理解你说的是谁，这次想先聊哪一位（{names}）？请在输入框上方选择人物，我再继续。' if language=='zh' else f'To make sure I understand who you mean, who should we focus on ({names})? Choose a person above the message box.'
            state['direct_kind']='clarification';state['choices']=[{'id':p['id'],'nickname':p['profile']['nickname']} for p in choices]
            state['context']=[];state['conversation']=[]
        previous=store.latest_report(sid)
        if previous: state['previous_judgments']=previous['current_hypotheses']
        return store.create_run(sid,'auto',message.strip(),agent.config(),state)

    def claim(self):
        with self.db.tx() as c:
            # Expired leases become explicitly resumable failures, not automatically billed retries.
            c.execute(update(runs).where(runs.c.status=='running',runs.c.lease_until<stamp()).values(status='failed',error='执行中断，可恢复 / Interrupted; resume available',worker=None,finished=stamp()))
            row=c.execute(select(runs).where(runs.c.status=='queued').order_by(runs.c.created).limit(1)).mappings().first()
            if not row: return None
            worker=ident()
            c.execute(update(runs).where(runs.c.id==row['id'],runs.c.status=='queued').values(status='running',worker=worker,lease_until=stamp()+300))
            return {**dict(row),'worker':worker}

    def reserve(self,store,rid,stage):
        day=datetime.now(timezone.utc).strftime('%Y-%m-%d')
        with self.db.tx() as c:
            store.valid_job(c,rid)
            c.execute(update(runs).where(runs.c.id==rid).values(lease_until=stamp()+300))
            for key,cap in [(f'model:{day}:global',self.settings.global_daily_calls),(f'model:{day}:{store.user_id}',self.settings.user_daily_calls)]:
                row=c.execute(select(quota).where(quota.c.key==key)).mappings().first()
                calls=row['calls'] if row else 0;money=row['reserved_usd'] if row else 0
                if calls>=cap or (key.endswith(':global') and money+self.settings.request_reserve_usd>self.settings.daily_budget_usd+1e-9):
                    raise ModelError('今日模型预算已用完，请明天再试 / Daily model budget reached')
                values={'calls':calls+1,'reserved_usd':money+self.settings.request_reserve_usd}
                if row: c.execute(update(quota).where(quota.c.key==key).values(**values))
                else: c.execute(insert(quota).values(key=key,**values))
            ticket=ident()
            c.execute(insert(attempts).values(id=ticket,user_id=store.user_id,run_id=rid,stage=stage,created=stamp(),usage={},estimated_usd=None))
            return ticket

    def usage(self,store,ticket,usage):
        safe={k:v for k,v in usage.items() if k in ('prompt_tokens','completion_tokens','input_tokens','output_tokens','total_tokens') and isinstance(v,int) and v>=0}
        amount=(safe.get('prompt_tokens',safe.get('input_tokens',0))*self.settings.input_usd_per_million + safe.get('completion_tokens',safe.get('output_tokens',0))*self.settings.output_usd_per_million)/1e6
        with self.db.tx() as c:
            priced = self.settings.input_usd_per_million > 0 and self.settings.output_usd_per_million > 0
            c.execute(update(attempts).where(attempts.c.id==ticket,attempts.c.user_id==store.user_id).values(usage=safe,estimated_usd=amount if safe and priced else None))

    def execute(self,job):
        store=ScopedStore(self.db,job['user_id'],job['person_ids'],worker=job['worker'])
        try:
            with self.db.tx() as c: store.valid_job(c,job['id'])
            client=self.client()
            if hasattr(client,'before_request'):
                client.before_request=lambda stage:self.reserve(store,job['id'],stage)
                client.after_request=lambda ticket,usage:self.usage(store,ticket,usage)
            run=store.run(job['id'])
            if run['state'].get('direct_reply'):
                store.finish(run['id'],{'kind':run['state']['direct_kind'],'reply':run['state']['direct_reply'],'choices':run['state'].get('choices',[]),'is_demo':client.mode=='mock'},[])
            else:
                # Safety prompts remain active beyond the conservative preflight keyword rules.
                RelationshipAgent(client,store,PrivateSearch(store)).execute(run['id'])
        except Exception:
            try:
                current=store.run(job['id'])
                if current['status']!='failed':store.fail(job['id'],'任务未完成，可重试或重新发送 / Run failed; retry available')
            except Missing: pass
            logging.getLogger('persona').warning('job_failed run_id=%s',job['id'])

    def resume(self,user_id,rid):
        store=ScopedStore(self.db,user_id)
        config=RelationshipAgent(self.client(),store).config()
        with self.db.tx() as c:
            run=store.own(c,runs,rid)
            if run['status']=='complete':return rid
            if run['status']!='failed':raise Busy('Task is already active')
            if run['epoch']!=store.epoch(c) or run['config']!=config or run['state'].get('prompt_version')!=PROMPT_VERSION:
                raise ValueError('记忆或模型版本已变化，请重新发送 / Context changed; send again')
            if c.execute(select(runs.c.id).where(runs.c.session_id==run['session_id'],runs.c.status.in_(['queued','running']))).first():raise Busy('Chat busy')
            c.execute(update(runs).where(runs.c.id==rid,runs.c.user_id==user_id).values(status='queued',worker=None,error=None,finished=None))
        return rid

    def public_run(self,user_id,rid):
        store=ScopedStore(self.db,user_id);r=store.run(rid)
        # No frozen context, model configuration, auth details or worker internals in public trace.
        result=r['result'] or None
        if result:
            result={k:v for k,v in result.items() if k not in ('memory_used','academic_search','input','model')}
            if result.get('memory_proposal'):
                from .database import events
                with self.db.read() as c:
                    candidate=c.execute(select(events.c.status).where(events.c.id==result['memory_proposal']['id'],events.c.user_id==user_id)).scalar()
                if candidate!='pending':result.pop('memory_proposal',None)
        trace=[]
        for t in store.traces(rid):
            detail=t['detail']
            trace.append({'event':t['event'],'stage':detail.get('stage'),'elapsed_seconds':detail.get('elapsed_seconds')})
        return {k:r[k] for k in ('id','session_id','input','status','error','created','finished','person_ids')}|{'result':result,'trace':trace}

    def feedback(self,user_id,rid,category,note,consent):
        allowed={'helpful','not_helpful','wrong_person','wrong_memory','unsafe','bug'}
        if category not in allowed or len(note)>1500:raise ValueError('Invalid feedback')
        with self.db.tx() as c:
            ScopedStore(self.db,user_id).own(c,runs,rid)
            c.execute(insert(feedback).values(id=ident(),user_id=user_id,run_id=rid,category=category,note=note,consent=int(consent),created=stamp()))

    def start(self):
        def loop():
            while not self.stop_event.is_set():
                try:
                    job=self.claim()
                    if job:self.execute(job)
                    else:self.stop_event.wait(.3)
                except Exception:
                    logging.getLogger('persona').warning('worker_poll_failed')
                    self.stop_event.wait(1)
        for _ in range(self.settings.workers):
            t=threading.Thread(target=loop,daemon=True);t.start();self.threads.append(t)

    def stop(self):
        self.stop_event.set()
        for t in self.threads:t.join(timeout=2)
