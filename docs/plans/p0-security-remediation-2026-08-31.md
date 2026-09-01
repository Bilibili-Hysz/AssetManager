# AssetManager 安全 P0 改造方案（2026-08-31）

> 状态：**提案**（未实施）。来源：第三轮五专家团深度评审（`docs/reports/expert-panel-deep-analysis-2026-08-31.md`）——P0 五项为公网暴露/发布红线，均属"改动小、收益立竿见影"类。
> 配套文档：`docs/archive/2026-09/analysis-superseded/project-analysis-2026-08-31.md`(已蒸馏:docs/reports/serpent-expert-analysis-distilled-2026-09-02.md)（第一轮总体评审）、`docs/plans/architecture-reliability-roadmap-2026-08-31.md`（H0-H3 可靠性长期路线，本方案中 S5 与其 H2"受保护分块流式响应"重叠，本方案建议将安全关键子集**提前**）。
> 约定：本文只描述改法与验收判据，**不直接改源码**；所有行号以当前工作树为准。

---

## 0. 背景与处置总览

第三轮评审确认的 P0（发布红线）五项：

| # | 问题 | 严重级 | 一句话根因 |
|---|---|---|---|
| P0-1 | 插件无沙箱（宿主进程 exec_module） | CRITICAL | `core/plugins/loader.py:89-93` 自动发现 + 同进程执行 |
| P0-2 | skip 路由零限流 + 随机 token 触发 PBKDF2 | HIGH | `security.py:186,312` 完全跳过限流；`server.py:1131-1150` 认证开销无处可挡 |
| P0-3 | 文件服务全量读内存、无上限、未认证可触达 | HIGH | `safe_open.py:59` 无 max_bytes；三处路由整读 |
| P0-4 | 密码模式令牌可用 DB 内 password_hash 伪造 | HIGH | `domain/auth.py:146-156` HMAC 密钥复用存储哈希 |
| P0-5 | 匿名信息泄露 + 默认 0.0.0.0 | MED | `system.py:112-131`；`server.py:146` |

处置原则：P0-2/P0-3 是纯 lan/ 层小改（一个提交可含）；P0-4 波及面已核实为单点；P0-5 双项各自独立；P0-1 拆两阶段（信任列表先行，子进程隔离其次）。

---

## 1. P0-2：skip 路由限流兜底（S2，HIGH）

### 1.1 现状与证据

- 路由策略声明：`lan/api.py:134-136` `_SKIP/_PUBLIC_SKIP/_OPTIONAL_SKIP = RoutePolicy(rate_limit="skip")`；`/api/image`（:225）、`/api/thumbnails/{path}`（:235）、`/api/thumbnails/batch`（:236）、`/api/revision`（:276）、`/api/stats`（:291）、`/ws`（:307）均为 skip。
- 中间件：`lan/security.py:186` `skip_rate = policy.rate_limit == "skip"`，`:312` `elif not skip_rate:` —— **skip 时一个限流器都不跑**。
- 认证链：`lan/server.py:1095-1152` `_resolve_principal` 对任意携带 Bearer 的请求执行：撤销表 DB 查询（:1126-1128）→ 50k 轮 PBKDF2 `verify_key`（:1131-1134；`domain/auth.py:28,44`）→ user token DB 查询（:1142-1148）→ password `verify_token_async`（:1149-1151）。skip 路由 auth 仍为 required（`_SKIP` 未改 auth），**随机 token 每请求烧 ~20-50ms CPU + 2 次 SQLite 查询且无频率上限**。

### 1.2 方案 A（推荐）：新增 `media` 限流档位

保留 skip 语义的"免限流"意图（媒体轮询合法突发大），改为"宽松但有上限"：

1. `lan/route_policy.py:26` `RateLimitClass` 增加 `"media"`；`:65` 校验集合同步。
2. `lan/security.py:296-323` 在 browse/general 之间新增分支：
   ```python
   elif policy.rate_limit == "media":
       active_limiter = media_limiter
       if not media_limiter.is_allowed(bucket_key):
           ...  # 429 media_rate_limited，格式对齐 browse 分支
   ```
   `media_limiter` 建议 `RateLimiter(max_requests=2000, window_seconds=60, max_ips=10000)`（比 general 1000/60s 宽松一倍，见 `security.py:65` 默认值）。
3. `lan/api.py:134-136` 的 `_SKIP` 系列与 `_PREVIEW_WRITE_SKIP`（:166）、`:291` 全部改为 `rate_limit="media"`；`security.py` 中的 skip 分支保留（仍可存在，但不再有路由使用，或一并移除）。
4. 工厂注入：`lan/server.py` 创建中间件处（约 `:104`）传入 `media_rate_limiter`，并遵守 `security.py:12-16` 的"仅事件循环线程触碰"并发契约。

### 1.3 方案 B（纵深防御，与 A 叠加）：PBKDF2 前置廉价哨兵

认证中间件在跑 PBKDF2 前加两级短路（`lan/server.py:1111-1151` 内）：

```python
def _cheap_token_sentinel(token: str) -> bool:
    # 1) 格式/长度预检：ts.nonce.sig 需 3 段、时间戳近 24h、hex 字符集
    # 2) 失败计数桶（LRU，10 次失败/60s/IP 内直接短路）
    ...
```

- 无效格式 token（绝大多数随机串）→ 不进入 `verify_key`；
- 同一 IP 连续失败超阈值 → 60s 内直接返回 None（该 IP 的 429 由 media 限流兜底）；
- 仅格式合法且未超失败阈值的 token 才付出 PBKDF2 成本。

### 1.4 验收门禁

- 新增 `tests/lan/test_lan_api.py` 用例：向 `/api/image` 连续发随机 Bearer 超预算 → 命中 `429 media_rate_limited`；monkeypatch `verify_key` 计数，断言非法格式 token 0 次 PBKDF2。
- 既有 210 用例全绿；`python run.py --package-smoke` 通过。

---

## 2. P0-3：文件服务流式化 + 大小上限（S5，HIGH）

### 2.1 现状与证据

- `core/file_snapshot.py:181-194` `read_snapshot` **已支持 `max_bytes`**（超限抛 `FileSnapshotError`），但 LAN 适配层 `lan/safe_open.py:54-67` `read_safe_file` **未暴露该参数**，返回 `tuple[bytes, FileIdentity]` 整读。
- 三个整读调用点：`lan/routes/downloads.py:182-184`（单文件下载）、`lan/routes/image.py:118-120`（解码路径）与 `:175-177`（验证路径）、`lan/routes/shares.py:319-321`（公开分享下载）。
- 威胁叠加：guest `preview` 默认 True（`lan/principal.py:96`）+ `/api/image` 原为 skip 限流 → **未认证可反复触发整读**；数 GB 文件 → OOM。
- 同类已有约束：批量 ZIP 已有 `MAX_BATCH_DOWNLOAD_BYTES`（`downloads.py:23-24`，500MB/100 文件）；缩略图 admission 64MB/256MB（`thumbnail_service.py:52-53`）——单文件下载与图片路径是唯一的"无上限"缺口。

### 2.2 改法（三层）

**层 1 — 适配层增加上限与流式入口**（`lan/safe_open.py`）：

```python
def read_safe_file(root, admitted_path, *, expected_identity=None,
                   max_bytes: int | None = None):   # 透传 read_snapshot
    ...
    return read_snapshot(root, admitted_path, expected_identity=expected_identity,
                         max_bytes=max_bytes)

def stream_safe_file(root, admitted_path, *, expected_identity=None) -> OpenedFile:
    """返回 OpenedFile 供路由层分块发送；发送后由调用方 fstat 复核 identity。"""
    return safe_open_under_root(root, admitted_path, expected_identity=expected_identity)
```

（`OpenedFile` 已具备 `file`/`size`/`identity`/`close`/上下文管理器，`file_snapshot.py:57-74`。）

**层 2 — 各路由设上限**：

- `downloads.py` 单文件分支：新增 `MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024`（与批量常量同一数量级，`downloads.py:23`），`read_safe_file(..., max_bytes=...)` 超限 → 413 `payload_too_large`；
- `image.py` 两处：`max_bytes=256 * 1024 * 1024`（解码/验证路径一致）；
- `shares.py` 公开下载：`max_bytes=512 * 1024 * 1024`，超限折叠为 404（保持"不泄露存在性"，对齐 `shares.py:301-306` 的 L2 折叠策略）。

**层 3 — 流式响应**（下载与分享两处）：

```python
# downloads.py:189-214 / shares.py:326-329 由 web.Response(body=body) 改为：
resp = web.StreamResponse(headers={"Content-Disposition": ..., "Content-Length": str(opened.size)})
await resp.prepare(request)
while chunk := opened.file.read(1024 * 1024):
    await resp.write(chunk)
# 发送后 fstat 复核 identity；变化则中断（对齐 read_snapshot:192 的防换文件检查）
await resp.write_eof()
```

- 保留既有语义：quota 计数后置（`downloads.py:195-209` 已设计好"构造成功才计数"）；断连走 `request.task.add_done_callback` 清理（`downloads.py:123-126` 模式复用）；
- `Content-Disposition` 头逻辑（`downloads.py:192`、`shares.py:328`）不动。

### 2.3 与 reliability-roadmap 的关系

`architecture-reliability-roadmap-2026-08-31.md` H2 已规划"分享、单文件下载和预览读取改为受保护的分块流式响应"。本方案是其中**未认证可触达**的安全关键子集（公开分享下载 + guest 图片预览），建议**提前**到本轮 P0 一并落地；H2 的其余内容（ZIP 分块写、entry/临时盘预算、Windows reparse 原子策略）维持原排期。

### 2.4 验收门禁

- 新建夹具：>512MB 稀疏文件下载 → 413/404，峰值 RSS 有界（断言 < 200MB）；
- 传输中断（`client.close()` 中途）→ 临时文件清理、无 worker 泄漏；
- 发送期间替换文件 → 中断且不发送混合内容；
- guest 角色反复请求 `/api/image` 大文件 → 413 且无 OOM（配合 P0-2 的 media 限流）。

---

## 3. P0-4：密码模式令牌改用独立密钥（HIGH）

### 3.1 现状与证据（波及面已核实为单点）

- `domain/auth.py:146-156` `generate_token(password_hash)`：`sig = hmac.new(password_hash.encode(), ...)`——**HMAC 密钥 = 存储在 DB 的密码哈希**（`users.password`）；`verify_token` :159-180 同构。
- 调用面（全项目仅 4 处）：
  - `application/auth_service.py:188-192`（薄包装）；
  - `lan/routes/auth.py:75` `token = auth_service.generate_token(lan.password_hash)`（密码登录签发）；
  - `lan/server.py:1149-1151` `verify_token_async(token, password_hash)`（认证链校验）。
- 不受影响（已确认独立密钥）：local_ui 令牌 `verify_auth_token(token, token_secret)`（`domain/auth.py:183-204`，`bootstrap.py:685` 独立 `secrets.token_hex(32)`）；user 令牌 `generate_user_token(..., secret)`（:209+）；分享令牌 `generate_share_token(share_id, self._secret)`（`share_service.py:399-406`）。
- 威胁：能读库 DB 者（本机恶意进程/备份泄露/隧道旁路读取）直接以 `password_hash` 为 key mint 任意 24h 有效登录令牌，绕过登录/审计。附加副作用：改密码即轮换 key → 旧令牌全体失效（可用性耦合）。

### 3.2 改法

1. **新增运行时独立密钥**：LAN 装配处（`bootstrap.py:685` token_secret 同点位）生成 `password_token_secret = secrets.token_hex(32)`，挂在 `lan` 对象上，**仅内存、不落盘**，重启轮换。
2. `domain/auth.py`：`generate_token(secret)` / `verify_token(token, secret)` 改签该 secret（token 格式 `ts.nonce.sig` 不变）；**不做旧格式兜底**——旧格式以 password_hash 为 key，切换后仍伪造可窗口内有效，且 24h 自动过期，直接一次性切换、用户重登即可。docstring 注明密钥语义变化。
3. 三处调用点改传 `lan.password_token_secret`：
   - `auth_service.py:188-192` 签名改 `generate_token(self, secret: str)`；
   - `lan/routes/auth.py:75` `auth_service.generate_token(lan.password_token_secret)`；
   - `lan/server.py:1149-1151` `verify_token_async(token, lan.password_token_secret)`。

### 3.3 验收门禁

- 单测：已知 secret mint → verify 真/假/过期/篡改四态；
- **伪造测试（核心）**：构造只持有 `password_hash`（模拟读库者）的 fixture，断言其无法 mint 通过 `verify_token` 的令牌；
- 行为变化标注：改密码后旧令牌**不再**随 key 轮换而失效（24h 内仍有效）——需在设置/文档中说明，避免用户困惑；
- 既有登录/认证 210 用例全绿（仅 password 模式受影响，key/user/share 模式零波及）。

---

## 4. P0-1：插件信任与隔离（CRITICAL，分两阶段）

### 4.1 现状与证据

- `core/plugins/loader.py:79-103`：`spec_from_file_location` + `exec_module`（:89-93）在**宿主进程**加载执行；仅校验 `module_path.is_relative_to(root_path)`（:85-86）与存在性，无签名/白名单/信任确认。
- 自动发现：Plugins/ 目录内容直接进入加载路径（plugin.json descriptor → entry），用户安装任意插件目录即获得以桌面用户身份执行任意代码的能力（文件系统/网络/进程全权限）。
- 与 Serpent 对照（功能对照报告）：Serpent 采用 QuickJS/WASM 插件运行时 + trusted/script 双档，能力边界明确。

### 4.2 阶段 A（本轮 P0，最小可发布）：默认不信任 + 指纹校验

1. **plugin.json 增加信任字段**：`"trusted": false` 默认；`core/plugins/descriptor.py` 解析并暴露。
2. **安装时指纹登记**：插件管理对话框（`dialogs/plugin_manager_dialog.py`）导入插件时计算目录内所有 .py 文件的 SHA-256 清单，写入 `plugin.json`（或旁路 `.trust` 文件，键为 `{relative_path: sha256}`）。
3. **加载时校验**：`loader.py:79` 加载前逐文件比对指纹，任一不符 → 拒绝加载并告警"插件已被修改"；`trusted: false` 的插件仅允许 `match/parse` 纯函数路径（不传入 host，不触发 `register`），或直接拒绝执行、仅展示元数据。
4. **UI 信任确认**：插件管理器增加"信任并启用"二次确认（列出插件声明的能力与文件指纹），未确认一律不加载。
5. 迁移兼容：存量插件缺 `trusted` 字段 → 视为 false，用户手动信任后升级。

### 4.3 阶段 B（P0 之后 1-2 迭代）：子进程隔离执行

参照 Serpent 双档运行时的最小自研方案：

1. `multiprocessing` spawn 专用插件 worker 进程（`spawn` 保证干净解释器、不继承打开句柄）；
2. 主进程 ↔ worker 之间仅通过受限 IPC（`multiprocessing.connection` 或 JSON-RPC over pipe）暴露白名单 API：plugin_api 的 `match/parse/register` 钩子 + host 提供的窄能力集（读元数据、查标签等）；
3. 插件崩溃 / `os._exit` / 无限循环 → 超时 kill worker，宿主无感；`unload` = 终止 worker；
4. 网络/文件系统不做 OS 级限制（Windows Job Object 受限令牌留作 P1 长期项，不阻塞本轮）。

### 4.4 验收门禁

- 恶意插件夹具（含 `os.system("whoami")`、读 `%APPDATA%`、`socket.connect` 外网）在阶段 A 被指纹/信任拦截、阶段 B 在 worker 内被拒或受限；
- 插件 `os._exit(0)` → 宿主存活，插件标记 failed 可重载；
- 现有 plugins 测试（`tests/plugins/` 12 个文件）全绿；`plugin_manager_dialog` 信任流程冒烟。

---

## 5. P0-5：匿名信息裁剪 + 默认绑定策略（MED，双项）

### 5.1 S1：`/api/info` 匿名分支裁剪（`lan/routes/system.py:69-135`）

- 匿名返回保留：`version`、`auth_mode`、`share_name`、`theme_color`、`theme_name`、`welcome_msg`、`footer_text`、`feature_flags`（login 页依赖 auth_mode，landing 页依赖 share_name，见 :70-77 注释）；
- 匿名返回**移除**：`library_root`（:115）、`library_stats`（:126-130，含项目总数与库总容量）；
- 已认证 principal 分支（:132-134）不变；
- **webui 联动**：`system.py:74-75` 注释表明 `LandingPage.tsx` 渲染 library_stats——匿名时前端降级为不渲染统计（或显示占位），登录后由 `/api/info` 认证分支补齐。

### 5.2 S7：默认绑定与 `auth=none` 语义（`lan/server.py:146,403`）

- auth 开启（key/user/password 任一）：维持 0.0.0.0（显式开启分享即意图暴露）；
- `auth_mode == "none"`：默认绑定 **127.0.0.1**，需要局域网匿名访问的用户须在设置中显式开启"允许匿名局域网访问"开关后绑定 0.0.0.0；既有的 preflight（`server.py:411-424`）在 facade 路径强制检查，本项把语义落到默认值；
- 设置 UI（`dialogs/settings_dialog.py`）同步增加开关与警示文案。

### 5.3 验收门禁

- 匿名 `GET /api/info` 响应断言不含 `library_root`/`library_stats`；认证后恢复；
- `auth=none` 新装默认绑定 127.0.0.1，局域网其他主机不可达；开启开关后可达；
- webui 匿名 landing 页无统计渲染报错。

---

## 6. 实施顺序（一个 PR 三个提交）

| 提交 | 内容 | 风险 | 依赖 |
|---|---|---|---|
| 1 | P0-2（media 限流）+ P0-3（流式化/上限） | 低，纯 lan/ 层，测试面集中 | 无 |
| 2 | P0-4（令牌密钥）+ P0-5（S1/S7） | 低-中，涉及 auth 行为变化需标注 | 无 |
| 3 | P0-1 阶段 A（信任列表 + 指纹） | 低，纯配置/校验 + UI 确认 | 无（阶段 B 独立排期） |

每提交独立过门禁：`pytest tests/lan tests/unit` → `ruff check` → `pyright` → `python run.py --package-smoke` → Windows 打包 smoke（`ci.yml:124-190` 同款）。

## 7. 遗留与后续（不在本轮范围）

- ZIP 分块写 / entry / 临时盘并发预算（reliability roadmap H2 保留）；
- 插件 OS 级沙箱（Windows Job Object / Restricted Token / QuickJS，Serpent 同款）——阶段 B 之后单独评审；
- `/ws` 的 media 限流对长连接会话的适配（WebSocket 握手后不再按请求计费，需确认 ws 帧级预算——原 skip 的合理性在此保留分析）；
- `read_safe_file` 上限常量收敛进 `lan/constants.py` 统一管理，供三层路由引用。
