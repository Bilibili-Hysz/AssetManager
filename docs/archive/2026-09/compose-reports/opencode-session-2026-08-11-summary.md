# 会话完整汇总 — 中危轮收尾验证 + P0/中危全量修改专项审计

> **来源会话**：`ses_013a88a93ffe2V0Gei7HvEt1K4`（MiMoCode compose 模式）
> **时间跨度**：2026-08-10 ~ 2026-08-11（约 03:00 UTC 结束）
> **规模**：2 个用户指令（交接启动 + 审计指令）/ 大量工具调用
> **性质**：全程未产生任何 git commit —— 所有代码改动均处于工作区**未提交**状态
> **用途**：本文件是跨会话交接文档，新会话应先读本文件 + `opencode-session-2026-08-11-startup.md`（快速启动包）+ 会话 1 的两份交接文档

---

## 1. 任务背景

用户在 2026-08-10 晚发起新会话，指令为：

> 先阅读 `docs/archive/2026-09/compose-reports/opencode-session-2026-08-10-startup.md` 和 `...-summary.md`，然后按启动文档的『下一步』执行。

即：继续会话 1（Opencode `ses_017505339ffeas793xTPQ7FLKL`，11 轮 UI/SVG 修复 + P0 高危轮 + 中危轮落盘）的未完成部分——**中危轮最终回归验证（会话 1 在分片回归时中断）**。

随后用户追加第二项任务：

> 审计所有高危和中危修改，务必确保不要引入新错误和性能下降。

## 2. 本会话工作总览

| 阶段 | 内容 | 结果 |
|------|------|------|
| A. 中危轮收尾 | 分片回归 + 修复挂起/回归 + 修复 6 个残留失败 | **全量 2839 passed, 7 skipped, 0 failed** |
| B. 专项审计 | 6 组只读子代理审计 P0+中危全部修改 | 2 严重 + 15 重要 → 17 处修复，复核 17/17 |

---

## 3. 阶段 A — 中危轮收尾（全部验证命令实测）

### 3.1 回归验证结果

| 验证 | 结果 |
|------|------|
| `python -m ruff check AssetsManager/` | 全绿 |
| 中危轮分片回归（会话 1 中断处命令） | **394 passed, 1 skipped**（skip=Windows symlink 权限，预期） |
| 定向核心（icons/themes/bg_effects/workspace_bar/file_list_grid_widget） | 105 passed |
| LAN 全量 | **513 passed**（修复挂起后，77.8s） |
| **全量 `pytest tests -q`** | **2839 passed, 7 skipped, 0 failed**（315.9s；README 基线 2790） |

### 3.2 修复的挂起/回归（2 处实现）

1. **`lan/utils.py` get_local_ip 永久挂起（D2 U1 修复引入的回归）**
   - 根因：`socket.gethostbyname(name)` 对每个网卡名做**同步 DNS 解析**，本机某网卡名解析永久挂起 → 在 aiohttp async handler 内同步调用（shares.py:139）阻塞整个事件循环 → test_lan_api.py 及 LAN 全量永久卡死（`asyncio.wait_for` 超时不触发 = 事件循环被同步阻塞的标志）
   - 修复：`_enumerate_private_ips(timeout=2.0)`（daemon 线程执行解析 + 主线程 `join(2s)` 兜底）+ 进程级 `_local_ip_cache` 缓存（loopback 回退结果**不缓存**，网络就绪后可重试）
   - 效果：test_lan_api 224 用例 118.7s → **18.9s**（缓存消除逐请求 2s 等待）
   - 后记：审计轮又发现 shares.py:139/167 首次调用仍同步阻塞事件循环 2s → 改为 `await asyncio.to_thread(get_local_ip)`（见第 5 节 #16）

2. **`test_public_commerce_auth.py` 骨架缺 `_revoked_tokens`（D1 引入）**
   - 根因：测试用 `object.__new__(_LanServerImpl)` 绕过 `__init__`，而 D1 新增的 `is_auth_token_revoked`（server.py:981）访问 `self._revoked_tokens` → AttributeError（生产代码 L330 总初始化，测试骨架没有）
   - 修复：测试补 `server._revoked_tokens = {}`（仅 test_public_commerce_auth.py:124 带 token 触达，其余骨架短路不触达，已审计确认）

### 3.3 修复的 6 个全量残留失败（均为测试断言未随预期行为变化同步，或测试侧竞态）

| 失败 | 性质 | 修复 |
|------|------|------|
| test_reconciliation_runtime_lifecycle.py:50 | G2 预期行为：失败回滚 `"open"`→`"failed"`（unit 测试已同步，integration 漏改） | 断言改 `"failed"` |
| test_reconciliation_library_owner_handoff.py:142 | 同上 | 断言改 `"failed"` |
| test_lan_sharing.py::test_share_manager_stop... | D1 预期行为：stop 不再抛异常、清 `_server`、`share_state="failed"`、`failure_reason="server_stop_failed"`、二次 stop 幂等 | 断言重写为新契约 |
| test_file_list_shim.py::test_partial_permanent_delete... | E/P0 撤销删除投影快照：undo_dir 现为 备份文件 + `{backup}.projection.json` 2 条目 | 断言改 2 条目 |
| test_asset_index_service.py::test_bound_tree... | worker 竞态：runtime_for 启动 reconciliation worker 在共享连接短暂持事务，测试 BEGIN 相撞 | 测试 BEGIN 前 `reconciliation_service.stop()` |
| test_file_operation_service.py::test_bound_move/delete... | 同上（顺序依赖竞态，单独跑通过、全量失败） | 同上 |

**审计确认**：explore-3 复核全部正确、无遗漏（全仓 `BEGIN` 17 处仅 3 处 runtime 场景需停 worker；`_state=="open"` 断言无残留；30+ 骨架对象仅 1 处需补字段）。

### 3.4 落盘抽查（D1/D2/E）

审计子代理逐条核对 module-*.md 中危项与工作区代码：
- **D2 全 10 项已修复**（scanner 置位原子化、tunnel 下载锁/崩溃监控/start 串行、ws 超时/1MB 上限、dto 类型校验含 is_active 回归）
- **E 全 11 项已修复**（跨盘移动失败清理残留、投影失败不阻断事件、DB 锁外 IO、根校验、撤销 TOCTOU、moved_pairs 契约、lexists 预检）
- **D1 6/7 已修复**（seller 限流 10/300、verify_key 限流、注销撤销令牌、broadcast 竞态、stop 卡死修复）；唯一部分修复 = **lan-core#4 查询串 token 认证**（跨源 Referer 已封堵、/api/shop、/api/info 已 `allow_query=False`，但 server.py:1678 主中间件仍 `allow_query=path != "/ws"`，同源请求仍可 `?token=` 认证——列入下一步待办）

---

## 4. 阶段 B — P0+中危全部修改专项审计

### 4.1 审计方法

因全部改动未提交、与 ~191 个预存修改混合（git SHA 范围不可用），按 6 组文件集互不相交派 explore 只读子代理，对照修复项清单审查工作区当前代码：

| 子代理 | 覆盖范围 |
|--------|---------|
| explore-4 | LAN 认证/路由（P0 A + D1）：security/server/manager/routes{auth,thumbnails,shares}/_helpers |
| explore-5 | LAN 工具链（D2）：scanner/tunnel/utils/ws/dto |
| explore-6 | 文件操作/撤销（P0 B + E）：file_operation_service/undo_service/_actions |
| explore-7 | 导出/完整性/维护（P0 B + F）：library_export/integrity/maintenance |
| explore-8 | core 存储（G1）：settings/json_store/cache/tag_library/project_data/config_migrator |
| explore-9 | runtime/身份（P0 C + G2）：path_resolver/database/runtime/context/tool_scheduler/security_preflight/crash_handler/reconciliation |

### 4.2 审计结论（总体）

- **无崩溃/数据损坏级新缺陷**
- **认证热路径开销可忽略**：SHA-256 摘要 ~1µs、local_ui HMAC ~5µs、无全局锁
- **写锁热路径无新争用**：conn 路径仅短暂取全局 `_write_gate.read()`（读-读并发），gate.write 仅 legacy 无参写入与 close 使用
- crash_handler 脱敏仅崩溃时执行，无热路径影响

### 4.3 发现并修复的问题（17 处，全部落盘）

**严重（2，并发数据丢失）**

| # | 位置 | 问题 | 修复 |
|---|------|------|------|
| S1 | file_operation_service.py move() | `os.path.lexists(dst)` 存在性检查在 `acquire_path_locks` **之外**：并发 move 到同一目标，加锁前目标已存在，`shutil.move` 静默覆盖 | 复查移入锁内、紧贴 `shutil.move` 之前（锁外快速失败路径保留） |
| S2 | file_operation_service.py move_to_directory() | 只锁 `src` 不锁 `target`：并发粘贴同名文件到同一目录，后到者覆盖先落地的 | 锁扩为 `(src, Path(destination_dir)/src.name)` + 锁内计算 `unique_destination`（键一致无死锁） |

**重要（15）**

| # | 位置 | 问题 | 修复 |
|---|------|------|------|
| I1 | runtime.py close() | `event_router.close()` 在 try 外：若订阅 close 抛异常，`_cleanup_in_progress` 永置 True → 后续所有 close() 永久挂起 | try/except BaseException 复位 `_cleanup_in_progress` + notify_all + re-raise |
| I2 | crash_handler.py | 脱敏键名漏 `access_token`/`id_token`/`session_token`/`client_token`（`?access_token=xxx` 明文入 crash.log） | 正则补 4 组 token 键名 |
| I3 | json_store.py + sidebar_favorites/recent | G1 宣称"JsonStore 加锁"未达成：`_on_before_save()` 快照在锁外求值，子类 add/remove 读改写无锁，旧快照可覆盖新写 | 单一 RLock 覆盖 load/mutation/save；子类 public 方法包 `with self._lock` |
| I4 | server.py `_revoked_tokens` | 只增不删、常驻内存无上限（仅命中时删过期项） | `_TOKEN_REVOCATION_MAX=10000` + 命中时 `_prune_revoked_tokens()`（先过期后最旧） |
| I5 | context.py connection_for() | requested_key 用 strict=True 的 `root_identity`：传入不存在根（父目录亦缺）抛 RuntimeError 而非预期 ValueError | requested 侧 `strict=False` |
| I6 | settings.py load() | UTF8 损坏（`UnicodeDecodeError` 是 ValueError 子类）落入 migrate 拒载分支，不 quarantine | 独立 `except UnicodeDecodeError` 分支 → quarantine（顺序在 ValueError 之前） |
| I7 | tag_library.py | 仅改 DEFAULT_SYNONYMS，已落盘 tag_library.json 仍含「场景/毛发」冲突，`_build_reverse` 后写覆盖静默裁决 | `_deduplicate_conflicts()`：load 后 first-wins 去重并持久化 |
| I8 | tunnel.py stop() | 无锁读 `self._process` + 无条件清 `_public_url/_ready`：与 worker 线程并发时清掉刚 start 就绪隧道的 URL | `_state_lock` 内按句柄身份清理（`if self._process is process`） |
| I9 | tunnel.py _start_locked() | 已运行未 ready 分支忽略 `wait(timeout)` 返回值：超时返回 None 但进程继续存活，后续 start 反复白等 | 超时即 `stop()` 返回 None（与新建路径一致） |
| I10 | undo_service.py _execute_reverse() delete 分支 | 恢复前只查 backup 存在，未查 `entry.path` 是否被用户重建：copy2 静默覆盖新文件（rename 分支有 lexists 预检，delete 分支缺失） | 恢复前 `os.path.lexists(entry.path)` 预检 → mark_failed |
| I11 | database_integrity_service.py | 盘断连时全表判 UNKNOWN，`message not in issues` 线性去重 O(n²)（issues 可达上万条） | `_run_issue_seen` set 去重 O(1)，`_run_pass` 收尾复位 |
| I12 | library_export_service.py | 目标存在检查与 replace 间隔整个备份过程（TOCTOU 窗口巨大），期间出现的同名文件被 `os.replace` 静默覆盖 | replace 前紧邻 `os.path.lexists(target)` 复查抛 FileExistsError |
| I13 | shares.py | `get_local_ip()` 首次同步阻塞 2s 卡事件循环（async handler 内） | 两处改 `await asyncio.to_thread(get_local_ip)` |
| I14 | file_operation_service.py acquire_path_locks() | 锁键未 normcase：Windows 上 `C:\Foo` 与 `c:\foo` 得两把锁，同文件并发未串行 | 键用 `os.path.normcase` |
| I15 | test_lan_sharing.py | 上轮断言重写后遗留未用 `import pytest`（ruff F401） | 删除 |

**修复通用模式（值得沉淀）**：文件操作的存在性检查必须与 IO 同持路径锁，目标名也要入锁；事件循环内禁止同步 DNS/阻塞调用；骨架测试模式在 server 新增实例状态后需同步补字段。

### 4.4 复核

explore-10 复核子代理逐一核对 17 处修复：**全部与描述一致、逻辑正确，无新引入死锁/竞态/异常吞噬/行为回退，无审计误修**；实跑全量 `2839 passed, 7 skipped` 与预期一致。

---

## 5. 审计发现但未修的问题（下一步输入，按风险排序）

| 优先级 | 位置 | 问题 | 建议 |
|--------|------|------|------|
| 高 | lan/server.py:1678 | lan-core#4 残留：主中间件 `allow_query=path != "/ws"`，同源/无 Referer 请求仍可 `?token=` 认证（日志/历史泄露面） | 全量 `allow_query=False` 或按端点白名单 |
| 高 | lan/manager.py:218-224 | stop 失败 `finally: self._server=None` 丢弃句柄：LanServerImpl.stop() 超时/失败时线程仍存活、端口仍绑定、状态却显示 stopped/failed，且无法重试 stop，下次 start 报端口占用 | stop 失败时保留 `_server` 引用供重试（注意：D1 审计曾确认此行为，改动需同步更新 test_lan_sharing 契约测试） |
| 中 | lan/ws.py:483-493 | broadcast 1MB 静默丢弃：批量文件操作 `projection_invalidated` paths 超 1MB 时客户端收不到失效通知，界面过期 | 超大事件分片/截断并计数，勿静默丢 |
| 中 | domain/auth.py:81-125 + server.py:969 | 令牌秒级确定性生成（同秒 HMAC 相同）：注销+同秒重新登录拿到已被撤销的同一令牌 → 首次请求 401 卡 1 秒；且 `_revoked_tokens` 重启即失效 | 生成时加随机 nonce |
| 低 | lan/routes/_helpers.py:349-361 | `_query_referer_allowed` 用 netloc 与 request.host 严格字符串相等：主机名大小写、端口别名（localhost vs 127.0.0.1）、IPv6 括号形式误拒同源 query 认证 | 规范化小写+去端口比较 |
| 低 | lan/dto.py:31 | `_as_int` float 分支 `int(round(inf/nan))` 抛 OverflowError/ValueError 未捕获；round 为银行家舍入 | 与字符串分支统一 try |
| 低 | core/tool_scheduler.py:66 | `all(isinstance(a, str))` 误拒合法数值参数（`["--port",8080]`） | int/float 归一化为 str |
| 记录 | lan/security.py:149-177 | 认证限流对成功请求、GET 也计数；NAT 多用户共用 IP 5 分钟锁死；共享密码多次错试连带其他共享；429 Retry-After 硬编码 5 与 60s 窗口不符；get_remaining 每响应 O(n) | 按用户名/失败次数计数、按限流器取值 |
| 记录 | lan/manager.py:490-495 | `_configured_auth_status` 在 auth_service 缺失时返回 `(False,"none")` 潜在 fail-open（当前因 LanServer 构造必失败而不可达） | 改为抛错 |
| 记录 | application/project_data.py | G1 的尺寸缓存 TTL 是死代码：热路径 metadata_service.py:260-281 直走 repo 纯 mtime 无 TTL（"就地编辑不刷新"bug 未修） | P1 轮 M6a 时接入 |
| 记录 | application/library_export_service.py | "512MB 上限移除"仅把快检改跳过，仍残留 1GB/成员、8GB/总量、1 万文件硬上限；并发检测 stat 与读取句柄不一致（rename-over 盲区）；持续写入文件 3 次重试后整备份中止；取消检查点未覆盖校验段；快照全程持 db_write_lock | P1 轮 M6a 时处理 |
| 记录 | lan/server.py:1502-1506 | fail-closed 无负缓存：DB 故障期间每请求一次失败查询+完整 `_log.exception` 堆栈（日志洪水） | 失败短暂负缓存 |

**性能核查通过项**：写锁热路径无新争用（gate.read 读-读并发）、认证热路径开销可忽略、undo 栈 O(1)/depth≤20、`_refresh_after_move` 仅重索引父目录+被移子树（非全库）、广播无双重序列化、tunnel 监视线程 1s 轮询开销可忽略。

---

## 6. 下一步（按优先级）

1. **审计遗留项**：第 5 节高/中优先项（lan-core#4 query token 收尾、manager stop 保留句柄、ws 1MB 分片、auth nonce）
2. **中危清单剩余项**：module-lan-core.md 中未修的限流策略/计数口径等
3. **P1 轮**：M6a 资产/索引/缩略图/搜索服务（含 project_data TTL 接入、library_export 上限与并发检测）、M9 repositories 16 文件 SQL 安全、M6c 分享/商业（配额竞态、订单状态机、金额精度）
4. **P2 轮**：M1 file_list、M2 info/sidebar、M3 dialogs（sharing_settings_dialog 2161 行）、M4 窗口/dock、M5+M7 controllers/domain（约 121 项低危）
5. **补测试缺口**：tests/unit/test_tray.py 缺 QApplication fixture 会挂起；grid 补 scale 重排/省略号用例；file-ops #13 批量 move 部分成功撤销（moved_pairs 契约已落盘，补撤销完整性用例）

**执行模式**（沿用既定流程）：每轮 explore 排 Bug → 修复子代理（文件集互不相交）→ 第二子代理复核真实性 → 修复后审计子代理复审 → ruff + 定向 pytest 全绿；既有 2839 测试保持全绿。

---

## 7. 代码改动范围（全部未提交，与 191 个预存修改文件混在工作区）

- **本次会话改动（17 处修复）**：
  - `AssetsManager/lan/utils.py`（get_local_ip 挂起修复：daemon 线程+超时+缓存）、`AssetsManager/lan/server.py`（_revoked_tokens 上限与清扫）、`AssetsManager/lan/tunnel.py`（stop 句柄身份清理、_start_locked 超时）、`AssetsManager/lan/routes/shares.py`（to_thread 包装 + import asyncio）
  - `AssetsManager/application/file_operation_service.py`（S1/S2/I14）、`AssetsManager/application/runtime.py`（I1）、`AssetsManager/application/context.py`（I5）、`AssetsManager/application/undo_service.py`（I10）、`AssetsManager/application/database_integrity_service.py`（I11）、`AssetsManager/application/library_export_service.py`（I12）
  - `AssetsManager/core/crash_handler.py`（I2）、`AssetsManager/core/json_store.py`（I3）、`AssetsManager/core/settings.py`（I6）、`AssetsManager/core/tag_library.py`（I7）
  - `AssetsManager/dialogs/sidebar_favorites.py`、`AssetsManager/dialogs/sidebar_recent.py`（I3 配套加锁）
  - 测试：`tests/lan/test_public_commerce_auth.py`（骨架补字段）、`tests/unit/test_lan_sharing.py`（stop 契约重写 + 删未用 import）、`tests/desktop/test_file_list_shim.py`（2 条目断言）、`tests/integration/test_reconciliation_runtime_lifecycle.py` 与 `test_reconciliation_library_owner_handoff.py`（"failed"断言）、`tests/integration/test_asset_index_service.py` 与 `test_file_operation_service.py`（bound 族停 worker）
- **会话 1 改动**：见 opencode-session-2026-08-10-summary.md 第 15 节（core/application/lan/Presentation/i18n/测试约 30 文件）

---

## 8. 注意事项与已知坑（新会话必读）

- **不要 commit/push**：所有改动（含 191 个预存修改）均在未提交工作区；仓库无远程 remote
- **工作区 diff 混杂**：`git diff` 中与任务无关的 hunk 是预先存在的用户改动，修复/审计时勿误判、勿回退
- **RuntimeData 会被测试污染**：测试产生海量残留目录（曾达 10.5 万），拖慢一切且淹没扫描类脚本；扫描/迁移脚本应支持显式库根参数；测试前建议定期清理
- **Windows 挂起诊断**：事件循环内同步 DNS/阻塞调用会挂死且 wait_for 超时不触发；抓栈用 daemon 线程轮询 `sys._current_frames()`；faulthandler timeout 在 Windows 无效；探针脚本必须 `python -u`
- **bound 族测试**：验证外层事务边界时，`runtime_for` 后必须先 `reconciliation_service.stop()` 再 BEGIN（worker 启动在共享连接短暂持事务）
- **骨架测试模式**：`object.__new__(_LanServerImpl)` 绕过 `__init__`，server 新增实例状态（如 `_revoked_tokens`）后需同步补测试字段；不要在生产代码加防御性 getattr
- **测试文件路径**：`tests/desktop/test_workspace_bar.py`、`tests/application/test_tag_service.py`、`tests/core/test_color_utils.py`、`tests/desktop/test_startup.py`、`tests/unit/test_undo_service.py`、`tests/core/test_json_store.py` 均不存在；实际路径：workspace_bar 在 `tests/unit/`、tag_service 在 `tests/integration/`、undo 在 `tests/integration/test_undo_service.py`、tag_library 在 `tests/unit/test_tag_library.py`
- **Qt 整数 0 陷阱**：`QPixmap.fill(0)` 是不透明黑（`Qt.GlobalColor.color0`）而非透明 —— 必须用 `fill(Qt.GlobalColor.transparent)`
- **LSP 噪音**：`_grid_widget.py:1060` 附近 "data/index is not a known attribute of None" 等报错为既有 stub 噪音
- **Windows 环境**：目录 symlink 测试无权限会 skip；进程终止类测试不具确定性会 skip
