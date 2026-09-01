# ZCode 会话汇总 — P2 轮（M1-M7 桌面 UI/控制器/领域，2026-08-11）

> **来源会话**：ZCode（deepseek-v4-flash），2026-08-11
> **任务来源**：P1 轮交接的下一步（P2 轮：M1 file_list / M2 sidebar·info / M3 dialogs / M4 窗口·dock·widgets / M5+M7 controllers·domain）
> **性质**：全程未 commit；改动与预存 WIP 混合在工作区
> **验证基线**：全量 `pytest tests -q` → **2983 passed, 7 skipped, 0 failed**（连续两轮稳定）

## 1. 完成内容

**排 Bug**：5 个并行探索代理（M1-M7 + 8 份低危清单核对），清单落盘 `docs/archive/2026-09/reports-superseded/p2-round-2026-08-11.md`（约 98 项缺陷 + 80+ 项低危未修清单）。

**修复 9 组**（7 组子代理 + 2 组主代理亲自实施）：

| 组 | 文件 | 关键修复 |
|---|---|---|
| 1 | `_base.py`/`__init__.py`/`_shortcuts.py` | **H1 拖放路径解析统一**（同目录斜杠不一致改名复制、外部拖入 ValueError 穿透）、H2 搜索框键盘拦截、L1 动画复用（9 个回归测试） |
| 2 | `_background.py`/`_model.py`/`_navigation.py` | **M2 QRunnable 生命周期**（autoDelete=True + 持有至 done，实证验证）、M3 scan_reused 网格空白、M4 `_go_up` 逃逸、M6 is_dir 守卫 |
| 3 | `sidebar.py`/`info.py` | **S-1 高亮清理 qFatal**、S-2 预扫跨线程 GUI、I-1 备注跨文件空保存（数据丢失）、I-2 库外路径 ValueError、I-5 `_same_path` resolve 归一化、S-6 最近文件夹修复、I-6 手动扫描移线程 |
| 4 | `window_lifecycle_coordinator.py`/`window.py` | **H1/H2/H3 库切换事务化**（失败回滚、close_session 入 run_window_step、open 失败恢复旧会话）、M4 LAN stop 状态如实、M5 closeEvent 悬挂、M6 背景 resize 缓存 |
| 5 | `sharing_settings_dialog.py`/`tabbed_dialog.py` | A1 密码空校验、A2 TunnelWorker 取消+失败原因、**A3/B1 `_on_dialog_closed` 钩子**（OK/Cancel 停轮询）、A4 死设置标注、A5/A7/A8 |
| 6 | `tag_editor`/`tag_library`/`theme_preview`/`startup`/`favorites`/`recent` | **H1 删除未使用标签修复**（unused 来源改 tag_library）、H2 TagLibrary 加锁+_save mkdir、H3 worker wait、G1/G2/G3 主题写盘容错+dark 保留、I1/I3 startup、C1/C2/C3 favorites/recent |
| 7 | `app.py`/`workspace_bar`/`dock_factory`/`tab_container` | M11 重开库异常不吞+startup.close、M18 restore_tabs 容错、L19 重命名 QSignalBlocker、M12 extension 缓存、M13 removeDockWidget、L14/L15 |
| 8 | `_actions.py`/`_grid_widget.py` | M1 库外粘贴错误反馈+剪贴板恢复、**M5 批量重命名进后台**、L2 Shift 锚点、L3 Escape 取消、L4 死分支 |
| 9 | `controllers/*`/`event_bus.py`/`auth.py` | C1 add_tag 真注册、C2 搜索历史防抖写盘、C3/C4/C5、**D1 WeakEventSubscription 强引用回退**、D6 密码黑名单 36 项 |

## 2. 关键问题与修复（flaky 定位）

**症状**：P2 首轮全量出现随机失败（集合每次不同：tag_service/gallery_routes → project_service/reconciliation 跨进程），单跑全部通过。

**根因**：conftest 的 `_cleanup_stores` 中我此前加的"LibraryService 模块级 `_root_ownership` 移除"段——它本是修 C 级崩溃的连带，但崩溃真正根因是"直接关连接"（已移除）；ownership 移除本身改变了跨测试会话语义 → 随机失败。

**修复**：移除该段（恢复 P1 稳定行为）；C 级崩溃不再发生（不再关连接）。连续两轮全量 2983 passed 稳定。

**教训**：测试基础设施的"防御性清理"改动会改变跨测试语义——**每处 conftest 改动都要全量验证稳定性（多轮）**，不能只看单轮。

## 3. 附加

- 架构边界测试 `test_tag_panels_use_session_scoped_tag_events` 适配 I-5 的 `_same_path`（断言更新，76 passed）
- i18n 补 `settings.theme_save_failed`（en/zh/ja）
- conftest 的 RuntimeData 清理机制保留（sessionfinish 清理 + settings 保护 + 24h 缓冲 + 成对保留收敛）

## 4. 下一步

1. **P2 低危清单**（约 80 项未修，`docs/archive/2026-09/reports-superseded/p2-round-2026-08-11.md` 末尾 + 8 份 module-*.md）：LAN 认证面（Bug 14-21）、LAN 路径面（NUL/ADS/二次 unquote/CSV 注入）、LAN 工具面（scanner/tunnel/ws/dto）、存储维护面（core-store 3-27、core-db 5-16、maintenance 5-17）、runtime 面（runtime 3-25）——可多会话滚动
2. **P2 剩余**：组 3 的 S-8/S-9、组 4 的 L16/L17/L21-L25、组 6 的 E1/E2/F1/D1、组 7 的 M6 已修其余 L 项（见 p2-round 清单未覆盖项）
3. **性能轮**：M6a-8 get_home 全表扫描、thumbnail 索引
4. **DB 迁移 v24**：assets 目录 mtime 快照（M6a-18）
