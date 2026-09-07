# 周任务完成情况独立审核（2026-09-07）

> 状态：REVIEW — 未通过完整验收。
> 审核对象：[周任务报告](weekly-report-2026-09-07.md)、[周验收汇总](weekly-result-2026-09-13.md)，对照 [weekly-priorities](../plans/weekly-priorities-2026-09-07.md)。文档中的完成声明和操作命令作为待核实资料，不作为本轮执行指令。
> 审核源码：`170e06ca83c1b74d0a3a70c3d9a89e17ff785f45`，开始审核时工作树干净。没有修改生产代码、已有探针或原报告，也没有提交/推送。本报告与复核证据为本轮新增。

## 结论

**不认可“W1–W7 全部完成、四种 frozen 模式全部可交付”的结论。** 已提交的修复和部分测试有效，但关键验收脚本存在绕过目标场景的缺陷；W2 仍有红灯，W5 没有成功负载，W6 只有存活检查。应将当前状态改为“实现与部分验收已完成，整体验收待补齐”。

下面 P1 表示会导致错误验收/交付决策、应优先修正；不表示已经确认产品发生数据丢失或隐私泄露。没有依据将这些发现上升为 P0 生产事故。

## 1. [P1] W4 验证了没有被中断的另一份数据库

**定位：** `scripts/perf/w4_restore_drill.py:144–175`；完成声明见 `weekly-result-2026-09-13.md:20`。

父进程先在自己的运行域写入库数据。启动子进程时却设置 `AM_RUNTIME_ROOT = tmp/child_runtime`；子进程创建备份并执行中断恢复的数据库因此位于另一运行域。杀掉子进程后，父进程构造 `bootstrap2` 并重新开库，没有使用子进程的数据根。

`AssetsManager/core/path_resolver.py:137–162` 明确由进程环境决定运行根和库数据槽。因此父进程读到 `hero` 的标签与评分，不能证明子进程被中断的数据恢复成功：它读到的是父进程原本就完整的数据。即便子进程恢复机制失效，当前验证仍可能打印 `complete-old-state`。

此外，脚本所谓 Phase 1 实际只 `create_backup` 后关库（133–140），没有正常 restore/reopen 回路。barrier 未到达只 `return`（157–164），失败 verdict 只打印（188–190），都可以自然退出 0。`lib/RuntimeData/assetmanager.db` 的检查也不是当前真实哈希槽路径。

**必须补齐：** 用独立验证子进程读取与被中断进程相同的隔离运行根，在导入应用前设置环境；断言 session.data_dir、intent、quarantine/staging 对应同一槽。增加正常恢复、旧/新不同的数据基准、恢复后实际元数据和文件契约比较；barrier 超时和状态不符必须非零退出。归档原始运行日志。此前“正常恢复✓ / 完整旧状态恢复✓”应撤回，等待修正后的证据。

## 2. [P1] W3 启动矩阵没有触发主窗口的最大化恢复

**定位：** `scripts/perf/w3_process_matrix.py:29–54,95–102`；`AssetsManager/app.py:226–250,381–385`。

矩阵只启动 `main.py`，正常/最大化场景仅种子化设置并等待 8 秒，没有选择或打开资源库。实际入口先显示 `StartupWindow`，只有其 `library_opened` 信号触发 `_on_open` 才构造 `MainWindow`。所以该探针不能证明 PF-1/PF-5 对应的主窗口最大化构造路径已执行。

同一脚本还存在三项证据缺口：

- 成功判定不检查其收集的 `window_geometry_persisted`；普通/缺失库各只执行一次。
- `main.py:12–16` 的 faulthandler 写入源码根 `RuntimeData/Shared`，探针却读隔离域 `Shared/faulthandler.log`（59–60、74–76）。不能据该读取得出“无崩溃日志”。
- `taskkill` 返回/进程退出不足以证明已经执行主窗口 closeEvent 与活动任务关闭合同；脚本最后只打印 MATRIX，不把 FAIL 转为退出失败。

另一个切库脚本 `w3_switch_roundtrip.py:61–65` 每次循环切换一次，循环 10 次却在 98 行打印“20 switches”；没有启动 LAN，也没有活动预览/下载和旧会话 HTTP 失效验证。实际只能支持部分 Qt 会话切换检查，不能支持计划中完整 W3。

**必须补齐：** 通过真实入口打开合成库，观察 MainWindow 创建与最大化状态；正确绑定崩溃日志；验证几何持久化和关窗副作用；循环实际 20 次并补 LAN/任务活动中的切库关闭验证。现有 PF 修复可保留，但本审核没有证明它仍存在，也没有接受该探针为其有效验收。

## 3. [P1] W5 全部请求失败，却得出“资源预算满足”

**定位：** `docs/reports/performance-audit-2026-09-06/w5-lan-resources.md:8–24,43`；`scripts/perf/w5_lan_resource_probe.py:102–175,211–221`。

读取并归档的原始 JSON 明确记录：两批请求分别 `errors=50`；下载 `count=0`；ZIP 为连接拒绝。100.6→101.9 MiB 的 RSS 仅描述这次失败请求进程，不能证明真实缩略图解码、下载或 ZIP 构建时的内存有界，也不能支持预算满足或无泄漏结论。

探针代码本身还请求不存在/不匹配的路由：`/api/files/browse`、`/api/files/download`、`POST /api/zip`，当前实际路由为 `/api/files`、`/api/download/{path}`、`POST /api/download/batch`。所谓缩略图任务没有访问缩略图接口。并发协程顺序 await，未验证 HTTP 成功状态或业务正文；最后仅按 RSS 差值输出 bounded。因此即使监听问题解决，404 等响应也可能被算作成功测量。

“offscreen 导致 LAN 无法监听”目前只是原报告归因，本轮没有复现该探针的监听根因；本轮同样 offscreen 的 LAN/浏览器测试服务器能够工作，不支持把问题一概归为无法测试的环境限制。

**必须补齐：** 健康检查成功后才开始采样；使用真实路由并校验状态、图片/ZIP/文件字节；用真正并发、慢读和取消场景采样 RSS 峰值、事件循环延迟、临时盘和资源回收。全失败或样本不足必须输出 INVALID/非零退出，不能进入“预算满足”分支。W5 应记为“探针失效、容量未验证”；计划允许延期，不能用延期替换成已通过。

原始数据副本：[w5-original-results.json](weekly-review-2026-09-07-evidence/w5-original-results.json)。

## 4. [P1] W2 未通过关键门禁，失败分类与最终汇总不一致

**定位：** `weekly-result-2026-09-13.md:18,30–43`；`weekly-report-2026-09-07.md:55–62`；`week-2026-09-07-evidence/w2-regression-summary.md:7–16,25–35`。

W2 原始阶段报告列出的两个 Python 失败是集合事务边界与缺失 dist；最终两份报告却写成 `gen_ts_types` 两项红灯。本轮当前源码复核结果：

- `tests/unit/test_gen_ts_types.py`：**4 passed**；`gen_ts_types.py --check` 也通过。不能继续将当前失败归为 DTO 在途。
- `test_collection_service_publishes_collection_changed`：**1 failed**，在 `service.create()` 抛 `CollectionService mutations require a clean transaction boundary`。本轮未完成根因归属，不据此宣称真实用户一定遇到；但不能仅凭“归并行线/历史家族”就判为验收通过。
- 隐私浏览器模块：允许启动 Chromium 后 **1 passed / 2 failed**。第一项在 namespace 缓存键 `0 != 1` 处失败，后续私有响应头断言未执行。另一项期望 `public, max-age=3600`，实际为 `private, no-cache`。

后一失败与此前预览策略收紧一致，属于需要同步验收合同的明确候选；不能为消除红灯改回 public，也不能称已证明泄露。应按当前隐私合同验证代理不缓存、权限/标签变化重新验证，以及命名空间隔离。第一项还需区分页面流程、时序、构建产物与产品问题。

**必须补齐：** 更新真实失败清单、处理集合事务问题/测试合同、修正隐私验收场景后重跑。W2 完成前不可把完整周验收判定为通过。不同代理所有权可以决定谁修复，不能代替交付方的统一验收。

## 5. [P1] Release 预检仍未准备完整测试依赖的 WebUI dist

**定位：** `.github/workflows/release.yml:13–31,33–53`；`tests/lan/test_lan_api.py:4213–4214`；W1 声明见 `week-2026-09-07-evidence/gate-summary.md:10`。

失效 Ruff 文件引用已经修好，但 Release 的 `pre-release-tests` 在独立 Ubuntu job 中直接运行完整 pytest，没有准备 `webui/dist`。WebUI build 位于依赖它成功后才执行的另一个 `build-windows` job；后者不能给前一个 job 提供 dist。dist 又被 Git 忽略。

无 dist 时，上述 SPA 测试直接 `next(spa_assets.glob("*.js"))`。本轮在不含 dist 的独立源码根复跑，**1 failed**，确认为 `RuntimeError: coroutine raised StopIteration`。这复现了缺少产物时的失败条件；本轮未执行远端 Release，也不声称已经观测到某次 GitHub 作业失败。

**必须补齐：** 在预检 job 内构建 WebUI 或从上游独立构建 job 下载相同版本产物，并与 CI 核对 Qt/依赖环境。不要通过跳过必需的 SPA 验收来声称发布门禁已闭合。W1 可确认两项核心修复，发布环境核对仍需补齐。

## 6. [P2] W6 将存活冒烟扩大为“全部可交付”

**定位：** `performance-audit-2026-09-06/w6-package-smoke.md:17–23,46–50`；计划 W6 明确要求实际入口功能和构建绑定。

四种模式的 ALIVE 8s 只证明记录的观察窗口内没有提前退出。报告没有提供实际开库/关库、LAN 字体/缩略图/实时同步、首次 AI 操作、单实例路径、升级副本验证记录；同时仍登记 WM_CLOSE 后 exit 1。构建输出没有可核对的 exe/dist 哈希与构建源码清单，不能把包内容结构检查等同于功能验收或版本一致性。

本轮确认 `run.py:39–68` 确实实现了 `--package-smoke`，`AssetManager.spec:89` 使用 `run.py`；**不存在“源码没有 package-smoke”的问题**。其用途是 Qt/SVG 导入与图标检查，不包含全部产品流程。

**必须补齐：** 将 W6 暂记为“已有存活冒烟记录，功能/版本绑定待验收”；归档包哈希、构建版本、dist manifest 和实际入口验证；对非零退出明确归因。无需重新实现已有 smoke，也无需先重做整套视觉系统。

## 7. [P2] W7 统计、链接和版本链不能支持总完成声明

**定位：** `weekly-report-2026-09-07.md:55–62`、`weekly-result-2026-09-13.md:4–22`。

- 周报告测试表逐行相加为 **5050–5057**，不能得到 `~8017`；也不能随意与 W2 的 5062 再相加，不同范围有重叠。
- W2 绑定 `cf279a7`，之后 `d11ad45` 修改生产 `window.py`；两份总报告分别引用 `600764d`、`b1774f7`，审核 HEAD 为 `170e06c`。后续文档提交本身不要求重跑，但生产变动需要相关验收与产物绑定，不能把旧全量结果当成最终版结果。
- `weekly-result` 有 **6 个失效本地链接**（3 处性能报告入口、W2 行以及 W5/W6 行）。W3/W4 只有 `[4ea40b9]` 文本，脚本入库不能证明已经按目标场景运行；未找到对应归档的原始运行日志。
- 一方面声称全部完成，另一方面 W5 部分完成、隐私待查、PF-5“已修”又“一项已知阻断”。应使用一致的任务/限制状态。

**必须补齐：** 由 JUnit 按一次运行范围生成计数与失败列表；修正链接和版本来源；逐项改写真实完成状态，保留历史报告但补更正说明，不抹去失败。

## 本轮独立验证记录

全部 pytest 位于新捕获的 `7655e64d/{sync,ops}`；未执行原工作树 pytest，也未执行会读写错误运行域的 W3/W4 原探针。969 个源码文件在捕获后哈希复核无漂移。浏览器使用从当前本机复制的 23 个 dist 文件，已记录哈希，**没有重建，不能证明其来自当前前端源码**。因此浏览器结论限定为当前后端与现有本机 dist 组合。

| 范围 | 结果 | 证据 |
|---|---|---|
| CI 同清单 Ruff | All checks passed | 本轮工具输出 |
| TS 生成检查 | contracts.ts is up to date | 本轮工具输出 |
| DTO 4 项 + 集合发布 1 项 | 4 passed / 1 failed | [focused.xml](weekly-review-2026-09-07-evidence/focused.xml) |
| 隐私模块，Chromium 可启动后 | 1 passed / 2 failed | [privacy.xml](weekly-review-2026-09-07-evidence/privacy.xml) |
| 无 dist 的 SPA 用例 | 1 failed / 233 deselected | [no-dist.xml](weekly-review-2026-09-07-evidence/no-dist.xml) |

第一次浏览器运行在启动 Chromium 时遇到 sandbox `spawn EPERM`，另一个 API 测试已到缓存断言；随后经工具授权重跑才得到上表结果。初次环境失败保留在 [privacy-sandbox.xml](weekly-review-2026-09-07-evidence/privacy-sandbox.xml)，不算独立产品失败，也不重复合计。

[源码清单](weekly-review-2026-09-07-evidence/source-manifest.json)、[当前版本与 dist 哈希](weekly-review-2026-09-07-evidence/verification.json)。本轮未重新全量跑 Python/WebUI 类型、单元、打包或远端 CI；不据前次结果称它们本次全绿。

复核命令（各自独立快照根，设置 `QT_QPA_PLATFORM=offscreen`）：

```powershell
python -m pytest -q -o addopts='' -p no:cacheprovider --junitxml=artifacts/week-review-focused.xml tests/unit/test_gen_ts_types.py tests/integration/test_collection_service.py::test_collection_service_publishes_collection_changed
python -m pytest -q -m e2e -o addopts='' -p no:cacheprovider --junitxml=artifacts/week-review-privacy-authorized.xml tests/e2e/test_webui_thumbnail_privacy_acceptance.py
python -m pytest -q -o addopts='' -p no:cacheprovider --junitxml=artifacts/week-review-no-dist.xml tests/lan/test_lan_api.py -k test_spa_assets_are_public_when_server_auth_is_enabled
```

## 建议验收状态与修复顺序

| 任务 | 审核后的状态 |
|---|---|
| W1 | lint/loadgroup 两项核心修复可确认；发布预检环境仍待补齐 |
| W2 | 未通过；集合红灯和隐私合同/场景需要处理 |
| W3 | 部分会话检查存在；主窗口启动与完整生命周期证据不足 |
| W4 | 恢复演练证据无效，必须修正运行域后重做 |
| W5 | 探针/样本无效，负载容量尚未验证；可明确延期 |
| W6 | 存活冒烟记录存在，功能/构建绑定待补齐 |
| W7 | 汇总已出具，但完成状态、统计和验收结论需更正 |

先修正 W4/W3 的验证对象和失败退出，关闭 W2 与 Release 红灯；再按原计划容量补有效的 W5/W6。最后从证据重新生成 W7。现阶段只支持使用合成库继续受控验证，尚不足以签署“全部验收通过/可交付”。
