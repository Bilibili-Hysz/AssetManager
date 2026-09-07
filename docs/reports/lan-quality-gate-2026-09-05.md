# LAN 优化质量复审与下一轮记录（2026-09-05）

更新：2026-09-06，完成 ZIP 响应移交窗口、排队取消及响应交付后的关闭/删除时序修复。

## 结论与范围

上一轮初审不通过：存在读取预算失效、部分 ZIP 伪成功、大文件下载回归和正常浏览误限流。上述问题修复后，LAN 完整回归与架构、打包配置门禁通过，进入下一轮 ZIP 协作取消改进。当前改动保留在工作树，未提交或发布。

本轮只修改文件快照、LAN 下载/分享/限流/ZIP 及其测试；同期桌面前端改动由其他任务负责，不纳入本报告验收。

## 发现与修复

| 问题 | 修复 | 主要证据 |
|---|---|---|
| 仅打开时检查大小，文件不断增长仍可能读到无限 EOF | 快照迭代器按已打开句柄的初始大小限制累计读取；结束时核对长度与身份；失败关闭句柄 | `test_stream_quality_review.py`：增长、截断 |
| ZIP 成员写入失败后仍返回带部分内容的归档 | 任一源读取、写入、身份校验或目录扫描失败使整个归档失败并删除临时文件；显式关闭源迭代器 | 同文件：写盘失败、读取中修改、扫描失败、源消失 |
| ZIP 的 500 MiB 限制只依赖事前路径估算 | 对实际打开的每个成员重新准入，累计执行 500 MiB 源字节预算 | 同文件：累计超限、恰好等于边界 |
| 普通/分享下载拒绝超过 64 MiB 的正常文件 | 使用拥有安全句柄的 `SafeFileResponse`，每次最多读取 1 MiB，支持大文件；逐块检查身份，最后一块发送前再次检查 | `test_file_response.py`：两个真实 HTTP 下载超过 64 MiB；限制分块读取量 |
| 下载响应、取消及配额拒绝可能遗留句柄 | 失败、取消、请求完成时关闭句柄；异步打开在请求取消后才完成时也关闭其结果 | 同文件：prepare/write/cancel、迟到打开、配额拒绝与不可用 |
| HEAD 按完整下载处理 | 返回长度与响应头，不读取正文、不增加单文件/分享下载次数 | 同文件：HEAD 后仍可使用一次性分享 |
| 已登录用户连续加载图片也命中 120 次/分钟限流 | 成功认证的凭据摘要在有限容量和短 TTL 内豁免未知凭据探测预算；每次请求仍执行认证、撤销与权限检查 | `test_credential_budget_review.py`：150 并发媒体请求、撤销、随机凭据、TTL |
| 公开或无认证路由携旧凭据也被计数 | 预算使用与认证链相同的启用条件；缺失 limiter 时在装配阶段明确创建 | 同文件：真实 `_build_app` 装配、public/no-auth、凭据来源优先级 |

另修复普通下载已计算但未发送的配额响应头，并允许尚未 prepare 的流式响应附加限流头。

## 首轮最终门禁

以下数字是各次运行的结果，集合有重叠，不累计为独立测试总数。

```powershell
python -m pytest tests/lan tests/core/test_package_contents.py tests/unit/test_architecture_boundaries.py tests/unit/test_build_installer.py -n 2 --basetemp=.pytest-tmp-quality-gate-1 -o cache_dir=.pytest-cache-quality-gate-1 -q
```

结果：**879 passed, 2 skipped，exit 0**。两项跳过是本机 Windows 无创建符号链接权限（WinError 1314），并非这些平台场景已验证。

变更生产代码与测试的 Ruff 检查通过；8 个变更生产代码文件 Pyright 为 0 errors、0 warnings。`python run.py --package-smoke` exit 0；这是入口冒烟，没有生成安装包。

## 下一轮已实施：ZIP 协作取消

`build_zip_async` 为每次请求创建独立取消事件；协程取消时把事件传给后台 worker。worker 在开始、目标/目录/文件遍历和分块写入边界检查事件，停止继续压缩、关闭源句柄并删除临时归档。保留原有完成回调清理作为兜底。取消返回不会把尚在运行的线程伪装成已经排空。

新增 `test_zip_cancellation.py` 验证：

1. worker 开始前已取消时不打开源文件。
2. 在真实压缩流程首次读取暂停后取消；释放后只读取一个 32 字节测试块，关闭源句柄并删除归档。
3. 真实单线程 executor 被占用时取消排队请求，worker 随后执行也不会打开源文件。

独立复核还发现：ZIP 已生成、等待配额检查时取消，原流程尚未把清理责任交给响应，因此临时文件会残留。目录和批量下载现已使用所有权 `finally`，在成功移交响应前统一负责清理；`test_zip_response_cleanup.py` 使用真实 ZIP 构建，覆盖两条路径的配额等待取消、意外配额异常、响应构造失败和 cookie 设置失败，共 8 项。

```powershell
python -m pytest tests/lan/test_zip_response_cleanup.py tests/lan/test_zip_cancellation.py tests/lan/test_stream_quality_review.py tests/lan/test_helpers.py tests/lan/test_l3_thread_resources.py tests/lan/test_free_download_quota.py -n 2 --basetemp=.pytest-tmp-quality-round2-final -o cache_dir=.pytest-cache-quality-round2-final -q
```

结果：**64 passed, 1 skipped，exit 0**；跳过原因同上。最终变更生产代码和测试 Ruff、8 个生产代码文件 Pyright 均通过。

2026-09-06 收尾后再次执行完整门禁：

```powershell
python -m pytest tests/lan tests/core/test_package_contents.py tests/unit/test_architecture_boundaries.py tests/unit/test_build_installer.py -n 2 --basetemp=.pytest-tmp-quality-final-0906 -o cache_dir=.pytest-cache-quality-final-0906 -q
```

结果：**891 passed, 2 skipped，exit 0，134.94 秒**。跳过仍为上述 Windows 符号链接权限限制。`git diff --check` 通过。当前两轮改动通过上述范围的门禁，不代表后续清单或完整产品发布验收已经完成。

## 第三轮：ZIP 响应关闭与删除顺序

已新增 `lan/temporary_file_response.py`，用独立线程安全 owner 管理临时 ZIP 的打开、句柄登记和清理：

- 在 aiohttp 后台 `_make_response` 返回前登记句柄，避免取消期间丢失迟到结果。
- 取消发生在打开期间时先记录清理意图，等打开完成后由 worker 关闭句柄并删除文件。
- 正常发送或 prepare 失败时显式完成句柄关闭，再删除文件；不依赖 aiohttp 自身异步关闭任务的完成速度。
- 请求任务结束但响应从未进入 prepare 时，由任务完成回调兜底清理。
- 继续继承 aiohttp `FileResponse` 的 Range、HEAD 和条件请求处理。旧 `write_eof` 删除包装已移除，相关测试改为真实打开后 prepare 失败的契约验证。

验证证据：

1. 将 Git HEAD 的旧 helper 仅注入测试进程，打开前/打开后取消的两项测试均复现未关闭句柄；没有回退生产文件。
2. `test_temporary_file_response.py` **13 passed**：真实 GET、206、HEAD、304、412、416、空文件；prepare 失败；单线程与双线程执行器的取消顺序；未 prepare 的响应。
3. `test_zip_response_cleanup.py` 补充延迟 aiohttp 自身 close 的确定性测试：该 close future 仍未完成时，我们持有的句柄已经关闭、文件已经删除。
4. 完整 LAN API + 配额 + ZIP 响应清理集合 **260 passed**。变更代码与测试 Ruff、生产代码 Pyright 通过。

第三轮最终完整门禁：

```powershell
python -m pytest tests/lan tests/core/test_package_contents.py tests/unit/test_architecture_boundaries.py tests/unit/test_build_installer.py -n 2 --basetemp=.pytest-tmp-quality-round3-final -o cache_dir=.pytest-cache-quality-round3-final -q
```

结果：**905 passed, 2 skipped，exit 0，127.61 秒**。两项跳过仍为 Windows 符号链接权限限制。该轮关闭/删除时序修复通过验收，后续工作进入全局任务与临时盘预算。

兼容性边界：`_make_response` 是本类唯一覆盖的 aiohttp 内部打开钩子。未来升级 aiohttp 时必须运行这些 HTTP 与取消契约测试；本轮不修改 aiohttp 依赖版本。

## 第四轮：进程 ZIP 资源预算

实现范围与初始容量见 `docs/plans/zip-resource-budget-2026-09-06.md`。

- 进程内最多 4 个在途 ZIP，每份固定预留 512 MiB，总预留最多 2 GiB。预算覆盖扫描、排队、压缩和响应传输；多个 LAN 应用与服务重建共用同一实例。
- `ZipReservation` 的独立引用句柄保证重复释放幂等。扫描 worker、压缩 worker 和临时响应各自持有必要引用；请求取消不会提前返还仍被占用的资源。
- 压缩 worker 在自身 finally 或原生 Future 回调中清理、释放。请求事件循环已经关闭时仍能完成收尾；排队任务取消也归还预算。
- 临时响应成功删除文件后才执行释放回调；关闭/删除失败时保留预算。小归档同样占用一份固定预留，这是当前保守容量策略。
- 共享 `scandir` 遍历限制 10,000 个成员、100,000 个扫描条目（包括选中根、dot-name 与链接项）和 64 层目录；提前中断会关闭扫描句柄。估算与打包遵循同一规则，保留原有 dot-name 隐藏规则。
- 源数据继续限制为 500 MiB；实际归档每次写入都检查末尾 offset，不超过 512 MiB，涵盖压缩 flush、头部改写、空归档尾记录与中央目录。
- 容量不足在扫描和临时文件创建前返回 `503 / zip_capacity_exhausted`，附带 `Retry-After: 1`。单请求超限返回不带本机路径的 `413 / zip_limits_exceeded`。普通单文件下载不占 ZIP 名额。

定向证据包括预算多线程竞争、同句柄并发释放、扫描/压缩取消后旧事件循环关闭、执行器排队取消、实际响应删除后归还、目录/batch失败路径、扫描与输出预算精确边界。新增实际 Windows junction 测试通过；这不替代尚未验证的所有 Windows 路径替换竞态。

`test_zip_budget_http.py` 对目录和批量下载进行真实 HTTP 验证：四个已构建归档暂停在发送前，计数保持 4 个名额/2 GiB，第五个请求返回 503 与 Retry-After；放行并验证四份 ZIP 内容、等待实际响应清理后计数归零，后续请求重新成功。该测试不替换预算、扫描或 ZIP 构建。

第四轮最终完整门禁：

```powershell
python -m pytest tests/lan tests/core/test_package_contents.py tests/unit/test_architecture_boundaries.py tests/unit/test_build_installer.py -n 2 --basetemp=.pytest-tmp-quality-round4-final -o cache_dir=.pytest-cache-quality-round4-final -q
```

结果：**967 passed, 2 skipped，exit 0，122.34 秒**。两项跳过仍为 Windows 符号链接权限限制；新增真实 junction 测试通过。变更生产代码和 LAN 测试 Ruff、变更生产代码 Pyright 通过；`python run.py --package-smoke` exit 0；`git diff --check` 通过。此轮资源预算通过上述范围验收。

## 后续轮次与验收要求

| 顺序 | 范围 | 交付与验收 |
|---|---|---|
| 1 | ZIP 崩溃遗留回收与容量测量 | 第五轮已增加当前进程内的受控重试及管理员诊断，详见 `zip-cleanup-recovery-2026-09-06.md`。后续设计进程崩溃后遗留归档回收，并通过 RSS、耗时和实际磁盘数据决定是否调整固定预留。 |
| 2 | 预览快照与策略一致性（第六轮已实施） | 内容验证和响应使用同一份字节，缓存摘要对应实际响应，策略收紧与旧缓存隔离详见 `preview-snapshot-consistency-2026-09-06.md`。Windows 原子打开策略仍待单独验证。 |
| 3 | 测量与运维 | 为传输记录实际发送字节、取消与失败阶段，验证慢客户端下的峰值内存与事件循环延迟；用可重复基线决定并发默认值。 |

## 当前证据边界

- 64 MiB 仍是需整块处理的图片源字节上限，不是解码像素、总内存或并发预算；本轮没有做 RSS 压测。
- 分块传输无法撤回已发送字节。源文件变化会中断连接；已经准入的下载在中途失败后仍消耗次数。普通/分享单文件下载未新增 Range/断点续传；ZIP 保留原有 Range 行为。
- 身份检查使用设备、inode、大小和 mtime，不等价于不可变内容快照；未声称解决全部 Windows 路径替换竞态。
- 已认证凭据豁免的是未知凭据探测预算，不是认证缓存，也不是全局 CPU 预算。
- ZIP 取消在边界协作生效，不能强制中断正在阻塞的操作系统读写或压缩调用；已开始的估算可能继续到有界扫描结束，期间仍占用名额。
- 2 GiB 是本进程在途归档的预留和文件输出额度，不是跨进程磁盘配额，也不覆盖崩溃遗留文件、文件系统元数据或其他程序的磁盘占用。删除失败不虚假返还额度；第五轮已增加当前进程内的重试，仍没有跨进程持久恢复与崩溃遗留回收。
- 未修改或验收同期前端视觉开发，也未执行完整桌面 E2E、浏览器 E2E 或安装包实机验证。
