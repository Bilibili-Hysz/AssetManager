# 10 · 与 docs/full-review/ 证据体系的交叉校验（2026-08-22）

**目的**：将本审计（[README.md](README.md) 索引的 8 份领域文档，130 条主要发现）与 `docs/full-review/` 的既有发现体系逐条对照，区分**已知项 / 部分重叠 / 新发现**，并修正本审计中与既有证据冲突或需要校准的表述。
**对照语料**：full-review 58 份文档 = 5 份发现层审计（09-deep-audit-2026-08-15、full-scan / cross-module-flow / performance-timing / code-quality 四份 2026-08-20，合计约 183 条编号发现）+ 1 份 canonical register（evidence-convergence-2026-08-20，13 个 EVID 编号映射到 S/C/G/PC 工作流）+ 15 份实施/回归/hardening 证据（2026-08-21 的 desktop-async、S1-S5-S2-min、C1~C10 系列、C6-C10 三份加固；2026-08-22 的 auth-plugin-websocket、auth-revocation 两份）+ 20 份机器可读 manifest。

## 1. 校验总结论

| 分类 | 条数（主要发现口径） | 占比 |
|---|---|---|
| **已知项**（full-review 已登记，含编号） | ~19 | 15% |
| **部分重叠**（同族已知 / 类别已知但本审计给出新锚点或新角度） | ~25 | 19% |
| **新发现**（full-review 全语料零命中，含逐词 grep 验证） | ~86 | 66% |

主审对本审计 11 条最高严重度发现做了读码复核；本轮对照又对关键新发现做了逐词语料 grep（`tab_container`、`windowOpacity`、`cached_file_count`、`Cf-Connecting`、`remove_partial_target`、`lexists` 等均为零命中）。**两条 P1 级新发现（restore_backup 数据破坏、导入清单恢复无终态）落在 C4/C10 刚实施的代码里**——即它们是 full-review 修复批次自身的残留缺陷，这正说明本审计与 full-review 体系互补而非重复。

## 2. 对本审计文档的修正（重要）

以下 5 点由对照产生，**覆盖各域文档的对应表述**：

| # | 修正 | 依据 |
|---|---|---|
| C-1 | **05 文档**"27 个裸 commit 写方法"应更正为 **25 个**：`revoked_token_repository` 的 2 个方法（add/prune_expired）已在 2026-08-22 的 AUTH-REV-01 批次修复（不再提交调用方事务，fixed-unverified）。 | [auth-revocation-concurrency-hardening-evidence-2026-08-22.md](../full-review/auth-revocation-concurrency-hardening-evidence-2026-08-22.md) §2 |
| C-2 | **02 文档**"取消的导入不发布任何事件"重新分类为**已知设计契约**而非新缺陷：C8-02 明确记载"already copied files are retained and no import event or refresh is published on cancellation"并称之为既有契约。本审计对其后果的批评（索引滞后至 watcher 下一轮，默认 120s）仍然成立，建议作为契约复审项而非 bug 登记。 | [c8-min-import-partial-contract-evidence-2026-08-21.md](../full-review/c8-min-import-partial-contract-evidence-2026-08-21.md) §C8-02 |
| C-3 | **02 文档**"导入清单恢复无终态"确认为**新发现（C10 实现缺陷）**：C10 报告描述了"扫描 recovery_pending 集合并入队 rescan"的机制，但未登记"成功恢复后状态仍是 recovery_pending ∈ 恢复集合 → 每次开库永久重复全库重扫、attempts 无限递增"的后果。机制有文档、缺陷无登记。 | [c10-min-import-durable-intent-recovery-evidence-2026-08-21.md](../full-review/c10-min-import-durable-intent-recovery-evidence-2026-08-21.md) §2 逐句比对 |
| C-4 | **07 文档**"下载超时总预算"确认为**已知项 P2-11 的修复副作用**：P2-11（blob body 完全不受超时约束）的修复引入了 5 分钟总预算；本审计发现的是该修复语义错误（总预算 ≠ 注释声称的停滞预算），属回归性新缺陷。 | [full-scan-2026-08-20.md](../full-review/full-scan-2026-08-20.md) P2-11 + webui/src/api/client.ts:36 现状 |
| C-5 | **08 文档**P0 的表述校准：full-review 体系本身包含**活跃的本地验证证据**（2026-08-22 两次全量套件：3912/3907 passed, 0 failed，Windows 本机），本审计 P0 指的是**独立 CI 执行缺失**（无 remote、分支不触发、release 无前置）——不是"没有任何测试证据"。EVID-04/GOV-01 已登记 release 门禁不足，但"仓库无 remote、CI 从未运行"这一事实未被任何 full-review 文档登记，属新发现的超集事实。 | [auth-plugin-websocket-implementation-evidence-2026-08-22.md](../full-review/auth-plugin-websocket-implementation-evidence-2026-08-22.md) §3 |

另一处值得登记的相邻发现：**01 文档**"ExtensionCategoryLookup 每次 get 重建字典"是 2026-08-22 当天 PLUGIN-OWN-01 修复（分类贡献改为 live canonical registry，`_common.py:16-60`）的**性能副作用**——正确性修复引入了热路径重建。修复该点时需保持 live 语义，只加缓存层。

## 3. 逐域对照表（主要发现）

图例：**已知** = full-review 有编号登记；**同族** = 类别/家族已知但本条是新的具体锚点或角度；**新** = 语料零命中。

### 01 桌面 UI（17 条）

| 本审计发现 | full-review 对应 | 分类 |
|---|---|---|
| stderr 全局锁串行化解码（P1） | PT-07 / EVID-12（canonical，排期 benchmark + 收窄设计） | 已知 |
| ThumbnailLoader 持锁 getmtime（P2） | 09-deep-audit 桌面 L1 LOW（_loader.py:549 同点） | 已知 |
| 关窗串行 drain 叠加（P1） | H-D1 / PT-08 / PT-20（desktop-async 批次已部分处理 blocked-worker teardown） | 同族（残留角度：串行叠加 + ffmpeg 跨面板共享池） |
| sharing 对话框 singleShot/_closed 不一致（P2） | M-D2（QTimer.singleShot 访问已销毁 widget） | 同族 |
| InfoPanel 预览 QPixmap 在 worker 线程（P2） | WT-01（cover callback affinity，同类不同点） | 同族 |
| TabContainer 重复标签页（P1）✓已复核 | — | **新** |
| 设置滑块每刻度磁盘写 + paintEvent 解码（P1） | — | **新** |
| 破坏性确认框硬编码英文（P1） | 仅 webui 侧已知（P2-13、前端 L1）；桌面 _actions 系列未登记 | **新**（桌面清单） |
| 纹理缓存无字节上限、ExtensionCategoryLookup 重建（P2，见 §2 注意） | — | **新** |
| windowOpacity 子控件动画无效（P2）及其余 7 条 | — | **新** |

### 02 应用数据管线（16 条）

| 本审计发现 | full-review 对应 | 分类 |
|---|---|---|
| 取消的导入不发布事件（P2） | C8-02（登记为契约决策） | 已知（见 C-2） |
| 导入清单恢复无终态（P1）✓已复核 | C10 描述机制、未登记缺陷后果 | **新**（见 C-3） |
| restore_backup 删除已存在目标（P1）✓已复核 | C4-03 只覆盖投影快照失败可观测性；lexists/target-exists 零命中 | **新** |
| quarantine→install 崩溃窗口（P2） | C6-B 剩余限制"cross-system crash window"（类别已知） | 同族（具体机制为新锚点） |
| watcher/worker stop 超时关库失败（P2） | XOWN-06 / PT-20（C7 已做 bounded stop/join） | 同族（残留：2s/30s 预算不匹配） |
| move IO 后事务被占仅告警（P2） | XFS-01/C4-B（move 修复包络已建） | 同族（残留路径） |
| manifest 更新异常中止导入（P2） | C8（部分失败契约已建，此路径未覆盖） | 同族 |
| lease 墙钟回拨（P2）、队列单行损坏锁死开库（P2）、rmtree 持写门（P2）、备份无 fsync（P2）及 P3×4 | — | **新**（10 条） |

### 03 应用领域服务（16 条）

| 本审计发现 | full-review 对应 | 分类 |
|---|---|---|
| gallery 增量/全量 generation 竞态（P2） | 批次 G（H-G1/M-G3 家族） | 同族（该具体竞态未登记） |
| 结账幂等竞态 500 而非重放（P2） | C1（错误 envelope 已实施）/ XAPI 家族 | 同族（跨进程竞态语义未登记） |
| search_by_tags 无预算（P2） | M-L4 / P2-04（无预算端点家族） | 同族（tags 参数具体点新） |
| CSV 泄漏 buyer_owner_key（P3） | P2-09（购物车暴露 owner_key，相邻） | 同族 |
| file_count 缓存永久陈旧（P1）✓已复核 | CQ-13 是相邻点（隐式写缓存），此失效缺陷零命中 | **新** |
| shop update_item 清空 metadata 画廊（P1） | — | **新** |
| QuotaService 死接线（P2）、项目列表 N+1 扫描（P2）及 P3×8 | — | **新**（11 条） |

### 04 核心基础设施+插件（16 条）

| 本审计发现 | full-review 对应 | 分类 |
|---|---|---|
| ProjectData 读路径无锁（P1） | H-L1 / P2-06（共享连接读锁覆盖不完整家族；P2-06 清单未含 ProjectData） | 同族（新锚点） |
| 插件加载/discover 并发（P2 部分） | P3-05⑦ / CQ-06/07/08（PLUGIN-OWN-01 已部分修复） | 同族 |
| settings 未来版本覆盖（P1）✓已复核 | CQ-09 是相邻点（跨进程 last-writer-wins），此降级路径零命中 | **新** |
| LibraryLock Windows PID 复用（P2） | P1-09/EVID-03 是 POSIX 对偶方向 | **新**（Windows 方向） |
| 五表契约死角（P2）、迁移连续性无断言（P2） | DOC-02 是文档漂移，非契约校验缺口 | **新** |
| 跨连接锁序（P1 疑似）、download_tracker 示例并发（P2）、BoundedPool 令牌泄漏（P2）、PreferenceBag 无锁（P2）、themes 竞态（P2）及 P3×6 | — | **新**（14 条） |

### 05 领域+仓库层（17 条）

| 本审计发现 | full-review 对应 | 分类 |
|---|---|---|
| 27→25 个裸 commit（P1）✓已复核 | CQ-12 / XFS-09 / EVID-06（C2/C3 工作流在途）；revoked 2 个已修（见 C-1） | 已知（清单扩充 + 状态更新） |
| sqlite3→领域错误映射不一致（P2） | CQ-15 | 已知 |
| remove_url 非原子 RMW（P2） | XFS-05/CQ-11（同函数的事件时序问题已知并排期 C3；RMW 窗口未登记） | 同族 |
| migrate/merge 循环 N+1（P2） | PT-04（tag 线性 fan-out 已知；metadata/favorite/shop_buyer 循环未登记） | 同族 |
| update_item 合并读取在事务外（P1）✓已复核 | CQ-12 家族未含此具体窗口 | **新** |
| 订单状态机贫血+校验不一致（P2）、event_bus BaseException（P2）、domain→core 依赖（P2）、索引失效搜索（P2）及 P3×6 | — | **新**（11 条） |

### 06 LAN 服务器安全（16 条）

| 本审计发现 | full-review 对应 | 分类 |
|---|---|---|
| 分享 info 暴露 created_by（P2） | P3-05④ | 已知 |
| 分享密码锁 check-then-count 竞态（P2） | P2-01（锁定范围问题，同函数相邻竞态） | 同族 |
| cloudflared 无哈希校验（P2） | EVID-04/GOV 家族（发布/依赖 provenance 已知；cloudflared 二进制下载具体点在全部语料零命中，security-boundary 报告亦未提及） | 同族（具体点新，与 08 文档共用） |
| /api/stats 无权限 + 能力声明漂移 4 组（P2） | L1 声明层与 check_route_capabilities.py 已建（写路由）；stats/漂移点未登记 | 同族（漂移清单新） |
| verify_user_token 同步阻塞 loop（P3） | EVID-02/S2-min（认证 offload 已做 password/access-key；user token 路径残留） | 同族（残留点） |
| **隧道限流 127.0.0.1 折叠（P1）✓已复核** | 全语料零命中（`Cf-Connecting`/该机制无登记） | **新** |
| 密码模式令牌哈希即密钥（P2）、无邀请码开放注册（P2）、410/expired 泄漏（P2）、ZIP 反斜杠（P3）、CSP 缺失（P3）、用户名时序（P3）、WS 非控制帧（P3）、失败字典无界（P3）、cookie Secure（P3） | — | **新**（11 条） |

### 07 WebUI 前端（15 条）

| 本审计发现 | full-review 对应 | 分类 |
|---|---|---|
| queryCache gc 不删条目（P3） | PT-13 | 已知 |
| 门禁盲区 components/（P2） | CQ-17 | 已知 |
| 类型双源 api.ts/contracts.ts（P2） | XAPI-07 / CQ-16 | 已知 |
| 真实后端 e2e 默认 skip（P2） | P1-13 | 已知 |
| 认证失败静默降级 guest（P3） | P2-14 | 已知（代码 B6 注释亦自认） |
| 卖家页面用主会话客户端（P1） | XAUTH-02（同族：卖家身份域混用；orders/products 页面具体点新） | 同族 |
| 主登出不清卖家会话（P2） | XAUTH-02 的对偶方向 | 同族 |
| 下载超时总预算（P1）✓已复核 | P2-11 的修复副作用（见 C-4） | 同族（回归性新缺陷） |
| WS 无心跳半开检测（P2） | XRT-04（重连窗口相邻） | 同族 |
| i18n 硬编码残留（P3） | 前端 L1 LOW（InfoPanel 已知；LandingPage 点新） | 同族 |
| AbortSignal 未转发（P2）、1.5s 抑制窗（P3）、StatusBar 轮询（P3）、permissions 死字段（P3）、错误快照回滚乐观更新（P3） | — | **新**（5 条，另 P2 卖家客户端归同族） |

### 08 测试·门禁·CI·构建（17 条）

| 本审计发现 | full-review 对应 | 分类 |
|---|---|---|
| release 无测试前置（P1） | GOV-01 / EVID-04 | 已知 |
| 依赖无 lock（P2） | GOV-02 | 已知 |
| 构建/发布路径漂移 + upx 不一致（P1） | GOV-05 | 已知 |
| pyright 钉旧 + basic（P2） | P3-02 | 已知 |
| conftest monkeypatch pytest 内部（P2） | P3-01 | 已知 |
| 浏览器 E2E 覆盖差距（P2） | P1-13 | 已知 |
| 性能门禁零执行（P1） | GOV-07（部分：nightly/p95 gate 已知；**恒真断言**未登记） | 同族 |
| Windows lane 窄（P1） | P3-02 相邻（平台矩阵缺口未明确登记） | 同族 |
| _cleanup_stores 覆盖不全（P1） | P3-01 相邻（全局状态登记机制未登记） | 同族 |
| 无 remote / CI 从未执行（P0）✓已复核 | EVID-04 超集事实（见 C-5） | 同族（新事实层） |
| CI 分支过滤（P0）✓已复核 | — | **新** |
| cloudflared（P0） | 见 06 行（同族，具体点新） | 同族 |
| flaky 无隔离机制（P1）、LAN 测试中间件漂移（P1）、stress 标记矛盾（P3 边缘）、ruff/compileall 范围漂移（P2） | — | **新**（4 条） |

## 4. 与在途 workstream 的合并建议

用户已声明将先完成 full-review 任务再处理本审计的建议。据此，本审计的发现按归属分为三组：

**A 组 · 可直接并入在途工作流的输入**（无需新开工作流）：
- C2/C3（事务所有权）：05 文档的 25 个裸 commit 清单 + update_item 事务外读取 + remove_url RMW 窗口，作为 C3 "write-scope and rollback oracle" 的实施清单。
- EVID-12（stderr 锁）：01 文档的锁粒度建议（dup2 瞬间 + header 预检）可直接作为该 benchmark 后的实施方案。
- Phase 3（plugin contribution ownership，PLUGIN-OWN-01 后续）：download_tracker 示例插件的无锁 dict、PreferenceBag 无锁、_undo_stack 无界，归入该工作流的收尾清单。
- EVID-04/G（发布治理）：cloudflared pin+哈希、无 remote 事实、CI 分支过滤、release 前置，全部并入 G1/G2 的实施范围。
- C8/C10 收尾：导入清单恢复终态（C-3）与取消导入的索引补偿（C-2 后果）应作为 C10 的 bug 修正而非新工作流。

**B 组 · 建议新增到 canonical register 的 EVID 级新发现**（语料零命中且 P1 级）：
1. restore_backup 目标已存在时的数据破坏（02）——建议进入 C4 后续批次。
2. settings 未来版本拒绝降级未闭环（04）——独立小批次。
3. 隧道场景速率限制身份折叠（06）——建议进入 S 系安全批次。
4. file_count 缓存无失效（03）——可并入 C 系投影一致性主题。
5. shop update_item 事务外合并读取 + metadata 整体覆盖（03+05 同族）——Commerce 域小批次。
6. TabContainer 重复标签页（01）——独立一行级修复。

**C 组 · 无需进 register 的低优先级新发现**（P2/P3，~70 条）：保留在本审计各域文档中，作为后续批次的挑选池，不占用 register 命名空间。

## 5. 对照过程中发现的 full-review 自身问题

1. **00-INDEX 计数漂移**：索引声称 09-deep-audit 为 "5 HIGH / 19 MEDIUM / 22 LOW"，正文实数 5/16/23（MEDIUM 表缺 3 条、LOW 多 1 条）。check_audit_reports.py 不校验 prose 计数，建议人工修正或在 manifest 中加 prose-count 断言。
2. **发现层五份文档均无状态标注**：183 条发现全部"问题+建议"形态，状态追踪完全依赖后续 evidence 文档引用其 ID。目前只有约 13 个 EVID + 被实施批次引用的少数 ID 有状态；其余（如 M-F1~M-F4、L 系列、P2 大半）的状态不可机读。建议为 register 增加"未排期"默认状态列。
3. **C8-02 与 watcher 补偿的衔接空白**：C8 把"取消不发布事件"定为契约，但该契约与 XFS-03（watcher 只发 invalidation 不触发 reconciliation）叠加后，取消导入的索引恢复依赖 120s 轮询——两个已知决策的**组合效应**未被任何文档登记，本审计 02 文档的批评实际指向这个组合空白。

## 6. 校验边界

- 本对照覆盖 8 份领域文档的 **130 条主要发现**；~145 条次要问题未逐条对照（其主题多与主要发现同族，预计新发现比例更高）。
- "零命中"判定基于逐词 grep + 关键报告精读；同义异名表述（如未用"windowOpacity"而用"透明度动画"描述的旧文档）理论上可能漏检，但五份发现层文档已由探索代理全量提取条目清单，交叉覆盖后残余风险低。
- full-review 的 15 份实施证据文档只精读了 6 份关键件（convergence、c4、c8、c10、auth-plugin、auth-revocation），其余 C1-C7/C9/S1-S5 系列以条目级引用核对为主；如需逐份深挖，建议后续单独任务。
