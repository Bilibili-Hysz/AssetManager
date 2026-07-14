# AssetManager 项目总结

> Archived snapshot. This document reflects the project summary before the 2026-06-16 workspace flattening. See `docs/workspace.md` for the current layout.

**版本**：2.0.0（重构版）
**日期**：2026-06-12
**状态**：生产就绪

---

## 一、项目简介

AssetManager 是一款面向数字艺术家和创意工作者的桌面资产库管理工具，基于 PySide6 构建，支持本地文件浏览、标签管理、元数据编辑、LAN 远程访问、缩略图预览、插件扩展等功能。

软件采用 QDockWidget 可停靠面板布局，支持多工作区切换，适配 VRChat、Blender、Unity、Unreal 等创意工作流的资产组织需求。

---

## 二、软件功能简介

### 2.1 文件浏览
- Grid / Details 双视图
- 排序（名称/日期/大小/类型）、过滤（6 大分类）、搜索
- 缩略图异步加载 + 磁盘缓存
- 拖拽复制、右键菜单、批量操作
- 目录大小异步计算

### 2.2 标签与元数据
- SQLite 标签存储，支持多语言同义词规范库（80+ 内置标签）
- 标签颜色/图标/分类支持（DB migration v3）
- 备注、URL、目录大小缓存
- 标签树面板，支持按标签过滤

### 2.3 LAN 远程访问
- aiohttp HTTP 服务器，35+ API 端点
- 项目浏览、搜索、下载、缩略图
- 分享链接（密码保护、过期、下载限制）
- 用户管理、邀请码、Token 认证
- Cloudflare Tunnel 集成
- WebSocket 实时通知

### 2.4 插件系统
- `plugin.json` 清单 + `match()/parse()` 函数式插件
- Blender 风格注册式 API（7 种扩展点）
- 插件管理对话框（可视化启用/禁用/查看详情）

### 2.5 其他
- 22 种主题（深色/浅色）
- 国际化（中文/日文/英文）
- DPI 适配 + UI 全局缩放（50%-200%）
- 系统托盘、工作区标签、崩溃处理

---

## 三、重写目标

### 3.1 架构目标
- 将单体 PySide6 文件浏览器重构为分层平台
- 桌面 UI 与 LAN Web 服务器共享同一套应用服务层
- 建立清晰的依赖方向：Presentation → Application → Domain → Core
- 消除 `lan/api.py` 1800 行单体模块

### 3.2 质量目标
- 全量测试覆盖（从 90 → 200+）
- Ruff + Pyright + compileall + pytest 四重质量门禁
- 零 warnings
- 安全漏洞清零

### 3.3 工程目标
- 数据库 migration 体系
- 插件系统完整集成
- 性能基线建立
- 文档体系化

---

## 四、实现的目标

### 4.1 架构成果

| 指标 | 重构前 | 重构后 |
|---|---|---|
| Application 服务 | 0 | 16 |
| LAN 路由模块 | 1（1842 行） | 13 |
| Domain 层 | 无 | 6 个模块 |
| Repository 层 | 无 | 4 个 |
| Controller 层 | 无 | 1 个 |
| Dialog 层 | 散落在 core/ | 12 个独立模块 |
| DI 容器 | 无 | 1 个 |
| 事件总线 | 无 | 1 个 |

### 4.2 质量成果

| 指标 | 重构前 | 重构后 |
|---|---|---|
| 测试数 | 90 | 522 |
| warnings | 4 | 0 |
| Ruff | 未检查 | 通过 |
| Pyright | 未检查 | 0 errors |
| 安全漏洞 | 未审计 | 7 个已修复 |
| 并发问题 | 未审计 | 4 个已修复 |
| 数据正确性问题 | 未审计 | 3 个已修复 |

### 4.3 性能成果

| 操作 | 优化前 | 优化后 | 改善 |
|---|---|---|---|
| `list_projects` avg | 5463ms | 511ms | -90.6% |
| `list_directory` | 61.6ms | 31.3ms | -34.5% |
| `thumbnail_cache_key` | 冷调用 | 缓存命中 | -12% |
| LAN routes | 同步阻塞 | 异步非阻塞 | — |

### 4.4 插件系统成果

| 扩展点 | API | 状态 |
|---|---|---|
| 文件解析器 | `register_file_handler(plugin_id, match, parse)` | ✅ |
| 生命周期钩子 | `hook(event_type, handler)` | ✅ |
| 上下文菜单 | `register_context_menu_item(...)` | ✅ |
| 文件类型分类 | `register_category(plugin_id, key, label, extensions)` | ✅ |
| 自定义列 | `register_column(plugin_id, key, label, width, order)` | ✅ |
| 搜索提供者 | `register_search_provider(plugin_id, provider_id, label, search)` | ✅ |
| 主题 token | `register_theme_token(plugin_id, token, fallback)` | ✅ |
| 权限控制 | `permissions` manifest + `check_permission()` | ✅ |

---

## 五、重写过程概述

### 5.1 第一阶段：基础设施建立
- 质量门禁固化（Ruff/Pyright/compileall/pytest）
- 测试基线确认（90 passed → 目标 200+）
- 清理 ResourceWarning 和 AppKey warnings

### 5.2 第二阶段：服务层抽取
- 从 `lan/api.py` 单体抽取 16 个 Application Services
- LAN 路由拆分为 13 个模块
- 数据库 migration 体系（v1 → v2 → v3）
- 插件系统完整集成

### 5.3 第三阶段：质量加固
- 安全漏洞修复（7 个）
- 数据正确性修复（3 个）
- 并发安全修复（4 个）
- 错误处理改善（3 个）
- 测试加固（4 个）

### 5.4 第四阶段：架构优化
- Domain Layer 建立（errors/library/asset/share/events/event_bus）
- DI 容器（ServiceContainer）
- Repository Pattern（Tag/Metadata/Share/Auth）
- UI Layer Cleanup（FileListController）
- Core/Dialogs 边界分离

### 5.5 第五阶段：性能优化
- `list_projects` 批量缓存预热（-90.6%）
- `thumbnail_cache_key` mtime 缓存（-12%）
- `list_directory` 扫描去重（-34.5%）
- LAN routes 异步化
- 大目录分页支持

### 5.6 第六阶段：插件系统升级
- 原版插件系统移植（booth_link + docs）
- Blender 风格注册式 API（7 种扩展点）
- 插件管理对话框

### 5.7 第七阶段：UI 缩放
- 全局 QSS px → scaled_px
- Dialog/Panel 层缩放
- 动态缩放响应（信号驱动）

### 5.8 第八阶段：Tag 系统升级
- 统一 TagRepository + TagService
- TagStore 委托 TagRepository
- Tag metadata v3（颜色/图标/分类）
- 线程安全加固

---

## 六、当前架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        ENTRY POINTS                             │
│   main.py / run.py → app.py → window.py                        │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                    PRESENTATION LAYER                           │
│   dialogs/    panels/    widgets/    dock_factory               │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                    CONTROLLERS                                  │
│   FileListController (business logic without Qt)               │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                 APPLICATION SERVICES (16)                       │
│   LibraryService  AssetService  TagService  MetadataService    │
│   SearchService   ProjectService  FileOperationService         │
│   ThumbnailService  AuthService  ShareService  UndoService     │
│   PluginService  AssetIndexService  AssetFilters               │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                    DOMAIN LAYER                                 │
│   ShareLink  AssetPath  AssetType  LibraryPath                 │
│   DomainEvent  EventBus  DomainError hierarchy                 │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                 REPOSITORIES                                    │
│   TagRepository  MetadataRepository  ShareRepository           │
│   AuthRepository                                                │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│               DI CONTAINER                                      │
│   ServiceContainer (register/resolve)                           │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│              CORE INFRASTRUCTURE                                │
│   database.py  settings.py  themes.py  signal_bus.py           │
│   tag_store.py  project_data.py  plugins/                      │
│   path_resolver.py  db_migrations.py  protocols.py             │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│              EXTERNAL DEPS                                      │
│   PySide6  sqlite3  PIL/Pillow  aiohttp  send2trash            │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│              LAN LAYER (OPTIONAL)                               │
│   lan/server.py → lan/api.py → lan/routes/*                    │
│   lan/auth.py  lan/security.py  lan/path_guard.py              │
│   依赖: application services + core                            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 七、文档体系

| 文档 | 路径 | 内容 |
|---|---|---|
| 项目总结 | `docs/PROJECT_SUMMARY.md` | 本文档 |
| 架构图 | `docs/architecture-diagram.md` | 4 层架构图 + 数据流 |
| 架构说明 | `docs/architecture.md` | 服务层/LAN 路由/数据库/插件系统说明 |
| 优化计划 | `docs/architecture-optimization-plan.md` | 6 阶段优化路线（已全部完成） |
| 重构结果 | `docs/refactoring-results.md` | 改动汇总、文件统计、测试覆盖 |
| 重构基线 | `docs/refactor-baseline.md` | 86 个阶段进度记录 |
| 测试策略 | `docs/testing.md` | 质量门禁、测试布局、性能基线 |
| 开发规范 | `docs/development.md` | 开发规则 |
| 数据库迁移 | `docs/migrations.md` | Schema migration 政策 |
| LAN 安全 | `docs/lan-security.md` | 安全设计 |
| Core 清理计划 | `docs/core-cleanup-plan.md` | Core/Dialogs 分离计划 |
| 插件系统 | `Plugins/Docs/PLUGIN_SYSTEM.md` | 插件架构与实现 |
| 插件 API | `Plugins/Docs/API.md` | 插件接口规范 |
| 插件接口 | `Plugins/Docs/MODULE_INTERFACES.md` | 扩展点定义 |
| 性能基线 | `tests/perf_baseline.py` | 合成数据基线 |
| 真实库基线 | `tests/perf_real_world.py` | 大库性能基线 |
| 启动基线 | `tests/perf_startup.py` | 启动性能基线 |

---

## 八、技术栈

| 层 | 技术 |
|---|---|
| 桌面 UI | PySide6 (Qt6) |
| LAN 服务器 | aiohttp |
| 数据库 | SQLite (WAL mode) |
| 图片处理 | Pillow |
| 文件删除 | send2trash |
| 隧道 | Cloudflare Tunnel |
| 静态检查 | Ruff + Pyright |
| 测试 | pytest |
| 打包 | PyInstaller |

---

## 九、运行方式

```bash
# 开发模式
python main.py

# LAN 分享
# 启动后通过 Tools → Share System 开启

# 运行测试
python -m pytest

# 质量门禁
python -m ruff check . && python -m pyright && python -m compileall AssetsManager -q && python -m pytest

# 性能基线
python -m tests.perf_baseline
python -m tests.perf_real_world
python -m tests.perf_startup
```

---

## 十、致谢

本项目基于原版 AssetManager 进行全面重构，保留了所有核心功能，同时建立了现代化的分层架构、质量门禁和插件系统。感谢原版作者的基础工作。
