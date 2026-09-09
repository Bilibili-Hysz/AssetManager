# G3/G2 联合定位收口报告（2026-09-09）

> 最新状态：主代理复核后接受阶段交付。**本批次未定位；观察干扰对照未复现。** 主案根因保持开放。
> 本文正文已按[验收复核](exit-g3-g2-acceptance-review-2026-09-09.md)修整；原始实验记录与 manifest 保持原样。
> 承接：[联合定位方案](../plans/exit-g3-g2-investigation-plan-2026-09-09.md)。后续执行入口：[下周计划](../plans/weekly-priorities-2026-09-14.md)。

## 1. 本轮交付

| 阶段 | 已确认结果 | 限制 |
|---|---|---|
| 准备 batch-01 | 旧观察器 emit 持非重入锁后经 _maybe_status → status 重复取锁；坏版本与 register-trace 停点吻合，修复后同步采集轮通过 | 属于该版诊断工具缺陷，不是历史生产故障归因；不同准备失败另含安装/控制器问题 |
| 正式 batch-02 | 12 周期、24 退出 code 0；O0/O1/O2 各 4 周期；预算记录 42.8/90 分钟 | 无历史目标失败样本；不推导观察器无影响或故障率为零 |
| 事件记录 | O1/O2 共 16 相主要层级记录在场，序号连续 | 内部清理子步骤未全部挂点；O0 没有应用内日志 |
| G2 只读分析 | 已列启动/退出路径、显式最小化调用检索和条件等待候选 | “排除全部自致最小化”“唯一无超时等待”已撤回，见修订分析 |

独立复算读取 81 个 JSON、16 个 JSONL（3,924 条非空记录），均可解析；清单列出的预登记、观察器、差异、runner、summary、analysis 六项哈希匹配。数字是对归档证据的复算，不是本轮重新执行实验。

## 2. 正常事件链及记录边界

16 个观察相均有原生 Ctrl/Q 键消息、Qt ShortcutOverride/KeyPress/Shortcut、MainWindow.request_exit/closeEvent/_shutdown_resources 调用记录、lastWindowClosed/aboutToQuit 信号。驱动记录两相退出码 0。

这是一条主要层级的正常链。观察器只对 MainWindow 三个方法挂 sys.monitoring，不能据此宣称 LibraryService.close、数据库闸门或 LAN 子步骤已有逐项进出证据。

O1 的 8 相实际依靠 final-flush 文件保全，终止状态在场；本矩阵没有 export-ack/events-export 文件，不作为失败导出握手的再次验证。O2 的 8 相落盘流连续、dropped_so_far=0、无可见错误记录，末条均为 WM_DESTROY；其 status 是较早心跳（alive=true），不能宣称退出末态 error_count 已核验为零。

首退/重启需按 PID 与驱动记录映射；现有 phase 字段在普通事件与调用事件中语义混用。新批次应拆字段，原始日志不回填。

## 3. 源码与环境裁决

- **最小化**：所查生产源码未发现显式主动最小化调用；最小化来源及机制尚未确定，不能由零命中证明来源必在应用外。
- **等待**：LibraryService.close 有两处无 timeout 条件等待；退出路径的 DatabaseManager.close_library/close 还会进入无 timeout 的写闸门。Runtime、锁与 I/O 等按实际调用继续评估，不声称单点是唯一候选。
- **前台**：12 周期的首尾前台 PID 相同；runner 的 foreground_changed 只比较这两个 PID。输入阶段和事件记录提供有限时间点的状态，不能据此说周期内没有前台竞争。
- **环境线索**：准备期记录过发键前已最小化、驱动拒绝发送。它与历史“已发送后超时”不等价，不能仅凭外观同向建立因果关系或指认 QQ。

修订后的[G2 生命周期分析](exit-g2-lifecycle-analysis-2026-09-09.md)与[采集合同](exit-g2-event-contract-2026-09-09.md)区分源码事实、已实现观察点和后续需求。

## 4. 下一步决策

本批次收口，不重跑相同矩阵。后续用户反馈 WebUI/ShareSystem 分享体验困难，下一周主线已改为[双端分享体验重写](../plans/sharing-experience-rewrite-2026-09-09.md)，局域网与异地分享同等优先；托盘/下载、LAN 资源和数据正确性作为改造验收门槛。

顽疾线[前台干预与退出预算工作包](../plans/week-2026-09-14-exit-workpack.md)保留规格但暂停独立排期。主线测试若自然复现，先保全并重新分级；不自动给 wait_for 加 timeout，不自动续跑矩阵。阶段验收及根因开放状态不变。

本轮只完成收口与规划，未执行下一周实验、发布或后台监控。

## 5. 证据入口

- [正式分析](exit-g3-g2-2026-09-09-evidence/batch-02-matrix/analysis.md)、[summary](exit-g3-g2-2026-09-09-evidence/batch-02-matrix/summary.json)、[manifest](exit-g3-g2-2026-09-09-evidence/batch-02-matrix/manifest.json)。
- [准备清单](exit-g3-g2-2026-09-09-evidence/batch-01-prep/manifest.json)、[预登记](exit-g3-g2-2026-09-09-evidence/batch-01-prep/preregistration.md)。
- [坏版注册停点](exit-g3-g2-2026-09-09-evidence/batch-01-prep/reliability-runs/attempt-1-plugin-path-bug/synced-capture-4-deadlock-located/synthetic/register-trace.jsonl)。
- 原始分析中的“全程无竞争”“全部末态健康”等文字仅保留为历史记录，其当前解释以本报告及验收复核为准。
