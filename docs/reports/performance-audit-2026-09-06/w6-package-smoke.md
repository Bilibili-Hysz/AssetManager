# 性能审查 W6 · Windows 包冒烟（2026-09-07）

> 状态：**PARTIAL — onefile 非最大化通过；maximized + onedir 段错误阻断**（frozen 特有）
> 环境：PyInstaller 6.19.0 / PySide6 6.11.0 / Python 3.14.3

## 1. 构建

| 模式 | 结果 | check_package_contents |
|---|---|---|
| onefile (`dist/AssetManager.exe`) | ✅ 构建成功 | ✅ verified |
| onedir (`dist/AssetManager/`) | ✅ 构建成功 | ✅ verified |

WebUI dist：已从当前源码重建（671 tests / typecheck 0 / build ✓）。

## 2. 冒烟结果

| 场景 | onefile | onedir |
|---|---|---|
| 非最大化启动（8s 存活） | ✅ ALIVE | ❌ segfault (139) |
| **最大化启动** | ❌ **segfault (139)** | ❌ segfault |
| `--help` 参数 | ✅ exit 0 | 未测 |
| check_package_contents | ✅ | ✅ |

## 3. 段错误分析

### onefile maximized（PF-1 frozen 变体）

崩溃发生在 Python faulthandler/crash_handler 启用**之前**（两个日志文件均空）——即 C 原生层段错误，比 PF-1 Python 级修复更早。开发模式（`python main.py`）相同 settings 下 W3 矩阵 ×3 全过。

**根因假设**：`_restore_window_geometry` → `showMaximized()` 触发原生窗口操作，在 frozen bootstrap 中 PySide6 的 C 侧事件分发与开发模式的初始化时序不同，导致 `_setup_ui()` 之前的 window 操作仍然崩溃。PF-1 修复（字段提升）解决了 Python 级的 AttributeError，但 **C 级窗口操作在 widget tree 未建立时的行为未因字段提升而改变**。

**根治方向**：`_restore_window_geometry` 不应在 `__init__` 期间调用 `showMaximized()`——应将最大化状态保存为标志，延迟到 `showEvent` 或 `_setup_ui` 完成后应用。

### onedir 非最大化（frozen 特有）

非最大化也段错误——onedir 模式的 `_internal` 目录结构或 frozen bootstrap 与 onefile 不同。归同一 frozen 特有类别。

### 结论

- **onefile 非最大化** = 唯一可交付的 frozen 模式
- **onefile maximized + onedir 全部** = **阻断**，需根治 `_restore_window_geometry` 时序后重建

## 4. 登记项

| # | 级别 | 内容 | 归属 |
|---|---|---|---|
| PF-5 | **P1 阻断** | frozen maximized 段错误（C 原生层，Python 处理器不可达）；onedir 全模式段错误。根治方向：`_restore_window_geometry` 的 `showMaximized` 延迟到 `_setup_ui` 后 | 独立修复批次（1–2 天） |
| PF-6 | P3 | onefile 非最大化 exit code=1（WM_CLOSE 路径 exit code 非 0，功能正常但需确认原因） | W6 后续 |

## 5. 交付建议

- onefile（非最大化）作为当前唯一可交付的 frozen 模式——用户如设置了最大化，**需要先修 PF-5**
- onedir 模式完全阻断，需独立调查 frozen bootstrap 差异
- W7 周日汇总中如实记录此发现

无证据即 unverified——本文档自身也是这个纪律的适用对象。
