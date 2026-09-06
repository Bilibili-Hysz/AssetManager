# 桌面视觉统一 · 阶段 E 结果（覆盖补齐与文案收口）

> 状态：**STAGE RESULT（2026-09-06）**
> 依据：主报告 V10/V05 残余（§8 阶段 E 完成条件）+ 阶段 D 结果文档 §6 移交清单。
> 范围约束：与并行 LAN 工作线互不接触（其 `lan/`、`webui/`、`thumbnail_service.py`、`file_snapshot.py` 在途改动未纳入本阶段）。

## 1. E-1 · V05 残余：CommandPalette 命令标题运行时重译

| 项 | 改动 |
|---|---|
| 内置命令可重建 | `widgets/command_palette.py`：15 条内置命令抽出为 `_builtin_commands()` 工厂（实例方法，绑定 self 的回调），每次调用以当前语言 `tr()` 重新生成；`_load_available_commands()` 改为**整表重建**（built-ins → tags → favorites → external），不再 `extend` 冻结表 |
| 外部注册保留 | `register_command` 双写：即时 append 进 `_commands`（原行为不变），同时按 `id` 存入新增的 `_external_commands: dict[str, PaletteCommand]`；重建时从 dict 合并回（dict 保持插入序，重复 id 覆盖）。生产两处构造点（`window.py:1156`、`_base_layout.py:785`）均为临时实例，无启动期注册流需要迁移 |
| 描述重译（V10） | 内置命令的英文类别描述（UI Theme / Preferences / Files / Maintenance…）原为绕过 tr() 的字面量，改为 `command_palette.desc_*` 词典键（14 键，Maintenance 复用一个） |
| 模式提示 | 页脚 `"> 命令   # 标签   @ 收藏"` 原为**硬编码中文**字面量且不参与刷新，拆为 `command_palette.hint_mode_cmd/tags/favs` 三键并在 `refresh_overlay_chrome` 重译 |
| 刷新接入 | `refresh_overlay_chrome` 在重跑 `_filter_items` 前调用 `_load_available_commands()`——语言/主题/缩放任一总线信号都会以当前语言重建命令表后重新分组渲染 |

新测试：`test_command_palette.py::test_command_palette_rebuilds_builtins_and_keeps_external_on_language_change`（切语言断言内置标题/描述已变且**不是**原对象、外部注册同对象幸存、">probe" 渲染仍含外部命令）、`::test_command_palette_mode_hint_is_translated`。

## 2. E-2 · V05 残余：QuickLook 提示语 + 三浮层 margins 缩放重排

- `quick_look_overlay.py`：`GenericFileWidget` 提示语改为**存 key 引用**（`_hint_key`/`_hint_default`，构造期照旧 tr()），新增轻量 `retranslate()`（setText(tr(key))）与 `apply_scaled_metrics()`（自身 24/10 margins+spacing 重算）；`QuickLookOverlay.refresh_overlay_chrome` 调用两者。
- 三浮层 `_apply_scaled_metrics` 补齐 layout margins/spacing 的 `scaled_px` 重算（阶段 D 只接了卡宽/输入高/字体）：
  - CommandPalette：根布局阴影 margin 16、搜索行 margins(16,10,16,10)+spacing 10、搜索图标 20×20、页脚 margins(14,6,14,6)+spacing 12（局部布局提为 `_root_layout`/`_search_layout`/`_footer_layout` 成员）。
  - QuickLook：header margins(16,10,16,10)+spacing 10、标题 maxWidth 420、footer margins(16,8,16,8)+spacing 8、GenericFileWidget 联动。
  - QuickTagger：card_layout spacing 10、header spacing 8、tags row spacing 4（root/card margins 阶段 D 已接）。

新测试：`test_overlay_shell.py` 三条缩放用例（palette margins、quicklook bar margins、quicktagger spacing，沿用 `get_ui_scale` monkeypatch + 总线发射既有模式）；`test_quick_look_overlay.py::test_quick_look_generic_hint_retranslates_on_language_change`。

## 3. E-3 · image_viewer 遮罩常量迁移

`panels/image_viewer.py` paintEvent 的 `QColor(0, 0, 0, 180)` 字面量改为 `QColor(0, 0, 0, OverlayShell.SCRIM_ALPHA_MEDIA)`（新 import：`AssetsManager.widgets.overlay_shell`；overlay_shell 只依赖 core，无 panels 反向依赖，无循环 import）。像素行为零变化（180 == 180），仅消除双处真值。

## 4. E-4 · V10 文案一致性缺口收口（高置信度子集）

扫描：桌面范围 `setText("英")` / `QLabel("英")` / `setPlaceholder` / `setToolTip("英` / `QMessageBox*`（多行参数逐一核对均走 tr()）/ `QGroupBox/QCheckBox/QMenu/windowTitle/setAccessibleName` 等模式。

**修复 22 键（三语同步，en/zh/ja 各 1057 keys）**：

| 键 | en | zh | ja |
|---|---|---|---|
| `command_palette.desc_ui_theme` | UI Theme | 界面主题 | UIテーマ |
| `command_palette.desc_preferences` | Preferences | 偏好设置 | 環境設定 |
| `command_palette.desc_files` | Files | 文件 | ファイル |
| `command_palette.desc_explorer` | Explorer | 资源管理器 | エクスプローラー |
| `command_palette.desc_view` | View | 视图 | 表示 |
| `command_palette.desc_help` | Help | 帮助 | ヘルプ |
| `command_palette.desc_library` | Library | 资源库 | ライブラリ |
| `command_palette.desc_maintenance` | Maintenance | 维护 | メンテナンス |
| `command_palette.desc_assets` | Assets | 素材 | アセット |
| `command_palette.desc_extensions` | Extensions | 扩展 | 拡張機能 |
| `command_palette.desc_history` | History | 历史 | 履歴 |
| `command_palette.desc_logs` | Logs | 日志 | ログ |
| `command_palette.desc_system` | System | 系统 | システム |
| `command_palette.desc_application` | Application | 应用 | アプリケーション |
| `command_palette.hint_mode_cmd` / `_tags` / `_favs` | > Commands / # Tags / @ Favorites | > 命令 / # 标签 / @ 收藏 | > コマンド / # タグ / @ お気に入り |
| `plugin_tracker.title` | Downloads | 下载历史 | ダウンロード |
| `plugin_tracker.cmd_clear` | Clear download history | 清除下载历史 | ダウンロード履歴をクリア |
| `plugin_tracker.pref_keep_days` | Keep history (days) | 保留历史（天） | 履歴を保持する日数 |
| `plugin_tracker.pref_confirm` | Confirm clear | 确认清除 | クリアの確認 |
| `plugin_tracker.empty` | No recorded downloads yet. | 暂无下载记录。 | ダウンロードの記録はまだありません。 |

内置插件 `Plugins/Addons/download_tracker/tracker.py` 的空态（V10 证据点名）、面板标题、命令标题、偏好标签全部接 `i18n.tr`（i18n 模块无 Qt 依赖，headless 加载安全）。

**登记为例外（不修）**：
- `widgets/theme_preview.py` 的 "Text input"/"Primary"/"Dialog Title" 等字面量——组件画廊的**刻意固定样张**（specimen），非宿主文案；
- `quick_look_overlay.py` "Space / Esc"、"←"、"→" tooltip 与 `_base_layout.py:277` "Ctrl+K" 按钮——键名/符号，非散文；
- 插件类属性标题为**注册期翻译**（构造时语言档），运行时重译需宿主为插件面板提供刷新钩子——归入 V10 任务"第三方插件语言能力在宿主规范中说明"的后续项。

## 5. E-5 · 覆盖盲区截图扩展

`tests/desktop/test_visual_baseline_a.py` 追加 3 用例（沿用既有 fixture/摘要机制，DARK_THEME=Navy）：

| 截图 | 构造方式 | 轨道 |
|---|---|---|
| `plugin_manager_dialog_navy.png` | 沿用 test_plugin_manager_dialog 的 `_PluginManager` 替身 + monkeypatch | **仅证据轨**（digest 豁免，startup_window 同款处置）：实测对 xdist worker 内前序测试残留敏感（两种稳定帧），组件本体由其单测覆盖 |
| `toast_success_navy.png` | 既有先例 Toast(parent, msg, level, icon, subtitle)，duration=60s 防收敛泵送期间消失 | 摘要棘轮 |
| `empty_panel_navy.png` | `EmptyPanel(state="empty")`（empty role 面板） | 摘要棘轮 |

`SCREENSHOT_UPDATE=1` 再生：PNG 3 张入 `evidence/screenshots/` + manifest 登记（source_head=8571fbf9602…）；摘要棘轮 11 条（原 8 + toast/empty_panel 2 新增，plugin_manager 豁免）。既有 8 条 digest 零漂移（再生前后逐一比对一致），再生后 `-n 0` 全模块 12 passed ×2（update 与 compare 两模式）。

## 6. E-6 · V14 sidebar 双设冗余

`panels/sidebar.py` `_bold_item`：`setWeight(QFont.Weight.Bold)` 与 `setBold(True)` 双设，删后者语义等价冗余（`setBold(True)` 即置 Bold weight）；`QFont` import 随之移除。零视觉变化。

## 7. V09 判定（本轮复核）

本轮未触碰 `settings_dialog.py` / `sharing_settings_dialog.py`，两设置壳无结构性改动——**V09 维持存档**（抽取触发条件未满足）。

## 8. 验证记录（2026-09-06）

- desktop 全套（默认 xdist + `--basetemp=.pytest-tmp-e1`）：**878 passed**（870 基线 + 9 新增：palette×2、quicklook×1、overlay_shell×3、visual baseline×3）。多轮中偶发 1–2 个与本阶段无关的既有时序敏感用例（`test_info_ai_tag` visibility gate、main-window/info-panel 截图摘要），单独运行均绿——与阶段 D §4 记录的共享 settings.json 跨会话干扰同族，非本阶段改动。
- 基线模块 `-n 0`：12 passed ×2 连续（update 再生 + compare 验证），既有 9 截图零漂移。
- 三浮层+palette 专项：42 passed；stylekit 快照/组件统一/sidebar：74 passed。
- unit+integration：**2724 passed, 17 skipped**（2 failed = `test_gen_ts_types`，归属并行 LAN 线在途收尾，非本阶段）。
- ruff 全绿；pyright **0 errors**；三样式门禁 G1 232/39 台账保持、D4 0 违规（95 范围文件）、G3 0 遗留。
- `check_i18n_catalogs`：en/ja/zh 各 **1057** 对齐；`check_documents` current；`check_doc_stats --fix`：README i18n_en/zh/ja 1036→**1058**（含 _meta）。
- 字体清单 `FONT_INVENTORY_UPDATE=1` 再生一次：19 处纯行号平移（command_palette/quick_look/quick_tagger/image_viewer/sidebar 行号位移所致），非 line 字段零变化——本阶段未新增任何 setPointSize/setPixelSize/font-size 调用。
- StyleKit 快照：包 1/2 未改任何 stylekit 调用形态（仅 layout margins/spacing 的 scaled_px 重算与 tr() 接入），`test_stylekit_snapshots` 全绿，无本体改动。

## 9. 阶段 E → F 衔接

| 事项 | 归属 |
|---|---|
| V11 视觉样板截图验收矩阵全量（真实资产网格/信息面板/命令面板组合态） | 阶段 F |
| 插件面板运行时重译的宿主刷新钩子（宿主规范条款） | 阶段 F / 宿主规范 |
| InfoPanel AI-tag 按钮可见性用例的异步交付等待加固（`_wait_until` 既有工具已在同文件） | 独立小修（非视觉） |


## 10. E-2 · M0 时间模型（动画路线第一批，主线程接手完成）

E-2 子代理完成时间驱动主体后因模型流中断，主线程接手收尾：

- **时间驱动核心（子代理已交付）**：`_animator.py` 全面改造——QTimer 仅作 16ms 节拍，一切进度由 elapsed monotonic 时间计算：缩略图淡入=固定时长线性坡（+0.12/次×16ms≈133ms→`motion("micro")` 档，换算依据注释在案）；hover/选择=固定时长 ease-out 插值（0.30 指数趋近→`motion("fast")` 档）；入场节奏=按时间窗释放批次。落定语义：elapsed≥时长即精确终值并清理记录（杜绝 0.99 停滞）；`monotonic` 为模块级测试接缝。reduce_motion 分支/取消路径/世代隔离/纹理缓存交互全部未动。
- **主线程补齐 1——伪时钟测试 ×3**：16ms×8 vs 33ms×4 vs 单次 128ms 跳变 → 同一墙钟时间下进度一致（动画文档 §10 验收第 1 条）；500ms 长停顿单 tick 精确落定；hover 中途改目标从**显示值**重锚定（§6.3——发现翻转的那次 tick 同瞬间重锚，值连续无跳变，断言即锁该语义）。
- **主线程补齐 2——reduce_motion 九文件审计收口**：workspace_bar 指示器动画加守卫（跳变到位+update）；panels/base.py `_animate_in` 加守卫（动画对象保留所有权——生命周期测试断言 parent/stopped——但 reduce_motion 下不 start，面板直接全不透明）；micro_tab_bar 已有守卫；其余（window/coordinator/tabbed/toast/info/grid）此前已收口。image_viewer 缩放为距离驱动算法，按 V07 任务原文豁免。
- **测量点（任务 3）**：animator 接 `_motion_recorder`（`_record_motion_start`/`_record_motion_settle`，thumbnail/hover/selection 三类），复用网格现有 `_performance_recorder` 接口风格，数据可得不接 UI。

## 11. E-2 验证记录

- 网格文件 `-n 0`：**97 passed**（94 + 3 伪时钟）；desktop 全套：**882 passed**
- 基线模块 12 passed（动画中间态不在截图内，零漂移）
- 字体清单再生一次（workspace_bar/base.py 守卫行号平移；98 qss_px 条目签名不变）
- ruff / pyright 0 errors 绿

无证据即 unverified——本文档自身也是这个纪律的适用对象。
