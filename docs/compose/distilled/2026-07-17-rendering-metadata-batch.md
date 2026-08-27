# 2026-07-17 批:渲染/元数据/主题稳定性 + 早期审计结论(决策摘要)

> 摘要起草: 2026-08-27 · 源文件: `docs/compose/plans/2026-07-17-{lan-first-image-linear-scan,metadata-combined-read,smooth-scroll-thumbnail-timing,theme-transition-stability,zoom-grid-relayout}.md` + `docs/compose/plans/{lan-error-audit,p1-audit-findings}.md`(2026-06-17 早期审计) · 原件归档: `docs/archive/2026-08/compose-raw/`

## 背景

- 5 份实现计划(性能/稳定性/渲染)+ 2 份早期审计(结论优先于设计,均判"已安全、无需修复");全部 TDD 式分步,带回归测试。

## 决策要点(决策 | 出处)

1. **LAN 首图单趟线性扫描**:`find_first_image()` 由"收集候选+排序"改为单趟 `os.scandir` 保留最优(不区分大小写最小文件名);空/无图/OSError→None;只认直接子文件且 ∈ IMAGE_EXTS;不改路由/鉴权/调用方 | lan-first-image-linear-scan
2. **metadata 合并读**:新增 `MetadataRepository.get_notes_and_urls()` 一次行内读 notes+urls;URL 解码/畸形→[]/非列表拒绝留在仓库层(共享 `_decode_urls`);`get_metadata()` 为 tag 1 次+合并读 1 次(=2 查询);`get_notes/get_urls` 独立行为不变 | metadata-combined-read
3. **平滑滚动推迟缩略图**:动画驱动(scrollbar by smooth-scroll)的更新不触发防抖,仅"最新动画完成"调度最终防抖(单调 generation);手动滚动保留 100ms 防抖;休眠 legacy QListView 路径不在范围 | smooth-scroll-thumbnail-timing
4. **主题过渡单所有者**:WindowCoordinator 独占窗口级过渡(单调 `_theme_generation`);每次先停活动动画恢复 opacity,仅当前 fade-out 回调可应用主题并启 fade-in;reduce_motion 无动画、同样 apply 路径并恢复 opacity 1.0 | theme-transition-stability
5. **缩放动画轻量重排**:`update_layout(*, relayout_only)` 只重算几何与滚动范围、不动 `_textures/_dirty`;zoom 帧走轻量路径;zoom 完成仍失效纹理+全量布局 | zoom-grid-relayout
6. **audit-LAN 错误响应**:Critical 0/Minor 0/Safe 62;无 str(exc)/traceback/repr 入客户端错误;"User not found" 与 "Invalid password" 为有意 UX 文案(附用户枚举风险注记);validate_path reason 只进状态行不进响应体 | lan-error-audit
7. **audit-P1 LAN DB 线程安全**:写路径全持连接级 `db_write_lock`;to_thread 内只读(WAL);connection_for 恒同连接并校验 root;LAN 不关连接(生命周期归主线程);结论=无需修复(4 条 minor 卫生观察) | p1-audit-findings

## 落地状态(2026-08-27 抽查)

- **渲染/缩放 ✅**:`_grid_widget_data.py:381` `update_layout(..., *, relayout_only)`;`:392-394` `keep_zoom_anchor = bool(self._zoom_source_rects) and not relayout_only`;`_base_events.py:263,279` zoom 帧;`_grid_widget_interact.py:60` 同步签名;后续 git 叠加 zoom 目标尺寸预渲染等(af5d0ca、36436ae)。
- **metadata 合并读 ✅**:`metadata_repository.py:272` `get_notes_and_urls`;`:322` `_decode_urls` 共享;`metadata_service.py:204-213` 走合并读。
- **thumbnail timing ✅**:`_base_events.py:139-146` 100ms 单次防抖 + `_scroll_animation_generation`;`_begin_smooth_scroll`(:410-424)动画驱动短路;`_finish_smooth_scroll`(:426-430)generation 校验后调度防抖。
- **主题 ✅**:`window_coordinator.py:65` `_theme_generation`、`:103 on_theme_refresh()`、`:148` 过期拦截;`window.py:650-651` 委托。
- **LAN 首图 ✅**:`lan/routes/_helpers.py:465-469` 确为 os.scandir 单趟、无 sorted。
- 两份审计结论未见推翻(LAN 错误契约后迁移至 canonical envelope,结论以现行实现复核为准)。

## 仍生效的约束或未决项

- 首图选取不依赖枚举顺序、`OSError→None`;URL 解码留在仓库层;防抖 100ms 且动画驱动不触发;WindowCoordinator 独占过渡;`relayout_only` 不动 textures/dirty。
- 未决:用户枚举风险(auth 文案差异)为非阻断独立议题;4 条 minor observations 未列修复;两份审计为时点性结论,归档后以现行代码为准。