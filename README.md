# ylune · Relationship Agent

[English](docs/README.en.md) · [架构](docs/architecture.md) · [验证记录](docs/verification.md)

一个独立的本地关系沟通应用：先与 Agent 多轮聊天；需要梳理时，再探索多个解释、比较行动、练习对话，并用真实反馈修正判断。中英文网页与 CLI 共用一个可恢复的 Harness。

**状态：本地单用户 MVP。** 默认演示模式使用有限的确定性样例；要分析任意真实问题，请配置 API。工程测试通过不等于情感建议质量通过。

## 最快开始

页面现在只提供一个聊天入口。每次发送消息先识别意图，再选择聊天、知识检索、关系分析或已有判断的反馈更新，全部结果保留在同一会话。真实 API 模式由模型结合最近对话识别意图；演示模式使用有限规则。路由结果也保存到检查点，恢复时不会重复已完成的识别。真实模式每条消息增加一次简短路由调用，仍计入本机请求上限。

第一版知识库包含 4 张项目编写的入门卡片：关系不确定性、沟通、依恋、信号与信息不对称；使用关键词检索。用户明确要求“论文、文献、证据来源”等内容时，系统会把主题词路由到学术证据工作流，并行尝试 Google Scholar（通过 SerpAPI）、Semantic Scholar 和 OpenAlex。它用于验证 RAG 流程，不应被当作经过专家审查的心理学资料库。知识提问不会作为个人经历进入关系记忆；引用片段必须来自本次检索结果，未覆盖的问题会提示资料不足。

### 学术证据搜索

学术搜索不是直接抓取 Google Scholar 网页：Google Scholar 官方不提供批量访问接口，因此项目使用 SerpAPI 的 Google Scholar 适配器；Semantic Scholar 和 OpenAlex 使用各自的公开 API。Google Scholar 需要 `SERPAPI_API_KEY`，另外两个 Key 可选，留空时仍会尝试其允许的匿名请求。网页“模型设置 → 学术搜索设置”可以在当前服务进程内填写或更换这些 Key。

搜索流程是：用户问题 → 意图识别为 `evidence` → 整理一条去除私人身份信息的英文检索词 → 三个服务并行搜索 → 按 DOI/标题去重 → 只把摘要或搜索摘要作为有明确标记的证据片段交给知识回答阶段 → 校验引用并展示原文链接。搜索摘要不是论文全文，相关性也不等于因果证明；服务商可能记录查询并按其套餐计费。Key 不会写入数据库、报告或模型上下文。

如需从终端配置：

```bash
export SERPAPI_API_KEY="..."
export SEMANTIC_SCHOLAR_API_KEY="..."  # 可选
export OPENALEX_API_KEY="..."           # 可选
```

服务重启后需要重新配置；当前实现把 Key 保存在服务进程内存中，不落盘。

在项目目录执行（已有 Python 3.10+ 即可，不需要安装前端工具链）：

```bash
python3 web_app.py
```

在你的电脑上，也可以使用已经配置的解释器：

```bash
cd /path/to/relationship-agent
.venv/bin/python web_app.py
```

打开 [本地页面](http://127.0.0.1:8765)。在“和 Agent 聊聊”输入并发送即可。可以说“只想聊聊”、问“什么是依恋”，或说“帮我分析这件事”；系统选择处理流程，分析报告可在聊天中打开。当前已启动版本使用端口 8766。在 PyCharm 直接运行 `web_app.py`，然后打开终端打印的地址。

页面提供多轮聊天、会话历史、阶段进度、分析卡片、真实反馈、执行记录和报告下载。点击右上角 English 切换界面；新会话使用所选语言，旧报告保留原语言。Agent 不会替用户向他人发送消息。

## 使用真实模型与更换 Key

网页右上角“模型设置”中：

1. 选择“真实模型 API”。
2. 选择“GLM · 智谱”或“GPT · OpenAI”预设，再填写你有权使用的对应 API Key。GLM-5.3 推荐 Chat Completions；GPT 预设填入 `gpt-4.1-mini` 和 `https://api.openai.com/v1`。模型 ID 与地址可手动修改。
3. 保存，建立真实模型会话，再输入问题。
4. 更换 Key 时重新填写即可；留空时只会沿用本次服务进程内同一地址、同一协议已输入的 Key。GPT 需要单独的 OpenAI API Key；ChatGPT 网页或 Codex 登录不等于 API 凭据。

Key 仅驻留服务进程内，不写入数据库、报告、浏览器存储或 Git。服务重启后需要重填，或用终端环境变量启动。模型会收到当前输入、同一会话内有界的历史陈述和相关判断。选中的服务商适用其自己的数据政策。切换服务商不会重置本次服务的请求次数上限。

**聊天记录如何保存：**网页中的每条用户输入和成功生成的回复，以及分析、反馈与执行记录，保存在本机 `memory/v2/sessions.sqlite3`；现在没有自动过期、账号同步或网页删除功能。失败的请求会留下输入，但不会凭空生成回复。重新打开网页可以找到旧会话；“新对话”会建立独立会话。每次向模型请求时，只选取当前会话最近最多 12 组已完成聊天（总长度上限 10000 字符），另按任务检索最近最多 8 条现实观察。因此，**保存全部历史不等于模型每次都会读完全部历史**。备份或删除该数据库文件会影响所有本机会话。

为控制测试消耗，每次启动服务默认最多向真实模型发起 **20 次请求尝试**（含重试和格式修复）；网页右上角显示本次服务剩余次数。GLM-5.3 默认使用 `low` 思考强度，聊天单次输出最多请求 768 tokens。达到本地上限会停止调用；这个数字不是智谱账户余额，也不能限制其他应用对同一 Key 的使用。可在启动前设置 `RELATIONSHIP_API_REQUEST_LIMIT` 调整本地上限。真实模型的完整分析通常需要四个阶段调用。

| 服务协议 | Base URL 示例 | 项目实际请求 |
| --- | --- | --- |
| GLM Anthropic 兼容 | `https://open.bigmodel.cn/api/anthropic` | `/v1/messages` |
| GLM Chat Completions | `https://open.bigmodel.cn/api/paas/v4` | `/chat/completions` |
| OpenAI Chat Completions | `https://api.openai.com/v1` | `/chat/completions` |
| 其他兼容服务 | 服务商提供的 API 根地址 | 根据所选协议拼接 |

模型名称默认沿用 `glm-5.3`；你的 Key 是否能访问该模型由服务商账号决定。选择其他模型需同时匹配该服务商的协议、地址、模型 ID 与 Key，不支持任意厂商的专有 API。

在 macOS zsh 中可隐藏输入密钥：

```bash
read -rs "GLM_API_KEY?粘贴你的 API Key，然后回车："
export GLM_API_KEY
echo
.venv/bin/python web_app.py --mode api --model glm-5.3
```

另一个协议或 Key 环境变量：

```bash
.venv/bin/python web_app.py --mode api \
  --protocol chat-completions \
  --base-url https://open.bigmodel.cn/api/paas/v4 \
  --model glm-5.3 --api-key-env GLM_API_KEY
```

也可以直接使用项目内的启动脚本；它固定使用 GLM-5.3、Chat Completions 和上述 Base URL，并在终端隐藏读取 Key：

```bash
zsh run-api.sh
```

脚本默认使用 8767 端口；如需改端口可先设置 `RELATIONSHIP_PORT=8766`。Key 仍只保存在本次服务进程内。

环境变量 `RELATIONSHIP_MODEL`、`RELATIONSHIP_BASE_URL`、`RELATIONSHIP_PROTOCOL` 也可设置；显式命令行参数优先。

## CLI 闭环

分析：

```bash
.venv/bin/python run_experiment.py --mode mock --stage full \
  --message "分开之后，他一直没有联系我。我不知道是不是因为他有其他人了。" \
  --memory-dir memory/v2 --output outputs/first.json
```

记录**真实发生**的反馈（下面是演示样例）：

```bash
.venv/bin/python run_experiment.py --mode mock --stage feedback \
  --feedback "他说他有新伴侣了。" \
  --report outputs/first.json --memory-dir memory/v2 \
  --output outputs/feedback.json
```

继续同一个会话，在下一条命令中加入报告中的 `--session-id SESSION_ID`。失败恢复使用 `--resume RUN_ID`，并保持原模型配置和记忆目录一致；Key 可以更换。已完成的阶段不会重新调用，完成的运行不会重复写入。

`--stage extract` 只做抽取；`--stage interactive` 开启 CLI 交互。交互中使用 `/feedback 真实发生的情况` 和 `/quit`。默认 `full` 每轮四次模型阶段调用，反馈为一次；网络重试和结构修复可能增加请求数。Mock 不消耗额度。

## Harness 做了什么

- 版本化阶段指令与 JSON 合约：聊天；以及抽取 → 解释 → 行动 → 演练 → 反馈。
- 事实候选必须引用当前输入原文；仍标为“用户陈述”，不宣称已独立核实。
- 分开持久化原始陈述、模型判断、假设对话。检索不会把演练当现实。
- 假设 ID、反馈引用、状态变化和原运行编号共同保留修改依据。
- SQLite 事务保存会话、阶段检查点、报告和执行轨迹，支持失败续跑。
- 当前消息最多 6000 字符；观察历史最多 8 条、6000 字符；聊天历史最多 12 组、10000 字符；单阶段 API 输入上限 24000 字符。这是字符预算，不是精确 token 预算。
- Anthropic Messages 与 Chat Completions 两个真实适配器；有限重试与结构修复，失败不会偷偷切换成 Mock。
- 真实 MCP stdio 接口，仅读取显式选择的一个会话。

当前是**固定顺序、有边界的 Agent 工作流**。没有宣称模型自主选择工具、Multi-Agent 协作、训练或 KV Cache 优化已经实现。这样的范围便于说明、测量和复现。

## MCP 集成（可选）

核心网页不依赖 MCP。安装集成：

```bash
.venv/bin/pip install -e '.[mcp]'
```

供 MCP Host 启动的命令：

```bash
.venv/bin/python -m relationship_agent.mcp_server \
  --memory-dir "$(pwd)/memory/v2" \
  --session-id YOUR_SESSION_ID
```

这是 stdio 服务，单独启动后等待 Host 输入是正常的。工具为 `get_observations` 和 `get_hypotheses`。前者只返回用户陈述，后者明确返回推测。接入外部 Host 意味着允许它读取这个指定会话；项目不会自动向任何 Host 注册。

SDK 使用已测试的 1.x 接口，约束 `mcp>=1.20,<2`；本机验证版本为 1.30.0。使用官方 SDK 处理协议握手与工具调用，不把普通函数注册表叫作 MCP。

## 测试与评测

```bash
.venv/bin/python -m unittest discover -s tests -p test_harness.py -v
.venv/bin/python tests/test_mcp_integration.py
.venv/bin/python evals/run_eval.py --output outputs/evaluation.json
```

覆盖事实引用、假设不确定性、性别交换、跨会话隔离、Mock/API 隔离、反馈修正、重启恢复、失败续跑、重试次数、两种 API 协议、网页闭环与真实 MCP stdio 调用。

`evals/cases.json` 含 8 个案例，每个附有人工审查标准。Mock 评测只检查工程约束，结果明确标记 `quality_status=NOT_EVALUATED`。同一套样例可用于真实模型评测（会消耗 API 额度）：

```bash
.venv/bin/python evals/run_eval.py --mode api --model glm-5.3 \
  --limit 2 --output outputs/live-evaluation.json
```

必须阅读实际回答，检查贴题程度、事实/假设区分、沟通边界和性别一致性，再评价模型质量。机械地出现几个字段不能证明这些能力。

## 数据与升级

默认数据库为 `memory/v2/sessions.sqlite3`。这是本机明文数据库，可用常规文件备份；不适合多用户公网服务。网页只监听 127.0.0.1，并检查 Host、Origin 和本地请求令牌；这不是生产登录系统。

v0.1 的 JSONL 文件和旧报告保留原样，**不会自动导入新版记忆**，因为旧 Mock 曾将预设内容混入事实。v0.2 在独立数据库中开始。不同会话独立；模拟与真实模型使用不同会话。

`memory/`、`outputs/`、`.env`、`.venv/` 和 IDE 配置均被 Git 忽略。发布 GitHub 时不要手动添加私人报告或数据库。

## 代码地图

```text
web_app.py / run_experiment.py   启动入口
src/relationship_agent/
  server.py                     本地 HTTP 服务与后台任务
  web/                          原生 HTML/CSS/JS，中英文界面
  engine.py                     编排、检查点、反馈修正
  storage.py                    SQLite 与有界现实记忆
  schemas.py / skills.py        阶段合约、指令与验证
  providers.py / demo.py         API 适配与明确标注的演示
  mcp_server.py                 指定会话的只读 MCP 工具
tests/                          工程与协议集成测试
evals/                          案例、约束检查、人工审查标准
docs/                           架构、英文说明、验证记录
```

## 参考

设计借鉴 [Generative Agents 论文](https://arxiv.org/abs/2304.03442) 的记忆与反馈思路；没有复现论文的虚拟小镇或人物模拟。项目实现独立，不依赖 ZScience 或团队代码。

协议依据：[智谱 Chat Completions 文档](https://docs.bigmodel.cn/api-reference/模型-api/对话补全)、[智谱官方 Claude 兼容示例](https://github.com/MetaGLM/glm-cc/blob/main/glm-4.5-claude-code-integration.md)、[MCP Python SDK 1.x](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x)。
