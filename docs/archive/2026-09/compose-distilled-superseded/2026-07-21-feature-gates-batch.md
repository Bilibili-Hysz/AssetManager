# 2026-07-21 功能/门禁子批:预览池/信息面板/WebUI 工作区/窗口退出(决策摘要)
> 状态:**历史蒸馏(已完结会话摘要)** · 2026-08-27 内容级合并自 compose-raw 原件,原件见 docs/archive/2026-08/compose-raw/ · 状态登记:2026-09-02(文档梳理轮补登)


> 摘要起草: 2026-08-27 · 源文件(19 份):`docs/compose/specs/2026-07-21-{layered-preview-pool-design,webui-workspace-redesign-design,weekly-stability-closure-design}.md` + `docs/compose/plans/2026-07-21-{filelist-scroll-boundary-redesign,gate-full-library-preview-pool,gate-home-react-migration,infopanel-grid-scroll-boundaries,infopanel-viewer-image-fit,lan-no-auth-login,layered-preview-pool,legacy-infopanel-project-preview,preview-gate-responsive-recovery,public-theme-setter,session-close-lan-websocket-regression,webui-dependency-security-upgrade,webui-desktop-dataflow-audit,weekly-stability-closure,window-exit-stop-failure-teardown,window-stop-failure-close-session-regression}.md` · 原件归档: `docs/archive/2026-08/compose-raw/`

## 背景

- 本批是与 07-21 架构重定标并行的功能/门禁子批:预览池与 Gate 首页、滚动与 InfoPanel 预览、WebUI 工作区、会话关闭与窗口退出容错、依赖安全与数据流审计。大量 plan 是"验证先于修改"的门禁型任务(纯回归证明通过时只加测试不改产品)。

## 决策要点(按主题;决策 | 出处)

### 预览池与门禁
- 缓存即数据源:预览仅复用 `directory_cache.preview_path`(按 mtime/存在性/根包含校验),不新增扫描管道/图片仓库/新 API | layered-preview-pool-design [S2]
- `/api/thumbnails/{path}` 保持唯一浏览器图片通道 | [S2/S6]
- `/api/home` 项目项可选 `thumbnail_url`,新增 `preview_pool` 字段;recent 20 条上限 | gate-full-library-preview-pool
- Gate 洗牌一次化(Fisher-Yates,主题切换/微调不重排);失败候选降级 lucide 图标,不阻塞导航 | layered-preview-pool
- 共享 `LayeredPreview` 组件(grid/list 尺寸、alt、无自交互);目录缩略图经 `thumbnailMap[path]` | [S4/S5]
- Gate 迁移边界:保留 `/`、cookie 认证、`/login`、`/browse`;删 `/api/config`、`/api/images` 原型 | gate-home-react-migration
- 动效生命周期:图像墙 ≤72 节点、20s 轮转待预载成功、reduced-motion/document hidden 暂停并清理 | [S3]
- `useTheme()` 追加公开 `setTheme`;Gate 特效节点在 body 需内联 `--gate-effect-color` | public-theme-setter / preview-gate [S2]

### 信息面板与滚动
- InfoPanel 预览与列表 `thumbnail_url` 解耦:按 path 推导 `/api/thumbnails/<path>?size=512`,显式 loading/ready/error | infopanel-grid-scroll-boundaries / preview-gate [S1]
- 预览适配不裁剪:object-contain;缩放 25%-500% 相对 fit;Reset/双击/切图回归 fit | infopanel-viewer-image-fit
- 项目预览:`/api/projects/{path}` ProjectDetail + 封面/图片;旧请求 abort+代际守卫 | legacy-infopanel-project-preview
- 滚动边界:header 固定、唯一滚动区 file-list-canvas;ProjectGrid `grid-cols-[repeat(auto-fill,minmax(168px,1fr))]` | filelist-scroll-boundary / infopanel [S2]
- 面板状态恢复:移动断点快照 sidebar/infoOpen,回桌面恢复 | preview-gate [S3]

### WebUI 工作区
- `/` Gate foyer + `/browse` 三栏工作区两段式旅程;BrowsePage 只协调,Sidebar 独占 expandedPaths,API 模块唯一 fetch 边界 | webui-workspace-redesign-design [S2/S4/S5]
- 恢复交互集:批量 ZIP(确定/不确定进度)、标签过滤芯片、权限徽标、分享复制、查看器手势、移动底栏、快捷键 `/`/Esc/`g`/`s` | [S4/S5]
- 硬标准:375px 无横向溢出、焦点恢复、reduced-motion 只禁动效 | [S6]

### 会话关闭与窗口退出
- 关闭全链路不变式:close_session → mark_closing → Runtime.close → LAN stop → realtime/WS 关 → 会话/DB 关;测试用真实 TCP/WS | session-close-lan-websocket-regression
- `shutdown_resources()` 全面 try、只记首个普通 Exception 最后重抛;closeEvent 嵌套 finally 保证 Qt close 与 LibraryService.close 无论如何执行 | window-exit-stop-failure-teardown
- `switch_library()` 捕获首个 stop 异常→排空→关旧会话→重抛→拒开替换库 | window-stop-failure-close-session-regression
- LAN no-auth 显式化:`lan_auth_mode="none"` 禁用活动用户准入,info 报 auth_enabled=False;缺省保持旧行为 | lan-no-auth-login

### 依赖安全
- 严格作用域升级:仅 react-router-dom 7.18.2/vite 7.3.6/vitest 3.2.6/@vitejs/plugin-react 5.2.0(--save-exact);不升 React 18/Tailwind 3/TS;禁 `npm audit fix --force` | webui-dependency-security-upgrade
- webui-desktop-dataflow-audit:只读,发现带严重级/根因/file:line 证据,输出 P0-P3 序列到 reports | webui-desktop-dataflow-audit

## 落地状态(2026-08-27 抽查)

- WebUI:`LayeredPreview.tsx` 存在并被 ProjectCard/ProjectList/LandingPage 引用;`BrowsePage.tsx` 含 browse-workspace/file-list-header/file-list-canvas 结构;`ProjectGrid` 用 auto-fill 168px;InfoPanel 项目预览 + thumbnailUrlFor(path,512/2048);useTheme 返回 {theme,setTheme,toggleTheme};依赖版本与基线一致。
- 后端:project_service 含 `preview_pool`(集成测试覆盖);lan/server、__init__、manager 含 auth_mode 接线;`tests/lan/test_lan_api.py` 有 `test_explicit_none_auth_mode_ignores_active_users`。
- 窗口/生命周期:`window_lifecycle_coordinator.py` switch_library(L118)/shutdown_resources(L276,first_error);window.py closeEvent 嵌套执行;`tests/integration/test_window_lifecycle_lan_failure.py` 两条真实 LAN stop 失败回归。
- 报告产物:compose/reports 下存在 stability-baseline/gate-home-react-migration/webui-dependency-security-upgrade/webui-desktop-dataflow-audit。

## 仍生效的约束或未决项

- 全部"不允许"清单:不提交无关脏文件、禁 audit fix --force、不复制 legacy static/app.js、不伪造客户端权限/分享、不加浏览器可读令牌、WS 不用 query 凭据。
- 周闭包前全绿命令集(riff→pyright→compileall→pytest 与 npm ci/typecheck/test/build);被阻塞命令不得声称可发布。
- 未决:weekly 闭包的后续日期报告(07-23/24/26/27)未在 reports 发现,最终发布结论待补验;plan checkbox 大多未勾选(实现归属后续批次,仅以现状为准)。