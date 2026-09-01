# Desktop UI Session 03 — 交接包

> 日期：2026-08-04
> 目标：为第二会话提供一个**受限的 Desktop UI 纯表现层任务包**。
> 重要边界：本交接包不把整个 Desktop 前端交给第二会话。

## 1. 交接结论

第二会话继续负责 WebUI 主线，同时可以认领本包中的 Qt 纯表现层任务：

- 视觉统一；
- 原生控件样式覆盖；
- 对话框外观和状态反馈；
- 空状态、错误状态、加载状态；
- 视觉回归和截图测试；
- 备份/恢复入口的界面壳层。

主会话继续负责：

- Runtime、数据库、锁和路径安全；
- 服务装配、生命周期和 session 切换；
- 备份/恢复服务 API 及错误语义；
- FileList 模型、扫描、缩略图、刷新和性能链路；
- Desktop/LAN/WebUI 跨端契约和最终验收。

## 2. 当前基线

- G6-5：数据库 quick_check、保守孤儿清理、并发重新验证、关闭竞态和单飞任务已完成第一切片。
- G6-1：metadata 导出、RuntimeData 备份校验、归档和关闭 session 后的受控恢复 API 已完成第一切片。
- G6-1 产品层仍未完成：Desktop 设置页入口、确认、进度、错误反馈、恢复后 Runtime 重建和隔离区管理。
- Desktop V1 视觉主要项已完成：图标、按钮变体、字阶/缩放、主题对比度、FileList 基础卡片阵列和动效。
- Desktop 真实性能验收仍未完成：真实图片 IO、reset 最小化、发布机复测和目录大小首屏门禁。
- 当前工作树中的未提交改动属于 WebUI 第二会话和已有 WebUI handoff，必须保留。

## 3. 阅读顺序

1. [01-current-state.md](./01-current-state.md)
2. [02-scope-and-file-ownership.md](./02-scope-and-file-ownership.md)
3. [03-task-backlog.md](./03-task-backlog.md)
4. [04-verification-and-acceptance.md](./04-verification-and-acceptance.md)
5. [05-start-prompt.md](./05-start-prompt.md)

## 4. 相关主线文档

- [DeepSeek Docs/施行路线图.md](../../../../../../baseline-2026-08-01/%E6%96%BD%E8%A1%8C%E8%B7%AF%E7%BA%BF%E5%9B%BE.md)
- [DeepSeek Docs/未来方向/05-桌面端UI视觉改进规划.md](../../../../../../baseline-2026-08-01/%E6%9C%AA%E6%9D%A5%E6%96%B9%E5%90%91/05-%E6%A1%8C%E9%9D%A2%E7%AB%AFUI%E8%A7%86%E8%A7%89%E6%94%B9%E8%BF%9B%E8%A7%84%E5%88%92.md)
- [DeepSeek Docs/未来方向/07-桌面端性能优化计划.md](../../../../../../baseline-2026-08-01/%E6%9C%AA%E6%9D%A5%E6%96%B9%E5%90%91/07-%E6%A1%8C%E9%9D%A2%E7%AB%AF%E6%80%A7%E8%83%BD%E4%BC%98%E5%8C%96%E8%AE%A1%E5%88%92.md)
- [G6-5 report](../../reports/g6-5-database-integrity-2026-08-03.md)
- [G6-1 restore report](../../reports/g6-1-restore-2026-08-04.md)
- [WebUI Session 02 handoff](../webui-session-02-2026-08-03/README.md)

## 5. 合并规则

- 每个 UI 子任务独立提交。
- 修改前先确认文件是否已被主会话或 WebUI 会话占用。
- 不回滚、覆盖或重排其他会话的未提交改动。
- 如果需要修改服务调用、Runtime 状态或共享协议，暂停并回报主会话。
- “视觉完成”必须同时有行为测试、截图或明确的环境阻塞说明。
