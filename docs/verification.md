# Persona AI 0.3.0 验证记录

验证日期：2026-10-05。旧版本记录单独保存在 [verification-legacy.md](verification-legacy.md)，其中的旧GLM联调不能当作本次Beta验证。

## 本机通过

- `PYTHONPATH=tests:src .venv/bin/python -m unittest test_harness test_academic test_mcp_integration test_persona test_persona_ops -v`：90项独立测试通过，耗时14.005秒。其中Persona核心36项，运维/MCP3项，旧Harness41项，学术9项，旧MCP1项。
- `evals/persona_eval.py`：40个中英文两轮案例 × profile_only/person_memory两种变体，共160轮Mock执行成功。对照两组保留同样人物资料，只改变已确认经历是否可检索。
- `evals/run_eval.py`：原有8/8结构案例通过。性别交换仅验证确定性测试样例，不证明模型公平性。
- 加密备份恢复使用临时空库，恢复前后对象关联一致；不备份登录令牌；反馈审阅拒绝未获同意的会话。
- Persona stdio MCP使用真实协议握手与工具调用，绑定单一用户和人物，仅返回已确认事件。
- 浏览器验证登录、人物创建、回车发送、记忆确认、新对话回忆、刷新恢复、反馈提交、语言切换及移动布局。人物与反馈均为合成测试数据。
- Python wheel构建、静态页面资源打包、私有数据排除、JavaScript语法检查通过。提交候选文件未检测到常见凭据格式。
- 模型API请求数：0；真实用户参与数：0；模型建议质量尚未评测。

## GitHub CI通过

[https://github.com/y011124/relationship-agent/actions/runs/37314361389](https://github.com/y011124/relationship-agent/actions/runs/37314361389)：应用代码85d1181的五个Job全部成功。

- Python 3.10与3.12：完整测试发现及两组Mock评测通过；test_smoke会重复原有41项，因此完整发现数量不当作独立测试数量。
- PostgreSQL 17：36项Persona核心测试通过，补上本机共享内存受限时无法完成的数据库兼容验证。
- Docker镜像构建、应用导入与页面资源检查通过。
- Chromium：登录→创建人物→回车聊天→确认记忆→新会话回忆→刷新恢复→英文→移动端无横向溢出的合成流程通过。首次浏览器脚本存在同名按钮定位歧义，限定到聊天记忆卡片后重跑通过。

## 尚未通过验证的部分

- 云平台账号、实际HTTPS部署、生产数据库备份恢复、真实模型与真人评测待完成。
- 模拟评测文件的`quality_status`为`NOT_EVALUATED`。Mock延迟不代表真实模型延迟。

详见 [release-status.md](release-status.md)；上线验收与命令见 [deployment.md](deployment.md)。
