# 桌面视觉统一 · 总览索引（单一入口）

> 状态：**INDEX / LIVING（2026-09-06）** · 本文档是视觉统一工程的总入口：状态账本、文档地图、剩余工作与归属。各阶段细节以对应文档为准。
> 工程 source：[desktop-visual-consistency-2026-09-05.md](../reports/desktop-visual-consistency-2026-09-05.md)（主报告，日期快照）+ [desktop-motion-direction-2026-09-05.md](../reports/desktop-motion-direction-2026-09-05.md)（动画专项）。

## 1. 实施状态总览

| 阶段 | 内容 | 状态 | 结果文档 | 入库 |
|---|---|---|---|---|
| A 基线与规范 | 固定样本 / 截图基线双轨 / 字体度量对照 | ✅ | [stage-a-baseline](desktop-visual-stage-a-baseline-2026-09-05.md) | 4243c6f |
| B 基础控件 | V01 手写 pt 接 token（9/12）/ V02 焦点·禁用对齐 | ✅ | [stage-b-result](desktop-visual-stage-b-result-2026-09-05.md) | 0db2ac5 |
| C 高频主界面 | V03 公共按钮栏 / V04 网格度量运行时化 / V06 零偏移·热区 | ✅ | [stage-c-result](desktop-visual-stage-c-result-2026-09-05.md) | 905f538 |
| 审查轮 | RV1–RV4 全量审查（子代理串行）：_M 快照缺陷修复、账本一致性、三棘轮变异验证、V12–V14 登记 | ✅ | [review-round](desktop-visual-review-round-2026-09-06.md) | bab8b46/7ba1ccc/869e92b |
| D 弹窗与浮层 | V05 OverlayShell 公共外壳 / V07 启动淡入 reduce_motion / V12 indicator 配方 | ✅ | [stage-d-result](desktop-visual-stage-d-result-2026-09-06.md) | 8571fbf |
| E 补齐覆盖 | V05 残余重译 / V10 文案 22 键 / 覆盖盲区截图 / V14 / M0 时间模型 | ✅ | [stage-e-result](desktop-visual-stage-e-result-2026-09-06.md) | f3563e1/6139113 |
| F 验收收口 | §9.3 全组件目录 34 张 / 真机验收模板 / 三重确定性钉扎 | ⏳ 前置件✅ 真机待用户 | [stage-f-acceptance](desktop-visual-stage-f-acceptance-2026-09-06.md) | 01fe3a3 |
| M0 时间与策略 | 网格动画时间驱动 / reduce_motion 九文件审计 / 测量点 | ✅ | stage-e 文档 §10–11 | 6139113 |
| M1–M3 微交互与连续性 | 轻弹性原型 / 内容连续性 / 探索效果 | ⏳ 未启动（见 §4） | — | — |

## 2. 发现账本终态（V01–V14）

| 编号 | 一句话 | 状态 |
|---|---|---|
| V01 字体单位 | 手写 pt 12 处→token（9 迁移+3 处 8pt 密度特例） | ✅ B |
| V02 状态样式 | 输入框焦点 2px 统一 / 禁用单色源 | ✅ B |
| V03 按钮栏 | 最后一处裸 QDialogButtonBox → DialogButtonBar | ✅ C |
| V04 网格冻结值 | 设计值/运行时度量分离 + 往返回归锁 | ✅ C（+RV1 快照缺陷修复） |
| V05 浮层外壳 | OverlayShell + 三浮层迁移 + 缩放响应 | ✅ D（正文重译余量→E 已清） |
| V06 零值规则 | 零偏移短路 / QuickTagger 热区 token | ✅ C |
| V07 动画例外 | 启动淡入接 reduce_motion / 时长档位化 | ✅ D |
| V08 材质叠加 | 配置差异确认，观感待真机 | ⏳ 阶段 F 真机 |
| V09 两设置壳 | 已同范式；RailNav 抽取存档（触发条件：任一壳结构性改动） | 🗄️ 存档 |
| V10 文案缺口 | 22 键三语（palette 17 + tracker 5）；插件运行时重译钩子归宿主规范 | ✅ E（钩子→宿主规范） |
| V11 视觉样板验收 | 34 张目录 + 模板就绪 | ⏳ 阶段 F 真机判定 |
| V12 indicator 分叉 | 全局采工厂 canonical（2px/hover accent/focus） | ✅ D |
| V13 时长字面量 | coordinator 接 motion 档位 | ✅ D |
| V14 setBold 双设 | 已清理 | ✅ E |
| V15 QuickTagger 幽灵方法 | 调生产不存在的 get_tags_for_file，AttributeError 被裸 except 吞——生产永久"暂无标签"、删标签不可达，且被单测桩+截图桩双重掩盖 | ✅ W 轮热修（改批量 get_tags_for_files 消 N+1；桩改真实契约，芯片呈现保留） |
| V16 QuickLook 内存滞留 | 关闭后全分辨率解码 pixmap 滞留（48MP≈190MB），面板引用 write-only 从不清理 | ✅ W 轮热修（closeEvent 释放像素，壳保留） |
| V17 动画态不在截图棘轮 | 全局钉 reduce_motion=True + 直赋字段，动画态渲染面退出基线（只锁数值不锁像素） | ⏳ 阶段 F（补 reduce_motion=False 落定终态摘要用例） |
| V18 大规模反选淡出 O(N)/tick | 10k 行 Ctrl+A 后 ~9 tick×10k 迭代+逐行 rect union，~150ms 掉帧窗 | ⏳ M1 性能批（>500 行跳 tween 直落定） |
| V19 _entrance_visible write-only | 生产零消费者，维护陷阱 | ✅ W 轮（bookkeeping-only 注记） |
| V20 zoom 后入场突发释放 | finish_zoom 不重锚时间窗，队列一 tick 突发（纯外观、罕见时序） | ⏳ M0 收尾顺手项 |
| V21 manifest 对账断言次序 | read 先于 is_file，缺失时报错信息劣化 | ✅ W 轮 |

## 3. 文档地图

- **方案与快照**：主报告（V01–V11 原始发现，勿改写）+ 动画专项（动作角色/时间模型/M0–M3）
- **阶段结果**：stage-a/b/c/d/e 五份 + review-round + stage-f-acceptance（ACCEPTANCE PENDING）
- **证据**：`docs/reports/desktop-visual-consistency-2026-09-05-evidence/`（字体清单棘轮 JSON、caption 度量、34 张截图 + manifest、主题对比度）
- **测试设施**：`tests/desktop/test_visual_baseline_a.py`（截图双轨+摘要棘轮）、`test_font_metric_baseline_a.py`（字体清单棘轮）、`test_overlay_shell.py`、`visual_conftest_helpers.py`（确定性样本库）

## 4. 剩余工作与归属

| 事项 | 归属 | 触发/依赖 |
|---|---|---|
| **真机验收走查**（模板 §4 十六步；V08 观感 / V11 判定 / 错误态与进度运行帧） | **用户** | 真机窗口；判定列回填模板 |
| M1 四样板（指示器轻弹性 A/B / 浮层进出动画）规格卡+录屏评审 | 用户评审后实施 | 依赖真机观感反馈；实现基础设施（M0/档位/reduce_motion 审计）已就绪 |
| M2 内容连续性 / M3 探索效果 | 阶段 F 后 | 依赖 M1 样板评审结论 |
| 8pt 网格密度特例（3 处） | 阶段后续 | 实机视觉校准 |
| ~~`_CORNER_R`→主题派生~~ | ✅ 完成（2026-09-06，df2a9f6）：24 shipped 主题 md 全=10，派生零漂移；回退链保历史字面 10 | — |
| 上游 issue：PySide6 FAST_FAIL / Vite `~` 路径 | 用户决定是否上报 | 质量轮/E 轮登记 |
| ~~低置信度死 i18n key 深审~~ | ✅ 完成（2026-09-06）：动态前缀感知改良扫描——98 零引用中仅 5 个整族全死（window.*/statusbar.*）已删，93 个部分死家族存档保留（动态构造风险） | — |
| push 远端（2026-09-06 实测 `origin/master..HEAD` = **2**：df2a9f6、6c70153） | **用户决策** | — |
| 并行 lan 线收尾（树内未提交产物 + gen_ts_types 2 红的 contracts 再生） | 其会话 | — |

## 5. 已知限制与运行约定（要点）

- 截图摘要棘轮：**单模块 `-n 0` 或默认 xdist 验证**；跨会话并行跑桌面测试共享 settings.json 是已知干扰源（阶段 D §4）
- xdist 全套偶发家族（隔离必绿，登记不修）：main_window_empty / settings_six_tabs / empty_panel 等——同 worker 进程级渲染残留
- offscreen 边界 7 条见验收模板 §5（字体 hinting、96dpi、透明合成等）
