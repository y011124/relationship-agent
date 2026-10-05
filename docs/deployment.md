# 从本地到公开 Beta

## 当前前提

用户目前没有托管账号或域名。仓库包含部署模板，但没有创建云资源、没有账单、没有可用公网网址。域名不是第一步必需：托管平台可提供HTTPS子域名。

先选择首批用户所在地区和合适的托管位置，确认模型服务可用、数据说明和隐私联系渠道，再邀请用户。这里不声称完成法律或合规审查。

## 路径 A：Render 模板

模板：仓库根目录render.yaml。使用新PostgreSQL数据库，不上传本地memory或outputs。

1. 用户本人注册Render并连接自己的GitHub仓库。确认新代码已推送，先让测试CI通过。
2. 创建Blueprint，选择render.yaml。模板指定新加坡区域、Web starter和PostgreSQL basic-256mb，属于可能产生持续费用的资源；创建前在平台核对价格与地区，不能把模板当成免费承诺。
3. 设置PERSONA_ORIGIN为平台实际分配的HTTPS完整源地址（不带路径或末尾斜杠）。若名字被占用，以平台实际地址为准。
4. 在平台Secret界面配置PERSONA_API_KEY、模型ID/Base URL/协议、PERSONA_PROVIDER_LABEL、PERSONA_PRIVACY_CONTACT。不要发到聊天或写进仓库。
5. 填入当前模型的输入/输出美元每百万token价格，设置保守的PERSONA_REQUEST_RESERVE_USD与每日预算。价格不是项目内硬编码的推荐价。
6. 保存自动生成的邀请码，私下提供给获邀的成年测试用户；不放在公开README。
7. 验证/healthz与/readyz返回成功。注册两个测试账号，执行越权、删除、恢复和费用限制验收。
8. 验证数据库备份实际启用、保留期限符合页面说明，并完成一次隔离恢复。平台套餐的备份能力需要现场核实；没有备份与恢复证据不能算上线验收完成。
9. 先由维护者做真实模型小额回归，再发出邀请。没有用户回复时，不能填写“用户测评通过”。

官方部署格式：https://render.com/docs/blueprint-spec
当前环境没有连接Render账号，模板未在平台验证，不能宣称创建成功。

## 路径 B：自有服务器 Docker Compose

需要Docker Compose、域名DNS指向该服务器，开放80/443。数据库端口不暴露公网。

```bash
cp .env.example .env
# 编辑 .env：production/api、HTTPS origin、域名、模型配置、价格、邀请码、隐私联系渠道
# POSTGRES_PASSWORD 使用URL安全随机字符串，避免连接字符串转义问题
# PERSONA_BACKUP_KEY 另行生成并独立保管
chmod 600 .env
docker compose config --quiet
docker compose up -d --build
```

Caddy处理HTTPS，应用只在容器网络中提供8770，PostgreSQL数据保存在持久卷。Dockerfile使用非root账户；应用本身不会处理付款、DNS或服务器账户。

生成备份加密Key（输出只保存到你自己的密码管理器，不发送到聊天）：

```bash
.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

## 备份与恢复

通过本机/服务器环境配置DATABASE_URL、PERSONA_BACKUP_KEY后：

```bash
python -m relationship_agent.beta.ops backup
python -m relationship_agent.beta.ops purge-old-backups
```

备份为Fernet加密文件，权限0600；密钥与备份分开保存。生产每天执行，输出复制到持久备份存储。7天保留策略需要运营配置生效。配置PERSONA_BACKUP_KEY后执行 `docker compose --profile backup up -d backup` 可启用backup服务，将加密文件保存在独立持久卷；这仍不防宿主机损坏，应配置异机复制。

恢复必须使用新的空数据库，并指向单独测试环境：

```bash
# DATABASE_URL 必须先指向隔离的空库
python -m relationship_agent.beta.ops restore --path backups/persona-TIMESTAMP.enc
```

工具拒绝覆盖非空用户库，恢复后撤销登录会话、把活跃任务标为失败。验证记录数量、人物和事件关联、只读检索；重新应用备份之后发生的删除请求，再考虑切回服务。密钥错误、未重放删除请求或恢复检查失败时禁止切换。

## 运营指标与故障处理

```bash
python -m relationship_agent.beta.ops stats
python -m relationship_agent.beta.ops feedback
python -m relationship_agent.beta.ops review --id FEEDBACK_ID
```

默认统计不显示原始对话或反馈备注；review只接受明确同意的反馈。数据库管理员在技术上仍有读库权限，应限制账号与操作记录，不能把应用中的同意开关描述成数据库加密隔离。

- 配置失败：检查服务日志中的字段名，不粘贴Key或带密码的DATABASE_URL。
- 模型失败：确认服务商、模型、配额；保留run_id。恢复前检查是否改变模型或记忆版本。
- 429／预算用尽：等待每日额度重置或由维护者明确调整预算，不循环重试。
- 进程中断：租约到期后任务变为可恢复失败，已完成阶段仍在。
- 泄漏或严重建议错误：停止邀请，停用相关模型/服务，复现最小合成案例，再加入回归测试。
- 用户忘记密码：通过事先约定的可信渠道核实账号归属后运行ops reset-password --username USER；不要仅凭一个用户名就重置。

## 必须实际验收的发布门槛

- PostgreSQL CI与容器构建通过；平台部署成功且HTTPS证书有效。
- 两个独立账号不能互读、修改人物、会话、运行、反馈与导出。
- 删除后不可继续检索；备份恢复不让已删除数据重新上线。
- 至少一次真实模型完整流程，含错误恢复与预算检查。
- 初始质量案例人工审查，严重越界问题处理完毕。
- 账号注册、邀请码发放、隐私联系和故障响应负责人明确。

未通过这些步骤时，只能称作本地/测试环境Beta，不能称为公开生产服务。
