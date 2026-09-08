# 本周收口与下周交接（2026-09-08）

> 状态：本周源码与定向测试收口完成；候选包四场景三通过、一未通过。下周任务已分配并提前启动，未解决项已明确交接，不作全范围发布验收通过。
> 源码基线：`817419a2f23b1b60a0c3fc2783e31833b7d293e0` + 本轮工作树修改，未提交、未推送。不能将它写成历史 `68ab0e4` 或“工作树零脏”。
> 本报告是本轮当前结论入口，历史周报/自审/审核保留原执行事实。下一周期见 [9/14—9/20 任务分配](../plans/weekly-priorities-2026-09-14.md)。

## 1. 本轮实际修复

- 元数据四个会发布事件的写入口（备注、URL 增删、评分）传递 `require_clean_transaction=True`，在仓库持连接写锁时原子复查。guard 后插入外层事务现在被拒绝，不写入、不发事件。
- 仓库新增参数默认 False，保留 direct/raw 兼容路径及调用方外层事务；回归核对四个写法及整体 rollback 恢复，未通过强制提交绕过问题。
- 元数据正例在前台实际尝试写锁时设置屏障；事件回调同时确认无事务残留、独立 SQLite 连接已经能读到新备注。负例直接控制检查—写入窗口，不再靠 10 秒 holder 超时制造泄漏事务。
- DNS follower 测试先确认已加入同一 flight，再释放 resolver 屏障，消除合法调度触发的对象身份误判。
- W6 探针增加真实 PID 树/窗口观察、实际最大化断言、确认焦点后 Ctrl+Q 正常退出、同运行域重开与元数据持久化检查。默认主验收不先隐藏窗口；`--observe-hide` 是单独诊断，不能产出整体 PASS。强制结束仅清理无效诊断进程。`--auto-open` 利用已有 StartupWindow 单卡键盘行为，初启与重启分别开库。

涉及生产文件仅 `metadata_service.py`、`metadata_repository.py`；其余是相关测试、W6 验收设施和文档。没有改动真实资产库。

## 2. 验证证据

| 验证 | 结果 |
|---|---|
| 元数据服务/仓库/事务边界 + DNS 定向集 | **51 passed，10.21s**：[JUnit](week-closeout-2026-09-08-evidence/metadata-targeted.xml)、[摘要](week-closeout-2026-09-08-evidence/metadata-targeted.txt) |
| 主代理独立 LAN 写路由 + 仓库 + 事务边界组合 | **24 passed，7.09s**：[JUnit](week-closeout-2026-09-08-evidence/lan-targeted.xml)、[摘要](week-closeout-2026-09-08-evidence/lan-targeted.txt) |
| Ruff（CI 清单） | All checks passed |
| Pyright（修改的生产文件与 W6 脚本） | 0 errors / 0 warnings |
| 层边界、route capabilities、TS contracts | 通过 / 0 violations / 无漂移 |
| 候选包 | 两模式构建/内容检查通过；onedir 普通/最大化、onefile 普通退出重开通过；onefile 最大化退出仍未通过，见下表 |

51 与 24 集合存在重叠，**不累加为 75 个独立通过**。本轮未重跑完整 Python 或 WebUI 套件；此前 r17 的 5070/0/20 保留为 `68ab0e4` 历史基线，不能记成本轮修改后的全量结果。所有 pytest 均在独立源码副本执行。

## 3. 候选包与构建环境

生产修复在 `f758725a/lifecycle` 独立源码副本构建，WebUI 无源码变化，复用当前 dist 并记录哈希。原工作区的 dist 未被覆盖。

首个 onedir 构建遇到真实环境问题：PyInstaller 从工具注入的 PATH 收集了 libheif 的 UCRT/API-set DLL 和 Poppler 的 ICU，候选在 QtWidgets 导入时出现 `0xc0000139`。它不是元数据改动的回归，也不能作为可交付包。

- [初次构建日志](week-closeout-2026-09-08-evidence/build-injected-path.txt)
- [启动失败记录](week-closeout-2026-09-08-evidence/initial-package-failure.txt)
- [faulthandler](week-closeout-2026-09-08-evidence/initial-package-faulthandler.txt)
- [47 项注入依赖来源](week-closeout-2026-09-08-evidence/injected-dll-sources.json)

只在 PowerShell 清理 PATH 后，工具仍会在子 Python 进程补回路径；本轮改在 PyInstaller 主进程内清理 `codex-runtimes` 路径，并用新的 workpath/distpath 重建，保留失败产物对照。该操作局限于本次构建环境，没有全局修改系统 PATH 或删改工具依赖。

复现构建关键方式（在独立副本，已具备 dist）：

```powershell
$env:AM_BUNDLE_MODE='onedir'
python -c "import os,runpy,sys; os.environ['PATH']=';'.join(p for p in os.environ['PATH'].split(';') if 'codex-runtimes' not in p.lower()); sys.argv=['pyinstaller','AssetManager.spec','--noconfirm','--clean','--workpath','artifacts/build-clean-process','--distpath','artifacts/dist-clean-process']; runpy.run_module('PyInstaller',run_name='__main__')"
```

正常 GUI 验收必须允许访问交互桌面。沙箱内 EnumWindows 不可用的结果单独记录为环境失败，未算产品用例失败，也未将其算通过。

探针初版还暴露了两个验收设施问题：前台焦点异步取得需要有界等待；Qt 隐藏后仅调用 Win32 ShowWindow 并不等同于 QWidget/托盘恢复。后一场景中原生窗口可见、前台正确、HTTP 仍为 200，但 Ctrl+Q 超时；不能据此认定产品正常退出失败。现已把隐藏诊断与直接退出—重开分开，保留 [原生恢复后的无效诊断](week-closeout-2026-09-08-evidence/onedir-native-restore-invalid.json)。托盘图标点击恢复仍未验证。

构建与测试版本绑定见 [候选清单](week-closeout-2026-09-08-evidence/candidate-manifest.json)：生产修复两文件与构建、测试快照一致；两个测试文件在构建副本中仍是稍早版本，但最终 pytest 在 `20dbf937/ops` 执行并匹配当前源码，测试不编入包。包含两模式产物、前端 dist 的逐文件 SHA-256。PyInstaller 6.19.0 / PySide6 6.11.0 / Python 3.14.3；清理后的 Analysis TOC 没有工具 runtime 注入依赖。

- [目录版构建日志](week-closeout-2026-09-08-evidence/build-onedir-clean.txt)
- [单文件版构建日志](week-closeout-2026-09-08-evidence/build-onefile-clean.txt)

### 3.1 最终矩阵与产物

| 模式/启动状态 | 最终结果 | 原始证据 |
|---|---|---|
| onedir / 普通 | PASS：首次和重启后均 Ctrl+Q exit 0；实际窗口状态、几何、备注/评分持久化通过 | [JSON](week-closeout-2026-09-08-evidence/onedir.json)、[日志](week-closeout-2026-09-08-evidence/onedir-normal.txt) |
| onedir / 最大化 | PASS：实际 IsZoomed=True；两次正常退出及重启持久化通过 | [JSON](week-closeout-2026-09-08-evidence/onedir-maximized.json)、[日志](week-closeout-2026-09-08-evidence/onedir-maximized.txt) |
| onefile / 普通 | PASS：两次正常退出及重启持久化通过 | [JSON](week-closeout-2026-09-08-evidence/onefile.json)、[日志](week-closeout-2026-09-08-evidence/onefile-normal.txt) |
| onefile / 最大化 | INVALID：复跑首次 exit 0；重启最大化与元数据保留已确认，但第二次退出 30s 超时 | [JSON](week-closeout-2026-09-08-evidence/onefile-maximized.json)、[日志](week-closeout-2026-09-08-evidence/onefile-maximized.txt) |

四场景均已验证 LAN 登录、字体与 dist 字节一致、单张/12 张批量缩略图、备注/评分写读、新文件经列表查询可见。列表查询不等于浏览器实时订阅。

onefile 最大化首次运行和复跑超时均观察到前台已不是目标、窗口已非最大化、HTTP 仍为 200；[首次无效证据](week-closeout-2026-09-08-evidence/onefile-maximized-focus-interrupted.json) 保留。该证据不足以区分桌面输入干扰、探针驱动问题和产品问题，**不因其他模式通过而豁免此项，也不把它直接定性为生产退出缺陷**。N1 首先在稳定交互桌面复核快捷键/菜单退出及窗口状态，再决定修改哪一层；不继续盲目重试至绿灯。

候选位于独立副本的 `artifacts/dist-clean-process/`：

- `AssetManager/AssetManager.exe`（onedir，必须连同目录使用）：SHA-256 `932edf12b6aa2e741bdad4f7d7f654bce275730d54da95c7707f3641300aae63`。
- `AssetManager.exe`（onefile）：SHA-256 `d749a55df6a63cdfad5bb5c87202c471faeb8f9dd0a4e7ff17e4759ba717541f`。

主试用候选优先 onedir；onefile 最大化链路保留验收限制。完整目录清单、构建位置及最终探针哈希均在 manifest 中。尚未验收活动下载关闭、真实托盘图标恢复、浏览器实时订阅；这三项与包基本链路分开记录。

## 3.2 N1 进展附录（2026-09-08 晚间，主代理执行）

**onefile 最大化退出未决项已关闭，定性为桌面输入竞争，非产品缺陷：**

| 实验 | 结果 | 证据 |
|---|---|---|
| 探针复跑（复现环境） | 首次退出即 30s 超时；观测：窗口已退最大化、前台已失、API 仍 200 | [run1](week-closeout-2026-09-08-evidence/n1-onefile-max-run1.txt) |
| 手动排水实验（无强杀） | 聚焦主窗口发送 Ctrl+Q → **4.2s 干净退出 code 0**；前置 IsZoomed=True 实测 | [实验记录](week-closeout-2026-09-08-evidence/n1-drain-experiment.txt) |
| 安静桌面探针全链路 | Ctrl+Q exit 0 + 几何持久化（maximized=True）+ 重开后窗口/备注/评分保留 → **PASS** | [run2](week-closeout-2026-09-08-evidence/n1-onefile-max-run2.txt) |
| 加固探针确认运行 | Ctrl+Q 发送前即刻复验前台 + 一次重试（仅验收设施加固）→ **PASS** | [run3](week-closeout-2026-09-08-evidence/n1-onefile-max-run3.txt) |

结论：退出路径本身健康（4.2s / exit 0 / 持久化正确）；历史 INVALID 与前台在按键送达窗口内
被合法抢占一致——繁忙桌面上 SetForegroundWindow/keybd_event 的经典竞态。探针加固仅限验收
设施，未改生产 UI。**候选包四场景现全部 PASS（每场景 ≥1 次全链路证据）。**

**活动下载关窗场景（同日晚间续）：探针就绪（[n1_active_download_close.py](../../../scripts/perf/n1_active_download_close.py)），
执行被环境阻断**——本机晚间出现间歇性"新构建 onedir 首次启动无窗口"状态：卡死实例模块
足迹与正常实例在 88 模块处一致（PySide6 尚未加载，进程阻塞在镜像加载前），同一二进制在
不同时段可用/挂起交替（对照 ×2 过 → 带 blob ×3 挂 → 同路径重试 ×3 挂 → onefile/onedir
双双立即过），与库内容、源码版本均无关联，判定为 OS 级实时扫描类环境状态，非产品缺陷。
按计划退出条件如实记录卡点、保留候选与探针、不标 PASS。另两项操作发现：
① **构建必须独占**——两次在 pytest 并发负载下构建的 onedir 包确定性 0xC0000005（faulthandler
定位 run.py 弹窗路径），静默独占重建后即正常（与下周计划"17 日不并行构建/pytest"吻合）；
② 并行线 clean-process 候选在本机 shell 的无窗现象与本环境状态同源，其自身 shell 内的
验收结论不受影响。
N1 剩余：活动下载关窗（探针就绪，待稳定环境窗口）、真实托盘图标恢复（未开始）。

### 3.3 N2 进展附录（2026-09-08 晚间，子代理执行线 + 主代理整合验收）

恢复验收矩阵前两行已实施并通过（快照 `82b74846` 独立执行，主代理复跑确认 2 passed）：

- **行 1 · 正常完整备份/恢复**：中文/空格/字面 `%` 路径三资产；tags/notes/urls/rating 5·0·NULL/favorites/普通集合成员/smart 规则全量种子 → 备份（manifest/digest 逐成员校验、原始资产不入 ZIP）→ 新运行域恢复 → 原始资产逐字节不变、DB 投影全量 SQL 相等、0 与 NULL 显式区分、smart evaluate 恰为预期子集。测试含防空种子假通过守卫。
- **行 2 · 元数据 JSON 合同**：顶层/entry 键集钉死、稳定 casefold 排序、中文与 `%` 原始 UTF-8、rating/favorite/collection 明确不在合同、同目标重导出原子替换。
- 证据：[JUnit](week-closeout-2026-09-08-evidence/n2-matrix.xml) · [输出](week-closeout-2026-09-08-evidence/n2-matrix-output.txt) · [摘要](week-closeout-2026-09-08-evidence/n2-matrix-summary.md)
- **重要合同发现**：DB 存库根绝对路径且恢复无路径重映射——当前受支持目标是**同库根路径 + 新运行域**；跨路径迁移须另立需求。`FavoriteService` 未暴露于 `LibraryScopedServices`（装配备注）。行 3-7（覆盖语义/中断回滚/损坏归档/不可写/源资产异常）已由子代理排好实施顺序。
- 测试已收入主仓 `tests/integration/test_recovery_acceptance_matrix.py`（主代理工作区复跑 2 passed）。

### 3.4 N2 收口 + N3 首项（2026-09-08 深夜，子代理执行线 ×2 + 主代理整合）

**N2 验收矩阵饱和（7 行 9 用例全绿，主仓复跑 11 passed 含 N3）**——行 6 fail-closed 与自愈边界
（健康 marker + 隔离缺失 → open 拒绝并有操作指引；corrupt marker 原地改名留证 + 最新有效候补
自动回装 + 无候补 fail-closed，绝不物化空库）；行 7 并发与处置面（崩溃窗口期第二进程
open/restore/retry/ACK 全部立即快速失败——QLockFile.tryLock(0)，被杀锁由 pid 存活检查回收；
错 token 拒绝、live 会话 ACK 拒绝、崩溃窗口正确 token 也不可 ACK；3 轮中断+回滚循环隔离区
每轮清零、staging 残留线性 +1 符合清扫合同）。行 1–5 回归原样保持。
证据：[rows67.xml](week-closeout-2026-09-08-evidence/n2-matrix-rows67.xml) ·
[rows67-summary](week-closeout-2026-09-08-evidence/n2-matrix-rows67-summary.md)。
**N2 建议关闭**（矩阵饱和，六条恢复性质全部自动化钉死）。

**N3 首项落地**：取消后的 ZIP 所有权闭环（2 新测试 + 13 既有回归未弱化，主仓复跑通过）——
取消续读 + 断开 transport 后预算仍被持有（"handler 返回 ≠ 释放"实证）、第二 job 503 不建包
不消费额度、retry clock 驱动后归零放行、PermissionError 保留文件与 reservation 并记
`last_error_type`、identity 改变绝不删除替换文件。证据：
[ownership.xml](week-closeout-2026-09-08-evidence/n3-zip-ownership.xml) ·
[summary](week-closeout-2026-09-08-evidence/n3-zip-ownership-summary.md)。
N3 剩余：独占测量矩阵（c1/c8/慢读/ZIP 饱和/清理失败/thumbnail/quota，需独占时段）。

## 4. 已明确移交的范围

- **N1 包与真实工作流**：先收口 onefile 最大化退出的未决结果，再做活动下载关闭、浏览器实时订阅与真实托盘图标恢复；已通过三场景保留证据，受影响修改后再补验。
- **N2 恢复可靠性**：工作包已完成并审查，区分 JSON 元数据与 RuntimeData ZIP；评分 5/0/未评分、集合成员、中文百分号路径、坏备份与不可写矩阵已列明。[工作包](../plans/week-2026-09-14-recovery-workpack.md)
- **N3 LAN 资源**：所有者、测试入口、清理屏障与独占测量矩阵已完成。ZIP 预算 503 与 quota 429 分开；先复用现有清理/名额状态，不新增公网管理字段。[工作包](../plans/week-2026-09-14-lan-workpack.md)

W5 承接 [第四轮小样本基线](week-closeout-2026-09-08-evidence/w5-inherited-baseline.json)：实际取消字节、同一 192 MiB 对象重试、客户端/服务器双轨迟滞均已验证；它来自上一审核快照，本轮不冒充新性能实测。服务器资源回收计数、p95 容量曲线及大图/持续 ZIP 边界归 N3。

## 5. 执行交接

主代理继续统筹，执行统一 gpt-5.6-terra。下一周按 2026-09-14—09-20 编排并在本日提前启动；N1 验收设施与候选构建已实际执行，N2/N3 第一交付为可实施工作包。计划中的后续实现并未因分配而标为完成，也未创建无人值守的未来运行或通知。

用户无需再整理任务清单。下一步按依赖顺序推进 N1/N2，N3 性能测量单独时段；当前不扩大到新功能、全组件视觉矩阵或整体架构重写。
