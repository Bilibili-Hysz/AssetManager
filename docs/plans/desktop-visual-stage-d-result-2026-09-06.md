# 桌面视觉统一 · 阶段 D 结果（弹窗与浮层族）

> 状态：**STAGE RESULT（2026-09-06）**
> 依据：主报告 V05/V07（+审查轮 V12/V13 并入）+ §8 阶段 D 完成条件（屏幕约束、焦点、按钮顺序、保存语义）。
> 范围约束：与并行 LAN 工作线互不接触（其 `thumbnail_service.py`、`file_response.py` 等树内产物未纳入本阶段提交）。

## 1. D-1 · V07+V13+V12 收口

| 项 | 改动 | 视觉 |
|---|---|---|
| V07 启动淡入 | `window.py:286-304` showEvent 首显淡入前检查 `StyleKit.reduce_motion()`——开启时直接 `setWindowOpacity(1.0)` 跳过动画（窗口立即不透明，不构造动画对象）；300ms → `themes.motion("slow")`（值不变） | reduce_motion 下无淡入（预期变更=修复） |
| V13 时长档位化 | `window_coordinator.py:138` 100→`motion("micro")`(120)、`:148` 200→`motion("normal")`(200)；reduce_motion 守卫已存在（:99） | 微调 20ms（预期） |
| V12 indicator 配方 | 全局 `themes.py:858-877` 采对话框工厂方案为 canonical：边框 1px→2px、hover 色 border_focus→accent、新增 `:focus` 规则（border_focus，置于 checked 后镜像工厂优先级）；disabled 两侧本已一致 | **有意视觉变更**：主窗 checkbox/radio 边框加粗、hover 换色（同语义同强度即本阶段目的） |

新测试：`test_window_startup_fade.py`（reduce_motion 跳过 + 正常动画参数）、`test_theme_qss_contract.py::test_indicator_states_match_dialog_factory_recipe`（正则抽取四规则断言 hover=accent/focus=border_focus/2px）、`tests/core/test_themes.py` 选择器清单同步。

## 2. D-2 · V05 浮层公共外壳

**新组件 `AssetsManager/widgets/overlay_shell.py`**：`OverlayShell(QDialog)` 基类（三浮层原直继承 QDialog，改基类侵入最小；mixin 会成菱形继承）。只管 chrome、正文归子类：

- **遮罩语义具名**：`SCRIM_WORKSPACE`（base+α172，统一历史 175/170 漂移）/ `SCRIM_MEDIA`（黑 α180，命名导出供 image_viewer 引用——viewer 本体只加注释未迁移，零爆炸半径）
- **刷新订阅**：构造订阅 theme/language/scale 三总线，closeEvent+done()+shutdown() 三路幂等断开（与 TabbedDialog 同理）；`refresh_overlay_chrome()` 子类钩子
- **屏幕约束**：`_constrain_to_screen`（钳入所在屏 availableGeometry）+ `_position_overlay`/`_focus_target` 钩子；showEvent 统一"捕获归还目标→定位→钳屏→焦点"
- **焦点归还**：关闭时焦点还给打开前记录的父窗口控件

**三浮层迁移**：CommandPalette（`scrim_variant=None` 保留透明浮动卡现状，零意图漂移；卡宽 560/字体/列表高收敛进 `_apply_scaled_metrics`）、QuickLook（删自绘 paintEvent 改用 shell 遮罩；缩放重算按钮尺寸）、QuickTagger（卡 QSS 提取为 `_apply_styles`；卡宽 440 接缩放；无父兜底 geometry→availableGeometry）。

**预期变更**：遮罩 α 统一 172（175/170 历史漂移 ≤3）；**三浮层首次获得缩放响应**（此前完全没有）；关闭路径断开总线+归还焦点（新契约）。**无出入场动画**（逐一核实），shell 文件头注明未来加动画必须走 `StyleKit.reduce_motion()`。

**新测试 20 条**（`test_overlay_shell.py`）：刷新契约×3 参数化、三路关闭断开、media 像素级黑 180、workspace 像素级 base@172（±1 预乘舍入）、palette 无遮罩、缩放宽×2、钳屏×2、焦点进入/归还等。

## 3. D-3 · V09 判定：存档延后阶段 E

`_SettingsNavShell`（settings_dialog，112 行）本就是为镜像 sharing 语法而生的 QTabWidget 兼容适配层（docstring 明言"Mirrors SharingSettingsDialog's shell grammar"）；两壳同用 `StyleKit.nav_css()`、同 760 紧凑阈值——**用户可见的范式统一已在 P1-6 达成**。剩余分叉是内部代码重复（rail 构建两份），收敛属重构而非视觉统一；两个稳定对话框（各自带语言刷新契约与大量测试）的重构回归风险大于维护收益。**判定：阶段 E 候选，触发条件=任一壳需要结构性改动时顺势抽取共享 RailNav。**（与阶段 B 的 D3 判定同款纪律。）

## 4. 截图基线再生与跨会话干扰记录

阶段 D 期间 4 张主窗/Info 截图摘要漂移（main_window_idle×2、info_panel_focused、main_window_empty）。像素取证：差异集中于 **Info 面板右缘垂直滚动条 thumb 区**（y440-739 × x1081-1189，797 点）——内容高度/滚动状态型差异，非样式变更；D-1/D-2 改动均不含 Info 面板。**归因**：并行会话同时在跑测试，共享 `RuntimeData/Shared/settings.json` 的窗口几何/面板状态在基线的几何清理与 MainWindow 构造之间存在竞态窗口。处置：按"漂移即再生"重生成 4 张 PNG+digest（再生后 9 passed ×2 稳定，desktop 870 全绿）。**教训入账**：跨会话并行跑桌面测试共享同一 settings.json 属已知干扰源——基线双轨的"漂移即取证再定性"流程正确消化了它，未误伤真回归。

## 5. 验证记录（2026-09-06）

- desktop：**870 passed**（850 基线 + 20 外壳用例；D-1 后为 850=847+3）
- 基线模块：再生后 9 passed ×2 连续；unit+integration：2724 passed, 17 skipped（**2 failed 归属并行线**：`test_gen_ts_types` 需 webui contracts.ts 再生 `zip_resources` 字段——其 lan/dto.py 在途改动的收尾动作，禁区不代做）
- 三样式门禁全绿（G1 232/39 台账保持、D4 0 违规、G3 0 遗留）；ruff 全绿；pyright 0 errors
- check_doc_stats --fix：python_test_files 335→348、widgets 19→20（本阶段新测试文件）
- 字体清单 `FONT_INVENTORY_UPDATE=1` 再生一次（themes.py 注释 +2 行的行号平移，签名比对证明零语义变化）

## 6. 阶段 D → E 衔接

| 事项 | 归属 |
|---|---|
| V09 两设置壳 RailNav 抽取 | 阶段 E（触发条件见 §3） |
| CommandPalette 命令标题重译（需重建命令表，保留外部注册） | 阶段 E |
| QuickLook GenericFileWidget 提示语重译、浮层 margins 全量缩放重排 | 阶段 E |
| image_viewer 遮罩迁移到 SCRIM_MEDIA 常量 | 阶段 E（现仅注释引用） |
| V10 文案一致性缺口 / V11 视觉样板截图验收矩阵全量 | 阶段 E/F |

无证据即 unverified——本文档自身也是这个纪律的适用对象。
