# 会话启动文档 — 中危轮收尾验证 + P0/中危全量修改审计（2026-08-11 交接）

> **使用方式 A（推荐）**：把本文件**全部内容**作为新会话的第一条消息。
> **使用方式 B**：新会话第一句话写：「先阅读 `docs/archive/2026-09/compose-reports/opencode-session-2026-08-11-startup.md` 和 `docs/archive/2026-09/compose-reports/opencode-session-2026-08-11-summary.md`，然后按启动文档的『下一步』执行。」
>
> 本文件是"快速启动包"，细节请查 `opencode-session-2026-08-11-summary.md`（完整汇总）。

---

## 一、开场指令（可整段粘贴给新会话）

```
请作为本项目的工程代理，继续以下工作。

【项目】基于 Python PySide6 的桌面资产管理器（含 aiohttp LAN 分享服务），仓库位于
D:\~Vibe-Coding\Projects\AssetsManager_old-bak。分层：Presentation（window.py/panels/widgets/dialogs）
→ Controllers → Application（服务层）→ Domain → Infra（core/repositories）→ LAN（aiohttp，约 9.4k 行）。

【背景】此前的两个 Opencode/MiMoCode 会话已完成：
- 会话 1（2026-08-10 交接，见 opencode-session-2026-08-10-startup.md）：UI/SVG 绘制 Bug 审计修复（13 项）、
  图标 SVG 化（含 fill(0)=不透明黑根因）、图标语义色体系（6 个 icon_* token）、菜单栏审查、
  逐模块排 Bug（约 177 项）、P0 高危修复轮（15+4 项全修）、中危修复轮六组（D1/D2/E/F/G1/G2）落盘。
- 会话 2（本次，2026-08-11）：中危轮收尾验证全绿 + 对 P0/中危全部修改做了一轮专项审计并修复 17 处。
所有代码改动均在工作区【未提交】状态，与约 191 个预存修改文件混在一起（git status 约 500+ 行）。

【当前状态】全量回归已全绿：pytest tests -q → 2839 passed, 7 skipped, 0 failed（约 5 分钟）。
P0 高危轮 + 中危轮六组修改已通过 6 组只读子代理专项审计，发现并修复 2 严重 + 15 重要问题
（详见 summary 第 5 节），复核子代理 17/17 确认无新错误、无性能下降。

【下一步，按优先级】
1. 处理审计遗留项（已记录、未修，按风险排序）：
   a. lan-core#4 查询串 token 认证收尾：server.py:1678 主中间件仍 allow_query=path != "/ws"，
      同源请求仍可 ?token= 认证（日志/历史泄露面）——建议全量 allow_query=False 或按端点白名单
   b. manager.py:218-224 stop 失败 finally 清 _server 句柄：LanServerImpl.stop() 超时/失败时线程仍存活、
      端口仍绑定、状态却显示 stopped/failed，且无法重试 stop——建议失败时保留 _server 供重试
      （注意：D1 审计曾确认此行为，改动需同步更新 test_lan_sharing 契约测试）
   c. ws.py:483-493 broadcast 1MB 静默丢弃：批量操作 projection_invalidated 超大事件收不到——
      建议分片/截断并计数，勿静默丢
   d. auth 令牌秒级确定性生成（同秒 HMAC 相同）：注销+同秒重登拿到已撤销令牌→401 卡 1 秒——
      建议生成时加随机 nonce（domain/auth.py:81-125 + server.py:969）
   e. 小项：_query_referer_allowed 主机名大小写/端口别名规范化（_helpers.py:349-361）、
      dto._as_int 对 inf/nan 统一 try（dto.py:31）、tool_scheduler 数值参数归一化为 str（:66）
2. 中危清单剩余项：确认 6 组清单中未覆盖的中危项（module-lan-core.md 中未修的限流策略/计数口径等）
3. P1 轮：M6a 资产/索引/缩略图/搜索服务、M9 repositories 16 文件 SQL 安全、M6c 分享/商业
   （配额竞态、订单状态机、金额精度）
4. P2 轮：M1 file_list、M2 info/sidebar、M3 dialogs（sharing_settings_dialog 2161 行）、M4 窗口/dock、
   M5+M7 controllers/domain（约 121 项低危）
5. 补测试缺口：tests/unit/test_tray.py 缺 QApplication fixture 会挂起；grid 补 scale 重排/省略号用例；
   file-ops #13 批量 move 部分成功撤销（moved_pairs 契约已落盘，补撤销完整性用例）

【红线】
- 不要 commit / push（仓库无远程 remote；工作区有用户预存未提交改动，git diff 中与任务无关的 hunk 勿动勿回退）
- 不要修改 DeepSeek Docs/ 目录
- 执行模式：探索排 Bug → 修复子代理（文件集互不相交）→ 第二子代理复核真实性 → 修复后审计子代理复审 → ruff + 定向 pytest 全绿
- 涉及 RuntimeData 扫描/迁移的脚本必须支持显式库根参数（目录会被测试残留严重污染）
- 探针脚本注意：QIcon.pixmap(n,n) 在图标实际尺寸小于 n 时返回实际尺寸，越界采样会得到错误像素；
  Windows 上抓挂起线程栈用 daemon 线程轮询 sys._current_frames()（faulthandler 的 timeout 在 Windows 无效）；
  探针脚本必须 python -u（stdout 块缓冲，进程被杀日志全丢）
```

---

## 二、已完成工作速览（3 个会话阶段，一行一个）

| 阶段 | 内容 | 结果 |
|------|------|------|
| 会话 1（08-10） | UI/SVG 审计 13 项、SVG 化、语义色体系、菜单栏 6 项、177 项排 Bug、P0 轮 15+4 全修 | 370 + LAN 513 + 桌面 547 无回归 |
| 会话 1（08-10） | 中危轮六组（D1/D2/E/F/G1/G2）落盘 + 审计 | 最终回归验证被中断 → 交给会话 2 |
| 会话 2（08-11） | 中危轮收尾：分片回归 + 修复 2 个挂起/回归 + 6 个残留失败 | **全量 2839 passed, 0 failed** |
| 会话 2（08-11） | P0+中危全部修改专项审计：6 子代理 → 2 严重 + 15 重要 → 17 处修复 | 复核 17/17，全量仍 2839 passed |

---

## 三、当前工作区状态（最重要）

- **所有改动未提交**：三个会话全程零 commit；改动与约 191 个预存修改文件混合在工作区（git status 约 500+ 行）
- 最近 HEAD 提交是 fbf3403（webui 相关，与本桌面工作无关）
- 迁移脚本 `scripts/migrate_legacy_icons.py` 正常状态：`libraries scanned: 10, failed: 0`
- RuntimeData 会被测试污染（曾达 10.5 万残留目录）；测试前建议定期清理，涉及扫描的脚本必须显式库根参数
- 本次会话修改文件清单（17 处修复）见 summary 第 5 节表格

---

## 四、文档索引（仓库内既有产物）

| 文件 | 内容 |
|------|------|
| `docs/archive/2026-09/compose-reports/opencode-session-2026-08-11-summary.md` | 本次会话完整汇总（本文件的细节版） |
| `docs/archive/2026-09/compose-reports/opencode-session-2026-08-10-startup.md` / `-summary.md` | 会话 1 交接包（11 阶段、中危轮落盘细节） |
| `docs/archive/2026-09/reports-superseded/ui-rendering-audit-2026-08-10.md` | 13 项 UI Bug 审计 + 修复记录 |
| `docs/plans/icon-svg-migration-2026-08-10.md` | SVG 化规划、黑底根因、主题色修复、语义色体系 |
| `docs/archive/2026-09/reports-superseded/menubar-review-2026-08-10.md` | 菜单栏 6 项修复 + 审计附录 |
| `docs/plans/bug-hunting-2026-08-10.md` | 逐模块排 Bug 计划 + P0 轮结果 + 高危修复记录 |
| `docs/reports/module-{lan-core,lan-routes,lan-tools,file-ops,maintenance,core-db,core-store,runtime}.md` | 8 份模块缺陷清单（177 项）—— P1/P2 轮直接工作输入 |

---

## 五、关键机制速查（新代理必读）

- **图标**：`core/icons.py` SVG 注册表 `icons.icon(name, color=None, size)`；color 三态：`None`→icon_primary、语义 token 名→themes.color() 解析、hex/rgba→原样；DPR 感知渲染；缓存键 `(name, tint, size, dpr)`；`icons.clear_cache()` 主题切换时调用
- **主题**：`core/themes.py` + `theme_loader.py` JSON 热重载；`Assets/Themes/` 22 个主题；文本 token + 6 个图标 token（icon_primary/icon_secondary/icon_muted/icon_on_accent/icon_accent/icon_disabled）
- **RuntimeData**：库数据按哈希槽位存放；`Shared/<hash>.identity` 为库身份标记（path_resolver.py）；迁移脚本默认不扫描 RuntimeData
- **LAN**：aiohttp 服务器，认证 fail-closed（DB 异常拒绝放行）、缩略图/分享排除 .svg + nosniff、ZIP 拒绝 symlink 越界；令牌撤销 `_revoked_tokens`（TTL 24h，10000 上限惰性清扫）；认证限流 AuthRateLimiter 10 次/300 秒
- **文件操作**：move 禁止覆盖已存在目标（锁内复查）；批量 move 部分成功撤销用 `moved_pairs` 契约；`acquire_path_locks` 进程级路径锁（normcase 键、排序获取防死锁）；IO 在 DB 写锁外执行
- **JsonStore**：单一 RLock 覆盖 load/mutation/save（`_on_before_save` 求值在锁内）；原子写（tempfile+os.replace+fsync）

---

## 六、验证命令速查

```powershell
# 静态检查
python -m ruff check AssetsManager/ tests/

# 全量回归（基线 2839 passed, 7 skipped；耗时约 5 分钟）
python -m pytest tests -q

# LAN 全量（约 513 项，约 1.5 分钟）
python -m pytest tests/lan -q

# 中危轮相关定向（394 passed）
python -m pytest tests/core tests/unit -k "settings or cache or tag_library or json_store or config_migrator or project_data or file_operation or undo or integrity or maintenance or export or runtime or reconciliation or crash or security_preflight or tool_scheduler"

# 定向核心（UI/图标层，105 passed）
python -m pytest tests/core/test_icons.py tests/core/test_themes.py tests/core/test_bg_effects.py tests/unit/test_workspace_bar.py tests/desktop/test_file_list_grid_widget.py -q

# 审计轮修复相关定向（461 passed）
python -m pytest tests/unit/test_lan_sharing.py tests/unit/test_tag_library.py tests/integration/test_undo_service.py tests/integration/test_file_operation_service.py tests/integration/test_favorite_service.py tests/desktop/test_file_list_shim.py tests/integration/test_reconciliation_runtime_lifecycle.py tests/integration/test_reconciliation_library_owner_handoff.py tests/lan/test_lan_api.py -q
```

---

## 七、已知坑清单

- `QPixmap.fill(0)` 是不透明黑（`Qt.GlobalColor.color0`）—— 透明必须写 `fill(Qt.GlobalColor.transparent)`
- Windows 上 `socket.gethostbyname(网卡名)` 可能**永久挂起**（接口名被当主机名解析）——绝不能在事件循环内同步调用；
  诊断判据：`asyncio.wait_for` 超时不触发 ⇒ 事件循环被同步阻塞。修复模式：daemon 线程 + join(timeout) + 进程级缓存
- Windows 抓挂起线程栈：daemon 线程循环 `sys._current_frames()` + `traceback.print_stack`；
  `faulthandler.dump_traceback_later` 与 pytest `-o faulthandler_timeout` 在 Windows 均不生效（无 SIGALRM）
- 探针脚本必须 `python -u`（重定向时 stdout 块缓冲，进程被杀则日志全丢）
- `bootstrap.runtime_for()` 启动 reconciliation daemon worker，启动时在共享连接上短暂持有事务（~0.5s）——
  bound 族测试（验证外层事务边界）必须在 `conn.execute("BEGIN")` 前显式 `reconciliation_service.stop()`；
  生产代码不受影响（queue store 用 SAVEPOINT 保护 caller 事务）
- `_LanServerImpl` 骨架测试模式（`object.__new__` 绕过 `__init__`）在 server 新增实例状态后需同步补字段，
  不要在生产代码加防御性 getattr
- 测试文件路径易错：`test_workspace_bar.py` 在 `tests/unit/`；`test_tag_service.py` 在 `tests/integration/`；
  `test_startup.py` 实际是 `test_startup_window.py`；`test_color_utils.py` 不存在；undo 测试在 `tests/integration/test_undo_service.py`
- `tests/unit/test_tray.py` 缺 QApplication fixture 会挂起（预存问题，补测试时注意）
- Windows 环境：目录 symlink 测试无权限会 skip；进程终止类测试不具确定性会 skip（均为预期）
- LSP 报错 `_grid_widget.py:1060` 附近 "data/index is not a known attribute of None" 为既有 stub 噪音
