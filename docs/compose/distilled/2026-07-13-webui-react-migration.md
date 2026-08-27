# 2026-07-13 批:WebUI React 迁移与 LAN 安全修复(决策摘要)

> 摘要起草: 2026-08-27 · 源文件: `docs/compose/specs/2026-07-13-webui-react-design.md`、`docs/compose/plans/2026-07-13-lan-security-fixes.md`、`docs/compose/plans/2026-07-13-localized-view-mode-stable-id.md`、`docs/compose/plans/2026-07-13-webui-react-plan.md` · 原件归档: `docs/archive/2026-08/compose-raw/`

## 背景

- 原 Web 前端是 `AssetsManager/lan/static/` 下的原生 JS 多页应用(MPA)。
- 本批两条主线:**(1)** 将 Web UI 重写为 `webui/` 下的 React SPA(设计规格 + 18 Task 实施计划);**(2)** 修复 LAN 授权、分享管理、ZIP 限额与安全设置,并把文件列表视图模式与翻译文本解耦(两份实施计划)。
- 本批属"07-21 recalibration 前"批次;LAN 修复另有最终报告 `docs/compose/reports/lan-security-fixes.md`。

## 决策要点(决策 | 出处)

1. **技术栈**:React 18 + TypeScript 5 + Vite 5 + React Router 6 + Tailwind CSS 3 + lucide-react;**明确不选** UI 组件库(shadcn/ui、Ant Design)、状态库(Zustand/Redux)与 React Query/SWR,以原生 fetch + Context + hooks 起步 | design [S2]
2. **项目形态**:新 SPA 置于 `webui/`;构建输出 `webui/dist/`,由后端 `setup_routes()` 注册静态路由;旧 `lan/static/` 的"保留回退"决策**已被后续批次推翻(目录已删)** | design [S1][S11]
3. **路由**:`/`(Landing)、`/browse?path=`、`/detail?path=`、`/login`、`/s/:shareId`,未匹配重定向 `/` | design [S4]、plan Task 4
4. **认证数据流**:启动 `fetch /api/info` 判 `auth_mode` → 免认证直进/进 Login;token 存 AuthContext + sessionStorage;401 清状态跳登录(**后被 cookie-only 模型取代**) | design [S7]、plan Task 2/3
5. **权限模型**(前端侧):admin 全量、user browse/download/preview、guest browse/preview;`AuthContext` 统一维护 | plan Task 3
6. **实时更新**:WS `/ws` 文件变更事件触发当前目录重载,断线退避重连(1s、2s、4s…上限 30s) | design [S7]、plan Task 17
7. **缩略图**:`POST /api/thumbnails/batch` 批量 + 前端 LRU 缓存(容量 200,sessionStorage) | design [S7]、plan Task 8
8. **功能边界**[S9]:核心套(浏览/认证/搜索/下载/详情/菜单/分享/查看器/i18n/响应式/骨架/主题/统计/WS)+ 管理套(用户/邀请码/分享/活动/在线用户)全实现
9. **视觉规范**[S10]:slate-900/slate-50 底、indigo-500 强调、圆角半透明卡片、Inter、transition-all duration-200、骨架脉冲
10. **实施顺序**:18 Task(脚手架→API→认证→路由基础页→i18n→通用 UI→布局→搜索浏览→标签→详情→分享→查看器→管理→响应式→主题→WS→后端集成) | plan Task 1-18
11. **前端工程约束**:全 TS 函数组件、仅 Tailwind utility、文本全走 i18n、API 统一 `client.ts`、类型集中 `types/api.ts`、PascalCase 组件/camelCase hook、认证豁免路径匹配 | plan 全局约束
12. **开发/生产对接**:Vite dev(5173)代理 `/api` `/ws` → 127.0.0.1:8080;生产由 `setup_routes()` 注册 `/assets` 静态 + `/` 返 index.html | plan Task 1/18
13. **LAN 修复范围纪律**:只修已审查问题、不重构 LAN;沿用 `get_user_permissions()`;行为变更必须带回归测试 | lan-security-fixes 全局约束
14. **路由级权限门**:`_helpers.py` 新增 `require_permission()`,在文件列表/下载/缩略图/分享入口调用 | Task 1
15. **ZIP 大小核算**:`_estimate_download_size()` 递归统计,超 `MAX_BATCH_DOWNLOAD_BYTES` 在创建临时 ZIP 前拒绝 | Task 2
16. **安全设置生效**:`lan_ip_whitelist` 传入 LanServer 并由 middleware 强制;安全设置变更检测差异后重启 | Task 3
17. **视图模式与翻译解耦**:QComboBox `addItem(tr(...), userData="Grid"/"Details")`,业务比对稳定 ID 不比对翻译文本 | localized-view-mode Task 1

## 落地状态(2026-08-27 抽查)

- **webui React 化:✅ 已落地(且超出原计划)**:`react ^18.3.1 / react-router-dom 7.18.2 / tailwind ^3.4.15 / vite 7.3.6`;`webui/dist/` 已构建;`lan/api.py` 注册 `/assets` SPA 静态路由;`lan/static` 已删除;功能扩展到 storefront/seller/gallery、RealtimeContext、queryCache 等(后续批次)。
- **LAN 权限门:✅ 已落地**:`require_permission` 在 `lan/routes/_helpers.py`,被 11 个路由文件使用;`downloads.py` 含 `_estimate_download_size` + `MAX_BATCH_DOWNLOAD_BYTES`(500MB)。
- **view mode 稳定 ID:✅ 已落地**:`panels/file_list/_base_layout.py` L147-148 `userData="Grid"/"Details"`,L329-330 `currentData() or currentText()`(计划书写的 `_base.py` 已拆分为 `_base_layout.py`)。
- 版本约束被取代:React Router 6/Vite 5 → 7.x。

## 仍生效的约束或未决项

- LAN 修复三约束仍有效:小范围修复、沿用角色/权限模型、变更带回归测试。
- 前端工程约束(仅 Tailwind、无 UI/状态库、i18n 全覆盖、统一 client.ts)现行仍可观察。
- 视图模式稳定 ID 约定("Grid"/"Details")仍生效。
- 未决:实施计划 Task 18 的 E2E 验证清单未勾选;验证结论以后续批次报告为准。