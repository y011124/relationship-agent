"""Tenant-scoped repository and adapter for the existing checkpointed engine."""
import json
import re
from sqlalchemy import select, insert, update, delete, and_
from .database import (users, people, sessions, runs, events, memories, traces, feedback, ident, stamp)

class Missing(ValueError): pass
class Busy(ValueError): pass

def data(row): return dict(row) if row else None

def public_profile(value):
    allowed = {'nickname','aliases','relationship','age','height','occupation','zodiac','background','impression'}
    if not isinstance(value, dict) or set(value)-allowed: raise ValueError('Invalid profile fields')
    profile = {key:str(value.get(key,'')).strip() for key in allowed}
    if not profile['nickname'] or len(profile['nickname']) > 40: raise ValueError('昵称需1–40字 / Nickname required')
    if any(len(v)>600 for v in profile.values()) or len(profile['aliases'])>120: raise ValueError('Profile too long')
    return profile

class ScopedStore:
    def __init__(self, db, user_id, person_ids=None, worker=None, idempotency_key=None):
        self.db, self.user_id = db, user_id
        self.person_ids = person_ids or []
        self.worker, self.idempotency_key = worker, idempotency_key

    def own(self, c, table, record_id):
        row = c.execute(select(table).where(table.c.id==record_id,table.c.user_id==self.user_id)).mappings().first()
        if not row: raise Missing('记录不存在 / Record not found')
        return dict(row)

    def epoch(self,c):
        row=c.execute(select(users.c.epoch).where(users.c.id==self.user_id)).first()
        if not row: raise Missing('Account not found')
        return row[0]

    def idle(self,c):
        if c.execute(select(runs.c.id).where(runs.c.user_id==self.user_id,runs.c.status.in_(['queued','running']))).first():
            raise Busy('请等待当前任务完成再修改记忆 / Wait for your active tasks')

    def invalidate(self,c):
        c.execute(update(users).where(users.c.id==self.user_id).values(epoch=users.c.epoch+1))
        # Failed jobs retain snapshots; they may no longer be resumed after an edit.
        failed=c.execute(select(runs.c.id,runs.c.state).where(runs.c.user_id==self.user_id,runs.c.status=='failed')).mappings().all()
        for run in failed:
            # Retain only deletion dependencies; frozen message/context must be discarded.
            state={'mentioned_person_ids':(run['state'] or {}).get('mentioned_person_ids',[])}
            c.execute(update(runs).where(runs.c.id==run['id'],runs.c.user_id==self.user_id).values(state=state,error='记忆已修改，请重新发送 / Memory changed; send again'))

    def people(self):
        with self.db.read() as c:
            return [dict(r) for r in c.execute(select(people).where(people.c.user_id==self.user_id).order_by(people.c.created)).mappings()]

    def person(self,pid):
        with self.db.read() as c: return self.own(c,people,pid)

    def save_person(self, profile, pid=None):
        profile=public_profile(profile)
        with self.db.tx() as c:
            self.idle(c)
            if pid:
                self.own(c,people,pid)
                c.execute(update(people).where(people.c.id==pid,people.c.user_id==self.user_id).values(profile=profile))
                self.invalidate(c)
            else:
                count=len(c.execute(select(people.c.id).where(people.c.user_id==self.user_id)).all())
                if count>=50: raise ValueError('人物数量上限50 / Person limit reached')
                pid=ident()
                c.execute(insert(people).values(id=pid,user_id=self.user_id,profile=profile,created=stamp()))
        return self.person(pid)

    def purge_person_context(self,c,pid):
        # Strong deletion: remove conversations that contain this person's input or derived output.
        affected={r['session_id'] for r in c.execute(select(runs).where(runs.c.user_id==self.user_id)).mappings()
                  if pid in (r['person_ids'] or []) or pid in (r['state'] or {}).get('mentioned_person_ids',[])}
        affected.update(c.execute(select(sessions.c.id).where(sessions.c.user_id==self.user_id,sessions.c.person_id==pid)).scalars())
        if affected: c.execute(delete(sessions).where(sessions.c.user_id==self.user_id,sessions.c.id.in_(affected)))
        self.invalidate(c)

    def delete_person(self,pid):
        with self.db.tx() as c:
            self.idle(c); self.own(c,people,pid)
            self.purge_person_context(c,pid)
            c.execute(delete(people).where(people.c.id==pid,people.c.user_id==self.user_id))

    def resolve(self,message,selected=None):
        all_people=self.people()
        if selected: self.person(selected)
        matched=[]
        for person in all_people:
            names=[person['profile']['nickname']]+re.split(r'[,，、\n]',person['profile'].get('aliases',''))
            for name in filter(None,(n.strip() for n in names)):
                pattern = re.escape(name)
                if name.isascii(): pattern=r'(?<!\w)'+pattern+r'(?!\w)'
                if re.search(pattern,message,re.I):
                    matched.append(person['id']); break
        # Multiple named people require an explicit focus choice; never silently attach an event.
        if len(matched)>1:
            if selected in matched: return [selected], []
            return [], [p for p in all_people if p['id'] in matched]
        if not matched and not selected and all_people and re.search(r'他|她|\b(he|she|him|her|they|them)\b', message, re.I):
            return [], all_people
        return matched or ([selected] if selected else []), []

    def list_events(self,pid):
        with self.db.read() as c:
            self.own(c,people,pid)
            return [dict(r) for r in c.execute(select(events).where(events.c.user_id==self.user_id,events.c.person_id==pid,events.c.status!='rejected').order_by(events.c.created.desc())).mappings()]

    def save_event(self,pid,payload,eid=None):
        text=str(payload.get('text','')).strip()
        kind=payload.get('kind','account')
        status=payload.get('status','confirmed')
        if not 1<=len(text)<=3000 or kind not in ('account','feeling','impression') or status not in ('confirmed','rejected'):
            raise ValueError('Invalid memory')
        occurred=str(payload.get('occurred_at','')).strip()
        if len(occurred)>64: raise ValueError('Invalid date')
        with self.db.tx() as c:
            self.idle(c); self.own(c,people,pid)
            if eid:
                previous=self.own(c,events,eid)
                if previous['person_id']!=pid: raise Missing('Memory not found')
                c.execute(update(events).where(events.c.id==eid,events.c.user_id==self.user_id).values(text=text,kind=kind,status=status,occurred_at=occurred))
                # Exclude stale transcript/checkpoints from subsequent model context.
                self.invalidate(c)
            else:
                eid=ident()
                c.execute(insert(events).values(id=eid,user_id=self.user_id,person_id=pid,run_id=None,quote=text,text=text,kind=kind,status=status,occurred_at=occurred,created=stamp()))
                self.invalidate(c)
        return eid

    def delete_event(self,eid):
        with self.db.tx() as c:
            self.idle(c); old=self.own(c,events,eid)
            self.purge_person_context(c,old['person_id'])
            c.execute(delete(events).where(events.c.id==eid,events.c.user_id==self.user_id))

    def create_session(self,title='',mode='mock',language='zh',person_id=None):
        if language not in ('zh','en'): raise ValueError('Invalid language')
        with self.db.tx() as c:
            if person_id: self.own(c,people,person_id)
            sid=ident()
            c.execute(insert(sessions).values(id=sid,user_id=self.user_id,title=(title.strip() or '新对话 / New chat')[:100],language=language,person_id=person_id,created=stamp()))
        return self.session(sid)

    def session(self,sid):
        with self.db.read() as c: return self.own(c,sessions,sid)

    def sessions(self):
        with self.db.read() as c: return [dict(x) for x in c.execute(select(sessions).where(sessions.c.user_id==self.user_id).order_by(sessions.c.created.desc())).mappings()]

    def delete_session(self,sid):
        with self.db.tx() as c:
            self.idle(c); self.own(c,sessions,sid)
            # Source-linked memories also removed when deleting their source conversation.
            ids=select(runs.c.id).where(runs.c.user_id==self.user_id,runs.c.session_id==sid)
            c.execute(delete(events).where(events.c.user_id==self.user_id,events.c.run_id.in_(ids)))
            c.execute(delete(sessions).where(sessions.c.id==sid,sessions.c.user_id==self.user_id))
            self.invalidate(c)

    def create_run(self,sid,kind,message,config,state=None):
        with self.db.tx() as c:
            self.own(c,sessions,sid)
            if self.idempotency_key:
                old=c.execute(select(runs).where(runs.c.user_id==self.user_id,runs.c.idempotency_key==self.idempotency_key)).mappings().first()
                if old:
                    if old['session_id']!=sid or old['input']!=message: raise ValueError('Idempotency key reused for different input')
                    return old['id']
            if c.execute(select(runs.c.id).where(runs.c.session_id==sid,runs.c.status.in_(['queued','running']))).first(): raise Busy('此对话正在回复 / This chat is busy')
            if len(c.execute(select(runs.c.id).where(runs.c.user_id==self.user_id,runs.c.status.in_(['queued','running']))).all())>=3: raise Busy('最多同时提交3个任务 / Too many active requests')
            for pid in self.person_ids: self.own(c,people,pid)
            if (state or {}).get('context_epoch',self.epoch(c))!=self.epoch(c):
                raise Busy('准备消息期间记忆发生变化，请重试 / Memory changed while preparing; please retry')
            rid=ident()
            c.execute(insert(runs).values(id=rid,user_id=self.user_id,session_id=sid,kind=kind,input=message,config=config,state=state or {},status='queued',created=stamp(),epoch=self.epoch(c),person_ids=self.person_ids,idempotency_key=self.idempotency_key,lease_until=0))
        return rid

    def run(self,rid):
        with self.db.read() as c: return self.own(c,runs,rid)
    def runs(self,sid):
        with self.db.read() as c:
            self.own(c,sessions,sid)
            return [dict(r) for r in c.execute(select(runs).where(runs.c.user_id==self.user_id,runs.c.session_id==sid).order_by(runs.c.created)).mappings()]

    def valid_job(self,c,rid):
        run=self.own(c,runs,rid)
        if run['epoch']!=self.epoch(c): raise ValueError('记忆已更新，请重新发送 / Memory changed')
        if self.worker and (run['worker']!=self.worker or run['lease_until']<stamp() or run['status']!='running'):
            raise ValueError('Execution lease lost')
        return run

    def checkpoint(self,rid,state):
        with self.db.tx() as c:
            self.valid_job(c,rid)
            c.execute(update(runs).where(runs.c.id==rid,runs.c.user_id==self.user_id).values(state=state,lease_until=stamp()+300))
    def fail(self,rid,error):
        with self.db.tx() as c:
            run=self.own(c,runs,rid)
            if self.worker and run['worker']!=self.worker: return
            c.execute(update(runs).where(runs.c.id==rid,runs.c.user_id==self.user_id).values(status='failed',error=error[:200],finished=stamp()))
    def trace(self,rid,event,detail=None):
        with self.db.tx() as c:
            self.own(c,runs,rid)
            c.execute(insert(traces).values(id=ident(),user_id=self.user_id,run_id=rid,event=event,detail=detail or {},created=stamp()))
    def traces(self,rid):
        with self.db.read() as c:
            self.own(c,runs,rid)
            return [dict(r) for r in c.execute(select(traces).where(traces.c.user_id==self.user_id,traces.c.run_id==rid).order_by(traces.c.created)).mappings()]

    def finish(self,rid,result,records):
        with self.db.tx() as c:
            run=self.valid_job(c,rid)
            if run['status']=='complete': return
            for layer,kind,content in records:
                if layer not in ('observation','inference','simulation'): raise ValueError('Invalid memory layer')
                c.execute(insert(memories).values(id=ident(),user_id=self.user_id,session_id=run['session_id'],run_id=rid,layer=layer,kind=kind,content=content,created=stamp()))
            result={**result,'person_ids':run['person_ids']}
            # This is a verbatim candidate user account, NOT extracted/verified fact.
            # Questions, research, ambiguous multi-person messages and rehearsals aren't auto-proposed.
            if len(run['person_ids'] or [])==1 and result.get('kind') in ('chat','analysis','feedback') and not any(x in run['input'] for x in ('？','?','演练','假设','如果','rehearse','what if')):
                pid=run['person_ids'][0]
                if not run['state'].get('multi_person'):
                    eid=ident()
                    c.execute(insert(events).values(id=eid,user_id=self.user_id,person_id=pid,run_id=rid,quote=run['input'],text=run['input'][:3000],occurred_at='',kind='account',status='pending',created=stamp()))
                    result['memory_proposal']={'id':eid,'person_id':pid,'text':run['input'][:3000],'kind':'account'}
            c.execute(update(runs).where(runs.c.id==rid,runs.c.user_id==self.user_id).values(status='complete',result=result,error=None,finished=stamp()))

    def context(self,sid,max_chars=6000,query=''):
        self.session(sid)
        selected=[]; used=0
        with self.db.read() as c:
            for pid in self.person_ids:
                p=self.own(c,people,pid)
                profile={'id':pid,'person_id':pid,'source':'user_profile_unverified','text':json.dumps(p['profile'],ensure_ascii=False)}
                cost=len(json.dumps(profile,ensure_ascii=False))
                if used+cost<=max_chars: selected.append(profile); used+=cost
            rows=c.execute(select(events).where(events.c.user_id==self.user_id,events.c.person_id.in_(self.person_ids),events.c.status=='confirmed').order_by(events.c.created.desc())).mappings().all() if self.person_ids else []
        words=set(re.findall(r'[a-z]{2,}|[\u4e00-\u9fff]{2}',query.lower()))
        rows=sorted(rows,key=lambda r:(sum(w in r['text'].lower() for w in words),r['created']),reverse=True)
        for r in rows:
            item={'id':r['id'],'person_id':r['person_id'],'source':'user_report_unverified','kind':r['kind'],'text':r['text'],'occurred_at':r['occurred_at']}
            cost=len(json.dumps(item,ensure_ascii=False))
            if used+cost>max_chars: continue
            selected.append(item); used+=cost
            if len(selected)>=10: break
        return selected

    def conversation(self,sid,budget=8500):
        rows=self.runs(sid)
        with self.db.read() as c: epoch=self.epoch(c)
        pairs=[]; used=0
        for r in reversed(rows):
            if r['status']!='complete' or r['epoch']!=epoch or sorted(r['person_ids'] or [])!=sorted(self.person_ids): continue
            result=r['result'] or {}
            # Generated analysis/rehearsal is excluded from chat history to avoid fact contamination.
            if result.get('kind') not in ('chat','knowledge','evidence'): continue
            reply=result.get('reply') or result.get('answer','')
            pair=[{'role':'user','content':r['input']},{'role':'assistant','content':reply}]
            cost=len(json.dumps(pair,ensure_ascii=False))
            if used+cost>budget: break
            pairs.append(pair);used+=cost
            if len(pairs)>=12: break
        return [m for pair in reversed(pairs) for m in pair]

    def latest_report(self,sid):
        with self.db.read() as c: epoch=self.epoch(c)
        for r in reversed(self.runs(sid)):
            if r['epoch']==epoch and r['status']=='complete' and sorted(r['person_ids'] or [])==sorted(self.person_ids) and (r['result'] or {}).get('kind') in ('analysis','feedback'): return r['result']
        return None

    def delete_account(self):
        with self.db.tx() as c:
            self.idle(c)
            c.execute(delete(users).where(users.c.id==self.user_id))

    def export(self):
        with self.db.read() as c:
            return {t.name:[dict(r) for r in c.execute(select(t).where(t.c.user_id==self.user_id)).mappings()] for t in (people,sessions,runs,events,feedback)}
