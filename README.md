# Amazon Geo Rank Monitor

Amazon geographic organic-rank monitoring service. It observes the same Amazon keyword from multiple geographic profiles, locates one or more ASINs in each SERP, and calculates a weighted organic rank.

## 中文部署与使用总指南

**当前默认是免费使用模式：`BILLING_MODE=free`。注册后的 Workspace 即使余额为 0，也可以执行排名监控；不需要先接 Stripe 或充值。** 免费指本应用不扣 credits，Oxylabs、住宅代理、服务器和邮件服务的实际费用由各自服务商决定。没有采集服务商凭据时，能启动页面，但不能取得真实 Amazon 排名。

本项目是服务器运行、浏览器操作的 Web 系统。Windows 用户可通过浏览器使用，或用 Docker Desktop/WSL2 启动容器；当前没有独立、签名的 `.exe` 安装包。以下操作适用于仓库代码，不表示已替你部署服务器或配置第三方账户。

阅读顺序：

1. [需要准备的资料](#operator-materials)
2. [第一次安装与启动](#operator-install)
3. [注册账户与首次监控](#operator-first-run)
4. [免费模式与指定账户余额管理](#operator-credits)
5. [日常功能怎么使用](#operator-workflows)
6. [维护、升级、备份和排错](#operator-maintenance)
7. [开发运行与接口集成](#operator-development)

<a id="operator-materials"></a>

### 1. 需要准备什么资料

| 资料或资源 | 何时需要 | 获取或填写方式 | 对应配置/入口 |
| --- | --- | --- | --- |
| 可持续运行的主机、Git、Docker Engine/Desktop 与 Compose v2 | 容器部署必需 | 主机需能拉取 GitHub 源码、容器镜像和依赖；真正采集时需能访问提供商与目标站点 | 项目根目录 `compose.yaml` |
| 服务器登录权限 | 安装、升级、调账时 | 仅交给维护人员；普通用户只需浏览器账户 | SSH/服务器终端；不要把登录口令放进源码 |
| 域名、DNS 与 HTTPS 证书 | 对外提供浏览器服务时 | 将域名指向主机，在宿主机反向代理终止 TLS | `PUBLIC_WEB_URL`、`CORS_ORIGINS`、`SESSION_COOKIE_SECURE` |
| 数据库密码与应用密钥 | 首次部署必需 | 自行生成随机值，保存到根目录 `.env`，另做受控备份 | `POSTGRES_PASSWORD`、`API_KEY_PEPPER` 和加密字段 |
| Oxylabs Amazon Search 的 Web Scraper API 用户名/密码 | Managed 真实采集必需 | 在供应商账户开通相应产品并获取凭据；确认账户有可用配额 | `OXYLABS_USERNAME`、`OXYLABS_PASSWORD` |
| 住宅代理用户名、密码、网关 | 使用 Strict 时 | 开通住宅代理；与 Managed API 凭据分开核对 | `RESIDENTIAL_PROXY_USERNAME/PASSWORD/SERVER` |
| SMTP 主机、端口、发件邮箱、用户名/授权密码 | 邮箱验证、找回密码、邀请、告警和报告 | 向邮箱服务商获取 SMTP 参数；当前客户端支持 SMTP + STARTTLS，不直接连接隐式 TLS 的 465 端口 | `SMTP_*` |
| 第一个使用者的邮箱、密码、显示名、Workspace 名称 | 首次登录必需 | 在注册页面自行填写，没有预设管理员密码 | 浏览器 Register/Create account |
| Amazon 站点、搜索关键词、目标 ASIN | 每个监控必需 | 从实际商品与目标搜索场景取得；ASIN 填商品编号，不填完整链接 | Monitors / Rank Explorer |
| 配送地区邮编、地区名称、权重、设备 | 地区监控必需 | 例如美国 ZIP `10001`；邮编按字符串填写，保留开头的 0 | Geo Profiles |
| Stripe API Key、Webhook signing secret、充值包价格 | 将来启用线上付费充值时 | 免费或管理员手动发额度都不需要；先用 Stripe 测试环境验证 | `STRIPE_*`、`CREDIT_PACK_*` |
| 通知收件人或 webhook 地址 | 启用相应告警/报告时 | 使用自己的测试收件人先验收；自定义 webhook 域名需允许 | Rank Alerts / Analytics & Reports |
| OIDC/SCIM 身份提供商资料 | 企业单点登录/自动配员时 | 常规邮箱登录不需要；由身份平台管理员提供 issuer/client 等配置 | Workspace 中的 SSO/SCIM 设置 |

常规排名监控不要求你提供 Amazon Seller Central 登录密码或 Amazon Ads API Token。供应商凭据保存在服务端，不填入普通浏览器表单或前端 `VITE_*` 变量。

**最小可用组合**：主机 + 数据库/应用密钥 + Managed 采集凭据 + 一个邮箱注册账户 + 一个关键词/ASIN/ZIP。先保持自动 Strict 关闭。没有 SMTP 时不会真实发信，不能承诺密码恢复、成员邀请或邮件告警可用；开放给其他人长期使用前应配置并实测邮件。

### 2. 配置项怎么填

所有后端进程共用根目录 `.env`。修改后要重建/重启 API、Worker、Scheduler，使计费和密钥配置一致。不要只改前端或只重启 API。

| 配置组 | 主要字段 | 初次使用建议 |
| --- | --- | --- |
| 免费/收费 | `BILLING_MODE` | 保持 `free`；只有明确恢复额度计费才改 `prepaid` |
| 费率 | `MANAGED_SERP_CREDIT_COST=1`、`STRICT_SERP_CREDIT_COST=5` | 仅 prepaid 下生效；free 下实际应用费率为 0 |
| 数据库 | `POSTGRES_PASSWORD`、`DATABASE_URL`、`AUTO_CREATE_SCHEMA` | Compose 自动连接内置 PostgreSQL，强制迁移管理；根目录默认 SQLite URL 仅用于裸进程开发 |
| 应用安全 | `API_KEY_PEPPER`、`MFA_ENCRYPTION_KEY`、`SSO_ENCRYPTION_KEY`、`SCIM_TOKEN_PEPPER`、`ALERT_ENCRYPTION_KEY`、`REPORT_ENCRYPTION_KEY` | 生成独立随机值；投入使用后保留原值，随意更换会使密钥或加密数据失效 |
| 浏览器地址 | `PUBLIC_WEB_URL`、`CORS_ORIGINS` | 公网填写同一个 HTTPS origin，例如 `https://rank.example.com`，不加 `/#/` 页面路由 |
| Cookie | `SESSION_COOKIE_SECURE`、`SESSION_COOKIE_SAMESITE` | 公网 `true` / `lax`；仅本机 HTTP 测试可以 `false` |
| 注册 | `ALLOW_PUBLIC_SIGNUP` | 首次受控注册时 `true`；内部使用可注册完首个 Owner 后改 `false` |
| 邮件 | `SMTP_HOST/PORT/USERNAME/PASSWORD/FROM_EMAIL/STARTTLS` | 按服务商的 STARTTLS 配置；主机和发件人为空时不发送真实邮件 |
| 采集 | `OXYLABS_*`、`RESIDENTIAL_PROXY_*` | 先配 Managed；Strict 按需要单独启用 |
| 自动核验 | `AUTO_STRICT_VERIFICATION_ENABLED=false`、`AUTO_STRICT_MAX_PROBES_PER_RUN=3` | 起步保持关闭；人工确认一次 Strict 成功和成本后再开启 |
| 缓存 | `PROBE_CACHE_MANAGED_TTL_SECONDS=300`、`PROBE_CACHE_STRICT_TTL_SECONDS=0` | Managed 默认 5 分钟；Strict 默认重新采集；缓存命中页面有来源信息 |
| 队列 | `JOB_MAX_ATTEMPTS=3`、`JOB_LEASE_SECONDS=900`、`JOB_RETRY_BASE_SECONDS=30`、`JOB_RETRY_MAX_SECONDS=900` | 先保留默认值；根据实测耗时调整，不能用缩短租约解决慢采集 |
| 执行轮询 | `WORKER_POLL_SECONDS=2`、`SCHEDULER_POLL_SECONDS=30` | 默认即可；不同副本使用独立 Worker/Scheduler ID |
| 代理信任 | `AGRM_NETWORK_*`、`AGRM_FRONTEND_IP`、`TRUSTED_EDGE_PROXY_CIDR` | 不冲突时保留默认；不要改成信任所有来源 |
| 支付 | `STRIPE_*`、`CREDIT_PACK_*_AMOUNT_MINOR` | 当前可留空/0；不要为了启动免费监控而配置支付 |

完整变量模板在 `.env.example`。`VITE_AGRM_*` 是前端构建时配置，不是服务端秘密配置；Compose 前端通过同源 `/api/` 请求，通常不需要手动改 API 地址。

<a id="operator-install"></a>

### 3. 第一次安装与启动

以下容器命令在项目根目录执行，终端示例使用 Bash/WSL。

```sh
git clone https://github.com/zerlinpi/amazon-geo-rank-monitor.git
cd amazon-geo-rank-monitor
cp .env.example .env
chmod 600 .env
```

首次初始化可用下面脚本补齐空白密钥；它只替换模板中尚未填写的字段，不显示生成值，不重置已有密钥：

```sh
python3 - <<'PY'
from pathlib import Path
import secrets
p = Path('.env')
lines = p.read_text(encoding='utf-8').splitlines()
keys = {'POSTGRES_PASSWORD', 'API_KEY_PEPPER', 'MFA_ENCRYPTION_KEY',
        'SSO_ENCRYPTION_KEY', 'SCIM_TOKEN_PEPPER', 'ALERT_ENCRYPTION_KEY',
        'REPORT_ENCRYPTION_KEY'}
lines = [line + secrets.token_hex(32) if line in {k + '=' for k in keys} else line
         for line in lines]
p.write_text('\n'.join(lines) + '\n', encoding='utf-8')
print('Blank local secret fields initialized; values not displayed.')
PY
```

编辑 `.env` 填入 Managed 凭据，保留 `BILLING_MODE=free`。不要覆盖旧服务器正在使用的密钥。地址选择如下：

| 项目 | 仅本机测试 | 公网运行 |
| --- | --- | --- |
| `PUBLIC_WEB_URL` | `http://localhost:8080` | `https://rank.example.com` |
| `CORS_ORIGINS` | `http://localhost:8080` | `https://rank.example.com` |
| `SESSION_COOKIE_SECURE` | `false` | `true` |
| `SSO_CALLBACK_URL` | `http://localhost:8080/api/v1/auth/sso/callback` | `https://rank.example.com/api/v1/auth/sso/callback` |

本机测试不要混用 `localhost` 与 `127.0.0.1` 登录。启动：

```sh
docker compose config --quiet
docker compose build
docker compose up -d --wait --wait-timeout 180
docker compose ps
docker compose exec -T api alembic current
docker compose exec -T api alembic heads
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/ready
```

数据库当前应到 `20261013_0023`。`migrate` 服务成功后退出是正常行为；API、Worker、Scheduler、数据库、Redis、前端应持续运行且健康。首次构建要下载依赖与浏览器，等待时间取决于网络，不能据此判断业务程序卡死。

本机打开 `http://localhost:8080`。服务器安装后需经 HTTPS 反向代理访问；Compose 默认仅监听宿主机 loopback，不应将数据库、Redis 或 API 8000 端口直接暴露公网。宿主机 Nginx 的核心配置示例（域名和证书路径换成实际值）：

```nginx
server {
    listen 443 ssl;
    server_name rank.example.com;
    ssl_certificate /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For $remote_addr;
    }
}
```

这里覆盖客户端传入的转发头，不能把不可信地址追加到信任链。公网域名应已解析并安装有效证书；HTTP 到 HTTPS 重定向由宿主机代理配置。其他容器化 TLS 代理的固定地址/信任配置见 [部署手册](docs/DEPLOYMENT.md)。

<a id="operator-first-run"></a>

### 4. 注册账户并跑通第一条监控

1. 打开注册页面，填写自己的邮箱、密码、显示名与 Workspace 名称。首个创建者成为该 Workspace 的 Owner；`agrm-bootstrap` 只创建机器 API 账户，不会创建可用邮箱登录的管理员。
2. 到 **Workspace → Credits & Billing**，应看到 **Free mode — no app credits required**。Balance 为 0 是正常状态。若看不到免费提示，先确认部署的是新版且三个后端进程都读取 `BILLING_MODE=free`。
3. 到 **Geo Profiles → Add Geo Profile**，输入名称 `New York`、配送 ZIP `10001`。默认 Amazon.com / US / Desktop；IP 地区和权重在高级设置中。第一次只创建一个地区即可。
4. 到 **Monitors → Create monitor**，填写自己的真实关键词（如 `adjustable trailer hitch`）和真实 ASIN（例如你要跟踪的商品编号），勾选地区。每条 Monitor 只有一个关键词，多个关键词分别建 Monitor；同一关键词可以填写多个 ASIN。
5. 第一次选择 **Manual only**、**Managed**，搜索深度先用较小值（例如 50）。保存后点 **Run now**，查看 Monitor activity 的排队、运行、完成或错误信息。
6. 点 **View result** 检查目标 ASIN 的自然排名、GEO、采集时间、缓存来源；刷新页面后仍可在 Run History 找到同一条记录。真正覆盖搜索范围但未找到时记为 `found=false`，深度 50 对应有效排名 51；上游错误显示失败，不能当成“未找到”。
7. 确认真实采集成功后，再增加地区、ASIN、深度或运行频率。每页结果数变化会增加采集页数，扫描上限 20 页；到达上限仍未覆盖深度会报错。
8. 需要每小时运行时，将 **Run frequency** 改成每小时并启用 Monitor。Scheduler 按 UTC 派发；`0 1 * * *` 是北京时间每天 09:00，`0 9 * * *` 是北京时间每天 17:00。美国地区涉及夏令时，不要把固定 UTC 计划当作全年固定美国当地时间。

免费模式也需要真实提供商账户可用。`/health` 或页面打开成功，只证明部分服务运行正常，不能代替这一轮真实采集验收。排名口径升级后应重新采集基准，旧历史不会自动改写。

<a id="operator-credits"></a>

### 5. 免费模式与单个账户余额怎么管理

#### 5.1 当前默认免费

```env
BILLING_MODE=free
```

- 手动/API/MCP 查询、后台 Worker 和自动 Strict 使用相同的零应用费率，不需要预留 credits，不会生成扣费/预留流水。
- 已有余额、历史充值、历史扣费全部保留；界面关闭在线充值，新建 Checkout 请求返回明确拒绝。
- 为接收切换前已付款订单的延迟回调，仍可保留 Stripe 配置与签名 webhook；不会因为当前免费而丢弃合法的旧订单到账。
- 自动 Strict 的运行开关、每轮探针上限仍有效；每日预算为 `0` 仍禁止新增自动/强制 Strict 探针，缓存可复用。**正数 credit 日预算与 pacing 在零费率下不是供应商支出的控制器**，请通过采集服务商配额、监控频率和探针上限控制真实调用。

上述自动核验预算不限制直接以 Strict 为主模式发起的采集；主模式 Strict 的真实费用也应在提供商账户和调用频率上控制。

切换已有运行环境前，暂停新任务提交、停 Scheduler、等待已有任务完成，再统一更新和启动 API/Worker/Scheduler。任务按执行进程当时配置计费；正在执行的旧进程不会因编辑 `.env` 立刻改价，也不会自动退款。

#### 5.2 管理员查询指定账户

余额属于 **Workspace（工作区/租户）**，同一 Workspace 的成员共用余额；它不是每个登录邮箱独立的钱包。同一邮箱可能加入多个 Workspace，因此先查清 ID 和名称再修改。

管理员在服务器项目目录执行，普通用户不需要也不应持有数据库权限：

```sh
docker compose exec -T api agrm-credits list --email 'owner@example.com'
docker compose exec -T api agrm-credits list --limit 100
docker compose exec -T api agrm-credits show --workspace WORKSPACE_ID
```

第一条返回该邮箱加入的 Workspace；第二条列出工作区（最多 `--limit 500`）；第三条显示指定 ID 的余额与最近 100 条流水。空查询结果表示邮箱/数据库不匹配，不要因此创建一笔未知账户的调账。`WORKSPACE_ID` 换成查询结果中的完整 `workspace_id`。

`balance` 为总余额，`reserved` 为执行中任务预留，`available = balance - reserved`。例如总余额 100、预留 20，则可用 80。免费模式下这些旧余额可以保留给未来恢复计费使用。

#### 5.3 加额度、减额度、直接设定余额

以下默认只预览，不写入数据库。核对输出中的工作区名称、ID、调整前后金额和原因后，对同一条命令加 `--apply` 才执行。

给指定 Workspace 增加 1000 credits：

```sh
docker compose exec -T api agrm-credits adjust --workspace WORKSPACE_ID --delta 1000 --operator bryant --reason '初始测试额度' --request-id trial-20261013-001
docker compose exec -T api agrm-credits adjust --workspace WORKSPACE_ID --delta 1000 --operator bryant --reason '初始测试额度' --request-id trial-20261013-001 --apply
```

扣回 200 credits 或将**总余额**设为 500，分别使用不同操作 ID：

```sh
docker compose exec -T api agrm-credits adjust --workspace WORKSPACE_ID --delta -200 --operator bryant --reason '扣回多发额度' --request-id correction-20261013-001
docker compose exec -T api agrm-credits adjust --workspace WORKSPACE_ID --set-balance 500 --operator bryant --reason '设置试用余额' --request-id balance-20261013-001
```

核对后，在需要执行的命令末尾加 `--apply`。`--delta` 和 `--set-balance` 只能选一个；不能把余额设成负数或低于已预留额度。若已有任务预留 600，就不能直接将总余额设为 500，应先让任务完成/释放，再查询和调整。

每次新业务操作使用新的 `--request-id`；同一操作因终端断线重试时复用原 ID 和所有原参数，系统只执行一次。即使期间发生消费，重放“设为 500”也不会再次把余额抬回 500。重复 ID 携带不同账户、金额、操作人或原因会被拒绝。

操作人是服务器维护者填写的审计标签，实际权限边界是服务器/数据库访问权限，不是仅凭这个名字授权。每笔应用后的变更在同一事务中写入余额及 `admin_adjustment` 流水，包含操作人、原因、金额和请求 ID；可用 `show` 或 **Credits & Billing → Credit ledger** 查看。不要直接用 SQL 修改 `credit_accounts.balance`，那样没有对应账本。

#### 5.4 将来恢复预付费

```env
BILLING_MODE=prepaid
MANAGED_SERP_CREDIT_COST=1
STRICT_SERP_CREDIT_COST=5
```

可以继续只用管理员命令发额度，**无需 Stripe**。恢复后零可用余额不能执行需要付费的新探针；缓存复用不会当成新的探针收费。更新 `.env` 后统一重建后端容器配置，例如在维护窗口执行 `docker compose up -d --force-recreate api worker scheduler`。

如果需要用户自行在线充值，再配置 Stripe 的 secret key、webhook secret、正数充值包价格以及：

```env
STRIPE_SUCCESS_URL=https://rank.example.com/#/workspace/billing
STRIPE_CANCEL_URL=https://rank.example.com/#/workspace/billing
CREDIT_PACK_STARTER_CREDITS=500
CREDIT_PACK_STARTER_AMOUNT_MINOR=1000
```

此价格仅为配置示例，不是建议售价；`AMOUNT_MINOR` 按所选币种的最小单位填写。Webhook URL 为 `https://rank.example.com/api/v1/billing/webhook`，处理 `checkout.session.completed` 和 `checkout.session.async_payment_succeeded` 的已付款事件。成功跳转页面不会自行加余额，必须收到有效签名并通过校验的付款回调。先在测试环境验证重复回调不会重复到账，再启用真实收款。

<a id="operator-workflows"></a>

### 6. 日常功能与操作入口

| 要做什么 | 从哪里操作 | 操作结果与注意点 |
| --- | --- | --- |
| 单次查询 | Rank Explorer | 填站点、关键词、ASIN、地区、深度；适合验证配置，不自动变成周期任务 |
| 新建/修改长期监控 | Monitors → Create/Edit | 保留原 ID 和历史；调整关键词或地区后解释趋势时注意口径变化 |
| 手动执行和看进度 | Monitors → Run now / Results | 查看该轮队列状态；关闭弹窗不取消任务；刷新状态不重复提交 |
| 暂停监控 | Monitors → More → Disable | 停止后续定时派发，已入队任务不会自动取消 |
| 查看历史 | Run History | 关键词、ASIN、时间/状态过滤，摘要分页；点 View 再取完整详情 |
| 趋势和 CSV | Analytics & Reports | 选择 Monitor 和时间窗口，按汇总或 GEO 导出；检查有效样本覆盖 |
| 看竞品 | Competitor Intelligence | 基于已保存搜索结果计算自然/广告份额，不等同 Amazon 全站市场份额 |
| 设置排名通知 | Workspace → Rank Alerts | 选规则、阈值、对象、渠道与冷却时间；转变类规则需要历史有效基准 |
| 定时报告 | Analytics & Reports | 设置 Monitor、收件人、UTC cron、窗口与 CSV；先 Send now 验证真实收件 |
| 调整团队权限 | Workspace → Team | Owner/Admin 邀请成员，按实际角色授权；最后一位 Owner 不能被移除 |
| 密码/MFA/会话 | Workspace → Account Security | 保存恢复码；丢失密码需可用 SMTP；不要通过改数据库绕过验证 |
| API 集成 | Workspace → API Keys | 创建最小范围 Key，用 `X-API-Key`；通常仅创建时显示明文 |
| MCP | Workspace → MCP Setup | 本地 stdio 需设置 `MCP_TENANT_ID`；账户余额工具只读，不开放远程调账 |
| 看失败和积压 | Workspace → System Status | 看 Worker/Scheduler 心跳、队列、重试、Dead Letter、提供商与通知状态 |
| 额度与流水 | Workspace → Credits & Billing | 免费状态、历史余额、操作人和调账原因；普通网页账户不能修改他人余额 |

Managed 使用配送地区，**不证明出口 IP 已匹配该地区**；Strict 才核验住宅代理出口和配送 ZIP。先单次验证 Strict，再开启自动核验。报表中自然排名越小越好；有效排名会把未找到计入 `search_depth + 1`；加权结果受地区权重和有效观测范围影响。

邮件入口显示“已配置”仅证明填了配置，不证明邮件已送达。请同时检查 delivery history 和真实收件箱。Webhook 仅允许配置的域名，不要为了测试关闭地址校验。

<a id="operator-maintenance"></a>

### 7. 维护、升级与备份

常用只读诊断命令：

```sh
docker compose ps
docker compose logs --tail=100 api worker scheduler
docker compose exec -T api alembic current
docker compose exec -T worker python -m amazon_geo_rank_monitor.operations.health rank
docker compose exec -T scheduler python -m amazon_geo_rank_monitor.operations.health scheduler
docker compose exec -T api agrm-credits --help
```

`agrm-readiness` 是更完整的生产配置验收工具，涵盖 HTTPS、邮件及 Managed/Strict。免费模式或未启用 Stripe 的手动发额度模式会明确跳过 Stripe 检查；其他未配置的检查仍可能失败。它的结果不是“只验证最小 Managed 安装”的结果。`--live` 可访问已启用的邮件/支付服务但不发送邮件、不收费；`--paid-provider-probes` 会额外执行真实 Managed 和 Strict 探针，可能产生供应商费用，应仅在明确预算的测试环境使用。

备份数据库（在仓库根目录，备份文件不要提交 Git）：

```sh
mkdir -p backups
chmod 700 backups
docker compose exec -T postgres pg_dump -U amazon_geo_rank -d amazon_geo_rank -Fc > backups/agrm.dump
chmod 600 backups/agrm.dump
```

这条命令会覆盖同名备份，实际维护请使用带日期的独立文件并保存异地副本。单独备份原有 `.env`/密钥及域名代理配置；缺少原加密密钥时，数据库恢复后也无法解密相关数据。恢复演练必须在隔离空库进行，操作详见 [备份与恢复](docs/BACKUP_RESTORE.md)。不要对生产数据库直接跑测试，也不要在升级时执行 `docker compose down --volumes`。

已有安装升级至本轮版本：

1. 记录旧 Git SHA、镜像与数据库版本，完成并核验备份；明确当前部署的 `BILLING_MODE`，旧付费服务若要维持付费必须显式设为 `prepaid`。
2. 暂停新任务提交，停 Scheduler，等待执行中和排队任务处理完，再停 Worker/API。
3. 检出已通过 Validate 的目标提交，保留原 `.env` 与密钥，执行 `docker compose build`。
4. 执行 `docker compose run --rm migrate`，确认迁移到 `20261013_0023`；此迁移增加调账审计详情字段，保留已有余额和流水。
5. 执行 `docker compose up -d --wait --wait-timeout 180`，检查健康状态、免费标识、历史记录和一条受控监控；再恢复定时运行。

代码回滚优先使用原镜像、原配置和保留的数据库。将数据库降级到 `0022` 会移除新的调账详情列；除非已经备份并明确接受丢失这部分审计信息，不要为代码回滚删除该列。

### 8. 常见问题怎么处理

| 现象 | 先检查什么 | 处理方式 |
| --- | --- | --- |
| 网页打不开 | `docker compose ps`、frontend 日志、域名/证书 | 先本机访问 8080，再检查公网代理；不要直接公开数据库端口 |
| 登录后又回到登录页 | HTTP/HTTPS、Cookie Secure、CORS、域名是否混用 | 使用配置的同一个 origin；公网保留 Secure Cookie |
| 余额为 0 无法运行 | Billing 页面模式、Worker 是否旧进程 | free 不应被余额阻止；确认 API/Worker/Scheduler 全部应用新配置 |
| 一直 queued | Worker 心跳、队列可用时间、数据库与重试退避 | 恢复 Worker/连接后观察；不要反复点 Run now 制造重复任务 |
| Managed 未配置/认证失败 | `OXYLABS_*`、API 产品权限、供应商配额 | 在服务端改正后重建进程；应用调账不会给供应商账户充值 |
| Strict 失败 | 住宅代理、浏览器、出口位置、配送 ZIP、运行开关 | 查看该 GEO 的错误；Managed 成功不代表 Strict 成功 |
| 未找到或排名异常 | 搜索深度、ZIP、设备、缓存时间、采集错误 | 确认完整有效采集后解释；不要把错误样本当名次下降 |
| 调账说 workspace not found | Workspace ID、所连数据库、邮箱查找结果 | 先 `list --email` 和 `show`，不要猜测 ID |
| 调账说低于 reserved | 尚有执行中的预留额度 | 等任务结算/释放后再查；不要手动清空预留字段 |
| 调账说 request_id 已使用 | 是否复用了旧操作 ID且改了金额/原因 | 精确重试保留原参数，新操作使用新 ID |
| 调账数据库失败 | 连接、迁移版本、数据库状态 | 执行 `alembic current/heads`，检查迁移；命令不会自动新建生产库 |
| 已付款但余额不变 | 是否免费关闭新支付、webhook 是否送达、签名及订单记录 | 查看 Stripe 事件和账本，避免人工加款后又被正常回调重复补款 |
| 没收到邮件/报告 | SMTP、TLS、发件人授权、delivery history、垃圾箱 | 配置后重启三类后端进程，并用测试邮箱实际收一封 |
| 运行缓慢 | 提供商页数、队列长度、CPU/内存、数据库、缓存 | 先减少地区/深度/频率，再按测量定位；没有承诺无限并发 |
| 免费后仍出现旧额度记录 | 旧任务和历史流水 | 正常保留历史；停旧进程排空任务后再切模式，新任务应不再扣款 |

<a id="operator-development"></a>

### 9. 开发运行与接口集成

生产优先使用以上 Compose 方式。开发机器使用 Python 3.12+、与仓库镜像匹配的 Node 24、Git；从根目录建立 Python 环境，安装锁定依赖：

```sh
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.lock
.venv/bin/pip install --no-deps -e backend
npm --prefix frontend ci
npm --prefix frontend run typecheck
```

最后一步会同步固定版本的 Fantastic Admin、按锁文件安装其依赖并检查类型。首次开发必须完成这一步；仅执行外层的 `npm ci` 尚未准备好实际 UI 的依赖。

根目录 `.env` 选择开发 SQLite URL、`AUTO_CREATE_SCHEMA=true`、免费模式及 `http://localhost:5173` 对应地址，使用三个终端从根目录分别运行 `.venv/bin/agrm-api`、`.venv/bin/agrm-worker`、`.venv/bin/agrm-scheduler`，另一个终端运行 `npm --prefix frontend run dev`。按前端终端实际显示的端口匹配 CORS 与公开地址。Windows PowerShell 的虚拟环境可执行文件在 `.venv\Scripts\`；其他路径与 shell 语法需按系统调整。

开发 SQLite 使用相对文件路径，所有后端命令必须保持同一工作目录，避免误连另一个空数据库；生产 CLI 建议始终通过 `docker compose exec -T api agrm-credits ...` 运行。

API 文档默认在后端 `/docs`。人类用户经注册登录，机器集成通过 Workspace → API Keys 创建 Key，使用 `X-API-Key`；浏览器写操作还需要 CSRF 令牌。常用接口包括：`GET /api/v1/billing/status`、`GET /api/v1/credits`、`GET /api/v1/credits/ledger`、Geo Profiles、Monitors 与 `GET /api/v1/runs/page`。调账命令没有对应的公开 HTTP/MCP 写接口。

在隔离开发环境验证：

```sh
(cd backend && TZ=UTC PYTHONPATH=src ../.venv/bin/python -m pytest -q)
.venv/bin/python -m ruff check backend/src backend/tests
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

浏览器 E2E 使用模拟 SERP 与真实 API/Worker，不会调用付费供应商。PostgreSQL/Redis 专项必须使用专用测试库；这些测试可能删除测试库内数据。CI 通过仅证明自动化验收范围，真实采集、邮件收件、长时间运行和备份恢复仍需在实际部署验收。更详细的内部架构与接口参考保留在本 README 下半部分。

## Start here

This is a **web SaaS**, not a standalone Windows desktop application. The backend
runs FastAPI, PostgreSQL, Redis, workers and a scheduler; the browser UI is
based on Fantastic Admin. A signed Windows `.exe` is not currently produced.

| Goal | Documentation |
| --- | --- |
| Check actual usability, acceptance evidence and remaining delivery conditions (中文) | [Operational acceptance](docs/ACCEPTANCE.zh-CN.md) |
| Learn every main user workflow (中文) | [Chinese user guide](docs/USER_GUIDE.zh-CN.md) |
| Install and operate the Linux/Compose service | [Production deployment](docs/DEPLOYMENT.md) |
| Investigate stalls, performance and failed jobs | [Performance and stability runbook](docs/PERFORMANCE_STABILITY.md) |
| Upgrade safely and roll back | [Upgrade and rollback](docs/UPGRADE.md) |
| Verify external staging dependencies | [Staging readiness](docs/STAGING_READINESS.md) |
| Understand Windows installers and code signing | [Windows release requirements](docs/WINDOWS_RELEASE.md) |

### First monitor in the browser

Once an administrator has configured the provider, selected free mode (or funded a prepaid workspace) and started
the worker, use this short path:

1. **Geo Profiles → Add Geo Profile**: enter a name and delivery ZIP. US/desktop
   defaults suit a first Managed check; requested IP and other options are under
   **Advanced region settings**. IDs are generated by the server.
2. **Monitors → Create monitor**: enter a name, keyword and ASINs, select regions,
   and choose **Manual only** or a frequency preset. Presets explicitly use UTC;
   custom five-field cron remains available. Advanced settings retain search depth
   and provider selection. Saving alone does not enqueue a manual run.
3. **Run now** opens **Monitor activity**, showing queued/running/completed jobs,
   retry state and failures. **View result** opens that exact run's observations.
   Return through **Results** after leaving the page; it shows the latest 10 jobs.
4. **Edit** changes an existing monitor without recreating it or deleting its
   history. Existing automatic verification overrides are retained. Use **More**
   for alerts, verification policy, one-off verification, enable/disable or delete.

The monitor list supports search by name, keyword and ASIN, and its actions wrap
on small screens. Failed form submissions retain input. Refreshing activity reads
status only; it never resubmits a job. Polling stops when the dialog is closed or
the browser tab is hidden. Real provider access and SMTP delivery still require
the external checks in the staging runbook.

The modern Run History endpoint loads bounded summaries via
`GET /api/v1/runs/page`. Phase 39 additionally batches legacy full-detail
`list_runs` reads into one run query, one observation query and one snapshot
query, avoiding per-run database requests while preserving the existing
response contract. This is an **SQL query-count optimization**, not a promise
of zero UI latency or a benchmarked throughput figure.

## Architecture and stable baseline

Phase 32 hardens the existing product: account/workspace access, geo profiles,
monitors, managed/strict verification, queued execution, weighted snapshots,
history, analytics, alerts and prepaid credits. It adds no new business subsystem.
The baseline entering hardening is `2ef06d5` (2026-09-30); the current database head
is `20261013_0023`. No published migration is rewritten.

The required **validate** check covers backend, PostgreSQL migrations/concurrency,
Redis, frontend tests/typecheck/build, browser E2E in UTC/New York/Singapore,
dependency/secret scans and a complete Docker Compose smoke test. A failed,
cancelled or skipped dependency makes this gate fail. Phase 32 is a release
candidate until all these checks succeed on its exact commit; no release tag is
created automatically.

- [Deploy and configure](docs/DEPLOYMENT.md)
- [Upgrade and roll back](docs/UPGRADE.md)
- [Back up and restore](docs/BACKUP_RESTORE.md)
- [Security policy](SECURITY.md)
- [GitHub required checks](docs/GITHUB_RULESET.md)
- [Hardening evidence and limitations](docs/hardening/PHASE32.md)
- [Staging release readiness](docs/STAGING_READINESS.md)
- [Changelog](CHANGELOG.md)

## Staging release readiness

Phase 33 adds a manual staging verification layer without changing rank semantics
or automatically publishing a release. `agrm-readiness` checks production-style
HTTPS/cookie/CORS configuration and can authenticate to SMTP and Stripe without
sending email or creating a payment.

A separate manual-only GitHub Actions **Staging Readiness** workflow verifies the
deployed frontend, `/health` and `/ready`. Real managed and Strict provider probes
are disabled by default and require explicit operator opt-in because they may consume
provider credits. See [the runbook](docs/STAGING_READINESS.md).

## Scope

This repository is intentionally focused on Amazon rank monitoring. Amazon Ads bidding, listing optimization, inventory, repricing, and review scraping are out of scope.

The architecture uses a Hybrid provider model:

- **Managed monitoring:** Oxylabs Amazon Search for routine, structured SERP collection.
- **Strict verification:** Playwright + residential proxy verification where the requested IP geography and Amazon Deliver-to location are independently confirmed before the SERP result is accepted.

Managed mode must not be described as strict IP verification. The Oxylabs adapter records the requested IP geography as metadata while using the delivery postal code for the managed Amazon search geography.

## Alert history baseline

Rank-change and competitive transition alerts compare against the most recently
**completed** earlier successful or partially successful run for the same
workspace and monitor. Failed or cancelled jobs, missing run records, and runs
completed at or after the current run cannot become a baseline. History is not
limited to the newest 20 jobs; after a long failure streak, the last valid
baseline remains eligible. If no valid earlier run exists, transition alerts
wait for a baseline. This change does not require a database migration.

Phase 37 adds a covering index on `rank_jobs(owner_id, monitor_target_id, status, run_id)`
to keep the unbounded, tenant-scoped alert baseline lookup efficient as job history
grows. Upgrade with `alembic -c alembic.ini upgrade head` before deploying the new
code; existing job data and alert semantics are unchanged. The index is created by
revision `20261008_0022`, which can be downgraded independently. On large
PostgreSQL installations, schedule this standard index migration during a
maintenance window because index creation can block concurrent writes.

## Rank semantics

The system keeps three concepts separate:

- `organic_rank`: position among organic products only; this drives the weighted score.
- `absolute_rank`: observed mixed product-card position including sponsored placements.
- `sponsored_rank`: position among sponsored results when present.

For Oxylabs managed results, provider `pos` is retained as an observed mixed SERP position; organic rank is derived from the ordered organic result collection so sponsored placements do not inflate the organic rank.

If an ASIN is not found within `search_depth`, the stored values are:

```text
found = false
organic_rank = null
effective_rank = search_depth + 1
```

A provider failure is an error, not an ASIN-not-found result.

Managed collection continues according to observed organic counts, with a 20-page
ceiling. Missing/duplicate provider pages, invalid organic records and a page cap
reached before sufficient coverage produce errors instead of false not-found
observations. Strict collection likewise fails on an incomplete page-limited scan.
Competitor organic/sponsored positions use their respective channel ordinals.
Deeper collection can require more provider requests; application credits remain
per GEO probe and are not a quote for external provider charges. Parser-versioned
cache keys invalidate older results; historical records are not rewritten.

## One SERP, many ASINs

The data-collection unit is a SERP probe, not an ASIN. A single query for:

```text
marketplace + keyword + geo profile + device + search depth
```

is matched against every requested ASIN. Therefore 2 ASINs across 3 geographic profiles require 3 provider probes, not 6.

## Weighted rank

For successful observations:

```text
weighted_rank = sum(effective_rank_i * weight_i) / sum(weight_i)
```

Weights are normalized mathematically and do not need to sum to 1 or 100. The raw regional observations are always retained alongside the weighted score. Confidence currently represents the share of configured geographic weight covered by successful probes.

## Managed monitoring

The default `OxylabsRankProvider` uses Oxylabs Amazon Search parsed results.

Managed mode is optimized for routine monitoring and bulk collection. It records:

- requested IP geography from the GeoProfile as intent;
- Amazon delivery postal code used for the managed request;
- `ip_geography_verified = false`.

This distinction is deliberate: managed results must not be presented as proof that the exit IP postal code was independently verified.

## Strict geographic verification

Strict mode is implemented by `StrictBrowserRankProvider` and `PlaywrightAmazonBrowserClient`.

Current strict flow:

```text
GeoProfile
   |
   v
Residential proxy with sticky session
   |
   v
Verify observed exit-IP geography
   |
   v
Same isolated Playwright BrowserContext
   |
   v
Open Amazon and set Deliver-to ZIP
   |
   v
Confirm requested ZIP is displayed
   |
   v
Search keyword and collect SERP cards
   |
   v
Organic / sponsored separation
```

A strict result is accepted only when both the requested IP geography and requested Amazon delivery ZIP are confirmed.

Current strict constraints:

- `amazon.com` only;
- US ZIP-level residential proxy targeting only;
- desktop browser only;
- one isolated BrowserContext per strict probe;
- CAPTCHA / robot-check pages produce an explicit blocked error;
- the implementation does not solve CAPTCHA, use stealth plugins, spoof fingerprints, or attempt to bypass anti-bot controls.

Strict verification is intended for manual checks, anomalies, and high-confidence validation. Routine scheduled monitoring should use managed mode.

## Local development

Requirements: Python 3.12+.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e '.[dev]'
cp ../.env.example .env
PYTHONPATH=src python -m pytest -q
ruff check src tests
```

Configure geographic profiles from `config/geo_profiles.example.yaml`.

For real managed Oxylabs calls:

```env
OXYLABS_USERNAME=...
OXYLABS_PASSWORD=...
```

For strict residential-proxy verification:

```env
RESIDENTIAL_PROXY_USERNAME=...
RESIDENTIAL_PROXY_PASSWORD=...
RESIDENTIAL_PROXY_SERVER=http://pr.oxylabs.io:7777
```

Install a Chromium runtime before executing real strict checks:

```bash
playwright install chromium
```

Provider credentials are not required to import the package or run the offline unit tests.

## Current implementation phase

Implemented:

- provider-neutral rank core and strict geographic verification;
- tenant-scoped REST, API keys, database worker and MCP runtime;
- prepaid credits, reserve/settle accounting and Stripe Checkout/webhooks;
- Fantastic Admin Basic SaaS console;
- cron-based monitor scheduling with idempotent time-slot dispatch;
- PostgreSQL-safe worker claiming with `FOR UPDATE SKIP LOCKED`;
- monitor-specific run history;
- Alembic production schema migrations;
- Docker Compose migration gate, API, worker and scheduler services;
- GitHub Actions tests, Ruff checks, and PostgreSQL integration coverage;
- least-privilege API-key scopes, database readiness, and worker heartbeats;
- leased rank jobs, automatic retries, stuck-job recovery, dead-letter queue, and Prometheus-compatible operations metrics;
- tenant audit trails, API-key usage/IP statistics, and Redis-backed multi-replica rate limiting.

The complete architecture is documented in `docs/superpowers/specs/2026-09-24-amazon-geo-rank-saas-design.md`.


## API, worker, and MCP runtime

Phase 3 exposes the same rank application through authenticated REST, a database-backed worker, and the official MCP Python SDK v2.

Required SaaS secret:

```env
API_KEY_PEPPER=replace-with-a-long-random-server-secret
```

Bootstrap the first tenant and API key:

```bash
cd backend
agrm-bootstrap --name "My Workspace"
```

The plaintext API key is printed once. The database stores only its display prefix and HMAC-SHA256 digest.

Start REST:

```bash
agrm-api
```

REST requests use:

```http
X-API-Key: agrm_...
```

Run one queued database job:

```bash
agrm-worker --once
```

Or run the worker continuously:

```bash
agrm-worker
```

For a local MCP stdio server, bind the process to one tenant:

```env
MCP_TENANT_ID=<tenant uuid>
```

Then run:

```bash
agrm-mcp
```

The local process boundary is the tenant security boundary for stdio. Streamable HTTP is intentionally not exposed by the CLI until an OAuth 2.1 `AuthSettings`, `TokenVerifier`, and access-token-to-tenant resolver are configured. A SaaS API key is not treated as an OAuth bearer token.

### REST endpoints

- `GET /health`
- `GET /ready`
- `POST/GET /api/v1/geo-profiles`
- `POST/GET /api/v1/monitors`
- `GET /api/v1/monitors/{id}`
- `GET /api/v1/monitors/{id}/history`
- `POST /api/v1/monitors/{id}/run`
- `GET /api/v1/jobs/{id}`
- `POST /api/v1/rank/check`
- `GET /api/v1/runs/page`
- `GET /api/v1/runs/{id}`
- `GET/POST/DELETE /api/v1/api-keys`
- `GET /api/v1/system/workers`
- `GET /api/v1/system/queue`
- `GET /api/v1/system/dead-letters`
- `POST /api/v1/system/dead-letters/{job_id}/requeue`
- `GET /api/v1/system/metrics`
- `GET /api/v1/system/audit`
- `GET /api/v1/system/verification-summary`
- `GET /api/v1/system/verification-analytics?hours=168`

All tenant-owned lookups are filtered server-side. A resource owned by another tenant is returned as not found.

### Searchable, paginated Run History

The Run History console loads 50 summaries at a time and supports **Newer** /
**Older** navigation, keyword search, exact ASIN search and run-status filtering.
Use **Run start time** to narrow the range, or choose the last 24 hours, 7 days or
30 days. The picker and Started column display the browser's local timezone;
the request sends UTC timestamps and keeps the selected range while paging.
Click **View** to fetch the full regional observations, snapshots and strict
verification evidence. Clearing the filters and choosing **Search / refresh**
returns to the newest runs.

```http
GET /api/v1/runs/page?limit=50&keyword=trailer&asin=B0FL2KKV77&status=succeeded
```

The endpoint requires `rank:read` and returns `{ "items": [...], "next_cursor": ... }`.
Pass the returned `next_cursor` as `cursor` with the same filters to get older
records; a null cursor ends the result set. `limit` defaults to 50 and accepts
1–100. Keyword matching uses literal substrings, including literal `%` and `_`.
Case folding follows the database: PostgreSQL uses its configured collation;
SQLite's built-in case folding covers ASCII only, so accented or non-Latin
letters may require matching case in local SQLite development.
ASIN matching normalizes case and searches persisted
observations and snapshots, including failed observations. Runs that have not yet
stored either cannot match an ASIN filter.

Ordering is `started_at DESC, id DESC`, so equal timestamps are deterministic and
newly inserted newer runs do not shift subsequent pages. Each cursor is validated
against the caller's workspace; missing and foreign cursors return the same 422
response. Status and cursor validation failures also return 422.

Optional `started_from` and `started_until` bounds filter the **run start time**,
including both endpoints. Supply ISO-8601 timestamps with an explicit UTC offset
or `Z`. Either bound may be omitted; omitting both preserves the full-history
behavior. Naive timestamps, invalid values and a start later than the end return
422. For example:

```http
GET /api/v1/runs/page?started_from=2026-09-01T00:00:00Z&started_until=2026-09-28T12:00:00Z
```

Bounds are normalized to UTC before querying SQLite or PostgreSQL. Summary
timestamps also carry an explicit UTC offset, including when SQLite removed the
timezone from a stored UTC value, so browsers do not interpret UTC as local time.
Time filters reuse the history index and require no additional migration.

Summary items include `snapshot_count` and strict-verification counters, but omit
observations, snapshots, per-probe events and full budget evidence. The detail
endpoint `GET /api/v1/runs/{id}` retains that evidence. Existing `GET /api/v1/runs`
and monitor-history responses keep their original array format for API and MCP
compatibility. The summary query uses at most two database reads on the first
page, or three with cursor validation, independent of page size.

Schema revision `20260928_0021` adds a workspace/time/ID index for history browsing.
Upgrade existing installations before deployment:

```bash
cd backend
alembic -c alembic.ini upgrade head
```

### MCP tools

- `check_rank`
- `list_geo_profiles`
- `create_monitor`
- `run_monitor`
- `get_rank_run`
- `get_rank_history`

MCP tools call the same application services used by REST; there is no duplicate ranking implementation.


## Prepaid credits and Stripe

`BILLING_MODE=free` is now the deployment default: no credit reservation or deduction,
no new checkout, and zero balance is usable. Existing balances and signed payment
webhooks are retained. The host-only `agrm-credits` command supports audited manual
adjustments in either mode; see the Chinese operator guide above.

When explicitly set to `BILLING_MODE=prepaid`, rank usage is billed by actual SERP
probe, not by ASIN. The default configurable prepaid rate card is:

- managed SERP: 1 credit per geographic probe;
- strict browser-verified SERP: 5 credits per geographic probe.

A request reserves the maximum probe cost before provider work. Only successful geographic probes are settled; unused reserved credits are released.

Credit packs are disabled by default because their prices are business configuration. Set the corresponding `CREDIT_PACK_*_AMOUNT_MINOR` values above zero to publish them.

Stripe configuration:

```env
BILLING_MODE=prepaid
STRIPE_SECRET_KEY=sk_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_SUCCESS_URL=https://app.example.com/#/workspace/billing
STRIPE_CANCEL_URL=https://app.example.com/#/workspace/billing
CREDIT_PACK_STARTER_AMOUNT_MINOR=...
CREDIT_PACK_GROWTH_AMOUNT_MINOR=...
CREDIT_PACK_SCALE_AMOUNT_MINOR=...
```

The browser success redirect never grants credits. Purchased credits are granted only after a signed Stripe webhook reports a paid Checkout Session. The internal append-only credit ledger remains the source of truth for application credits.

Billing REST endpoints:

- `GET /api/v1/billing/status`
- `GET /api/v1/credits`
- `GET /api/v1/credits/ledger`
- `GET /api/v1/billing/packs`
- `POST /api/v1/billing/checkout`
- `POST /api/v1/billing/webhook`

MCP exposes `get_credit_balance` as read-only; it does not expose ledger mutation or Stripe operations.


## SaaS frontend

The SaaS console uses Fantastic Admin Basic `core-element-plus` as its only UI foundation. The upstream source is pinned rather than copied wholesale into this repository:

- upstream: `fantastic-admin/basic`
- version: `v6.4.0`
- revision: `4cf1d0f92c3c7a8651bc41c6c3b65aabbde30af1`
- license attribution: `THIRD_PARTY_NOTICES.md`

Product-specific files live under `frontend/overlays/`. The sync script clones the exact pinned upstream revision into the ignored `frontend/.vendor/fantastic-admin` directory and overlays the Amazon Geo Rank Monitor pages before running the upstream build.

Requirements: Node.js 24.15+ and Git.

```bash
cp frontend/.env.example frontend/.env
npm --prefix frontend run sync
npm --prefix frontend run dev
```

Production build:

```bash
VITE_AGRM_API_BASEURL=https://api.example.com npm --prefix frontend run build
```

The generated static bundle is copied to `frontend/dist`.

The current authentication surface uses a Workspace API Key because the backend deliberately has no password-user model yet. Fantastic Admin route authentication is enabled, the key is sent as `X-API-Key`, and provider/Stripe secrets are never exposed to the browser.

Main console pages:

- Dashboard
- Rank Explorer
- Monitors
- Geo Profiles
- Run History
- Credits & Billing
- API Keys
- MCP Setup


## Scheduled monitors

A monitor may include a standard 5-field cron expression. Schedules are interpreted in UTC.

Example:

```text
0 */6 * * *
```

Run the scheduler once:

```bash
agrm-scheduler --once
```

Or run it continuously:

```bash
agrm-scheduler
```

The scheduler dispatches only the latest due cron slot. It does not backfill every missed slot after downtime. Each slot receives a deterministic job UUID derived from the monitor ID and scheduled UTC minute, so repeated scheduler scans and multiple scheduler instances do not intentionally create duplicate jobs for the same slot.

## Database migrations

Local development keeps `AUTO_CREATE_SCHEMA=true` by default for fast SQLite setup. Production should run Alembic and set `AUTO_CREATE_SCHEMA=false`.

For a new database:

```bash
cd backend
alembic -c alembic.ini upgrade head
```

The included Docker Compose stack runs a one-shot `migrate` service before the API, worker and scheduler start.

For an existing database created by an earlier Phase 1-5 build, take a backup and verify that its schema matches the current SQLAlchemy models before stamping the baseline revision:

```bash
cd backend
alembic -c alembic.ini stamp 20260924_0001
```

Do not run the baseline `upgrade` against an already-populated schema that was created with `Base.metadata.create_all()`; stamp it only after verification.


## Production API boundary

Authenticated `/api/v1/*` requests support a per-process API-key rate limit configured with:

```env
API_RATE_LIMIT_PER_MINUTE=120
```

Responses include `X-Request-ID`. Clients may provide their own `X-Request-ID` up to 128 characters; otherwise the API generates one.

HTTP and validation failures keep the existing `detail` field for compatibility and also return a machine-readable envelope:

```json
{
  "detail": "API key required",
  "error": {
    "code": "AUTH_REQUIRED",
    "message": "API key required",
    "request_id": "..."
  }
}
```

The built-in limiter is intentionally process-local. Multi-replica deployments should also enforce a shared rate limit at the API gateway or replace the limiter with a shared store.

Monitor lifecycle endpoints now include:

- `PATCH /api/v1/monitors/{id}`
- `DELETE /api/v1/monitors/{id}`

PATCH supports partial updates to monitor metadata, ASINs, geo profiles, provider mode, schedule, search depth, and enabled state. Tenant ownership is revalidated for all referenced geo profiles.


## Least-privilege API keys

API keys now carry explicit scopes. Existing/bootstrap keys use `*` for backward-compatible full access. New automation keys should request only what they need.

Available scopes:

- `geo:read`, `geo:write`
- `monitors:read`, `monitors:write`
- `rank:read`, `rank:write`
- `billing:read`, `billing:write`
- `keys:manage`
- `system:read`, `system:write`
- `*` for full access

Example:

```json
{
  "name": "rank-reporting",
  "scopes": ["geo:read", "monitors:read", "rank:read"]
}
```

A valid key that lacks a required scope receives HTTP 403 with error code `FORBIDDEN`.

## Readiness and worker heartbeats

`GET /health` is a process liveness check. `GET /ready` executes `SELECT 1` against the configured application database and returns HTTP 503 when the database cannot be reached. Docker Compose uses `/ready` for the API healthcheck.

Rank workers persist heartbeat state in `worker_heartbeats`. Authorized operators can inspect it with:

```http
GET /api/v1/system/workers
X-API-Key: <key with system:read>
```

Each heartbeat includes worker ID, status, last job ID/error, processed-job count, start time, and last-seen time. Set a unique `WORKER_ID` per worker replica.

## PostgreSQL CI

Backend CI starts PostgreSQL 17 and executes a real concurrent claiming test against `FOR UPDATE SKIP LOCKED`. This complements the default SQLite unit suite and protects the production multi-worker path from regressions.

Schema revision `20260924_0002` adds API-key scopes and worker heartbeat state. Existing databases already stamped at `20260924_0001` should run:

```bash
cd backend
alembic -c alembic.ini upgrade head
```


## Job reliability and dead-letter recovery

Rank jobs use a database-backed lease rather than assuming a worker will always exit cleanly. A claim records the worker ID and a lease expiry. While provider work is running, the worker renews the lease periodically.

If a worker process disappears, another worker detects the expired lease and recovers the job. Failed attempts use exponential backoff until `JOB_MAX_ATTEMPTS` is exhausted; the job then moves to `dead_letter` and remains visible for operator review.

Default controls:

```env
JOB_MAX_ATTEMPTS=3
JOB_LEASE_SECONDS=900
JOB_RETRY_BASE_SECONDS=30
JOB_RETRY_MAX_SECONDS=900
```

The retry delay is capped exponential backoff. A job is not claimable before its `available_at` time. Total provider failure is retried; partial rank results remain a completed `partially_succeeded` run.

Billing reservations are attempt-specific. When a stale lease is recovered, any still-reserved credits for that abandoned attempt are released before the next attempt is claimed.

Operators with `system:read` can inspect queue state and the DLQ. Requeueing a dead-letter job requires `system:write` and resets its attempt counter.

The Fantastic Admin console exposes this under **Workspace → System Status**, including queue counters, worker/scheduler heartbeats, last errors, and dead-letter requeue actions.

## Prometheus-compatible metrics

Authenticated operators can scrape:

```http
GET /api/v1/system/metrics
X-API-Key: <key with system:read>
```

The endpoint uses Prometheus text exposition and currently emits:

- `agrm_rank_jobs{status=...}`
- `agrm_queue_oldest_pending_age_seconds`
- `agrm_service_heartbeat_age_seconds{worker_id,worker_type,status}`
- `agrm_service_processed_jobs_total{worker_id,worker_type,status}`

Schedulers now emit the same persistent heartbeat records as rank workers. Set a unique `SCHEDULER_ID` for each scheduler replica.

## Strict verification effectiveness and cost analytics

Workspace operators with `system:read` can inspect windowed Strict Verification
performance:

```http
GET /api/v1/system/verification-analytics?hours=168
```

The endpoint supports 1–2160 hours and combines two existing immutable sources:
`rank_runs.verification_metadata` for verification outcomes and the credit
ledger for exact billing attribution.

It reports:

- requested, attempted, succeeded and skipped strict verification;
- automatic versus manually forced requests;
- forecast-aware automatic pacing deferrals and deferral percentage of automatic Strict requests;
- daily UTC pacing deferrals, excluding manual-force probes;
- recovered managed Geo probe failures;
- strict cache hits;
- normalized anomaly-trigger and skip-reason counts;
- exact credits settled under `auto_strict_verification`;
- estimated credits avoided through strict cache reuse;
- credits per successful verification;
- daily UTC activity.

Only `settlement` ledger rows count as spend. Credit reservations, releases,
and failed strict probes that release their reservation are not counted as
consumption.

Fantastic Admin exposes this in **Workspace → System Status** with selectable
24-hour, 7-day, 30-day and 90-day windows. The dashboard shows verification
effectiveness, recovered Geo failures, trigger/skip breakdowns, strict credit
spend and cache savings.

The detailed semantics are documented in
`docs/superpowers/specs/2026-09-27-phase-23-verification-analytics.md`.

## Daily Strict Verification credit guardrail

Workspace administrators can optionally set a live daily cap for new paid
Strict Verification credits under **Workspace → Team → Automatic strict
verification**.

The cap uses UTC-day accounting:

- unset: unlimited;
- `0`: block new paid Auto Strict / manually forced strict probes;
- positive integer: maximum committed Strict Verification credits for the UTC
  day.

The guardrail counts both settled Strict Verification credits and currently
reserved Strict Verification credits. Released reservations do not consume the
daily cap. Enforcement happens under the Workspace credit-account database row
lock, so concurrent PostgreSQL workers cannot overspend the same remaining
allowance.

The daily cap is intentionally live rather than snapshotted into queued jobs.
Lowering it affects jobs that are already queued. Manual force cannot bypass
it. Compatible strict cache hits remain allowed because they create no new
credit reservation.

A blocked verification is recorded as:

```text
skipped_reason = daily_credit_budget_exhausted
```

Run History records the effective cap, Rank Alerts can notify on
`strict_daily_budget_exhausted`, and System Status includes the reason
in its verification analytics.

Schema revision `20260927_0019` adds
`tenants.auto_strict_daily_credit_budget`.

Detailed semantics:
`docs/superpowers/specs/2026-09-27-phase-24-daily-strict-credit-guardrail.md`.

### Live daily budget status

The Workspace verification-policy response also reports the current UTC-day
guardrail state from the same credit reservations used for enforcement:

- settled Strict Verification credits;
- in-flight reserved Strict Verification credits;
- total committed credits;
- remaining credits;
- utilization percentage;
- UTC reset time.

This live status is intentionally different from the historical verification
cost analytics: historical cost counts immutable settlements, while live status
also includes in-flight reservations that currently consume the hard daily
allowance.

Fantastic Admin displays the status and 80%/100% warning states under both
**Workspace → Team** and **Workspace → System Status**. System Status refreshes
it every 10 seconds.

See
`docs/superpowers/specs/2026-09-27-phase-25-live-strict-budget-status.md`.

## Phase 9 migration

Schema revision `20260924_0003` adds rank-job availability, worker ownership, lease expiry, and maximum-attempt fields.

Existing production databases should run:

```bash
cd backend
alembic -c alembic.ini upgrade head
```

New databases continue to run all migrations through the existing Docker Compose migration gate.


## Audit trail and API key usage

Every authenticated REST request under `/api/v1/*` writes a tenant-scoped audit event after the response is produced. Audit events store metadata only:

- API key ID, never the plaintext key;
- request ID;
- HTTP method and path;
- response status;
- direct client socket IP;
- user agent;
- timestamp.

Request bodies, provider credentials, Stripe secrets, and API key plaintext are never written to the audit table.

API key records also track:

- `usage_count`;
- `last_used_at`;
- `last_used_ip`.

The server intentionally uses the direct socket address by default and does not trust `X-Forwarded-For` automatically. If a reverse proxy is introduced, proxy trust should be configured explicitly at the deployment boundary rather than accepting arbitrary forwarded headers.

Operators with `system:read` can query recent tenant events:

```http
GET /api/v1/system/audit?limit=100
X-API-Key: <key with system:read>
```

The Fantastic Admin System Status page displays recent audit events, and the API Keys page shows request count and last client IP.

## Shared Redis rate limiting

Set `REDIS_URL` on API replicas to share rate-limit state:

```env
API_RATE_LIMIT_PER_MINUTE=120
REDIS_URL=redis://redis:6379/0
```

API key plaintext is hashed with SHA-256 before being used as the limiter identity, so Redis keys do not expose credentials.

Redis is the primary limiter in multi-replica deployments. If Redis is temporarily unavailable, the API falls back to the existing process-local limiter instead of failing all requests. Docker Compose now includes Redis 7 and Backend CI executes a real two-instance shared-limit integration test.

## Phase 10 migration

Schema revision `20260924_0004` adds API-key request counters, last client IP, and tenant audit events.

Upgrade existing production databases with:

```bash
cd backend
alembic -c alembic.ini upgrade head
```


## SaaS human accounts and workspace RBAC

The web console now uses human accounts and short-lived-by-policy session credentials instead of treating a workspace API key as a browser login.

Automation remains separate:

- human browser sessions use `Authorization: Bearer agrs_...`;
- API integrations, MCP and CI continue to use `X-API-Key: agrm_...`;
- session tokens and invitation tokens are stored only as hashes in the database;
- passwords are hashed with Argon2;
- membership is rechecked on every session-authenticated request, so removing a member or changing a role takes effect without waiting for the session to expire.

Default session and invitation policy:

```env
ALLOW_PUBLIC_SIGNUP=true
SESSION_TTL_HOURS=720
INVITATION_TTL_HOURS=168
AUTH_RATE_LIMIT_PER_MINUTE=20
```

Public login and registration are rate-limited by direct client IP. When Redis is configured, this authentication limit is shared across API replicas using a separate `agrm:auth` namespace.

### Workspace roles

Human membership has four roles:

- **Owner** — full workspace access, including ownership and team administration.
- **Admin** — operational administration, billing, API keys, system status and team management; admins cannot create or modify Owner/Admin peers.
- **Analyst** — rank, monitor and geo read/write access plus billing/team visibility.
- **Viewer** — read-only rank, monitor, geo, billing and team visibility.

The last Owner cannot be demoted or removed.

### Account API

Public/session endpoints:

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`
- `POST /api/v1/auth/logout`
- `POST /api/v1/auth/switch-workspace`
- `POST /api/v1/auth/accept-invitation`

Team endpoints:

- `GET /api/v1/team/members`
- `GET /api/v1/team/invitations`
- `POST /api/v1/team/invitations`
- `PATCH /api/v1/team/members/{user_id}`
- `DELETE /api/v1/team/members/{user_id}`

Invitations return a plaintext `agri_...` token only when created. The database stores only its SHA-256 hash. The Fantastic Admin Team page turns that one-time token into a shareable `#/login?invite=...` link.

### Migrating an API-key-only workspace

Existing API keys continue to work. A legacy workspace can create its first human Owner with an API key that has `team:manage` (bootstrap `*` keys already qualify):

```http
POST /api/v1/team/bootstrap-owner
X-API-Key: agrm_...
Content-Type: application/json

{
  "email": "owner@example.com",
  "password": "use-a-strong-password",
  "display_name": "Workspace Owner"
}
```

Bootstrap only creates a new account. If the email already belongs to an account, use a normal workspace invitation instead; the bootstrap endpoint will not impersonate or issue a session for an existing user.

### Browser console

The login page now provides:

- email/password sign-in;
- new workspace registration;
- invitation-aware registration/joining;
- a Legacy API Key option for migration compatibility.

Workspace → **Team** provides membership roles, invitation creation, member removal and workspace switching. Workspace API Keys remain available for machine-to-machine use.

### Audit identity

Audit events now distinguish `session` and `api_key` actors and can store the human `user_id` for session-authenticated requests. Request bodies and plaintext credentials remain excluded.

## Phase 11 migration

Schema revision `20260924_0005` adds:

- `users`;
- `workspace_memberships`;
- `user_sessions`;
- `workspace_invitations`;
- human actor fields on `audit_events`.

Upgrade an existing database with:

```bash
cd backend
alembic -c alembic.ini upgrade head
```


## Secure browser sessions

Human browser authentication now uses a host-only HttpOnly session cookie instead of persisting the `agrs_...` session token in `localStorage`.

The browser receives two cookies:

- `agrm_session` — HttpOnly session credential; JavaScript cannot read it.
- `agrm_csrf` — per-session CSRF token; the web client mirrors it into `X-CSRF-Token` on unsafe requests.

The CSRF token is also bound to the server-side session by a SHA-256 hash. Cookie-authenticated `POST`, `PUT`, `PATCH`, and `DELETE` requests are rejected unless the cookie, header, and stored session hash all agree.

Bearer sessions remain accepted for non-browser compatibility, and API keys continue to use `X-API-Key`. CSRF enforcement applies only to cookie-authenticated human sessions.

Recommended production settings:

```env
SESSION_COOKIE_NAME=agrm_session
CSRF_COOKIE_NAME=agrm_csrf
SESSION_COOKIE_SECURE=true
SESSION_COOKIE_SAMESITE=lax
```

Use HTTPS whenever `SESSION_COOKIE_SECURE=true`. Local HTTP development keeps the default `false`. The default frontend API base URL is now `http://localhost:8000` so the Vite frontend at `http://localhost:5173` remains same-site for development cookies.

Credentialed CORS is enabled only for configured `CORS_ORIGINS`; do not use wildcard origins with cookie sessions.

### Session management

Human users can inspect and control active sessions:

- `GET /api/v1/auth/sessions`
- `DELETE /api/v1/auth/sessions/{session_id}`
- `POST /api/v1/auth/logout`
- `POST /api/v1/auth/logout-all`
- `POST /api/v1/auth/change-password`

Session metadata includes creation time, last-seen time, direct client IP and user agent. Password changes keep the current session and revoke every other active session.

The Fantastic Admin console exposes these controls under **Workspace → Account Security**.

## Phase 12 migration

Schema revision `20260925_0006` adds per-session CSRF hashes and device metadata:

- `user_sessions.csrf_hash`
- `user_sessions.created_ip`
- `user_sessions.last_seen_ip`
- `user_sessions.user_agent`

Upgrade existing deployments with:

```bash
cd backend
alembic -c alembic.ini upgrade head
```

Existing Phase 11 browser sessions should sign in again after deployment so the browser receives the new HttpOnly session and CSRF cookies.


## Email verification and account recovery

Phase 13 adds email ownership verification, privacy-safe password recovery, login lockout and user-visible authentication history.

New accounts created through public registration start with an unverified email address. Accounts created from a valid workspace invitation are marked verified because possession of the invitation link proves access to the invited mailbox.

Existing users are backfilled as verified by migration `20260925_0007`, so upgrading an existing deployment does not lock current users out.

Account endpoints:

- `POST /api/v1/auth/verify-email`
- `POST /api/v1/auth/resend-verification`
- `POST /api/v1/auth/forgot-password`
- `POST /api/v1/auth/reset-password`
- `GET /api/v1/auth/security-events`

Verification tokens use an `agrv_...` prefix. Password reset tokens use `agrr_...`. Only SHA-256 hashes are stored in the database. Creating a new token invalidates previous unused tokens of the same type, and a successful verification/reset consumes the token permanently.

Forgot-password always returns the same accepted response whether or not the account exists. This prevents the recovery endpoint from becoming an email-enumeration oracle.

Password reset:

- validates the single-use reset token;
- updates the Argon2 password hash;
- clears failed-login counters and account lock state;
- revokes every active session;
- records a security event.

### Login lockout

Default policy:

```env
LOGIN_MAX_FAILURES=5
LOGIN_LOCK_MINUTES=15
```

Repeated invalid passwords increment a per-user failure counter. Reaching the threshold temporarily locks the account and login responds with HTTP `423 Locked`. A successful login clears the counter. A successful password reset also clears any lock.

Login success, login failure, lockouts, reset requests/completions, registration and email verification are written to `auth_events`. Users can review their own events in **Workspace → Account Security**.

### Email delivery

Without SMTP configuration, the fallback sender does not send mail or log message
bodies, recipients, verification links or reset tokens. Email alert attempts and
scheduled report attempts are recorded as `failed` with
`Email delivery is not configured`; reports have `sent_count=0`.
Other alert channels can still deliver independently. Configure SMTP to enable email:

```env
PUBLIC_WEB_URL=https://app.example.com
EMAIL_VERIFICATION_TTL_HOURS=24
PASSWORD_RESET_TTL_MINUTES=30

SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=...
SMTP_FROM_EMAIL=no-reply@example.com
SMTP_STARTTLS=true
```

Apply the same settings to the API, worker and scheduler, then restart those
processes. **Workspace → Rank Alerts**, **Ranking → Analytics & Reports** and
**Workspace → System Status** show a warning when email is not configured, with
**Refresh delivery status** to recheck. Rules and schedules can still be prepared.
If the status request fails, the notice reports that failure and offers a retry.
System Status also shows when email is configured.

`GET /api/v1/notifications/status` requires authentication and `monitors:read`.
It returns only `{"email":{"configured":true}}` (or `false`), with no SMTP host,
credentials or sender address. This is a configuration check of the API process,
not an SMTP connection test or proof of mailbox delivery. In non-Compose deployments,
ensure the worker and scheduler have the same configuration. Use the
[staging readiness runbook](docs/STAGING_READINESS.md) for live integration checks.

Review **Recent alert events → Delivery** and **Report delivery history** for the
result and safe error reason for each attempt. `sent` means the SMTP server accepted
the message, not that it reached the inbox. Failed attempts remain in history and
are not automatically replayed; after fixing configuration, use a report's
**Send now** action or wait for the next scheduled report/new alert event. Existing
historical statuses are not rewritten by this update.

Registration and password recovery keep their privacy-safe responses even if email
cannot be sent. A recovery response does not reveal whether an account exists or
whether its message was delivered. Verify SMTP before enabling public signup.

The sender abstraction is intentionally separate from account logic, so a managed provider such as SES, Postmark or Resend can replace SMTP later without changing recovery-token behavior.

Workspace invitations are also delivered through the same sender while the console continues to expose the one-time invitation link for manual sharing.

### Browser flows

The Fantastic Admin frontend now includes:

- **Recover** on the sign-in page;
- `/#/reset-password?token=...`;
- `/#/verify-email?token=...`;
- email verification state and resend control in Account Security;
- recent authentication/security events with result, IP and user agent.

## Phase 13 migration

Schema revision `20260925_0007` adds:

- `users.email_verified_at`;
- `users.failed_login_count`;
- `users.locked_until`;
- `users.last_login_at`;
- `users.last_login_ip`;
- `account_tokens`;
- `auth_events`.

Upgrade with:

```bash
cd backend
alembic -c alembic.ini upgrade head
```


## TOTP MFA, recovery codes and trusted devices

Phase 14 adds human-account multi-factor authentication without changing machine authentication.

Human browser accounts can enroll a standard TOTP authenticator from **Workspace → Account Security**. The TOTP secret is encrypted at rest with Fernet. Recovery codes are high-entropy one-time codes stored only as SHA-256 hashes.

Password login for an MFA-enabled user is now two-stage:

1. email/password is validated;
2. the API returns a short-lived `agrmfa_...` challenge instead of creating a session;
3. `POST /api/v1/auth/mfa/complete` accepts a TOTP or unused recovery code;
4. only successful second-factor verification creates the normal HttpOnly browser session.

A user may mark the browser as trusted. The trusted-device credential is a separate high-entropy `agrd_...` HttpOnly cookie. The database stores only its hash. Trusted-device bypasses are revoked when the user changes or resets the password, disables MFA, or signs out everywhere.

Default MFA settings:

```env
MFA_ENCRYPTION_KEY=
MFA_ISSUER=Amazon Geo Rank Monitor
MFA_CHALLENGE_MINUTES=5
TRUSTED_DEVICE_DAYS=30
TRUSTED_DEVICE_COOKIE_NAME=agrm_trusted_device
```

When `MFA_ENCRYPTION_KEY` is empty, the service derives the encryption key from `API_KEY_PEPPER` for backward-compatible deployment. Production deployments should set a dedicated, stable `MFA_ENCRYPTION_KEY` and protect it like any other encryption secret. Changing that key without re-enrollment makes existing encrypted TOTP secrets unreadable.

### MFA API

Authenticated account setup endpoints:

- `POST /api/v1/auth/mfa/enroll`
- `POST /api/v1/auth/mfa/enroll/verify`
- `POST /api/v1/auth/mfa/recovery-codes/regenerate`
- `POST /api/v1/auth/mfa/disable`

Password-login second step:

- `POST /api/v1/auth/mfa/complete`

Enrollment requires a verified email address. Recovery codes are returned in plaintext only when MFA is enabled or codes are regenerated. Each recovery code can be consumed once.

### Workspace-required MFA

Workspace Owners can manage the policy through:

- `GET /api/v1/team/security-policy`
- `PATCH /api/v1/team/security-policy`

When `require_mfa=true`:

- human sessions must have completed MFA before any scoped workspace API can be used;
- Account Security remains reachable so a newly invited member can enroll MFA;
- enabling the policy requires every current member to already have MFA enabled;
- future invited members may join, but remain restricted until enrollment is complete;
- a user cannot disable MFA while any workspace membership requires it;
- API keys, MCP and CI integrations remain independent from the human MFA policy.

The Team page shows every member's MFA state and exposes the policy switch to Workspace Owners.

### Session and recovery security

MFA-authenticated sessions record `mfa_authenticated_at`. Workspace switching preserves the current session's MFA-authenticated state. Password reset and password change revoke trusted devices. `logout-all` also revokes trusted-device bypasses.

The login UI accepts either a 6-digit TOTP or a recovery code. A required-MFA session is automatically redirected to **Workspace → Account Security** instead of failing repeatedly on business APIs.

## Phase 14 migration

Schema revision `20260925_0008` adds:

- `tenants.require_mfa`;
- `users.mfa_secret_encrypted`;
- `users.mfa_enabled_at`;
- `users.mfa_last_verified_at`;
- `user_sessions.mfa_authenticated_at`;
- `account_tokens.details`;
- `mfa_recovery_codes`;
- `trusted_devices`.

Upgrade with:

```bash
cd backend
alembic -c alembic.ini upgrade head
```


## Enterprise SSO with OpenID Connect

Phase 15 adds workspace-scoped Enterprise SSO for Google Workspace, Microsoft Entra ID and standards-compatible RS256 OpenID Connect providers.

The browser uses Authorization Code + PKCE. SSO state and nonce values are single-use and short-lived. The backend performs the code exchange, validates the signed ID token, and only then creates the normal HttpOnly application session.

The web frontend never receives the OIDC client secret, PKCE verifier, application session token, or raw ID token.

### OIDC validation

The backend validates:

- discovery issuer equality;
- HTTPS provider endpoints;
- RS256 signature against the provider JWKS;
- `kid`, issuer and audience;
- `azp` when an ID token contains multiple audiences;
- expiration, not-before and issued-at timestamps;
- the per-login nonce;
- a stable OIDC subject (`sub`);
- allowed workspace email domains;
- explicit `email_verified=false` rejection.

Workspace identity bindings are stored by `workspace + issuer + subject`. Email is used for the controlled first bind/JIT decision, not as the permanent external identity key.

### Provider configuration

Workspace Owners configure SSO under **Workspace → Team → Enterprise SSO**.

Google Workspace normally uses:

```text
Provider: Google Workspace
Issuer: https://accounts.google.com
```

Microsoft Entra ID should use the tenant-specific v2.0 issuer rather than a multi-tenant `common` issuer:

```text
https://login.microsoftonline.com/<tenant-id>/v2.0
```

Generic OIDC providers must expose standard discovery at:

```text
<issuer>/.well-known/openid-configuration
```

and currently must sign ID tokens with RS256.

Register the application redirect URI at the identity provider exactly as configured by:

```env
SSO_CALLBACK_URL=https://api.example.com/api/v1/auth/sso/callback
```

The frontend URL is configured separately through `PUBLIC_WEB_URL`; successful callbacks return to `/#/sso-complete`, where the frontend hydrates the already-created HttpOnly application session.

### SSO secret encryption

Recommended production configuration:

```env
SSO_ENCRYPTION_KEY=<stable high-entropy secret>
SSO_CALLBACK_URL=https://api.example.com/api/v1/auth/sso/callback
SSO_TRANSACTION_MINUTES=5
PUBLIC_WEB_URL=https://app.example.com
SESSION_COOKIE_SECURE=true
```

OIDC client secrets and PKCE verifiers are encrypted with Fernet before being stored. If `SSO_ENCRYPTION_KEY` is omitted, the service falls back to `MFA_ENCRYPTION_KEY` and then `API_KEY_PEPPER` for deployment compatibility. Production should use a dedicated stable SSO key.

Do not rotate `SSO_ENCRYPTION_KEY` without a migration/reconfiguration plan; existing encrypted client secrets cannot be decrypted with a different key.

### Safe SSO rollout

SSO rollout intentionally has two stages:

1. save and enable the OIDC connection;
2. use **Test SSO** as a Workspace Owner.

A connection is marked `verified_at` only after a real successful Owner SSO callback. `enforce_sso=true` is rejected until the connection is both enabled and verified.

Changing the issuer, client ID or client secret clears verification and automatically disables enforcement. Changing allowed email domains also disables enforcement so the new access boundary must be reviewed before it is required. Disabling the connection also disables enforcement.

This prevents a mistyped issuer or client credential from immediately locking the workspace out.

### SSO enforcement

When Enterprise SSO is enforced:

- local email/password login is rejected for that workspace;
- an existing local session cannot switch into the workspace;
- every scoped human API request verifies that the current session was issued by that exact workspace's SSO connection;
- an SSO session from Workspace A cannot satisfy Workspace B's SSO requirement;
- API keys, MCP and CI automation remain independent from the human SSO policy.

Existing sessions read the current workspace SSO policy on every authenticated request, so enabling enforcement also protects sessions created before the policy change.

A `team:manage` API key has one deliberately narrow break-glass capability: it may set SSO enforcement to `false`. API keys cannot enable enforcement or change the issuer/client configuration.

### Domain controls and JIT

Each SSO connection has one or more allowed email domains.

With JIT disabled, the OIDC identity must resolve to an existing user who is already a member of the workspace.

With JIT enabled:

- an existing account with an allowed email may be added to the workspace as Viewer;
- an unknown allowed-domain user may be created and joined as Viewer;
- a newly JIT-created SSO user receives an unguessable random local password hash and does not receive a reusable default password.

After first binding, future logins use OIDC issuer + subject rather than relying on the email string.

### SSO and MFA

SSO does not automatically imply MFA.

If the ID token `amr` claim explicitly includes an MFA/OTP/hardware/software-key signal, the application session is marked MFA-authenticated. Otherwise a workspace with `require_mfa=true` requires the user to complete local TOTP/recovery-code verification in **Account Security** before scoped workspace APIs are available.

This allows Workspace Owners to combine:

- IdP-only SSO;
- SSO + local TOTP;
- or IdP-asserted MFA.

### Enterprise SSO API

Public authentication flow:

- `GET /api/v1/auth/sso/discover?email=...`
- `POST /api/v1/auth/sso/start`
- `GET /api/v1/auth/sso/callback`

Authenticated current-session MFA:

- `POST /api/v1/auth/mfa/session-verify`

Workspace Owner controls:

- `GET /api/v1/team/sso-config`
- `PUT /api/v1/team/sso-config`
- `PATCH /api/v1/team/sso-config/enforcement`

Public SSO discovery/start are protected by the authentication IP rate limiter.

## Phase 15 migration

Schema revision `20260925_0009` adds:

- `workspace_sso_configs`;
- `sso_login_transactions`;
- `sso_identities`;
- `user_sessions.auth_method`;
- `user_sessions.sso_owner_id`.

Upgrade with:

```bash
cd backend
alembic -c alembic.ini upgrade head
```


## SCIM 2.0 provisioning

Phase 16 adds workspace-scoped SCIM 2.0 provisioning for enterprise identity providers.

SCIM complements Enterprise SSO rather than replacing it:

- OIDC SSO controls how human users authenticate.
- SCIM controls user lifecycle, workspace membership state and IdP-driven role assignment.
- API keys, MCP and CI automation remain separate machine-authentication paths.

### Supported SCIM surface

The SCIM base path is:

```text
https://<api-origin>/scim/v2
```

The service supports:

- `GET /ServiceProviderConfig`
- `GET /ResourceTypes`
- `GET /Schemas`
- `GET /Users`
- `POST /Users`
- `GET /Users/{id}`
- `PUT /Users/{id}`
- `PATCH /Users/{id}`
- `DELETE /Users/{id}`
- `GET /Groups`
- `POST /Groups`
- `GET /Groups/{id}`
- `PUT /Groups/{id}`
- `PATCH /Groups/{id}`
- `DELETE /Groups/{id}`

Responses use `application/scim+json`. SCIM errors use the standard
`urn:ietf:params:scim:api:messages:2.0:Error` envelope.

Supported filters include the common provisioning forms:

```text
userName eq "person@example.com"
externalId eq "idp-user-id"
id eq "<scim-resource-id>"
displayName eq "Engineering"
```

Pagination uses `startIndex` and `count`, with a maximum page size of 200.

Bulk and sort are intentionally not advertised as supported.

### Provisioning token

Workspace Owners configure SCIM in **Workspace → Team → SCIM provisioning**.

Generate a provisioning token and configure the IdP with:

```http
Authorization: Bearer agrscim_...
```

The plaintext token is shown once. The database stores only a token prefix and
an HMAC hash. Rotating the token immediately invalidates the previous token.

Recommended production configuration:

```env
SCIM_TOKEN_PEPPER=<independent high-entropy secret>
```

For backward-compatible deployments, `SCIM_TOKEN_PEPPER` falls back to
`API_KEY_PEPPER` when unset. Production should use a dedicated value.

### User lifecycle semantics

A SCIM User maps to one workspace membership, not to the global user identity.

This distinction is deliberate: a person may belong to multiple workspaces.
Deprovisioning from one enterprise must not disable their unrelated workspace
access.

When a SCIM user is deactivated or deleted:

- the workspace membership is marked suspended;
- every active browser session for that user in that workspace is revoked;
- the global user record remains intact;
- memberships and sessions in other workspaces remain untouched;
- normal workspace switching, SSO login and existing-session validation reject
  the suspended membership.

SCIM `DELETE /Users/{id}` therefore behaves as a reversible workspace-level
deprovision operation. Re-provisioning or setting `active=true` can reactivate
the same membership.

SCIM-created users receive a high-entropy random local password hash and their
email is treated as verified for the trusted provisioning flow.

### Stable user identity

The SCIM resource `id` is the workspace membership ID. `externalId` may be
stored per workspace.

`userName` must currently be an email address. Changing `userName` through
SCIM is deliberately rejected because the underlying user identity can be
shared across multiple workspaces. This avoids one enterprise IdP silently
rewriting another workspace's login identity.

### Ownership protection

SCIM can assign only:

- `admin`
- `analyst`
- `viewer`

SCIM can never create, promote, demote or take over a Workspace Owner.
Ownership remains an explicit human administrative boundary.

### Group-driven roles

IdP groups synchronized through `/Groups` appear in the Team SCIM console.
Workspace Owners can map each group to:

- Admin
- Analyst
- Viewer
- no mapping

If a SCIM-managed user belongs to multiple mapped groups, role precedence is:

```text
Admin > Analyst > Viewer
```

If no mapped group applies, the workspace SCIM default role is used. Changing
the default role immediately recomputes SCIM-managed memberships that are not
overridden by a higher mapped-group role.

Manual role controls are disabled in the Team UI for SCIM-managed members to
avoid configuration fights between the application and the identity provider.

### SCIM authentication, rate limiting and audit

SCIM requests use a dedicated Bearer token. They still pass through the normal
API request boundary:

- request IDs are returned in `X-Request-ID`;
- the configured API rate limiter applies;
- rate-limit failures use SCIM error JSON;
- successful authenticated SCIM requests are recorded in the audit log with
  `actor_type=scim`.

### Identity-provider setup

The exact administrator UI varies by identity provider, but the application
side is always:

1. As a Workspace Owner, open **Workspace → Team → SCIM provisioning**.
2. Choose the default workspace role and enable SCIM.
3. Generate or rotate the provisioning token.
4. Configure the IdP provisioning base URL as
   `https://<api-origin>/scim/v2`.
5. Configure the generated Bearer token.
6. Enable user and, if desired, group provisioning in the IdP.
7. After groups synchronize, map IdP groups to workspace roles in the Team page.

The generated token is not stored in browser local storage and cannot be
retrieved again after the one-time display dialog is closed.

### Phase 16 migration

Alembic revision `20260925_0010` adds:

- `workspace_scim_configs`;
- `scim_groups`;
- `scim_group_members`;
- `workspace_memberships.suspended_at`;
- `workspace_memberships.scim_managed`;
- `workspace_memberships.scim_external_id`;
- `workspace_memberships.updated_at`;
- a workspace-scoped unique constraint for SCIM external IDs.

Existing memberships remain active and non-SCIM-managed after migration.

Upgrade with:

```bash
cd backend
alembic -c alembic.ini upgrade head
```


## Rank alerts and notifications

Phase 17 adds proactive ranking alerts on top of completed monitor runs. Alert evaluation happens only after a rank job has reached a successful or partially successful terminal state. Provider retries and failed rank jobs do not emit ranking-change alerts.

Supported rule types:

- `rank_drop`: weighted aggregate rank becomes worse by at least N positions compared with the previous completed run for the same Monitor.
- `rank_improve`: weighted aggregate rank improves by at least N positions.
- `enters_top_n`: weighted rank crosses from below the configured Top N boundary into it.
- `exits_top_n`: weighted rank crosses out of the configured Top N boundary.
- `not_found`: the ASIN has zero aggregate found weight in the current run.
- `geo_not_found`: the ASIN is not found for a matching geographic observation.
- `geo_rank_above`: a geographic observation has an effective rank worse than the configured threshold.
- `strict_verification_failed`: a strict upstream verification attempt fails.
- `strict_insufficient_credits`: strict verification is requested but skipped because prepaid credits are insufficient.
- `strict_daily_budget_pacing_deferred`: an automatic paid strict probe is intentionally deferred by forecast-aware pacing; the alert event preserves the estimated resume time and current pacing allowance.
  Email, Slack and webhook alert summaries also show the **estimated** resume timestamp and paced credit allowance when available; the estimate is advisory, not a guaranteed restart time.
- `strict_probe_budget_exhausted`: a requested strict probe is skipped because the per-run upstream budget is exhausted.
- `strict_provider_unavailable`: the strict browser provider is unavailable when verification is requested.
- `strict_runtime_disabled`: a manually forced strict verification is blocked by the runtime global kill switch.

Strict verification rules are probe-level rather than ASIN-level. They may optionally
scope to one Geo in the Monitor; otherwise they watch every verification event in the
run. A single strict SERP probe therefore produces at most one matching alert event per
rule and Geo instead of one duplicate notification per tracked ASIN.

Rules are always evaluated against the same `monitor_target_id`; a run from another Monitor with the same keyword cannot become the comparison baseline.

### Cooldown and deduplication

Each rule has `cooldown_minutes`. Cooldown is scoped to the rule + ASIN + geo + event type, which suppresses repeated identical alerts while allowing unrelated ASINs or geographies to notify independently.

Each emitted event also has a deterministic per-run fingerprint. Re-evaluating the same run cannot create duplicate event rows.

Archiving a rule is a soft delete. Historical alert events and delivery records are retained for incident review and audit.

### Notification channels

A rule may contain one or more of:

- email recipients;
- Slack Incoming Webhook;
- generic HTTPS webhook.

Email uses the same SMTP sender configured for account verification/recovery.

Slack webhook URLs are restricted to official Slack webhook hosts.

Generic webhooks are disabled unless the destination hostname is explicitly present in:

```env
ALERT_WEBHOOK_ALLOWED_HOSTS=alerts.example.com,automation.example.com
```

Private/loopback/link-local IP literal destinations are rejected. For production, network-level egress policy should still restrict worker outbound traffic to the intended notification destinations.

Generic webhooks include:

- `event=rank_alert.triggered`;
- stable `event_id`;
- rule, Monitor and run IDs;
- ASIN and geo;
- previous/current values;
- event details.

The request also carries `X-AGRM-Event-ID` so receivers can implement idempotency.

### Destination secret encryption

Notification channel configuration is encrypted with Fernet before storage. Slack and generic webhook secret URLs are never returned by the API after creation.

Production should configure a dedicated stable key:

```env
ALERT_ENCRYPTION_KEY=<stable high-entropy secret>
ALERT_WEBHOOK_ALLOWED_HOSTS=
```

If `ALERT_ENCRYPTION_KEY` is omitted, the runtime falls back to `MFA_ENCRYPTION_KEY` and then `API_KEY_PEPPER` for deployment compatibility. API and worker processes must use the same effective key.

Do not rotate `ALERT_ENCRYPTION_KEY` without a migration/re-encryption plan; existing channel configuration cannot be decrypted by a different key.

### Delivery failure semantics

Notification delivery is best-effort after the rank job is completed. Email, Slack or webhook failures are stored as `rank_alert_deliveries.status=failed` with a bounded error message.

A notification outage never changes an already completed rank job back to failed/retry. Ranking data remains authoritative even when a downstream notification channel is unavailable.

### Alert API

Read access uses the existing `monitors:read` scope. Rule mutation uses `monitors:write`.

- `GET /api/v1/alerts/rules`
- `POST /api/v1/alerts/rules`
- `PATCH /api/v1/alerts/rules/{rule_id}`
- `DELETE /api/v1/alerts/rules/{rule_id}` (archive)
- `GET /api/v1/alerts/events`

Fantastic Admin exposes **Workspace → Rank Alerts**, including rule configuration, Monitor/ASIN/Geo scoping, cooldown, channel state, alert event history and delivery status. The Monitors screen also links directly into alert creation for a selected Monitor.

## Phase 17 migration

Schema revision `20260925_0011` adds:

- `rank_alert_rules`;
- `rank_alert_events`;
- `rank_alert_deliveries`.

Upgrade with:

```bash
cd backend
alembic -c alembic.ini upgrade head
```


## Historical analytics and scheduled reports

Phase 18 adds monitor-scoped historical analytics, CSV export and scheduled stakeholder email reports.

Analytics are derived directly from completed rank jobs and their existing rank runs, snapshots and geographic observations. The system does not maintain a second analytics copy of ranking results, so the underlying rank run remains the source of truth.

### Historical analytics

Analytics queries are always scoped by both workspace and Monitor. A run belonging to another tenant or another Monitor cannot become part of the same trend even when the keyword or ASIN is identical.

Supported windows are 1 hour through 1 year.

Monitor analytics include:

- weighted aggregate rank history per ASIN;
- first and latest rank in the selected window;
- rank change, where a negative value means improvement;
- best, worst and average weighted rank;
- average confidence;
- aggregate found rate;
- geographic effective-rank averages;
- geographic best/worst rank;
- geographic found rate and observation count.

REST endpoints:

```http
GET /api/v1/analytics/monitors/{monitor_id}/trend?hours=168
GET /api/v1/analytics/monitors/{monitor_id}/summary?hours=168
GET /api/v1/analytics/monitors/{monitor_id}/export.csv?hours=168&granularity=aggregate
GET /api/v1/analytics/monitors/{monitor_id}/export.csv?hours=168&granularity=geo
```

These endpoints require `rank:read`.

The CSV export is generated on demand from the same tenant-scoped historical query used by the UI. Aggregate exports contain weighted snapshots; geographic exports contain individual regional observations.

### Scheduled reports

Workspace administrators can create reports that combine one or more Monitors and deliver a text summary by email. Reports can optionally attach one aggregate CSV file per Monitor.

Each schedule contains:

- report name;
- one or more Monitor IDs;
- recipient email addresses;
- a standard five-field UTC cron expression;
- a lookback window;
- CSV attachment on/off;
- enabled state.

Report schedule configuration and delivery history use `system:read`; creating, changing, archiving or manually sending reports uses `system:write`.

REST endpoints:

```http
GET    /api/v1/reports/schedules
POST   /api/v1/reports/schedules
PATCH  /api/v1/reports/schedules/{schedule_id}
DELETE /api/v1/reports/schedules/{schedule_id}
POST   /api/v1/reports/schedules/{schedule_id}/send
GET    /api/v1/reports/deliveries
```

### Report scheduling semantics

The existing scheduler process dispatches both Monitor rank jobs and scheduled reports.

Like Monitor schedules, reports use five-field cron expressions interpreted in UTC. The scheduler considers only the latest due slot and does not replay every missed historical slot after downtime.

Before sending, the scheduler reserves a `report_deliveries` row. The database unique constraint on `schedule_id + scheduled_for` makes a cron slot idempotent across repeated scans and multiple scheduler replicas.

A delivery records:

- scheduled time;
- status: `sent`, `partially_failed` or `failed`;
- recipient count;
- successful send count;
- subject;
- bounded error text;
- a compact stored rank summary.

One failed recipient does not erase successful recipient deliveries, and report delivery failures never alter underlying rank jobs or rank runs.

### Recipient encryption

Report recipient lists are encrypted with Fernet before storage.

Production should set a stable independent key:

```env
REPORT_ENCRYPTION_KEY=<stable high-entropy secret>
```

If omitted, the runtime falls back to `MFA_ENCRYPTION_KEY` and then `API_KEY_PEPPER` for deployment compatibility.

API and scheduler processes must use the same effective encryption key. Do not rotate `REPORT_ENCRYPTION_KEY` without a migration/re-encryption plan; existing encrypted recipient lists cannot be decrypted with a different key.

The scheduler also requires the same SMTP configuration already used by account emails:

```env
SMTP_HOST=...
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=...
SMTP_FROM_EMAIL=...
SMTP_STARTTLS=true
```

### Fantastic Admin

The console exposes **Rank Monitoring → Analytics & Reports**.

The page includes:

- Monitor and time-window selection;
- per-ASIN trend sparklines;
- current/change/best/worst/average rank cards;
- geographic performance table;
- aggregate and geographic CSV export;
- Admin report schedule creation/editing;
- manual **Send now**;
- delivery history.

Users without report-management permissions can still use historical analytics and CSV export when they have rank read access.

## Phase 18 migration

Alembic revision `20260925_0012` adds:

- `report_schedules`;
- `report_deliveries`;
- the unique report schedule/slot idempotency constraint.

Existing production databases should run:

```bash
cd backend
alembic -c alembic.ini upgrade head
```


## Billing-aware SERP probe cache

Phase 19 implements the reusable SERP probe cache from the original SaaS design. Cache reuse happens before ASIN matching, because the billable/upstream unit is the SERP probe rather than an individual ASIN.

A cache identity contains the fields that materially affect the upstream SERP:

- tenant / workspace;
- provider mode, provider name and verification level;
- marketplace and keyword;
- requested IP country/state/city/postal code;
- Amazon delivery country/postal code;
- device;
- search depth.

Geo Profile display name, profile ID and weighting are deliberately excluded from the cache identity. This means a weight-only edit can reuse the same compatible SERP and recalculate weighted rank, while an IP location, delivery location, device, search-depth or provider change produces a cache miss.

Cache entries are tenant-scoped and are never shared across workspaces.

### Default cache policy

```env
PROBE_CACHE_MANAGED_TTL_SECONDS=300
PROBE_CACHE_STRICT_TTL_SECONDS=0
PROBE_CACHE_RETENTION_HOURS=24
```

Managed probes reuse a compatible result for five minutes by default. Strict browser verification is uncached by default so an explicit strict verification continues to perform a fresh residential/browser probe. Strict caching can be enabled intentionally by setting a positive strict TTL.

The cache is an optimization rather than a correctness dependency. Cache lookup/store failures fail open and the normal provider path continues.

### Billing behavior

Before a paid request or scheduled worker run, the application preflights fresh compatible cache entries.

Only expected cache misses are included in the credit reservation. After execution, settlement charges only successfully completed upstream probes.

Therefore:

- cache hits do not consume credits as new upstream probes;
- a fully cached request creates no credit reservation;
- a fully cached request can run even when the workspace has zero available credits;
- if another worker fills a cache entry after preflight, the unused reservation is released during settlement;
- provider failures are not converted into cache hits and are not cached.

For rank runs, `settled_probe_count` now explicitly represents successfully completed upstream/billable probes. `cache_hit_count` records reused probes separately.

### Provenance and transparency

Every request still creates a new RankRun and new RankObservation / RankSnapshot rows so historical analytics remain continuous.

Each observation exposes:

- `probe_source=upstream|cache`;
- `cache_age_seconds` for cached observations;
- the original `observed_at` fetch timestamp.

Direct REST/MCP rank-check responses also expose:

```json
{
  "usage": {
    "requested_probe_count": 5,
    "upstream_probe_count": 2,
    "cache_hit_count": 3,
    "billable_probe_count": 2
  }
}
```

Fantastic Admin Rank Explorer and Run History display the same usage/provenance so cache savings are visible rather than implicit.

## Phase 19 migration

Schema revision `20260925_0013` adds:

- `serp_probe_cache`;
- `rank_runs.cache_hit_count`;
- `rank_observations.probe_source`;
- `rank_observations.cache_age_seconds`.

Upgrade existing deployments with:

```bash
cd backend
alembic -c alembic.ini upgrade head
```


## SERP competitive intelligence and share of voice

Phase 20 turns each successful geographic SERP probe into reusable competitive intelligence instead of discarding products that were not explicitly configured on the Monitor.

For every successful `run + Geo Profile`, the system persists one compact row per discovered ASIN with its best:

- organic position;
- sponsored position;
- absolute SERP position;
- captured title;
- probe source (`upstream` or `cache`);
- cache age when applicable;
- original SERP observation timestamp.

An ASIN that appears in both organic and sponsored results is stored once for that geo/run.

### Share of voice

The Monitor competitive summary calculates two different visibility concepts deliberately:

- **Organic SOV** — the ASIN's placements divided by all captured organic Top-N slots, including tracked products. This represents its share of the whole observed SERP rather than only the filtered competitor table.
- **Geo coverage** — the percentage of Monitor geo probes in which that ASIN appeared organically inside Top-N.

Sponsored SOV and sponsored geo coverage are calculated independently.

The summary also includes:

- best and average organic rank;
- latest run-level average organic rank;
- change from the previous completed run, where negative means improvement;
- best/average sponsored rank;
- run count and Geo Profile count;
- per-Geo top competitor leaders.

Tracked Monitor ASINs are excluded from the competitor table by default but can be included as a benchmark. Excluding them from the table does not remove them from the SOV denominator.

### Competitive trend

The trend API groups competitors by completed Monitor run and returns:

- average organic rank;
- best organic rank;
- organic geo-probe coverage;
- sponsored appearances.

This supports direct comparison of the most visible competing ASINs through time without running extra Amazon requests.

### Cache behavior

Phase 19 SERP cache reuse is compatible with competitive intelligence.

A cache hit still creates a new competitive observation set for the current RankRun so Monitor history remains continuous, but the rows preserve:

- `probe_source=cache`;
- the cache age;
- the original cached SERP fetch timestamp.

Competitive capture is fail-open. A persistence failure is logged but never changes the authoritative rank-check result, billing settlement or worker completion state.

### API

Competitive intelligence uses the existing `rank:read` permission:

```http
GET /api/v1/competitive/monitors/{monitor_id}/summary?hours=168&top_n=20
GET /api/v1/competitive/monitors/{monitor_id}/trend?hours=168&top_n=20
```

Summary parameters support:

- `hours`: 1–8760;
- `top_n`: 1–100;
- `limit`: 1–200;
- `include_tracked`: include the Monitor's configured ASINs in the returned table.

Trend can accept repeated `asins` query parameters. When omitted, the service automatically follows the leading competitors from the same summary window.

Fantastic Admin exposes **Rank Monitoring → Competitor Intelligence**, with Monitor/window/Top-N selection, organic and sponsored SOV, geo coverage, rank movement sparklines and geographic leaders.

### Data start point

Competitive observations begin with SERP probes performed after Phase 20 is deployed. Existing historical RankRuns only stored explicitly requested ASIN observations, so they cannot be used to reconstruct products that were never persisted.

No additional Amazon probe or credit is required to collect competitive intelligence; it is derived from the same SERP response already obtained for the rank check.

## Phase 20 migration

Schema revision `20260926_0014` adds:

- `serp_competitive_observations`;
- indexes for run, tenant, Geo Profile, ASIN and observed time;
- a unique `run + geo + ASIN` constraint.

Upgrade existing deployments with:

```bash
cd backend
alembic -c alembic.ini upgrade head
```


## Competitive trend alerts

Phase 21 extends the existing rank-alert engine with competitor-specific transitions derived from the SERP-wide competitive observations captured for each completed monitor run.

No additional SERP probes are performed and no additional credits are consumed. Competitive alerts evaluate only after a monitor run has completed successfully or partially successfully, using the same captured SERP observations that power **Competitor Intelligence**.

Supported competitor rules:

- `competitor_enters_top_n` — fires when the competitor's best organic position moves from outside Top N (or absent) to inside Top N between adjacent successful runs.
- `competitor_exits_top_n` — fires on the inverse transition.
- `competitor_sov_gain` — fires when the competitor gains at least N **percentage points** of organic share of voice between adjacent successful runs.
- `competitor_sov_loss` — fires when the competitor loses at least N percentage points.
- `competitor_overtakes_tracked` — fires when the competitor's average organic rank becomes better than the best average organic rank among the monitor's tracked ASINs, and it was not ahead on the previous successful run.

Competitor alert rules require one untracked 10-character ASIN. They intentionally use monitor-wide geo scope; existing geo-specific tracked-ASIN alert rules remain separate.

All competitor alerts reuse the existing alert infrastructure:

- Email delivery;
- Slack Incoming Webhooks;
- allowlisted generic HTTPS webhooks;
- encrypted notification destinations;
- stable event IDs;
- worker-safe cooldown enforcement;
- tenant-scoped event history and delivery audit.

The cooldown key remains rule + ASIN + geo scope. Repeated matching runs inside the cooldown window are suppressed.

The **Competitor Intelligence** table provides a **Create alert** action for discovered untracked ASINs. It opens **Workspace → Rank Alerts** with the monitor and competitor prefilled.

### Metric definitions

For one monitor run:

- **Best organic rank** is the lowest organic position observed for the ASIN across the run's geo probes.
- **Average organic rank** is the arithmetic mean of the ASIN's organic positions across geo probes where it appeared.
- **Organic SOV** is the ASIN's number of captured organic placements divided by all captured organic placements in that run, expressed as a percentage.
- **SOV gain/loss thresholds** are absolute percentage-point changes. For example, 25% → 40% is a +15 percentage-point gain.

Competitive transition rules compare the current run only with the previous completed/partially-completed monitor run. A first run by itself never emits a transition alert.

Phase 21 does not add database tables or require an Alembic migration; it extends the Phase 17 alert rule/event schema and Phase 20 competitive observation data.
