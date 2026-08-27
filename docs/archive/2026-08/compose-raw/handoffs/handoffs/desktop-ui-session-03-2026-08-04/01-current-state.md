# 01 — 当前状态与任务判断

## 1. 已完成的基础能力

### 数据安全

主线最近提交已经完成 G6 数据安全基础切片：

- quick_check 与保守孤儿清理；
- 在写锁内重新验证待清理对象，降低并发误删风险；
- 后台完整性检查的单飞、取消和关闭语义；
- RuntimeData 孤儿目录隔离；
- Tags、Notes、URLs JSON 导出；
- SQLite WAL 一致性备份归档；
- manifest、SHA-256、路径安全和数据库校验；
- 关闭 session 后的 staging、按库锁、原子替换和失败回滚恢复。

这些能力的产品入口仍未闭合。第二会话只负责入口的表现层，不能重新实现上述服务逻辑。

主会话已提供 Qt-free LibrarySettingsAdapter（AssetsManager/application/library_settings_adapter.py），并在 MainWindow 打开 SettingsDialog 时注入；第二会话可以通过 SettingsDialog.library_settings_adapter 消费只读 view-model 和受控操作，不得绕过 adapter 直接访问 Runtime。

### Desktop 视觉

桌面端 V1 主要项已经形成基线：

- SVG 语义图标系统；
- primary/secondary/ghost/danger 按钮语义；
- 字阶和 DPI 缩放；
- 主题对比度和 token 管线；
- FileList 卡片排列、hover/zoom 基础动效；
- reduced-motion 降级路径；
- 顶层容器阴影封装。

下一阶段不是换技术栈，也不是迁移 QML，而是继续使用 PySide6 + QSS + 少量自绘完成一致性收口。

## 2. 尚未闭合的 Desktop 产品任务

以下任务属于主线整体计划，但只有其中标注为“表现层”的部分可以交给第二会话：

| 任务 | 主会话 | 第二会话 |
|---|---|---|
| 备份/恢复服务 API | 负责 | 不修改 |
| 设置页恢复入口的服务接入 | 负责 | 不修改服务调用 |
| 恢复对话框布局、状态和视觉 | 审查契约 | 可以负责 |
| 恢复进度、错误和确认的展示组件 | 提供状态模型 | 可以负责 |
| Runtime 重建、session 关闭/恢复 | 负责 | 不修改 |
| FileList reset/刷新/缩略图性能 | 负责 | 不修改 |
| 原生控件视觉覆盖 | 审查回归 | 可以负责 |
| Dialog 标题栏、阴影、淡入 | 审查生命周期 | 可以负责 |
| Desktop/LAN/WebUI 跨端验收 | 负责 | 提供 UI 证据 |

## 3. 当前不应误判的事项

- G6-5 和 G6-1 的基础代码通过 targeted regression，不代表整个数据安全产品阶段已经完成。
- Desktop V1 视觉完成，不代表所有 QTableWidget、QSpinBox、QCheckBox、QToolTip、QMessageBox 和对话框矩阵已经完成截图验收。
- Grid synthetic/offscreen 遥测不等于真实图片 IO 和发布机性能门禁。
- WebUI 的视觉 token 和 Qt 的主题 token 当前保持语义对齐即可，不要求现在引入跨端自动生成器。
- FileList 的 Grid 设计必须保留左对齐、固定卡片宽度、固定缩略图比例和无 reflow 动画。
