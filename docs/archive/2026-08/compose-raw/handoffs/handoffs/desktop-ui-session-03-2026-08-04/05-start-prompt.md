# 05 — 第二会话启动提示词

以下内容可以直接复制到第二会话：

```text
你现在负责 AssetsManager 项目的 Desktop UI V2 受限子任务，同时继续保留 WebUI 主线职责。

请先读取并理解以下文档：

1. docs/compose/handoffs/desktop-ui-session-03-2026-08-04/README.md
2. docs/compose/handoffs/desktop-ui-session-03-2026-08-04/01-current-state.md
3. docs/compose/handoffs/desktop-ui-session-03-2026-08-04/02-scope-and-file-ownership.md
4. docs/compose/handoffs/desktop-ui-session-03-2026-08-04/03-task-backlog.md
5. docs/compose/handoffs/desktop-ui-session-03-2026-08-04/04-verification-and-acceptance.md
6. DeepSeek Docs/施行路线图.md
7. DeepSeek Docs/未来方向/05-桌面端UI视觉改进规划.md
8. DeepSeek Docs/未来方向/06-现代化界面技术路线评估.md
9. DeepSeek Docs/未来方向/07-桌面端性能优化计划.md

任务定位：

- 你可以处理 Qt 的纯表现层、视觉状态、QSS、原生控件样式、对话框外观、空/错/加载状态、截图和 UI 行为测试。
- 你可以为 G6-1 备份/恢复入口制作纯 UI 对话框壳层，但不得自行实现恢复服务、Runtime 重建、数据库操作或 session 生命周期。
- 主会话已提供 LibrarySettingsAdapter，并通过 SettingsDialog.library_settings_adapter 注入；UI 只能消费 adapter，不得直接读取 LibraryScopedServices。
- 你必须继续遵守 WebUI 第二会话的 API、权限、RealtimeContext 和真实浏览器验收边界。

严格禁止修改或重构以下范围：

- AssetsManager/application/
- AssetsManager/core/
- AssetsManager/window.py
- AssetsManager/application/bootstrap.py
- AssetsManager/panels/file_list/__init__.py
- AssetsManager/panels/file_list/_base.py
- AssetsManager/panels/file_list/_model.py
- AssetsManager/panels/file_list/_loader.py
- AssetsManager/panels/file_list/_navigation.py
- AssetsManager/panels/file_list/_thumbnail_delivery.py
- AssetsManager/panels/file_list/_grid_widget.py
- AssetsManager/dialogs/_share_api.py
- AssetsManager/dialogs/share_link_dialog.py
- AssetsManager/dialogs/sharing_settings_dialog.py
- AssetsManager/widgets/lan_sharing.py

不要修改 LAN API、DTO、权限、cookie、WebSocket、revision/epoch 协议；不要引入 QML、QWebEngine、全量 canvas、大型动画库或没有真实性能证据的虚拟滚动。

请按以下顺序开始：

1. 只读检查工作树，并确认现有未提交改动主要属于 webui/ 和 docs/compose/handoffs/webui-session-02-2026-08-03/；不要回滚或覆盖它们。
2. 只读检查 Desktop UI 当前测试和主题 token 管线。
3. 提出一个不超过一个提交的最小 UI 子任务，优先选择 D1 原生控件视觉补全或 D2 对话框视觉统一。
4. 在得到明确边界后再修改文件；每个任务独立提交。
5. 提交前运行对应 targeted tests、适用的 Ruff/compileall、git diff --check，并记录截图或环境限制。
6. 最终报告必须列出修改文件、未修改的共享文件、测试结果、视觉证据和后续接入点。

第一轮不要修改 FileList 的模型、loader、导航、缩略图队列、reset 语义或性能遥测；不要把“视觉完成”写成“Desktop/LAN/WebUI 整体发布完成”。
```
