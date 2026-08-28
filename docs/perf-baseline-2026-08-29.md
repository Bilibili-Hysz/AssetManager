# Performance Baseline 2026-08-29（D3 决策基线）

> 状态:**LIVING** · updated: 2026-08-29 · D3 正式性能基线与"单连接架构"决策记录；所有数字为本地趋势证据，非机器无关预算。

## 1. 定位与口径

- 本文是 D3 决策项的正式 dated 基线：固化 2026-08-29 本机一次完整采集（`tests/perf/` 三项基准），并据此对**每库单 SQLite 连接 + locked_read 串行化**架构做出维持/重启决策（§4）。
- 口径沿用基准脚本自述（三个脚本头注）与 README"性能基准"小节：产出是**本地趋势证据，不是机器无关的帧预算**，不得用作普通 PR 的 pass/fail 门禁。
- 原始 artifact（json + md + junit）保留在 `artifacts/perf/{grid,directory,thumbnail}/<UTC 时间戳>/`，本文引用各基准的最后一次运行目录：
  - grid：`artifacts/perf/grid/20260828T174456Z/`（共 3 次运行）
  - directory：`artifacts/perf/directory/20260828T174601Z/`（共 2 次运行）
  - thumbnail：`artifacts/perf/thumbnail/20260828T174900Z/`（共 4 次运行）

## 2. 环境

| 项 | 值 |
|---|---|
| 机器 / OS | 本机开发机，Windows 11（`Windows-11-10.0.26220-SP0`） |
| Python | 3.14.3 |
| PySide6 / Qt | 6.11.0 / 6.11.0（`QT_QPA_PLATFORM=offscreen`） |
| 其他关键依赖 | aiohttp 3.14.0、Pillow 12.2.0、numpy 2.4.4（与 `requirements-ci.txt` pin 一致） |
| DB schema | v35（`db_migrations.CURRENT_SCHEMA_VERSION`） |
| fixture | 全部合成（空 `.txt` / 8×8 PNG），不触碰真实库 |
| 采集时间 | 2026-08-29 本地（artifact UTC 时间戳 2026-08-28T17:42Z–17:49Z） |

## 3. 基线数字

### 3.1 Grid（`--items 1000 10000`，3 次运行）

`grid.frame` 耗时（视口 1200×720，offscreen；每次运行按场景给范围）：

| 场景 | n/次 | p50 ms（3 次范围） | p95 ms（3 次范围） |
|---|---:|---|---|
| 1000-warm | 3 | 0.63 – 0.70 | 0.86 – 1.58 |
| 1000-scroll_zoom | 25 | 9.96 – 12.13 | 17.57 – 19.74 |
| 10000-warm | 3 | 0.48 – 0.93 | 0.84 – 1.44 |
| 10000-scroll_zoom | 25 | 8.98 – 12.61 | 17.43 – 23.41 |
| cold（1000 与 10000） | 3 | 9.50 – 13.19（噪声 ±30%，见下） | 9.71 – 13.48 |

- `model.reset`（每次 n=2，样本极小）：1000 条目 p50 3.6–13.0 ms；10000 条目 p50 36.7–68.2 ms。**运行间波动 >20%，按噪声对待**，只看量级。
- 关键结论：scroll_zoom 帧成本在 1000 与 10000 条目下同级（p50 ≈ 9–12 ms）→ **grid 帧成本视口绑定，不随库规模线性增长**。
- 纹理缓存峰值 4.0 MiB（静态）/10.6 MiB（zoom 中），0 次逐出；帧请求合并 p50 1–2。

### 3.2 Directory（`--directories 100 500 --items-per-directory 10`，2 次运行）

每场景单次 `AssetService.list_directory`（p50=p95=max）；条目数 = 目录数 × 11（100→1100、500→5500）。

| 场景 | run1 List ms | run2 List ms | 差异 | 吞吐（条目/秒） | Summary P50 ms |
|---|---:|---:|---:|---:|---:|
| 100-cold | 58.0 | 56.8 | 2% | ≈19k | 0.43–0.45 |
| 500-cold | 271.5 | 283.3 | 4% | ≈20k | 0.44–0.45 |
| 100-warm | 26.5 | 30.2 | 13% | ≈39–42k | 0.17–0.21 |
| 500-warm | 122.6 | 124.4 | 1.5% | ≈44–45k | 0.17 |
| 100-summaries_off | 5.2 | 5.6 | 8% | — | — |
| 500-summaries_off | 13.7 | 17.1 | **25%（噪声注记）** | — | — |

- cache 命中符合预期：warm 全命中、cold 全 miss。
- 除注明外两次运行差异 <13%；`500-summaries_off` 超 20% 已标注（该场景总耗时仅十几 ms，调度噪声占比高）。

### 3.3 Thumbnail（`--items 1000`，合成 8×8 PNG，4 次运行）

24 可见 + 48 预取 = 72 请求：

| 指标 | cold（4 次范围） | warm（4 次范围） |
|---|---|---|
| first visible ms | 71 – 129（**噪声 ±40%**，磁盘 IO 主导） | 0.50 – 0.72 |
| last visible ms | 320 – 422 | 10.1 – 15.0 |
| 吞吐 | ≈170 – 220 thumbs/s | — |
| cache 结果 | miss 144 / stored 72 | hit 72 |

- max queue depth 72、cache 峰值 18,432 bytes，无积压异常。
- **兼容性修复**：`thumbnail_telemetry_benchmark.py` 的 `QImage.save(path, b"PNG")` 被 PySide6 6.11.0 签名校验拒绝（`ValueError: wrong argument values`），已改为 `image.save(str(path), "PNG")`（tests/perf 脚本内，非产品代码）。此前该基准在 6.11.0 下无法运行——这也是 thumbnail 基线此前缺失的原因。

## 4. 决策：每库单 SQLite 连接 + locked_read 串行化（D3 正式闭环）

### 4.1 现状吞吐画像（引用 §3 基线）

- 现状模型：每库一条 `check_same_thread=False` 连接；连接级写锁 `db_write_lock`（RLock per connection）；`locked_read`（`AssetsManager/core/database.py:1266`）把 LAN 路径仓库读串行化到同一把锁；跨进程一致性靠文件锁（WAL + timeout=30）与 CAS。等待已有遥测：`db.write_lock.wait` / `db.write_lock.hold`（`_record_write_lock`）。
- 单连接串行化下的热路径实测：目录列表 warm ≈ 44–45k 条目/秒（5500 条目 p50 122–124 ms），cold ≈ 19–20k 条目/秒；单条目录摘要 0.17–0.45 ms。列表成本随条目近线性（100→500 目录约 ×4.7）。
- 串行化的代价在本基线中**不可观测**：基准为单线程顺序访问，无 `db.write_lock.wait` 记录；grid 帧成本视口绑定（§3.1），与 DB 连接并发度无关。

### 4.2 结论：维持现状

维持"每库单连接 + locked_read 串行化"，**不做连接池/多连接改造**。理由：

1. 基线显示单连接吞吐（≈45k 条目/s warm）远高于当前单用户桌面与 LAN 小规模并发的需求；瓶颈在磁盘 IO（cold 路径、缩略图），不在连接串行化。
2. 与 ADR 0001 决策 1 一致：共享连接是过渡模型，新代码继续走 `LibraryContext` / 显式 `connection_for()` / 服务层，而非推翻连接模型。
3. 改造收益不成比例：多连接需重解写锁公平性、跨进程一致性（README 关键设计取舍 #1"单进程模型"）与架构边界测试允许清单，风险大于当前可观测收益。

### 4.3 重启条件（任一满足即重开本决策）

1. LAN 常态并发用户 **>10** 且遥测出现 `db.write_lock.wait` p95 **>50 ms**（事件已内建，见 §4.1）。
2. 真实库（非合成 fixture）目录列表 p95 **>500 ms** 在连续 7 天 nightly/手动基线中复现。
3. 出现必须多连接的功能需求（并行迁移、只读副本、库内并行写），需先更新 ADR 0001/0002。
4. 真实库导入/扫描写入与 LAN 读互相阻塞成为用户可观测问题（`db.write_lock.wait` 排队证据）。

### 4.4 后续观测方式

- **nightly workflow 已随仓库激活**：`.github/workflows/nightly-perf.yml`，schedule `cron: "17 3 * * *"`（每日 03:17 UTC ≈ 北京时间 11:17），ubuntu-24.04 + Python 3.13 + PySide6 6.11.0，产出 grid telemetry artifact，**保留 30 天**（`retention-days: 30`）→ 30 天趋势对比窗口。
- 触发器：`schedule` + `workflow_dispatch`（手动触发入口已具备）。
- 依赖口径（已核对）：nightly 只安装 `requirements-perf.txt`（仅 `PySide6==6.11.0`）；与 `requirements-ci.txt` 的 `PySide6==6.11.0` 为**同一 pin，无冲突**（且 CI 安装顺序上 requirements-ci 本就要求后装覆盖）。
- 本机趋势复跑命令（本文 §3 全部数字可由此再生）：

```bash
python -m tests.perf.grid_telemetry_benchmark --items 1000 10000
python -m tests.perf.directory_telemetry_benchmark --directories 100 500
python -m tests.perf.thumbnail_telemetry_benchmark --items 1000
```
