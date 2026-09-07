# 当前代码状态核查（2026-09-07）

> 状态：DATED ASSESSMENT · 核查日期：2026-09-07（Asia/Shanghai）。本文记录当前工作树，不等于 HEAD 的发布状态。配套执行计划：[一周重点工作](../plans/weekly-priorities-2026-09-07.md)。

## 1. 判断

项目已经具备较完整的资产管理能力和分层结构：Qt 桌面与 React WebUI 共享 Python 应用服务，库会话管理 SQLite、文件索引和后台任务，LAN 提供认证、预览、下载、分享和实时失效通知。当前主要工作应转向**整合现有修复、证明关键用户流程可靠、建立同一源码版本的验收记录**。

现有代码不支持“需要重写架构”的判断，也不能仅凭分批测试通过就宣称可以发布。最近几批变更同时涉及启动、窗口事件次序、切库回滚、元数据保留、LAN 传输和测试设施，交叉验证比继续扩展功能更紧要。

本轮只增加核查与计划文档、证据文件及导航入口；未修改产品代码、未提交或发布，也未操作真实资产库。

## 2. 核查基准与范围

- HEAD：`b9ad72e27b5194df71818616b76c86ace1393a55`；分支 `master`。
- 核查开始时有 **57 个已跟踪文件发生修改**。新增 LAN 实现、测试、图集及报告另在未跟踪项中；不能以 `git diff --stat` 代表完整交付范围。
- 与此前 `0ce0406` 台账相比，已有桌面性能与视觉相关提交；工作树还包含 `app.py`、`ollama_client.py` 的延迟导入、`search_service.py` 的路径解析优化，以及 `window.py` 的启动次序调整。
- 从当前代码捕获独立源码快照 `0d87daf0`，含 **965 个源码/配置/资源文件**；不复制用户 RuntimeData。仅在其 `sync` 根运行本轮 pytest。
- 验收后逐项比对 965 个文件，**无源码哈希漂移**。捕获脚本并非发布打包器：不覆盖 Git 元数据、全部文档、完整 WebUI 构建配置和生成 dist，不能当成发布包清单。
- 本机 Python 3.14.3；类型检查为本机执行。未查询远端 CI 状态，也未运行 Windows 安装包、完整测试矩阵、真实桌面交互或负载测试。

证据：[工作树信息与关键哈希](project-state-2026-09-07-evidence/workspace.json)、[源码清单](project-state-2026-09-07-evidence/source-manifest.json)、[哈希与 JUnit 核对](project-state-2026-09-07-evidence/verification.json)。清单中包含本机路径和样本环境信息，分享报告时可只导出必要部分。

## 3. 本轮实际执行结果

| 检查 | 结果 | 解释 |
|---|---|---|
| 隔离快照的 7 个模块/选择器组合 | **82 passed / 0 failed / 0 skipped** | 覆盖路径解析、pytest 隔离、切库失败恢复、runtime events、DTO 生成及字面百分号下载；不是全仓库测试 |
| `python -m pyright` | **0 errors / 0 warnings** | 当前本机配置；工具升级提示不是类型错误 |
| WebUI `npm run typecheck` | **exit 0** | 仅类型检查，本轮未重跑 Vitest/build/浏览器 |
| 边界、路由能力、前端数据访问、TS 契约生成检查 | **均通过** | 路由和前端检查分别 0 violation；TS 无漂移 |
| `git diff --check` | **exit 0** | 当前已跟踪 diff；此前 EOF 空行问题本轮未再出现 |
| 与 CI 完全相同的 Ruff 路径清单 | **exit 1，唯一报告 E902** | `setup_cython.py` 不存在；这是可复现的门禁配置错误，不能写成 Ruff 全绿 |

pytest 命令（在 `0d87daf0/sync` 中设置 `QT_QPA_PLATFORM=offscreen` 后运行）：

```powershell
python -m pytest -q -o addopts='' -p no:cacheprovider --junitxml=artifacts/week-assessment.xml tests/core/test_path_resolver.py tests/test_support/test_runtime_isolation.py tests/integration/test_window_switch_failure_recovery.py tests/integration/test_runtime_events.py tests/unit/test_gen_ts_types.py tests/lan/test_lan_api.py::test_download_route_serves_filename_with_literal_percent
```

JUnit：[assessment-82.xml](project-state-2026-09-07-evidence/assessment-82.xml)。静态检查命令及结果摘录：[checks.md](project-state-2026-09-07-evidence/checks.md)。本轮串行抽样不构成 xdist 并行安全证明。

## 4. 确认的问题与优先级

### C01 · CI/Release 引用已不存在的 lint 文件（本周优先）

`.github/workflows/ci.yml:27`、`.github/workflows/release.yml:26` 均运行：

```text
ruff check AssetsManager tests scripts run.py build.py main.py setup_cython.py
```

当前根目录没有 `setup_cython.py`，本轮执行同等命令返回 `E902 / os error 2`。因此按当前树重跑这些步骤会失败；这不等于已查看 GitHub 上某次运行失败。应同步清理两处失效引用，并检查发布预检与 CI 的依赖、Qt 系统库和 WebUI dist 准备是否一致。后者是待核对项，本轮没有实际执行 Linux 发布作业。

### C02 · 并行分组承诺与调度器不一致（本周优先）

`pytest.ini:11` 使用 `--dist worksteal`，注释承诺带 `xdist_group("serial")` 的 8765 端口测试不会并行；`tests/lan/test_server_lifecycle.py:12-14` 也依赖该假设。

本机安装的 xdist 在 `WorkerInteractor.pytest_collection_modifyitems` 中，仅 `config.getvalue("loadgroup")` 为真时才给 nodeid 加分组标记。已保存[本机实现摘录](project-state-2026-09-07-evidence/xdist-group-source.txt)。当前配置不能提供其注释声称的分组保证；本轮没有人为制造端口碰撞，也不把所有生命周期测试都当成真实 socket 测试。

修复选择：短期使用 `loadgroup` 对需要串行的测试分组，或独立串行执行固定端口模块；长期尽量让真实服务器绑定动态端口。仅改注释或增加更多 marker 不解决保证缺失。RuntimeData 隔离也不隔离 TCP 端口。

### C03 · 已修复行为与当前整合版本的证据尚未完全闭合

B00–B05 台账保存了丰富的分批证据，但与新增启动、搜索和 LAN 工作树变更没有同版本完整验收。本轮 82 项提高了可信度，仍缺当前树的完整后端、WebUI、实际桌面和 frozen 环境组合。

优先验证 PF-1：当前 `window.py` 确实在 `_restore_window_geometry` 前初始化背景及淡入状态（约 226–244 行），因此应补“最大化状态保存后重启”的真实进程验收，不能重复报告其仍未修复。延迟导入还应验证首次 AI 操作和打包后的依赖发现，不能只测启动时间。

### C04 · 开发台账存在证据表达漂移

旧台账仍有“下一批优先 B00”与“B00 已完成”并存、人工抄写哈希不准确等问题。例如实际 `tests/conftest.py` 哈希为 `D5B517B923B60816B81A04A9589C55579F17A900D55D3C8DAD72239E332CC80A`，应以本轮生成清单为准。今后以脚本生成的清单绑定源码，叙述说明版本和限制，减少人工长哈希复制。

## 5. 已有能力与仍需验证的边界

| 领域 | 当前代码/已有证据 | 下一步需要证明的内容 |
|---|---|---|
| 删除与撤销 | B01 已带评分快照及旧格式兼容测试 | 在当前整合版本验证真实文件与标签、备注、评分恢复 |
| 切库与关窗 | B02 补偿、禁用与重试流程已经实现；本轮相关测试通过 | 实际面板、任务、HTTP/WebSocket 联动，不只记录型 QWidget 替身 |
| 智能集合 | B03 已补后端失效和 WebUI 接收/成员刷新；历史 123 后端、46 前端、7 浏览器 | 当前构建 dist 与当前后端的再验收；历史计数不得相加成当前总数 |
| LAN ZIP | 在途预算、取消、响应清理和进程内重试已实现 | 崩溃后遗留归档恢复未实现；慢客户端、RSS、实际临时盘占用未测 |
| LAN 预览 | 同字节验证、ETag、策略重新验证已实现；历史 1112 passed / 2 skipped | 64 MiB 是源字节上限，不是解码像素/全局内存上限；无本轮并发容量证据 |
| 备份恢复 | 设置页、主窗口、恢复意图/启动恢复入口都存在 | 真实子进程强制结束后的数据和 UI 恢复；不能再写“缺少产品入口” |
| 桌面视觉 | 有离屏截图、digest、样式门禁；Stage F 仍为 ACCEPTANCE PENDING | 当前 Windows 真机 DPI/字体/错误态和动态过程 |
| 性能 | 9/6–9/7 报告记录 1k 启动约 2.0–2.3 秒、10k reset 约 70ms 观察项 | 这些是特定数据集的历史测量；LAN 负载、实际外盘和当前打包版本未验收 |

### 纠正此前的路径风险判断

`downloads.py`、`metadata.py`、`thumbnails.py` 已直接使用 aiohttp 解码一次后的 `match_info`；下载测试 `test_download_route_serves_filename_with_literal_percent` 已构造 `a%2Fb.txt` 与真实 `a/b.txt`，验证不会读到错误对象。本轮两项参数化用例通过。此前把它作为下一项“待修双重解码缺陷”缺少当前代码依据，应从本周优先修复列表移除。该结论限定于核对的代码与已跑下载用例，不扩张为全部路径入口完备证明。

## 6. 本周规划依据与延期项

本周先修 C01/C02、锁定整合版本，再验证启动/会话、数据恢复、LAN 容量和 frozen 入口。**没有证据支持给整个项目贴 P0 故障标签**；本周的最高工作优先级表示阻挡可靠验收，不代表已发生数据损坏。

以下保留为下一周或由本周结果触发：ZIP 跨进程持久回收完整实现、Windows 原子文件打开改造、全量视觉 34 组件 × 多语言 × 多 DPI、10k reset 拆分、外置盘检查异步化、插件/商业化扩展。它们有价值，但同时展开无法在一周形成可信结果。

资料来源：

- [开发统筹与 B00–B05](../plans/development-control-2026-09-06.md)
- [LAN 质量门禁](lan-quality-gate-2026-09-05.md)、[ZIP 清理恢复](zip-cleanup-recovery-2026-09-06.md)、[预览快照](preview-snapshot-consistency-2026-09-06.md)
- [性能审查](performance-audit-2026-09-06/README.md)、[桌面 Stage F](../plans/desktop-visual-stage-f-acceptance-2026-09-06.md)
- [恢复中断历史证据](../full-review/archive/restore-crash-intent-recovery-evidence-2026-08-26.md)：历史模拟状态测试不能替代真实终止进程。

核查分工：主代理负责当前树、门禁和抽样验证；两个 `gpt-5.6-terra` 子代理分别独立核对 LAN/会话、桌面/性能/恢复资料。子代理建议的工作优先级和总量经过主代理收敛；没有把所有建议直接塞进同一周。
