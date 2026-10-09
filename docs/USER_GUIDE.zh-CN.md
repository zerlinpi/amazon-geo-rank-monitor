# Amazon Geo Rank Monitor 用户操作手册（简体中文）

> 适用范围：当前 FastAPI + PostgreSQL + Redis + Fantastic Admin Web SaaS。请以实际部署版本、账号权限及环境配置为准。本项目当前**不是** Windows 单机 .exe 程序。
>
> 新手先看 [部署文档](DEPLOYMENT.md)；运维与故障处理看 [稳定性手册](PERFORMANCE_STABILITY.md)；Windows 安装包与签名边界看 [Windows 发布说明](WINDOWS_RELEASE.md)。

## 1. 产品能做什么

系统按“Amazon 站点 + 搜索词 + 地理区域 + 设备 + 搜索深度”采集 SERP，在一次区域请求中定位多个 ASIN，并保存每个区域的观测和加权排名。它还支持定时 Monitor、竞品份额、排名告警、Strict 地理核验、历史趋势与报告。

- **Organic rank**：不含 Sponsored 的自然商品排名，是加权排名主要依据。
- **Absolute rank**：页面中自然和广告混排的位置，不要与自然排名混用。
- **Sponsored rank**：广告结果中的位置。
- **Effective rank**：目标 ASIN 在搜索深度内未找到时按 `search_depth + 1` 处理；上游失败不是“未找到”。
- **Managed**：常规自动监测；**不代表**已经独立验证出口 IP 位置。
- **Strict**：需代理与浏览器真实核验出口 IP 和 Amazon Deliver-to ZIP；有额外成本与适用限制。

本系统不是 Amazon Ads 自动调价系统，也不负责采集 Amazon 用户评论。数据受提供商可用性、页面变化、搜索个性化、代理和网络条件影响；不要将一次观测解释为所有用户的绝对排名。

## 2. 首次部署（管理员）

建议 Linux + Docker Compose、PostgreSQL 17、Redis 7；Windows 管理员可用 Docker Desktop + WSL2 运维容器，参见 [部署手册](DEPLOYMENT.md)。本地开发需要 Python 3.12+、Node.js 24.15+、Git。

1. 检出已审核的 Git SHA，确认 [Actions 的 Validate](../.github/workflows/validate.yml) 全部成功；生产上线前还需按 [staging 手册](STAGING_READINESS.md) 验证。
2. 将项目根目录的 `.env.example` 复制为 `.env`。生成独立的 `API_KEY_PEPPER`、数据库密码和加密密钥；禁止上传、提交或打印明文。
3. 设置公网 HTTPS 域名、`PUBLIC_WEB_URL`、`CORS_ORIGINS`、`SESSION_COOKIE_SECURE=true` 及 SMTP。若启用支付，另配 Stripe；若启用真实 Amazon 采集，另配对应提供商凭证。
4. 执行以下命令（在项目根目录）：

```sh
docker compose config --quiet
docker compose build
docker compose up -d --wait --wait-timeout 180
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/ready
docker compose exec -T api alembic current
```

5. 核对迁移位于最新 `alembic heads`，容器均健康。不要将 8000、PostgreSQL、Redis 直接公开到互联网；通过 TLS 反向代理发布前端。
6. 为测试环境建立一个测试 Workspace，验证登录、读写权限、一次无需真实供应商的 CI/模拟探针、历史查询、告警测试配置和备份恢复；不应在生产环境用可破坏数据的测试命令。

`/health` 只证明 API 存活；`/ready` 还校验数据库与已配置的 Redis。健康状态通过不意味着 Oxylabs、邮件、代理或 Stripe 也都正常。

## 3. 账户、安全和权限

- **Owner**：管理 Workspace 和所有成员；最后一位 Owner 不可移除。
- **Admin**：运营、告警、报告、API Key、系统和团队管理；不能随意改变 Owner/Admin 同级成员。
- **Analyst**：读写排名/Monitor/Geo，查看部分团队和计费信息。
- **Viewer**：只读。
- 浏览器用户使用邮箱登录和 HttpOnly 会话 Cookie + CSRF 校验；API 集成使用 `X-API-Key`，不能将供应商密码放进浏览器。
- 进入 **Workspace → Team** 进行邀请、权限调整与 Workspace 切换；进入 **Workspace → Account Security** 管理密码、会话、MFA。
- 配置 API Key 时遵循最小权限，如只读数据导出使用 `geo:read,monitors:read,rank:read`。密钥通常只在创建时显示一次。

若登录不成功，优先检查 HTTPS、Cookie Secure、CORS、CSRF、账号是否被禁用/锁定、MFA/SSO 策略及后端时钟。不要通过关闭 CSRF/MFA 或修改数据库绕过登录问题。

## 4. 创建第一次排名监控

1. 打开 **Geo Profiles**。创建一个与目标 Amazon marketplace 对应的地区，填写地区名称、目标国家/州/城市/邮编、Amazon 配送邮编、设备类型及正权重。
2. 打开 **Monitors**。选择 marketplace，填写明确的搜索关键词、一个或多个 ASIN、Geo Profiles、搜索深度（如 100），选择 Managed/Strict 策略。
3. 初次建议使用 **Managed** 模式和极少量区域，确认余额、数据来源、排名与计费后再增加监控规模。
4. 需要定时运行时配置标准五字段 cron（按 **UTC** 解释，例如 `0 */6 * * *`）。Scheduler 只派发最新应运行的时间槽，不批量补齐所有停机期间的历史时间槽。
5. 手动触发一次 Monitor，打开 **Run History** 观察 queued/running/succeeded/partially_succeeded/failed，并查看完整观测、每 GEO 的自然排名、有效排名、快照与错误。
6. 若目标 ASIN 未找到，但请求成功，则通常是 `found=false` 且 `effective_rank=search_depth+1`；如供应商出错应检查错误/重试，而不是认定商品掉出排名。

**成本估算**：一次 SERP 请求可匹配多个 ASIN，账单主要由 GEO 探针次数和验证模式决定，不能用 ASIN × GEO 简单估价。默认 Managed 每探针 1 credit、Strict 每探针 5 credits，但应以当前 Workspace 的费率与结算规则为准。切勿用生产密钥批量实验。

## 5. 查看历史、趋势与竞品

- **Run History**：关键字搜索、ASIN 精确过滤、状态和起始时间范围筛选；Newer/Older 分页每次加载限定数量的摘要，**View** 才取完整观测。
- **Analytics & Reports**：选择 Monitor 与时段，查看每 ASIN 加权排名、区间变化、地理细分；导出 aggregate 或 geo CSV。负向排名变化代表名次改善。
- **Competitor Intelligence**：选择 Monitor、Top N、窗口，观察自然/广告 SOV、地理覆盖、竞品趋势。SOV 是已捕获的 SERP 样本份额，不代表整个 Amazon 全站流量份额。
- 竞品历史只能覆盖部署相应采集功能以后保存的 SERP；不会凭空补全此前未采集的竞品。

如需要大范围导出，请按窗口分批导出，避免在浏览器同时打开数千个明细。常规历史列表优先使用 `GET /api/v1/runs/page`，不要反复调用返回完整观测的旧接口。

## 6. Strict 验证、预算和告警

1. 初期保持自动 Strict 关闭；待确认出口 IP 和配送 ZIP、代理预算与合规情况后，在 Workspace 的自动 Strict 策略中逐步开启。
2. 设置单次任务最多 Strict 探针数、每日信用额度和自动 pacing。每日上限按 UTC 结算，可能包含尚未结算的预留额度；`0` 代表禁止新增付费 Strict。
3. 在 **System Status** 查看 Strict 请求、尝试、成功、跳过、缓存命中、pacing 延后原因及真实结算额。缓存命中不等同于新鲜的实时 Strict 采集。
4. 在 **Rank Alerts** 配置 rank drop/improve、Top N 进出、not found、Strict 失败/预算耗尽等规则，选择 Monitor/ASIN/GEO、阈值和冷却期。
5. 可用邮箱、Slack Incoming Webhook 或显式允许域名的 HTTPS webhook。通知发送失败保留在 delivery history，不应将已完成的 rank job 回退为失败。
6. 规则触发后先检查基准运行与当前运行的时间顺序、有效 GEO、任务状态和数据来源，再决定是否采取业务操作。

## 7. 报告、任务队列和日常运维

- 在 **Analytics & Reports** 中设置 UTC cron 报告、Monitor、收件人和 CSV 附件；用 **Send now** 验证邮件环境。
- 在 **Workspace → System Status** 查看 API/Worker/Scheduler 心跳、队列积压、租户用量、失败与 Dead Letter。
- Dead Letter 重排队可能产生实际的上游调用/费用；先找到根因再重新入队。
- 生产升级要先备份、停止 Scheduler 并排空正在处理的任务，再迁移数据库、更新镜像并验证。完整步骤见 [升级手册](UPGRADE.md) 与 [备份恢复](BACKUP_RESTORE.md)。

### 管理员每日检查建议

| 检查 | 正常判断 | 异常优先检查 |
|---|---|---|
| API | `/ready` 成功 | DB、Redis、迁移、应用日志 |
| Worker/Scheduler | 心跳持续更新 | 崩溃、租约、队列、资源占用 |
| 排名任务 | 有完成记录且探针状态合理 | 凭证、超时、搜索页变化 |
| Strict | 成本、成功率和 GEO 一致 | 代理 IP、ZIP、浏览器、预算 |
| 告警与报告 | delivery history 合理 | SMTP、Webhook 域名、网络 |
| 数据 | 可恢复备份、迁移一致 | 磁盘空间、数据库备份验证 |

## 8. 常见问题

**Q：页面加载缓慢或卡住？** 先看浏览器 Network 和 Console；区分静态资源、API 响应、数据库查询还是供应商请求超时。Run History 使用摘要分页；不要一次显示全部明细。观察 CPU、内存、PostgreSQL 慢查询、Redis 可用性和 Worker 心跳，按 [稳定性手册](PERFORMANCE_STABILITY.md) 分层定位。

**Q：窗口刷新后登录失效？** 检查域名是否混用 http/https、Cookie Domain/SameSite/Secure、系统时间和后端会话过期。不要保存会话 Token 到明文 Local Storage。

**Q：运行状态一直 queued？** 检查 Worker 心跳、数据库连通、可用时间、租约和重试退避，以及配额；不要为“解卡”直接删除 Job。

**Q：结果为 partial/failed？** 查看每个 GEO 原始错误、provider 状态和请求额度。上游失败不能视为排名未找到。

**Q：可以直接生成 Windows .exe 吗？** 目前没有该交付方式；这是需要单独的桌面外壳/安装器、Windows CI、安全测试和代码签名的开发目标。详见 [Windows 发布说明](WINDOWS_RELEASE.md)。

**Q：如何证明“没有 bug”？** 无法仅靠一次 CI 保证绝对零缺陷。应结合固定版本依赖、数据库并发测试、Chrome E2E、负载/长稳测试、阶段发布、监控、崩溃日志及可恢复的回滚机制。

## 9. 文档目录

- [README（架构、API 与历史功能）](../README.md)
- [部署](DEPLOYMENT.md) · [升级与回滚](UPGRADE.md) · [备份与恢复](BACKUP_RESTORE.md)
- [稳定性、性能与验证](PERFORMANCE_STABILITY.md) · [Staging 准入](STAGING_READINESS.md)
- [Windows 安装包与签名](WINDOWS_RELEASE.md) · [GitHub 合并门禁](GITHUB_RULESET.md)

请勿将示例域名、密码、密钥、Webhook、支付凭证直接当作生产值使用。
