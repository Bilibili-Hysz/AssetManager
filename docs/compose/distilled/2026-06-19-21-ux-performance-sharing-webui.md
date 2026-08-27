# 2026-06-19~21 批:背景效果/主题 UI/性能优化/分享系统/WebUI 视觉(决策摘要)

> 摘要起草: 2026-08-27 · 源文件: `docs/compose/specs/2026-06-19-background-enhancement.md`、`2026-06-19-theme-ui-redesign.md`、`2026-06-20-performance-optimization-design.md`、`2026-06-20-sharing-ui-redesign.md`、`2026-06-21-share-system-redesign.md`、`2026-06-21-web-ui-visual-upgrade.md` + 对应同名 6 份 plans · 原件归档: `docs/archive/2026-08/compose-raw/`

## 背景

- 06-19~21 五条设计线:桌面背景增强(视频+模糊/马赛克)、主题选择器 UI 重构、性能优化(缓存+Cython)、分享模块 UI/UX 重设计、LAN Web UI 视觉升级。全部为 PySide6/WEB 前端层面的产品级设计,为后续 07-13 WebUI React 重写提供了视觉基线。

## 决策要点(决策 | 出处)

1. **背景增强**:设置项(+视频背景 QMediaPlayer 自动循环静音 + 图片模糊/马赛克,强度可调;视频时效果区置灰);存储键 `bg_type/bg_blur_enabled/bg_blur_intensity/bg_mosaic_enabled/bg_mosaic_intensity`;模糊作用于原图缩放前;马赛克=降采样再就近放大 | background-enhancement [S2]
2. **主题 UI 重构(三区→两按钮)**:设置对话框主题区改为 [模式按钮 深色▼][主题按钮 Forest Dark▼] 双 popup;模式切换自动选该模式首个主题;自定义主题按基色亮度自动归入 Dark/Light(luminance<128→Dark);菜单含新建/编辑(仅自定义启用)/导入/删除 | theme-ui-redesign [S2][S3]
3. **目录元数据缓存**:新增 SQLite `directory_cache(dir_path PK, item_count, preview_path, mtime, scanned_at)`,mtime 校验失效重扫;`AssetService.list_directory()` 默认不扫摘要、LAN `?summaries=true` 按需;桌面 async 首屏渲染目标 1000 文件 <100ms | performance [S1]
4. **Cython 热点加速白名单**:仅 4 个纯计算模块——`core/cache.py`(LRUCache)、`core/color_utils.py`(hex↔rgb)、`core/format_utils.py`(format_size)、`application/asset_filters.py`(matches_search/is_hidden/sort_key_for_entry);排除 Qt 依赖、`__future__ annotations`、I/O 密集模块 | performance [S2]
5. **分享桌面快速入口**:文件右键"Quick Share"浮出卡片(文件名/数量/大小 + 生成链接 + 复制 + QR + 密码/限次/限时折叠项),入口=右键+工具栏+`Ctrl+Shift+S`;托盘图标绿=分享中 | sharing-ui [S1]
6. **分享管理对话框 4 页**:概览(状态卡/快速分享/活动/隧道)/分享链接(表格+搜索过滤+批量)/用户管理(管理员/邀请码/在线 kick /访客默认权限)/设置(网络/安全/品牌/高级) | sharing-ui [S2]
7. **实时刷新与反馈**:写操作统一发 `data_changed` 信号驱动自动刷新;活动 2s 轮询(原 6s)+ 新条目淡入;状态卡 300ms 边框色动画;复制按钮"Copied ✓"1.5s;建链 loading→结果展开+QR;删除确认→淡出→toast;隧道"Connecting...";API 错误红色 toast 5s;骨架屏 | 06-21 share-system [S1-S3]
8. **Web 视觉升级**(为 React 重写提供基线):Lucide SVG 图标、Inter 字体、基字 16px、统一动画 token(--ease-out/duration 150-300ms)、骨架 shimmer、可见焦点环、hover/press 反馈;精化色板(indigo #818cf8 强调、#1e1e2e 卡片底、slate 文本) | web-ui-visual-upgrade [S1-S4]

## 落地状态(2026-08-27 抽查)

- **背景增强:✅ 部分落地**:`core/bg_effects.py`(模糊/马赛克,4K 源先降采样)存在;settings_dialog 有背景区(一次写 7 个 bg_* 键);**视频背景(QMediaPlayer)未见独立实现**,以图片背景+效果为主。
- **主题 UI:✅ 落地并演进**:settings_dialog 现为 6 页设置,主题区由后续批次继续演进;`Assets/Themes` 24 主题、暗/亮分组仍在。
- **性能:✅ 落地**:`directory_cache` 即迁移 v5 表,`core/directory_cache.py`(241 行)+ AssetService 摘要缓存;`/api/files/summaries` 端点存在;4 个 Cython 目标全部编译(.pyd 存在,源码回退保留),加速表见 README。
- **分享 UI/UX:✅ 大体落地**:`widgets/lan_sharing.py` 快速分享入口 + `dialogs/share_link_dialog.py` 浮卡 + `dialogs/sharing_settings_dialog.py`(1374 行外壳:端点/链接/访问/配置 4 页 + 2s 轮询)+ `toast.py` + tray 状态同步 —— 设计全部兑现,后续被 08-21+ 批次深度加工。
- **Web 视觉:✅ 被 07-13 React 重写吸收**:lucide-react 图标、暗色、骨架屏、焦点环、Inter 字族、动画 token 在 `webui/` 现行代码中可观察。

## 仍生效的约束或未决项

- 目录摘要必须走 `directory_cache` + mtime 校验(不得每次全扫);`?summaries` 语义仍生效。
- Cython 白名单 4 模块仍为唯一编译目标(README 声明的加速契约,`setup_cython.py` 维护)。
- 分享 4 页结构与 2s 轮询、toast 反馈语义仍生效于当前 sharing_settings 外壳。