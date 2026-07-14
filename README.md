# AssetManager

**Python 桌面资产管理器 + 局域网分享服务器**

AssetManager 是一款基于 PySide6 (Qt) 的桌面资产管理应用，内置 aiohttp 局域网分享服务器。用户可以通过桌面端管理文件资产库（元数据、标签、缩略图），也可以通过局域网内的浏览器远程浏览和下载资产。

---

## 目录

- [功能特性](#功能特性)
- [技术栈](#技术栈)
- [项目架构](#项目架构)
- [项目结构](#项目结构)
- [快速开始](#快速开始)
- [开发指南](#开发指南)
- [构建与部署](#构建与部署)
- [LAN 分享系统](#lan-分享系统)
- [插件系统](#插件系统)
- [国际化](#国际化)
- [测试](#测试)

---

## 功能特性

### 桌面端 (PySide6)

- **文件浏览**：网格/列表视图，支持缩略图预览、元数据显示、标签管理
- **多库支持**：在多个资产库之间切换，每个库独立的数据库和设置
- **图片查看器**：内置图片预览，支持缩放、平移
- **标签系统**：为文件添加标签，支持标签树、标签搜索、批量操作
- **元数据管理**：为文件添加备注、URL 链接、自定义属性
- **撤销/重做**：文件操作支持撤销和重做（按库隔离）
- **主题系统**：深色/浅色/自定义主题，支持实时预览和切换
- **背景效果**：支持模糊/马赛克背景效果
- **插件系统**：可扩展的插件架构，支持自定义分类、菜单、文件处理器
- **系统托盘**：最小化到系统托盘，支持快捷操作
- **工作区标签**：多标签页浏览不同目录
- **快捷键**：丰富的键盘快捷键支持

### 局域网分享 (aiohttp)

- **文件浏览**：通过浏览器浏览资产库，支持网格/列表视图
- **文件下载**：单文件下载和批量 ZIP 打包下载
- **分享链接**：创建密码保护、限时、限次的分享链接
- **用户系统**：管理员/注册用户/访客三级权限，支持邀请码注册
- **QR 码**：生成分享链接的 QR 码，支持一键复制
- **Cloudflare 隧道**：一键暴露到公网，支持自动下载 cloudflared
- **WebSocket**：实时事件推送
- **安全机制**：速率限制、IP 黑名单、路径遍历防护、认证中间件
- **移动端适配**：响应式布局，底部操作栏，触摸优化

### 国际化

- 支持英语、中文、日语三种语言
- 桌面端和 Web 端均有完整翻译
- Web 端自动检测浏览器语言，支持手动切换

---

## 技术栈

### 核心框架

| 技术 | 版本 | 用途 |
|------|------|------|
| Python | 3.14 | 主语言 |
| PySide6 | >=6.6 | 桌面 UI 框架 (Qt 6) |
| aiohttp | >=3.9 | 异步 HTTP 服务器 |
| SQLite3 | 内置 | 数据库 (WAL 模式) |
| Pillow | >=10.0 | 图片处理 |
| segno | >=1.6 | QR 码生成 |

### 桌面 UI

| 组件 | 说明 |
|------|------|
| QDockWidget | 可拖拽停靠面板 |
| QAbstractListModel | 文件列表数据模型 |
| QPropertyAnimation | UI 动画 |
| QGraphicsBlurEffect | 背景模糊效果 |
| QThreadPool | 异步任务执行 |
| signal_bus | Qt 信号总线（跨面板通信） |
| event_bus | 领域事件总线（业务逻辑） |

### LAN 服务器

| 组件 | 说明 |
|------|------|
| aiohttp.web | REST API + WebSocket |
| aiohttp middleware | 认证、安全、速率限制 |
| PathGuard | 路径遍历防护 |
| JWT-like tokens | 认证令牌 |
| Cloudflare Tunnel | 公网穿透（可选） |

### 数据层

| 组件 | 说明 |
|------|------|
| DatabaseManager | 连接池管理，每库独立连接 |
| TagRepository | 标签 CRUD |
| MetadataRepository | 元数据 CRUD |
| ShareRepository | 分享链接 CRUD |
| AuthRepository | 用户/邀请码 CRUD |
| ThumbnailRepository | 缩略图缓存 |
| db_migrations | 版本化数据库迁移 |

### 开发工具

| 工具 | 用途 |
|------|------|
| ruff | 代码风格检查 |
| pyright | 类型检查 |
| pytest | 测试框架 |
| Cython | 热点模块编译加速 |
| PyInstaller | 打包为独立 exe |

---

## 项目架构

```
┌─────────────────────────────────────────────────────────┐
│                    Presentation Layer                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
│  │  Panels   │  │ Dialogs  │  │ Widgets  │  │ LAN UI  │ │
│  │(file_list,│  │(settings,│  │(toast,   │  │(HTML/JS) │ │
│  │ sidebar,  │  │ share,   │  │ tray,    │  │         │ │
│  │ info,tag) │  │ startup) │  │ tab)     │  │         │ │
│  └─────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬────┘ │
│        └──────────────┼──────────────┼──────────────┘     │
├───────────────────────┼──────────────┼────────────────────┤
│                 Controllers Layer                         │
│  ┌─────────────────┐ ┌────────────┐ ┌──────────────────┐ │
│  │FileListController│ │InfoController│ │SidebarController│ │
│  └────────┬────────┘ └─────┬──────┘ └────────┬─────────┘ │
├───────────┼────────────────┼──────────────────┼───────────┤
│                  Application Layer                        │
│  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐ │
│  │AssetService│ │TagService│ │MetadataService│ │LibraryService│ │
│  │SearchService│ │ShareService│ │AuthService│ │ThumbnailService│ │
│  └────┬────┘ └────┬─────┘ └────┬─────┘ └──────┬───────┘ │
├───────┼──────────┼───────────┼──────────────────┼─────────┤
│                   Domain Layer                            │
│  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐ │
│  │  events  │ │  errors  │ │  asset   │ │    share     │ │
│  │ event_bus│ │  auth    │ │ library  │ │              │ │
│  └─────────┘ └──────────┘ └──────────┘ └──────────────┘ │
├───────────────────────────────────────────────────────────┤
│                Infrastructure Layer                        │
│  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐ │
│  │database  │ │ settings │ │  themes  │ │   plugins    │ │
│  │  cache   │ │json_store│ │  i18n    │ │  path_resolver│ │
│  └─────────┘ └──────────┘ └──────────┘ └──────────────┘ │
└───────────────────────────────────────────────────────────┘
```

### 架构原则

- **分层架构**：Domain → Application → Presentation，依赖向下流动
- **依赖注入**：`ApplicationBootstrap` 通过 `ServiceContainer` 管理服务生命周期
- **领域事件**：业务事件通过 `event_bus` 发布，UI 通过 `_event_bridge` 订阅
- **Qt 信号**：UI 层内部通信使用 Qt 信号/槽机制
- **Repository 模式**：所有 SQL 操作封装在 Repository 中
- **LibrarySession**：每库独立的服务作用域，切换库时注入新服务

---

## 项目结构

```
AssetsManager_old-bak/
├── AssetsManager/              # 主包
│   ├── app.py                  # 应用入口（启动窗口 → 主窗口）
│   ├── window.py               # 主窗口（QMainWindow + LanSharingMixin）
│   ├── window_coordinator.py   # 窗口协调器（主题/语言/菜单）
│   ├── dock_factory.py         # QDockWidget 工厂
│   │
│   ├── application/            # 应用服务层
│   │   ├── asset_service.py    # 文件浏览服务
│   │   ├── tag_service.py      # 标签管理服务
│   │   ├── metadata_service.py # 元数据服务
│   │   ├── search_service.py   # 搜索服务
│   │   ├── share_service.py    # 分享链接服务
│   │   ├── auth_service.py     # 认证服务
│   │   ├── library_service.py  # 库生命周期管理
│   │   ├── undo_service.py     # 撤销/重做服务
│   │   ├── bootstrap.py        # 依赖注入引导
│   │   ├── context.py          # LibrarySession/LibraryContext
│   │   └── ...
│   │
│   ├── controllers/            # UI 控制器（非 Qt 业务逻辑）
│   │   ├── file_list_controller.py
│   │   ├── info_controller.py
│   │   ├── sidebar_controller.py
│   │   └── tag_tree_controller.py
│   │
│   ├── core/                   # 基础设施层
│   │   ├── database.py         # DatabaseManager（连接池、WAL）
│   │   ├── db_migrations.py    # 数据库迁移
│   │   ├── directory_cache.py  # 目录元数据缓存
│   │   ├── settings.py         # AppSettings（持久化设置）
│   │   ├── themes.py           # 主题系统
│   │   ├── theme_loader.py     # 主题文件加载
│   │   ├── signal_bus.py       # Qt 信号总线
│   │   ├── cache.py            # LRUCache/TTLCache（线程安全）
│   │   ├── json_store.py       # JSON 持久化存储
│   │   ├── tag_store.py        # 标签存储（委托 TagRepository）
│   │   ├── path_resolver.py    # 路径解析（RuntimeData/LibraryData）
│   │   ├── ui_scale.py         # HiDPI 缩放
│   │   ├── color_utils.py      # 颜色工具
│   │   ├── format_utils.py     # 格式化工具
│   │   ├── bg_effects.py       # 背景效果（模糊/马赛克）
│   │   ├── tool_scheduler.py   # 外部工具调度
│   │   ├── crash_handler.py    # 崩溃处理
│   │   └── plugins/            # 插件系统
│   │       ├── descriptor.py   # 插件描述符
│   │       ├── host_context.py # 宿主上下文（权限、贡献）
│   │       ├── loader.py       # 插件加载器
│   │       └── manager.py      # 插件管理器
│   │
│   ├── domain/                 # 领域层
│   │   ├── events.py           # 领域事件（LibraryOpened, FileRenamed 等）
│   │   ├── event_bus.py        # 领域事件总线
│   │   ├── errors.py           # 领域错误
│   │   ├── asset.py            # 资产值对象
│   │   ├── auth.py             # 认证工具（哈希、令牌）
│   │   ├── library.py          # 库值对象
│   │   └── share.py            # 分享链接值对象
│   │
│   ├── repositories/           # 数据访问层
│   │   ├── tag_repository.py
│   │   ├── metadata_repository.py
│   │   ├── share_repository.py
│   │   ├── auth_repository.py
│   │   └── thumbnail_repository.py
│   │
│   ├── lan/                    # LAN 服务器
│   │   ├── server.py           # aiohttp 服务器（认证中间件）
│   │   ├── api.py              # 路由注册
│   │   ├── auth.py             # 认证工具
│   │   ├── path_guard.py       # 路径遍历防护
│   │   ├── security.py         # 速率限制、IP 黑名单
│   │   ├── scanner.py          # 目录扫描器
│   │   ├── tunnel.py           # Cloudflare 隧道
│   │   ├── ws.py               # WebSocket 管理
│   │   ├── routes/             # API 路由处理器
│   │   │   ├── auth.py         # 登录/注册/验证
│   │   │   ├── files.py        # 文件列表
│   │   │   ├── downloads.py    # 文件下载
│   │   │   ├── shares.py       # 分享链接
│   │   │   ├── tags.py         # 标签管理
│   │   │   ├── thumbnails.py   # 缩略图
│   │   │   ├── metadata.py     # 元数据/搜索/项目
│   │   │   ├── users.py        # 用户管理
│   │   │   ├── system.py       # 系统信息
│   │   │   └── websocket.py    # WebSocket 处理
│   │   └── static/             # Web UI 前端
│   │       ├── index.html      # 主页面（三栏布局）
│   │       ├── share.html      # 分享页面
│   │       ├── login.html      # 登录页面
│   │       ├── detail.html     # 详情页面
│   │       ├── app.js          # 主应用逻辑
│   │       ├── style.css       # 样式（暗色主题）
│   │       ├── i18n.js         # 国际化框架
│   │       └── i18n/           # 翻译文件（en/zh/ja）
│   │
│   ├── panels/                 # Qt 停靠面板
│   │   ├── file_list/          # 文件列表面板（网格/列表/详情）
│   │   ├── sidebar.py          # 侧边栏（目录树/收藏/最近）
│   │   ├── info.py             # 信息面板（元数据/标签/备注）
│   │   ├── tag_tree.py         # 标签树面板
│   │   ├── image_viewer.py     # 图片查看器
│   │   └── _event_bridge.py    # 领域事件 → Qt 信号桥接
│   │
│   ├── dialogs/                # Qt 对话框
│   │   ├── settings_dialog.py         # 设置对话框
│   │   ├── sharing_settings_dialog.py # 分享系统对话框（4 Tab）
│   │   ├── share_link_dialog.py       # 创建分享链接
│   │   ├── share_link_manager.py      # 管理分享链接
│   │   ├── quick_share_card.py        # 快速分享卡片
│   │   ├── startup.py                 # 启动窗口（库选择）
│   │   ├── tag_editor_dialog.py       # 标签编辑器
│   │   ├── plugin_manager_dialog.py   # 插件管理器
│   │   ├── theme_preview_dialog.py    # 主题预览
│   │   └── collapsible_panel.py       # 可折叠面板组件
│   │
│   ├── widgets/                # 可复用 Qt 组件
│   │   ├── toast.py            # Toast 通知
│   │   ├── tab_container.py    # 标签页容器
│   │   ├── workspace_bar.py    # 工作区标签栏
│   │   ├── tray.py             # 系统托盘
│   │   ├── tag_chip.py         # 标签芯片
│   │   ├── title_bar.py        # 自定义标题栏
│   │   ├── hsv_wheel.py        # HSV 颜色选择器
│   │   └── lan_sharing.py      # LAN 分享 Mixin
│   │
│   ├── di/                     # 依赖注入容器
│   └── i18n/                   # 国际化
│       ├── en.json             # 英语
│       ├── zh.json             # 中文
│       └── ja.json             # 日语
│
├── tests/                      # 测试套件（720+ 测试）
│   ├── core/                   # 核心基础设施测试
│   ├── unit/                   # 单元测试（领域、控制器、过滤器）
│   ├── integration/            # 集成测试（SQLite、服务）
│   ├── desktop/                # 桌面 UI 测试（PySide6 offscreen）
│   ├── lan/                    # LAN API 安全测试
│   └── performance/            # 性能基准测试
│
├── docs/                       # 文档
│   ├── compose/specs/          # 设计规格
│   ├── compose/plans/          # 实施计划
│   └── adr/                    # 架构决策记录
│
├── Plugins/                    # 插件
│   ├── Addons/booth_link/      # Booth 链接解析器
│   ├── Addons/download_tracker/# 下载追踪器
│   └── Docs/                   # 插件文档
│
├── Assets/Themes/              # 主题 JSON 文件
├── RuntimeData/                # 运行时数据（设置、缓存）
├── main.py                     # 入口脚本
├── run.py                      # 运行脚本
├── build.py                    # 构建脚本
├── setup_cython.py             # Cython 编译脚本
├── AssetManager.spec           # PyInstaller 打包规格
├── pyrightconfig.json          # Pyright 配置
├── pytest.ini                  # Pytest 配置
├── requirements.txt            # 核心依赖
├── requirements-lan.txt        # LAN 依赖
└── requirements-dev.txt        # 开发依赖
```

---

## 快速开始

### 环境要求

- Python 3.12+ (推荐 3.14)
- Windows 10/11 (主要平台)
- Visual Studio Build Tools (Cython 编译需要)

### 安装

```bash
# 克隆项目
git clone <repo-url>
cd AssetsManager_old-bak

# 安装核心依赖
pip install -r requirements.txt

# 安装 LAN 分享依赖（可选）
pip install -r requirements-lan.txt

# 安装开发依赖（可选）
pip install -r requirements-dev.txt
```

### 运行

```bash
# 启动应用
python main.py

# 或使用预构建的 exe
dist/AssetManager/AssetManager.exe
```

### 首次启动

1. 启动后显示「启动窗口」
2. 选择或创建一个资产库目录
3. 进入主窗口，开始浏览文件

---

## 开发指南

### 质量门

每次提交前必须通过：

```bash
python -m ruff check . --exclude ".Cython&Noikta"
python -m pyright
python -m compileall AssetsManager -q
python -m pytest -q
```

当前状态：**720 passed, 0 warnings**

### Cython 编译加速

```bash
# 安装 Cython
pip install cython

# 编译热点模块（LRUCache, color_utils, format_size, asset_filters）
python setup_cython.py build_ext --inplace

# 验证加速效果
python -m pytest tests/performance/test_cython_benchmarks.py -v -s
```

加速效果：
| 模块 | 编译前 | 编译后 | 提升 |
|------|--------|--------|------|
| format_size | 1.2M ops/s | 2.8M ops/s | 2.3x |
| is_hidden | 10M ops/s | 14.9M ops/s | 1.5x |
| hex_to_rgb | 2.1M ops/s | 3.2M ops/s | 1.5x |
| matches_search | 7.3M ops/s | 9.8M ops/s | 1.3x |

### 性能基准测试

```bash
python -m pytest tests/performance/test_baselines.py -v
```

测试内容：
- 1K/10K 文件目录列表
- 元数据读取延迟
- 标签列表性能
- PathGuard 路径解析
- 索引搜索性能
- 分享链接创建/读取
- 目录缓存冷/热对比

---

## 构建与部署

### PyInstaller 打包

```bash
# 完整构建（清理 + 编译 + 优化 + 报告）
python build.py --clean --build --optimize --report

# 输出
# dist/AssetManager/AssetManager.exe (127 MB)
```

### 构建优化

| 优化项 | 节省 |
|--------|------|
| Cloudflare 延迟下载 | -51.6 MB |
| 删除 opengl32sw.dll | -19.7 MB |
| 排除未使用 Qt/PIL 模块 | -31.6 MB |
| 精简翻译文件 | -3 MB |
| **总计** | **262 MB → 127 MB** |

### CI/CD

GitHub Actions 工作流（`.github/workflows/ci.yml`）：

```yaml
- Lint: ruff check
- Type Check: pyright
- Test: compileall + pytest (Python 3.12, 3.13, 3.14)
```

---

## LAN 分享系统

### 启动分享

```python
# 桌面端：点击工具栏的分享按钮
# 或通过代码：
from AssetsManager.lan.server import LanServer
server = LanServer(library_root="/path/to/library", ...)
server.start(port=8080)
```

### API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/files` | GET | 文件列表 |
| `/api/projects` | GET | 项目列表 |
| `/api/search` | GET | 搜索 |
| `/api/tags` | GET/POST | 标签管理 |
| `/api/shares` | GET/POST | 分享链接 |
| `/api/download/{path}` | GET | 文件下载 |
| `/api/download/batch` | POST | 批量下载 |
| `/api/thumbnails/{path}` | GET | 缩略图 |
| `/api/auth/login` | POST | 登录 |
| `/api/auth/register` | POST | 注册 |
| `/api/users` | GET | 用户列表 |
| `/api/stats` | GET | 服务器统计 |
| `/s/{id}` | GET | 分享链接页面 |

### 权限模型

| 角色 | 浏览 | 下载 | 上传 | 管理链接 | 管理用户 | 设置 |
|------|------|------|------|----------|----------|------|
| 管理员 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 注册用户 | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| 访客 | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |

### 分享链接权限

- **只读**：只能预览（图片/视频/文本）
- **可下载**：预览 + 下载
- **密码保护**：需要输入密码才能访问
- **限时**：过期后自动失效
- **限次**：达到下载次数后自动失效

---

## 插件系统

### 插件结构

```
Plugins/Addons/my_plugin/
├── plugin.json     # 插件描述符
├── parser.py       # 入口模块
└── ...
```

### plugin.json

```json
{
  "id": "my_plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "entry": "parser.py",
  "permissions": ["filesystem.read"]
}
```

### 插件能力

- 注册自定义文件分类
- 添加菜单项和工具栏按钮
- 注册文件解析器
- 注册搜索提供者
- 注册主题令牌
- 注册事件钩子

### 权限系统

插件权限是建议性的（advisory），不强制执行。插件运行在完整的 Python 解释器中，拥有完全的系统访问权限。

---

## 国际化

### 支持语言

| 语言 | 文件 | 状态 |
|------|------|------|
| English | `i18n/en.json` | ✅ 完整 |
| 中文 | `i18n/zh.json` | ✅ 完整 |
| 日本語 | `i18n/ja.json` | ✅ 完整 |

### 添加新语言

1. 复制 `i18n/en.json` 为 `i18n/xx.json`
2. 翻译所有键值
3. 在 `i18n/__init__.py` 中注册语言代码

### Web 端 i18n

Web 端使用独立的 i18n 系统：
- `static/i18n.js` — 轻量级 JS i18n 库
- `static/i18n/{lang}.json` — 翻译文件
- 自动检测浏览器语言，支持 `localStorage` 手动切换

---

## 测试

### 测试结构

```
tests/
├── core/           # 核心基础设施测试（数据库、设置、主题、缓存）
├── unit/           # 单元测试（领域、控制器、过滤器、事件）
├── integration/    # 集成测试（服务层、Repository、库生命周期）
├── desktop/        # 桌面 UI 测试（PySide6 offscreen 模式）
├── lan/            # LAN API 测试（安全、路由、路径防护）
└── performance/    # 性能基准测试（目录列表、元数据、搜索）
```

### 运行测试

```bash
# 全部测试
python -m pytest -q

# 特定目录
python -m pytest tests/unit/ -q
python -m pytest tests/lan/ -q

# 性能测试
python -m pytest tests/performance/ -v

# Cython 加速测试
python -m pytest tests/performance/test_cython_benchmarks.py -v -s
```

### 测试 fixture

- `temp_dir` — 临时目录
- `memory_db` — 内存 SQLite 数据库
- `schema_db` — 带完整 schema 的内存数据库
- `_cleanup_stores` (autouse) — 测试后清理全局状态
- `_ensure_qapp` — PySide6 QApplication 初始化

---

## 许可证

私有项目。
