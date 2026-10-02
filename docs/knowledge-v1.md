# 知识入口第一版

页面使用统一聊天入口，由意图路由选择聊天、知识、分析或反馈工作流；后端复用 RelationshipAgent 的运行、校验、检查点、存储和恢复能力。它们是同一个执行器的不同工作流。

知识路径：用户问题 → 本地关键词检索 → 固定检索结果进入模型上下文 → 回答及引用校验 → 保存结果与执行记录 → 页面展示。真实 API 模式调用当前配置的模型；mock 模式从检索片段生成确定性演示回复。

学术证据路径：用户明确请求论文、文献、研究支持或来源时，路由进入 `evidence`。系统先生成受约束的英文检索词，再并行调用 Google Scholar（SerpAPI）、Semantic Scholar Graph API 和 OpenAlex Works API，按 DOI/标题去重，只保留摘要或搜索摘要等可解释片段，随后复用知识回答和引用校验。Google Scholar 官方不提供批量抓取接口，所以没有直接爬取网页。SerpAPI Key 通过 `SERPAPI_API_KEY` 或网页设置提供；Semantic Scholar、OpenAlex Key 为可选项。失败、限流和未配置都会作为 provider 状态记录，不会伪装成“没有证据”。

资料位于 `src/relationship_agent/knowledge.py`，学术适配器位于 `src/relationship_agent/academic.py`。4 张卡片均为项目编写的中英文入门笔记，覆盖不确定性、沟通、依恋及信息不对称。当前没有向量数据库；外部搜索是按请求进行的轻量检索。未覆盖问题应报告资料不足。引用校验可以阻止伪造来源或片段，但不能证明回答中的每一项推论正确。

统一入口下，知识工作流可参考最近对话理解追问，知识依据仍限于检索片段。知识问题与回答持久化用于显示历史，但知识问题不会进入后续关系分析的个人经历上下文。

2026-09-26 验证：86 项 unittest 通过；8 个 mock 评测用例结构检查通过；前端 JavaScript 语法检查通过。浏览器验证了知识入口、中文问题、引用展开、刷新恢复和倾诉入口切换。外部接口实测中 OpenAlex 返回了论文，Semantic Scholar 正确报告限流，缺少 SerpAPI Key 时 Google Scholar 正确报告未配置。测试没有调用付费模型。尚未评测真实模型回答质量。

本次新版服务运行于 `http://127.0.0.1:8766/`。重启命令：

```sh
cd /path/to/relationship-agent
.venv/bin/python web_app.py --port 8766
```
