# AssetManager — Code Audit Resolution Summary

> Original audit: 2026-06-08
> Fixes applied: 2026-06-08
> Source: `.opencode/plans/code-audit-report.md`

---

## 1. Fixed Items (12)

### Performance (4)

| ID | Title | File | Fix |
|----|-------|------|-----|
| **P-1** | Canvas 布局全量标记脏行 | `_grid_widget.py:180` | 仅列数/缩略图尺寸变化时全量失效；普通 resize 保留纹理缓存 |
| **P-2** | 橡皮框释放全量遍历 | `_grid_widget.py:734` | 根据 rubber-band Y 坐标反算行范围：`first_row = rect.top() // _item_h` |
| **P-3** | Worker 线程创建 QPixmap | `_loader.py:215` | 全程 QImage，主线程 `QPixmap.fromImage()` 转换 |
| **P-4** | 目录大小任务缺去重 | `_model.py:140` | `_pending_dir_sizes` 去重 + `_dir_size_gen` 丢弃库切换后的旧结果 |
| **P-5** | LAN zip 阻塞事件循环 | `api.py:796` | 移至 `ThreadPoolExecutor`，`loop.run_in_executor` 异步执行 |

### Functional (6)

| ID | Title | File | Fix |
|----|-------|------|-----|
| **F-1** | Worker 线程调 QMessageBox | `_actions.py:185` | `_do_paste()` 收集 errors 列表，`_on_paste_done` 主线程弹窗 |
| **F-2** | 后台信号对象 GC | `_actions.py:481` | `_Sig` 持久化到 `self._background_ops`，完成即移除 |
| **F-3** | 缩略图再生无法取消 | `_loader.py:398` | 新增 `_regen_cancel` 标志，`set_lib_root()` 中断旧任务 |
| **F-4** | TabbedDialog 信号泄漏 | `tabbed_dialog.py:139` | `closeEvent` 中 `disconnect` 后 `_theme_connected = False` |
| **F-5** | AppSettings 线程安全 | `settings.py:36` | 全方法包裹 `RLock`，`save()` 用 `dict(self._data)` 快照 |
| **F-7** | sys._MEIPASS 缺少保护 | `themes.py:62` | `getattr(sys, '_MEIPASS', fallback)` |

### Code Quality (2)

| ID | Title | File | Fix |
|----|-------|------|-----|
| **Q-3** | UI 文本硬编码 | `info.py:310` | `"Open"` → `tr("info.open")`，`"Copy Path"` → `tr("info.copy_path")` 等 |
| **F-6** | Server stop 线程泄漏 | `server.py:101` | `future.result(timeout=8)` + `call_soon_threadsafe(loop.stop)` |

---

## 2. Unfixed Items (4)

### Code Quality (4)

| ID | Title | File | Reason |
|----|-------|------|--------|
| **Q-1** | pyright 不可用于回归门禁 | `pyrightconfig.json` / 多文件 | **需大规模类型标注**：313 errors 主要为 mixin 动态属性、Qt Optional 返回、QObject 子类成员未标注。需为 `dock.create()`、`FileListPanel`、`InfoPanel` 等添加 Protocol/类型约束，压低到可管理数量后再纳入 CI |
| **Q-2** | 大量异常被吞 | `lan/api.py:333` 等多处 | **需全项目 review**：全项目 50+ 处 `except Exception: pass` 或空 `pass`。需逐个审计调用点，添加 `_log.exception` 日志、用户反馈或错误恢复逻辑 |
| **Q-4** | Dialog 单一 QSS 约束未遵守 | `settings_dialog.py:35` 等多处 | **需逐个对话框迁移**：SettingsDialog、SharingSettingsDialog 等仍存在子控件级 `setStyleSheet()`。需将样式收敛到 `TabbedDialog._dialog_qss()`、objectName 或动态 property |
| — | `_delegate.py:675` 硬编码 white/black | `_delegate.py:675` | 运行时 painter 调用 `QColor("white") / QColor("black")` 用于文本对比度选择，需基于背景亮度改用 `t['on_accent']` |

---

## 3. Summary

| Category | Fixed | Unfixed | Total |
|----------|-------|---------|-------|
| Performance | 5 | 0 | 5 |
| Functional | 6 | 0 | 7 |
| Code Quality | 2 | 4 | 4 |
| **Total** | **12** | **4** | **16** |

---

## 4. Recommendation

Unfixed items are all quality improvements, not functional bugs or performance issues. Priority order for future work:

1. **Q-2** (swallowed exceptions) — highest ROI for stability, can be done incrementally file-by-file
2. **Q-4** (single-QSS migration) — affects theme consistency, should be done when adding new dialogs
3. **Q-1** (pyright) — requires dedicated typing sprint, best done after API stabilizes
4. Painter white/black — edge case in `_delegate.py`, low priority
