# 桌面视觉统一 · 阶段 F 真机验收记录（模板）

> 状态：**ACCEPTANCE PENDING（待真机验收，2026-09-06 建档）**
> 依据：主报告 [desktop-visual-consistency-2026-09-05.md](../reports/desktop-visual-consistency-2026-09-05.md) §9.2 验收矩阵 / §9.3 视觉样板与截图要求 + 阶段 A–E 结果文档。
> 截图目录：[docs/reports/desktop-visual-consistency-2026-09-05-evidence/screenshots/](../reports/desktop-visual-consistency-2026-09-05-evidence/screenshots/)（34 张 PNG + manifest.json，由 `tests/desktop/test_visual_baseline_a.py` 产出，`SCREENSHOT_UPDATE=1` 再生）。
> 范围约束：与并行 LAN 工作线互不接触（其 `lan/`、`webui/`、`thumbnail_service.py`、`file_snapshot.py` 在途改动未纳入本目录）。

## 1. 使用说明

1. 本模板与截图目录**一一对应**：§3 组件目录表的每一行 = 截图目录里的一张 PNG（`manifest.json` 同名键，含 §9.3 全部元数据字段：组件/状态、主题、语言、应用缩放、系统DPI、窗口尺寸、字体环境、Qt 版本、提交及未提交差异、样本数据版本、截图文件名）。
2. 真机核验逐项执行：每完成一项，在 §3"真机判定"列填 **通过 / 偏差（附 V 编号或描述）/ 延期原因**；发现偏差时先登记再修复，不改写历史判定。
3. **不以脚本通过替代截图**（主报告 §9 验收纪律）：`test_visual_baseline_a.py` 全绿只证明"offscreen 确定性摘要未回归"，不证明真机观感；离屏已验列打勾的行仍须真机复核后才可判定通过。
4. 摘要棘轮（`tests/desktop/snapshots/visual_baseline_digests.txt`）与 PNG/manifest 由同一命令再生：`SCREENSHOT_UPDATE=1 python -m pytest tests/desktop/test_visual_baseline_a.py -n 0`。34 张中 32 张走摘要比对轨；2 张（#9、#10）为**仅证据轨**（PNG/manifest 落盘、无摘要比对，豁免理由见各用例 docstring 与 §3 注）。
5. 本模板是阶段 F 的**验收记录载体**：真机验收完成后在状态头追加 `ACCEPTED / PARTIAL（日期）` 并保留全部判定痕迹。

## 2. 验收矩阵（主报告 §9.2 十维度 → 离屏已覆盖 / 待真机）

| 维度 | 离屏已覆盖（截图目录 + 单测） | 待真机 |
|---|---|---|
| 主题 | Navy 暗代表全组件 34 张；Dawn 亮代表主窗/网格 2 张；24 主题参数由 `test_theme_qss_contract` / theme-contrast 证据覆盖 | Dawn/阈值主题扩到全组件；真实观感、状态色对比度人工判读 |
| 语言 | 全部截图钉 en（manifest `language` 字段）；三语目录对齐由 `check_i18n_catalogs` 门禁覆盖 | zh/ja 长标签、按钮宽度、换行、缺字走查；语言往返恢复 |
| 应用缩放 | 全部截图钉 ui_scale=1.0（manifest `ui_scale`）；缩放重算契约由 `test_overlay_shell` / `test_dialog_runtime_refresh` 等单测覆盖 | 1.25/1.5/2.0 与边界 0.5/3.0 的整窗可用性、热区、圆角/字号实感 |
| 系统DPI | 无（offscreen 固定逻辑 96dpi，manifest `system_dpi` 如实记录） | Windows 100%/150%/200% 全组件走查；混合 DPI 双屏移动（模糊/重复缩放/弹窗位置） |
| 窗口 | 默认尺寸（各对话框 min_size）、窄窗回退（设置/分享导航壳 <760 顶部导航，单测覆盖） | 窄窗口溢出、最大化、面板浮动、弹窗屏幕约束实机复核 |
| 状态 | idle + hover + 选中（网格 #4/#5 编程触发）；模态 idle 态；空态（#3/#12） | pressed/disabled/read-only/focus 独立判读；焦点不依赖 hover 的键盘走查 |
| 数据 | representative（长名/多标签/渐变彩图/子目录）+ empty 两个确定性 profile | 大目录滚动性能、多选批量反馈、拥挤/截断的真实字体下的观感 |
| 媒体 | 渐变 PNG（#32/#34）+ 通用文件占位（单测） | 横/竖图、透明 PNG、大图、损坏文件、视频、音频的真实解码与占位/失败区别 |
| 背景 | 无（背景关闭/亮图/暗图/高细节为运行时合成，离屏不具备判读意义） | 背景四态 + CPU/GL 回退的合成后文字可读性、窗口重绘 |
| 动态 | reduce_motion=True 钉扎下截图收敛（无动画帧）；主题/语言重译契约由单测覆盖 | 主题/语言/缩放往返无残留；库切换焦点保留；reduce_motion 开关实测 |

## 3. 组件目录表（§9.3 全组件清单，34 张）

> "离屏已验"列：✔ = 摘要棘轮比对轨（跨运行确定性摘要已入 `visual_baseline_digests.txt`）；仅证据 = PNG/manifest 证据轨（豁免理由见注）。
> "真机判定"列留空待填：通过 / 偏差 / 延期原因。

| # | 组件（§9.3 条目） | 状态 | 主题 | 截图文件名 | 离屏已验 | 真机判定 |
|---|---|---|---|---|---|---|
| 1 | 默认主窗口 | idle + Info 聚焦 | Navy | main_window_idle_navy.png | ✔ | |
| 2 | 默认主窗口 | idle（亮主题代表） | Dawn | main_window_idle_dawn.png | ✔ | |
| 3 | 默认主窗口 | 空库空态 | Navy | main_window_empty_navy.png | ✔ | |
| 4 | 网格列表 | hover + 选中 | Navy | file_list_grid_navy.png | ✔ | |
| 5 | 网格列表 | hover + 选中 | Dawn | file_list_grid_dawn.png | ✔ | |
| 6 | 详细列表 | 详情视图 | Navy | file_list_details_navy.png | ✔ | |
| 7 | Info 各分段 | 聚焦（名称/信息/标签/备注） | Navy | info_panel_focused_navy.png | ✔ | |
| 8 | 编辑模态（主题预览） | idle | Navy | theme_preview_dialog_navy.png | ✔ | |
| 9 | 启动页 | idle（最近库/首次使用卡片） | Navy | startup_window_navy.png | 仅证据¹ | |
| 10 | 插件管理 | 选中插件详情 | Navy | plugin_manager_dialog_navy.png | 仅证据² | |
| 11 | Toast | success + 图标 + 副标题 | Navy | toast_success_navy.png | ✔ | |
| 12 | 空态 | empty role 面板 | Navy | empty_panel_navy.png | ✔ | |
| 13 | 设置·外观页 | tab:appearance | Navy | settings_dialog_appearance_navy.png | ✔ | |
| 14 | 设置·通用页 | tab:general（语言/UI缩放/AI打标） | Navy | settings_dialog_general_navy.png | ✔ | |
| 15 | 设置·缩略图页 | tab:thumbnails | Navy | settings_dialog_thumbnails_navy.png | ✔ | |
| 16 | 设置·维护页 | tab:maintenance | Navy | settings_dialog_maintenance_navy.png | ✔ | |
| 17 | 设置·备份页 | tab:backup | Navy | settings_dialog_backup_navy.png | ✔ | |
| 18 | 设置·插件页（内置插件面板） | tab:plugins | Navy | settings_dialog_plugins_navy.png | ✔ | |
| 19 | 分享设置·端点页 | page:endpoint（离线态） | Navy | sharing_settings_endpoint_navy.png | ✔ | |
| 20 | 分享设置·链接页 | page:links（离线态） | Navy | sharing_settings_links_navy.png | ✔ | |
| 21 | 分享设置·访问页 | page:access | Navy | sharing_settings_access_navy.png | ✔ | |
| 22 | 分享设置·配置页 | page:configuration（桩化默认值） | Navy | sharing_settings_configuration_navy.png | ✔ | |
| 23 | 编辑模态（标签编辑） | 当前标签芯片 + 建议列表 | Navy | tag_editor_dialog_navy.png | ✔ | |
| 24 | 编辑模态（批量重命名） | 计划有效（3 行表） | Navy | batch_rename_dialog_navy.png | ✔ | |
| 25 | 编辑模态（标签样式） | idle（hero） | Navy | tag_style_dialog_navy.png | ✔ | |
| 26 | 编辑模态（侧栏设置） | idle | Navy | sidebar_settings_dialog_navy.png | ✔ | |
| 27 | 编辑模态（分享二维码） | QR 已生成（固定 URL） | Navy | share_qr_dialog_navy.png | ✔ | |
| 28 | 编辑模态（颜色选择） | 初值 #123456 | Navy | color_picker_dialog_navy.png | ✔ | |
| 29 | 编辑模态（崩溃恢复通知） | Warning + Ok/报告按钮 | Navy | crash_report_dialog_navy.png | ✔ | |
| 30 | 标签树 | 真实 TagService 数据 | Navy | tag_browser_tree_navy.png | ✔ | |
| 31 | CommandPalette | 打开态（输入聚焦 + 命令表） | Navy | command_palette_open_navy.png | ✔ | |
| 32 | QuickLook | 样本图已加载 | Navy | quick_look_image_navy.png | ✔ | |
| 33 | QuickTagger | 带目标文件（gradient.png + 标签芯片） | Navy | quick_tagger_overlay_navy.png | ✔ | |
| 34 | ImageViewer | 样本渐变图 ready | Navy | image_viewer_gradient_navy.png | ✔ | |

注 1（#9 仅证据轨）：StartupWindow 在构造期重读磁盘 settings，卡片集合受同 worker 前序测试的落盘残留影响，存在两种稳定帧的时序二态（用例 docstring 详述）。
注 2（#10 仅证据轨）：插件对话框渲染对同 worker 前序测试的进程级渲染残留敏感（xdist 分组不同产生不同稳定帧）；本体无样式问题（单测全绿）。
注 3（目录树侧）：§9.3"目录/标签树"的目录侧对应物 = #1/#3 的侧栏树（representative 样本含 sub/ 子目录）；标签树侧为 #30。

### 3 末尾 · 缺失清单（§9.3 点名但无对应截图，登记跳过理由）

| §9.3 条目 | 跳过理由 | 补偿路径 |
|---|---|---|
| 真实错误态（损坏文件解码失败帧、库损坏/IO 错误） | 真实故障态需故障注入与真实运行环境判读；离屏构造的"错误占位"不能代表真实错误呈现（任务书点名项） | 真机人工构造：损坏图片文件 + 拔盘路径库（§4 步骤 13），截图补入本目录后回填编号 |
| 可取消与不可取消进度（运行中进度帧） | 进度运行态依赖真实长任务（缩略图重生成/备份/恢复），内容时变（百分比/剩余时间）——摘要不稳定且离屏无判读意义；控件 idle 形态已由 #15/#16/#17 覆盖 | 真机运行缩略图重生成与备份任务观察运行帧（§4 步骤 14） |

## 4. 真机操作清单（每步标注核验的组件编号）

前置：真实桌面会话（非 offscreen），干净 settings（或记录当前值）；每步完成后在 §3 判定列落笔。

1. **启动真实 app**（真实工作目录，记录托盘/单实例行为）→ 核验 #9、#1（首屏）。
2. **主窗走查**：菜单行/工作区标签/侧栏/网格/信息面板/状态栏；键盘 Tab 走焦点环 → #1、#3、#4（对照截图判读布局与裁切）。
3. **网格/详情切换 + hover/选中/多选**（鼠标与键盘两路）→ #4/#5/#6。
4. **Info 各分段**：聚焦图片文件，逐段（名称/信息/标签/备注）核对 → #7；从标签段打开标签树 → #30。
5. **设置六页逐页走查**（左侧栏导航 + 窄窗顶部导航回退）→ #13–#18；维护/备份页**仅走查 idle 形态**（运行帧见步骤 14）。
6. **分享设置四页走查**：启动 LAN 服务后重开对话框，核对"运行中"状态与离线态差异 → #19–#22。
7. **编辑模态逐个打开**：批量重命名（多选 → Ctrl+R 流程）、标签编辑（Info 段入口）、标签样式（标签树右键）、侧栏设置、分享二维码（真实分享链接）、颜色选择、主题预览 → #23–#28、#8。
8. **崩溃恢复通知**：在安全环境构造一次带 crash 记录的启动（或用 `build_crash_report_dialog` 手工触发）→ #29。
9. **浮层带内容**：Ctrl+K 命令面板（输入过滤、> / # / @ 三模式）、空格 QuickLook（图片与通用文件各一）、T 快速打标（单选与多选）、双击进 ImageViewer → #31–#34。
10. **DPI 走查**：Windows 显示缩放 100% → 150% → 200%，每档重开主窗 + 设置 + 一个浮层，对照截图核对布局/字号/热区 → 全部组件；重点 #27/#31–#34（浮层定位与阴影）。
11. **混合 DPI 双屏**：跨屏拖动主窗与浮层，检查模糊/重复缩放/弹窗屏幕约束 → #27、#31–#34。
12. **主题往返**：Navy → Dawn → Navy，重开各容器，核对无样式残留 → #1/#2、#13–#22；**reduce_motion 开/关**各走一遍网格 hover 与浮层开关（V07 契约）。
13. **切库/切语言**：切换两个真实库 + en/zh/ja 各一轮主窗与设置 → #1、#13–#18（语言往返恢复正确性，主报告 §9.3 关键验收第 3 条）。
14. **进度运行态**（补缺失清单）：触发缩略图重生成（可取消）与备份（不可取消），观察运行帧与取消行为 → 回填 §3 缺失清单。
15. **真实错误态**（补缺失清单）：加载损坏 PNG、指向失效盘符的库 → 观察占位/失败区别与错误呈现 → 回填 §3 缺失清单。
16. **背景合成**（§9.2 背景维度）：背景关/亮图/暗图/高细节图四态核对文字可读性 → #1（叠加态无离屏对应物）。

## 5. 边界声明（offscreen 渲染与真机的已知差异）

1. **字体与字形**：offscreen 平台字体回退与真机不同——本仓 offscreen 基线中 tr() 文本以 tofu 方块字形呈现（回退族缺字形覆盖，manifest `font_environment` 如实记录族名/hinting）。因此**文字度量、换行、截断、省略号的正确性不在离屏可判读范围**，全部以真机步骤 2–9 复验为准；摘要棘轮只保证"同一生成机制下跨运行不变"，不保证与真机像素一致（主报告 §9.3"同一平台固定字体后再建立像素基线"）。
2. **系统 DPI**：offscreen 固定逻辑 96dpi，无 Windows DPI 缩放与 DPI 变化事件——DPI 维度（§2）离屏覆盖为"无"，全部待真机。
3. **透明合成**：浮层（`WA_TranslucentBackground`）在 offscreen 下无真实桌面 alpha 合成——透明区域在 grab 中读作黑/主题底色（如 toast 截图四角），阴影/遮罩（SCRIM）/毛玻璃的观感只能真机判读。
4. **窗口几何与屏幕约束**：offscreen 屏幕为虚拟几何（逻辑 96dpi 假屏），OverlayShell 的 availableGeometry 钳制与浮层定位逻辑在真机多屏/混合 DPI 下可能有不同落点。
5. **动画**：全部截图在 `reduce_motion=True` 钉扎 + 静止收敛泵下抓取（无动画帧）；真机默认动画开启，观感差异按动画契约（V07）判读，不视为离屏/真机矛盾。
6. **动态内容桩化**：分享设置页（MCP token 前缀等本机随机持久值）以只读设置桩落默认值；QuickTagger 标签集为定值桩（生产 `application.TagService` 与浮层读取面的适配接缝见用例 docstring）。真机验收时这两处以**真实数据**形态复核（步骤 6、9）。
7. **进程隔离约定**：摘要棘轮的验证命令是单模块 `-n 0` 或全套默认 `-n auto`；共享进程 `-n 0` 跑整个 desktop 套件的滚动条级渲染残留属已知限制（模块 docstring），不作为真机判读依据。
