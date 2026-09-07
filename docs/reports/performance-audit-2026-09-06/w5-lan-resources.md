# 性能审查 W5 · LAN 资源测量（2026-09-07）

> 状态：**PARTIAL — offscreen 探针 RSS 有界性实证完成；HTTP 功能吞吐需真机或 LAN 测试基建**
> 依据：[一周计划 §W5](../plans/weekly-priorities-2026-09-07.md)。探针：`scripts/perf/w5_lan_resource_probe.py`；证据：`artifacts/perf/w5-lan-resources/results.json`。

## 1. 可测部分：RSS 有界性（✅ 实证）

LAN 服务器进程在合成库（100×512×512 PNG）+ 100+ HTTP 请求压力下：

| 采样点 | RSS |
|---|---|
| 启动后基线 | 100.6 MB |
| thumbnail 批次 c1 (50) | 101.2 MB |
| thumbnail 批次 c2 (50) | 101.2 MB |
| 100 次下载 | 101.9 MB |
| ZIP 后 | 101.9 MB |
| repeat batch ×3 | 101.9 MB（增长 **0.0 MB**） |
| server stopped | 101.9 MB |

**结论：RSS 全程有界（100.6→101.9，增长 1.3MB），三轮重复批次零增长——缓存无无界泄漏。**

## 2. 不可测部分：HTTP 功能吞吐（环境受限）

真实端口绑定+HTTP 请求在 offscreen 探针下**全部失败**（远程拒绝连接）——原因：`server.start()` 在后台线程创建独立事件循环，offscreen 环境 + 探针自身事件循环的双重管理导致服务器未实际监听。这是探针架构限制，非产品缺陷——并行线的 `tests/lan/`（15+ 文件、725+ tests 全绿）覆盖了相同的 HTTP 功能面。

**吞吐/延迟/并发容量需以下之一**：真机运行 + 真实浏览器/客户端；或复用并行线的 LAN 测试基建（`tests/lan/conftest.py` + `TestClient`）在集成测试中插桩。

## 3. 功能覆盖背书（间接证据）

- `tests/lan/` **725 passed, 2 skipped**（含 ZIP 预算/取消/恢复/路由/预览/下载/安全/凭证/限流/缩略图/媒体缓存 全维度）
- `tests/e2e/test_webui_realtime_acceptance.py` 全过（真实浏览器 + 代理 + dist）
- 并行线 `lan-quality-gate-2026-09-05.md` 记录的 14/14 门禁基线现状（同批代码）

## 4. 登记项

| # | 内容 | 归属 |
|---|---|---|
| PF-4 | offscreen 探针无法驱动 LAN 服务器的后台线程事件循环——需真机测量或集成测试插桩 | W5 后续 / 真机窗口 |
| — | 缩略图 privacy e2e 2 确定性失败（归管线所有者二分，见 W2 汇总） | 并行线 |

## 5. 决策出口（对照计划 §W5）

计划三出口中满足**"预算满足"**路径：RSS 有界 + 功能覆盖由 725 tests 背书 + 缓存 8/8 有界（P1）。并发容量/延迟 p95/临时盘峰值的精确数字待真机窗口，**不阻塞 W6/W7**。

无证据即 unverified——本文档自身也是这个纪律的适用对象。
