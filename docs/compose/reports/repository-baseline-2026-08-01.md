---
feature: repository-baseline-2026-08-01
status: delivered
as_of: 2026-08-01
branch: master
head_before_baseline: 945fd1e
baseline_commit: f7f9e14de6c644c60575ed28f16567b8b717133a
remote: none configured
---

# Repository Baseline — 2026-08-01

## 1. 结论

本报告是 2026-08-01 基线提交时的状态快照，负责把代码、测试、DeepSeek Docs、Compose 证据和 Git 工作树放到同一条时间线上。Desktop–LAN–WebUI recalibration 的 Tasks A–E 已交付；T151、T530、T533 的证据已闭合。桌面 UI 视觉 V1 的主要实现也已完成。性能路线已经有实现和 50,000 项本地遥测，但性能发布阈值尚未闭合。基线之后的增量代码与路线状态见 [`repository-followup-review-2026-08-01.md`](repository-followup-review-2026-08-01.md)。

本轮基线整理不使用 reset、checkout、clean 或未知范围的删除。原工作树中的产品代码、测试和文档按目录核对后纳入基线；项目本地的 .codex/ 仅是 Codex 运行元数据，已加入 .gitignore，内容保留但不进入产品提交。

## 2. 基线前工作树盘点

在 master @ 945fd1e 上，基线前工作树包含：

| 类别 | 数量 | 说明 |
|---|---:|---|
| 已跟踪修改 | 122 | Runtime/session/LAN、Desktop UI、主题、FileList、WebUI、测试和 Compose 文档 |
| 未跟踪项目文件 | 61 | DeepSeek Docs、Task A–D 报告、UI 收口报告、图标/阴影实现、新测试与 WebUI auth 文件 |
| 未跟踪本地工具文件 | 6 | .codex/ agents/config；不纳入 Git，由 .gitignore 保留 |
| 总工作树路径 | 189 | 其中 6 个工具文件不属于产品基线 |

上一轮历史整理报告中的 198 路径是较早时间点快照，不代表本次基线前状态。

## 3. 已交付范围

### Desktop–LAN–WebUI

- Runtime/session/LAN 生命周期、adapter pre-close barrier、失败重试和 restart generation：Task A。
- HttpOnly Cookie 身份、受保护 principal/capabilities 投影、401/logout teardown：Task B。
- Share/user/invite/activity/presence producer-backed domain events 与 React projection refetch：Task C。
- ApplicationBootstrap.for_library()、cleanup_library() 等已证实兼容路径移除：Task D。
- Windows Chromium/desktop/LAN cross-surface matrix 与 Ubuntu WSL directory-symlink gate：Task E。

证据文件：

- docs/compose/reports/desktop-lan-webui-architecture-recalibration.md
- docs/compose/reports/desktop-lan-webui-architecture-migration.md
- docs/compose/reports/desktop-lan-webui-architecture-task-a.md
- docs/compose/reports/desktop-lan-webui-architecture-task-b.md
- docs/compose/reports/desktop-lan-webui-architecture-task-c.md
- docs/compose/reports/desktop-lan-webui-architecture-task-d.md
- docs/compose/reports/session-07d28cba9ffeR7yeBnz5N4prK7-final.md

### Desktop UI

Desktop UI-07 收口报告记录了 SVG 语义图标、按钮变体、字阶/缩放、主题对比度、阴影封装、FileList 卡片阵列和缩放动画、watcher 防抖及相关回归。视觉 V1 主要项已完成；全控件截图矩阵和全部对话框统一视觉仍是后续 P1。

## 4. 可复核验证

| 检查 | 结果 | 备注 |
|---|---|---|
| Python full suite | 1590 passed, 1 skipped | 使用 python -m pytest -q --basetemp C:\\tmp\\assetsmanager-baseline；Windows 目录符号链接 skip，Ubuntu WSL 已有独立 gate |
| WebUI full suite | 37 files / 289 tests passed | npm test |
| WebUI typecheck | passed | npm run typecheck |
| WebUI production build | passed | npm run build，1632 modules transformed |
| Ruff | passed | ruff check AssetsManager tests |
| Python compileall | passed | python -m compileall -q AssetsManager tests |
| pyright | 41 errors | 已知静态类型债务，不影响 pytest/Ruff/compileall，但不能标为全绿 |
| T151 | 209 passed | 既有 closeout evidence |
| T530 | 186 passed | 既有 Windows focused cross-surface evidence |
| T533 | 1 passed, 23 deselected | Ubuntu WSL symlink gate |
| Grid 50k trend | generated | artifacts/perf/grid/20260801T144222Z/，ignored local evidence |

50,000 synthetic/offscreen Grid 指标：cold grid.frame P50 6.436ms；scroll/zoom P50 3.713ms、P95 10.853ms；warm 场景 texture_build_count=0。该结果是本机趋势证据，fixture 为 empty text entries，不能替代真实图片 IO 和发布机验收。

## 5. DeepSeek 总路线状态（基线快照）

| 阶段 | 当前状态 | 下一步判断 |
|---|---|---|
| 阶段 0：可回滚基线 | ✅ 完成 | 本报告与基线提交作为后续入口 |
| 阶段 1：数据安全 | ⏳ 未开始 | 最高优先级，先做单实例锁、undo 残留、DB 自检和导出/防误删 |
| 阶段 2：性能 | 🟡 部分完成 | 继续目录大小治理、reset 最小化、真实图片 IO 验收 |
| 阶段 3：前后端分离 A+B | 🟡 部分完成 | recalibration 已交付，但应用层 URL/ThumbnailLoader 边界仍需清理 |
| 阶段 4：视觉 V1 | ✅ 主要项完成 | P1 原生控件覆盖和真实窗口截图矩阵 |
| 阶段 5：插件 API v2 | ⏳ 未开始 | 不提前实现权限/兼容层，先完成数据安全 |
| 阶段 6：P1 功能精选 | ⏳ 未开始/零散基础 | 以 ROI 清单逐项立项 |
| 阶段 7：契约化收尾 | ⏳ 未开始 | OpenAPI、桌面端口层、插件权限门禁 |

## 6. 基线时真实缺口

1. AssetsManager/core/database.py:302-315 的 clean_orphan_dirs() 仍直接 shutil.rmtree；AssetsManager/window.py:414 仍是调用点，需要改为可审计、可恢复的移走/回收策略。
2. 未发现 QLockFile 或其它单实例锁；双开拒绝门未实现。
3. AssetsManager/application/undo_service.py:49 创建 AssetsManager_undo_* 临时目录，正常 close 会清理，但启动时没有统一残留扫描。
4. 没有统一的启动 PRAGMA quick_check、数据库维护、自检、缺失文件修剪和缩略图孤儿清理流程。
5. 公网 Tunnel/guest 默认策略仍需要首次开启安全提示和强制认证门禁；当前 guest 可按设置 browse/preview。
6. Capabilities.upload 已出现在 public DTO，但没有对应 upload route 或 WebUI 上传闭环。
7. AssetsManager/application/project_service.py、search_service.py 仍生成 /api/... URL；阶段 3 A1 未完成。
8. AssetsManager/panels/file_list/_loader.py:185-231 仍直接持有 sqlite3/ThumbnailRepository；阶段 3 B2 未完成。
9. AssetsManager/lan/routes/_helpers.py:336-362 仍保留 deprecated query-string ?token=/?key= 兼容读取（WebSocket 已禁用该路径）。
10. pyright 目前报告 41 个错误，主要集中在 DTO/principal 的 object narrowing、LAN 生命周期可选状态和 FileList 模型类型。

## 7. 文档与任务入口

- 当前任务入口：DeepSeek Docs/施行路线图.md。
- 当前事实入口：本报告。
- 基线之后的增量事实入口：[`repository-followup-review-2026-08-01.md`](repository-followup-review-2026-08-01.md)。
- 架构交付证据：docs/compose/reports/desktop-lan-webui-architecture-recalibration.md。
- UI 交付证据：docs/compose/reports/desktop-ui-visual-closure-2026-08-01.md。
- 性能计划：DeepSeek Docs/未来方向/07-桌面端性能优化计划.md。
- 数据安全缺口：DeepSeek Docs/功能缺口分析/06-安全与可靠性.md。

历史计划中的 checkbox 不等于当前待办；任何下一项都必须先更新路线图或创建独立计划，并在完成后补充验证证据。

## 8. Git 交接

当前 checkout 没有 configured remote；之前的 push 失败是 fatal: No configured push destination. 本基线只在本地建立，可回滚但尚未推送。.codex/ 内容被保留并忽略，RuntimeData/、artifacts/、缓存和构建产物均按 .gitignore 保留在本地但不属于提交。
