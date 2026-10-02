"""Clearly labelled deterministic fixtures. Never presented as model reasoning."""
import re
from dataclasses import dataclass


@dataclass
class MockModelClient:
    mode: str = "mock"
    model: str = "demo-rules-v2"
    protocol: str = "mock"
    base_url: str = ""

    def complete_json(self, stage, payload, schema=None):
        if stage == "route":
            from .routing import demo_route
            return demo_route(payload["user_message"], payload.get("has_report", False))
        en = payload.get("language") == "en"
        def t(zh, eng):
            return eng if en else zh
        if stage == "academic_query":
            text = payload['user_message'] + ' ' + ' '.join(x['content'] for x in payload.get('conversation', []) if x['role'] == 'user')
            topics = [('依恋', 'adult attachment relationship satisfaction'), ('attachment', 'adult attachment relationship satisfaction'),
                      ('焦虑', 'relationship uncertainty anxiety'), ('沟通', 'couple communication conflict'), ('博弈', 'game theory interpersonal cooperation')]
            return {'query': next((q for word, q in topics if word in text.lower()), '')}
        if stage == "chat":
            message = payload["user_message"]
            history = payload.get("conversation", [])
            if any(x in message.lower() for x in ("不想建议", "只想", "just listen")):
                reply = t(f"我听到你现在说“{message[:90]}”，也暂时不想听建议。好，我们先不急着找办法；此刻最重的感受是什么？", f"I hear you saying “{message[:90]}” and that you do not want advice right now. We can leave solutions aside; what feeling is heaviest at this moment?")
            elif not history and any(x in message.lower() for x in ("焦虑", "难过", "害怕", "担心", "生气", "anxious", "sad", "afraid", "worried", "angry")):
                reply = t("听起来你现在真的很焦虑，这种不确定感会很累。我们先不急着解决，你愿意说说最让你焦虑的是哪一部分吗？", "It sounds like you are feeling really anxious, and that uncertainty can be exhausting. We do not have to solve it immediately; what part feels most difficult right now?")
            elif history:
                previous = next((x["content"] for x in reversed(history) if x["role"] == "user"), "")
                reply = t(f"我记得你刚才提到“{previous[:90]}”。现在你又说“{message[:90]}”，听起来这份感受还在。哪一部分变得更明显了？", f"I remember you mentioned “{previous[:90]}”. Now you have added “{message[:90]}”; it sounds like the feeling is still present. What feels more pronounced now?")
            else:
                reply = t("可以，我们慢慢聊。你提到的这件事里，现在最想说的是哪一部分？", "We can take this slowly. Which part of what happened would you most like to talk about?")
            return {"reply": reply + t("\n\n（演示回复：切换到真实模型后，才能获得针对具体情境的自然交流。）", "\n\n(Demo reply: switch to a real model for context-sensitive conversation.)")}
        if stage == "knowledge":
            retrieved = payload.get("retrieved", [])
            if not retrieved:
                answer = t("当前本地知识卡片没有覆盖这个问题。可以换一个更具体的概念，例如依恋、不确定性、沟通边界或信号。", "The starter knowledge cards do not cover this question yet. Try a narrower concept such as attachment, uncertainty, communication boundaries or signals.")
            else:
                first = retrieved[0]
                answer = t(f"根据“{first['title']}”，可以先把这个概念理解为：{first['text']}\n\n这只是一般知识框架，不能仅凭它判断你或对方的心理状态。", f"According to “{first['title']}”: {first['text']}\n\nThis is a general framework, not a diagnosis of you or the other person.")
            return {"answer": answer, "sources": [{"title": x["title"], "source": x["source"], "snippet": x["text"][:180]} for x in retrieved]}
        if stage == "extract":
            message = payload["user_message"]
            # Only literal fragments that actually occur in this input.
            candidates = ["他一直没有联系我", "她一直没有联系我", "我们已经分手", "回复变慢",
                          "我们约定不再联系", "他明确说不要再联系", "她明确说不要再联系",
                          "he hasn't contacted me", "she hasn't contacted me", "we broke up"]
            facts = [{"quote": x} for x in candidates if x in message]
            feelings = [x for x in ("我很难过", "我很焦虑", "我很生气", "I feel anxious", "I feel sad") if x in message]
            assumptions = [x.strip() for x in re.split(r"[。！？\n]", message)
                           if any(k in x for k in ("是不是", "我猜", "我怀疑", "maybe", "wonder", "someone else"))]
            return {"facts": facts, "feelings": feelings, "assumptions": assumptions[:4],
                    "unknowns": [t("关系状态、事件时间和对方的明确表态仍需核实。", "The relationship status, timing and stated boundaries need clarification.")],
                    "questions": [t("你们最后一次沟通时，怎样约定接下来的联系？", "What did you agree about future contact?") ,
                                  t("你现在更希望了解事实、表达需求，还是整理自己的感受？", "Would you like clarity, to express a need, or space to process your feelings?")]}
        if stage == "hypotheses":
            previous = payload.get("previous_judgments_unverified", [])
            if previous:
                return {"items": [{k:v for k,v in item.items() if k != "last_update"} for item in previous]}
            return {"items": [
                {"id": "h1", "explanation": t("对方可能希望保持距离。", "The other person may want distance."), "status": "unknown",
                 "support": [], "limitations": [t("缺少对方明确说明，不能判断原因。", "There is no direct explanation of their reasons.")],
                 "check": t("先回看双方已明确表达的边界。", "Review boundaries both people have explicitly stated.")},
                {"id": "h2", "explanation": t("对方可能开始了其他关系，但目前没有依据确认。", "Another relationship is possible, but is not established by the available information."),
                 "status": "unknown", "support": [], "limitations": [t("不联系本身不能证明有其他人。", "Lack of contact alone does not establish another relationship.")],
                 "check": t("只依据直接说明和可核实信息，不通过监控寻找答案。", "Use direct statements and verifiable information, not surveillance.")},
            ]}
        if stage == "actions":
            return {"items": [
                {"id": "a1", "name": t("先整理自己的需要与边界", "Clarify your needs and boundaries"),
                 "benefit": t("留出空间整理感受。", "Creates room to process feelings."),
                 "risk": t("暂时不能得到对方的解释。", "May not provide an immediate explanation."),
                 "condition": t("信息不足，或对方要求不联系时。", "Useful when information is limited or no contact was requested."),
                 "first_step": t("写下已知情况、猜测，以及自己希望得到什么。", "Write down what you know, what you assume and what you need.")},
                {"id": "a2", "name": t("在双方愿意时澄清沟通", "Clarify, if contact is welcome"),
                 "benefit": t("可能获得直接信息。", "May provide direct information."),
                 "risk": t("可能不回复或带来失望。", "A reply may not come or may be disappointing."),
                 "condition": t("对方没有提出不联系，且你愿意接受不回复。", "Only if no-contact boundaries do not apply and you can accept no reply."),
                 "first_step": t("先确认沟通目的，再决定是否发出简短请求。", "Clarify your purpose before deciding whether to send a brief request.")}
            ], "recommended_id": "a1", "reason": t("演示默认先澄清自己的需要；真实选择取决于具体情境。", "The demo starts with your needs; a real choice depends on the context.")}
        if stage == "dialogue":
            return {"action_id": payload["selected_action"]["id"],
                    "opening": t("仅在心里练习：我现在知道什么？哪些是我担心却还未确认的？", "Private rehearsal: What do I know, and what am I worried about but cannot yet confirm?"),
                    "branches": [{"imagined_reply": t("练习中的念头：没有联系一定说明有其他人。", "Practice thought: No contact must mean someone else."),
                                  "practice_reply": t("我还没有证据确认，可以允许暂时不知道。", "I cannot establish that yet. I can allow some uncertainty.")}],
                    "boundaries": [t("这是私人练习，不会替你发送消息，也不是对方真实说过的话。", "This is private practice, not a message sent or words actually spoken by the other person.")]}
        if stage == "feedback":
            feedback = payload["feedback"]
            updates = []
            # Deliberately narrow fixture; unsupported feedback remains pending.
            direct = next((x for x in ("他说他有新伴侣了", "她说她有新伴侣了", "He said he has a new partner", "She said she has a new partner") if x in feedback), None)
            if direct and any(x["id"] == "h2" for x in payload["hypotheses"]):
                updates = [{"hypothesis_id": "h2", "status": "supported", "quote": direct,
                            "reason": t("用户报告了对方的直接表述，增加该解释的支持；仍不是独立核实。", "A user-reported direct statement supports this explanation; it is not independent verification.")}]
            return {"updates": updates,
                    "reflection": t("演示只识别有限的反馈示例。新陈述已保留；未匹配的判断保持原状。", "The demo recognizes limited feedback fixtures. The new account is retained; unmatched judgments stay unchanged."),
                    "next_steps": [t("结合后续可核实信息再评估自己的选择。", "Reassess your choices as verifiable information arrives.")]}
        raise ValueError("Unknown stage")
