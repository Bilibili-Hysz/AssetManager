# 2026-06-17~18 批:架构重构与主题系统(决策摘要)
> 状态:**历史蒸馏(已完结会话摘要)** · 2026-08-27 内容级合并自 compose-raw 原件,原件见 docs/archive/2026-08/compose-raw/ · 状态登记:2026-09-02(文档梳理轮补登)


> 摘要起草: 2026-08-27 · 源文件: `docs/compose/specs/2026-06-17-refactor-architecture-design.md`、`2026-06-18-custom-theme-system-design.md`、`2026-06-18-theme-editor-phase2-design.md` + `docs/compose/plans/2026-06-17-refactor-architecture.md`、`2026-06-18-custom-theme-system.md`、`2026-06-18-theme-editor-phase2.md`、`2026-06-18-theme-editor-phase3.md` · 原件归档: `docs/archive/2026-08/compose-raw/`

## 背景

- 06-17:启动"严格分层架构重构",7 阶段自底向上(SQLite 线程安全 → 应用层清理 → lan/auth.py 清理 → 单例移除 → 面板解耦 → 会话生命周期 → 架构边界测试),目标:每层只经明确定义接口依赖下层,消灭全局函数回退/重复代码/隐式跨线程访问。
- 06-18:主题系统两阶段——自定义主题基础设施(文件迁移 + ThemeLoader + 选择器 UI)与主题编辑器(实时预览 + HSV 取色器)。

## 决策要点(决策 | 出处)

1. **架构重构 7 阶段 + 每阶段独立可提交**:P1 SQLite 跨线程安全(审计 LAN 路由 DB 路径,回归测试并发读)→ P2 应用服务统一 ConnectionProvider(移除 `get_lib_db()` 回退)→ P3 lan/auth.py 只留 re-export + init_tables,DB 操作迁入 AuthRepository/ShareRepository → P4 移除 `get_manager()/get_store()/get_project_data()/get_library_service()` 全局单例(先 deprecated 包装再删)→ P5 面板删除 `has_bootstrap()` 回退路径,强制 `require_scoped_services()` → P6 LibrarySession.close() 关闭会话资源、切库先关旧会话、is_closed 守卫 → P7 扩展架构边界测试(domain 不 import sqlite3/上层;repositories 只依赖 core.database+domain;lan 不 import Qt/panels 等) | design [S2-S9]
2. **质量门(每任务)**:`ruff check .` + `pyright` + `compileall AssetsManager -q` + `pytest -q`(当时基线 603 passed) | design [S1]
3. **主题文件约定**:`Assets/Themes/` 下 `D_`(暗,内置不可编辑)/`L_`(亮,内置)/`U_`(用户,可编辑可删)前缀;旧 `AssetsManager/themes/*.json` 迁移并自动映射旧主题名;PyInstaller datas 更新 | custom-theme-design [S1][S4]
4. **ThemeLoader 动态加载**:启动扫描 + JSON schema 校验(必须含 colors/properties)+ QFileSystemWatcher 热重载;`core/themes.py` 改为委托 ThemeLoader | [S2]
5. **主题选择器三入口**:外观模式(Dark/Light/Follow System)过滤、主题菜单(悬停预览/点击确认/可复制为自定义)、自定义菜单(编辑/导出/删除/新建 U_ 前缀) | [S3]
6. **主题编辑器实时预览**:设置对话框左右分栏(左:外观模式+主题列表+自定义;右:全组件预览:按钮/输入/标签/列表/表格/对话框/复选/滑条/进度/GroupBox);选主题→apply_theme 实时渲染 | theme-editor-phase2 [S1][S2]
7. **HSV 取色器**:HSV 色轮 + 亮度滑条 + RGB/HSV 切换 + HEX 输入 + 实时预览;预览区色块点击打开,改色实时应用到主题 JSON | phase3(基于 phase2 [S4])

## 落地状态(2026-08-27 抽查)

- **架构分层:✅ 已落地并继续演进**:`check_boundaries.py`/`check_layers.py` 门禁 + `tests/unit/test_architecture_boundaries.py` 均存在且全绿;`tag_store.get_store()`、`project_data.get_project_data()` 仍保留为 deprecated 包装(部分旧单例清理未彻底,属已知遗留);`LibrarySession` 具备 `_begin_close/_finish_close/is_closed` 语义(远超 P6 范围)。
- **主题基础设施:✅ 已落地**:`core/theme_loader.py`(315 行,scan/validate/hot-reload)+ `core/themes.py`(735 行,委托加载 + 22 主题)+ `Assets/Themes/`(24 JSON);`dialogs/settings_dialog.py` 主题选择器;`core/color_utils.py`/`ui_scale.py` 支持。
- **主题编辑器:✅ 已落地**:`widgets/theme_preview.py`(714)+ `dialogs/theme_preview_dialog.py`(238)+ `dialogs/color_picker_dialog.py`(216)+ `widgets/hsv_wheel.py`(218)。
- P1 审计结论记录于 `docs/compose/plans/p1-audit-findings.md`("无并发安全问题,修复可跳过",见 07-17 批摘要)。

## 仍生效的约束或未决项

- 层依赖规则(domain 零上层依赖、panels 不经 DB、lan 不 import Qt)仍是当前架构红线,由静态门禁强制。
- deprecated 全局包装(`get_store`/`get_project_data` 等)仍未完全移除——作为兼容 seam 保留,新代码不得使用。
- 主题文件前缀约定与"热重载"语义仍生效。