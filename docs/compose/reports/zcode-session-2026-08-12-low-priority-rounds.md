# ZCode 会话汇总 — 低危系列滚动完成（2026-08-12）

> **来源会话**：ZCode（deepseek-v4-flash），2026-08-12
> **任务**：按顺序滚动处理全部剩余低危系列（lan-tools → runtime → core-store → file-ops → maintenance → core-db）
> **性质**：每批语义化提交（无远程）
> **验证**：后端 **3361 passed**（xdist ~170s）/ 前端 vitest 591 / ruff 全绿

## 各批次成果

| 批次 | 修复项 | 关键亮点 | 验证 |
|---|---|---|---|
| **lan-tools** | S2-S8、T5-T7、W5-W8、D3-D6（18 项） | tunnel dev 路径 3 级跳转真实 bug、URL 正则锚定、ws 心跳生命周期、dto 树深度截断 | 3145 |
| **runtime** | Bug 3/4/5/6/7/8/10/11/13-18/20-22/24/25（20 项） | **Bug 11 真实死锁**（锁序统一）、跨进程队列冲突只读降级、Windows 路径脱敏、threading.excepthook | 3190 |
| **core-store** | Bug 3-27（21 项） | settings 原子化/atexit、DictCache 锁、TagLibrary 冲突拒绝、**token 级 CHECK 比较**、singleton 装饰器 | 3263 |
| **file-ops** | Bug 9/10/16/22（4 项） | Windows 保留名友好校验、错误分类前缀、备份失败反馈+空间检查 | 3323 |
| **maintenance** | Bug 5/6/9/11-14/16-18（10 项） | quick_check busy 重试、锁外复查+批量删除、vacuum 边界拒绝、完成事件失败路径发布 | 3338 |
| **core-db** | Bug 1/2/5/6/8-16（13 项） | **_WriteGate 双向死锁快速失败**、迁移进程内互斥+重试、离线库 orphan 保护（recent_libraries）、40-bit 碰撞二级探测 | 3361 |

## 过程要点

- **每批 2-6 个修复子代理并行**（文件集互不相交），主代理复核关键契约 + 全量回归 + 语义化提交
- **多次"重跑即绿"瞬时抖动**：并行子代理并发修改共享文件（schema_defs/migration 等）导致瞬时 InvalidSchemaError/ImportError——最终全量均稳定通过
- **关键决策**：D4 契约修正（dto type 拒绝非 dir）、Bug 23 normcase 否决（跨组件键契约）、Bug 21 默认 fire-and-forget（GUI 菜单契约）、quick_check(N) 不缩短扫描实证
- **跨组件协调项记录**：ProjectData._key vs MetadataRepository._path_key 键归一未统一；color_utils/format_utils 陈旧 .pyd 遮蔽源码（cache.pyd 已删）；维护完成事件 UI 订阅待接线；export 恢复路径 DatabaseError 未捕获

## 当前状态

- **全部 P0/P1/P2/LAN 认证面/桌面扫描/前端扫描/开发计划四轮/低危系列** 完成
- 后端 3361 passed、前端 vitest 591 + tsc strict 0 错误、ruff 全绿
- 工作区仅剩 DeepSeek Docs 17 条预存修改未提交（红线不碰）

## 后续候选

- 跨组件协调项（键归一、.pyd、事件订阅、DatabaseError 捕获）
- M4 投递令牌 URL 明文、架构统一（长期）
- 性能轮已完成核心项；可选进一步（get_home 的 assets 投影——依赖资产索引启用）
