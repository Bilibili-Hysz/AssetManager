# AssetManager — 全面代码审计任务

> 版本：2026-06-08
> 目标：由独立审计大模型扫描全部源码，识别性能热区、功能错误、低质量代码。

---

## 一、项目概览

| 属性 | 值 |
|------|-----|
| 语言 | Python 3.11+ |
| GUI 框架 | PySide6 (Qt 6) |
| 架构 | QMainWindow + QDockWidget + 自定义 QWidget Canvas |
| 包管理 | requirements.txt |
| 打包 | PyInstaller (AssetManager.spec) |
| 入口 | `run.py` → `AssetsManager/app.py` → `AssetsManager/core/startup.py` → `AssetsManager/window.py` |

### 核心模块（按优先级）

| 模块 | 路径 | 行数(估) | 职责 |
|------|------|---------|------|
| 主窗口 | `window.py` | ~440 | QMainWindow + dock 布局 + bg 绘制 |
| 主题引擎 | `core/themes.py` | ~460 | JSON 主题加载 + QSS 生成 + bg API |
| 对话框模板 | `core/tabbed_dialog.py` | ~430 | 统一 Dialog 基类 + Widget 工厂 |
| 文件列表面板 | `panels/file_list/` | ~3000 | 自定义 Canvas 网格 + 模型 + 委托 + 加载器 |
| 侧边栏 | `panels/sidebar.py` | ~740 | QTreeWidget + 收藏/最近列表 |
| 信息面板 | `panels/info.py` | ~1060 | 文件元数据 + 预览 + 标签 |
| 启动窗口 | `core/startup.py` | ~610 | 库选择器 + 历史卡列表 |
| 工作区标签栏 | `widgets/workspace_bar.py` | ~340 | QTabBar 库切换器 |
| 设置对话框 | `core/settings_dialog.py` | ~270 | 主题/背景/语言/缩略图设置 |
| 缩略图加载器 | `panels/file_list/_loader.py` | ~ | QThreadPool 并行加载 + WebP 缓存 |
| 数据库 | `core/database.py` | ~ | SQLite WAL 模式 |
| 国际化 | `i18n/__init__.py` | ~ | JSON 翻译 + 动态切换 |
| LAN 共享 | `lan/` | ~ | aiohttp 服务器 + Cloudflare tunnel |
| Dock 工厂 | `dock_factory.py` | ~170 | QDockWidget 创建 + 标题栏 |

### 完整目录树

```
AssetsManager_Python_Rewrite/
├── run.py                         # 入口
├── AssetManager.spec              # PyInstaller 配置
├── requirements.txt
├── AssetsManager/
│   ├── app.py                     # QApplication 启动
│   ├── window.py                  # MainWindow
│   ├── dock_factory.py            # Dock 工厂
│   ├── core/
│   │   ├── themes.py              # 主题系统 v2
│   │   ├── color_utils.py         # 颜色工具 (alpha/lighten/darken/contrast)
│   │   ├── tabbed_dialog.py       # Dialog 模板
│   │   ├── settings_dialog.py     # 设置 UI
│   │   ├── sharing_settings_dialog.py
│   │   ├── sidebar_settings_dialog.py
│   │   ├── generic_settings_dialog.py
│   │   ├── tag_editor_dialog.py
│   │   ├── settings.py            # JSON 原子写入
│   │   ├── database.py            # SQLite 管理
│   │   ├── cache.py
│   │   ├── signal_bus.py          # 全局信号
│   │   ├── startup.py             # 启动窗口
│   │   ├── library_manager.py
│   │   ├── tool_scheduler.py
│   │   ├── config_migrator.py
│   │   ├── crash_handler.py
│   │   ├── singleton.py
│   │   ├── json_store.py
│   │   ├── path_resolver.py
│   │   ├── protocols.py
│   │   ├── project_data.py
│   │   ├── sidebar_favorites.py
│   │   ├── sidebar_recent.py
│   │   └── plugins/
│   ├── panels/
│   │   ├── base.py                # PanelContent 基类
│   │   ├── empty.py
│   │   ├── sidebar.py             # 侧边栏
│   │   ├── info.py                # 信息面板
│   │   ├── image_viewer.py        # 全屏查看器
│   │   ├── tag_tree.py
│   │   └── file_list/
│   │       ├── __init__.py         # QWidgetFileListPanel
│   │       ├── _base.py            # FileListPanel (QListView 兼容)
│   │       ├── _grid_widget.py     # 自定义 Canvas
│   │       ├── _grid_layout.py     # 网格布局计算
│   │       ├── _model.py           # FileSystemModel
│   │       ├── _delegate.py        # GridDelegate
│   │       ├── _loader.py          # ThumbnailLoader + QThreadPool
│   │       ├── _actions.py         # 文件操作
│   │       ├── _navigation.py      # 导航
│   │       ├── _common.py          # 常量
│   │       ├── _detail_model.py
│   │       ├── _cached_view.py
│   │       └── _toast.py
│   ├── widgets/
│   │   ├── workspace_bar.py       # 工作区标签栏
│   │   ├── title_bar.py
│   │   ├── lan_sharing.py
│   │   ├── tab_container.py
│   │   └── tray.py
│   ├── i18n/
│   │   ├── __init__.py
│   │   ├── en.json
│   │   ├── zh.json
│   │   └── ja.json
│   ├── lan/
│   │   ├── __init__.py
│   │   ├── api.py
│   │   ├── server.py
│   │   ├── manager.py
│   │   ├── security.py
│   │   ├── tunnel.py
│   │   ├── scanner.py
│   │   ├── ws.py
│   │   ├── auth.py
│   │   └── static/
│   └── themes/
│       ├── default.json
│       ├── navy.json / slate.json / forest.json / amber.json
│       ├── dawn.json / silver.json / mint.json
│       ├── dracula.json / gruvbox.json / nord.json / rosepine.json
```

---

## 二、审计维度

### A. 性能热区

**重点关注**：

| 序号 | 文件 | 关注点 | 原因 |
|------|------|--------|------|
| A1 | `_grid_widget.py` | `paintEvent` | 自定义 QPainter 渲染所有文件卡片，每帧遍历可见行。检查：纹理缓存效率、batch 绘制、脏区域追踪 |
| A2 | `_loader.py` | `ThumbnailLoader` | QThreadPool(3) 并行加载。检查：线程数是否合理、WebP 编解码开销、QPixmapCache 命中率 |
| A3 | `_model.py` | `data()` / `rowCount()` | 大目录（>10K 文件）下的列表模型性能。检查：是否有全量扫描、排序开销 |
| A4 | `_delegate.py` | `paint()` | 旧的 GridDelegate，备用路径。检查：是否仍在热点调用 |
| A5 | `window.py` | `paintEvent` | 背景图绘制。检查：每帧缩放开销、缓存命中率 |
| A6 | `themes.py` | `stylesheet()` | QSS 字符串拼接。检查：是否被频繁调用、缓存是否有效 |
| A7 | `sidebar.py` | `_populate()` | 重建整个树。检查：增量更新、懒加载深度限制 |
| A8 | `startup.py` | 卡列表 | 历史库卡片渲染。检查：是否使用了虚拟列表 |
| A9 | `info.py` | 异步目录大小 | `_start_async_dir_size`。检查：线程安全、取消策略 |
| A10 | `database.py` | SQLite WAL | 事务批处理、连接池。检查：频繁写入时的锁争用 |

**审计指令**：
- 搜索 `QTimer`、`QThreadPool`、`threading` 的使用——确认是否有泄漏或未管理的线程
- 搜索 `for.*range` + `len(` 模式——可能的大循环
- 搜索 `QPixmapCache`、`QCache` 使用——确认缓存上限
- 检查所有 `paintEvent` 是否绘制了不可见区域

---

### B. 功能性错误

**重点关注**：

| 序号 | 文件 | 关注点 | 风险 |
|------|------|--------|------|
| B1 | 全局 | `themes.get()` 调用未缓存 | 主题切换后仍有组件使用旧颜色。搜索：哪些组件未连接 `theme_changed` 信号 |
| B2 | `_actions.py` | 文件删除/粘贴 | 后台线程操作。检查：错误处理、撤销栈、线程安全 |
| B3 | `_navigation.py` | FS watcher | 文件系统监控。检查：重命名/移动时的路径解析、符号链接处理 |
| B4 | `_model.py` | `data(DIR_SIZE_ROLE)` | 非阻塞但返回缓存值。检查：首次加载时返回空→0 闪变 |
| B5 | `_loader.py` | `clear_thumb_cache()` / `regenerate_all()` | 异步操作。检查：操作进行中用户关闭库/退出 |
| B6 | `window.py` | Dock 状态保存/恢复 | `save_state` / `restore_state`。检查：序列化/反序列化边界 |
| B7 | `settings.py` | JSON 原子写入 | `AppSettings.save()`。检查：并发写入、损坏恢复 |
| B8 | `sidebar.py` | `_populate()` 重建时 | 展开状态丢失。检查：`_fav_expanded` / `_rec_expanded` 是否正确恢复 |
| B9 | `startup.py` | `_LibraryCard._setup()` | 卡状态点颜色。检查：路径变更后是否存在卡不存在但状态显示为绿色 |
| B10 | `tabbed_dialog.py` | `showEvent` 懒连接 | 连接未在 `closeEvent` 中断开。检查：重复打开/关闭对话框时信号累加 |
| B11 | `i18n/__init__.py` | 动态语言切换 | 检查：哪些 UI 组件未在 `language_changed` 时刷新 |
| B12 | `lan/` | aiohttp 服务器 | 检查：空路径/无效路径请求、文件越权读取、并发连接上限 |

**审计指令**：
- 搜索 `except Exception` 或 `except:` 的裸捕获——是否有吞掉关键错误
- 搜索 `os.path` vs `pathlib.Path` 混用——跨平台路径问题
- 搜索 `QFileInfo`、`QDir` 的返回值——是否有未检查 `exists()`
- 搜索 `emit` 信号——是否有信号发出但无接收者导致的静默失败
- 搜索 `None` 访问——是否有未初始化的属性访问风险

---

### C. 低质量代码

**检查项**：

| 序号 | 类别 | 检查内容 |
|------|------|----------|
| C1 | 重复代码 | 多个文件中相似的 QSS 生成逻辑、相似的 setup/refresh 配对模式 |
| C2 | 魔法数字 | 硬编码的像素值、颜色值、超时值。应通过 tokens 或常量引用 |
| C3 | 命名规范 | 私有方法是否用 `_` 前缀、类名是否 PascalCase、常量是否 UPPER_CASE |
| C4 | 类型标注 | 是否有 `Any` 泛滥、缺失返回类型、`Optional` 未处理 |
| C5 | 资源管理 | QTimer/QThreadPool 是否在 `closeEvent`/`shutdown` 中正确清理 |
| C6 | 信号连接 | 是否在 `shutdown()` 中断开所有连接（防止野指针） |
| C7 | 导入顺序 | 标准库 → 第三方 → 项目内部 |
| C8 | 文档字符串 | 公开 API 是否有 docstring |
| C9 | LSP 诊断 | 搜索 `# type: ignore`、`pyright: ignore` 标识 |
| C10 | 死代码 | 未使用的 import、未调用的函数、永远为 False/True 的条件 |

**审计指令**：
- 运行 pylint / ruff / mypy / pyright 并收集诊断
- 搜索 `TODO`、`FIXME`、`HACK`、`XXX` 注释
- 搜索 `pass` 语句块（是否为未实现的桩）
- 搜索 `import *` 通配符导入
- 检查 `sys._MEIPASS` 访问是否有 `getattr` 保护

---

## 三、审计输出格式

请按以下格式输出每个发现：

```markdown
### [类别]-[序号] 标题
- **文件**: `path/file.py:123`
- **严重度**: Critical / High / Medium / Low
- **描述**: 一句话说明问题
- **复现**: 触发条件
- **建议**: 修复方向
```

最后附上汇总表：

```markdown
| 类别 | Critical | High | Medium | Low | 合计 |
|------|----------|------|--------|-----|------|
| 性能 |          |      |        |     |      |
| 功能 |          |      |        |     |      |
| 质量 |          |      |        |     |      |
```

---

## 四、优先审计路径

建议按以下顺序推进（每个步骤完成后报告发现）：

1. **文件级扫描**：遍历所有 `.py` 文件，检查 `import` 错误、语法错误、LSP 诊断
2. **性能热区**：按 A1→A10 顺序逐文件审计
3. **功能性错误**：按 B1→B12 顺序逐文件审计
4. **代码质量**：全量 C1→C10 检查
5. **汇总报告**：按输出格式整理

---

## 五、设计约束（审计时需注意）

- **主题系统 v2**：所有颜色通过 `themes.get()` 获取，禁止硬编码 `#XXXXXX`
- **透明度原则**：同色组件只用最外层 PanelContent 一层半透，内部全透
- **单一 QSS**：Dialog 级别只设一次 `setStyleSheet`，子控件不单独设（除 heading/muted/gear btn）
- **TabbedDialog 模板**：`core/tabbed_dialog.py` 是唯一 Dialog 基类
- **QWidget 画布**：`_grid_widget.py` 替代 QListView 作为默认渲染
- **后台文件操作**：`_paste`/`_delete`/`_undo` 全部通过 `_run_in_background()` + `on_done`
- **I18n**：所有用户可见文字应通过 `tr()` 获取
- **条件导入**：LAN 共享和 AI tagger 使用 `try/except ImportError` 可选加载
