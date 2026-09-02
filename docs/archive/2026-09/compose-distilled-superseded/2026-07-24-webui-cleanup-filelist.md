# 2026-07-24 批:WebUI 遗留清理与文件列表项目交互(决策摘要)
> 状态:**历史蒸馏(已完结会话摘要)** · 2026-08-27 内容级合并自 compose-raw 原件,原件见 docs/archive/2026-08/compose-raw/ · 状态登记:2026-09-02(文档梳理轮补登)


> 摘要起草: 2026-08-27 · 源文件(6 份):`docs/compose/specs/2026-07-24-{filelist-project-interaction-design,webui-legacy-cleanup-design}.md` + `docs/compose/plans/2026-07-24-{filelist-project-interaction,gate-workspace-preview-responsive-fix,theme-infopanel-preview,webui-legacy-cleanup}.md` · 原件归档: `docs/archive/2026-08/compose-raw/`

## 背景

- 07-24 收口两条交互线:Filelist 项目交互语义(桌面单击/双击、is_project 契约)与 WebUI 旧前端清理(删除 lan/static 多页,SPA 唯一入口)。方法:每 plan 声明 REQUIRED SUB-SKILL、checkbox TDD、尾部统一质量门。

## 决策要点(决策 | 出处)

1. **is_project 由后端权威计算**:`/api/files` 目录项暴露 is_project(sidebar_depth_cfg/ProjectDepthConfig);前端禁止按路径深度/文件夹名推断 | filelist spec [S4/S9]
2. **桌面交互矩阵**:单击=选择+InfoPanel(不导航);双击=进入普通目录;项目目录双击=复用 `/detail?path=` 独立页;移动端保留单击直航;批量选择显式模式 | [S2/S5/S10]
3. **键盘**:Enter 触发双击同主动作;Space 选择;保留可见焦点环 | [S5/S8]
4. **Back 语义**:回到进入详情前的精确 `/browse?path=...` URL(含筛选);不建第二详情页 | [S7/S10]
5. **删除 legaay WebUI**:删 `AssetsManager/lan/static/` 全部旧页面 + 静默回退 | webui-legacy-cleanup spec [S5]
6. **SPA-or-503**:页面路由只服务 `webui/dist/index.html`,缺失返回 503 + 构建提示 | [S4]
7. **公开路由分类**:`/static/*` 移出公开与限流跳过列表,`/assets` 保持公开;API/ws/下载/分享协议不变 | [S4/S7]
8. **源码分层保留**:pages/components/api/hooks/stores/types 不做 feature-first 大迁移 | [S3/S9]
9. **测试与打包契约**:测试迁 SPA-or-503 契约;打包检查 `_internal/webui/dist/index.html+assets`;.gitignore 增 `/webui/dist/`、`/webui/.vite/` | [S6]
10. **杂项修复**:Gate 指针光效恢复;thumbnailUrlFor 按段 encode 保留 `/`;工作区开关移 Breadcrumb 行;768px 自动关面板持久化;useTheme 统一外部 store(am_theme 唯一,含旧 key 迁移);Gate 背景设置与主题偏好分离;InfoPanel 预览=button+ImageViewer(高清源 size=2048,不开未鉴权原图端点);图片判定扩到 .bmp/.tiff/.ico/.svg;统一 .asset-preview-surface | 各 plan

## 落地状态(2026-08-27 抽查)

- `webui/dist/index.html` + dist/assets(55 文件)存在;`lan/static/` 已不存在;`lan/routes/pages.py` 含 SPA_DIR/503;`lan/api.py` 仅剩 `/assets` add_static。
- `asset_service.py`/`files.py`/`types/api.ts` 均有 is_project;`BrowsePage.tsx` 含 handleItemOpen/is_project/isMobile(25 处命中)。
- `useTheme.ts` 含 am_theme 与 gate-theme 迁移;`LandingPage.tsx` 含 gate-cursor-glow;`InfoPanel.tsx` 含 asset-preview-surface / size=2048 / ImageViewer。

## 仍生效的约束或未决项

- LAN 启动前必须构建 webui/dist,否则 503(设计意图)。
- is_project 只能来自后端;桌面双击约定仅限桌面,移动语义不变。
- 未决:全页面视觉 parity 与真实浏览器/移动验收未闭合;G6-5 数据库完整性 blocker 未收口;文件名含字面 % 的 aiohttp {path:.*} 双重解码风险未修复(08-03 交接仍记)。