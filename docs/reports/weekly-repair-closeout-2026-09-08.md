# 汇编复核修整与最终收口（2026-09-08）

> 后续更新：本文保留上一批次事实。后续输入驱动修复后，受控 W6 六项包验收已通过，当前结论和历史失败见 [退出验收驱动修复报告](exit-repair-2026-09-08.md)。唯一根因未确定，托盘等其余发布场景不在该矩阵内。
> 当时状态：源码修整与证据收口完成；目录版退出重开验收通过，单文件最大化重启退出仍阻断，不能宣称发布验收全部通过。
> 基线：`103f119d3100bfe4350f770015180782af87e974` 加本轮未提交修改；未提交、未推送。
> 对应发现：[汇编独立复核 F1—F5](weekly-consolidated-review-2026-09-08.md)。本页保留该批次结论，后续 W6 处置见上方链接。

## 本轮范围

修复测试进程清理归属、活 owner 识别与 echo、活动下载验收判据；补原恢复矩阵的不可写与源资产审计负例。最终测试、源码与候选包按同一批次哈希绑定。所有 Python 测试和构建均在独立源码副本，GUI 仅使用合成库；原工作区和用户资产不作为演练对象。

## 处置与验证

| 发现 | 本轮处置 |
|---|---|
| F1 测试清理越界 | 探针移入 main，已有同名进程时明确拒绝且不触碰；仅可清理本次启动的 PID 树 |
| F2 活 owner 误判 | 复用 LibraryLock/QLockFile 确认同运行域所有权，IPC 不决定准入；预缓冲 ping 立即排水，断开后释放连接引用；锁建立失败显示独立错误并返回 1 |
| F3 活动下载假通过 | HTTP 200、源长度/Content-Length、部分消费屏障、暂停/恢复读取、断连或显式截断、正常退出及 worker 结束共同决定结果；完整传完、任意异常或超时不能通过 |
| F4 包版本漂移 | 冻结当前源码，独立构建两模式，记录生产输入、前端 dist、探针、测试与包的哈希，旧包结果保留为历史 |
| F5 原恢复矩阵漏项 | 补 staging 创建、旧态隔离、安装三点不可写；补资产删除/篡改两项验收审计。旧的自愈/并发扩展保留独立编号 |

恢复失败用例核对了旧态的文件 digest 与数据库投影、主异常和次级清理异常；并分别验证立即重试或 fail-closed 后显式 ACK 再重试。新增资产审计只在测试端判定 missing/changed，不修改产品格式。

定向执行：单实例 14 项后补 2 项合同，恢复矩阵 14 项，探针合同先 8 项后补已有实例保护用例，分别在独立副本通过；与最终全量重叠，不相加作为独立总数。

第一轮整合为 5107 passed / 1 failed / 20 skipped。唯一失败为字体证据中 `app.py` 字号调用的定位行号 230→274；逐项核对字体调用、字号表达式和单位没有变化，只更新清单的行号。保留 [首轮 JUnit](weekly-repair-2026-09-08-evidence/full-suite-before-inventory-fix.xml) 和 [输出](weekly-repair-2026-09-08-evidence/full-suite-before-inventory-fix.txt)，修后全量及真实包结果另行列示。

第二轮为 5108 passed / 1 failed / 20 skipped，发现已有 LAN 测试仅关闭 SQLite、未注销其测试连接归属，后续对象 id 复用触发 bootstrap 检查失败。现改为冻结 aiohttp 清理信号、执行应用已注册的 cleanup，并断言注册记录已删除且连接已关闭；未清空全局注册表或放宽 bootstrap 断言。前置 LAN→bootstrap 加探针合同复跑 **11 passed**。保留 [第二轮 JUnit](weekly-repair-2026-09-08-evidence/full-suite-before-fixture-fix.xml) 与 [输出](weekly-repair-2026-09-08-evidence/full-suite-before-fixture-fix.txt)。

### 最终源码验收

- 最终全量：**5110 passed / 0 failed / 20 skipped，143.55s**。[JUnit](weekly-repair-2026-09-08-evidence/full-suite-final.xml)、[输出](weekly-repair-2026-09-08-evidence/full-suite-final.txt)。跳过项保持平台限制（OpenGL、Windows 符号链接权限等），未通过改 marker 或放宽断言取得结果。
- 完整 Ruff、完整 Pyright、探针 Pyright、文档统计/维护、分层、边界、路由能力、TS 契约、Web token 生成共 10 个命令均返回 0：[静态结果](weekly-repair-2026-09-08-evidence/static-checks.json)。更早 audit-manifest 门禁没有注册对象，不将空检查算作证据完整性证明。
- [源码清单](weekly-repair-2026-09-08-evidence/source-manifest.json) 记录 302 个生产/构建输入、405 个测试/探针文件、23 个 dist 文件与依赖版本。生产输入与构建副本逐字节相同；未改测试文件可能因 git archive 与工作树换行格式不同，清单同时记录两种哈希并验证规范化文本一致。
- 最终 `AssetsManager/app.py` SHA-256：`3e1b21510c3b1bce136725a0131fb70b7b3d1324253786f9f6bd0507fd6cb78f`。生产输入在全量之后没有再变更；后续调整仅涉及 GUI 探针就绪/按键驱动及其合同测试，单独记录验证范围。
- 最终探针合同复跑 **10 passed**：[JUnit](weekly-repair-2026-09-08-evidence/final-probe-contracts.xml)、[输出](weekly-repair-2026-09-08-evidence/final-probe-contracts.txt)。新增窗口就绪用例发生在全量之后，未冒称 5111 项全量；它与已有 9 项探针用例合计 10 项定向验证。源码清单保留全量执行时输入，最终 helper 哈希见候选清单；活动下载记录保留其当时执行的独立 helper 哈希。
- 收尾再次执行 11 个静态命令及 diff check，全部返回 0；核对 302 个生产输入摘要未变、当前报告本地链接无缺失：[最终静态记录](weekly-repair-2026-09-08-evidence/final-static-checks.json)。

## 当前候选与真实包验收

交付目录：`artifacts/weekly-repair-2026-09-08-103f119/`。该批次是 `103f119` 加本轮生产修复的独立构建，不能仅凭目录中的 HEAD 短号推断为原始提交产物。前端沿用清单内已有 dist，本轮未更改前端。

| 模式 | 相对交付目录的入口 | EXE SHA-256 |
|---|---|---|
| onedir | `AssetManager/AssetManager.exe` | `6afcf6635c59119f321e9e441972bb991f3cb3678110669401f87d5c72578f12` |
| onefile | `AssetManager.exe` | `1d568fb80ef6dcb78f9d8001ea68c521367638938a3463cf2964e51960372c5a` |

[候选清单](weekly-repair-2026-09-08-evidence/candidate-manifest.json) 逐一核验 262 个构建文件与交付副本一致，并绑定源码清单摘要与最终探针哈希。启动后额外生成的空 `faulthandler.log` 单列为运行时文件，不充当构建输入。构建前从 Python 进程的 PATH 中移除 Codex 附带运行时，Analysis 清单无该运行时引用。两模式 [onedir 内容检查](weekly-repair-2026-09-08-evidence/contents-onedir.txt)、[onefile 内容检查](weekly-repair-2026-09-08-evidence/contents-onefile.txt) 均通过；保留 [onedir 构建日志](weekly-repair-2026-09-08-evidence/build-onedir.txt) 与 [onefile 构建日志](weekly-repair-2026-09-08-evidence/build-onefile.txt)。

### 活动下载中退出

新 onedir 包真实执行 **PASS**：[原始输出](weekly-repair-2026-09-08-evidence/activity-final.txt)、[输入哈希](weekly-repair-2026-09-08-evidence/n1-active-download-evidence.json)、[结果](weekly-repair-2026-09-08-evidence/n1-active-download-result.json)。响应 HTTP 200、Content-Length 与源文件同为 201326592 字节；消费 1048576 字节后建立屏障，暂停读取并调用 Ctrl+Q。正常退出码为 0，客户端恢复读取后记录 `ConnectionResetError/WinError 10054`，总消费仍为 1048576 字节，worker 已结束；本次退出及客户端收尾观察共 18.34 秒，小于 60 秒观察窗。

此结果证明本场景中的正常退出、部分传输与客户端终结，不证明服务端各类资源计数归零，也不扩展到 onefile 的活动传输场景。

### 包退出复核的未通过项

最终保留的驱动下，目录版普通与最大化的两次正常退出、重开、备注评分及实际窗口状态均通过：[普通结果](weekly-repair-2026-09-08-evidence/onedir-normal-final.json)、[最大化结果](weekly-repair-2026-09-08-evidence/onedir-maximized-final.json)、[普通输出](weekly-repair-2026-09-08-evidence/gui-onedir-normal-control.txt)、[最大化输出](weekly-repair-2026-09-08-evidence/gui-onedir-maximized-control.txt)。后文批量驱动的失败不能作为该最终驱动的执行结果。

**剩余阻断：onefile 最大化重启退出 INVALID。** 最终驱动下首次正常退出为 0，最大化/几何保存成功；重启后的窗口与备注评分恢复成功，随后 Ctrl+Q 30 秒未完成。[最终结果](weekly-repair-2026-09-08-evidence/onefile-maximized-final.json)、[完整输出](weekly-repair-2026-09-08-evidence/gui-onefile-maximized-control.txt)。异常清理只结束该测试自有 PID 树，不计为正常退出。当前目录版可作限定范围的验证候选；单文件完整验收不通过。

相同新包在较早按键驱动下取得 onedir 普通/最大化、onefile 普通窗口的通过记录，分别保留为 [onedir 普通](weekly-repair-2026-09-08-evidence/pre-batch-onedir.json)、[onedir 最大化](weekly-repair-2026-09-08-evidence/pre-batch-onedir-maximized.json)、[onefile 普通](weekly-repair-2026-09-08-evidence/pre-batch-onefile.json)。它们不能覆盖后续出现的无效运行，也不能合成为“稳定通过”。

复核尝试将 Ctrl+Q 改为 ABI 校验后的批量 SendInput，但没有证明改善。该驱动下 onedir 普通重启退出、onedir 最大化首次退出、onefile 最大化首次退出均出现 30 秒未完成：[普通重启](weekly-repair-2026-09-08-evidence/batch-onedir-normal-invalid.json)、[目录版最大化](weekly-repair-2026-09-08-evidence/batch-onedir-maximized-invalid.json)、[单文件最大化](weekly-repair-2026-09-08-evidence/batch-onefile-maximized-invalid.json)。单文件的一次超时观察中目标仍在前台、窗口非最大化、LAN 仍响应；不能只归因于焦点被抢，也不能据这些外部输入记录直接断言生产 request_exit 已执行却挂死。缺少的是对快捷键实际派发及退出入口触发的观测。

为避免保留未经证实有效的修改，最终撤回批量 SendInput，恢复既有按键发送实现；保留 API 就绪后稳定自有窗口的检查。过程中使用库路径标题作为就绪条件也被否定并移除：workspace 在 MainWindow 连接 directory_changed 前恢复，初始标题事件可能已错过，因此重启后的简短标题合法地存在。保留 [标题误判运行](weekly-repair-2026-09-08-evidence/onefile-maximized-invalid-readiness.json) 与 [批量驱动早期运行](weekly-repair-2026-09-08-evidence/onefile-maximized-invalid-batch.json)，不将它们计作产品失败或通过。

**交付判断：** F1—F3 的修复、F4 的重新构建与版本绑定、F5 的缺失合同补验已完成；F4 所涉及的两模式完整包试用声明仍不予批准。当前提供可追溯的候选和明确的模式边界。下一周期优先工作已在 [N1 分配](../plans/weekly-priorities-2026-09-14.md) 列出：固定 onefile 最大化重启场景，区分输入驱动、窗口状态和实际退出流程，再决定生产修复；该阻断处理前不扩大 N3 测量。

## 交付边界

- 单实例所有权按运行数据域隔离：相同 AM_RUNTIME_ROOT 互斥，不同域可并行。旧包没有这一 owner lease，不能保证新旧版本混跑互斥；使用新版接管日常运行前应正常关闭旧版。
- RuntimeData ZIP 保存运行数据，不包含库根原始资产；源资产删除/篡改检查属于验收工具的 digest 审计，不新增产品备份承诺。
- 本轮活动下载验收不代替 N3 的服务端资源计数、容量曲线或长期性能测量。
- 真实托盘图标恢复与浏览器实时订阅仍需各自场景，列表轮询不能替代订阅验证。
- 较早 r19 全量和旧包的通过仅属于其原执行版本，本轮结果独立列示，不跨轮累计。
