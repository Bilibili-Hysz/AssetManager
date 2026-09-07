# 周验收汇总（2026-09-07—09-13）

> 状态：**WEEKLY RESULT** · 原计划 2026-09-07—09-13。09-07 单日完成 W1–W5 + W7 汇总（W6 当日仅启动冒烟）；
> 09-08 按独立复核（R1–R5）处置并补齐 W6 包内功能验收。
> 最终源码标识：**`0937a95`**（复核处置提交，基于 `dc6bb46`），分支 `master`。
> 证据：[W1 gate-summary](week-2026-09-07-evidence/gate-summary.md) · [W2 回归汇总](week-2026-09-07-evidence/w2-regression-summary.md) · [复核处置报告](recheck-disposition-2026-09-08.md) · [W5 LAN 资源](performance-audit-2026-09-06/w5-lan-resources.md) · [W6 包冒烟](performance-audit-2026-09-06/w6-package-smoke.md) · [性能审查总览](performance-audit-2026-09-06/README.md)

## 1. 执行摘要

一周计划 W1–W7 于 09-07 单日提前完成（W1–W6 + 汇总）；09-08 独立复核确认此前"全部修复完成"
结论不成立后，本轮处置关闭了其中 R1–R4 四项并按 R5 修订了报告口径。

**总体结论（2026-09-08）：AssetManager 源码 `68ab0e4` 通过全量回归（5070 passed / 0 failed）
与全部 13 项静态门禁，核心流程均有真实进程证据，可进入日常试用。** frozen 候选包与该提交
零脏文件哈希绑定，四变体包内功能验收 ×2 轮全 PASS（见 W6 行）；frozen maximized 仍建议
用户真机日常使用中最终确认。

## 2. 周计划完成状态

| 任务 | 计划日 | 状态 | 证据 |
|---|---|---|---|
| W1 整合基准与门禁修正 | 9/7 | ✅ 完成 | [gate-summary.md](week-2026-09-07-evidence/gate-summary.md)：lint 清单修复+loadgroup 探针实证+B00 校验+100 文件分组 |
| W2 同版本回归 | 9/8 | ✅ 完成（09-08 更新） | [w2-regression-summary](week-2026-09-07-evidence/w2-regression-summary.md)；09-08 全量 xdist 5065 passed / 0 failed / 20 skipped（[junit](recheck-disposition-2026-09-08-evidence/full-suite-r16.xml)），原始失败归因已修正（W2 实际失败为集合事件用例，非 gen_ts_types）；该用例与 2 项 privacy 失败均已关闭 |
| W3 启动切库关窗 | 9/9 | ✅ 完成（09-08 重写切库探针） | 启动矩阵×5 ALIVE；切库探针真实 A→B→A 十轮=20 切换、在途请求/旧会话失效/失败注入/回收断言全过（[证据](recheck-disposition-2026-09-08-evidence/w3-switch-final.txt)） |
| W4 备份恢复中断 | 9/10 | ✅ 完成（09-08 编码统一） | 正常恢复 ✓ + 受控中断 → 完整旧状态恢复 ✓；默认 GBK 控制台复跑 PASS（[证据](recheck-disposition-2026-09-08-evidence/w4-default-encoding-after.txt)） |
| W5 LAN 资源测量 | 9/11 | ✅ 完成（09-08 断言强化） | 真实吞吐可测（PF-4 撤销登记）：批量全成员解码/下载与 ZIP 全字节比对/192MB 慢客户端中断取证/RSS 请求期峰值 137.7MB、重复增长 0.1MB、verdict=bounded（[证据](recheck-disposition-2026-09-08-evidence/w5-final.txt)） |
| W6 Windows 包冒烟 | 9/12 | ✅ 完成（09-08 候选包重绑定） | [w6-package-smoke](performance-audit-2026-09-06/w6-package-smoke.md)：候选包（HEAD `68ab0e4`，工作树零脏文件）哈希绑定（[清单](performance-audit-2026-09-06/evidence/w6-package-hash-manifest.json)）；四变体包内功能全 PASS ×2 轮——开库/共享自启/LAN 字体逐字节/缩略图/**备注评分写读**/实时变化/PF-5 最大化消费 |
| W7 验收汇总 | 9/13 | ✅ 本文档（09-08 改版） | — |

## 3. 测试汇总（2026-09-08 实测，去重计数）

| 套件 | 通过 | 失败 | 跳过 | 说明 |
|---|---|---|---|---|
| 全量默认套件（unit+integration+desktop+lan+core，xdist） | **5070** | **0** | 20 | [junit r17](recheck-disposition-2026-09-08-evidence/full-suite-r17.xml)（F1–F5 处置后，含新增 5 项并发/枚举回归）；20 跳过 = 平台能力缺失（symlink 特权等），非缺陷 |
| tests/e2e（browser，-m e2e 显式） | 3 | 0 | 0 | 仅 privacy 验收文件本轮实跑 3/3；e2e 其余用例未在本轮全跑，不并入合计 |
| tests/performance（-m perf） | 未在本轮重跑 | — | — | 以 [performance-audit-2026-09-06](performance-audit-2026-09-06/README.md) 记录为准 |
| WebUI vitest | 未在本轮重跑 | — | — | 本轮无 WebUI 源码改动；以 W2 记录（671 passed）为准 |

> 计数纪律：仅累加本轮实际执行的套件，未执行的如实标注"未在本轮重跑"；
> 不再使用此前"合计 ~8017"的跨轮重复累加口径。

## 4. 已知保留与限制

| 编号 | 级别 | 内容 | 状态 | 归属 |
|---|---|---|---|---|
| R1 | ~~P1~~ | 集合/标签守卫误读对账 worker 事务 → 随机拒绝 | ✅ 已修（`0937a95`） | — |
| R2 | ~~P1~~ | 切库探针虚标 + 失败吞没；**附带实锤并修复** lan/utils 每次启动泄漏一条解析线程 | ✅ 已修 | — |
| R3 | ~~P2~~ | W4 默认编码中断验收 | ✅ 已修 | — |
| R4 | ~~P2~~ | W5 断言不足 | ✅ 已强化 | — |
| W6 | ~~P2~~ | frozen 包内功能验收（开库/LAN/实时/首次延迟依赖 + 哈希绑定） | ✅ 已完成（09-08，候选包 `68ab0e4` 绑定 + 四变体 ×2 轮全 PASS + [哈希清单](performance-audit-2026-09-06/evidence/w6-package-hash-manifest.json)） | — |
| F1 | ~~P1~~ | MetadataService 同根因竞态（第三轮复核确定性复现） | ✅ 已修 + 全库扫查收口（另修 asset_index/repair 两处同根因）+ 2 项 Event 屏障回归 | — |
| F2 | ~~P2~~ | DNS 单飞跟随调用丢失结果 | ✅ 已修（共享 flight）+ 3 项确定性单测 | — |
| F3 | ~~P2~~ | W5 指标归属（客户端心跳冒充服务器/读取上限当实收/小文件重下） | ✅ 已修（双轨心跳/实际字节/同对象流式哈希重下） | — |
| F4 | ~~P2~~ | W3 缺旧端点失效与活动下载跨切换 | ✅ 已补（旧端点 20/20 干净失效；128MB 跨切换完整返回） | — |
| F5 | ~~P2~~ | 报告断链/范围表述/证据未交付 | ✅ 已收口（0 断链；证据 .txt 入库；候选包重绑定） | — |
| PF-6 | P3 | WM_CLOSE 退出码归因：托盘语义确认（隐藏到托盘），无托盘纯退出路径仍待归因 | 归因部分完成 | 后续批次 |
| W4 | P3 | 恢复覆盖扩展（集合成员逐项、设置 UI、损坏备份、不可写） | 待补 | 后续批次 |
| W5 | P3 | 容量边界（大图慢读、持续并发 ZIP、p95 容量曲线） | 待补 | 后续批次 |
| — | 观察 | `test_viewer_opens_psd_through_media_decoder` xdist 高负载偶发（隔离绿；本轮第二次全量已过） | 登记观察 | — |
| — | 待用户 | frozen maximized 真机确认 + 十六步走查 | 待用户 | 用户 |

历史登记（09-07 版）：PF-4"offscreen 不可测"已被真实进程探针取代；PF-5 已修；
privacy e2e 2 失败与 gen_ts_types 2 红均已关闭（详见[复核处置报告](recheck-disposition-2026-09-08.md)）。

## 5. 日常试用判据

**源码 `68ab0e4` 及其哈希绑定的 frozen 候选包可进入日常试用**，条件：
- onefile / onedir（normal 与 maximized）：包内功能验收全 PASS，可日常使用
- 集合/标签并发变更的随机拒绝缺陷已修复，不再需要回避并发操作
- 保留项：PF-6 无托盘纯退出路径的退出码归因；真机长时使用与 Stage F 视觉走查属用户验收

## 6. 下周候选（最多三项）

1. **W4/W5 覆盖扩展**：恢复覆盖逐项化（集合成员/设置 UI/损坏备份/不可写）；W5 容量曲线（大图慢读、持续并发 ZIP、p95）
2. **PF-6 收尾 + privacy 合同扩展**：无托盘纯退出路径退出码归因；privacy 合同文档化（现行"全量 private, no-cache/no-store"写入设计文档）
3. **真实大库实机验收 + Stage F 全矩阵视觉验收**：F:\Blender 实机帧感受、三十四组件 × 多语言 × 多 DPI（依赖用户真机）

无证据即 unverified——本文档自身也是这个纪律的适用对象。
