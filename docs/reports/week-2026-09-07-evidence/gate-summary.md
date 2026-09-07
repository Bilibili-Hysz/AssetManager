# W1 · 整合基准与测试门禁修正 — gate summary（2026-09-07）

> 状态：**STAGE RESULT（一周计划 W1，当日交付）** · HEAD 基线 `b9ad72e` · 证据：[baseline.json](baseline.json)、[w1-loadgroup-probe.jsonl](w1-loadgroup-probe.jsonl)

## 1. C01 · CI/Release 失效 lint 清单（✅ 修复）

- `.github/workflows/ci.yml:27` 与 `release.yml:26` 的 ruff 清单移除不存在的 `setup_cython.py`（其余清单核对：`build.py`/`run.py`/`main.py` 均存在）
- **与 CI 完全相同的命令实测**：`ruff check AssetsManager tests scripts run.py build.py main.py` → All checks passed
- 发布预检依赖链核对：release 作业装齐 `requirements{,-lan,-dev}.txt`、WebUI dist 经 `npm ci && npm run build` 先于 PyInstaller、含 `check_package_contents` 与冻结冒烟——与 CI 无需修的差异（更深打包核验归 W6）

## 2. C02 · 并行分组保证（✅ 修复 + 实证）

- `pytest.ini` `--dist worksteal` → **`--dist loadgroup`**：使 `xdist_group` 标记真实生效（worksteal 下标记被静默忽略——C02 根因）
- **新发现并一并分组**：`test_security_preflight_internal/integration.py` 同绑 8765 固定端口（此前无任何分组标记），补 `xdist_group("serial")`；既有分组使用点（desktop 基线 ×2、server_lifecycle）在 loadgroup 下自动生效
- **探针实证**（`w1-loadgroup-probe.jsonl`，-n 2 loadgroup）：serial_a/b/c 全部落在 PID 35372，ungrouped_a/b 在 PID 14516——同组零分散
- 真实固定端口三模块 loadgroup 下：**63 passed**；desktop+unit 全量 smoke：**2621 passed**（全局调度切换无破坏）
- 注：不同外层 pytest 进程仍不共享固定端口——该边界由"串行运行固定端口模块"策略覆盖（计划原文已含）

## 3. B00 · 测试设施校验（✅）

- `tests/conftest.py` -330/+37：内联会话快照逻辑抽取为 `tests/test_support/runtime_isolation.py`（`install_pytest_runtime()`）
- 四项安全特性逐项核实：清理异常守卫（OSError/RuntimeError/ValueError）、嵌套 pytest 新域、应用子进程经 `AM_RUNTIME_ROOT` 继承、atexit LIFO 先于 AppSettings saver
- `tests/test_support/` 10 tests passed（含状态核查报告已抽样的 `test_runtime_isolation.py`）

## 4. 改动分组（baseline.json，100 文件 → 7 行为单元，零未分组）

| 行为单元 | 文件数 | 说明 |
|---|---|---|
| LAN-ZIP预览 | 51 | zip_cleanup/resources/sources、temporary_file_response、file_response 新模块 + 路由 + 15 个 zip 测试 + 快照一致性 + 报告 |
| 启动搜索性能 | 13 | app.py/ollama_client 延迟导入、search_service 路径解析、path_resolver、window.py 启动次序（含 PF-1 热修，与并行调整同文件 co-mingled）、info 系测试 |
| 文档 | 11 | 周计划/状态核查/图册/开发统筹/ZIP 与 LAN 报告 |
| B03B04B05-失效前端 | 11 | runtime_events、RealtimeContext、Sidebar、contracts.ts、gen_ts_types、tag_service 搜索索引联动（单键→批量签名） |
| B01B02-数据会话 | 6 | undo/file_operation/metadata 服务 + 切库失败恢复新测试 |
| B00-测试设施 | 6 | runtime_isolation 模块化 + loadgroup + perf 基线微调 |
| W1-门禁修正 | 2 | 双 workflow |

依赖版本（baseline.json `deps`）：Python 3.14.3 / PySide6 6.11.0 / pytest 9.0.2 / xdist 3.8.0 / pyright 1.1.410

## 5. 验收对照（计划 W1 验收条款）

- [x] 与 workflow 一致的 lint 命令通过
- [x] 分组归属探针有实际证据（PID 级）
- [x] 并发进程 RuntimeData 不同（B00 隔离域测试覆盖；本轮未人为制造端口碰撞——按计划不做）
- [x] 老台账不再手抄错误哈希（baseline.json 脚本生成 SHA-256）
- 提交：按行为单元分批（B00 → 门禁 → 启动搜索 → B01B02 → B03B04B05 → LAN → 文档）

无证据即 unverified——本文档自身也是这个纪律的适用对象。
