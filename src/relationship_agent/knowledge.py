"""Small, source-labelled starter knowledge base for the knowledge workspace.

The first version deliberately uses deterministic lexical retrieval. It keeps the
retrieved text and source together so a vector index can be added later without
changing the Agent contract.
"""
from __future__ import annotations

import re


DOCUMENTS = [
    {
        "id": "uncertainty",
        "title": "关系不确定性与反复确认",
        "source": "ylune starter knowledge note",
        "text": "当重要关系缺少明确回应时，人容易反复回看消息、猜测原因并寻求确定答案。这种反复确认可以暂时降低焦虑，却也可能让注意力继续围绕未知信息循环。一个有帮助的做法是把已知事实、个人感受和仍未确认的解释分开，再决定需要什么信息或边界。",
        "tags": "不确定性 焦虑 反刍 确认 事实 感受 uncertainty anxiety reassurance rumination",
    },
    {
        "id": "communication",
        "title": "困难关系对话的表达结构",
        "source": "ylune starter knowledge note",
        "text": "表达关系中的需要时，可以先描述具体观察，再说明自己的感受和需要，最后提出一个清楚而可拒绝的请求。把请求和指责分开，有助于让对方知道你希望讨论的具体事情。对方是否回应、何时回应，仍然不完全由表达者控制。",
        "tags": "沟通 需要 请求 冲突 非暴力沟通 communication request conflict needs",
    },
    {
        "id": "attachment",
        "title": "依恋概念的使用边界",
        "source": "ylune starter knowledge note",
        "text": "依恋相关概念可以帮助人理解自己在亲密关系中的安全感、靠近和退缩模式，但一次冲突或一段聊天不足以确定一个人的依恋类型。它更适合作为自我观察的语言，而不是给自己或他人下诊断。具体困扰持续影响生活时，应考虑寻求合格专业人士的帮助。",
        "tags": "依恋 安全感 诊断 心理学 attachment security diagnosis",
    },
    {
        "id": "signals",
        "title": "关系中的信号与信息不对称",
        "source": "ylune starter knowledge note",
        "text": "在信息不对称的关系里，一个人的沉默、主动或承诺都可能被另一方解读为信号，但信号通常不是唯一原因的证明。判断行动时，可以比较不同解释的证据、核实成本和边界风险，而不是只根据一次行为推断对方的全部动机。",
        "tags": "博弈论 信号 信息不对称 承诺 推断 证据 game theory signals asymmetry",
    },
]


def _tokens(value: str) -> list[str]:
    return [x.lower() for x in re.findall(r"[\w\u4e00-\u9fff]+", value or "") if len(x) > 1]


ENGLISH = {
    "uncertainty": ("Relationship uncertainty and reassurance", "When an important relationship lacks clear responses, people may repeatedly check messages and seek explanations. Reassurance can offer temporary relief while keeping attention on unknowns. Separate reported facts, feelings and unverified explanations before choosing what information or boundaries you need."),
    "communication": ("A structure for difficult conversations", "Describe a specific observation, express your feelings and needs, then make a clear request the other person can decline. Separate requests from accusations. The other person's response and timing remain outside your control."),
    "attachment": ("Limits of attachment concepts", "Attachment concepts can help describe patterns of security, closeness and withdrawal. One conflict or chat is insufficient to determine a person's attachment style. Use these concepts for reflection, not diagnosis. Consider qualified professional support when difficulties persistently affect daily life."),
    "signals": ("Signals and information asymmetry", "When people have different information, silence, initiative and promises may be interpreted as signals. A signal does not prove a single cause. Compare evidence for different explanations, the cost of checking and boundary risks before inferring motives."),
}


def search(query: str, limit: int = 3, language: str = "zh") -> list[dict]:
    """Return the most relevant cards with a compact, source-labelled payload."""
    query_tokens = set(_tokens(query))
    scored = []
    for doc in DOCUMENTS:
        haystack = set(_tokens(" ".join((doc["title"], doc["text"], doc["tags"]))))
        score = sum(2 for tag in doc["tags"].split() if
                    (tag in query.lower() if re.search(r"[\u4e00-\u9fff]", tag) else tag in query_tokens))
        score += len(query_tokens & haystack)
        if score:
            scored.append((score, doc))
    scored.sort(key=lambda item: (-item[0], item[1]["id"]))
    return [{"id": doc["id"], "title": ENGLISH[doc["id"]][0] if language == "en" else doc["title"], "source": doc["source"], "text": ENGLISH[doc["id"]][1] if language == "en" else doc["text"], "score": score}
            for score, doc in scored[:max(1, min(limit, 5))]]
