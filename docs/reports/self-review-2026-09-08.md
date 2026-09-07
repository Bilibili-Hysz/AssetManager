# 自深度审查报告（2026-09-08）

> **收口更正：** 本文为历史自审记录。第四轮独立复核发现 metadata 仓库未原子复查 clean transaction，且原事件测试与 W6 窗口/退出断言不足；“三服务均由仓库复查”不适用于当时的 metadata 实现。本轮已针对性处置，当前结果见 [收口与交接报告](week-closeout-2026-09-08.md)，不继续沿用本页“无产品缺陷发现”作为现状结论。

> 对象：本会话四个提交（`0937a95` · `8421f1c` · `68ab0e4` · `baadf73`）——R1–R5 与 F1–F5
> 两轮复核处置的全部代码、探针、测试与报告。
> 方法：逐 diff 审读 → 新失败面静态扫查 → 动态对抗验证（真 worker 并发压测）。
> 结论：**通过；1 项转常设探针，3 项备忘登记，无产品缺陷发现。**

## 1. 逐 diff 审读

| 变更 | 审读结论 |
|---|---|
| 三服务守卫锁内采样（collection/tag/metadata） | 采样-释放-再获取窗口安全：worker 若在窗口内开事务，仓库侧 `_write_scope(require_clean_transaction=True)` 会在锁内**阻塞至 worker 完成后**再采样，不会误拒；仅对真实泄漏事务 fail-closed |
| `asset_index_service` 两处采样 | 锁序 `refresh_lock → conn_lock` 单向（`_refresh_lock` 全库仅此两处获取点），无反序死锁 |
| `_require_committed` 锁内提交 | 调用方（`_refresh`/`_refresh_move`）不持连接锁，无重入/序问题 |
| `lan/utils` flight | worker/结果/完成态同对象；`Thread.start` 异常路径下下一次调用开新 flight；`list(results)` 拷贝与 GIL 原子 append 并发安全 |
| w3/w5/w6 探针 | 关闭语义（WM_CLOSE→托盘）、进程树 `/T`、流式哈希、跨 loop 心跳取消路径逐一核对 |
| 两个新测试文件 | xdist 下 socket 全局 monkeypatch 为进程局部，安全；metadata 测试的 `setenv` 为冗余保险（实际隔离靠 B00 每进程运行域），无害 |

## 2. 新失败面静态扫查

| 风险 | 结论 |
|---|---|
| **A：守卫新增 `db_write_lock` 获取**，若调用方持有 legacy 全局写锁（no-arg 形态）会触发 fail-fast RuntimeError | ✅ 排除——全库 grep 确认**无任何生产调用方**使用 no-arg 形态（仅测试） |
| **B：锁序反转**（conn_lock → refresh_lock 逆序路径） | ✅ 排除——见上表 |
| **C：守卫等待时长**——前台变更需等待 worker 事务完成 | 登记备忘：worker 事务为短促队列轮询，等待有界；以"短暂等待"换"零误拒"是有意取舍 |

## 3. 动态对抗验证（`scripts/perf/guard_stress.py`，本审查转常设）

真实 ApplicationBootstrap + LibrarySession + **在跑的 reconciliation worker**（`is_running=True`，
runtime 自启确认），每轮 7 类变更（集合增删/成员/smart 建评/标签/备注/评分/URL）+ 文件扰动
喂养对账队列，最大化竞争窗口：

- 50 轮 + 3×30 轮：**误拒 0、其他错误 0**。
- 审查过程中修正压测脚本自身三处缺陷（库目录不得置于运行域内——运行域卫生会清理陌生目录；
  需安装 tag 规范化器；manual 集合不可 evaluate）——均为审查工具问题，非产品缺陷。

## 4. 备忘登记（不构成缺陷）

| # | 内容 | 处置 |
|---|---|---|
| 1 | W6 探针种子 `lan_share_safety_ack_version: 1` 与现行合同版本耦合；版本升级后探针会以 INVALID 失败（确认对话框路径） | 探针随版本升级时同步 |
| 2 | metadata 并发测试的 `AM_RUNTIME_ROOT` setenv 冗余（B00 每进程隔离已覆盖） | 保留作双保险 |
| 3 | `get_local_ip` 在解析 worker 长阻塞时仍返回 loopback 回退（单飞仅保证线程有界与结果不丢） | 行为与修复前一致，登记已知边界 |

## 5. 审查覆盖声明

本审查覆盖本会话全部生产代码变更（5 文件）与三个探针、两个测试文件、四份报告的交叉引用；
未重审既有历史代码与未变更区域。静态门禁（ruff/doc）与全量 xdist（5070/0/20，r17 junit）
为本审查的回归底座。

无证据即 unverified——本文档自身也是这个纪律的适用对象。
