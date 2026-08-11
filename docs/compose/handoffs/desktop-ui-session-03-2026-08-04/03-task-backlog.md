# 03 — Desktop UI V2 任务队列

任务顺序为“先建立视觉边界，再处理真实界面，最后截图验收”。

## D0 — 认领与基线确认

- 阅读本交接包以及 DeepSeek Docs 的 05、06、07 文档；
- 检查当前工作树，不触碰 WebUI 未提交改动；
- 确认主会话保留文件没有被修改；
- 运行现有 Desktop UI targeted tests，记录基线；
- 为每个后续任务建立独立提交。

## D1 — 原生控件视觉补全

目标：降低 Qt 原生外观残留。

范围：

- QTableWidget：行高、选中态、无网格线、滚动区域；
- QSpinBox / QDoubleSpinBox：箭头、输入态、禁用态；
- QCheckBox / QRadioButton：指示器和 focus-visible；
- QProgressBar：成功、警告、失败和 indeterminate；
- QToolTip、QMessageBox：主题、按钮层级和边距。

要求：只沿用现有 themes.py 的 token、prop()、scaled_px() 和 scaled_pt() 管线。

## D2 — 对话框视觉统一

目标：让设置、分享、标签和恢复类对话框具有一致的标题栏、层级和反馈。

范围：

- TitleBarWidget 视觉复用；
- 对话框圆角、顶层阴影和内容间距；
- primary/secondary/ghost/danger 按钮语义；
- loading、success、error、retry 状态；
- 150–220ms 的淡入或状态过渡；
- _reduce_motion 时取消非必要动画。

禁止把分享服务调用移入新的 UI 层，也不修改 share_* 的 Runtime 绑定逻辑。

## D3 — G6-1 恢复/备份入口界面壳层

目标：为主会话提供可接入的设置页 UI。

建议拆成：

- LibraryBackupRestoreDialog 或同类纯 UI 对话框；
- 状态：idle、selecting、validating、restoring、success、error、cancelled；
- 用户确认、危险操作提示、进度区、错误指导和恢复完成提示；
- 隔离区列表的展示组件，不实现实际删除或回滚；
- 为服务结果预留明确的 view-model 输入。

服务调用接口和 Runtime 重建由主会话另行提供。若接口尚未冻结，只实现静态 view-model 驱动的 UI 和测试。

## D4 — 空状态与错误状态统一

覆盖：

- 空库；
- 空目录；
- 无搜索结果；
- 缩略图失败；
- 数据库检查失败；
- 恢复失败；
- 无权限或服务不可用。

每个状态必须有明确文案、图标、行动按钮和 keyboard/focus 路径。

## D5 — 视觉回归证据

最小矩阵：

- 亮色和暗色主题；
- 100%、125%、150% DPI 缩放；
- 375px 等效窄窗口、标准桌面窗口和宽屏窗口；
- loading、empty、error、success；
- reduced-motion 开关；
- 关键对话框打开、关闭、焦点和按钮状态。

## 暂缓任务

- FileList 模型、loader、reset、队列和真实图片 IO；
- 大规模 Grid virtualization；
- QML 或 QWebEngine 迁移；
- 商品化、支付、订单和社交功能；
- 未冻结服务契约的编辑、上传和恢复后 Runtime 操作。
