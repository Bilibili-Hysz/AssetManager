# 预览快照、缓存与模糊策略一致性

## 范围

第六轮优先处理预览检查结果与实际响应不一致的问题。主代理负责共享契约、复核与验收，GPT-5.6-terra 子代理负责原图、缩略图和应用服务缓存。没有修改前端。

## 实现决策

- 原图接口先取得有界的 `read_safe_file` 字节快照，内容验证、模糊处理和响应使用同一份字节。取消按路径验证后重新读取的流程。
- RAW/PSD 在返回 304 前也需要成功解码；处理过程中模糊策略收紧时，使用已捕获的源字节重新解码。图像编码会关闭输入图像，不能复用已关闭的 PIL 对象。
- 缩略图检查实际选择的原图、WebP 缓存或视频帧，读取时校验对应的身份。根目录只接受资源库或配置的缩略图目录。原始字节回退也必须通过光栅图片内容验证，并使用检测得到的 MIME。
- ETag 同时包含实际源文件身份、响应内容类型、响应字节摘要和规范化请求参数。图片验证及摘要计算在后台线程执行。最终未模糊响应及 304 的策略检查安排在这些工作之后。
- 可缓存预览改为 `private, no-cache`，要求每次复用前向服务端重新验证权限和模糊策略。模糊输出与私有分享预览继续 `private, no-store`。公开预览入口也不再允许共享缓存直接复用。
- LAN 调用 `ThumbnailService.resolve(..., allow_legacy_cache=False)`：v2/v3 和视频帧使用捕获的原文件身份生成键，返回缓存前再次安全打开原文件以核验身份和资源库目录边界；不接受无法绑定原文件身份的旧格式缓存。应用服务默认值保持 `True`，保留桌面已有兼容行为。
- 原文件最初不存在返回 404，准入后身份变化返回缩略图既有的 409。缓存命中时继续允许原文件超过解码准入大小，因为此时只读取有界的缓存图片。
- 批量预览逐项处理并释放原始字节，完成全部处理后再核验未模糊条目的策略。新变为敏感的条目从部分成功结果中省略，不为重新处理而保留整批原始字节。
- `serve_verified_image` 直接依据捕获的原图字节与当前策略处理，不再依据另一次缓存解析决定是否缩小原图。小于 256 的尺寸请求仍处理输出；大尺寸未模糊请求直接发送验证过的原图。

## 审查与验证

定向覆盖：检查后路径替换、相同大小及时间戳的内容变化、真实缓存文件变化、旧缓存失效、模糊策略在处理和摘要期间收紧、失败处理不得回退泄露原图、批量早期条目的策略收紧、RAW 解码失败与重复解码、真实标签数据库变更后的条件请求。

主审额外修复了缓存身份检查早于标签查询的间隙、缺失原文件误返回 409、重新模糊处理复用已关闭图像，以及批量保留所有源字节导致的内存放大。收尾审查补充了缓存命中时对原文件的最终目录边界检查，防止仅核验缓存文件而遗漏指向库外的原文件链接。

最终完整门禁：

```powershell
python -m pytest tests/lan tests/integration/test_thumbnail_service.py tests/integration/test_thumbnail_lan_cache_identity.py tests/integration/test_thumbnail_cache_capacity.py tests/integration/test_media_decoder_consumers.py tests/unit/test_thumbnail_governance.py tests/unit/test_thumbnail_key.py tests/core/test_package_contents.py tests/unit/test_architecture_boundaries.py tests/unit/test_build_installer.py -n 2 --basetemp=.pytest-tmp-quality-round6-verified -o cache_dir=.pytest-cache-quality-round6-verified -q
```

结果：**1112 passed, 2 skipped，exit 0，137.17 秒**。两项跳过为 `tests/lan/test_safe_open.py` 与 `tests/lan/test_helpers.py` 中需要 Windows 符号链接创建权限的测试（WinError 1314）。新增真实 junction 测试覆盖常规图片和未知扩展名，均通过。

静态与入口检查：

```powershell
python -m ruff check AssetsManager/lan/routes/_helpers.py AssetsManager/lan/routes/image.py AssetsManager/lan/routes/thumbnails.py AssetsManager/application/thumbnail_service.py tests/lan tests/integration/test_thumbnail_lan_cache_identity.py
python -m pyright AssetsManager/lan/routes/_helpers.py AssetsManager/lan/routes/image.py AssetsManager/lan/routes/thumbnails.py AssetsManager/application/thumbnail_service.py
python run.py --package-smoke
git diff --check
```

以上通过，Pyright 为 0 errors、0 warnings。本轮在上述范围内验收通过，代码保持未提交状态；并行前端修改保留。

## 边界与代价

- 304 节省响应传输，但现在仍需读取和验证选中的字节，处理型预览也可能重新渲染。尚未进行设备级吞吐、RSS 或事件循环延迟压测。
- `no-cache` 要求后续复用重新验证，无法撤回已发送、已显示的内容；旧版本已经发出的长时效缓存也不能由服务端主动失效。策略查询与网络发送不是数据库/文件系统联合事务。
- 原文件身份仍是设备、inode、大小和 mtime。直接响应的字节摘要可以识别同身份的内容变化；持久缩略图的源映射仍依赖元数据指纹，不声称识别原文件全部保留元数据的原地修改。
- 64 MiB 限制的是单次需要整块读取的源字节，不是解码像素或所有并发请求的总内存。批量输出字节的全局预算、解码预算和性能测量仍需后续设计。
- 本轮不实现 Windows 原子打开、跨进程磁盘预算或崩溃后 ZIP 遗留回收，也没有执行安装包实机与前端交互验收。
