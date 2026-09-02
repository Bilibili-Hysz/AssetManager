# 2026-08-03~04 会话交接摘要(webui-session-02 / desktop-ui-session-03 / mainline-session-04)
> 状态:**历史蒸馏(已完结会话摘要)** · 2026-08-27 内容级合并自 compose-raw 原件,原件见 docs/archive/2026-08/compose-raw/ · 状态登记:2026-09-02(文档梳理轮补登)


> 摘要起草: 2026-08-27 · 源文件(19 份):`docs/compose/handoffs/webui-session-02-2026-08-03/`(11)、`docs/compose/handoffs/desktop-ui-session-03-2026-08-04/`(6)、`docs/compose/handoffs/assetsmanager-mainline-session-04-2026-08-04/`(2) · 原件归档: `docs/archive/2026-08/compose-raw/`

## 各会话定位与交接内容

- **webui-session-02(08-03,11 份)**:WebUI 前端主线。基线 de64492/上一轮 b9dca9d;React 18.3.1 / Router 7.18.2 / Vite 7.3.6 / TS 5.6.3 / Vitest 3.2.6;37 files/292 tests、typecheck、build(1632 modules)通过。已交付 App 骨架 + Auth/Realtime/Toast/Download Provider,路由 /、/login、/browse、/detail、/s/:shareId;RealtimeContext 按 domain 失效,WS 只是提示、权威靠 HTTP refetch。任务队列 W0-W2:保持 G6-5 blocker 可见、冻结 API 契约矩阵、补前端直接证据(ShareReceivePage 测试、8 个 API 工厂契约文件、ContextMenu/Modal/ResizablePanel 等)。08-04 收口:46/343 → 52/388 → 55/404 → 57/423,+16 Playwright(静态产物)。09/10 文把 DeepSeek Docs 视觉原则与 G5 缺口/Storefront 路线映射到 React/Vite。
- **desktop-ui-session-03(08-04,6 份)**:给第二会话的受限 Qt 纯表现层任务包(视觉统一、原生控件样式、对话框外观、空/错/加载态、截图回归、G6-1 备份/恢复入口 UI 壳);主会话保留 Runtime/DB/锁/路径安全、FileList 模型与性能、跨端契约。G6-5/G6-1 基础切片已提交但产品层未闭合;主会话提供 Qt-free LibrarySettingsAdapter 注入 SettingsDialog。禁改清单明确(application/core/window.py/file_list 内部/share 绑定);D1-D4 任务 + 7 项最低证据 + targeted gate + 截图环境规则。
- **assetsmanager-mainline-session-04(08-04,2 份)**:主线继续,非发布声明。HEAD 51e50203;约 1067 条未跟踪(约 942 条为历史测试遗留 tmp/,**禁止全量 git clean**);保护域 webui/**、application/**、core/**、lan/**、file_list/**。用户要求"先收口 AssetsManager、暂缓 WebUI 显示优化"。唯一优先级 R1:G6-1 restore 的 root/session ownership 与 rollback failure 合同(限 library_service.py/library_export_service.py/bootstrap.py+测试),7 条硬要求(fail-closed、root-aware reservation 串行化、coordinator 缺失 fail-closed、staging/隔离/回滚失败不可静默、追加 race/quarantine/rollback 测试、恢复包上限)。

## 各会话遗留的未决项

- **webui-session-02**:G6-5 数据删除竞态/线程启动回滚/缩略图 key 对抗测试仍 blocker;真实 Desktop→LAN→第二浏览器旅程门禁未建;G5-1 编辑/G5-2 上传/G5-4 虚拟滚动/G5-7 统一错误页未闭合;路径双重解码(% 文件名)风险未修;/api/tunnel/status 文档-代码差异待修。
- **desktop-ui-session-03**:G6-1 产品入口(设置页、确认、进度、错误反馈、恢复后 Runtime 重建、隔离区管理)未完成;截图矩阵未全覆盖;D1-D4 待执行;真实图片 IO/reset 最小化/发布机性能门禁未闭合。
- **mainline-session-04**:R1 尚未实现(下一轮唯一优先级);G6 整体不能宣布完成;1067 条未跟踪状态未清理;Desktop UI 阶段实现未单独提交。

## 已知工程限制

- 外置 Git 元数据绝对路径硬编码(`C:\Users\86177\.codex\...git-metadata-...`),跨机失效。
- npm test 在 ~/#/% 路径下必须走 `scripts/run-vitest.mjs`(subst 盘符),直接 npx vitest 报 Cannot find module '/@vite/env'。
- pytest 临时目录须放仓库外(避免 ACL 失败误判产品失败)。
- jsdom/Vitest 不能证明真实 CSS 布局/pointer capture/下载/WS 握手/图片解码;Playwright 16 条仅覆盖静态构建产物。
- 旧测试计数不可跨报告复用,必须带命令与日期。
- 前端 capability 只是 UX gate,服务端路由仍需独立鉴权;WS 不带 query token;token 不进 localStorage/URL/React state。