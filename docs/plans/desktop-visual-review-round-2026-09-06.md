# 桌面视觉统一 · 全量审查轮（RV1–RV4，子代理串行）

> 状态：**REVIEW ROUND RESULT（2026-09-06）**
> 对象：阶段 A/B/C 全部交付（4243c6f / 0db2ac5 / 905f538）+ 证据体系 + 测试门禁健康 + 桌面视觉面 fresh-eyes。
> 方式：串行子代理（RV1 代码审查 / RV2 账本证据一致性 / RV3 测试门禁健康 / RV4 fresh-eyes 扫描）；RV1 中断后主线程接手收尾，RV2/RV4 因派发中断改主线程执行。

## RV1 · 阶段 A/B/C 代码审查（✅ 抓到并修复 1 个真实缺陷）

**缺陷（已修，commit bab8b46）**：`_grid_widget_render.py` 用 `from _grid_widget_data import _M`——`rebuild_grid_runtime_metrics()` 重绑 data 模块容器后，render 的名字仍指向旧冻结实例；1.0→1.5 时圆角走新 `_RM` 而边距仍是导入期值（V04 修的病的残留变体）。修复：模块限定访问 `_grid_data._M`（live 容器）+ 回归断言 `grid_render._grid_data._M is grid_data._M`；清单 JSON 行号平移再生。

七维度复核结论：
- **token 等值**：24 主题 font_size 无任何非默认覆盖（值域 9–22），9 处迁移零漂移声明成立于全部 shipped 主题；`int()` 包裹冗余但无害（防御主题浮点值）
- **重建机制**：两个 rebuild 均 `global` 声明正确；render `_RM` 同模块重绑原子；`_M` 跨模块曾快照（已修）
- **DialogButtonBar**：基类 `_on_language_changed` 经 `_button_box.button()` + `_apply_btn` 两路刷新 OK/Cancel/Apply——sharing 两个标准属性均已登记，契约成立；`_dialog_apply_btn` 无外部读者
- **elevation**：`offset_x == 0` 覆盖 0.0 float；负偏移当前词汇表无、注释已声明
- **quick_tagger 22→24**：有意视觉变更（非零漂移），阶段 C 文档如实记录；quick_tagger 不在截图基线——盲区登记（见 §RV3 遗留）
- **文档主张**：手写 12→3 / token 8→14 / md 全=10 / 24 主题无 font_size 覆盖——全部实测复核成立

## RV2 · 账本证据一致性（✅ 修复 3 处漂移）

- **V01–V11 逐项状态表**：已收口 5 项（V01/V02/V03/V04/V06）与代码一致；V05/V07/V08/V09/V10/V11 无虚声称（阶段 D/后续归属正确）
- **修复 1**：三份阶段文档的"工作树未 commit"状态头过期 → 统一改为 commit 哈希标注（4243c6f / 0db2ac5 / 905f538）
- **修复 2**：stage C 追加 §6 证据时效性说明——screenshots/manifest 的 `source_head` 混有 `112483c8`（A 期 8 张）与 `7d07098a`（B 期空库再生 1 张）；B/C 的零漂移改动按"漂移即再生"策略未重生成 PNG，但每次都经摘要棘轮验证"当前渲染与入库 PNG 逐行等价"
- **修复 3**：README `python_test_files` 328→335（并行 lan 工作线树内新测试文件的共享计数同步，`--fix`）
- i18n 双口径澄清：README/doc_stats 的 1036 含 `_meta` 键、check_i18n_catalogs 的 1035 排除——两门禁各自自洽，非漂移

## RV3 · 测试与门禁健康（✅ 三棘轮变异验证 + 补 3 覆盖测试）

**变异验证（改→红→还原→绿，git diff 核验还原干净）**：

| 棘轮 | 变异 | 结果 |
|---|---|---|
| 摘要棘轮 | digests.txt 篡改 rows 哈希 | 红（digest mismatch 逐字符 diff）→ 还原绿 |
| 字体清单棘轮 | 临时加 `scaled_pt(7)` | 红（20≠19 定位到行）→ 还原绿 |
| 样式门禁 | 面板加硬编码 hex QSS | 红（2 处 literal-hex-in-qss）→ 还原绿 |

**跑分**：desktop **844 passed ×3**；unit+integration **2715 passed, 17 skipped**（基线持平）；无真回归。flaky 账本无新成员（main_window_empty 时序二态约 1/4 触发率，隔离必绿，维持登记）。

**覆盖补强（3 个新测试）**：
- `test_refresh_theme_rebuilds_runtime_metrics`：refresh_theme 路径的重建此前**零测试**（V04 测试只护 scale 路径）——主题可覆写 `radius_badge` 时该路径就是生产回归面
- `test_dialog_button_bar_add_button_inserts_between_cancel_and_ok`：插入序 Cancel|custom|OK + roles
- `test_dialog_button_bar_unknown_standard_button_and_role_fallback`：未知枚举 None / 兜底 ApplyRole
- 判定不补：elevation 非零偏移分支（当前词汇表全零偏移，防御性死代码）；登记未补：`shadow_params()`/`refresh_elevation()` 零测试（3-10 行薄包装，低价值）

**门禁全景**：六门禁 + 三样式门禁全绿（ruff/pyright 各 1 个残留 error 在并行区 `lan/zip_sources.py`，合入前须其归属会话清理）。

## RV4 · fresh-eyes 扫描（✅ 新发现 V12–V14，登记不实施）

七维度扫描（硬编码值/动画字面量/缩放冻结/浮层清单/字体旁路/状态分叉/可访问性）。**排除项**：QColor(0,0,0,α) 阴影族=elevation 规范语义；dominant_palette_strip 的 rgba 白/黑叠层=作用于内容派生色（图象调色板），语义豁免；浮层恰为 V05 登记的 3 个无漏网；网格外无模块级冻结常量。

| 编号 | 严重度 | 发现 | 证据 | 建议归期 |
|---|---|---|---|---|
| **V12** | **P1** | **checkbox/QRadioButton indicator 状态分叉**：hover 全局=`border_focus` 1px（themes.py:867）vs 对话框工厂=`accent` 2px（stylekit.py:300）；checked 边框宽度同样 1px vs 2px——V02 同类病在 indicator 上，V02 收口未覆盖 | 两处 QSS 对照 | 阶段 D（与 V02 同批"indicator 配方对齐"） |
| V13 | P3 | window_coordinator 主题过渡时长字面量 100/200ms 未接 `themes.motion()` 档位（reduce_motion 守卫已存在 :99，仅时长未具名化）——并入 V07 时长具名化任务 | window_coordinator.py:138,148 | 阶段 D（V07 批次） |
| V14 | P3 | sidebar.py:348-349 `setBold(True)` + `setWeight(Bold)` 双设冗余（微方言） | sidebar.py:348 | 顺手项 |

**Top 3 优先**：V12（真状态分叉，用户可见）> V13 > V14。

## 审查轮验证记录（2026-09-06）

- RV1 修复后：往返纹理用例 3 连绿、基线模块 9 passed、desktop 全绿
- RV3 补测后：`test_tabbed_dialog_visuals + test_file_list_grid_widget` → 113 passed
- RV2 后：check_doc_stats（README 335 同步）/ check_documents 绿
- 全套：desktop 844×3（RV3 轮）、unit+integration 2715（本轮一次）
- 提交：bab8b46（RV1 修复）、本提交（RV2 文档 + RV3 测试 + RV4 文档）

无证据即 unverified——本文档自身也是这个纪律的适用对象。


---

# 第二轮全量审查（W1–W4，子代理串行，2026-09-06）

> 对象：阶段 D/E/F + 决策项 7 提交（8571fbf…6c70153）。W1 中断后重派成功；W2/W4 因并发限制改主线程执行。

## W1 · 代码审查（7 维度全✅，3 实质修复）

- **修复**：① late-settle 测量契约测试补齐（动画文档 §10 第 1 条的 `late`/`max_late_ms` 此前无锁定）② `setCursorFlashTime(0)` 进程级钉扎补还原纪律 ③ 6139113 提交内 E731 lambda（该提交"ruff 绿"声明与树不符，已修正）
- **重要更正**：F 阶段"QFont() 免疫字体污染"的注释断言经实证为**错**（QFont() 返回同族同号）——工作树注释已正；钉扎的真实价值是"确定性基准"而非"免疫"
- 登记：6139113 提交信息超claim（E-1 文件实为 83 秒后的 f3563e1）；OverlayShell ctor 哨兵重载注释建议

## W2 · 账本证据一致性（14/14 核对一致）

- 34 PNG == 34 manifest == 32 摘要 + 2 豁免，三方对账干净；manifest 抽 3 条字段真实
- 修复 4 行：索引 C 行断链（-09-06→-09-05）、push 行改实测（origin..HEAD=2）、D/E 状态头入库化（RV2 漏盖其后新建的两份）

## W3 · 测试门禁健康

- desktop ×3：903/902/902 → 补测后 905/904；失败成员全部属登记偶发家族（隔离必绿）。**钉扎收敛结论：部分收敛**——appearance/empty_panel/palette 0/4 消失；six_tabs 2/4、main_window_empty 1/4 轮转仍活跃（升级条件已写入账本）
- 变异抽检三发全中（新摘要条目/字体清单 px 族/PNG-manifest 对账——对账守卫系 W1 在途新增，双向 set 强于条目数）
- 补 2 覆盖测试（均有"牙齿验证"：临时抹除守护逻辑→红→逐字节还原）：scrim None 零绘制像素锁、错峰重提交时间窗重锚
- 门禁全绿——**并行线已清掉 zip_sources 的 ruff/pyright 残留**

## W4 · fresh-eyes（新面扫描，登记 V15–V21，Top 2 已热修）

- **V15（P1，已热修）**：QuickTagger 调生产不存在的 `get_tags_for_file`，AttributeError 被裸 except 吞——生产永久"暂无标签"、删标签不可达，且被单测桩+截图桩双重掩盖（测试在锁错误契约）。修复：批量 `get_tags_for_files`（消 N+1）+ 桩改真实契约（芯片呈现保留、摘要零再生）
- **V16（P2，已热修）**：QuickLook 关闭后全分辨率 pixmap 滞留（48MP≈190MB）——closeEvent 释放像素、壳保留（WA_DeleteOnClose 方案因改变生命周期语义被测试否决，弃用）
- V17 动画态不在截图棘轮（阶段 F 补落定终态用例）/ V18 大反选 O(N)/tick（M1 性能批）/ V19 write-only 状态（注记）/ V20 zoom 后入场突发释放（M0 收尾）/ V21 断言次序（已修）
- 五维度排除项（除零/None/闭包生命周期等均有守卫或测试锁定）详见审查记录

## W 轮验证

- 主线程：基线+网格 140 passed；desktop 终态 902+（轮转家族成员全数隔离绿）；ruff/pyright 0；字体清单再生一次（V15/V16/V19 行号平移，98/20 不变）；i18n 1052×3
- 提交：本提交（W1 修复 + W3 补测 + V15/V16/V19/V21 修复 + 账本 V15–V21 + 本节）

无证据即 unverified——本文档自身也是这个纪律的适用对象。
