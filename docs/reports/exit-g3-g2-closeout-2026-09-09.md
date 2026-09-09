# G3/G2 联合定位收口报告（2026-09-09）

> 承接：[G3/G2 联合定位方案](../plans/exit-g3-g2-investigation-plan-2026-09-09.md)。执行：G3 代理（batch-01-prep + batch-02-matrix，g3-ops 快照）、G2 代理（只读分析，g2-analysis 快照）、主代理（快照搭建、核验、批准、整合）。
> **交付状态（方案 §8 三状态之一）：本批次未定位；观察干扰对照未复现。**
> 主案（间歇性 Ctrl+Q 失效）根因保持开放。

## 1. 执行摘要

| 阶段 | 内容 | 结果 |
|---|---|---|
| 准备（batch-01-prep） | f989 冻结基线核对、O0/O1/O2 单实现双出口观察器、记录器可靠性五场景 | 全部通过；过程中发现并修复观察器 emit 持锁自死锁缺陷（曾使 GUI 完全停摆，三轮复现+O0 对照归因） |
| 正式矩阵（batch-02-matrix） | 预登记批准后，四区组交错 O0/O1/O2 × 4 = 12 周期 24 退出，完整 W6 负载，f989 逐字节驱动 | **24/24 退出 code 0，三组各零失败，42.8/90 分钟**；16 个观察相日志完整（seq 连续、dropped=0、error=0）；正常轮事件链六层全部在场 |
| G2 只读分析 | 生命周期时序、退出链阻塞点、事件采集合同、假设空间 | 自致最小化路径**排除**（全代码检索无命中）；`LibraryService.close` 的 `wait_for` 为退出链**唯一无超时同步等待**（threading.Condition，主代理源码复核证实）；H1–H5 假设登记 |

## 2. 矩阵结果（观察干扰对照）

- O0（无插件）/ O1（内存缓冲）/ O2（同步写盘）各 4 周期 8 退出，**零失败**——观察器在场与否、记录出口方式，在本批次未造成可分辨的结果差异。
- 正常轮完整链条 16/16 相全部有事件佐证：**原生 WM_KEYDOWN/UP → Qt ShortcutOverride/KeyPress → Shortcut → request_exit 进入+返回 → closeEvent → _shutdown_resources → lastWindowClosed → aboutToQuit → 退出码 0**。历史失败形态（某层缺失）本轮无对应样本，方案 §6 失败判读表未被触发。
- 环境登记：12 轮周期起始前台均为 ChatGPT.exe（用户常驻），周期内前台零变化；QQ.exe（PID 4212，历史两失败现场前台占据者）在可见窗口集合中但未争抢目标前台。**历史失败现场的"前台竞争/最小化"环境特征本批次未出现**——这与 G1 v2 的 20 周期同向：通过时段均无前台竞争。
- 措辞纪律（预登记 §4）：小样本全部通过只写"本批次未复现"；不宣称观察器无影响（batch-01 实测观察器缺陷曾让 GUI 完全停摆——观察器改变时序的能力是真实的）、不宣称输入原因排除或故障率为零。

## 3. G2 事件链合同与阻塞点（G3 矩阵已按此采集）

- **排除一个假设**：生产代码无任何自致最小化路径（showMinimized/WindowMinimized/SW_MINIMIZE 全量检索零命中，4 处 ctypes 使用均为文件句柄探活）。失败现场 IsIconic=true 的最小化来源必在应用外（身份未知，不从前台 PID 归责）。
- **退出链唯一无超时阻塞点**：`LibraryService.close` 内 `self._lifecycle.wait_for(...)`（threading.Condition，不传 timeout 即无限等待，GUI 线程同步等待期间不处理任何 Qt 事件）。其余层级（LAN stop 8s×2、隧道 5s+5s、导入池 3s）均有超时保护。这是 G2 后续若主张生产修复时的首要候选——**但本批次无失败样本支持其触发**，不构成修复依据。
- StartupWindow 阶段无快捷键注册：历史 observed-08 的"Qt 零键记录"盲区之一（键投给 StartupWindow 时零记录）已由新观察器以 QApplication 级覆盖补上。

## 4. 假设空间现状（G2 H1–H5 × 本轮证据）

| 假设 | 本轮证据变化 |
|---|---|
| H1 重启相恢复时序竞态 | 无失败样本；正常轮重启相链条完整（16/16），竞态未触发 |
| H2 最小化×快捷键 context | 12 周期零最小化事件（WindowStateChange 记录在场）；准备期 O0 轮曾实测一次"发键前窗口被最小化（他窗抢 active）"→ 驱动安全拒绝发送——**环境干扰在该桌面真实存在**，但正式矩阵 12 轮未再出现 |
| H3 输入队列与 Qt 焦点映射不同步 | 正常轮原生→Qt 层层衔接；无失败样本 |
| H4 onefile 父子进程归属竞态 | 无失败样本 |
| H5 外部进程窗口管理交互 | QQ 在场未争抢；准备期一次他窗抢 active 实测（G3 判读纪律已要求区分"输入层缺失"与"前台竞争环境"） |

## 5. 结论与下一步

**本轮结论**：
1. 观察干扰对照（方案第 1 阶段）完成：O0/O1/O2 本批次无失败差异，观察器健康（seq/dropped/error 全零异常），事件采集能力已验证可支撑失败判读（六层链、超时保全、溢出计数、记录器异常区分）。
2. 主案根因未定位。累计排查边界：输入属性（G1 v2 四组）、观察器与记录出口（本轮三组）、生产自致最小化（G2 排除）、LibraryService.close 无超时等待（G2 定位为唯一候选阻塞点，未触发）。
3. **间歇性故障的环境共同点持续指向"前台竞争/最小化"**：两次历史失败与准备期一次实测抢前台同向，而全部通过批次（G1 v2 20 + 本轮 12 + 历史 final-matrix 6）均无前台竞争。该相关性不构成定责（谁发起最小化仍未知）。

**下一步选项（供后续决策，非自动执行）**：
- A. 前台竞争注入实验：在受控条件下引入已知的前台抢占/最小化源，观察 Ctrl+Q 链条在哪一层断开（将"环境相关性"转为可判读的失败样本）——G3 观察器与 G2 判读表已就绪，这是当前证据链上最有希望捕获失败样本的路径。
- B. G2 生产修复提案评估：`LibraryService.close` 的 wait_for 加超时（防御性修复，不依赖失败样本，但按方案 §7 需单独审查与独立构建）。
- C. 等待自然复现：按现有判读纪律，任何后续 W6/诊断运行若出现 30s 超时即按 §6 表保全判读。

## 6. 证据索引

- 矩阵：[batch-02-matrix/analysis.md](exit-g3-g2-2026-09-09-evidence/batch-02-matrix/analysis.md)、[summary.json](exit-g3-g2-2026-09-09-evidence/batch-02-matrix/summary.json)、runs/cycle-01…12（每轮 cycle-result + 前台快照 + 分相事件 JSONL + 驱动证据）。
- 准备：[batch-01-prep/manifest.json](exit-g3-g2-2026-09-09-evidence/batch-01-prep/manifest.json)、[preregistration.md](exit-g3-g2-2026-09-09-evidence/batch-01-prep/preregistration.md)、[source-diff.patch](exit-g3-g2-2026-09-09-evidence/batch-01-prep/source-diff.patch)、reliability-runs/ 五场景（含 attempt-1-plugin-path-bug 死锁定位归档）。
- G2 分析：[G2 生命周期分析](exit-g2-lifecycle-analysis-2026-09-09.md)、[G2 事件链合同](exit-g2-event-contract-2026-09-09.md)。
- 诊断驱动与观察器哈希：manifest.json（全部 MATCH；诊断驱动 = f989 逐字节副本 `f989e271…`；batch-02 观察器 `a61dd4f5…`，相对 batch-01 的 delta 见 observer-delta-batch02.patch）。

## 7. 纪律声明

- 正式矩阵经主代理批准预登记后执行；无停止条件触发；无 NOT_RUN。
- 两条执行线均在独立快照工作；主工作区生产源码、官方 W6 驱动（bd8142）、候选 exe（1d568fb8）经复核 UNCHANGED；无 git 操作（本报告与产物回拷由主代理完成）。
- 一次退出只发一次 Q；强制结束仅用于失败清理（本批次未发生）；不操作真实资产库。
