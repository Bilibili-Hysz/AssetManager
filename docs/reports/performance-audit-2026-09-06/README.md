# 性能审查总览（2026-09-06/07，主线程执行）

> 状态：**AUDIT COMPLETE** · 范围：桌面应用基础性能（启动/内存/吞吐/UI 帧预算）。LAN 服务端性能归并行线范围，未覆盖。
> 方法：既有基础设施复用（`-m perf` 门禁基线 / tests/perf 遥测 runner / PerformanceRecorder）+ 新增探针（`scripts/perf/startup_probe.py`、`scan_scale_probe.py`、`write_lock_probe.py`）。

## 结论一句话

**基础性能全面健康**：启动 2.0–2.3s（1k 文件库全就绪）、10k 条目列表扫描 0.19s 亚线性、索引搜索 0.9ms 恒定、缩略图 1k 冷态 <1s、写门禁零竞争、网格帧预算全达标且 1k↔10k 规模平坦、8 个模块级缓存全有界。

## 三棒结果

| 棒 | 报告 | 头条数字 |
|---|---|---|
| P1 启动与内存 | [p1-startup-memory](p1-startup-memory.md) | 导入 0.36s；就绪 2.0–2.3s；RSS 77→107MB；缓存 8/8 有界 |
| P2 吞吐与规模 | [p2-throughput-scale](p2-throughput-scale.md) | 14/14 门禁过；搜索 0.9ms 恒定；缩略图冷态 902ms/1k 张；写门禁 1.01x |
| P3 UI 帧预算 | [p3-ui-frame-budget](p3-ui-frame-budget.md) | paint p50 9ms(冷)/0.4ms(热)，10k 平坦；动画 tick ≤0.17ms；model_reset 10k=70ms（唯一热点，观察项） |

## 发现清单（PF 编号）

| # | 级别 | 发现 | 状态 |
|---|---|---|---|
| PF-1 | **P1 产品缺陷** | MainWindow 构造次序：几何恢复先于 bg/淡入字段初始化，持久化最大化标志命中即 C 级崩溃（探针在本机真实 settings 下实锤复现质量轮登记缺陷） | ✅ 已修（window.py 次序重排+删重复赋值） |
| PF-2 | P3-信息 | 并发 tag 变更遇开事务抛 clean-transaction RuntimeError（桌面单写者可接受；多写者归 LAN 线序列化） | 登记 |
| PF-3 | P3 观察项 | model_reset 10k 行 p99 70ms（导航一次性顿挫） | 登记（方向：reset 拆分） |
| — | 测试基建 | 缩略图遥测 runner `QImage.save(b"PNG")` 在 PySide6 6.11 必崩（bytes→str）——该 runner 此前完全不可用 | ✅ 已修 |

## 用户侧后续（如需深入）

- 真实库（F:\Blender 大库）的实机帧感受与 offscreen 数据对照
- 启动完整性检查（上次库在外置盘）的异步化/跳过策略——产品行为决策
- M1 微交互样板的观感评审（依赖真机）

## 证据目录说明

`evidence/` 内的原始 JSON 来自两次独立测量通道（主线程探针 + 部分运行的子代理产线，后者在 provider 错误前已完成其测量段）——两通道头条数字互相印证（启动 UI 就绪 ~0.98s vs 我的分段总 ~2.0s 差异为口径：后者含扫描+淡入收敛窗口）。原始文件按测量名自解释，叙述以三份 md 为准。

无证据即 unverified——本文档自身也是这个纪律的适用对象。