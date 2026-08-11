# 02 — 范围与文件认领

## 1. 第二会话可以认领的文件域

### A. 纯视觉 widgets

优先范围：

- AssetsManager/widgets/elevation.py
- AssetsManager/widgets/title_bar.py
- AssetsManager/widgets/tab_container.py
- AssetsManager/widgets/collapsible_panel.py
- AssetsManager/widgets/toast.py
- AssetsManager/widgets/workspace_bar.py
- 指定的新建纯视觉 widget 文件。

允许内容：

- objectName 和视觉状态；
- token/QSS 使用；
- spacing、radius、字体和阴影统一；
- focus、hover、pressed、disabled、error 状态；
- reduced-motion；
- 组件级 Qt 行为测试和截图测试。

### B. 纯表现层 dialogs

可以认领：

- 新建的恢复/备份对话框 UI 壳层；
- TabbedDialog 的视觉统一部分；
- theme_preview_dialog.py、generic_settings_dialog.py 等不改变服务契约的视觉部分；
- 对话框 TitleBar、按钮层级、阴影、淡入和错误状态布局。

约束：服务调用、Runtime 状态、关闭 session 和恢复结果模型由主会话提供；第二会话只消费稳定的 view-model 或 signal/slot 结果。

### C. 指定 panels 的表现层

可以在明确认领后处理：

- AssetsManager/panels/empty.py；
- AssetsManager/panels/sidebar.py 的纯布局和状态样式；
- AssetsManager/panels/info.py 的纯展示样式；
- AssetsManager/panels/tag_tree.py 的纯展示样式；
- 不涉及服务装配的 loading、empty、error、retry 视觉组件。

## 2. 当前必须由主会话保留的文件域

以下文件在 Desktop UI V2 阶段禁止第二会话直接修改：

- AssetsManager/application/；
- AssetsManager/core/；
- AssetsManager/window.py；
- AssetsManager/panels/file_list/__init__.py；
- AssetsManager/panels/file_list/_base.py；
- AssetsManager/panels/file_list/_model.py；
- AssetsManager/panels/file_list/_loader.py；
- AssetsManager/panels/file_list/_navigation.py；
- AssetsManager/panels/file_list/_thumbnail_delivery.py；
- AssetsManager/panels/file_list/_grid_widget.py；
- AssetsManager/dialogs/_share_api.py；
- AssetsManager/dialogs/share_link_dialog.py；
- AssetsManager/dialogs/sharing_settings_dialog.py；
- AssetsManager/widgets/lan_sharing.py；
- AssetsManager/application/bootstrap.py。

这些文件分别涉及 Runtime 生命周期、数据库、服务装配、分享服务、缩略图 IO、Grid 性能遥测、session token 和跨端状态，不属于当前纯 UI 认领范围。

## 3. 修改边界

允许：

- QSS、objectName、视觉 token 的既有管线使用；
- 视觉组件内部的局部状态；
- 不改变公共服务 API 的 view-model 适配；
- 截图、Qt 行为测试和视觉回归测试。

禁止：

- 修改 Runtime、数据库、锁、路径安全和服务生命周期；
- 修改 LAN API、DTO、权限、cookie、WebSocket 和 revision/epoch 语义；
- 修改 FileList scan/reset/loader/cache/queue 行为；
- 为了视觉任务引入 QML、QWebEngine、全量 canvas 或大型动画库；
- 通过删除测试、放宽断言或改测试计数来制造通过。

## 4. 文件冲突处理

如果需要同时修改主会话保留文件和 UI 文件：

1. 先停止实现；
2. 记录需要修改的文件和原因；
3. 将逻辑变更交给主会话；
4. 第二会话只保留可独立合并的视觉补丁。
