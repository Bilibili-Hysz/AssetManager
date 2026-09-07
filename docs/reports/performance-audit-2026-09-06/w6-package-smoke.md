# 性能审查 W6 · Windows 包冒烟（2026-09-07，PF-5 修后更新）

> 状态：**ALL PASS — 4 frozen 模式全部可交付**（PF-5 修复后重建验证）
> 环境：PyInstaller 6.19.0 / PySide6 6.11.0 / Python 3.14.3

## 1. 构建

| 模式 | 结果 | check_package_contents |
|---|---|---|
| onefile (`dist/AssetManager.exe`) | ✅ 构建成功 | ✅ verified |
| onedir (`dist/AssetManager/`) | ✅ 构建成功 | ✅ verified |

WebUI dist：已从当前源码重建（671 tests / typecheck 0 / build ✓）。

## 2. 冒烟结果（PF-5 修复后最终态）

| 场景 | onefile | onedir |
|---|---|---|
| 非最大化启动（8s 存活） | ✅ ALIVE | ✅ ALIVE |
| **最大化启动** | ✅ **ALIVE 8s** | ✅ **ALIVE 8s** |
| `--help` 参数 | ✅ exit 0 | 未测 |
| check_package_contents | ✅ | ✅ |

修复前基线（登记用）：onefile maximized ❌ segfault 139 / onedir 全模式 ❌ / onefile 非最大化 ✅（唯一过项）。

## 3. PF-5 根因与修复

**根因**：`_restore_window_geometry` 在 `__init__` 期间调用 `showMaximized()`（line 156），此时 `_setup_ui()` 尚未执行——widget tree（dock/central/layout）不存在。`showMaximized()` 触发原生 resize+show 事件，C 侧分发进入不完整的 widget tree，frozen 引导阶段 Python 处理器不可达 → 原生段错误。开发模式下同一操作产生 Python 级异常（可捕获但不稳定，即 PF-1 变体）。

**修复**：`showMaximized()` 延迟到 `_setup_ui()` 完成后——`_restore_window_geometry` 改为存 `setattr(window, "_pending_maximized", flag)`，`__init__` 在 `_setup_ui()` 返回后检查标志并调用 `showMaximized()`。开发模式与 frozen 模式均验证通过。

## 4. 验证矩阵（PF-5 修后全部可交付）

| frozen 模式 | 修前 | 修后 |
|---|---|---|
| onefile 非最大化 | ✅ | ✅ |
| onefile maximized | ❌ segfault | ✅ ALIVE 8s |
| onedir normal | ❌ segfault | ✅ ALIVE 8s |
| onedir maximized | ❌ segfault | ✅ ALIVE 8s |

## 5. 登记项

| # | 级别 | 内容 | 归属 |
|---|---|---|---|
| ~~PF-5~~ | ~~P1 阻断~~ | ~~frozen maximized 段错误~~ | ✅ 已修（d11ad45） |
| PF-6 | P3 | onefile 非最大化 exit code=1（WM_CLOSE 路径 exit code 非 0，功能正常但需确认原因） | W6 后续 |

## 6. 交付结论

**全部 4 frozen 模式可交付**。W7 周日汇总中记录修复与验证。

无证据即 unverified——本文档自身也是这个纪律的适用对象。
