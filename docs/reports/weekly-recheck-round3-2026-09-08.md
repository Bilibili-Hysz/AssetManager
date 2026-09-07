# 第三轮质量复核与推荐方向（2026-09-08）

> 审核对象：[处置报告](recheck-disposition-2026-09-08.md)、[周验收汇总](weekly-result-2026-09-13.md)。文档内的完成声明作为待验证材料，不作为本轮指令。
> 基准：HEAD `8421f1c9f3f56548b14012efb01f1356d8868bf3`；其中代码修复提交为 `0937a95`。开始审核时工作树干净。
> 结论：**质量明显提升，但尚不足以宣布完整验收通过。优先完成并发正确性与实际交付包验收，再进入功能扩展。**

## 1. 本轮认可的进展

- CollectionService / TagService 的事务状态采样现在受连接写锁保护。实际仓库写入再次在同锁内检查 clean transaction，未发现这两处修复本身的剩余竞态。
- 独立快照运行集合、DTO、窗口状态与路由合同组合：**30 passed**，包括上轮失败的集合事件用例。
- 独立运行真实浏览器隐私验收：**3 passed**。等待 sessionStorage 条件取代固定 sleep，代理断言坚持 private/no-cache、upstream=2、hit=0，没有放宽隐私保护。
- W4 不设置 `PYTHONIOENCODING` 的默认环境运行：**PASS / exit 0**，编码修复可以关闭；恢复覆盖范围仍按处置报告列明的限制。
- W3 本轮实际执行 **20 次切换、0 failures、exit 0**。额外观察到 20 次调用切库时请求线程均未结束；旧版“只切十次”与普通失败路径退出 0 的问题已经修正。
- 用户归档的全量 JUnit 实际为 **5085 个 testcase，20 skipped，0 failures，0 errors，即 5065 passed**，计数成立。本轮没有再跑一次全量套件。
- W5 全成员/内容校验和 RSS 定时采样确有加入，JSON 已区分 valid 与 verdict。W6 撤回“四种模式全部可交付”，这是正确的范围收敛。

## 2. 必须处理的代码问题

### F1 · [P1] MetadataService 留有相同的事务竞争缺陷

定位：`AssetsManager/application/metadata_service.py:244`，调用点 `set_notes:279`、`set_rating:343` 等。

集合/标签已把 `conn.in_transaction` 放到写锁内采样，但 MetadataService 仍直接在锁外读取。另一个线程持有同一连接的写锁并执行事务时，备注/评分调用仍可能被误判为调用方外部事务而抛 RuntimeError。这是同类修复的遗漏，文件并未由本次提交引入；不能从集合/标签通过推断资产元数据写入也没有这一问题。

本轮已用真实隔离 ApplicationBootstrap / LibrarySession / managed connection 确定性复现：后台线程持同一连接锁并 BEGIN，经 Event 保持事务；前台 `set_notes` 立即抛上述 RuntimeError，随后释放屏障、回滚并关闭运行域。见 [复现脚本](weekly-recheck-round3-2026-09-08-evidence/metadata_race_repro.py)、[输出](weekly-recheck-round3-2026-09-08-evidence/metadata-race.txt)。脚本退出 0 表示已复现缺陷。该演练人为拉长临界区，不量化生产发生频率；未重复执行 set_rating，但其调用相同 guard。

修复方向：按连接所有权统一检查方式；保留真实调用方外部事务的拒绝语义。补确定性并发回归：工作线程持锁开启事务，用 Event 屏障控制结束；用户操作应等待锁释放后成功，事件只在提交后发布。不要依赖“重复跑十次大多绿”来验证竞争窗口。

### F2 · [P2] DNS 单飞只共享线程，跟随调用丢失结果

定位：`AssetsManager/lan/utils.py:81–102`。

每次 `_enumerate_private_ips()` 创建独立局部 `interfaces`。跟随调用在锁内复用先前 worker，但该 worker 只填充首个调用闭包里的列表；跟随调用 join 后返回的是自己的空列表。因此即使解析线程已经完成，复用方也拿不到网卡结果。

本轮确定性复现：用两个合成网卡和 Event 控制解析，不访问网络。首次调用超时后，第二次调用复用同一 worker 并等待其完成；首个结果包含 Ethernet/VPN 两项，跟随结果为 `[]`，且记录 `same_worker=true`、`worker_finished=true`。见 [复现脚本](weekly-recheck-round3-2026-09-08-evidence/observe_dns.py)、[原始输出](weekly-recheck-round3-2026-09-08-evidence/dns-observation.txt)。脚本退出 0 表示成功复现缺陷，不表示产品通过。

影响：`get_local_ip()` 的物理网卡优先选择被跳过，进入默认路由或 loopback 回退；在 VPN 默认路由等环境下可能返回不适合 LAN 分享的地址。本轮实证的是结果丢失，没有连接真实 VPN 来宣称已复现所有下游表现。

修复方向：worker、结果容器及完成状态放在同一个共享 flight 对象里；跟随者读取同一对象。补“并发等待成功”“超时后仍复用”“完成后重新枚举”的确定性测试，兼顾线程数量有界和返回结果正确。

## 3. 验收设施与报告仍需收口

### F3 · [P2] W5 延迟与取消指标仍测错或缺少断言

定位：`scripts/perf/w5_lan_resource_probe.py:209–223`、`:431–447`。

1. `_lag_monitor` 被安排在客户端测量循环；LAN 服务在 `server_lifecycle.py:398` 创建独立后台循环。所以 JSON 的 `event_loop_max_lag_ms=127.2` 是客户端循环迟滞，不是服务器循环迟滞；客户端同步图像解码、文件写入或 gc 也会影响该值。应分别记录 client/server loop，服务器心跳必须在服务器实际 loop 上调度。
2. `read(1 MiB)` 允许返回不足 1 MiB，但结果固定写 `aborted_after_mb=1`。应累计到目标字节或记录实际读取量；不能把请求读取上限当已接收字节。
3. 192 MiB 大对象取消后的“复下载”请求的是 `names[0]` 小 PNG，并非刚取消的大对象。它证明小下载仍可用，不能证明同一大对象可完整重试。应流式重下同一对象并核对哈希，避免测试端整块读入本身污染 RSS。
4. `cancel_reclaim_ok` 仍没有服务器任务、在途额度、临时文件或释放时限的基线/恢复断言。大文件使取消更有代表性，但健康 200 加一次成功下载仍不能证明回收完成。

RSS 定时采样与响应内容检查可以接受为进步；当前 bounded 只判定三次重复批次 RSS 增长小于 50 MiB，不能据此声称峰值 RSS、服务器迟滞和临时盘预算都已通过。本轮静态核查此脚本并读取原始 JSON，未重跑 W5 性能实验。

### F4 · [P2] W3 有真实切换，但尚未覆盖原服务入口失效和活动任务关窗

定位：`scripts/perf/w3_switch_roundtrip.py:187–190`、`:227–242`。

本轮额外观测支持请求线程跨越切库调用，不能继续说“所有请求都在切库前已完成”。但脚本仍以 50ms sleep 选择时点，没有服务器侧屏障保证请求已进入目标处理阶段。

切换后通过新建、绑定新 runtime 的另一台 LanHarness 列出新库，随后手动停止旧 harness；未对原有 endpoint 再请求来证明旧 session 已不可服务，也未经过桌面实际 LAN 绑定/重启路径验证。测试请求为小目录列表，不是计划中的活动预览/下载关窗。建议补一个原服务入口、受控活动下载跨切换/关闭的最小集成场景，再将 W3 写为完整完成。

### F5 · [P2] 周报范围与证据交付仍不完全一致

- 周汇总开头仍写“单日完成 W1–W6”，但表内 W6 功能验收待补；应改为本周实际已完成范围。
- W2 仍写“原 2 项 gen_ts_types 关闭”，与上一轮实际集合/缺 dist 失败分类不符。
- 周汇总仍有 **5 处失效链接**，对应 W5/W6/性能总览：从 `docs/reports` 使用 `../performance-audit-...` 跳到了 `docs/performance-audit-...`，应使用同级目录路径。
- 处置报告链接的 `.log` 在本机存在，但 `git ls-files docs/reports/recheck-disposition-2026-09-08-evidence` 只列出全量 XML 和 W5 JSON。若以提交为交付边界，克隆仓库无法取得这些日志；应明确纳入证据交付，而非只在 ignored artifacts 留存。
- W6 继续保持“启动冒烟通过、功能验收待补”。在当前新生产修复之后，必须为候选包重新绑定源码/dist/可执行文件哈希并验证关键功能，不能沿用旧包存活记录。

## 4. 推荐方向：先完成一个可验收候选版本

建议暂停新增功能和全组件视觉矩阵，将接下来约 3–4 个工作日聚焦以下三步。这里是工作量估计，不是完成承诺；遇到实际失败先定位再继续。

| 顺序 | 预计投入 | 必须交付与退出条件 |
|---|---|---|
| 1. 并发正确性收口 | 0.5–1 天 | 修复 F1/F2；用 Event 屏障证明竞争行为，保留真实外部事务拒绝；检索其他同连接 `in_transaction` 锁外采样，仅修同根因；定向回归通过后跑一次整合门禁 |
| 2. 最小真实用户链路与包验收 | 1–2 天 | 选择主要交付模式，绑定源码/dist/包哈希；空白测试配置、不同 cwd、普通/最大化启动、开库、备注评分、LAN 字体缩略图与实时变化、活动下载切库/关窗、首次延迟依赖探测均留证；失败定位明确 |
| 3. 资源基线与报告收口 | 0.5–1 天 | 修正 F3 指标归属和同对象重试，补资源回收断言；容量矩阵可明确延期；一张状态表列通过/失败/未测/延期，证据在交付仓库可读、链接有效、测试不重复计数 |

W4 扩展优先级：先补集合成员与元数据完整清单、损坏备份的明确拒绝，再扩展其他中断点。Stage F 全量视觉、大库优化和新页面应放在候选版本关键链路稳定以后；现有证据不支持现在启动大范围架构重写。

本轮评价：**已经从“关键探针无效”推进到“多数修复可信，但仍有并发遗漏与验收测量错误”。** 下一步应追求一个范围较小、可复现通过的交付版本，而不是继续扩大“全部完成”的表述。

## 5. 独立证据和范围

- [30 项定向 JUnit](weekly-recheck-round3-2026-09-08-evidence/targeted.xml)、[输出](weekly-recheck-round3-2026-09-08-evidence/targeted.txt)。
- [privacy 3 项 JUnit](weekly-recheck-round3-2026-09-08-evidence/privacy.xml)、[输出](weekly-recheck-round3-2026-09-08-evidence/privacy.txt)。首次 sandbox 启动 Chromium 为 spawn EPERM；允许启动后 3 项通过，环境失败不归为产品失败。
- [W3 输出](weekly-recheck-round3-2026-09-08-evidence/switch-observed.txt)、[线程在途观测](weekly-recheck-round3-2026-09-08-evidence/switch-overlap.json)、[观测包装脚本](weekly-recheck-round3-2026-09-08-evidence/observe_switch.py)。只在副本包裹请求和切换入口观察状态，不改变原探针的循环、等待或业务断言。
- [W4 默认编码日志](weekly-recheck-round3-2026-09-08-evidence/w4-default.txt)。
- [源码 manifest](weekly-recheck-round3-2026-09-08-evidence/source-manifest.json)：快照 `bd4a17f2`，969 个文件，复跑后与原树 SHA-256 核对 0 差异。
- [本次浏览器所用 dist 清单](weekly-recheck-round3-2026-09-08-evidence/tested-dist-manifest.json)：23 个文件；从当前本地 dist 复制，记录 SHA-256，本轮没有重新 production build，因此结果不等同于证明可从提交重建该 dist。

本轮测试全部在独立源码副本与合成库运行，没有改动生产代码、原测试、原探针和用户报告，没有提交或推送。执行子代理使用 gpt-5.6-terra 负责并发修复的独立审查与定向复现，主代理复核结论并汇总。

复现脚本的归档副本仅作证据，需放回独立源码副本的原位置执行：`observe_dns.py` 和 `observe_switch.py` 位于源码根，`metadata_race_repro.py` 位于 `scripts/perf/`。不要直接在原工作区或文档目录运行这些应用探针。定向 pytest 命令为 `python -m pytest -q -o addopts='' -p no:cacheprovider tests/integration/test_collection_service.py tests/unit/test_gen_ts_types.py tests/unit/test_low_batch_window.py tests/lan/test_route_policy_contract.py`；隐私命令为 `python -m pytest -q -o addopts='' -p no:cacheprovider -m e2e tests/e2e/test_webui_thumbnail_privacy_acceptance.py`，均在上述独立副本执行。
