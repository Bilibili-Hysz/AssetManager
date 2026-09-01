# 2026-07-15 批:投递安全/文件操作一致/LAN-WebUI 可靠性/作用域服务(决策摘要)

> 摘要起草: 2026-08-27 · 源文件: `docs/compose/specs/2026-07-15-{batch-a-delivery-safety,batch-b-file-operation-consistency,batch-d-scoped-library-services,lan-webui-reliability}-design.md` + `docs/compose/plans/2026-07-15-{anchor-worktree,batch-a-delivery-safety,batch-b-file-operation-consistency,batch-c-lan-webui-reliability,batch-d-scoped-library-services,lan-webui-reliability}.md` · 原件归档: `docs/archive/2026-08/compose-raw/` · 落地报告: `docs/archive/2026-09/compose-reports/{batch-a-delivery-safety,batch-b-file-operation-consistency,batch-c-lan-webui-reliability,batch-d-scoped-library-services}.md`

## 背景

- 07-15 四大批(投递安全 / 文件操作一致性 / LAN-WebUI 可靠性 / 作用域服务)+ anchor worktree 纪律,构成 Phase 2 的"可连续验证 + 生命周期隔离"主线;batch-b 计划已全部勾选完成,batch-a/c/d 落地报告存在于 compose/reports。

## 决策要点(决策 | 出处)

1. **anchor worktree 纪律**:把已审计工作树固化为可复现 Git 锚点(基线提交 + tag),不删源码与本地产物;`.gitignore` 只扩可复现依赖/生成物/本地工具/Cython 中间产物/cloudflared 二进制;`webui/dist/` 忽略规则保留(Vite 由源码再生) | anchor-worktree 全局约束
2. **Batch A 投递安全**:CI 增加 WebUI lockfile 安装/typecheck/build + Windows 打包冒烟(验 exe/SPA 入口与 assets/翻译/主题/插件/RuntimeData);Vite `/assets/*` 公开(登录页/分享壳引导依赖);浏览器会话凭据=HttpOnly `lan_token` cookie,密码分享用独立作用域 HttpOnly cookie;响应体不给 token(Bearer 仅显式 API client 保留) | batch-a-design [S3-S5]
3. **Batch A 库切换生命周期**:切库=停 LAN → 使缩略图运行时失效 → 关旧会话 → 开新会话;缩略图工作捕获不可变 generation,陈旧完成/缓存/仓库写入一律拒绝 | [S6]
4. **Batch B 文件操作一致性**:`FileOperationService` 是唯一桌面变异边界(绑定 active library root;无作用域服务即拒绝);文件系统变异成功后按序更新 metadata/thumbnails/asset-index 投影再发事件;删除清路径/子树投影;移动/复制对账后代 | batch-b-design [S3-S5]
5. **Batch B Undo 语义**:undo/redo 经操作服务执行、成功后移动历史条目;permanent-delete 备份按实际删除路径提交;trash 不可逆;网格重命名经意图委托;带作用域:库内拖放=移动、外部拖放=复制 | [S5-S6]
6. **Batch C LAN-WebUI 可靠性**:`webui/dist/index.html` 存在即活性页面壳,`lan/static` 仅为回退;先修服务器/公开资源边界,再对齐 share/download 传输与后端响应类型,再稳定 React effect/WS 清理,最后策略/无障碍/最小回退修复;share 密码 cookie 按 share 路径作用域、SameSite=Lax、TTL=分享令牌寿命、与 lan_token 独立;密码分享 info 无 cookie 时返回净化 200(仅密码/过期/预览状态),匹配 cookie 才返回完整公开分享 | lan-webui-reliability [S1-S3]
7. **Batch D 作用域服务**:`LibrarySession` 为新代码唯一公开打开库边界;`ApplicationBootstrap.for_library(session)` 是唯一作用域服务束工厂;MainWindow 在开/切库时注入一次 `set_scoped_services()` 到面板;变异动作无作用域即失败,禁止 `FileOperationService()`/`UndoService()` 无绑定回退;Undo 按库隔离(AB 两库并存互不串);`DatabaseManager.close_library(root)` 显式逐库 teardown,幂等、不关他库 | batch-d-design [S1-S5]

## 落地状态(2026-08-27 抽查)

- **Batch A:✅ 落地**:`webui/dist` 打包进 PyInstaller(`_internal/webui/dist`),`check_package_contents.py` 校验收紧;SPA assets 公开策略在 `lan/api.py`(/assets add_static);cookie-only 认证为现行模型;缩略图 generation 机制在 `panels/file_list/_loader.py`/`_thumbnail_delivery.py`。
- **Batch B:✅ 落地(计划全勾选)**:`FileOperationService` 会话绑定 + 投影修复/清理 + 事件发布顺序符合;undo 经操作服务;集成/桌面回归测试在 tests/integration、tests/desktop。
- **Batch C:✅ 落地**:share 作用域 cookie(`share_token` path=/api/shares/{id}、1h)按设计;`/assets` 公开;SPA-or-503(pages.py);错误契约迁移至 canonical envelope。
- **Batch D:✅ 落地并演进**:`bootstrap.runtime_for`(for_library 已被其后 recalibration 取代为 runtime_for)+ `set_scoped_services` 面板注入;会话租约/`_publish_while_live`/幂等 close 均在 context.py;逐库 teardown 由 `LibraryService.close_session` 编排。
- **anchor**:`mirror/*.bundle` 存在多个基线 bundle(08-13~15),本批承诺的"单基线提交+tag"被后续批次继续执行。

## 仍生效的约束或未决项

- "库切换先停 LAN→失效缩略图→关旧→开新"顺序仍是当前 lifecycle coordinator 的硬约定。
- 变异必须带作用域服务(无绑定回退为红线,由 check_boundaries/架构测试守护)。
- share cookie 作用域与 TTL、`/assets` 公开分类仍生效;browser 凭据不进 query/localStorage/sessionStorage。
- 未决:anchor 单基线 tag 未在 git 历史中显式出现(以 mirror bundle 形式留存)。