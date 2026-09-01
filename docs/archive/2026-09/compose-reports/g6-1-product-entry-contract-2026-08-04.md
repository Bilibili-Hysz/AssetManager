---
feature: g6-1-product-entry-contract-2026-08-04
status: proposed-contract
scope: Desktop settings presentation boundary for export, backup, validation, restore, and integrity status
---

# G6-1 产品入口服务契约 — 2026-08-04

## 1. 文档定位

本文冻结 Desktop 设置页与主线应用服务之间的最小边界。它不是恢复功能的交付报告，也不代表 Desktop 设置页已经实现。

目标是让纯 UI 层消费稳定的状态模型，不直接操作 Runtime、数据库、文件系统或 session 生命周期。

## 2. 当前可用的服务能力

当前 Runtime 的 LibraryScopedServices 已包含：

- export_service：metadata JSON 导出、RuntimeData 备份、备份校验、关闭 session 后的受控恢复；
- integrity_service：后台 quick_check、保守孤儿清理、last report 和关闭取消；
- session：当前库的 canonical LibrarySession；
- metadata_service：库统计和 metadata 查询；
- maintenance_service：数据库大小、WAL checkpoint 和维护运行状态；

G6-1 的实际服务实现位于 AssetsManager/application/library_export_service.py。G6-5 的完整性实现位于 AssetsManager/application/database_integrity_service.py。

## 3. 操作矩阵

| 操作 | 是否要求 live session | 当前服务边界 | UI 责任 |
|---|---:|---|---|
| 导出 Tags/Notes/URLs JSON | 是 | export_metadata_json() | 选择目标、展示进度/结果/错误 |
| 创建 RuntimeData 备份 | 是 | create_backup() | 选择目标、展示阶段和结果 |
| 校验备份 | 否 | validate_backup() | 展示 manifest、库名、文件数、quick_check 和错误 |
| 恢复备份 | 否，必须关闭目标 session | restore_backup() | 二次确认、危险提示、阶段状态和完成提示 |
| 后台完整性检查 | 是 | integrity_service.schedule() | 展示运行中、上次报告、失败指导 |
| 清理隔离区 | 由后续服务契约决定 | 当前未提供产品入口 | 暂不伪造删除/回滚按钮 |
| 恢复后 Runtime 重建 | 由主窗口/应用层协调 | 当前未并入 UI 服务 | UI 只展示“需要重新打开/正在重建”状态 |

重要边界：在线 Runtime 不允许直接执行恢复。恢复必须先完成 session 关闭、再取得按库锁、验证备份、staging 提取、quick_check、原子替换和必要的 Runtime 重建。

## 4. UI 状态模型

纯 UI 对话框至少支持以下状态，不应直接把服务异常映射为“成功”：

- idle：尚未开始操作；
- selecting：等待用户选择文件或目标目录；
- validating：正在校验备份或目标；
- running：导出、备份、完整性检查或恢复执行中；
- success：服务返回成功结果；
- error：服务失败并提供可读指导；
- cancelled：用户取消或 Runtime 关闭导致任务取消；
- blocked：操作被安全边界拒绝，例如 session 仍在线、库名不匹配或锁不可用。

推荐输入：一个只读 view-model，而不是把 LibraryScopedServices 直接传入纯 UI 组件。

## 5. 进度与反馈规则

- 没有可靠总量时使用 indeterminate progress，不显示伪造百分比。
- 备份可按“准备数据库快照 → 写入归档 → 校验 manifest”展示阶段；阶段百分比由应用层决定。
- 恢复可按“关闭 session → 验证备份 → staging → quick_check → 替换 → Runtime 重建”展示阶段；UI 不自行推进阶段。
- 错误必须区分：输入/路径错误、备份格式错误、库名不匹配、quick_check 失败、锁冲突、session 状态错误、回滚失败。
- 成功状态应包含目标路径、文件数或备份大小等服务返回信息；不得仅显示通用“完成”。

## 6. 第二会话可实现的部分

第二会话可以在不修改服务契约的前提下实现：

- Backup/Restore 对话框布局；
- 危险操作确认和取消；
- validating/running/success/error/blocked 状态；
- 进度区和错误指导；
- 隔离区列表的只读展示；
- Qt 行为测试和截图证据。

第二会话不得：

- 直接关闭或重新打开 LibrarySession；
- 直接调用数据库连接、VACUUM、quick_check 或文件移动；
- 自行实现恢复回滚；
- 为缺少进度回调的操作伪造准确百分比；
- 修改 application/、core/、window.py 或 FileList 性能链路。

## 7. 主会话后续接入任务

1. 已在 AssetsManager/application/library_settings_adapter.py 提供 Qt-free adapter，将当前 session、服务结果和生命周期状态转换为只读 view-model。
2. MainWindow 打开 SettingsDialog 时注入 adapter；SettingsDialog 只保存 adapter，不直接操作 Runtime。
3. 继续明确设置页打开时的 canonical session 获取方式，避免使用陈旧 Runtime snapshot。
4. 明确异步任务取消、切库和退出时的 UI 状态转换。
5. G3-9 已接入 Runtime；设置页仍需绑定维护状态和用户反馈。
6. 完成真实崩溃恢复演练后，再把“恢复完成”升级为发布门禁证据。

## 8. 验收要求

- 纯 UI 测试覆盖 idle/running/success/error/blocked/cancelled；
- 在线 session 执行恢复时必须显示 blocked，而不是触发服务调用；
- quick_check 失败、备份校验失败和回滚失败不能被吞掉；
- 亮色/暗色、DPI 缩放、keyboard focus 和 reduced-motion 均有证据；
- 服务层、Runtime 生命周期和真实文件操作由主会话测试，不由截图测试替代。

当前状态：主会话已提供 Qt-free adapter 和 SettingsDialog 注入点；第二会话可以据此制作纯表现层，但设置页控件、异步 worker 和截图验收仍未完成。
