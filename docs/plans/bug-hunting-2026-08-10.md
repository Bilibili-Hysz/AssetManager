# 逐模块排 Bug 任务计划（2026-08-10）

> 依据架构图（DeepSeek Docs/01-项目总览与架构.md）组织：每个模块一张任务卡，
> 含范围、检查重点、已知风险线索、交付物。执行方式：explore 子代理排 Bug →
> 修复子代理 → 审计子代理（与既往三轮流程一致）。

## 架构图 → 模块映射与规模

```
┌─ Presentation (65 文件 / 23.6k 行) ─────────────┐
│  M1 file_list  M2 info/sidebar/tag_tree         │
│  M3 dialogs  M4 window/widgets/coordinator      │
├─ Controllers (5 / 740)  → M5                    │
├─ Application (39 / 19.1k) → M6a 资产库 / M6b 文件│
│   撤销 / M6c 分享商业                           │
├─ Domain (8 / 933) → M7                          │
├─ Infrastructure core (35 / 8.0k) → M8           │
│              repositories (16 / 5.7k) → M9      │
└─ LAN (37 / 9.4k) → M10a 核心 / M10b routes /    │
                   M10c 工具链                    │
```

**已完成面**（不重复）：UI 渲染 13 项、SVG 化（黑底/emoji/语义色）、菜单栏 6 项、
themes/icons/color_utils/bg_effects/ui_scale/theme_loader、grid_widget 核心、
image_viewer、workspace_bar、tray/toast/tag_chip/status_indicator。

---

## P0 · 高价值高风险（先执行）

### M10 LAN（9.4k 行）— 安全与可靠性
- **范围**：`lan/`：api、auth、dto、manager、path_guard、principal、scanner、
  security、server、tunnel、utils、ws + `lan/routes/*`（23 路由）
- **检查重点**：
  1. 路径遍历：path_guard 与各文件/缩略图/下载路由的组合防线（含 URL 编码二次解码、符号链接）
  2. 认证：cookie/JWT 校验、密码散列、邀请码、会话过期、中间件顺序
  3. 限流/黑名单/IP 白名单边界与绕过
  4. WebSocket 生命周期（断线重连、广播、权限）
  5. 并发：aiohttp 任务取消、连接池、资源释放
  6. 错误响应信息泄露（堆栈/路径/版本）
- **子代理**：A1=server/auth/security/path_guard/principal/api；A2=routes/*（分组：文件/下载/缩略图 vs 用户/分享/商业）；A3=scanner/tunnel/utils/ws
- **交付**：每项 bug 带 文件:行号 + 复现路径 + 修复建议

### M6b Application·文件操作与撤销
- **范围**：file_operation_service、undo_service、library_export_service、
  database_integrity_service、database_maintenance_service
- **检查重点**：复制/移动/重命名/删除的事务边界；撤销栈正确性（跨库隔离、
  重命名-撤销-重做链）；跨设备移动、目标冲突、只读/隐藏文件、回收站；
  导出 ZIP 大文件内存；数据库完整性检查的锁与并发
- **子代理**：B1=file_operation+undo；B2=export+integrity+maintenance

### M8 Infra·core 基础设施（未审面）
- **范围**：database、db_migrations、settings、config_migrator、cache、
  directory_cache、json_store、library_lock、library_manager、path_resolver、
  signal_bus、session_contract、tag_library/tag_store、project_data、protocols、
  schema_defs、singleton、performance、crash_handler、tool_scheduler、
  security_preflight、runtime、runtime_events、reconciliation_*、bootstrap、context
- **检查重点**：
  1. DB：连接池生命周期、WAL、迁移幂等（v1~v19 历史 DDL）、读写锁死锁
  2. signal_bus 连接泄漏（Qt 信号 vs 领域事件）；事件路由丢事件
  3. JSON 存储写入原子性（favorites/recent/settings 崩溃安全）
  4. 锁：library_lock 跨进程、崩溃释放
  5. 配置迁移向后兼容；session_contract 契约
- **子代理**：C1=database/migrations/lock/path_resolver；C2=settings/json_store/cache/tag_store；
  C3=runtime/runtime_events/reconciliation/bootstrap/context

## P1 · 常规面

### M6a Application·资产与库服务
- **范围**：asset_index_service、asset_index_reconciliation_service、asset_service、
  library_service、metadata_service、thumbnail_service、search_service、
  gallery_service、project_service、tag_service、favorite_service
- **检查重点**：索引懒填充/对账（reconciliation_queue 三件套）、缩略图缓存键
  与 mtime、搜索 SQL 注入/转义、库统计一致性、标签同义词/规范化
- **子代理**：D1=index/reconciliation/thumbnail；D2=search/metadata/gallery/project/tag

### M9 Infra·repositories（16 文件）
- **检查重点**：SQL 参数化（无 f-string 拼接）、事务提交/回滚、会话绑定
  （跨库串库）、返回契约一致性、游标关闭
- **子代理**：E1 全部 16 文件（可拆 E1a tag/metadata/favorite/thumbnail；E1b share/auth/order/quota/shop/*）

### M6c Application·分享与商业
- **范围**：share_service、auth_service、seller_auth_service、seller_profile_service、
  shop_service、shop_buyer_service、order_service、quota_service、
  free_download_quota_service、storefront_analytics_service、plugin_service
- **检查重点**：分享链接限时/限次竞态、配额并发扣减、订单状态机、货币金额
  精度（浮点）、插件沙箱/权限边界
- **子代理**：F1=share/auth/seller；F2=shop/order/quota/storefront

## P2 · 桌面交互面

### M1 Presentation·文件列表（未深审面）
- **范围**：file_list 的 `_actions`（拖放/右键/批量）、`_model`（扫描/取消/
  代际）、`_loader`（缩略图队列）、`_detail_model`、`_navigation`、`_shortcuts`、
  `_batch_rename`、`_commands`
- **检查重点**：拖放状态机（外部导入 vs 库内移动）、Ctrl+滚轮缩放与
  快捷键冲突、扫描取消后过期结果丢弃、批量重命名正则边界、命令分发
- **子代理**：G1=_actions+_commands+_shortcuts；G2=_model+_loader+_navigation+_batch_rename

### M2 Presentation·信息面板与侧边栏（剩余面）
- **范围**：info（异步代际/标签流/URL 发现）、sidebar（搜索代际/深度配置）、
  tag_tree、image_viewer 剩余、base/empty、_event_bridge
- **子代理**：H1=info；H2=sidebar/tag_tree/_event_bridge

### M3 Presentation·对话框（未深审面）
- **重点**：sharing_settings_dialog（2161 行最大对话框：状态同步/热重载）、
  settings_dialog、startup、tabbed_dialog、share_link/qr（线程）、
  generic_settings、color_picker、plugin_manager、sidebar_settings
- **子代理**：I1=sharing_settings_dialog；I2=其余对话框

### M4 Presentation·窗口/停靠/组件
- **重点**：window 生命周期（会话切换/关闭语义）、dock 布局保存恢复、
  lan_sharing 启停、tab_container、file_picker、theme_gallery、shortcut_manager、
  command_palette、pager_overlay
- **子代理**：J1=window/coordinator/lifecycle；J2=widgets 剩余

### M5 Controllers + M7 Domain
- **重点**：无 Qt 纯逻辑（搜索代际、LRU、分类、URL 发现）；领域事件契约
  与错误分类、值对象不变式
- **子代理**：K1=controllers；K2=domain

---

## 执行编排（并行安全分组）

```
第 1 轮（P0）: A1 A2 A3 + B1 B2 + C1 C2 C3   （9 个子代理并行，文件集互不相交）
第 2 轮（P1）: D1 D2 + E1a E1b + F1 F2
第 3 轮（P2）: G1 G2 + H1 H2 + I1 I2 + J1 J2 + K1 K2
每轮结束:     修复子代理（按 bug 清单）+ 审计子代理复核
```

## 产出物

1. 每模块 `docs/reports/module-<name>-bugs-2026-08-10.md`：bug 清单（文件:行号、
   严重度、复现、修复建议）
2. 汇总索引 `docs/plans/bug-hunting-2026-08-10.md`（本文件）进度勾选
3. 修复后统一验证：ruff + 定向 pytest + 回归

## 门禁

- 每轮 bug 清单须经第二子代理复核真实性（防误报/漏报）
- 修复不得改变公共 API；不得引入未讨论的方案
- 既有 160+ 相关测试保持全绿

---

## 进度：第 1 轮（P0）已完成 2026-08-10

8 个只读探索代理并行排 Bug，产出 8 份清单（docs/reports/module-*.md），**共约 177 项**（高 15 / 中 41 / 低 121 估）。

| 模块 | 清单 | 高 | 关键发现（摘） |
|------|------|----|----------------|
| LAN 核心 | module-lan-core.md | 2 | auth fail-open（DB 异常放行全部请求）、启动期同款 fail-open、seller 登录无严格限流、token 进日志/Referer、注销不撤销令牌 |
| LAN 路由 | module-lan-routes.md | 4 | thumbnails/shares 内联 SVG 无 nosniff（XSS）、模糊图失败回退原图（隐私绕过）、ZIP 符号链接泄露库外文件、batch 缩略图无限制 DoS |
| LAN 工具链 | module-lan-tools.md | 1 | cloudflared 下载无校验/无超时/残留损坏 exe、隧道崩溃无监控、start 竞态误杀、WS 广播超时/序列化无防护、DTO KeyError→500 |
| 文件操作/撤销 | module-file-ops.md | 4 | move 静默覆盖已存在目标、delete 投影异常致撤销备份整体丢失、unique_destination 只读目录死循环、撤销删除不恢复标签/元数据 |
| 导出/维护 | module-maintenance.md | 3 | 512MB DB 备份硬上限、备份目标静默覆盖、`_exists` 断连误判 MISSING 批量删元数据 |
| core 数据库 | module-core-db.md | 1 | migrate_path_metadata LIKE 大小写不敏感 DELETE 与 remap 大小写敏感冲突致整子树数据删除 |
| core 存储 | module-core-store.md | 0 | settings/JsonStore 无锁与损坏文件不修复、LRU None 误判、TagLibrary 同义词冲突/无锁、ProjectData mtime 缓存过期 |
| runtime/事件 | module-runtime.md | 1 | 双实例启动冲突阻断库打开、损坏 marker 阻断库打开、崩溃日志明文泄露、tool_scheduler args 类型无校验 |

**修复编排建议（下一轮）**：按严重度先修 15 项高（3 组并行：LAN 安全组 / 文件数据安全组 / 可用性组），随后中危批量。每项修复前经第二子代理复核真实性。

---

## 进度：高危修复轮已完成 2026-08-10

3 个修复子代理并行（文件集互不相交），15 项高危全部修复 + 4 项顺带安全项（runtime 中项：损坏 marker/崩溃脱敏等），2 项预期行为测试随契约更新。

### 组 A · LAN 安全（6 高）✅
- server.py `_has_active_users` DB 异常 fail-closed（拒绝而非放行）
- manager.py `_configured_auth_status` 异常按 auth_mode 安全默认，不静默降级无认证
- thumbnails.py 排除 .svg + 全局 nosniff；blur 失败返回 500 不再回落原图
- shares.py 公开预览排除 .svg + nosniff
- _helpers.py ZIP 打包拒绝 symlink/越界 resolved 路径

### 组 B · 文件数据安全（8 高）✅
- move/rename 目标已存在禁止覆盖（lexists 检查）
- 删除投影清理异常降级 warning，撤销备份不再被误弃
- **撤销删除恢复投影快照**（tags/meta/favorites 随备份 JSON 保存，restore 写回，含 remap）
- unique_destination 仅 FileExistsError 重试 + 1000 次上限（只读目录不死循环）
- 备份 512MB 硬上限移除（大库 quick_check 标记 skipped）
- 备份目标已存在拒绝静默覆盖
- integrity `_exists` 父目录不可达时判 UNKNOWN 不删元数据
- migrate_path_metadata DELETE 与 remap 统一精确匹配（不再误删整子树）

### 组 C · 可用性（2 高 + 2 中顺带）✅
- tunnel 下载超时 + 临时名 + `--version` 冒烟校验 + 原子替换
- reconciliation 双实例 generation 冲突降级 warning 不再阻断库打开
- 损坏 legacy marker 迁移降级为空队列不阻断打开
- crash_handler 崩溃日志敏感信息脱敏（token/密钥/Bearer）

### 验证
- ruff 全绿；定向测试 **370 passed, 2 skipped**（skips 为 Windows 环境性）；LAN 全量 513 + 桌面核心 547 通过
- 2 个测试随新契约更新（512MB 上限 → 大库跳过 quick_check 断言）

### 剩余（后续轮次）
中危 41 项 / 低危 121 项（P1/P2 轮）；file-ops 报告第 13 项（批量 move 部分成功撤销记录缺失，涉及 FileOperationResult 契约扩展）建议随中危轮处理。
