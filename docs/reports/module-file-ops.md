# 模块排 Bug 清单（module-file-ops.md · 2026-08-10 P0 第1轮）

> 来源: 只读探索代理审计，行号经源码核对。修复前需第二子代理复核真实性。


# 文件操作/撤销服务缺陷审计（file_operation_service.py / undo_service.py）

审计日期：2026-08-10（只读探索，未修改仓库）

## 一、文件操作事务性

### 1. [高] 单文件 move 对已存在目标静默覆盖（Windows 同样受影响）
- 位置：file_operation_service.py:386-416（move）、:373-382（rename）
- 描述：move() 直接调用 shutil.move，目标存在时不检查。Windows 上 os.rename 对已存在文件抛 FileExistsError 后，shutil.move 回退到 copy2(src,dst)+unlink(src)：copy2 用 wb 截断覆盖既有目标文件，源文件再被删除。UI 重命名路径 _rename_absolute（_actions.py:302）走的就是这个单文件 move。
- 触发/复现：把文件 A.txt 重命名为已存在的 B.txt → B.txt 内容被 A.txt 覆盖，无任何错误提示。
- 修复建议：move 前检查 os.path.lexists(dst)（跨平台），已存在时抛带明确信息的 OSError/走冲突确认流程；禁止 copy2 覆盖路径。

### 2. [中] 跨盘/跨卷移动失败后目标残留部分拷贝
- 位置：file_operation_service.py:410（move）、:469（move_to_directory）、:440-443/:491-493/:541-543（copy 类）
- 描述：shutil.move 跨设备目录移动 = copytree+rmtree；copytree 中途失败（如子文件被占用）不会清理已拷入目标的部分内容，源目录保持原样 → 目标出现未索引的部分残留；再次重试会继续堆积。单文件 copy2/copytree 中途失败同样在目标留下半写文件。批量路径只把异常字符串计入 errors，残留路径不报告。
- 触发/复现：跨盘移动一个含只读/被占用子文件的目录 → 目标盘出现残缺目录，源目录仍在。
- 修复建议：失败时 best-effort 清理已创建的目标（rmtree/delete），或先复制到目标临时目录再原子 rename。

### 3. [高] delete_permanent 非 OSError 异常 → 已删除文件的撤销备份被整体丢弃（数据丢失）
- 位置：file_operation_service.py:509-528（delete_permanent），配合 _actions.py:371-386
- 描述：循环内 _clear_deleted_projection（DB 投影清理，含 conn.execute、TagRepository 等）可能抛 OperationalError（数据库被锁等），它不是 OSError → 不被 except OSError 捕获 → 整个方法抛出。此时本批次前面已删除的文件未进入 changed、事件未发布，而调用方 _actions._do_perm_delete 的 except Exception 会调用 discard_delete 丢弃该批次全部备份 → 已删除文件无法撤销，永久丢失。
- 触发/复现：批量永久删除时第 2+ 个文件触发 DB 锁/投影清理异常。
- 修复建议：把 _clear_deleted_projection 异常降级为 warning（已有 reconciliation 通道），文件系统删除与 DB 清理解耦；方法内捕获所有异常转成 errors，保证始终返回 FileOperationResult。

### 4. [中] move 文件已移动但投影/元数据失败 → 事件不发布、UI 与实际不一致
- 位置：file_operation_service.py:410-416（move）、:579-589（_migrate_metadata）、:625-634（_refresh_after_move）
- 描述：shutil.move 成功后 _migrate_metadata 或 _refresh_after_move 抛异常（remove_entry/remove_directory 未包 try，可能抛 OperationalError）→ 文件已移动但 FileRenamed/FileSystemChanged 未发布，索引/元数据残留旧路径，异常直接抛给 UI 显示操作失败而实际已成功。
- 触发/复现：移动文件时 DB 忙/锁冲突。
- 修复建议：文件系统成功后，投影/元数据失败一律走 _record_index_refresh_issue warning 通道，不把文件操作判失败；对 _refresh_after_move 中未捕获的 DB 异常补 try。

### 5. [中] move 持有 DB 写锁执行文件 IO，长操作阻塞全库写入
- 位置：file_operation_service.py:403-416
- 描述：db_write_lock 的 with 块覆盖 shutil.move 全程，跨盘拷贝可达分钟级，期间所有 DB 写入被串行阻塞（含其他库会话）。
- 修复建议：仅在边界检查与投影更新两段持锁，文件 IO 移出锁范围（注意注释里说明的 in_transaction 竞态，可用双阶段检查弥补）。

## 二、路径安全

### 6. [中] create_folder 缺少库根校验
- 位置：file_operation_service.py:356-371
- 描述：create_folder 是唯一不做 _assert_under_root 的操作；若 parent 在库根外（面板曾导航到外部路径或错误参数），会在库外创建文件夹并发布 FileCreated/FileSystemChanged。
- 修复建议：对 target/target.parent 补 _assert_under_root。

### 7. [中] delete_permanent/delete_to_trash 允许删除库根本身
- 位置：file_operation_service.py:503-511、:553-563
- 描述：_assert_under_root 用 is_relative_to，路径等于 root 时通过 → shutil.rmtree(root) 可整库删除（API 层可达）。
- 修复建议：校验排除 p.resolve() == root（及 p 是 root 父路径的悬挂情况）。

### 8. [中] 删除操作断言用 resolve 路径、实际操作用未解析路径
- 位置：file_operation_service.py:510、:562（p = Path(path) 未 resolve）
- 描述：_assert_under_root(p, root) 内部 resolve，但 unlink/rmtree、changed.append(p) 用原始路径。调用方传相对路径且 CWD 与库根不一致时：断言按库根解析、操作按 CWD 解析，行为不一致；changed 里的未解析路径与 _actions.py:380 的 resolve 集合比对永远不匹配 → 备份被误 discard。
- 修复建议：统一 p = Path(path).resolve()。

### 9. [低] Windows 保留设备名/结尾点空格/MAX_PATH 无友好处理
- 位置：file_operation_service.py:358-371、:373-382
- 描述：重命名/新建为 CON、NUL、COM1、foo.、超长路径时仅抛原生 WinError（123/206），错误信息不可读。
- 修复建议：操作前做 Windows 名称合法性校验并给出友好错误。

### 10. [低] 符号链接策略偏保守（根内指向根外的链接无法移动/删除）
- 位置：file_operation_service.py:64-66
- 描述：resolve() 跟随链接导致根内链接→根外目标一律 ValueError；行为安全但限制功能，建议文档化。
- 修复建议：文档注明；如需要可改为仅对目标校验、对链接本体放行（需同步审查 rmtree/unlink 语义）。

## 三、撤销栈

### 11. [高] 撤销删除只恢复文件，不恢复标签/元数据/收藏/缩略图记录
- 位置：undo_service.py:397-410（_execute_reverse）+ file_operation_service.py:531-549（restore_backup）、:668-744（_clear_deleted_projection）
- 描述：删除时 _clear_deleted_projection 删除了 file_tags/file_meta/library_favorites/thumbnail_cache 全部投影；restore_backup 仅拷回文件并重建索引，不恢复上述数据 → 撤销删除后文件回来，但标签、笔记、URL、收藏全部丢失（缩略图靠重新生成可恢复）。
- 触发/复现：对打标+收藏文件永久删除 → 撤销 → 文件在、标签收藏空。
- 修复建议：撤销删除时重建 DB 投影（undo entry 携带投影快照，或恢复前记录被删投影）。

### 12. [中] perform_undo/perform_redo 存在 TOCTOU：文件操作已生效但历史栈未移动
- 位置：undo_service.py:346-367、:370-391
- 描述：_execute_reverse/_execute_forward 在锁外执行；成功后重新加锁校验 _undo_stack[-1] != entry 才弹栈。若执行期间另一线程 push 了新条目 → 校验失败返回 False，但文件操作已执行 → 栈与文件系统不一致（实际已撤销却报告失败，重试会再次执行同一操作）。
- 修复建议：执行期间持有栈锁，或执行后无条件弹出已执行条目并记录执行结果。

### 13. [中] 批量移动部分成功时撤销记录整体缺失
- 位置：file_operation_service.py:49-61（FileOperationResult 契约，无 per-source 映射）+ _actions.py:202-205
- 描述：if result.ok 全有或全无：批量 move 只要有一个失败，已成功移动的文件也不记录 record_rename → 用户无法撤销已发生的移动；同时契约未提供 source↔target 映射，调用方无法为部分成功正确记录。
- 修复建议：FileOperationResult 增加 (source, target) 配对列表，调用方按配对逐个记录。

### 14. [中] 撤销重命名时原位置被重新占用：Windows 卡栈 / POSIX 覆盖
- 位置：undo_service.py:397-425（_execute_reverse/_execute_forward 复用 move）
- 描述：用户撤销前在 entry.old 位置新建了同名文件时：Windows 上 os.rename 抛 FileExistsError → undo 失败且条目滞留栈顶，LIFO 阻塞后续全部撤销；POSIX 上静默覆盖新文件（同 #1 覆盖缺陷在 undo 路径放大）。
- 修复建议：undo 移动前检查目标存在性；失败条目提供跳过/驱逐机制（避免栈毒化）。

### 15. [低] 撤销失败条目无驱逐机制，栈被毒化
- 位置：undo_service.py:346-367、:397-425
- 描述：条目执行失败后一直留在栈顶，后续撤销全部被阻塞，且无 UI 途径跳过（如外部程序删除了文件后撤销重命名永远失败）。
- 修复建议：提供 skip/fail-and-drop 策略与提示。

### 16. [低] _make_backup 失败静默，删除对话框承诺可撤销但不兑现；无大小/空间限制
- 位置：undo_service.py:455-465、:252-258；对话框文案 _actions.py:361
- 描述：备份失败返回 None → record_delete 静默不记录；大文件备份无大小/磁盘空间约束，可能占满临时盘。
- 修复建议：备份失败时返回错误让调用方提示；备份前检查磁盘剩余空间。

## 四、事件

### 17. [中] 批量删除中途非 OSError 异常：部分成功事件已发布但 errors 契约丢失
- 位置：file_operation_service.py:509-528（同 #3 事件面）
- 描述：前面文件的 FileDeleted/FileSystemChanged 已发布，随后抛异常 → 调用方只见异常，无法得知部分成功；与 errors/warnings 契约不符（errors 元组永不返回）。
- 修复建议：同 #3（方法内捕获全部异常并入 errors，始终返回 FileOperationResult）。

### 18. [低] 事件发布契约不一致：FileSystemChanged 仅 session 绑定时发布
- 位置：file_operation_service.py:343-354（_publish_file_change）与 :446-447/:474-475 等领域事件对比
- 描述：FileRenamed/FileDeleted/FileCopied 无条件发布，FileSystemChanged 仅 session is not None 时发布；legacy 无 session 调用时两类事件不一致。
- 修复建议：文档化或统一发布条件。

## 五、并发

### 19. [中] 同文件并发操作无互斥；回收站删除与永久删除无串行化
- 位置：file_operation_service.py:503-577、undo_service.py:455-465
- 描述：后台粘贴（move）与删除、回收站删除与永久删除作用于同一文件时无 per-file 锁，仅 DB 写锁串行化投影；prepare_delete 备份拷贝与并发删除存在竞态（拷贝一半文件被删 → 备份损坏/失败）。
- 修复建议：按 path 加细粒度锁或全局文件操作队列；prepare_delete 与删除同锁。

### 20. [低] move 持 DB 写锁执行文件 IO（同 #5，并发影响面）

## 六、边界

### 21. [高] unique_destination 在目标目录只读/磁盘满/名称非法时死循环
- 位置：file_operation_service.py:747-783（unique_destination/_try_reserve）
- 描述：_try_reserve 捕获所有 OSError（含 PermissionError、ENOSPC、WinError 123/206）返回 False；while True 无限递增 → 向只读目录复制/移动/新建/去重时 UI 永久卡死。
- 触发/复现：向只读目录执行 copy/move/duplicate/create_folder。
- 修复建议：仅 FileExistsError 继续尝试，其余 OSError 直接抛出或返回 None；并设置最大尝试次数兜底。

### 22. [低] 错误分类缺失：errors 仅含 str(exc) 原始文本
- 位置：file_operation_service.py:448-449、:476-477、:524-525、:573-574
- 描述：只读/占用/路径非法/跨设备等错误全部混为一段文本，调用方无法区分做针对性提示。
- 修复建议：errors 使用结构化错误（错误码/类型字段），展示层分类提示。

### 23. 空选择：无问题
- 服务层对空 sources/paths 列表正常返回空 FileOperationResult（ok=True），UI 侧 _selected_paths 为空时由 _delete/_paste 等入口过滤；无缺陷。

## 附注（不在两个目标文件内，但与契约直接相关）
- _actions.py:203-205 的批量 move 撤销记录依赖 result.ok 全有或全无（见 #13）。
- _actions.py:371-386 的备份丢弃逻辑放大 #3 的数据丢失风险。

