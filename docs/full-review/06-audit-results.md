# 审查结果（06-audit-results.md）

> 审查日期：2026-08-11 · 工作区实况 · 汇聚本轮 6 域审查发现 + 历史审计结论 + 文档过时清单

## 1. 本轮审查新发现（按域）

### 1.1 后端核心/数据层
1. **`docs/migrations.md` 严重过时**：只记录到 v6，实际 v23（v7-23 完全缺失）
2. **`path_guard.py` 无显式 NUL/ADS 拒绝**：防护完全依赖 `Path.resolve()` 规范化 + is_relative_to；若此前文档声称"NUL/ADS 显式拒绝"需修正（实际靠 resolve 兜底，module-lan-core Bug8/9 记录为低危待办）
3. **`ProjectData.get_dir_size` 无生产调用方**（TTL 死代码问题已在 P1 修：metadata_service 接入 30s TTL）
4. **`auth_repository.insert_user_with_invite`/`consume_invite_code` 仍为裸 except**（P1 只修了 insert_user/insert_invite_code；同类模式残留 2 处，低危记录）
5. **Cython 产物 4 个 .pyd 全部存在**，源码回退保留（删除 .pyd 即回退纯 Python）

### 1.2 应用服务层
6. **`StorefrontAnalyticsService`/`SellerProfileService`/`FreeDownloadQuotaService` 为每请求构造**（无缓存）——低开销，但注意与 `shop.py` 缓存构造的差异
7. **`_LanServicesHolder` 懒投影**：`search_service` 构造时 `require_library_session`——任何绕过 bootstrap 直构 SearchService 的调用会抛 TypeError（契约保护）
8. **`library_export_service` 行数 2112**（工作区）——备份/恢复三块结构复杂，改动需专属测试覆盖（tests/unit/test_library_export_service.py 约 800 行）

### 1.3 LAN 层
9. **`lan/static` 已不存在**（旧静态前端废弃）；SPA 由 pages.py 托管 webui/dist
10. **`path_guard` 对 URL 解码层**：aiohttp 双重解码后 resolve 兜底；`%00`（NUL）在 resolve 时抛 ValueError 可能 500（module-lan-core Bug8，低危记录，未修）
11. **`/api/stats` 无 admin 检查**（仅 auth）——设计如此（容量统计），记录
12. **路由注册 139 条**（任务描述"约 150+""约 110"均不准；routes/ 24 个 .py 含 __init__/_helpers/_resource_urls）

### 1.4 桌面 UI
13. **6 个 widget 零生产消费方**（待接线）：command_palette/file_picker/pager_overlay/theme_gallery/status_bar/title_bar（title_bar 自带注释声明）
14. **`AdminManagement.test.tsx` 孤儿测试**（前端）
15. **grid 与 AssetService 双实现**：桌面 file_list 直接 os.scandir，LAN 走 AssetService——同一目录两套代码，语义一致性靠测试分别覆盖（潜在漂移风险）

### 1.5 前端
16. 前端 `stats` 投影域仅前端存在（服务端 14 域，前端 15 域白名单）
17. `GalleryHomePage` 未消费 feature_flags
18. `run-vitest.mjs` subst workaround 是 Windows 特有——CI Linux 走原生 vitest（需保持脚本兼容）
19. **前端深度扫描轮（2026-08-11）**：75 项（2 高/24 中/49 低）全部修复——ErrorBoundary、懒加载、竞态守卫、错误态重试、请求超时、i18n 补齐（详见 05 §11 与 docs/reports/frontend-fine-scan-2026-08-11.md）
20. **quota cookie flaky 定位**：测试篡改 base64 末字符仅贡献 4 比特，~1/16 概率篡改无效——改篡改 cookie_id 段后稳定（产品 HMAC 实现正确）

### 1.6 信号/数据流
19. `LibraryOpened` 事件无订阅者（仅记录）——桌面会话建立不依赖它（经回调链），Web 用 runtime_ready 替代
20. **桌面与 Web 双通道刷新**：同一 FileSystemChanged 既触发桌面 file_list 500ms 防抖，又经 WS 推给浏览器——桌面开分享时同事件双消费（设计如此）

## 2. 文档过时清单（逐条差异）

### 2.1 README.md
| 项 | 文档 | 实际 |
|---|---|---|
| API 端点表 | 13 行 | 139 条路由（缺失 gallery/favorites/quicksearch/image/notes/activity/online-users/websocket/revision/quota + 全部 55 条 commerce/seller） |
| 服务模块 | 8 个 | 39 个 |
| 目录树 core | 18 模块 | 33 模块 + plugins/4 |
| repositories | 5 个 | 15 个 |
| 代码示例 | `LanServer(library_root=...)` | 构造强制 `runtime=`；`mgr.start(port, lib_root=)` 无效 |
| 权限模型表 | 缺预览列/realtime/local_ui | 8 位 capabilities 完整 |
| 门禁声明 | 2790 passed（2026-08-09） | 2952 passed（2026-08-11） |

### 2.2 docs/architecture.md（相对最准确）
- 服务表 17 行 → 缺 reconciliation 系列/商务栈/RuntimeEventRouter/LibraryScopedServices 结构
- 路由表 12 模块 → 实际 24 文件 139 条；`api.py ~98 lines` → 360 行
- A3 快照字段（eager 10 + LAN 3）→ eager 增 reconciliation 系列、LAN 增 gallery/favorite
- "Future Work：Pyright 83 errors"与 README"0 errors"矛盾（以 CI 白名单实测为准）

### 2.3 docs/lan-security.md
- token 读取顺序：文档"cookie → header → query" → 实际 **header(Bearer) 优先 → cookie，不支持 query**
- 公开路径：文档含 /api/tunnel/status、/ws、/static → 实际 tunnel-status 需 admin、/ws 需 realtime、/static 不存在（/assets 前缀）
- AuthRateLimiter 范围 → 实际还含 verify_key/seller-login/shop-auth-login + 任意 shares/*/verify
- 默认限流 1000/60s → _LanServerImpl 默认 100（ShareManager 默认 1000）
- verify_user_token 签名过时

### 2.4 docs/migrations.md
- 只到 v6；缺 v7-23；无 savepoint 事务/版本化契约回溯/未来版本拒绝描述；v2 SQL 快照过时

### 2.5 DeepSeek Docs/（2026-08-01 基线，结构性准确）
- 03 章：服务 17 → 39；行号全漂移；ShareService 密码规则 4-128 → 8-128；未提 reconciliation/发布状态机/商务栈/restore 令牌契约
- 04 章：迁移表 v1-v5；行号失效；project_data"已废弃"表述不准确（类仍是 LibraryContext 字段）
- 05 章：仓库 6 → 15；未提 for_session 绑定/session_contract/savepoint 契约
- 07 章：缺 window_coordinator/lifecycle_coordinator/RuntimeEventSubscription；sharing_settings 结构描述过时；6 个组件清单缺失
- 08 章：路由表只 5 条；api 清单缺 5 工厂；旧静态 UI 表述过时；测试数字过时

## 3. 技术债与风险清单（按优先级）

### 待办（从历史审计 + 本轮）
| # | 项 | 状态 |
|---|---|---|
| 1 | **P2 轮**：M1-M7（桌面 UI/控制器/领域约 121 项低危） | ✅ 已完成（2026-08-11） |
| 2 | **M4 投递令牌 URL 明文**：delivery_url 含裸令牌（前端依赖 /storefront/delivery/:token）——需前后端配合改短 id/header 传递 | 记录（H2 撤销机制已兜底） |
| 3 | **M6a-8 get_home 全表扫描**：LAN 首页每请求全量 thumbnail_metadata + 每行 2 stat | 性能轮 |
| 4 | **DB 迁移 v24**：assets 目录 mtime 快照列（M6a-18 可靠实现前提） | 待办 |
| 5 | **心跳续约硬上限**：reconciliation worker 挂起（网络盘卡死）时任务永久 RUNNING | 中危记录 |
| 6 | 免费配额表/analytics 表无全局清理（身份无限增长） | 低 |
| 7 | metadata TTL 缓存 dict、share 失败计数 dict 无修剪 | 低 |
| 8 | auth_repository 2 处裸 except 残留 | 低 |
| 9 | 6 个桌面 widget 零消费方（接线或删除决策） | 低 |
| 10 | AdminManagement.test.tsx 孤儿测试（现为组合测试；admin 组件未挂路由） | 低 |
| 11 | module-lan-core Bug8/9（NUL→500、NTFS ADS）——resolve 兜底但无显式拒绝 | 低 |
| 12 | metadata add_url 跨连接读改写丢失更新（需原子 append 或新表） | 低 |
| 13 | **前端 admin 面板接线** | ✅ 已完成（2026-08-11）：/admin 路由（ProtectedRoute manage_users）+ AdminPage（5 区块）+ Header/AppHeader 菜单导航 + 2 测试 |
| 14 | **A4 单文件下载 window.open**（契约测试钉死，需同步改契约与 BrowsePage） | 后续 |
| 15 | **A9 后端双重 unquote**（downloads.py/gallery.py，文件名含字面 %XX 时路径解错） | 后续 |
| 16 | **BuyerOrders 分页**（ORDER_LIMIT=50 无 cursor 客户端支持） | 后续 |

### 红线与工程约定
- **不 commit/push**（仓库无远程；工作区 529 条未提交变更与用户预存 hunk 混合——git diff 无关 hunk 勿动勿回退）
- **不改 DeepSeek Docs/** 目录
- 执行模式：探索排 Bug → 修复子代理（文件集互不相交）→ 复核 → 审计 → ruff + 定向 pytest 全绿
- RuntimeData 会被测试污染（曾 10.5 万残留目录）：扫描/迁移脚本必须显式库根参数
- 探针脚本 `python -u`；Windows 挂起抓栈用 daemon 线程轮询 sys._current_frames()（faulthandler timeout 无效）
- 测试路径坑：test_workspace_bar 在 tests/unit/；tag_service 测试在 tests/integration/；undo 在 tests/integration/test_undo_service.py；tag_library 在 tests/unit/test_tag_library.py
- 骨架测试（object.__new__ 绕过 __init__）在 server 新增实例状态后需补字段
- bound 族测试：runtime_for 后先 reconciliation_service.stop() 再 BEGIN

## 4. 审计结论（历史轮次已核实的正确性声明）

| 领域 | 结论 |
|---|---|
| SQL 安全 | 全参数化、LIKE 转义、ORDER BY 白名单——全部复核通过（P0/P1 两轮） |
| 配额竞态 | CAS 条件 UPDATE + 连接写锁 + schema CHECK 三层防护，无超卖 |
| 订单状态机 | 服务层白名单 + 仓库 CAS 双保险；投递令牌生命周期（fulfill/rotate 作废/revoke）闭环 |
| 金额精度 | 全整数 cents 无浮点路径；结账金额与校验时同快照（item 透传） |
| 路径安全 | PathGuard + assert_under_root + resolve 防 symlink 逃逸 + ZIP islink 拒绝 |
| 事件投影 | 会话隔离（session_token+root 校验）、revision 单调、WS 截断不静默丢、前端缺口恢复 |
| 性能 | 热路径无回归（P0/P1 两轮审计实测）；认证开销 µs 级 |
