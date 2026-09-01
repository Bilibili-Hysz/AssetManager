# ZCode 会话汇总 — 桌面端深度精细扫描 + 全量回归加速（2026-08-11）

> **来源会话**：ZCode（deepseek-v4-flash），2026-08-11
> **任务**：桌面端深度精细扫描（排 Bug 100 项 + 9 组修复）+ 全量回归耗时诊断与加速
> **性质**：全程未 commit；改动与预存 WIP 混合在工作区
> **验证基线**：全量 **3076 passed, 7 skipped**（xdist 并行，95s）；e2e/perf 显式可选

## 1. 桌面端深度扫描（100 项：3 高 / 35 中 / 62 低）

**6 组并行探索**（file_list 辅助 / panels / dialogs / widgets / window / controllers+core），主代理交叉复核组1；清单落盘 `docs/archive/2026-09/reports-superseded/desktop-fine-scan-2026-08-11.md`（含每项文件:行号与修复建议）。

**高危 3 项**（全部修复）：
- **H1** `_event_bridge.py` DomainEventSubscription 改 QueuedConnection（域事件从 worker 发布时槽不再在发布线程执行 GUI）
- **H2** `info.py` _FileInfoTask 的 URL 写入移回主线程（urls_discovered 信号 + `_on_task_urls_discovered` 槽）
- **H3** `_loader.py` wait_for_runtime 加 5s 超时 + 超时 pool.clear（消除库切换/退出时永久挂起）

**9 个修复组**（7 组子代理 + 2 组主代理补完空返回子代理的剩余工作）：

| 组 | 关键修复 |
|---|---|
| A | H1/H2 + 预览双击防双触发（event.accept）、splitter 缩放 150ms 防抖、_LinkScanTask autoDelete、死代码清理（_urls_scanned/_classify_dir）、_SizeTask 打标跳过 |
| B | H3 + stderr 重定向日志、set_size 锁内写、clear_thumb_cache 锁外删除、regenerate_all 无条件 on_complete、_stopped 语义修正、touch 60s 节流、BAKE_SIZE 删除、drain 异常防护 |
| C | _rebuild_tags_cache 宽异常（reset 不再悬挂）、sort() changePersistentIndexList、两遍稳定排序目录恒置顶、除零防护、分隔符全平台拒绝、occupied 惰性+5000 上限 |
| D | tag_tree 变更后 _populate、sidebar _PreloadTask autoDelete、image_viewer 降采样 2048+目录缓存+缩放 clamp [0.05,64]、GL/加载失败日志 |
| E1 | hsv_wheel 色环映射统一+离屏缓存、file_picker 目录标志预计算、pager 搜索防抖+1000 上限+2MB 截断、stylekit t.get 兜底、command_palette 增量注册（**回归中发现组排序 bug 并修复**） |
| E2 | tag_chip 同义词缓存、theme_gallery 静态 CSS 缓存+左键校验、title_bar 去 refresh_theme、tray QMenu 释放、toast chrome 固定宽度、lan_sharing 状态机 4 项 |
| F | 窗口几何持久化、库切换失败回滚+提示、菜单退出真退出、定时器悬垂防护、restore 容错+清理、构造期弹窗延迟、TabContainer.shutdown() |
| G | color_picker 3 项、share_link 3 项、sidebar_settings 深度钳制数据丢失、_share_api 3 项、plugin_manager 4 项（含卡片点击）、startup Path 容错 |
| H+I | themes 缓存键+类型校验+reload 恢复、crash_handler 重入标志、tool_scheduler cmd/c 包装+原子写、directory_cache 读锁+prune、settings 自动 load+形状校验、json_store 宽捕获、icons LRU、bg_effects 降采样、favorites 跨库串扰、info/tag_tree controller 并发与批量 |

**保留决策**：_animate_in、_on_domain_tags_changed（测试依赖）；_detail_model resolve（与 TagStore key 规范一致）；lan_sharing F4 注释化。**未修项**（后续）：P7/P8 tag_tree 跨面板接线（directory_selected 无消费者、标签过滤无效果）。

**新增 8 个测试文件共 73 用例**（test_low_batch_loader/panels/detail_model/widgets_e1/widgets_e2/dialogs/window/core）。

## 2. 全量回归加速（597s → 95s，6.3×）

**诊断**：无并行（串行 3092 用例）+ ~30 个结构性慢用例（server_lifecycle 8s 超时边界 ×6、Playwright ×20、性能基线、进程 spawn）+ 平均 0.19s/用例的累积。

**实施**：
1. `pip install pytest-xdist`（3.8.0）；pytest.ini `addopts` 加 `-n auto --dist worksteal -m "not e2e and not perf"`
2. e2e/perf 标记分离：`tests/e2e/test_webui_realtime_acceptance.py` + `tests/performance/` 两文件加 `pytestmark`，默认排除、`pytest -m e2e` / `-m perf` 显式运行
3. 固定端口（8765）测试文件 `test_server_lifecycle.py` 加 `pytestmark = pytest.mark.xdist_group(name="serial")`（worksteal 下防并发）
4. conftest session hooks master-only：`_is_xdist_worker()` 检测 `PYTEST_XDIST_WORKER`——settings 恢复与 RuntimeData 清理只在 master 执行（消除 16 worker 并发清理的 I/O 风暴 + 配置恢复竞争）

**实测**：loadfile 分发 414s → worksteal 分发 **95.23s**（任务级均衡解决大文件长尾）；两轮均为 3076 passed, 7 skipped，无并行引入的 flaky。

## 3. 后续建议

- 未修项：P7/P8 tag_tree 接线（需 window/dock_factory 协作，功能增强型）
- 可选：低危清单剩余（LAN 路径面 Bug 8/9、lan-tools 系列、runtime 系列）
- 注意：`-n auto` 在多核 CI 上收益最大；Windows 单盘 I/O 密集场景 worksteal 优于 loadfile
