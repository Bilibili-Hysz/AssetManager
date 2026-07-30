# WebUI Legacy Cleanup and Structure Design

## [S1] Objective

整理 AssetsManager 中的新 React/Vite WebUI 与旧 LAN 多页面 WebUI 的并存遗留，建立单一 WebUI 运行入口和清晰的渐进式源码边界。

本轮目标：

- 移除 `AssetsManager/lan/static/` 旧 HTML/JS/CSS/i18n 页面及其回退逻辑。
- 让 LAN 页面路由统一服务 `webui/dist/index.html`。
- 当 React 构建产物不存在时返回明确的 503，而不是静默切换到旧产品。
- 清理 WebUI 生成物和本地依赖的 Git 管理边界。
- 保留现有 `pages / components / api / hooks / stores / types` 源码分层，不进行 feature-first 大迁移。
- 保留 API、WebSocket、缩略图、下载、分享和认证业务契约。

## [S2] Current State and Problem

仓库当前存在两套页面资产：

1. `webui/`：React 18 + Vite + TypeScript 的新 SPA，构建输出为 `webui/dist/`。
2. `AssetsManager/lan/static/`：旧版多页面 HTML/JS/CSS，包含 `index.html`、`detail.html`、`login.html`、`share.html` 及对应脚本。

`AssetsManager/lan/routes/pages.py` 和 `shares.py` 在 SPA 构建不存在时回退到旧页面，`AssetsManager/lan/api.py` 还暴露 `/static/*`。这使“页面是否可用”依赖两套产品，旧页面和新页面的行为、测试与资源边界容易继续分叉。

`webui/dist/`、`webui/node_modules/` 和 `webui/tsconfig.tsbuildinfo` 是本地构建/依赖产物，不应成为源码结构的一部分；其中 `dist/` 是否被打包由构建/发布流程生成，而不是提交源代码。

## [S3] Target Source Structure

保留并明确现有渐进式职责边界：

```text
webui/
├── src/
│   ├── api/           # API client 与领域 API 模块
│   ├── components/
│   │   ├── admin/     # 管理面板专属组件
│   │   ├── files/     # Filelist、项目卡片、工具栏、预览
│   │   ├── layout/    # 工作区布局、Sidebar、InfoPanel、Header
│   │   ├── shares/    # 分享操作组件
│   │   ├── tags/      # 标签展示组件
│   │   ├── ui/        # 无业务归属的通用控件
│   │   └── viewer/    # 图片查看器
│   ├── hooks/         # 可复用 React hooks
│   ├── i18n/          # 前端翻译资源与 hook 支持
│   ├── pages/         # 路由级页面
│   ├── stores/        # React context / 全局状态
│   ├── types/         # 前端 API 与领域类型
│   ├── App.tsx
│   ├── main.tsx
│   └── index.css
├── index.html
├── package.json
├── vite.config.ts
├── tailwind.config.ts
├── postcss.config.js
├── tsconfig.json
└── tsconfig.node.json
```

本轮不移动已经符合上述边界的源文件；“整理结构”通过删除旧入口、明确构建目录、统一页面服务入口和补充文档/忽略规则完成。这样可避免只为改变路径而产生大规模 import 噪声。

## [S4] Runtime Contract

当 `webui/dist/index.html` 存在时：

- `/`、`/browse`、`/detail`、`/login` 和 `/s/{shareId}` 返回同一 React SPA index。
- `/assets/*` 由 `webui/dist/assets/` 提供。
- `/api/*`、`/ws` 和下载/缩略图/分享 API 保持原有路由。

当 `webui/dist/index.html` 不存在时：

- 上述页面路由返回 HTTP 503。
- 响应明确说明需要先构建 WebUI，不尝试查找或服务旧 static 页面。
- `/assets/*` 未注册或返回 404；API 路由仍正常注册。

`/static/*` 旧路径被移除，不再作为页面、脚本、样式或 i18n 的公共入口。认证公开路径列表与安全中间件必须同步移除 `/static` 前缀；`/assets` 保持公开以支持 SPA 启动。

## [S5] Cleanup Scope

删除：

- `AssetsManager/lan/static/index.html`
- `AssetsManager/lan/static/detail.html`
- `AssetsManager/lan/static/login.html`
- `AssetsManager/lan/static/share.html`
- `AssetsManager/lan/static/app.js`
- `AssetsManager/lan/static/detail.js`
- `AssetsManager/lan/static/login.js`
- `AssetsManager/lan/static/share.js`
- `AssetsManager/lan/static/style.css`
- `AssetsManager/lan/static/detail.css`
- `AssetsManager/lan/static/icons.js`
- `AssetsManager/lan/static/i18n.js`
- `AssetsManager/lan/static/i18n/*.json`

不删除：

- `webui/src/**` 仍被入口、路由或测试使用的文件。
- `webui/index.html`、Vite/TypeScript/Tailwind/PostCSS 配置。
- 后端 API、WebSocket、缩略图、下载和分享服务实现。

本地生成物通过忽略规则保持不进入 Git：`webui/node_modules/`、`webui/dist/`、`webui/.vite/` 和 `webui/tsconfig.tsbuildinfo`。如果这些路径已经存在，只清理可验证为生成物的内容，不触碰 RuntimeData 或用户资产。

## [S6] Test Migration

测试必须从“旧 static 页面源码契约”迁移为“React SPA 单一入口契约”：

- 删除只验证旧 HTML/JS/CSS/i18n 内容的断言。
- 保留页面路由、SPA index、资产路由、API 路由和安全边界测试。
- 增加/更新构建产物缺失时 503 的测试。
- 增加 `/static/*` 不再服务旧文件的测试。
- 更新打包资源检查，使其要求 `webui/dist/index.html` 和 `webui/dist/assets`，不再把旧 static 作为页面运行依赖。
- 运行现有 WebUI Vitest、LAN pytest、类型检查和生产构建。

## [S7] Compatibility and Safety

- 只改变页面静态入口和旧回退行为，不改变 `/api`、`/ws`、Cookie 认证、下载、缩略图和分享数据协议。
- React Router 的客户端路径继续由同一个 `index.html` 接管。
- 旧 `/static` 链路被有意移除；不添加兼容重定向，避免继续保留第二套产品入口。
- 删除前必须以当前引用扫描和测试为证据；不得删除仍被 Python、测试或构建脚本使用的 React 源文件。
- 保留用户工作树中与本任务无关的未提交修改。

## [S8] Verification Contract

完成前必须通过：

- 旧 static 文件引用扫描只剩迁移说明或删除断言，不再有运行时 import/页面 fallback。
- LAN 相关 pytest 全部通过。
- WebUI Vitest 全部通过。
- `npm --prefix webui run typecheck` 通过。
- `npm --prefix webui run build` 通过。
- `git diff --check` 通过。
- 运行时审查确认：构建存在服务 SPA，构建缺失返回 503，`/assets` 公开，`/static` 不再暴露。

## [S9] Decision Trace

```json
[
  {
    "decision": "Remove the old static fallback instead of preserving it",
    "reason": "The user asked to organize legacy WebUI; keeping a silent fallback preserves two competing products and hides missing React builds.",
    "alternatives": ["Keep legacy fallback", "Move legacy files to a compatibility directory"],
    "tradeoff": "Unbuilt deployments now fail explicitly with 503 and must build the React app before serving pages."
  },
  {
    "decision": "Keep the existing React responsibility directories",
    "reason": "api, components, hooks, pages, stores, types already express stable boundaries; path-only migration would create noise without improving ownership.",
    "alternatives": ["Feature-first full migration", "Do not touch any source structure"],
    "tradeoff": "The result is a conservative cleanup rather than a full feature architecture rewrite."
  },
  {
    "decision": "Return 503 when the SPA build is missing",
    "reason": "A clear build error is safer and more diagnosable than serving stale HTML from a second frontend implementation.",
    "alternatives": ["Return 404", "Serve a minimal inline error page", "Keep old fallback"],
    "tradeoff": "Operators must recognize and fix the build prerequisite, while API routes remain available for diagnostics."
  }
]
```

## [S10] Anti-Slop Self-Check

The plan intentionally avoids broad React file moves and speculative abstractions. It removes the duplicate runtime entry, cleans generated artifacts, updates only affected tests/configuration, and leaves existing domain boundaries intact.
