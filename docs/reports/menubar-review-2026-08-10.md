# 菜单栏组件审查报告（2026-08-10）

> 范围：主窗口菜单栏（`window.py` 菜单构建/几何/主题/语言刷新 + `widgets/workspace_bar.py`
> WorkspaceSection/WorkspaceBar + `window_coordinator.py` apply_menu_theme）。
> 状态：**已修复 6 项，待子代理复审**（附录待回填）。

## 组件清单

```
_menu_widget (QWidget, setMenuWidget)
├── _menu_bar (QMenuBar, native 隐藏)
│   ├── 库菜单：打开库 / 最近库(aboutToShow 重建) / 刷新 / 退出
│   ├── 设置 (直接 action)
│   └── 工具菜单：外部工具(图标+fallback) / 插件管理器 / 插件贡献 / 分享系统 / 键盘快捷键
├── _ws_left (QSpacerItem, 动态)
├── WorkspaceSection：分隔线 + WorkspaceBar(库标签) + "+"按钮
├── _ws_right (QSpacerItem, Expanding)
└── _share_toggle_btn (分享开关, 28x28, icon_primary)
```

## 一、已修复问题

### Bug 1（严重）— 菜单选中项文字对比度不足（17/22 主题 < 4.5）
- `QMenu::item:selected { background: accent }` + 菜单文字 heading。
- 探针实测：Nord 1.74、Rose Pine 1.59、Forest 2.14——选中项文字几乎不可读。
- 修复：`window_coordinator.py apply_menu_theme` 增加 `color: {t['on_accent']}`（on_accent vs accent 全部主题 ≥ 4.7）。

### Bug 2 — 分享按钮 hover 固定白色（浅色主题无反馈）
- `window.py` share 按钮 hover `alpha('#ffffff', 0.1)`：浅色主题 header 近白 → hover 不可见。
- 修复：改用 `alpha(themes.get()['hover_overlay'], 0.1)`（随主题深浅自适应）。

### Bug 3 — 菜单 QSS 双份重复维护
- `window._apply_menu_theme` 与 `coordinator.apply_menu_theme` 内容相同（漂移风险）。
- 修复：window 版改为委托 `self._coordinator.apply_menu_theme()`，单一定义点。

### Bug 4 — 语言切换刷新缺口
- `_refresh_language` 未刷新：键盘快捷键项、分享不可用项、分享按钮 tooltip/accessibleName。
- 修复：保存 action 引用（`_menu_act_shortcuts`/`_menu_act_share_unavailable`）并纳入刷新；share 按钮 tooltip 同步刷新。

### Bug 5 — `_lan_server = None` 初始化位置误导
- 从 `_setup_tools_menu` 末尾（工具菜单逻辑中）移至 `MainWindow.__init__`。

### Bug 6 — WorkspaceSection "+" 按钮文本图标化
- `QPushButton("+")` → SVG `plus` 图标（icon_primary, 12px），tooltip/accessibleName
  （新增 i18n key `workspace.add_library` 三语）。

## 二、核查通过项

- 菜单栏几何：`_on_menu_row_resize` 边界计算（20%/80% + 菜单宽度防重叠）正确；窄窗口隐藏 workspace 而非挤压。
- 最近库菜单：aboutToShow 重建 + lambda 默认参数捕获正确；60 字符截断。
- 菜单图标：全部 `icon_primary` 语义色（工具/插件管理器/插件贡献/share），主题切换经 `_refresh_tools_menu_icons` 重着色。
- `QMenuBar::item:selected` 用 `alpha(accent, 0.313)` 透明背景（深浅主题均 OK，与文字无冲突）。
- WorkspaceBar 指示条 resize 对齐（此前已修复）正常。
- 菜单项 padding（右 28px 图标预留）、字号 scaled_pt(12) 随 ui_scale。

## 三、遗留说明（未修，低优先）

- 工具菜单**外部工具名/插件贡献标题**来自配置/插件（非 i18n），语言切换不刷新——符合预期。
- 菜单选中态下**图标颜色**保持 icon_primary（不随选中变 on_accent）——线条图标对比可接受，保持静态。

## 验证

- ruff 全绿；pytest 28 passed（workspace_bar 6、window_coordinator/startup/lifecycle 13、icons 9）
- i18n：`workspace.add_library` 三语已补

## 附录 · 子代理审计结论

6/6 全部通过，无回归。

| 项 | 结论 | 证据要点 |
|----|------|----------|
| Bug 1 选中项对比度 | ✅ | coordinator:46 `color: on_accent`；22 主题对比度最低 4.70（Rose），全部 ≥4.5 |
| Bug 2 share hover | ✅ | window:322 `alpha(hover_overlay, 0.1)`；alpha import 无 F841 |
| Bug 3 QSS 单定义 | ✅ | window:488-489 仅委托行；grep 无残留重复 QSS；coordinator 先于 `_setup_ui` 创建（:46/:62） |
| Bug 4 语言刷新 | ✅ | share_unavailable 仅 else 分支保存（:278-280）+ hasattr 防御刷新（:527-534）；shortcuts 无条件保存 |
| Bug 5 `_lan_server` | ✅ | 移至 __init__（:66）；_setup_tools_menu 无残留 |
| Bug 6 "+" SVG 化 | ✅ | workspace_bar:359-360 icon_primary plus 12px；i18n 三语（zh:754/en:715/ja:754）JSON 有效；scaled_pt 仍使用无 F841 |

回归：pytest 13 passed（workspace_bar 6 + window_coordinator/startup/lifecycle 7）+ icons 9；ruff 3 文件全绿。
