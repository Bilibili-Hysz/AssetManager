# 本轮命令结果摘录

> DATED EVIDENCE · 2026-09-07。以下为工具输出摘录，不是 CI 远端执行日志。

| 位置 | 命令 | 结果 |
|---|---|---|
| 原工作树 | `python -m ruff check AssetsManager tests scripts run.py build.py main.py setup_cython.py --output-format concise` | exit 1；`setup_cython.py:1:1: E902 系统找不到指定的文件。 (os error 2)`；`Found 1 error.` |
| 原工作树 | `python -m pyright` | exit 0；0 errors, 0 warnings, 0 informations |
| 原工作树/webui | `npm run typecheck` | exit 0；`tsc --noEmit` |
| 原工作树 | `python scripts/check_boundaries.py` | boundary checks passed (gates 1/2/3/5 + layer DAG) |
| 原工作树 | `python scripts/check_route_capabilities.py` | 0 violation(s) |
| 原工作树 | `python scripts/check_frontend_data_fetch.py` | 0 violation(s) across 10 page file(s) |
| 原工作树 | `python scripts/gen_ts_types.py --check` | contracts.ts is up to date |
| 原工作树 | `git -c core.safecrlf=false diff --check` | exit 0，无输出 |
| 独立源码根 0d87daf0/sync | 报告所列 7 个模块/选择器组合 | 82 passed in 23.33s；JUnit 0 errors / 0 failures / 0 skipped |

`verification.json` 来自实际 JUnit 解析与源码逐文件哈希比对；`workspace.json` 来自 Git、文件哈希及本机版本查询。未将历史报告测试计入本轮计数。原工作树没有运行 pytest。
