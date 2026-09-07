# W2 · 同版本整合回归 — 阶段汇总（2026-09-07，提前执行）

> 状态：**STAGE RESULT（一周计划 W2，提前于 9/7 执行）**
> 版本绑定：隔离 worktree @ `cf279a7`（= 主树 HEAD，工作树清零后建树，候选源码同版本）；JUnit：`artifacts/python.xml`（worktree 内）。

## 1. Python 全量回归（隔离 worktree，xdist loadgroup）

**5062 passed / 2 failed / 20 skipped**（2:41）

| 失败 | 分类 | 证据与定性 |
|---|---|---|
| `test_collection_service_publishes_collection_changed` | **历史问题（已登记家族）+ 产品观察项** | clean-transaction 守卫拒绝。双环境双模式：隔离 worktree 串行 3/3 红；主树先绿后红（1/2）——**非确定性、依赖事件发布路径的隐式提交时序**（RecordingBus 替身抑制订阅方提交的分支实测）。W3 已登记 EventBus 家族；本轮回填两个复现点。**产品观察项**：守卫（B03 新增）拒绝时调用方收到 RuntimeError 而非等待/重试——归并行线评估是否改等待语义。最短复现：`pytest tests/integration/test_collection_service.py::test_collection_service_publishes_collection_changed`（隔离 worktree） |
| `test_spa_assets_are_public_when_server_auth_is_enabled` | **缺失依赖（worktree 无 dist）** | 协程内裸 `next()` 在 SPA 资产清单为空时抛 StopIteration——隔离 worktree 无 `webui/dist`（gitignored 不入树）。主树（有 dist）同用例通过。非产品回归；处置：worktree 跑 lan 测试前构建 dist，或该用例加 dist 存在性跳过标记（登记给并行线选择） |

skip 20 = Windows 符号链接权限（WinError 1314，既知）+ 平台条件，全部有理由标注。

## 2. WebUI（主树 webui/，node_modules 复用）

- vitest：**89 文件 / 671 tests 全过**（较昨日 +2 文件/+6 测试，并行线新增）
- typecheck：exit 0
- production build：✓ 34.6s（dist 新鲜，index-CFFjZpIA.js）
- TS 契约：`gen_ts_types --check` → contracts.ts up to date（零漂移）

## 3. 浏览器 e2e（真实 Chromium + 代理 + 合成库）

- `test_webui_realtime_acceptance.py`：**全过** ✅——W2 目标"WebUI 实时同步证据"达成
- `test_webui_thumbnail_privacy_acceptance.py`：**2/3 确定性失败（待查-候选回归）**
  - `namespace_and_private_thumbnail_headers` + `intermediary_only_caches_explicit_public_thumbnail_responses`
  - 现象：`sessionStorage` 中 `lan_thumb_cache:` 键数为 0（缓存从未写入）——页面渲染正常（browse-workspace 可见）
  - 写入端 `useThumbnailCache.ts` 未被近期批次触碰；交界方：B03 前端批次（useProjects+72/useQuickLook+95/RealtimeContext ±1）× 并行线缩略图后端批次（thumbnail_service/routes/file_snapshot）× 测试环境
  - 最短复现：`pytest tests/e2e/test_webui_thumbnail_privacy_acceptance.py -m e2e`（需 dist）
  - **隐私敏感性**：`*_private_thumbnail_headers` 用例同红——无法确认私有缩略图响应头行为，**登记为隐私候选回归，归缩略图管线所有者（并行线）优先二分**（front 停用 useThumbnailCache 版本 × 后端批次二分）
  - 分类：**待查**（尚未归因，不计通过）

## 4. 静态检查（同版本）

pyright 0 errors；boundaries/routes/frontend-fetch/TS-contract 四检查全过；CI 同款 ruff 全绿；check_doc_stats/documents 绿（README 351 同步）。

## 5. 失败汇总对照（计划 §4 W2 验收）

| 计划要求 | 结果 |
|---|---|
| 关键模块与浏览器用例 0 failure | ⚠️ 部分：Python 关键模块 0（2 失败均定性非回归）；浏览器 realtime 全过；privacy 2 失败**待查登记** |
| 完整测试结果可解释 | ✅ 本节分类表 |
| 生成类型与实际 API 字段一致 | ✅ |
| JUnit 与源码绑定 | ✅ junit 于 worktree artifacts/，HEAD cf279a7 |
| 不合并重复集合通过数 | ✅（计数分组呈现） |

## 6. 对 W3/W4 的影响

- W3（启动/切库/关窗）：**无阻断**——PF-1 已修（本 worktree 全量回归 5062 passed 亦为修复的回归证明）
- W4（备份恢复）：**无阻断**——collection flake 为测试设施家族，不涉备份恢复路径
- privacy e2e 待查：建议与并行线协调后二分（前端停用版 × 后端批次），不阻塞 W3/W4

无证据即 unverified——本文档自身也是这个纪律的适用对象。
