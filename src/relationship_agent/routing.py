"""Deterministic routing for offline demos; live routing uses the model contract."""
import re


def demo_route(message, has_report=False):
    text = message.lower()
    if any(x in text for x in ("只想聊", "只想倾诉", "听我说", "不想分析", "不要分析", "just listen", "don't analyze")):
        kind = "chat"
    elif any(x in text for x in ("不要搜索", "不用查", "don't search", "no search")):
        kind = "knowledge"
    elif any(x in text for x in ("论文", "文献", "出处", "证据来源", "研究支持", "相关证据", "来源", "谷歌学术", "scholar", "openalex", "papers", "evidence", "sources", "citations")):
        kind = "evidence"
    elif has_report and any(x in text for x in ("后来", "他说", "她说", "更新判断", "反馈", "he said", "she said", "update", "since then")):
        kind = "feedback"
    elif any(x in text for x in ("分析", "怎么办", "怎么做", "怎么回复", "怎么说", "练习", "analy", "what should", "rehearse", "compare options")):
        kind = "analysis"
    elif re.search(r"什么是|是什么意思|解释.{0,20}(概念|依恋|博弈)|科普|资料|理论|what is|what are|explain|define", text):
        kind = "knowledge"
    else:
        kind = "chat"
    return {"intent": kind, "reason": "Offline demo intent rule"}
