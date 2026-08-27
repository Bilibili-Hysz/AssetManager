# AssetManager 完整审查文档集 — 索引（00）

> **索引规则**：`docs/full-review/` 是带日期和基线的审计快照集合，不是当前工作区的可执行权威。
> **当前事实来源**：代码、测试与 CI 配置；运行结果必须链接到带 commit、命令、平台和 artifact 的证据。
> **2026-08-11 快照**：`master @ fbf3403` + 当时工作区 529 条未提交变更；其 pytest/ruff 结果只适用于该快照。
> **2026-08-20 证据快照**：`feat/quality-audit-2026-08-17 @ 5fbf93059e2a2926ffb6b4fb940981736fd7050f`，dirty worktree，12 个 tracked 和 4 个输入审计报告；详情见 `audit-manifest-2026-08-20.json`。

---

## 1. 文档集目标

由浅入深、由架构到模块、由后端到前端、由信号到行为、由文档到代码地**完全审查**该项目，并将：
- 软件构造详情
- 数据流
- 事件/信号系统
- 审查结果与已知风险

汇聚为一份系统性文档集，作为未来任务的"工作区实况索引"。

## 2. 审查方法

| 步骤 | 方式 |
|---|---|
| 文档资产盘点 | 读取 README（674 行）、docs/（architecture/development/testing/migrations/lan-security/adr）、docs/compose/（handoffs 3 + plans 54 + reports 92 + specs 25）、DeepSeek Docs/（17 项） |
| 分域代码审查 | 6 个并行只读审查代理，逐文件精读 + grep 交叉验证（详见各章"审查范围"） |
| 行为链路验证 | 关键链路（开库/浏览/搜索/分享/结账/备份）以文件:行号锚定 |
| 基线实测 | 全量 pytest + ruff 现场复跑（见 07） |

## 3. 文档清单

| 文档 | 内容 | 对应目标 |
|---|---|---|

### 3.1 基础审计文档（固定编号）

| 文档 | 内容 | 对应目标 |
|---|---|---|
| [01-construction.md](01-construction.md) | 软件构造详情：三端形态、技术栈、六层架构、依赖装配、核心机制、设计模式、存储体系、构建打包 | 软件构造详情 |
| [02-module-map.md](02-module-map.md) | 模块地图：后端 33+8+15+39+LAN 全部模块（职责/关键类/签名/规模）、前端 src 地图、服务分类 | 由架构到模块 |
| [03-data-flow.md](03-data-flow.md) | 数据流文档：6 条端到端链路（触发→服务→仓库→事件→投影→前端刷新） | 数据流 |
| [04-events-signals.md](04-events-signals.md) | 信号/事件系统：EventBus、19 领域事件清单、投影域映射、WebSocket 协议、前端恢复、桌面 Qt 信号 | 由信号到行为 |
| [05-frontend.md](05-frontend.md) | 前端审查：React 架构、API 客户端、状态管理、Hooks、路由、组件地图、实时协议、测试 | 前端 |
| [06-audit-results.md](06-audit-results.md) | 审查结果：本轮发现、文档过时清单（逐条差异）、已知风险、技术债、工程红线 | 审查结果 |
| [07-verification.md](07-verification.md) | 验证基线：测试体系、实测结果、CI、构建打包、质量门 | 验证 |
| [08-webui-architecture-dataflow.md](08-webui-architecture-dataflow.md) | WebUI 数据流与设计架构专项：请求管线、状态模型、实时失效链路、契约一致性、问题清单（2026-08-12 补充） | 前端架构/数据流 |
| [10-native-acceleration-atlas.md](10-native-acceleration-atlas.md) | 可固定加速图谱（2026-08-17）：按任务拆墙钟/CPU，T0–T3 准入函数清单，禁止把 `core/` 整层 C 化 | 原生加速合同 |
| [11-plugin-api-v2-handover.md](11-plugin-api-v2-handover.md) | Plugin API v2 交接快照 | 插件平台 |

### 3.2 批次证据索引（按日期分组；每份 dated 报告与其配对 manifest 相邻）

> **统计总览**：共 9 个日期分桶；83 份 dated 证据报告、76 份机器可读 manifest。manifest 制度自 2026-08-21 起完整执行；早期 7 份报告未生成配套 manifest。校验入口：`python scripts/check_audit_reports.py`。

#### 2026-08-15（1 报告 / 0 manifest）

| [09-deep-audit-2026-08-15.md](09-deep-audit-2026-08-15.md) | 深度审查轮（2026-08-15）：4 域并行只读审查（Gallery/数据层、LAN 并发安全、桌面线程生命周期、前端状态清理）——5 HIGH / 19 MEDIUM / 22 LOW，含已验证安全清单与修复批次建议 | 深度审查 |

#### 2026-08-17（2 报告 / 0 manifest）

| [12-quality-audit-2026-08-17.md](12-quality-audit-2026-08-17.md) | 2026-08-17 质量审计快照 | 质量治理 |
| [13-architecture-debt-quantified-2026-08-17.md](13-architecture-debt-quantified-2026-08-17.md) | 2026-08-17 架构债量化快照 | 架构治理 |

#### 2026-08-20（5 报告 / 1 manifest）

| [full-scan-2026-08-20.md](full-scan-2026-08-20.md) | 2026-08-20 分模块全量静态扫描 | 发现集 |
| [cross-module-flow-api-audit-2026-08-20.md](cross-module-flow-api-audit-2026-08-20.md) | 2026-08-20 跨模块信息流、数据流和 API 审计 | 发现集 |
| [performance-timing-audit-2026-08-20.md](performance-timing-audit-2026-08-20.md) | 2026-08-20 性能与时序静态审计 | 发现集 |
| [code-quality-architecture-worktree-dependency-audit-2026-08-20.md](code-quality-architecture-worktree-dependency-audit-2026-08-20.md) | 2026-08-20 深度质量、架构、工作树与依赖治理审计 | 发现集 |
| [evidence-convergence-2026-08-20.md](evidence-convergence-2026-08-20.md) | 2026-08-20 证据收敛、勘误与修复排期 | canonical register |
| [audit-manifest-2026-08-20.json](audit-manifest-2026-08-20.json) | 2026-08-20 输入摘要、基线指纹与 finding manifest | 机器可读证据 |

#### 2026-08-21（17 报告 / 17 manifest）

| [desktop-async-implementation-evidence-2026-08-21.md](desktop-async-implementation-evidence-2026-08-21.md) | Desktop async lifecycle 的实施、blocked-worker teardown 证据与定向测试结果 | 动态实施证据 |
| [audit-manifest-2026-08-21.json](audit-manifest-2026-08-21.json) | Desktop async 实施批次的 worktree 指纹、输入摘要与 finding 状态 | 机器可读实施证据 |
| [s1-s5-s2-min-implementation-evidence-2026-08-21.md](s1-s5-s2-min-implementation-evidence-2026-08-21.md) | S1 分享预览、S5 WebUI 身份/缓存、S2-min 认证 offload 的实施与动态验证 | 动态实施证据 |
| [audit-manifest-s1-s5-s2-min-2026-08-21.json](audit-manifest-s1-s5-s2-min-2026-08-21.json) | 当前 S1/S5/S2-min 批次的 worktree 指纹、输入摘要与 finding 状态 | 机器可读实施证据 |
| [c1-min-contract-implementation-evidence-2026-08-21.md](c1-min-contract-implementation-evidence-2026-08-21.md) | C1 Gallery、Activity、HTTP/TypeScript error envelope 契约实施与验证 | 动态实施证据 |
| [audit-manifest-c1-min-2026-08-21.json](audit-manifest-c1-min-2026-08-21.json) | C1-min 批次的 worktree 指纹、输入摘要与 finding 状态 | 机器可读实施证据 |
| [c2-c3-min-session-transaction-evidence-2026-08-21.md](c2-c3-min-session-transaction-evidence-2026-08-21.md) | C2 Favorite session binding 与 C3 Metadata transaction/event guard 实施证据 | 动态实施证据 |
| [audit-manifest-c2-c3-min-2026-08-21.json](audit-manifest-c2-c3-min-2026-08-21.json) | C2/C3-min 批次的 worktree 指纹、输入摘要与 finding 状态 | 机器可读实施证据 |
| [c4-min-file-operation-reconciliation-evidence-2026-08-21.md](c4-min-file-operation-reconciliation-evidence-2026-08-21.md) | C4 文件操作删除/恢复失败可观测性与 asset-index reconciliation scope 实施证据 | 动态实施证据 |
| [audit-manifest-c4-min-2026-08-21.json](audit-manifest-c4-min-2026-08-21.json) | C4-min 批次的 worktree 指纹、输入摘要与 finding 状态 | 机器可读实施证据 |
| [c5-min-session-lease-hard-gate-evidence-2026-08-21.md](c5-min-session-lease-hard-gate-evidence-2026-08-21.md) | C5 session lease timeout 与 canonical owner teardown hard gate 实施证据 | 动态实施证据 |
| [audit-manifest-c5-min-2026-08-21.json](audit-manifest-c5-min-2026-08-21.json) | C5-min 批次的 worktree 指纹、输入摘要与 finding 状态 | 机器可读实施证据 |
| [c4-b-move-metadata-savepoint-evidence-2026-08-21.md](c4-b-move-metadata-savepoint-evidence-2026-08-21.md) | C4-B move metadata savepoint、thumbnail 失败传播与移动失败契约实施证据 | 动态实施证据 |
| [audit-manifest-c4-b-move-metadata-savepoint-2026-08-21.json](audit-manifest-c4-b-move-metadata-savepoint-2026-08-21.json) | C4-B 批次的 worktree 指纹、输入摘要与 finding 状态 | 机器可读实施证据 |
| [c6-min-durable-filesystem-projection-repair-evidence-2026-08-21.md](c6-min-durable-filesystem-projection-repair-evidence-2026-08-21.md) | C6-min move/delete durable filesystem projection repair 实施与验证 | 动态实施证据 |
| [audit-manifest-c6-min-durable-filesystem-projection-repair-2026-08-21.json](audit-manifest-c6-min-durable-filesystem-projection-repair-2026-08-21.json) | C6-min 批次的 worktree 指纹、输入摘要与 finding 状态 | 机器可读实施证据 |
| [c6-b-restore-projection-repair-evidence-2026-08-21.md](c6-b-restore-projection-repair-evidence-2026-08-21.md) | C6-B restore projection durable repair 实施与验证 | 动态实施证据 |
| [audit-manifest-c6-b-restore-projection-repair-2026-08-21.json](audit-manifest-c6-b-restore-projection-repair-2026-08-21.json) | C6-B 批次的 worktree 指纹、输入摘要与 finding 状态 | 机器可读实施证据 |
| [c7-min-watcher-durable-rescan-evidence-2026-08-21.md](c7-min-watcher-durable-rescan-evidence-2026-08-21.md) | C7-min watcher durable rescan producer 与 stop/join 生命周期实施证据 | 动态实施证据 |
| [audit-manifest-c7-min-watcher-durable-rescan-2026-08-21.json](audit-manifest-c7-min-watcher-durable-rescan-2026-08-21.json) | C7-min 批次的 worktree 指纹、输入摘要与 finding 状态 | 机器可读实施证据 |
| [c8-min-import-partial-contract-evidence-2026-08-21.md](c8-min-import-partial-contract-evidence-2026-08-21.md) | C8-min ImportService session lease、partial/degraded 结果与索引补偿实施证据 | 动态实施证据 |
| [audit-manifest-c8-min-import-partial-contract-2026-08-21.json](audit-manifest-c8-min-import-partial-contract-2026-08-21.json) | C8-min 批次的 worktree 指纹、输入摘要与 finding 状态 | 机器可读实施证据 |
| [c9-min-import-ui-cancel-pool-lifecycle-evidence-2026-08-21.md](c9-min-import-ui-cancel-pool-lifecycle-evidence-2026-08-21.md) | C9-min Import UI cancel、dialog close race 与后台池生命周期实施证据 | 动态实施证据 |
| [audit-manifest-c9-min-import-ui-cancel-pool-lifecycle-2026-08-21.json](audit-manifest-c9-min-import-ui-cancel-pool-lifecycle-2026-08-21.json) | C9-min 批次的 worktree 指纹、输入摘要与 finding 状态 | 机器可读实施证据 |
| [c10-min-import-durable-intent-recovery-evidence-2026-08-21.md](c10-min-import-durable-intent-recovery-evidence-2026-08-21.md) | C10-min Import durable intent/manifest 与 runtime restart recovery 实施证据 | 动态实施证据 |
| [audit-manifest-c10-min-import-durable-intent-recovery-2026-08-21.json](audit-manifest-c10-min-import-durable-intent-recovery-2026-08-21.json) | C10-min 批次的 worktree 指纹、输入摘要与 finding 状态 | 机器可读实施证据 |
| [c6-c10-convergence-2026-08-21.md](c6-c10-convergence-2026-08-21.md) | C6-C10 dated 收敛关系、残余限制与本批证据边界 | 后续收敛快照 |
| [audit-manifest-c6-c10-convergence-2026-08-21.json](audit-manifest-c6-c10-convergence-2026-08-21.json) | C6-C10 收敛快照的 baseline、输入摘要、关系与验证证据 | 机器可读收敛证据 |
| [c6-c10-regression-evidence-2026-08-21.md](c6-c10-regression-evidence-2026-08-21.md) | C6-C10 并行 focused 回归、修复后全量 Python 与静态门禁结果 | 动态回归证据 |
| [audit-manifest-c6-c10-regression-evidence-2026-08-21.json](audit-manifest-c6-c10-regression-evidence-2026-08-21.json) | 并行回归快照的 baseline、命令摘要、平台 skip 与 finding 状态 | 机器可读回归证据 |
| [c6-c10-hardening-evidence-2026-08-21.md](c6-c10-hardening-evidence-2026-08-21.md) | Batch download quota、WebSocket offload hardening 与修复后 focused/full 回归 | 动态 hardening 证据 |
| [audit-manifest-c6-c10-hardening-evidence-2026-08-21.json](audit-manifest-c6-c10-hardening-evidence-2026-08-21.json) | Hardening 快照 baseline、命令摘要、平台 skip 与 finding 状态 | 机器可读 hardening 证据 |
| [c6-c10-security-boundary-hardening-2026-08-21.md](c6-c10-security-boundary-hardening-2026-08-21.md) | 项目 containment、thumbnail、POSIX lock、release provenance hardening 与全量回归 | 动态安全边界证据 |
| [audit-manifest-c6-c10-security-boundary-hardening-2026-08-21.json](audit-manifest-c6-c10-security-boundary-hardening-2026-08-21.json) | 安全边界 hardening 快照 baseline、命令摘要、平台限制与 finding 状态 | 机器可读安全证据 |

#### 2026-08-22（11 报告 / 11 manifest）

| [auth-plugin-websocket-implementation-evidence-2026-08-22.md](auth-plugin-websocket-implementation-evidence-2026-08-22.md) | Auth、Plugin owner/lifecycle、WebSocket token revocation 实施与动态验证 | 动态实施证据 |
| [audit-manifest-auth-plugin-websocket-implementation-evidence-2026-08-22.json](audit-manifest-auth-plugin-websocket-implementation-evidence-2026-08-22.json) | Auth/Plugin/WebSocket 批次 baseline、输入摘要、命令 artifact 与 finding 状态 | 机器可读实施证据 |
| [auth-revocation-concurrency-hardening-evidence-2026-08-22.md](auth-revocation-concurrency-hardening-evidence-2026-08-22.md) | Token revocation registry 并发、跨进程 miss、事务与 logout hardening 证据 | 动态安全 hardening 证据 |
| [audit-manifest-auth-revocation-concurrency-hardening-evidence-2026-08-22.json](audit-manifest-auth-revocation-concurrency-hardening-evidence-2026-08-22.json) | Revocation hardening baseline、命令 artifact、平台限制与 finding 状态 | 机器可读安全证据 |
| [plugin-lifecycle-category-refresh-evidence-2026-08-22.md](plugin-lifecycle-category-refresh-evidence-2026-08-22.md) | Plugin lifecycle 并发、测试持久化隔离与已打开 FileListPanel 动态分类刷新 | 动态实施证据 |
| [audit-manifest-plugin-lifecycle-category-refresh-evidence-2026-08-22.json](audit-manifest-plugin-lifecycle-category-refresh-evidence-2026-08-22.json) | Plugin/category 批次 baseline、命令 artifact、平台限制与 finding 状态 | 机器可读实施证据 |
| [final-open-toctou-hardening-evidence-2026-08-22.md](final-open-toctou-hardening-evidence-2026-08-22.md) | LAN final-open、POSIX descriptor traversal 与 ZIP source byte acquisition hardening | 动态安全证据 |
| [audit-manifest-final-open-toctou-hardening-evidence-2026-08-22.json](audit-manifest-final-open-toctou-hardening-evidence-2026-08-22.json) | Final-open 批次 baseline、命令 artifact、平台限制与 finding 状态 | 机器可读安全证据 |
| [thumbnail-processing-final-open-evidence-2026-08-22.md](thumbnail-processing-final-open-evidence-2026-08-22.md) | Thumbnail Pillow bytes snapshot、视频临时快照 ffmpeg 与 LAN route 贯通 | 动态安全证据 |
| [audit-manifest-thumbnail-processing-final-open-evidence-2026-08-22.json](audit-manifest-thumbnail-processing-final-open-evidence-2026-08-22.json) | Thumbnail processing 批次 baseline、命令 artifact、平台限制与 finding 状态 | 机器可读安全证据 |
| [desktop-final-open-migration-evidence-2026-08-22.md](desktop-final-open-migration-evidence-2026-08-22.md) | Desktop FileList、ImageViewer、InfoPanel 的 final-open snapshot 迁移与动态回归 | 动态桌面安全证据 |
| [audit-manifest-desktop-final-open-migration-evidence-2026-08-22.json](audit-manifest-desktop-final-open-migration-evidence-2026-08-22.json) | Desktop final-open 迁移 baseline、命令 artifact、平台限制与 finding 状态 | 机器可读桌面安全证据 |
| [thumbnail-key-contract-evidence-2026-08-22.md](thumbnail-key-contract-evidence-2026-08-22.md) | Thumbnail identity-aware key、legacy cache fallback 与 Desktop/LAN/Project 消费者收敛 | 动态缓存安全证据 |
| [audit-manifest-thumbnail-key-contract-evidence-2026-08-22.json](audit-manifest-thumbnail-key-contract-evidence-2026-08-22.json) | Thumbnail key contract baseline、命令 artifact、平台限制与 finding 状态 | 机器可读缓存安全证据 |
| [thumbnail-cache-metadata-eviction-evidence-2026-08-22.md](thumbnail-cache-metadata-eviction-evidence-2026-08-22.md) | Thumbnail metadata v32、webp/jpg/tmp 生命周期、完整 metadata 与单进程磁盘 eviction | 动态缓存生命周期证据 |
| [audit-manifest-thumbnail-cache-metadata-eviction-evidence-2026-08-22.json](audit-manifest-thumbnail-cache-metadata-eviction-evidence-2026-08-22.json) | Thumbnail metadata/eviction baseline、命令 artifact、平台限制与 finding 状态 | 机器可读缓存生命周期证据 |
| [thumbnail-video-lifecycle-hardening-evidence-2026-08-22.md](thumbnail-video-lifecycle-hardening-evidence-2026-08-22.md) | Video JPG metadata registration、clear epoch、artifact cleanup 与 transaction hardening | 动态缓存生命周期 follow-up 证据 |
| [audit-manifest-thumbnail-video-lifecycle-hardening-evidence-2026-08-22.json](audit-manifest-thumbnail-video-lifecycle-hardening-evidence-2026-08-22.json) | Video lifecycle follow-up baseline、命令 artifact、平台限制与 finding 状态 | 机器可读 follow-up 证据 |
| [thumbnail-cross-process-ownership-evidence-2026-08-22.md](thumbnail-cross-process-ownership-evidence-2026-08-22.md) | Cross-process cache owner lease、conditional delete、SQLite busy policy 与 subprocess recovery | 动态缓存 ownership 证据 |
| [audit-manifest-thumbnail-cross-process-ownership-evidence-2026-08-22.json](audit-manifest-thumbnail-cross-process-ownership-evidence-2026-08-22.json) | Cross-process thumbnail ownership baseline、命令 artifact、平台限制与 finding 状态 | 机器可读 ownership 证据 |
| [thumbnail-cross-process-lock-order-followup-evidence-2026-08-22.md](thumbnail-cross-process-lock-order-followup-evidence-2026-08-22.md) | Final cache-owner-before-database lock-order correction 与回归验证 | 动态 ownership follow-up 证据 |
| [audit-manifest-thumbnail-cross-process-lock-order-followup-evidence-2026-08-22.json](audit-manifest-thumbnail-cross-process-lock-order-followup-evidence-2026-08-22.json) | Lock-order follow-up baseline、命令 artifact、平台限制与 finding 状态 | 机器可读 follow-up 证据 |

#### 2026-08-23（18 报告 / 18 manifest）

| [thumbnail-desktop-profile-admission-evidence-2026-08-23.md](thumbnail-desktop-profile-admission-evidence-2026-08-23.md) | Desktop WebP profile-aware cache admission、metadata baked_size 与 header fallback | 动态 Desktop 缓存证据 |
| [audit-manifest-thumbnail-desktop-profile-admission-evidence-2026-08-23.json](audit-manifest-thumbnail-desktop-profile-admission-evidence-2026-08-23.json) | Desktop profile admission baseline、命令 artifact、平台限制与 finding 状态 | 机器可读 Desktop 缓存证据 |
| [thumbnail-shared-lan-profile-admission-evidence-2026-08-23.md](thumbnail-shared-lan-profile-admission-evidence-2026-08-23.md) | Shared/LAN persistent WebP cache 的 bounded snapshot、格式与尺寸 admission | 动态 shared/LAN 缓存证据 |
| [audit-manifest-thumbnail-shared-lan-profile-admission-evidence-2026-08-23.json](audit-manifest-thumbnail-shared-lan-profile-admission-evidence-2026-08-23.json) | Shared/LAN cache admission baseline、命令 artifact、平台限制与 finding 状态 | 机器可读 shared/LAN 缓存证据 |
| [thumbnail-blur-cache-privacy-evidence-2026-08-23.md](thumbnail-blur-cache-privacy-evidence-2026-08-23.md) | Blurred thumbnail 的 private/no-store HTTP cache policy 与 LAN 回归 | 动态 LAN 隐私证据 |
| [audit-manifest-thumbnail-blur-cache-privacy-evidence-2026-08-23.json](audit-manifest-thumbnail-blur-cache-privacy-evidence-2026-08-23.json) | Blurred thumbnail privacy baseline、命令 artifact、平台限制与 finding 状态 | 机器可读 LAN 隐私证据 |
| [thumbnail-batch-response-privacy-evidence-2026-08-23.md](thumbnail-batch-response-privacy-evidence-2026-08-23.md) | Batch thumbnail base64 response 的 private/no-store HTTP cache policy 与客户端回归 | 动态 LAN batch 隐私证据 |
| [audit-manifest-thumbnail-batch-response-privacy-evidence-2026-08-23.json](audit-manifest-thumbnail-batch-response-privacy-evidence-2026-08-23.json) | Batch response privacy baseline、命令 artifact、平台限制与 finding 状态 | 机器可读 LAN batch 隐私证据 |
| [thumbnail-webui-namespace-isolation-evidence-2026-08-23.md](thumbnail-webui-namespace-isolation-evidence-2026-08-23.md) | Runtime-scoped WebUI thumbnail memory/sessionStorage namespace isolation 与客户端回归 | 动态 WebUI 缓存隔离证据 |
| [audit-manifest-thumbnail-webui-namespace-isolation-evidence-2026-08-23.json](audit-manifest-thumbnail-webui-namespace-isolation-evidence-2026-08-23.json) | WebUI namespace isolation baseline、命令 artifact、平台限制与 finding 状态 | 机器可读 WebUI 缓存隔离证据 |
| [thumbnail-webp-v3-profile-key-evidence-2026-08-23.md](thumbnail-webp-v3-profile-key-evidence-2026-08-23.md) | Persistent WebP v3 profile-aware key、v33 metadata、Desktop/LAN 双读新写与 path collision 回归 | 动态 persistent 缓存证据 |
| [audit-manifest-thumbnail-webp-v3-profile-key-evidence-2026-08-23.json](audit-manifest-thumbnail-webp-v3-profile-key-evidence-2026-08-23.json) | WebP v3 profile key baseline、命令 artifact、平台限制与 finding 状态 | 机器可读 persistent 缓存证据 |
| [thumbnail-video-jpg-legacy-dual-read-evidence-2026-08-23.md](thumbnail-video-jpg-legacy-dual-read-evidence-2026-08-23.md) | Shared/LAN 视频 JPG v2→legacy 双读、v2 优先级与提取回归 | 动态视频缓存兼容证据 |
| [audit-manifest-thumbnail-video-jpg-legacy-dual-read-evidence-2026-08-23.json](audit-manifest-thumbnail-video-jpg-legacy-dual-read-evidence-2026-08-23.json) | 视频 JPG 双读 baseline、命令 artifact、平台限制与 finding 状态 | 机器可读视频缓存证据 |
| [project-service-webp-preview-convergence-evidence-2026-08-23.md](project-service-webp-preview-convergence-evidence-2026-08-23.md) | ProjectService WebP profile/identity/key 校验、稳定选择与 JPG 排除 | 动态项目预览收敛证据 |
| [audit-manifest-project-service-webp-preview-convergence-evidence-2026-08-23.json](audit-manifest-project-service-webp-preview-convergence-evidence-2026-08-23.json) | ProjectService preview convergence baseline、命令 artifact、平台限制与 finding 状态 | 机器可读项目预览证据 |
| [project-service-webp-artifact-admission-evidence-2026-08-23.md](project-service-webp-artifact-admission-evidence-2026-08-23.md) | ProjectService 复用统一 WebP bytes admission、坏/过小 artifact cache-miss 与非破坏回归 | 动态 WebP admission 证据 |
| [audit-manifest-project-service-webp-artifact-admission-evidence-2026-08-23.json](audit-manifest-project-service-webp-artifact-admission-evidence-2026-08-23.json) | WebP artifact admission baseline、命令 artifact、平台限制与 finding 状态 | 机器可读 WebP admission 证据 |
| [thumbnail-path-migration-concurrency-evidence-2026-08-23.md](thumbnail-path-migration-concurrency-evidence-2026-08-23.md) | Thumbnail path migration 生产 caller owner-lock 收敛、collision/rollback/cleanup 回归 | 动态缓存迁移证据 |
| [audit-manifest-thumbnail-path-migration-concurrency-evidence-2026-08-23.json](audit-manifest-thumbnail-path-migration-concurrency-evidence-2026-08-23.json) | Thumbnail migration lock-order baseline、命令 artifact、平台限制与 finding 状态 | 机器可读迁移证据 |
| [thumbnail-browser-intermediary-e2e-evidence-2026-08-23.md](thumbnail-browser-intermediary-e2e-evidence-2026-08-23.md) | 真实 Chromium + loopback LAN + controlled intermediary 的 namespace/privacy/cache 行为验证 | 动态浏览器证据 |
| [audit-manifest-thumbnail-browser-intermediary-e2e-evidence-2026-08-23.json](audit-manifest-thumbnail-browser-intermediary-e2e-evidence-2026-08-23.json) | Browser/intermediary E2E baseline、命令 artifact、平台限制与 finding 状态 | 机器可读浏览器证据 |
| [import-manifest-terminal-recovery-evidence-2026-08-23.md](import-manifest-terminal-recovery-evidence-2026-08-23.md) | Import manifest terminal state、recovery 幂等、取消 rescan 与 update failure 隔离 | 动态 mutation/recovery 证据 |
| [audit-manifest-import-manifest-terminal-recovery-evidence-2026-08-23.json](audit-manifest-import-manifest-terminal-recovery-evidence-2026-08-23.json) | Import recovery baseline、命令 artifact、平台限制与 finding 状态 | 机器可读 mutation/recovery 证据 |
| [import-subprocess-termination-evidence-2026-08-23.md](import-subprocess-termination-evidence-2026-08-23.md) | Import 子进程终止 checkpoint、重启 recovery、no-replay 与 late-cancel rescan 验证 | 动态 mutation/recovery follow-up 证据 |
| [audit-manifest-import-subprocess-termination-evidence-2026-08-23.json](audit-manifest-import-subprocess-termination-evidence-2026-08-23.json) | Import subprocess follow-up baseline、命令 artifact、平台限制与 finding 状态 | 机器可读 mutation/recovery follow-up 证据 |
| [import-manifest-recovery-robustness-evidence-2026-08-23.md](import-manifest-recovery-robustness-evidence-2026-08-23.md) | Import manifest 坏 payload 隔离、双连接 CAS、item transition 与 finish retry 验证 | 动态 mutation/recovery robustness 证据 |
| [audit-manifest-import-manifest-recovery-robustness-evidence-2026-08-23.json](audit-manifest-import-manifest-recovery-robustness-evidence-2026-08-23.json) | Import manifest robustness baseline、命令 artifact、平台限制与 finding 状态 | 机器可读 mutation/recovery robustness 证据 |
| [import-manifest-recovery-claim-lease-evidence-2026-08-23.md](import-manifest-recovery-claim-lease-evidence-2026-08-23.md) | Import manifest v34 claim/lease、token CAS、lease takeover 与双进程 winner 验证 | 动态 mutation/recovery ownership 证据 |
| [audit-manifest-import-manifest-recovery-claim-lease-evidence-2026-08-23.json](audit-manifest-import-manifest-recovery-claim-lease-evidence-2026-08-23.json) | Import recovery claim/lease baseline、命令 artifact、平台限制与 finding 状态 | 机器可读 mutation/recovery ownership 证据 |
| [import-no-overwrite-atomic-copy-evidence-2026-08-23.md](import-no-overwrite-atomic-copy-evidence-2026-08-23.md) | ImportService 独占创建 no-overwrite、竞争者保护、身份感知清理与 focused/full 验证 | 动态文件系统边界证据 |
| [audit-manifest-import-no-overwrite-atomic-copy-evidence-2026-08-23.json](audit-manifest-import-no-overwrite-atomic-copy-evidence-2026-08-23.json) | ImportService no-overwrite 批次 baseline、命令 artifact、平台限制与 finding 状态 | 机器可读文件系统边界证据 |
| [batch-move-transaction-boundary-evidence-2026-08-23.md](batch-move-transaction-boundary-evidence-2026-08-23.md) | Batch move caller outer transaction 前置拒绝、共享 worker fixture 稳定化与全量回归 | 动态事务边界证据 |
| [audit-manifest-batch-move-transaction-boundary-evidence-2026-08-23.json](audit-manifest-batch-move-transaction-boundary-evidence-2026-08-23.json) | Batch move 事务 admission baseline、命令 artifact、平台限制与 finding 状态 | 机器可读事务边界证据 |
| [import-ancestor-link-admission-evidence-2026-08-23.md](import-ancestor-link-admission-evidence-2026-08-23.md) | ImportService destination 祖先 symlink/junction/reparse admission、规划后复核与回归 | 动态文件系统边界证据 |
| [audit-manifest-import-ancestor-link-admission-evidence-2026-08-23.json](audit-manifest-import-ancestor-link-admission-evidence-2026-08-23.json) | ImportService ancestor-link baseline、命令 artifact、平台限制与 finding 状态 | 机器可读文件系统边界证据 |

#### 2026-08-25（8 报告 / 8 manifest）

| [import-copy-replay-idempotency-evidence-2026-08-25.md](import-copy-replay-idempotency-evidence-2026-08-25.md) | Import manifest v2 stable copy identity、source fingerprint、显式 replay 与 conflict/adoption 回归 | 动态导入幂等证据 |
| [audit-manifest-import-copy-replay-idempotency-evidence-2026-08-25.json](audit-manifest-import-copy-replay-idempotency-evidence-2026-08-25.json) | Import replay/idempotency baseline、命令 artifact、平台限制与 finding 状态 | 机器可读导入幂等证据 |
| [import-filesystem-db-queue-consistency-evidence-2026-08-25.md](import-filesystem-db-queue-consistency-evidence-2026-08-25.md) | Import 取消/replay 双故障补偿、重启收敛与故障注入回归 | 动态一致性补偿证据 |
| [audit-manifest-import-filesystem-db-queue-consistency-evidence-2026-08-25.json](audit-manifest-import-filesystem-db-queue-consistency-evidence-2026-08-25.json) | Import FS/DB/queue 一致性 baseline、命令 artifact 与 finding 状态 | 机器可读一致性补偿证据 |
| [import-hardening-convergence-evidence-2026-08-25.md](import-hardening-convergence-evidence-2026-08-25.md) | 28-A/29/28-B/28-C/28-D 收敛登记、partial supersession 关系与发布前质量门 | 动态收敛快照证据 |
| [audit-manifest-import-hardening-convergence-evidence-2026-08-25.json](audit-manifest-import-hardening-convergence-evidence-2026-08-25.json) | Import 加固收敛 baseline、命令 artifact、supersession 关系与 finding 状态 | 机器可读收敛证据 |
| [import-source-consistency-toctou-evidence-2026-08-25.md](import-source-consistency-toctou-evidence-2026-08-25.md) | 导入复制与 manifest 指纹的句柄级源一致性守卫与漂移回归 | 动态源一致性证据 |
| [audit-manifest-import-source-consistency-toctou-evidence-2026-08-25.json](audit-manifest-import-source-consistency-toctou-evidence-2026-08-25.json) | 源一致性守卫 baseline、命令 artifact 与 finding 状态 | 机器可读源一致性证据 |
| [recovery-midphase-process-termination-evidence-2026-08-25.md](recovery-midphase-process-termination-evidence-2026-08-25.md) | recover() claim/enqueue 中段真实子进程终止、租约接管与单任务稳定验证 | 动态恢复终止证据 |
| [audit-manifest-recovery-midphase-process-termination-evidence-2026-08-25.json](audit-manifest-recovery-midphase-process-termination-evidence-2026-08-25.json) | 恢复中段终止 baseline、命令 artifact 与 finding 状态 | 机器可读恢复终止证据 |
| [asset-index-safe-open-reparse-consistency-evidence-2026-08-25.md](asset-index-safe-open-reparse-consistency-evidence-2026-08-25.md) | AssetIndex/safe_open reparse 检测对齐、junction 漏检修复与 fail-closed 收紧 | 动态检测一致性证据 |
| [audit-manifest-asset-index-safe-open-reparse-consistency-evidence-2026-08-25.json](audit-manifest-asset-index-safe-open-reparse-consistency-evidence-2026-08-25.json) | Reparse 一致性 baseline、命令 artifact 与 finding 状态 | 机器可读检测一致性证据 |
| [evidence-register-v2-evidence-2026-08-25.md](evidence-register-v2-evidence-2026-08-25.md) | 全局登记 v2：ID 普查、7 项批量晋升 verified-fixed、EVID 接管显式化、勘误指针与待办普查 | 收敛登记快照证据 |
| [audit-manifest-evidence-register-v2-evidence-2026-08-25.json](audit-manifest-evidence-register-v2-evidence-2026-08-25.json) | Register v2 baseline、晋升条目、supersession 关系与验证 artifact | 机器可读收敛登记证据 |
| [cache-failure-quota-hygiene-deepseek-archive-evidence-2026-08-25.md](cache-failure-quota-hygiene-deepseek-archive-evidence-2026-08-25.md) | 缓存时间戳、失败字典、免费额度历史清理与 DeepSeek Docs 选择性归档 | 动态卫生与文档迁移证据 |
| [audit-manifest-cache-failure-quota-hygiene-deepseek-archive-evidence-2026-08-25.json](audit-manifest-cache-failure-quota-hygiene-deepseek-archive-evidence-2026-08-25.json) | 卫生清理与 DeepSeek 归档 baseline、命令 artifact 与 finding 状态 | 机器可读卫生与迁移证据 |

#### 2026-08-26（12 报告 / 12 manifest）

| [restore-backup-fail-closed-admission-evidence-2026-08-26.md](restore-backup-fail-closed-admission-evidence-2026-08-26.md) | restore_backup 目标存在拒绝、文件/目录保留与恢复事件边界 | 动态恢复安全证据 |
| [audit-manifest-restore-backup-fail-closed-admission-evidence-2026-08-26.json](audit-manifest-restore-backup-fail-closed-admission-evidence-2026-08-26.json) | Restore admission baseline、命令 artifact 与 finding 状态 | 机器可读恢复安全证据 |
| [lan-zip-cancel-cleanup-evidence-2026-08-26.md](lan-zip-cancel-cleanup-evidence-2026-08-26.md) | LAN 临时 ZIP 的取消后延迟清理、提交拒绝清理与三类入口覆盖 | 动态 LAN 生命周期证据 |
| [audit-manifest-lan-zip-cancel-cleanup-evidence-2026-08-26.json](audit-manifest-lan-zip-cancel-cleanup-evidence-2026-08-26.json) | ZIP cleanup baseline、命令 artifact 与 finding 状态 | 机器可读 LAN 生命周期证据 |
| [settings-future-version-write-guard-evidence-2026-08-26.md](settings-future-version-write-guard-evidence-2026-08-26.md) | Future settings version 拒绝、只读保护、legacy 抑制与 library manager 写入阻断 | 动态核心持久化证据 |
| [audit-manifest-settings-future-version-write-guard-evidence-2026-08-26.json](audit-manifest-settings-future-version-write-guard-evidence-2026-08-26.json) | Settings guard baseline、命令 artifact 与 finding 状态 | 机器可读核心持久化证据 |
| [shop-partial-metadata-preservation-evidence-2026-08-26.md](shop-partial-metadata-preservation-evidence-2026-08-26.md) | Shop 部分更新以持久化元数据为底、status/gallery 确定性叠加与保留回归 | 动态 commerce 数据证据 |
| [audit-manifest-shop-partial-metadata-preservation-evidence-2026-08-26.json](audit-manifest-shop-partial-metadata-preservation-evidence-2026-08-26.json) | Shop metadata preservation baseline、命令 artifact 与 finding 状态 | 机器可读 commerce 数据证据 |
| [tunnel-limiter-identity-isolation-evidence-2026-08-26.md](tunnel-limiter-identity-isolation-evidence-2026-08-26.md) | 隧道模式限流按签名访客 cookie 隔离、首请求共享降级与直连零变化 | 动态 LAN 安全证据 |
| [audit-manifest-tunnel-limiter-identity-isolation-evidence-2026-08-26.json](audit-manifest-tunnel-limiter-identity-isolation-evidence-2026-08-26.json) | Tunnel limiter isolation baseline、命令 artifact 与 finding 状态 | 机器可读 LAN 安全证据 |
| [restore-crash-intent-recovery-evidence-2026-08-26.md](restore-crash-intent-recovery-evidence-2026-08-26.md) | 恢复两步替换的持久化意图标记与开库自动回滚/fail-closed | 动态恢复崩溃证据 |
| [audit-manifest-restore-crash-intent-recovery-evidence-2026-08-26.json](audit-manifest-restore-crash-intent-recovery-evidence-2026-08-26.json) | Restore intent recovery baseline、命令 artifact 与 finding 状态 | 机器可读恢复崩溃证据 |
| [lan-auth-eventloop-offload-evidence-2026-08-26.md](lan-auth-eventloop-offload-evidence-2026-08-26.md) | 登录/注册/分享密码 PBKDF2 卸载与停靠事件回归 | 动态 LAN 响应性证据 |
| [audit-manifest-lan-auth-eventloop-offload-evidence-2026-08-26.json](audit-manifest-lan-auth-eventloop-offload-evidence-2026-08-26.json) | Auth offload baseline、命令 artifact 与 finding 状态 | 机器可读 LAN 响应性证据 |
| [quota-maintenance-cadence-retry-evidence-2026-08-26.md](quota-maintenance-cadence-retry-evidence-2026-08-26.md) | 免费额度维护 cadence、失败重试与 quota-store 503 fail-closed | 动态额度维护证据 |
| [audit-manifest-quota-maintenance-cadence-retry-evidence-2026-08-26.json](audit-manifest-quota-maintenance-cadence-retry-evidence-2026-08-26.json) | Quota maintenance baseline 与 finding 状态 | 机器可读额度维护证据 |
| [download-tracker-concurrency-evidence-2026-08-26.md](download-tracker-concurrency-evidence-2026-08-26.md) | download_tracker 历史字典与面板快照并发保护 | 动态插件并发证据 |
| [audit-manifest-download-tracker-concurrency-evidence-2026-08-26.json](audit-manifest-download-tracker-concurrency-evidence-2026-08-26.json) | Download tracker baseline 与 finding 状态 | 机器可读插件并发证据 |
| [delivery-claim-tunnel-isolation-evidence-2026-08-26.md](delivery-claim-tunnel-isolation-evidence-2026-08-26.md) | delivery claim failure 按 tunnel visitor identity 隔离 | 动态 LAN 交付安全证据 |
| [audit-manifest-delivery-claim-tunnel-isolation-evidence-2026-08-26.json](audit-manifest-delivery-claim-tunnel-isolation-evidence-2026-08-26.json) | Delivery claim tunnel baseline 与 finding 状态 | 机器可读交付安全证据 |
| [restore-intent-recovery-ack-evidence-2026-08-26.md](restore-intent-recovery-ack-evidence-2026-08-26.md) | 无 session 时 restore marker 诊断、重试回滚与 token ACK | 动态恢复处置证据 |
| [audit-manifest-restore-intent-recovery-ack-evidence-2026-08-26.json](audit-manifest-restore-intent-recovery-ack-evidence-2026-08-26.json) | Restore intent ACK baseline 与 finding 状态 | 机器可读恢复处置证据 |
| [shop-metadata-input-contract-evidence-2026-08-26.md](shop-metadata-input-contract-evidence-2026-08-26.md) | Shop metadata/image_paths 输入边界与前端 payload 类型 | 动态 commerce 契约证据 |
| [audit-manifest-shop-metadata-input-contract-evidence-2026-08-26.json](audit-manifest-shop-metadata-input-contract-evidence-2026-08-26.json) | Shop metadata contract baseline 与 finding 状态 | 机器可读 commerce 契约证据 |

#### 2026-08-27（9 报告 / 9 manifest）

| [tunnel-cookie-farm-guard-evidence-2026-08-27.md](tunnel-cookie-farm-guard-evidence-2026-08-27.md) | 隧道限流拒绝响应不再发放访客 cookie，关闭身份农场 | 动态 LAN 安全证据 |
| [audit-manifest-tunnel-cookie-farm-guard-evidence-2026-08-27.json](audit-manifest-tunnel-cookie-farm-guard-evidence-2026-08-27.json) | Cookie farm guard baseline 与 finding 状态 | 机器可读 LAN 安全证据 |
| [claim-reservation-accounting-evidence-2026-08-27.md](claim-reservation-accounting-evidence-2026-08-27.md) | share-claim 占位式记账消除 check/record 并发窗口 | 动态交付限流证据 |
| [audit-manifest-claim-reservation-accounting-evidence-2026-08-27.json](audit-manifest-claim-reservation-accounting-evidence-2026-08-27.json) | Claim reservation baseline 与 finding 状态 | 机器可读交付限流证据 |
| [claim-map-hard-cap-evidence-2026-08-27.md](claim-map-hard-cap-evidence-2026-08-27.md) | claim failure map 5000 键硬上限与插入序淘汰 | 动态内存边界证据 |
| [audit-manifest-claim-map-hard-cap-evidence-2026-08-27.json](audit-manifest-claim-map-hard-cap-evidence-2026-08-27.json) | Claim hard cap baseline 与 finding 状态 | 机器可读内存边界证据 |
| [tunnel-cookie-dedupe-secure-evidence-2026-08-27.md](tunnel-cookie-dedupe-secure-evidence-2026-08-27.md) | 访客 cookie 单发去重与按请求方案 Secure 标志 | 动态 cookie 契约证据 |
| [audit-manifest-tunnel-cookie-dedupe-secure-evidence-2026-08-27.json](audit-manifest-tunnel-cookie-dedupe-secure-evidence-2026-08-27.json) | Cookie dedupe/Secure baseline 与 finding 状态 | 机器可读 cookie 契约证据 |
| [quota-consume-busy-retry-evidence-2026-08-27.md](quota-consume-busy-retry-evidence-2026-08-27.md) | quota consume 完整事务 busy 重试与 fail-closed 不变 | 动态存储弹性证据 |
| [audit-manifest-quota-consume-busy-retry-evidence-2026-08-27.json](audit-manifest-quota-consume-busy-retry-evidence-2026-08-27.json) | Consume retry baseline 与 finding 状态 | 机器可读存储弹性证据 |
| [quota-preflight-fast-deny-evidence-2026-08-27.md](quota-preflight-fast-deny-evidence-2026-08-27.md) | 已耗尽身份在昂贵准备前被只读预检快速拒绝 | 动态资源防护证据 |
| [audit-manifest-quota-preflight-fast-deny-evidence-2026-08-27.json](audit-manifest-quota-preflight-fast-deny-evidence-2026-08-27.json) | Preflight fast-deny baseline 与 finding 状态 | 机器可读资源防护证据 |
| [prefs-path-lock-merge-evidence-2026-08-27.md](prefs-path-lock-merge-evidence-2026-08-27.md) | 插件偏好同路径多 bag 锁+重读合并防丢更新 | 动态插件持久化证据 |
| [audit-manifest-prefs-path-lock-merge-evidence-2026-08-27.json](audit-manifest-prefs-path-lock-merge-evidence-2026-08-27.json) | Prefs path lock baseline 与 finding 状态 | 机器可读插件持久化证据 |
| [restore-residue-sweep-evidence-2026-08-27.md](restore-residue-sweep-evidence-2026-08-27.md) | 库锁内本库槽 restore 孤儿残留归档清扫 | 动态恢复卫生证据 |
| [audit-manifest-restore-residue-sweep-evidence-2026-08-27.json](audit-manifest-restore-residue-sweep-evidence-2026-08-27.json) | Restore residue sweep baseline 与 finding 状态 | 机器可读恢复卫生证据 |
| [tunnel-quota-parity-assembly-evidence-2026-08-27.md](tunnel-quota-parity-assembly-evidence-2026-08-27.md) | quota↔tunnel 身份互验契约与生产装配实测 | 动态契约覆盖证据 |
| [audit-manifest-tunnel-quota-parity-assembly-evidence-2026-08-27.json](audit-manifest-tunnel-quota-parity-assembly-evidence-2026-08-27.json) | Parity/assembly coverage baseline 与 finding 状态 | 机器可读契约覆盖证据 |
| [storefront-secret-parity-evidence-2026-08-27.md](storefront-secret-parity-evidence-2026-08-27.md) | storefront analytics 签名密钥收敛至共享回退源，三方同源 | 动态 cookie 契约证据 |
| [audit-manifest-storefront-secret-parity-evidence-2026-08-27.json](audit-manifest-storefront-secret-parity-evidence-2026-08-27.json) | Storefront secret parity baseline 与 finding 状态 | 机器可读 cookie 契约证据 |
| [lan-activity-offload-evidence-2026-08-27.md](lan-activity-offload-evidence-2026-08-27.md) | 活动日志 SQLite 落盘经 to_thread 卸载事件循环 | 动态 LAN 响应性证据 |
| [audit-manifest-lan-activity-offload-evidence-2026-08-27.json](audit-manifest-lan-activity-offload-evidence-2026-08-27.json) | Activity offload baseline 与 finding 状态 | 机器可读 LAN 响应性证据 |
| [webui-503-net-evidence-2026-08-27.md](webui-503-net-evidence-2026-08-27.md) | WebUI 503 分类/重试回归网（测试-only） | 动态前端契约证据 |
| [audit-manifest-webui-503-net-evidence-2026-08-27.json](audit-manifest-webui-503-net-evidence-2026-08-27.json) | WebUI 503 net baseline 与 finding 状态 | 机器可读前端契约证据 |
| [prefs-crossproc-lock-evidence-2026-08-27.md](prefs-crossproc-lock-evidence-2026-08-27.md) | 插件偏好跨进程 advisory 保存锁与双子进程回归 | 动态插件持久化证据 |
| [audit-manifest-prefs-crossproc-lock-evidence-2026-08-27.json](audit-manifest-prefs-crossproc-lock-evidence-2026-08-27.json) | Prefs cross-process lock baseline 与 finding 状态 | 机器可读插件持久化证据 |
| [claim-lru-refresh-evidence-2026-08-27.md](claim-lru-refresh-evidence-2026-08-27.md) | claim 容量淘汰按刷新重插实现近似 LRU 保位 | 动态限流治理证据 |
| [audit-manifest-claim-lru-refresh-evidence-2026-08-27.json](audit-manifest-claim-lru-refresh-evidence-2026-08-27.json) | Claim LRU refresh baseline 与 finding 状态 | 机器可读限流治理证据 |
| [audit-manifest-tunnel-quota-parity-assembly-evidence-2026-08-27.json](audit-manifest-tunnel-quota-parity-assembly-evidence-2026-08-27.json) | Parity/assembly coverage baseline 与 finding 状态 | 机器可读契约覆盖证据 |

## 4. 与既有文档的关系

| 文档 | 定位 | 状态 |
|---|---|---|
| 本文档集 `docs/full-review/` | **带基线的历史审计快照索引** | 以每份报告的日期、commit 和 manifest 为准 |
| `README.md` | 项目总览/门禁声明 | 结构数字受 `check_doc_stats.py` 校验；运行结果必须有 CI artifact |
| `docs/architecture.md` | 架构层描述 | 当前说明文档，代码仍是实现事实来源 |
| `docs/migrations.md` | 迁移文档 | 需要持续与代码 schema 同步 |
| `docs/lan-security.md` | LAN 安全 | ⚠️ token 读取顺序、公开路径、限流范围过时（见 06 §2.3） |
| `DeepSeek Docs/`（10 章） | 2026-08-01 基线审计 | ⚠️ 结构性准确，行号/模块数/版本大量过时（差异清单见 06 §2） |
| `docs/compose/` | 历史计划/报告/交接 | 历史参考；`reports/` 中 8-10/8-11 会话系列为近期工作记录 |

**约定**：未来任务以本文档集为入口；历史文档仅作背景参考，引用代码行号以工作区实测为准。

## 5. 阅读路径建议

- **新任务快速上手**：01（架构）→ 02（模块索引）→ 07（验证基线）
- **改事件/实时逻辑**：04 → 03 §B1/B2
- **改 LAN API**：02 §4（路由表）→ 03 §B3-B5
- **改前端**：05 → 03 §B2-B5
- **排查已知问题**：06 §1（本轮发现）→ 06 §3（技术债清单）
- **按日期追溯批次证据**：第 3.2 节的 9 个日期分桶（每份报告与其 manifest 相邻）；最新批次在文件末尾对应的 `#### YYYY-MM-DD` 小节
