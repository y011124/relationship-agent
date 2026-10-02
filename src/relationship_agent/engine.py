"""A bounded, checkpointed harness workflow, not an unconstrained autonomous agent."""
from __future__ import annotations
import time

from .schemas import validate_stage, SCHEMAS
from .storage import Store
from .knowledge import search as search_knowledge
from .academic import AcademicSearch


def _needs_empathy(message, reply):
    """Small guardrail for explicit feelings; it does not infer hidden emotions."""
    message = message.lower()
    reply = reply.lower()
    feelings = ("焦虑", "难过", "害怕", "担心", "生气", "委屈", "孤单", "不安",
                "anxious", "sad", "afraid", "worried", "angry", "hurt", "lonely")
    if not any(word in message for word in feelings):
        return False
    acknowledgements = ("听起来", "听到你", "理解", "感到", "感觉", "难受", "不容易", "辛苦", "陪你", "正常", "合理",
                        "你现在", "it sounds", "i hear", "i understand", "that sounds", "must feel", "hard", "difficult",
                        "exhausting", "with you")
    return not any(marker in reply for marker in acknowledgements)


def _empathy_fallback(message, language):
    if language == "en":
        return {"reply": f"It sounds like this is weighing on you, especially when you say “{message[:120]}”. We do not have to solve it immediately; what feels hardest right now?"}
    emotion = next((word for word in ("焦虑", "难过", "害怕", "担心", "生气", "委屈", "孤单", "不安") if word in message), "难受")
    return {"reply": f"听起来你现在因为“{emotion}”真的很不好受。我先陪你停在这里，不急着解决；此刻最压着你的是什么？"}


class RelationshipAgent:
    def __init__(self, client, store: Store, academic=None):
        self.client, self.store = client, store
        self.academic = academic or AcademicSearch()

    def config(self):
        return {"mode": self.client.mode, "model": self.client.model,
                "protocol": self.client.protocol, "base_url": self.client.base_url}

    def start(self, session_id, message, kind="analysis"):
        if not isinstance(message, str) or not message.strip() or len(message) > 6000:
            raise ValueError("输入须为 1–6000 字符 / Input must contain 1–6000 characters")
        session = self.store.session(session_id)
        if session["mode"] != self.client.mode:
            raise ValueError("请为当前模式创建新会话 / Create a new session for this mode")
        if kind not in {"analysis", "feedback", "chat", "knowledge", "auto", "evidence"}:
            raise ValueError("Invalid run kind")
        state = {"language": session["language"], "context": self.store.context(session_id)}
        if kind in {"auto", "evidence"}:
            state["conversation"] = self.store.conversation(session_id)
        if kind == "chat":
            state["conversation"] = self.store.conversation(session_id)
            state["context"] = self.store.context(session_id, max_chars=3000)
        elif kind == "knowledge":
            state["context"] = []
            state["retrieved"] = search_knowledge(message, language=session["language"])
        previous = self.store.latest_report(session_id)
        if kind == "feedback":
            if not previous:
                raise ValueError("请先完成分析 / Complete an analysis before feedback")
            state["hypotheses"] = previous["current_hypotheses"]
        elif previous:
            state["previous_judgments"] = previous["current_hypotheses"]
        run_id = self.store.create_run(session_id, kind, message.strip(), self.config(), state)
        self.store.trace(run_id, "retrieve_observations", {"record_ids": [r["id"] for r in state["context"]], "context_chars": len(str(state["context"]))})
        if kind == "knowledge":
            self.store.trace(run_id, "knowledge_retrieved", {"document_ids": [d["id"] for d in state["retrieved"]]})
        return run_id

    def execute(self, run_id):
        run = self.store.run(run_id)
        if run["status"] == "complete":
            return run["result"]
        if run["config"] != self.config():
            raise ValueError("恢复时请使用相同模型配置；Key 可以更换 / Resume needs the same model configuration")
        state, message = run["state"], run["input"]
        common = {"language": state["language"]}

        def stage(name, payload):
            if name in state:
                return state[name]
            self.store.trace(run_id, "stage_started", {"stage": name})
            started = time.monotonic()
            payload = {**common, **payload}
            value = validate_stage(name, self.client.complete_json(name, payload, SCHEMAS[name]), payload)
            state[name] = value
            self.store.checkpoint(run_id, state)
            self.store.trace(run_id, "stage_completed", {"stage": name, "elapsed_seconds": round(time.monotonic()-started, 3), "usage": getattr(self.client, "last_usage", {})})
            return value

        try:
            if run["kind"] == "auto":
                previous = self.store.latest_report(run["session_id"])
                routing = stage("route", {"user_message": message, "conversation": state["conversation"],
                                           "has_report": bool(previous)})
                run["kind"] = routing["intent"]
                if run["kind"] == "feedback":
                    state["hypotheses"] = previous["current_hypotheses"]
                elif run["kind"] == "knowledge":
                    state["context"] = []
                    if "retrieved" not in state:
                        state["retrieved"] = search_knowledge(message, language=state["language"])
                        if not state["retrieved"] and any(x in message.lower() for x in ("它", "这个", "这种", "that", "this", "it ")):
                            query = " ".join(x["content"] for x in state["conversation"][-4:] if x["role"] == "user")
                            state["retrieved"] = search_knowledge(query, language=state["language"])
                        self.store.trace(run_id, "knowledge_retrieved", {"document_ids": [d["id"] for d in state["retrieved"]]})
                self.store.checkpoint(run_id, state)
            if run["kind"] == "evidence":
                state["context"] = []
                query = stage("academic_query", {"user_message": message, "conversation": state.get("conversation", [])})['query']
                if query and 'academic_search' not in state:
                    self.store.trace(run_id, 'academic_search_started')
                    state['academic_search'] = self.academic.search(query, enabled=self.client.mode == 'api')
                    self.store.checkpoint(run_id, state)
                    self.store.trace(run_id, 'academic_search_completed', {'providers': state['academic_search']['providers'], 'cached': state['academic_search']['cached']})
                search = state.get('academic_search', {'query': '', 'documents': [], 'providers': []})
                evidence = [d for d in search['documents'] if d['text'] and d['evidence_level'] != 'metadata_only']
                if evidence:
                    response = stage('knowledge', {'user_message': message, 'retrieved': evidence, 'conversation': [], 'search_status': search['providers'], 'academic': True})
                    citations = []
                    for source in response['sources']:
                        doc = next(d for d in evidence if d['title'] == source['title'] and d['source'] == source['source'] and source['snippet'] in d['text'])
                        citations.append({**source, **{k: doc[k] for k in ('url', 'year', 'authors', 'doi', 'evidence_level', 'found_in')}})
                    answer = response['answer']
                else:
                    en = state['language'] == 'en'
                    answer = ('Which topic would you like research sources for?' if en else '你希望查哪一个观点或主题的研究来源？') if not query else ('No usable research text was retrieved. See each provider’s status below; this is not evidence that no research exists.' if en else '这次没有取得可用于回答的研究文本。下方显示各平台的检索状态；这不代表相关研究不存在。')
                    citations = []
                result = {'kind': 'evidence', 'answer': answer, 'sources': citations, 'academic_search': search}
                records = [('observation', 'knowledge_input', {'text': message, 'source': 'user_report_unverified'}),
                           ('inference', 'academic_answer', {'answer': answer, 'sources': citations})]
            elif run["kind"] == "knowledge":
                response = stage("knowledge", {"user_message": message, "retrieved": state["retrieved"], "conversation": state.get("conversation", [])})
                result = {"kind": "knowledge", "answer": response["answer"], "sources": response["sources"], "retrieved": state["retrieved"]}
                records = [("observation", "knowledge_input", {"text": message, "source": "user_report_unverified"}),
                           ("inference", "knowledge_answer", response)]
            elif run["kind"] == "chat":
                prior_replies = [x["content"] for x in state["conversation"] if x["role"] == "assistant"][-3:]
                chat_payload = {"user_message": message, "conversation": state["conversation"],
                                "observations": state["context"], "previous_assistant_replies": prior_replies,
                                "avoid_exact_replies": prior_replies}
                response = stage("chat", chat_payload)
                # A provider can skip emotional acknowledgement or copy the previous turn.
                # Give it one bounded repair attempt before using a safe contextual fallback.
                duplicate = prior_replies and response["reply"].strip() in {x.strip() for x in prior_replies}
                missing_empathy = _needs_empathy(message, response["reply"])
                if duplicate or missing_empathy:
                    state.pop("chat", None)
                    reasons = []
                    if duplicate:
                        reasons.append("Your reply was identical to an earlier assistant reply")
                    if missing_empathy:
                        reasons.append("You did not acknowledge the user's explicitly stated feeling")
                    chat_payload["repair"] = ("; ".join(reasons) + ". Begin with a specific, gentle acknowledgement of the stated feeling, then ask exactly one new follow-up question. Do not give advice yet.")
                    response = stage("chat", chat_payload)
                if ((prior_replies and response["reply"].strip() in {x.strip() for x in prior_replies}) or
                        _needs_empathy(message, response["reply"])):
                    response = _empathy_fallback(message, state["language"])
                    state["chat"] = response
                    self.store.checkpoint(run_id, state)
                result = {"kind": "chat", "reply": response["reply"]}
                records = [("observation", "chat_input", {"text": message, "source": "user_report_unverified"}),
                           ("inference", "assistant_reply", response)]
            elif run["kind"] == "feedback":
                update = stage("feedback", {"feedback": message, "hypotheses": state["hypotheses"], "observations": state["context"]})
                hypotheses = [dict(x) for x in state["hypotheses"]]
                for change in update["updates"]:
                    for h in hypotheses:
                        if h["id"] == change["hypothesis_id"]:
                            h.update(status=change["status"], last_update={"reason": change["reason"], "quote": change["quote"], "run_id": run_id})
                result = {"kind": "feedback", "update": update, "current_hypotheses": hypotheses}
                records = [("observation", "feedback", {"text": message, "source": "user_report_unverified"}),
                           ("inference", "hypothesis_revision", {"hypotheses": hypotheses, "update": update})]
            else:
                evidence = stage("extract", {"user_message": message})
                hypotheses = stage("hypotheses", {"user_message": message, "evidence": evidence, "observations": state["context"], "previous_judgments_unverified": state.get("previous_judgments", [])})
                current_hypotheses = [dict(x) for x in hypotheses["items"]]
                for item in current_hypotheses:
                    for prior in state.get("previous_judgments", []):
                        if item["id"] == prior["id"] and item["explanation"] == prior["explanation"] and "last_update" in prior:
                            item["last_update"] = prior["last_update"]
                actions = stage("actions", {"user_message": message, "evidence": evidence, "hypotheses": hypotheses})
                selected = next(x for x in actions["items"] if x["id"] == actions["recommended_id"])
                dialogue = stage("dialogue", {"user_message": message, "evidence": evidence, "selected_action": selected})
                result = {"kind": "analysis", "evidence": evidence, "hypotheses": hypotheses,
                          "actions": actions, "dialogue_rehearsal": dialogue, "current_hypotheses": current_hypotheses}
                records = [("observation", "input", {"text": message, "source": "user_report_unverified"}),
                           ("inference", "analysis", {"evidence": evidence, "hypotheses": hypotheses, "actions": actions}),
                           ("simulation", "rehearsal", dialogue)]
            result.update(run_id=run_id, session_id=run["session_id"], input=message, mode=self.client.mode,
                          model=self.client.model, language=state["language"], memory_used=state["context"],
                          is_demo=self.client.mode == "mock")
            if "route" in state:
                result["routing"] = state["route"]
            self.store.finish(run_id, result, records)
            self.store.trace(run_id, "committed", {"layers": [x[0] for x in records]})
            return result
        except Exception as exc:
            # Do not persist provider error bodies, credentials, or a traceback.
            error = str(exc) if type(exc).__name__ in {"ModelError", "ContractError"} else "Execution failed; retry the run or inspect local tests"
            self.store.fail(run_id, error)
            self.store.trace(run_id, "failed", {"error": error})
            raise RuntimeError(error) from None
