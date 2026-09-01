# AssetManager 整改任务包 · 2026-09-01（交托执行手册 v2）
> 状态：**现行**（交托执行手册 v2） · 状态登记：2026-09-02（文档整理轮补登）


> 打包日期：2026-09-01
> 基线 commit：本地 HEAD `be146da`（08-31 17:03）／ 远程待确认（开工前先 `git status` + `git log origin/master..HEAD`）
> 面向：接管执行的智能体。**本文件自包含，无需回看历史对话。** 执行证据基线见 `docs/reports/re-audit-2026-09-01.md`。

---

## 0. 开工前必读

### 三条铁律（沿用 v1，新增第 4 条）

1. **先跑门禁，再动手；改完再跑一遍门禁。** 门禁红就是没做完（门禁清单见 §2.5）。
2. **每个任务单独一个 commit**，conventional commit 风格（历史：`feat(scope) 描述` / `fix(scope) 描述`）。
3. **不确定就停手问，不要猜。** 项目已有多个"看起来坏了其实没坏、看起来没坏其实坏了"的坑（见 §2.4）。
4. **工作区当前有 62 个未提交条目**（37 M / 25 ??），其中含并行会话的 WIP（MCP 路由、README 收敛）。**动工前先盘点**：哪些属于本任务包范围、哪些是并行工作的产出。**禁止 `git add -A` 一把梭**——分批 add，避免把别人的 WIP 混进你的 commit。

### 上游文档（本任务包的依据，需要细节时查阅）

| 文档 | 内容 |
|---|---|
| `docs/reports/re-audit-2026-09-01.md` | **本轮复审证据基线**：P0 五项重验 + 状态变化矩阵（必读） |
| `docs/plans/p0-security-remediation-2026-08-31.md` | P0 五项代码级改法（before/after/波及面/验收）——批次 A 的施工图 |
| `docs/reports/architecture-function-and-reliability-review-2026-09-01.md` | 9-01 复核：迁移 v44/outbox/H1 协议——批次 B 的依据 |
| `docs/plans/architecture-reliability-roadmap-2026-08-31.md` | 长期执行账本（H1/H2/H3），本任务包与其衔接，不另立路线 |
| `docs/reports/global-synthesis-analysis-2026-08-31.md` | 30 项唯一风险 U-1..U-30 + 五大根因 + P0 批判（pwd_version 补强源自此处） |
| `docs/plans/task-package-2026-08-30.md` | v1 任务包：环境手册全文（§2 踩坑记录）与 T0-T10 任务（多数已执行或执行中） |
| `docs/reports/expert-panel-deep-analysis-2026-08-31.md` | 五专家团深度报告（S1-S7 编号安全发现、P1-Pn 性能发现） |

---

## 1. 项目当前状态速览（2026-09-01 复审结论）

| 项 | 值 |
|---|---|
| 桌面端 | PySide6，`AssetsManager/` 282+ .py（仍在增长：08-31 新增 ai_tagging/commands/relink） |
| 服务端 | aiohttp，**72 路由**，SQLite(WAL)，**迁移 v44**，12 仓库 |
| Web 端 | `webui/` React 18 + Vite + TS，10 页面，85+ 测试文件 |
| 分层 | 有 AST 门禁守护（12 层依赖 DAG）；domain→core 反向依赖仍未清（`domain/events.py:11`） |
| i18n | en/zh/ja 三语 **1007 key**（08-31 新增 AI 打标等 key 已同步） |
| 未提交 | **37 M / 25 ??**（含 MCP 路由 WIP、README 商城收敛、本任务包相关文档） |
| 迁移/恢复 | v44-v46 transition outbox 已落地；唯一 canonical manifest consumer 使用显式 disposition，observer 为 ACK 后非阻塞；H1 仍缺 lease、普通失败终态/保留与完整 crash-replay |

### 1.1 复审结论一览（P0 五项 = 发布红线，全部仍开放）

| 任务 | 论断 | 当前证据 | 判定 |
|---|---|---|---|
| A1 | 插件无沙箱 | `core/plugins/loader.py:89,93` exec_module 未动 | 🔴 |
| A2 | 插件信任/隔离 | 同 A1 | 🔴 |
| A3 | skip 限流 DoS | `lan/api.py:134-136,291` + `lan/security.py:186` 未动 | 🔴 |
| A4 | 全量读内存 OOM | `lan/safe_open.py:54-60` 无 max_bytes | 🔴 |
| A5 | 密码令牌伪造 | `domain/auth.py:155` 用 password_hash 作 HMAC key | 🔴 |
| A6 | 匿名泄露/默认绑定 | 未提交 diff 无相关改动 | 🔴 |
| C4 | spec 幽灵 + Cython | `AssetManager.spec:177-182` 未动；`build.py` 0 处 cython | 🔴 |

---

## 2. 环境操作手册（精简版，全文见 v1 §2）

### 2.1 跑 Python 测试（必须清 safe-delete shim）

```bash
PY="C:/Users/86177/AppData/Local/Programs/Python/Python314/python.exe"
env -u CODEBUDDY_SAFE_DELETE_SANDBOX -u CODEBUDDY_SAFE_DELETE_BIN_DIR \
    -u CODEBUDDY_SAFE_DELETE_BULK_GUARD -u CODEBUDDY_SAFE_DELETE_BULK_STATE_DIR \
    -u CODEBUDDY_SAFE_DELETE_BULK_THRESHOLD -u CODEBUDDY_SAFE_DELETE_REPORT_PATH \
    -u PYTHONPATH -u NODE_OPTIONS \
    $PY -m pytest <路径> -q -p no:cacheprovider --override-ini="addopts=-ra"
```

### 2.2 WebUI 测试

本地路径含 `~` 导致 vitest 的 subst 失败 → **替代验证**：`npm run typecheck` + `npm run build`；vitest 交给 CI。

### 2.3 Git 分支指针丢失坑（已出现 4 次）

commit 成功后 `.git/refs/heads/feat/*` 可能消失。收尾动作：

```bash
git add <文件> && git commit -q -m "..." -m "..."
SHA=$(tail -1 .git/logs/HEAD | awk '{print $2}')
mkdir -p .git/refs/heads/feat && printf "$SHA\n" > .git/refs/heads/feat/<branch-name>
git log --oneline -1   # 验证
```

### 2.4 grep 排除 `.worktrees/`

`.worktrees/grid-zoom-interpolation-fix/` 是主树完整副本，统计会被翻倍。全仓 grep 加 `--exclude-dir=.worktrees`。

### 2.5 门禁（改完全部跑一遍）

```bash
PY="C:/Users/86177/AppData/Local/Programs/Python/Python314/python.exe"
$PY -m ruff check AssetsManager tests scripts run.py
for s in check_boundaries check_layers check_style_sources check_route_capabilities \
         check_frontend_data_fetch check_doc_stats check_documents; do
  printf "%-32s " "$s"; timeout 180 $PY "scripts/$s.py" >/dev/null 2>&1 && echo PASS || echo FAIL
done
$PY scripts/gen_ts_types.py --check
$PY scripts/gen_web_tokens.py --check
```

注意：**新增/删除路由、修改 i18n key 或 stats 数字时 `check_doc_stats` 与 `check_route_capabilities` 必红**，改代码的同时更新 README stats 行与路由 golden 契约。

### 2.6 推送

代理端口会变。失败流程：`netstat -ano | grep LISTENING` 探测可用端口 → `HTTPS_PROXY=http://127.0.0.1:<端口> timeout 180 git push origin master` → **失败直接重试一次**。

---

## 3. 任务清单

> 分四批 + 观察项。**顺序建议：A（发布红线，小而确定）→ B（恢复一致性协议，需先定协议再写码）→ D（收尾：先定 MCP 限流档位再提交 WIP）→ C（结构性，可穿插）。**
> 每个任务给出：目标 / 证据 / 改法 / 验收 / 风险。

---

### 批次 A：发布红线（P0 五项 + 1，施工图见 `p0-security-remediation-2026-08-31.md`）

#### A1 · 插件信任列表 + SHA-256 指纹（P0-1 阶段 A）

- **证据**：`AssetsManager/core/plugins/loader.py:89,93` 在宿主进程 `exec_module`；自动发现加载，无签名/白名单。
- **改法**：plugin.json 增加 `trusted` 字段；安装时登记 SHA-256 指纹；加载前逐文件校验；插件管理器加"信任并启用"二次确认。**注意**：v1 方案遗漏"插件更新即重新信任"与撤销信任路径，一并补上。
- **验收**：未信任插件无法加载；篡改已信任插件文件后校验失败并拒绝加载。
- **风险**：低（纯加载侧改动）。**这不是隔离**，阶段 B 不可拖延。

#### A2 · 插件子进程隔离（P0-1 阶段 B，1-2 迭代内）

- **改法**：`multiprocessing` spawn 子进程 + 受限 IPC 白名单（对齐 Serpent 双档运行时）；崩溃/死循环被隔离。OS 级沙箱留 P1。
- **验收**：插件 `time.sleep(999)` / 死循环 / 崩溃不影响宿主；插件只能经白名单 IPC 触达宿主能力。
- **风险**：中（IPC 协议设计，先补契约测试）。

#### A3 · 修复 skip 限流 DoS（S2）

- **证据**：`lan/api.py:134-136` 定义 `_SKIP/_PUBLIC_SKIP/_OPTIONAL_SKIP`，`/api/image` 等 6+ 条路由用 skip（`:225` 系），`/api/stats`（`:291`）也是；`lan/security.py:186` skip 完全跳过限流；但认证中间件对随机 Bearer 仍跑撤销表查询 + 50k 轮 PBKDF2（`lan/server.py:1131-1134`）。
- **改法（2026-09-01 12:10 修正，依据 `docs/reports/task-package-validity-check-2026-09-01.md` §3.1）**：**不需要新增档位**——三档已具备：`auth_strict`（`api.py:137-139`）、`browse`（`:163-164`）、`skip`（`:134-136`），语义见 `security.py:181-182`，处理分支在 `:282` 与 `:297-300`。
  - 方案 A（本轮必做）：把 7 条 skip 路由改挂既有 `_BROWSE` 系档位——`/api/image`(`:225`)、`/api/thumbnails/{path}`(`:235`)、`/api/thumbnails/batch`(`:236`)、`/api/revision`(`:276`)、`/api/stats`(`:291`)、`/ws`(`:307`)、`/assets`(`:377`)。
  - **⚠️ 隐藏前置依赖（原方案未识别）**：`tests/lan/test_route_policy*.py:26` 断言注释 "only media/status polling stays skip-open"、`:81` 返回 `"skip"` —— **测试契约已把 media 保持 skip 固化**，必须与代码同改，否则 `check_route_capabilities` 门禁红。
  - 方案 B（load-bearing，仍有效）：PBKDF2 前置"格式预检 + 失败计数桶"，随机 token 根本不进哈希（认证流程 `server.py:1125-1140`，预检位尚未加）。**新路由必须显式声明限流档位**（含未提交的 `/mcp`，见 D2）。
- **验收**：随机 Bearer 刷 `/api/image` 5000 次/分钟，CPU 占用不再显著上升；skip 档从路由策略契约中消失（代码与 `test_route_policy*` 同步更新）。
- **风险**：低-中（golden 契约与测试同步更新）。

#### A4 · 文件服务流式读 + 大小上限（S5）

- **证据**：`lan/safe_open.py:54-60` `read_safe_file` 无 max_bytes，整文件读 bytes；底层 `read_snapshot` **已有 `max_bytes`**（`AssetsManager/core/file_snapshot.py:186-190`）只是没透传；三条调用路径：`lan/routes/downloads.py:183`、`lan/routes/image.py:119,176`、`lan/routes/shares.py:320`。
- **改法**：① `read_safe_file` 透传 max_bytes；② 新增 `stream_safe_file`（分块迭代器）；③ 三条路径分别设上限（512MB / 256MB / 512MB）并改 `StreamResponse` 分块发送；④ 保留 quota 后置计数与断连清理语义。**S6（ZIP 配额）并入本任务**：批量 ZIP 增加文件数/总大小上限。
- **验收**：>512MB 文件下载返回 413 而非 OOM；大文件下载中断后临时文件被清理；新增单元测试覆盖上限与流式路径。
- **风险**：中（LAN 契约变更，需更新路由测试）。

#### A5 · 密码模式令牌独立签名密钥（P0-4，含 global-synthesis 补强）

- **证据**：`domain/auth.py:146-156` `generate_token` 用 `hmac.new(password_hash.encode(), ...)`；调用面仅 4 处：`auth_service.py:188-192`、`routes/auth.py:75`、`server.py:1149-1151`（分享令牌与 local_ui 令牌均为独立 secret，零波及）。
- **改法**：LAN 装配处新增内存态 `password_token_secret`，三处改传；**补强一（pwd_version）**：令牌负载加入密码版本计数器，改密即递增并拒绝旧版本令牌（恢复"改密踢旧会话"语义）；**补强二**：密钥从既有 `token_secret` 经 HKDF 派生，避免重启全员重登。
- **验收**：只持 password_hash（能读库）者无法 mint 有效令牌；改密后旧令牌立即失效；应用重启后旧令牌仍可验证（如保留派生持久化）。
- **风险**：低-中（涉及认证路径，改完跑 `tests/lan/` 全量）。

#### A6 · 匿名信息泄露 + 默认绑定地址（MED）

- **证据**：`lan/routes/system.py` `/api/info` 匿名分支返回 `library_root`/`library_stats`（见 p0 方案 §P0-5）。
- **改法**：匿名分支移除 `library_root` 与 `library_stats`（保留 auth_mode/share_name 供登录页）；`auth=none` 时默认绑定 `127.0.0.1`，需匿名局域网访问须在设置显式开启；webui LandingPage 联动说明。
- **验收**：匿名访问 `/api/info` 不含路径信息；`auth=none` 默认不对外监听。
- **风险**：低。

---

### 批次 B：恢复一致性协议（H1，依据 9-01 复核报告；先定协议再写码）

> 原则（9-01 报告 §4 原话）："这组工作必须先定'谁是 durable consumer、什么算成功交付'的协议，再改实现。否则增加后台重试只会更快地放大误 ACK、重复执行或头阻塞。"

#### B1 · outbox listener 显式 disposition（P0）

- **原证据**：`handle_task_transition()` 记录 DB 错误后返回；`drain_transition_outbox()` 因 listener 未抛错而 ACK（9-01 报告 §4 H1 首行）。
- **状态（2026-09-01 12:10 校验：已实施）**：`application/reconciliation_queue.py:174-182` 定义 `ReconciliationTransitionDisposition`（`APPLIED`/`STALE`/`RETRY`）；`:970-979` 在 listener 返回 disposition 后仅对 `APPLIED`/`STALE` 放行 ACK，`RETRY` 不 ACK。与 B2 的 canonical consumer 边界配套。
- **后续**：无需重写；本条转为**验收验证项**，与 B2/B5/B6 一并跑测试确认后提交。
- **验收**：manifest DB 暂不可用时 `delivered_at` 保持空，恢复后自动回放且仅 ACK 一次。

#### B2 · canonical consumer 边界与未来每 consumer receipt（P1）

- **状态**：已实施最小模型：`import_manifest_recovery` 是唯一 canonical durable consumer，只有其 `APPLIED` / `STALE` 能 ACK；通用 listener 是 ACK 后 observer，失败不影响 durable retry。
- **后续条件**：当前没有第二个生产 durable consumer，不增加 v47 receipt/inbox。产品新增独立 projection 时，先设计 `(event_id, consumer_id)` receipt、registry、历史与 retention。
- **未来验收**：两个 durable consumer 中 A 成功、B 失败后，只重放 B；后注册 consumer 的历史起点和移除语义可验证。

#### B3 · 有界后台 drainer（P1）

- **证据**：drain 只在 mutation/注册/显式 recovery 时运行，单次上限 64。
- **改法**：增加有界后台 drainer：停止语义、jitter、退避、可观测性。
- **验收**：65+ 条积压、一次 listener 失败后，无新 mutation 也能全部推进。

#### B4 · poison row 隔离（P1）

- **原证据**：最早损坏的 outbox 行会卡住严格顺序；decoder 对 snapshot 的 task 身份校验不足。
- **状态（2026-09-01 12:10 校验：已实施）**：`application/reconciliation_queue_store.py:1001` 显式使用 **v45 quarantine**；`:963` 限制单次 claim 的 poison 扫描量，避免一条坏行拖住整个严格顺序队列。迁移见 `core/db_migrations.py:1146`。
- **后续**：转为验收验证项；建议补一条"坏 snapshot 后续合法事件继续推进"的回归测试。
- **验收**：坏 JSON/坏 snapshot 被隔离，后续合法事件可交付且不污染 manifest。

#### B5 · 失败退避/死信/ACK 清理（P1）

- **状态**：`next_delivery_at` 指数退避、默认八次尝试和 v45 dead-letter 已实施；第八次 failure 在 token-CAS copy/delete 事务内保留原始 event、snapshots、attempts 与最后错误，v44 无 dead-letter 表保持 retry。
- **后续**：提供受审计的人工 replay、ACK retention/prune 与 age/attempt/dead-letter 指标。
- **验收**：持续失败不热循环；第八次失败不阻塞后续 head；老 ACK 按策略清理，人工 replay 与指标可验证。

#### B6 · delivery lease heartbeat（P1）

- **状态**：已实施。SQLite outbox 使用 delivery-token CAS 在 canonical callback 运行期间按约三分之一 lease 续期，默认 300 秒 callback age 后停止续期；迟到 callback 不 ACK，最后一个 lease window 后允许另一连接接管。
- **门禁**：current-token CAS、慢 callback 不被第二连接抢占、callback-age 后接管均已覆盖；完整进程退出于 manifest CAS 和 ACK 之间的 crash-replay 仍在后续范围。

---

### 批次 D：收尾与治理（先做 D1-D2，再提交 WIP）

#### D1 · 未提交 WIP 盘点与定型提交

- **现状**：37 M / 25 ??。其中：README 商城收敛（含 ADR 0005 声明、stats v44/72/1007）、`lan/api.py` +6 行（/mcp 注册）、`core/`（schema_defs、db_migrations、settings）、`application/`（bootstrap、runtime、import_service、reconciliation_queue 系 12 处）、`tests/` 5 处、新增 `lan/mcp_server.py`、多份计划/报告文档。
- **动作**：逐批 add + commit（conventional commit），**先与并行会话核对归属**；每个 commit 独立过门禁。
- **验收**：工作区清零或仅剩明确未完成项；每个 commit 可独立 `git log` 追溯。

#### D2 · MCP 路由安全定型（新风险面）

- **证据**：`AssetsManager/lan/mcp_server.py`（未提交）：fail-closed 设计良好（空 token→404、timing-safe Bearer、body 1MB、输出 200KB、只读五工具、worker 线程）；但 `api.py:249-253` 注册 policy 为 `auth="public", capabilities=_BROWSE`，**未显式声明 rate_limit**。
- **改法**：① 显式限流档位（建议并入 A3 的 media 档）；② token 存储与轮换策略（`lan_mcp_token` 存于设置，确认非日志/非导出面）；③ 审计日志接入。
- **验收**：MCP 端点有限流；token 不出现在日志/错误响应；README/文档注明启用方式与风险。
- **风险**：低（未提交，定型前不影响发布）。

#### D3 · U-6 写路径实时容量触发（P2 尾）

- **证据**：`thumbnail_service.py:441` 容量帽 + `library_governance.py:197` 启动治理已实现；但写入路径无触发（调用点仅 `library_settings_adapter.py:189` 与启动治理两处）。
- **改法**：缩略图生成/缓存写入后检查容量，超限触发驱逐（注意性能：抽样检查而非每次写入全量扫描）。
- **验收**：会话内生成大量缩略图越过 2GB 上限后，缓存被自动收缩。
- **风险**：中（写路径加检查有性能成本，需基准）。

#### D4 · 08-31 新功能安全审计（AI 打标 / relink / commands）

- **范围**：`37cfc56`（Ollama 客户端 + 标签白名单）、`cabb3d9/7dd5230`（relink 失链再挂接）、`142c2ec/be146da`（T8 命令注册表 + 幂等）。三个功能均为 08-31 新提交，未经安全视角评审。
- **重点**：Ollama 连接 URL 是否可被恶意配置成 SSRF；命令注册表是否可能执行任意命令（T8 边界）；relink 文件操作是否走 application 层统一路径。
- **验收**：三份小审计结论（各 ≤1 页）+ 发现项修复或显式豁免记录。

---

### 批次 C：结构性与工程深化（可与 A/B/D 穿插，单个 commit 独立）

#### C1 · DI 收敛（Service Locator → provider seam）

- **证据**：`di/__init__.py:3` 自述 Service Locator；`AppSettings.instance` 74 处直接引用。
- **改法**：先接高频 `AppSettings` 与事件订阅到既有 provider/session seam（9-01 报告 H2/H3）；不需一次性重写 DI。
- **验收**：AppSettings 直接引用数显著下降；既有测试全绿。

#### C2 · 清理 domain→core 反向依赖

- **证据**：`domain/events.py:11` 依赖 `core.event_contracts`（五专家团已验证）。
- **改法**：事件契约下沉 domain 或抽取中立层；同时清理 UI 的直接全局事件订阅。
- **验收**：分层门禁（check_layers）不再豁免该依赖。

#### C3 · 巨文件拆分（7 个 1600+ 行单体）

- **对象**：core/database.py（身份/迁移/写闸门）、queue store/dispatch、LAN lifecycle、桌面加载器等（见五专家报告 §2）。
- **改法**：每一刀先补契约测试再拆；**优先拆 core/database.py 的迁移与身份逻辑**。
- **验收**：拆分后文件 ≤ 1000 行；迁移/身份逻辑有独立专测（当前 database.py 身份/迁移零专测）。

#### C4 · 类型检查补全 + Cython 链路（含 spec 幽灵模块）

- **证据**：`pyrightconfig.json`（basic 模式，exclude 范围待核对）；`build.py` 0 处 cython；`AssetManager.spec:177-182` 引用不存在的 `lan.routes.shop.*`、`:77` 大写 `Assets/` vs 磁盘小写。
- **改法**：① pyright basic→strict（先纳入 `background/`、`core/plugins/`，排除量收敛）；② 删 spec 幽灵模块、修 `Assets/` 大小写；③ 若 Cython 继续废弃则删 `setup_cython.py` 与 README 宣传，否则接通 build.py。
- **验收**：pyright strict 通过（或明确豁免清单）；spec 仅引用存在模块；Windows 打包 smoke 通过。

#### C5 · webui 撤销/重做（双端奇偶差）

- **证据**：`webui/src` grep "undo|redo" 0 命中；桌面端按库隔离的 undo/redo 成熟（T5 已提交）。
- **改法**：Web 端最小实现（标签/评分/收藏等写操作的历史栈 + Ctrl+Z/Y），复用桌面端契约。
- **验收**：Web 端标签编辑可撤销/重做；i18n 三语新增 key 同步。
- **风险**：中（新交互面，先出交互设计再实现）。

#### C6 · 文档-代码收敛（U-8 尾收）

- **现状**：README 商城已改（未提交）；spec 幽灵模块未动（并入 C4）。
- **改法**：全仓 grep 商城残留（webui 文案、其他 docs）；stats 行与 9-01 数字对齐（72 路由/v44/1007 key）。
- **验收**：README/docs 中无"商城系统"作为可用功能承诺；`check_doc_stats` 绿。

---

### 批次 E：观察项（不立即做，记录跟踪）

- **E1**：性能深水区——files 分页 keyset 化（替代 OFFSET）、读连接池（T10 只读路径）、FTS 分片（10 万库触发信号出现前不替换 SQLite）。
- **E2**：云 AI 多厂商适配器（保留本地 Ollama 默认）——功能路线而非修复，等路线图决策。
- **E3**：Serpent 借鉴项 P1/P2（智能合集、3D/视频/文档缩略图、WebDAV）——见功能对照报告 §4。

---

## 4. 交叉引用表（风险 → 任务 → 状态）

| 风险/来源 | 任务 | 状态 |
|---|---|---|
| U-1 插件无沙箱（R1/P0-1/Serpent-P0） | A1+A2 | 🔴 待执行 |
| U-2 S2 skip 限流 DoS | A3（+D2 覆盖 /mcp） | 🔴 待执行 |
| U-3 S5 全量读内存 | A4（+S6 ZIP 配额） | 🔴 待执行 |
| U-4 密码令牌伪造（P0-4） | A5 | 🔴 待执行 |
| U-5 匿名泄露/默认绑定 | A6 | 🔴 待执行 |
| U-6 缩略图缓存 | D3（部分已闭环） | 🟡 待补写路径 |
| U-8 文档背离（商城/spec） | C4+C6（README 已改未提交→D1） | 🟡 收尾中 |
| H1 恢复一致性（9-01 报告 P0-P2） | B1-B5 | 🔴 协议未定 |
| H2-d2 MCP 面（未提交 WIP） | D2 | 🟡 WIP |
| 新功能审计（AI 打标/relink/commands） | D4 | 🔴 未评审 |
| 工作区未提交状态 | D1 | 🟡 62 条目 |
| DI/分层/巨文件/类型（C 系） | C1-C4 | 🔴 待执行 |
| 双端奇偶（webui undo） | C5 | 🔴 待执行 |

---

## 5. 建议执行顺序与门禁

1. **先跑一遍 §2.5 门禁**，记录基线（当前工作区未提交状态下可能部分红——因为 WIP 未收尾，属预期）。
2. **批次 A（A3→A4→A5→A6→A1→A2）**：每任务独立 commit + 门禁。A3/A4 涉及路由契约，先改 golden 测试。
3. **D1+D2**：先定 MCP 限流档位，再提交工作区 WIP（避免把未定型面固化）。
4. **批次 B（B1 先行）**：B1 是 P0，其余依赖其协议设计。
5. **批次 C**：穿插执行，每个 commit 独立。
6. 全部完成后：**门禁全绿 + 工作区清零 + 每个 commit 独立可追溯**，即本任务包交付完成。

---

*本任务包由 8-31 四轮评审 + P0 方案 + 9-01 代码状态复审沉淀。执行中如发现证据与代码不符，以最新代码为准并回写本文件（append 变更记录节）。*
