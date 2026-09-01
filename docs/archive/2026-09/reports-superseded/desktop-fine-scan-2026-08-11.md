# 桌面端深度精细扫描清单（2026-08-11）

> 6 组并行探索（组1 file_list 辅助 + 组2 panels + 组3 dialogs + 组4 widgets + 组5 window/app + 组6 controllers/core），主代理交叉复核组1。
> 共 **100 项**：高 3 / 中 35 / 低 62。已排除 P2 轮已修项。
> 验证基线：3019 passed, 7 skipped（本轮扫描前）。
> **修复状态（2026-08-11 同日完成）**：9 组全部落地（A/B/C/D/E1/E2/F/G/H+I）；净增 72 个新测试（8 个 test_low_batch_*.py 文件）；command_palette 组排序 bug 于回归中发现并修复；全量 **3091 passed, 7 skipped, 0 failed**。
> **明确不在本批**（需跨面板接线，见文档尾）：P7（tag_tree directory_selected 无消费者）、P8（标签过滤无效果）。

## 修复分组（文件集互不相交，均已落地）

| 组 | 文件 | 项 |
|---|---|---|
| A | `_event_bridge.py`、`info.py` | H1（QueuedConnection）、H2（urls_discovered 主线程）、P13-P18 |
| B | `_loader.py`、`_thumbnail_delivery.py`、`_toast.py` | H3（wait_for_runtime 5s 超时）、L1-L4、L8、L16-L22 |
| C | `_detail_model.py`、`_grid_layout.py`、`_batch_rename.py`、`_batch_rename_dialog.py` | L5-L7、L9-L15 |
| D | `tag_tree.py`、`sidebar.py`、`image_viewer.py`、`base.py` | P1-P6、P9-P12（P7/P8 跨面板除外） |
| E1 | `hsv_wheel.py`、`file_picker.py`、`pager_overlay.py`、`stylekit.py`、`command_palette.py` | W1-W3、W6-W9（含回归中发现的组排序修复） |
| E2 | `tag_chip.py`、`theme_gallery.py`、`title_bar.py`、`tray.py`、`toast.py`、`lan_sharing.py` | W10-W17（F4 注释化） |
| F | `window.py`、`app.py`、`workspace_bar.py`、`window_lifecycle_coordinator.py`、`tab_container.py` | X1-X8 |
| G | dialogs 6 文件 | D1-D16（调试打印已清理） |
| H+I | core 9 文件 + `sidebar_favorites.py` + controllers 2 文件 | C1-C17 |

**保留决策**（测试依赖/设计权衡）：`_animate_in`（test_tab_container 依赖）、`_on_domain_tags_changed`（test_tag_event_session_routing 依赖）、`_detail_model` resolve（与 TagStore key 规范一致）、lan_sharing F4（重启必须重跑 preflight）、themes.py 两处 stderr print（预存）。

## 高危（3）

| # | 文件:行号 | 问题 |
|---|---|---|
| H1 | `_event_bridge.py:18` | DomainEventSubscription 用默认 DirectConnection：域事件在任意线程 publish → 槽在发布线程执行，与 RuntimeEventSubscription 的显式 QueuedConnection 矛盾，"UI-safe delivery" 注释不成立 |
| H2 | `info.py:214-222` | _FileInfoTask.run（工作线程）内 controller.add_url → metadata_service.add_url 同步 publish AssetUrlsChanged → 直连桥（H1）→ _on_domain_urls_changed 在工作线程做 GUI 操作（建/删 QPushButton、setStyleSheet、deleteLater）→ 跨线程 GUI 随机崩溃 |
| H3 | `_loader.py:292-310` | wait_for_runtime 无超时无限等待；被 prepare_library_switch（_base.py:1277）与 shutdown（_base.py:1322）在主线程调用 → 任务线程卡死（网络盘/SMB 挂起）时 UI 永久阻塞 |

## 组1 file_list 辅助（中 8 / 低 12）

| # | 严重度 | 位置 | 问题 |
|---|---|---|---|
| L1 | 中 | `_loader.py:76-87` | _suppress_libpng_warnings 用 os.dup2 重定向进程级 fd2，其它线程日志/Qt 警告被静默丢入 /dev/null |
| L2 | 中 | `_loader.py:450-462` | set_size 在锁外写 _size（数据竞态），清缓存不 bump generation → 在飞 worker 旧尺寸结果写回新缓存 |
| L3 | 中 | `_loader.py:899-924` | clear_thumb_cache 主线程持锁 os.listdir+逐删+DB 清除；Windows worker 正在写的文件 PermissionError 被吞，残留 .tmp/.webp |
| L4 | 中 | `_loader.py:926-977` | regenerate_all 的 on_complete 仅 _is_active_runtime 为真时回调 → 切换库时 settings_dialog 进度条永不见、按钮永禁用 |
| L5 | 中 | `_detail_model.py:71-79` | _rebuild_tags_cache 只捕 AttributeError；Path.resolve()/store 抛 OSError/ValueError 时处于 beginResetModel 与 endResetModel 之间 → reset 永不结束、视图损坏 |
| L6 | 中 | `_detail_model.py:161-169` | sort() 未调用 changePersistentIndexList → 排序后选中/高亮跳到另一文件 |
| L7 | 中 | `_toast.py:50-57` | 淡出 finished 只 close 不删除（无 WA_DeleteOnClose/deleteLater）→ 带 parent 的 toast 累积泄漏窗口句柄 |
| L8 | 中 | `_thumbnail_delivery.py:36` | 主线程 QPixmap.fromImage —— quality=original/high 时全尺寸转换掉帧，与 _loader 注释"worker 转换"矛盾 |
| L9 | 低 | `_batch_rename.py:45` | 非 Windows（windows_rules=False）pattern 含 `/` → with_name ValueError 未捕获崩溃；occupied resolve 未捕 OSError |
| L10 | 低 | `_batch_rename_dialog.py:36` | occupied 收集 GUI 线程全量 iterdir+resolve（大目录卡顿） |
| L11 | 低 | `_detail_model.py:74` | 每文件主线程 Path.resolve()（1 万文件详情刷新明显变慢） |
| L12 | 低 | `_detail_model.py:86-87` | fallback except Exception: pass 静默吞标签查询失败 |
| L13 | 低 | `_detail_model.py:152-153` | setData 异步 rename 未成功即返回 True，失败无回滚无反馈 |
| L14 | 低 | `_detail_model.py:179-192` | 降序排序时 not is_dir 被反转 → 目录沉底（惯例目录恒置顶） |
| L15 | 低 | `_grid_layout.py:22-78` | item_hint 传 QSize(0,0) 时除零崩溃（防御缺失） |
| L16 | 低 | `_loader.py:502-515` | request 缓存命中路径主线程逐个 getmtime stat（滚动卡顿） |
| L17 | 低 | `_loader.py:843-857` | _store_baked_image epoch 复检与 os.replace 间窗口，旧代 bake 覆盖新 .webp（自愈） |
| L18 | 低 | `_loader.py:496-497` | request 无条件 _stopped=False，stop 后残留事件重启池 |
| L19 | 低 | `_loader.py:940-950` | regenerate_all os.walk 不剪枝 dirs + 全量图片收集内存 |
| L20 | 低 | `_loader.py:818-820` | 每次磁盘缓存命中 touch_cache_metadata（DB 写放大） |
| L21 | 低 | `_loader.py:25` | BAKE_SIZE 死常量无引用 |
| L22 | 低 | `_loader.py:357-388` | _drain_deferred_loads 内 _start_task 异常逃逸，deferred 任务被静默丢弃 |
| L23 | 低 | `_common.py:76` | badge_color_for_extension ext.lower() 对 None 崩溃（调用方保证非 None） |

## 组2 panels（高 2 / 中 9 / 低 10）

| # | 严重度 | 位置 | 问题 |
|---|---|---|---|
| P1 | 中 | `image_viewer.py:118-128` | 主线程同步整图解码（4000px 位图数百毫秒） |
| P2 | 中 | `image_viewer.py:193-209` | 每次翻页重 os.scandir 整个目录+排序重建列表 |
| P3 | 低 | `image_viewer.py:54-58` | 滚轮缩放无上下限，~600 次后 m11 溢出 inf/NaN |
| P4 | 低 | `image_viewer.py:48-52` | 无 GL 上下文不回退；QOpenGLWidget 不透明与 WA_TranslucentBackground 冲突 |
| P5 | 低 | `image_viewer.py:131-132` | except Exception 静默吞，损坏图无提示 |
| P6 | 低 | `base.py:41-48` | _animate_in 对子控件做 windowOpacity（Windows 仅顶层窗口有效，空转 200ms） |
| P7 | 中 | `tag_tree.py:202-203` | 文件行点击 emit directory_selected 全应用无消费者 → 点击无导航效果 |
| P8 | 中 | `tag_tree.py:164-186` | _active_tag_filter 设置后树不过滤、get_tag_filter() 无消费方 → 标签过滤无效果 |
| P9 | 中 | `tag_tree.py:234-252` | rename/delete/remove 后不 _populate()（无 runtime 绑定路径树保持陈旧）；_on_domain_tags_changed 死代码 |
| P10 | 低 | `tag_tree.py:33,302,331` | _current_path 只写不读；Path.resolve() 未捕异常 |
| P11 | 中 | `sidebar.py:92-121` | _PreloadTask setAutoDelete(False) 且任务运行中被置 None → 每次搜索泄漏任务+results（autoDelete=False 池不销毁） |
| P12 | 低 | `sidebar.py:239-251` | _restore_depth_cfg except pass 吞配置异常 |
| P13 | 中 | `info.py:73-75,935-943` | 预览双击 view_fullscreen 双触发（label 双击未 accept → 传播到 eventFilter）→ 双开重叠查看器 |
| P14 | 中 | `info.py:899-913` | _apply_scaled_preview 每次 splitterMoved/resize 全图 SmoothTransformation 缩放（拖分隔条卡顿） |
| P15 | 中 | `info.py:267-283` | _LinkScanTask setAutoDelete(False) 置 None 后泄漏（同 P11 型） |
| P16 | 低 | `info.py:304,1240` | _urls_scanned 只写不读死状态，"避免重复扫描"未实现 |
| P17 | 低 | `info.py:997-1002` | _classify_dir 死代码无调用方 |
| P18 | 低 | `info.py:1036-1070` | 快速切目录多个 _SizeTask 并发空跑，无取消/合并 |

## 组3 dialogs（中 2 / 低 14）

| # | 严重度 | 位置 | 问题 |
|---|---|---|---|
| D1 | 中 | `sidebar_settings_dialog.py:66-116,154` | 深度 spinbox 0-5 静默钳制 6-32/99 配置值，OK 后原值被降级持久化（数据丢失） |
| D2 | 中 | `plugin_manager_dialog.py:40-157` | PluginCard 无 mouseReleaseEvent，卡片主体点击无反应（选中详情只能靠点 toggle） |
| D3 | 低 | `color_picker_dialog.py:154-161` | 无效 HEX 静默忽略，输入框保留非法文本无提示 |
| D4 | 低 | `color_picker_dialog.py:174` | 灰度色 hueF()==-1.0 → int(-360) 钳到 0，调 S/V 变红色调 |
| D5 | 低 | `color_picker_dialog.py:163-187` | _updating 标志非异常安全，中途异常永久冻结对话框 |
| D6 | 低 | `share_link_dialog.py:276-277` | singleShot lambda 对已删除 _copy_btn 调用 → Internal C++ object already deleted |
| D7 | 低 | `share_link_dialog.py:258` | error None 时消息框显示 "…None" |
| D8 | 低 | `share_link_dialog.py:292-298` | 关闭只递增 generation，未用 _on_dialog_closed 钩子；worker 继续跑完 create_share |
| D9 | 低 | `sidebar_settings_dialog.py:21-22` | DEPTH_OPTIONS（含 99）死常量与 spinbox 0-5 不一致 |
| D10 | 低 | `sidebar_settings_dialog.py:90-98` | os.scandir 未用 with 关闭（句柄延迟释放） |
| D11 | 低 | `_share_api.py:52-55` | ShareApiTask 异常完全静默（无 _log） |
| D12 | 低 | `_share_api.py:50` | 200 + 非 JSON body 时 json() 抛异常无法区分服务器错误与解析失败 |
| D13 | 低 | `_share_api.py:108-118` | getattr(type(service),"session") 返回类属性描述符而非实例值 |
| D14 | 低 | `plugin_manager_dialog.py:295` | record.root_dir None 时显示 "None" 字面量 |
| D15 | 低 | `plugin_manager_dialog.py:110-122` | 启用后 PLUGIN_STATE_LOADABLE 圆点灰色与"已启用"语义不符 |
| D16 | 低 | `plugin_manager_dialog.py:502-510` | 筛选隐藏选中卡片后详情仍显示旧插件；无方向键导航 |

## 组4 widgets（中 5 / 低 12）

| # | 严重度 | 位置 | 问题 |
|---|---|---|---|
| W1 | 中 | `hsv_wheel.py:48-53,95` | 色环绘制与点击取值镜像关系：显示 hue≈0.75 处点击选中 0.25（所见非所得） |
| W2 | 中 | `file_picker.py:124` | 每次按键对每个匹配文件主线程同步 os.path.isdir（逐字输入卡顿） |
| W3 | 中 | `pager_overlay.py:234-262` | 搜索逐字 toPlainText 全量复制+re.finditer+全量 setExtraSelections（大文件卡死） |
| W4 | 中 | `lan_sharing.py:297-320` | server.start 失败但服务器实际运行（rollback_failed）时状态栏/按钮/托盘全显示关闭，状态机不一致 |
| W5 | 中 | `lan_sharing.py:327-328` | 只捕 OSError，非法 port/bind（手改配置）ValueError/TypeError 冒泡无反馈 |
| W6 | 低 | `command_palette.py:106-138` | 每次注册全量重建列表 O(N²) |
| W7 | 低 | `pager_overlay.py:124-131` | show_file 主线程同步读整个文件 |
| W8 | 低 | `stylekit.py:252-385` | dialog_css 直接索引 t['panel'] 等，主题缺键 KeyError 崩溃（token() 有 fallback 而这里没有） |
| W9 | 低 | `stylekit.py:144-146` | make_fade_in/pulse 无条件 setGraphicsEffect 覆盖已有效果（阴影） |
| W10 | 低 | `tag_chip.py:66-69` | 每 chip 全量拼同义词（批量创建重复开销） |
| W11 | 低 | `theme_gallery.py:204-228` | 每张卡每次全量 dialog_css setStyleSheet（N 卡 × 全量样式/点击） |
| W12 | 低 | `theme_gallery.py:42-46` | eventFilter 右键 MouseButtonRelease 也触发 clicked（右键切主题） |
| W13 | 低 | `title_bar.py:180-186` | 每次最大化调 refresh_theme 全量重建图标+样式 |
| W14 | 低 | `tray.py:35` | QMenu() 无父，manager 析构不随释放 |
| W15 | 低 | `toast.py:126-131` | _horizontal_chrome 布局激活前 width()==0，chrome 低估 24px |
| W16 | 低 | `lan_sharing.py:198-203` | 停止后 _lan_server 未置空、快照残留 |
| W17 | 低 | `lan_sharing.py:427-430` | 设置变更重启直接 _toggle_sharing 可能重复弹安全确认框 |

## 组5 window/app（中 4 / 低 4）

| # | 严重度 | 位置 | 问题 |
|---|---|---|---|
| X1 | 中 | `window.py:48` | 窗口几何/最大化从不持久化，每次重启 1200×800 |
| X2 | 中 | `window.py:427-429` | 库切换失败异常从信号槽逸出仅打印 traceback，tab 已停在"新库"而实际服务旧会话，无用户反馈 |
| X3 | 中 | `window_lifecycle_coordinator.py:274-280` | cleanup_file_list → _loader.stop() 无超时等待（同 H3 根因），closeEvent 异常隔离处理不了 hang |
| X4 | 中 | `workspace_bar.py:380`（+window.py:577、startup.py:529） | settings.json 类型损坏（workspace_tabs 非字符串）→ Path(x) TypeError 从构造函数冒泡，应用无法启动 |
| X5 | 低 | `window.py:227` | 菜单"退出"在托盘可用时只是 hide 到托盘，与真实退出语义不符 |
| X6 | 低 | `window.py:412`、`app.py:113` | singleShot lambda 捕获已销毁对象（2 秒/1 秒内关闭 → RuntimeError 刷屏） |
| X7 | 低 | `window_lifecycle_coordinator.py:48-88` | 启动恢复失败在构造期弹模态框阻塞 |
| X8 | 低 | `tab_container.py` | 无 shutdown()，dock 关闭时内部 worker 不停止（当前未实例化，潜伏） |

## 组6 controllers+core（中 7 / 低 10）

| # | 严重度 | 位置 | 问题 |
|---|---|---|---|
| C1 | 中 | `themes.py:432-434` | stylesheet() 缓存键只含主题名，ui_scale 变更不失效 → 缩放后 QSS 尺寸停留旧值 |
| C2 | 中 | `themes.py:125-145` | _merge_theme 只校验 token 存在性不校验类型；properties 非 dict / 颜色 "red" → stylesheet() 内崩溃 |
| C3 | 中 | `crash_handler.py:64-85` | _excepthook 只捕 OSError，钩子内再抛（RecursionError 下 format_tb 失败）→ 无限递归崩溃 |
| C4 | 中 | `tool_scheduler.py:85-88` | Windows Popen shell=False 无法启动 .cmd/.bat（VS Code 默认工具必失败静默） |
| C5 | 中 | `directory_cache.py:61-91` | get/get_batch 读路径不持 db_write_lock，与 set 并发同一 check_same_thread=False 连接 → 偶发 OperationalError |
| C6 | 中 | `info_controller.py:291-353` | GUI 线程与 _FileInfoTask worker 并发访问同一 _db_conn（get_fields 读与 upsert_batch 写交错） |
| C7 | 中 | `sidebar_favorites.py:27-33` | 切库时新库 favorites.json 不存在 → 把旧库收藏写入新库（跨库串扰） |
| C8 | 低 | `themes.py:241-249` | reload_themes 不恢复 _current（编辑文件瞬时无效被重置） |
| C9 | 低 | `settings.py:85-108` | instance() 前 set()+save() 会用残缺数据覆盖 settings.json（加载时序） |
| C10 | 低 | `settings.py:88-92` | settings.json 合法 JSON 但形状错误（[]）→ migrate AttributeError 被吞，不 quarantine |
| C11 | 低 | `json_store.py:84-107` | _save 只捕 OSError；json.dumps TypeError、mkdir 失败（try 外）传播；_on_loaded 二次异常不兜底 |
| C12 | 低 | `directory_cache.py:127-141` | directory_cache 表行永不清理（孤儿行无限增长） |
| C13 | 低 | `info_controller.py:447-491` | classify_dir 缓存无 mtime 失效，目录增删后摘要过期 |
| C14 | 低 | `tag_tree_controller.py:35-51` | get_tag_with_files 每 tag 一次 SQL（N+1），GUI 线程执行，数百 tag 卡顿 |
| C15 | 低 | `tag_tree_controller.py:68-70` | rename_tag 不同步 TagLibrary/元数据，旧 canonical 残留累积 |
| C16 | 低 | `icons.py:93,143-164` | _CACHE 无界 dict，dpr 键跨屏拖动沿用旧 dpr 模糊 |
| C17 | 低 | `bg_effects.py:9-47` | apply_blur 在 paintEvent 内 9 次全幅贴图（4K+blur 冻结数秒） |

## 修复分组建议（文件集互不相交）

| 组 | 文件 | 项 |
|---|---|---|
| A | `_event_bridge.py`、`info.py` | H1、H2、P13-P18 |
| B | `_loader.py`、`_thumbnail_delivery.py`、`_toast.py` | H3、L1-L4、L8、L16-L22 |
| C | `_detail_model.py`、`_grid_layout.py`、`_batch_rename.py`、`_batch_rename_dialog.py` | L5-L7、L9-L15 |
| D | `tag_tree.py`、`sidebar.py`、`image_viewer.py`、`base.py` | P1-P12 |
| E | widgets 11 文件 | W1-W17 |
| F | `window.py`、`app.py`、`workspace_bar.py`、`window_lifecycle_coordinator.py`、`tab_container.py` | X1-X8 |
| G | dialogs 6 文件 | D1-D16 |
| H | core 9 文件 + `sidebar_favorites.py` | C1-C17 |
| I | `info_controller.py`、`tag_tree_controller.py` | C6、C13-C15 |

## 未修项（后续轮次）

- **P7**：tag_tree 文件行点击 emit directory_selected 全应用无消费者（需 window/dock_factory 接线 → file_list.navigate_to）。注：2026-08-15 曾以 dock 形式接线，后按用户要求改为独立窗口，接线随新入口重做。
- **P8**：tag_tree 标签过滤无效果（get_tag_filter() 无消费方，需跨面板下发；且 file_list model 尚无按 tag 过滤维度——属独立特性，仍待做）
- **W4 残余**：lan_sharing F4 重启路径重复弹确认（保守注释化，未改逻辑）
- **D8 残余**：share_link_dialog 关闭后 worker 清理（_on_dialog_closed 已断开信号，任务本身仍会跑完——线程池负载场景可接受）

