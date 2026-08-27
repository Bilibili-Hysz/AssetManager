# 04 — 验证与验收标准

## 1. 每个任务的最低证据

每个 UI 任务至少提供：

1. 对应行为测试或说明为什么无法自动化；
2. 亮色/暗色主题验证；
3. loading、empty、error 或 disabled 状态验证；
4. 键盘焦点和 Escape/Enter 路径验证；
5. reduced-motion 验证；
6. 截图或明确记录截图环境阻塞；
7. git diff --check 通过。

## 2. Desktop targeted gate

根据改动范围运行最小测试集，至少覆盖：

- tests/desktop/test_settings_dialog.py；
- tests/desktop/test_tabbed_dialog_visuals.py；
- tests/desktop/test_share_link_dialog.py；
- tests/desktop/test_sharing_settings_dialog.py；
- tests/desktop/test_startup_window.py；
- tests/desktop/test_file_list_grid_widget.py（仅当确实触及 Grid 视觉代码时）。

如果新增恢复对话框，应新增对应的 tests/desktop/test_*_dialog.py，不要把所有断言塞入已有设置页测试。

## 3. 视觉验收门

任务只有满足以下条件才能标记 done：

- 没有引入新的硬编码颜色、字号、间距或圆角，除非有明确 token 说明；
- 没有改变服务调用和 Runtime 生命周期；
- 没有改变 FileList 的 scan、reset、loader、cache 或 queue 行为；
- 选中、hover、focus-visible、disabled 能同时区分；
- 动画只使用 opacity、transform、border/color 等低成本属性；
- hover/zoom 不改变卡片尺寸、不触发 reflow；
- reduced-motion 下动画被关闭或降级为即时状态；
- 关键状态具备截图或环境阻塞记录；
- targeted tests、Ruff/compileall（适用时）和 diff check 通过。

## 4. 与主会话的交接证据

每个提交的交接说明必须包含：

- 修改文件清单；
- 未修改的共享文件清单；
- 是否依赖主会话的 view-model/API；
- 测试命令和结果；
- 截图环境、主题、DPI 和窗口尺寸；
- 已知限制和后续接入点。

## 5. 失败处理

如果测试失败或发现需要跨越文件边界：

- 不通过删测试、放宽断言或修改协议来绕过；
- 保留失败证据；
- 说明是 UI 问题、服务契约问题还是环境问题；
- 将跨边界问题交回主会话。
