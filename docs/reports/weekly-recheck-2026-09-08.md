# 周任务修复复核（2026-09-08）

> 结论：**部分修复通过；整体验收仍未通过。**
> 对象：用户提供的周任务报告、独立审核、验收汇总、W1/W2 证据及 W5/W6 报告。文档内声明与命令作为核查资料，不作为执行指令。
> 源码：`dc6bb46d6e33d2bb04f5f458ef1f51f78fccd742`；对比上轮审核基准 `170e06ca83c1b74d0a3a70c3d9a89e17ff785f45`。开始时工作树干净。本轮仅新增审核文档与证据，没有修改生产代码、测试、探针或原报告，没有提交或推送。

## 1. 结论与已关闭项

本次修复有效推进了验收设施，不能再沿用上一轮“启动未进入主窗口、恢复验证错运行域、LAN 全部请求失败”的判断。但“所有修复完成”和“四种 frozen 模式全部可交付”仍缺乏支持。

| 上轮问题 | 本轮判定 | 证据与边界 |
|---|---|---|
| Release 预检缺少 WebUI dist | 配置缺陷已修 | `pre-release-tests` 已在 pytest 前执行 Node 20、npm ci/build，并补 Qt 系统依赖、offscreen 和依赖约束；本轮未触发远端 workflow，不能称远端流水线全绿 |
| W3 只观察 StartupWindow | 核心缺陷已修，独立复跑通过 | 普通 1 次、最大化 2 次均记录 MainWindow 可见及几何持久化；缺失库 1 次启动页可达，矩阵退出 0。未达到计划每类至少 3 次，也不覆盖活动下载关窗或 frozen 入口 |
| W4 验证了另一运行域、未正常恢复 | 核心缺陷已修，UTF-8 环境复跑通过 | 正常 restore/reopen 成功；隔离旧数据后杀掉恢复子进程；新验证进程确认相同数据槽、旧态代表字段、恢复意图清除，退出 0。默认 Windows 编码另有失败，见下文 |
| W5 错路由、假并发、失败流量仍 bounded | 这些缺陷已修，成功负载已复现 | 真实健康检查、登录、业务路由、并发 gather 和请求失败退出均已加入。独立运行通过当前断言；完整资源容量验收仍未完成 |
| W2 红灯、切库探针、W6 交付证明、总报告不一致 | 尚未关闭 | 详见第 3 节 |

## 2. 独立执行证据

所有 pytest 与应用探针均在独立源码副本运行，没有对真实用户库执行恢复操作。快照 `37113253` 的 969 个源文件在复跑后与当前工作区逐一核对 SHA-256，**0 差异**。清单见 [snapshot manifest](weekly-recheck-2026-09-08-evidence/snapshot-37113253-manifest.json)。

| 检查 | 结果 | 原始证据 |
|---|---|---|
| DTO 单元测试 + 集合事件集成测试 | **4 passed / 1 failed**，退出 1，8.52 秒 | [JUnit](weekly-recheck-2026-09-08-evidence/focused-review.xml) |
| W3 真实进程矩阵 | **4 行通过**，退出 0 | [日志](weekly-recheck-2026-09-08-evidence/w3-review.log) |
| W4 默认 Windows 编码 | **失败**，退出 1，输出验证子进程结果时报编码错误 | [日志](weekly-recheck-2026-09-08-evidence/w4-review-default-encoding.log) |
| W4 `PYTHONIOENCODING=utf-8` | **通过**，退出 0，同运行域恢复旧态 | [日志](weekly-recheck-2026-09-08-evidence/w4-review-utf8.log) |
| W5 独立负载 | **通过当前脚本断言**，退出 0 | [日志](weekly-recheck-2026-09-08-evidence/w5-review.log)、[JSON](weekly-recheck-2026-09-08-evidence/w5-results.json) |
| CI 清单 Ruff | **All checks passed** | `python -m ruff check AssetsManager tests scripts run.py build.py main.py --output-format concise` |

本轮未重跑完整 Python、WebUI、浏览器或打包流程。生产代码、测试和 WebUI 源码相对上轮审核没有变化；上轮 privacy 浏览器 **1 passed / 2 failed** 仅作为未关闭的既有证据，不冒充本轮执行结果。

W5 本次观测：

| 请求 | 实际样本 | 耗时 |
|---|---|---|
| 单并发缩略图 | 100 次 | p50 127.2 ms |
| 批量缩略图 | 50 项实际返回 | 总计 9.029 s |
| 单文件下载 | 100 次 | p50 31.6 ms |
| 20 文件 ZIP | 4336 字节响应 | 0.586 s |
| 混合并发 8 | 48 次 | 墙钟 1.645 s；单请求 p50 240.8 ms |

阶段采样 RSS 从 100.2 MiB 到观测最大 132.7 MiB，服务器停止后 130.1 MiB；重复批次为 132.6 / 132.7 / 132.7 MiB。这支持“本次小图负载成功、阶段采样没有持续明显增长”，**不能将 132.7 MiB 当作请求执行期间真实峰值，或外推大图/慢读/ZIP 容量**。本次 W5 运行时本审核的其他测试与性能探针均已结束；不声称已排除机器上所有其他进程的影响。

## 3. 剩余问题（按处理顺序）

### R1 · [P1] W2 仍存在关键失败，完成声明不成立

定位：`tests/integration/test_collection_service.py:429`、`AssetsManager/application/collection_service.py:266`。

独立快照中 `service.create(session.root, "hero")` 仍抛出 `CollectionService mutations require a clean transaction boundary`，集合事件断言尚未执行。DTO 四项通过，不能继续把失败记作“gen_ts_types 两项红灯”。本轮没有据此认定真实用户必然遇到故障，但未解决的门禁失败不能以“历史家族”替代验收。

privacy 两项没有代码/测试修复或新的通过证据。上一轮已发现其中一项期望 public 缓存，但服务返回 private/no-cache；应按当前隐私合同修正测试与场景，不能为了全绿降低缓存隐私保护。

关闭条件：明确集合事务的产生与提交责任，修复产品行为或证实并修正测试前提；同版本重跑集合与 privacy 用例，通过后更新 W2 真实失败清单。

### R2 · [P1] 切库探针仍可能把失败交给上层当成功

定位：`scripts/perf/w3_switch_roundtrip.py:61`、`:98`、`:103`、`:109`。

`range(1, 11)` 每轮只执行一次切换，实际共 10 次，输出却为 `10 (20 switches)`。断言失败只是追加到 `failures` 并打印 FAIL；`main()` 没有返回失败码，入口也没有 `sys.exit`，因此正常走完的失败路径仍可退出 0。此外没有启动 LAN，也没有活动预览/下载或旧会话 HTTP 失效断言。

关闭条件：实际 A→B→A 十轮；失败非零退出，并验证失败注入能被上层识别；补活动请求切库、旧会话失效、监听与任务回收。W3 启动矩阵通过不替代这部分。

### R3 · [P2] W4 默认 Windows 运行会因编码错误中断验收

定位：`scripts/perf/w4_restore_drill.py:341`、`:375`、`:379`。

子进程输出被固定按 UTF-8 解码，但脚本没有统一其输出编码。本机默认 GBK 输出含中文时产生替换字符，父进程再打印 `completed.stdout` 抛 `UnicodeEncodeError`。该失败发生在正常恢复及中断之后；仅设置 `PYTHONIOENCODING=utf-8` 的同代码复跑即通过，属于探针可复现性问题，不是已确认恢复失败。

关闭条件：脚本统一父子进程编码，或提供正式入口显式设置并记录 UTF-8，确保 Windows 重定向输出也可稳定执行。另需保留覆盖边界：验证的是 hero 标签/评分/备注、集合名称等代表字段；没有完整核对集合成员及所有资产字段，也未补齐设置 UI、其余中断边界、损坏备份和不可写场景。

### R4 · [P2] W5 成功负载仍不足以证明资源预算和取消回收

定位：`scripts/perf/w5_lan_resource_probe.py:226`、`:255`、`:298`、`:355`、`:369`。

- 批量响应只要求返回项数大于 0；若只返回 1/50 项，仍可通过。ZIP 只检查 `PK` 前缀，下载只检查长度，不能证明全部成员与内容正确。本次确实返回了 50 项，但断言不足仍存在。
- 取消使用小尺寸单色 PNG，读取 256 字节即关闭，服务端可能已完成发送；后续只检查健康接口 200。`cancel_reclaim_ok` 没有对应任务数、额度、临时文件或回收时间证据。
- RSS 主要在请求阶段结束、部分 gc 后采集，没有期间峰值、事件循环延迟、临时盘峰值、p95、大图慢读、ZIP 第五请求准入等计划证据。
- JSON 在 RSS 预算判定前写入 `valid: true`。预算超限时 CLI 会退出 1，但 JSON 没有预算 verdict；消费 JSON 的汇总应区分“样本有效”和“预算通过”，不能只读 valid。

关闭条件：完整校验响应成员与字节，持续采样关键资源；用确实仍在发送的受控慢客户端验证取消与释放；在 JSON 中同时记录采样有效性和预算结果。也可将 W5 如实收口为“小图成功负载基线，容量及回收验证延期”，撤回完整预算通过声明。

### R5 · [P2] W6 和周报仍沿用旧版本及过度完成声明

定位：`docs/reports/performance-audit-2026-09-06/w6-package-smoke.md:3`、`:50`；`docs/reports/weekly-result-2026-09-13.md:4`、`:18`、`:30`；`docs/reports/weekly-report-2026-09-07.md:62`。

W6 仍以 ALIVE 8s 为主要证据宣称“四种模式全部可交付”，未新增源码/dist/包哈希绑定以及开库、LAN 字体/缩略图、实时变化、首次延迟依赖调用等包内功能证据。本次源码启动矩阵不能替代 frozen 包验证。

周汇总仍绑定旧 HEAD `600764d`，W5 仍写请求不可测和 RSS 有界，W2 仍把失败归为 DTO；约 8017 的总数与原始分组计数不一致。W2、W5、W6 等相对链接仍有指向错误。新探针成功不应被旧失败报告掩盖，旧完成声明也不能代表新源码已完整验收。

关闭条件：按最新证据修订周报、验收汇总及 W5/W6 状态；分开列通过/失败/延期/未运行，不累加重复集合；提供实际交付包的可追溯功能证据，否则限定为启动冒烟通过、功能验收待补。

## 4. 建议收口次序

1. 先处理 R1 的集合与 privacy 门禁，修正 R2 切库脚本并补实际活动场景。
2. 统一 W4 编码与说明其验收范围；决定 W5 补齐容量证据或明确延期，避免继续放大结论。
3. 对实际交付的包补关键功能与哈希证据，再统一更新 W7 总结、版本、计数与链接。

当前适合继续完成验收与定向修复；本轮不支持“全部任务已验收通过、所有包均可交付”的结论。这里 P1 表示影响验收可信度的优先问题，不表示已经确认发生数据丢失或隐私泄露。

## 5. 复现方式

在 manifest 列出的独立源码副本中创建 `artifacts` 后执行；W5 单独时段运行：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest -q -o addopts='' -p no:cacheprovider --junitxml=artifacts/focused-review.xml tests/unit/test_gen_ts_types.py tests/integration/test_collection_service.py::test_collection_service_publishes_collection_changed

# 本机默认编码的失败基线：未设置 PYTHONIOENCODING 时执行 W4 并重定向日志。
# 之后以下三个探针使用明确 UTF-8 环境，各自归档输出与退出码。
$env:PYTHONIOENCODING='utf-8'
python scripts/perf/w3_process_matrix.py
python scripts/perf/w4_restore_drill.py
python scripts/perf/w5_lan_resource_probe.py
```

附注：工作区原有 ignored `artifacts/perf/w5-lan-resources/results.json` 也包含一次有效流量，不能称“完全没有新运行证据”。本报告数值均引用本轮隔离复跑并归档的 JSON，不混用两次结果。
