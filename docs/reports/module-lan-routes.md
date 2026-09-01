# 模块排 Bug 清单（module-lan-routes.md · 2026-08-10 P0 第1轮）
> 状态:**历史底稿(已过期)** · 2026-08-10 P0 轮行号级审计,行号已随代码演化失效;发现项由后续评审批次关闭 · 状态登记:2026-09-02(文档梳理轮补登)


> 来源: 只读探索代理审计，行号经源码核对。修复前需第二子代理复核真实性。


# LAN 模块路由深度缺陷审计清单（2026-08-10，M10b routes）

> 只读审计，未修改任何仓库文件。范围：AssetsManager/lan/routes/ 全部 23 个 .py。
> 复核基线：path_guard.py、lan/security.py、lan/server.py(_auth_middleware)、lan/principal.py、
> 以及 routes 引用的 application 服务（share/thumbnail/order/search/shop/quota）与 repositories。

---

## Bug 1 - /api/thumbnails 原样内联返回 SVG（同源存储型 XSS）
- 位置: AssetsManager/lan/routes/thumbnails.py:47-51（配合 thumbnail_service.py:232-235 与 domain/asset.py:9 的 IMAGE_EXTS 含 .svg）
- 严重度: 高
- 描述: IMAGE_EXTS 包含 ".svg"。resolve() 对任何 .svg 后缀文件返回原始文件作为 source_path；handle_thumbnail 在 not should_blur 且 max_size>=256（默认 512）且未命中缓存时直接 `web.FileResponse(source_path)` 原样输出。FileResponse 按扩展名猜 Content-Type 为 image/svg+xml，未设置 X-Content-Type-Options: nosniff、未加 Content-Disposition: attachment → 浏览器同源内联渲染 SVG，库内任意恶意 SVG（如从外部拷贝/共享而来）在 LAN 源上执行脚本，可读取/请求同源数据（收藏、订单、后台 API）。image.py:20 已显式排除 .svg，本路由未同步。
- 触发/复现: 在库内放置 evil.svg（含 <script>），GET /api/thumbnails/evil.svg（访客 preview 默认开启，且该路径在 security.py 限流豁免清单内）。
- 修复建议: 仿照 image.py 引入 _SAFE_IMAGE_EXTS = IMAGE_EXTS - {".svg"} 过滤；原始文件回退路径加 X-Content-Type-Options: nosniff 与 Content-Disposition: attachment；或统一改走 /api/image 的已验证通道。

## Bug 2 - 缩略图模糊策略被"处理失败回退原图"绕过（隐私泄露）
- 位置: AssetsManager/lan/routes/thumbnails.py:59-61
- 严重度: 高
- 描述: 当 should_blur=True 时（blur_tags 命中隐私标签），process_image 失败（PIL 对损坏/异常/超大图抛 OSError/ValueError 返回 None）后，路由回退 `web.FileResponse(source_path)` 直接下发未打码原图。image.py:158-178 对同类场景明确"绝不回退原图"（返回 500），本路由未遵循同一安全契约，模糊门禁形同虚设。
- 触发/复现: 配置 lan blur_tags 覆盖某文件，请求该文件缩略图；构造 PIL 无法重编码（如损坏、格式特性不兼容）的同名图片。
- 修复建议: should_blur 时处理失败返回 500/404，绝不回退原图（与 image.py 一致）。

## Bug 3 - 分享预览路由公开内联返回 SVG（公开 XSS，无需任何凭据）
- 位置: AssetsManager/lan/routes/shares.py:341-345
- 严重度: 高
- 描述: handle_share_preview 仅校验 `target.suffix.lower() in IMAGE_EXTS`（含 .svg），随后 `web.FileResponse(target)` 原样输出。分享预览为公开端点（server.py _is_public_share_endpoint 放行），无 nosniff、无附件头，SVG 在 /s/{id} 同一 LAN 源内联渲染执行脚本 → 任何拿到分享链接的人可投递 XSS；无密码分享下连口令都不需要。
- 触发/复现: 分享含恶意 SVG 的文件，GET /api/shares/{id}/preview/evil.svg。
- 修复建议: 复用 image.py 的 _SAFE_IMAGE_EXTS 与 _inspect_image 验证；加 X-Content-Type-Options: nosniff 与 Content-Disposition。

## Bug 4 - 目录/批量下载 ZIP 跟随库内符号链接越界读取（任意文件泄露）
- 位置: AssetsManager/lan/routes/_helpers.py:400-413（build_zip_sync，os.walk 仅过滤点目录，未拒绝符号链接），调用点：downloads.py:158（目录下载）、downloads.py:256（批量下载）、shop.py:1001（订单交付 ZIP）
- 严重度: 高
- 描述: PathGuard 只校验顶层目标（validate_path 对顶层做 resolve 约束），但 ZIP 打包遍历子项时未校验内部符号链接：库内某目录中的文件符号链接指向库外（如 C:\Users\...\私密文件），zf.write 跟随链接把目标内容写入 ZIP。批量/目录下载与 shop 交付目录打包均受影响。
- 触发/复现: 库内目录含指向库外文件的 symlink，调用 GET /api/download/{dir} 或 POST /api/download/batch 下载该目录。
- 修复建议: 打包前对每个 os.walk 产出的文件做 resolve 后 is_relative_to(library_root) 校验，符号链接直接跳过或拒绝；同时限制 ZIP 内文件数。

## Bug 5 - /api/thumbnails/batch 无限流的高成本批量缩略图（CPU/内存 DoS）
- 位置: AssetsManager/lan/security.py:126-131（path.startswith("/api/thumbnails/") 整体豁免限流）+ AssetsManager/lan/routes/thumbnails.py:98-160
- 严重度: 中
- 描述: POST /api/thumbnails/batch 每次最多 100 个路径、size 可到 2048，逐个 PIL 处理并 base64（单请求峰值可达数百 MB 内存/长时间 CPU），且该前缀被限流豁免（访客 preview 默认开启、无需认证）。并发轰炸可耗尽 CPU/内存，且该端点无 X-Content-Type 等输出问题之外的资源上限。
- 触发/复现: 未认证访客并发 POST /api/thumbnails/batch（100 个 2048px 路径）。
- 修复建议: 限流豁免仅保留 GET /api/thumbnails/；批量端点限 size<=1024、路径<=50，或加独立令牌桶/信号量。

## Bug 6 - verify_key 与 seller-login 不在严格认证限流内（口令爆破窗口）
- 位置: AssetsManager/lan/security.py:117-120（_AUTH_ENDPOINTS 仅 login/register）；auth.py:75-95（/api/auth/verify_key）；seller_auth.py:39-55（/api/auth/seller-login 与 /api/shop/auth/login）；放行列表 server.py:1480-1493
- 严重度: 中
- 描述: 访问密钥校验与卖家登录同为口令类端点，但只受通用限流（1000 次/分/IP）约束，远高于 AuthRateLimiter 的 10 次/5 分钟。弱访问密钥或卖家口令可在 1000/分 速率下爆破。
- 触发/复现: 对 /api/auth/verify_key 或 /api/auth/seller-login 高频枚举口令。
- 修复建议: 将 /api/auth/verify_key、/api/auth/seller-login（含 /api/shop/auth/login 别名）加入 _AUTH_ENDPOINTS。

## Bug 7 - 登录错误消息可枚举用户名
- 位置: AssetsManager/lan/routes/auth.py:35（原样透传 err）配合 application/auth_service.py:186-191（"User not found" / "Invalid password" / "User is deactivated"）
- 严重度: 低
- 描述: 用户名存在性、停用状态可被探测，便于后续定向爆破。
- 触发/复现: 对 /api/auth/login 分别提交存在的/不存在的用户名。
- 修复建议: 统一返回 "Invalid username or password"。

## Bug 8 - /api/projects 的 limit/offset 无上限
- 位置: AssetsManager/lan/routes/metadata.py:249-255
- 严重度: 低
- 描述: limit=max(int(...),0) 无上限（0=全量），offset 可任意大；分页在 service 全量扫描后切片（project_service.py:264-276），超大 limit/offset 无法缩减扫描成本，大目录 + 高频请求放大 IO/内存压力。
- 触发/复现: GET /api/projects?limit=999999999&offset=999999999。
- 修复建议: 限制 limit 1..500（0 保留语义）、offset<=100000，超出返回 400。

## Bug 9 - 订单 CSV 导出公式注入（买家可控字段入表）
- 位置: AssetsManager/lan/routes/shop.py:933-944（handle_order_export）+ application/order_service.py:884-898（export_csv 未对 = + - @ 前缀单元做防注入处理）
- 严重度: 低
- 描述: buyer_name/buyer_email 由买家提交，导出时原样写入 CSV；以 =、+、-、@ 开头的字段在 Excel/WPS 打开时执行公式（如 =HYPERLINK(...) / DDE），可对卖家本机造成钓鱼/命令执行风险。
- 触发/复现: 下单时 buyer_name="=cmd|'/C calc'!A0" 后卖家导出订单 CSV 并用表格软件打开。
- 修复建议: 导出时对以 = + - @ \t 开头的字段前置单引号。

## Bug 10 - 公共 /api/stats 与 /api/info 泄露服务器运行信息
- 位置: AssetsManager/lan/routes/system.py:92-101（handle_stats 无任何权限检查）、system.py:54-77（handle_info 公开输出 auth_mode、library_root.name、统计）
- 严重度: 低
- 描述: 未认证者可读取连接数、请求数、字节量、运行时长、认证模式与库文件夹名，辅助攻击者判断攻击面（auth_mode 直接告知口令/密钥/用户体系）。
- 触发/复现: 未认证 GET /api/stats、GET /api/info。
- 修复建议: stats 至少要求 browse 能力；info 对未认证请求剔除 auth_mode/library_root.name 细节。

## Bug 11 - 创建分享时 allow_preview 接受任意真值字符串
- 位置: AssetsManager/lan/routes/shares.py:122
- 严重度: 低
- 描述: `allow_preview = body.get("allow_preview", True)` 未做布尔校验，客户端传 "false"（字符串）时按真值处理 → 预览被意外开启（与分享者意图相反）。
- 触发/复现: POST /api/shares {"paths":[...], "allow_preview": "false"}。
- 修复建议: 仅接受 isinstance(value, bool)，非法返回 400。

## Bug 12 - 弃用的 ?token=/?key= 查询参数认证仍全局生效（凭据泄露渠道）
- 位置: AssetsManager/lan/routes/_helpers.py:348-375（get_auth_token 默认 allow_query=True）+ lan/server.py:1633（除 /ws 外全部允许）
- 严重度: 低
- 描述: 令牌可经 URL 传递，会进入服务器日志、浏览器历史与 Referer；仅打日志警告未停用。共享链接/第三方站点可通过 Referer 捕获 LAN 凭据。
- 触发/复现: GET /api/files?token=<lan_token>（响应成功）。
- 修复建议: 默认 allow_query=False，仅对显式配置的兼容场景放行并加开关。

## Bug 13 - 路径路由普遍二次 URL 解码（潜在解析错位/未来绕过）
- 位置: downloads.py:99、thumbnails.py:25、metadata.py:34/63/282、shares.py:248/321、gallery.py:28、tags.py:99/123、image.py:131
- 严重度: 低
- 描述: aiohttp 对 match_info/query 已解码一次，路由再 unquote 一次。当前因全部经 PathGuard.resolve() 归一化 `..` 而无穿越风险，但：1) 文件名含字面 "%2f" 等会被错误还原导致 404/错文件；2) 属潜伏风险，未来任何绕过 PathGuard 的拼接路径会直接成为穿越。
- 触发/复现: 库内文件名为 "100%2Fpercent.jpg" 时 /api/download/100%252Fpercent.jpg 解析错位。
- 修复建议: 移除冗余 unquote，统一以 aiohttp 解码后的值直接入 PathGuard。

## Bug 14 - 分享 Cookie SameSite=Lax：跨站顶层导航可携带凭据触发下载
- 位置: AssetsManager/lan/routes/_helpers.py:332-337（set_share_cookie path=/api/shares/{id}，samesite=Lax）+ shares.py:239-290（handle_share_download 用该 cookie 放行）
- 严重度: 低
- 描述: Lax 模式下用户点击第三方站点链接（顶层导航）会携带 share_token cookie；知晓分享 id 与库内路径的攻击者可使受害者浏览器自动下载分享文件（附件落盘），并消耗分享下载次数。无法读回内容，影响有限。
- 触发/复现: 受害者访问过某分享后，点击恶意站点指向 /api/shares/{id}/download/{path} 的链接。
- 修复建议: 分享下载端点要求自定义头（X-AssetsManager-API-Client）或 SameSite=Strict；或对 GET 下载校验 Origin/Referer。

## Bug 15 - 临时 ZIP 在传输中断时可能残留（%TEMP% 磁盘累积）
- 位置: AssetsManager/lan/routes/downloads.py:30-56（_file_response_with_cleanup 只在 write_eof 的 finally 清理）
- 严重度: 低
- 描述: 客户端在响应体发送前/中断连接、或服务器关闭导致 write_eof 未调用时，mkstemp 生成的 ZIP（目录下载可达 500MB）不会删除，长期累积可填满临时盘。
- 触发/复现: 反复请求大目录下载并中途断连。
- 修复建议: 在 finally 中同时登记 asyncio 取消清理（add_done_callback / try-finally 包住整个响应生命周期），或改用 aiohttp 的临时文件管理。

---

## 检查点结论（无问题项明确标注）
1. 路径/文件访问：PathGuard 顶层约束（resolve+is_relative_to）与分享作用域校验（shares.py:29-53 对解析后路径做包含性检查）均正确；.thumbnails 位于 RuntimeData（库外，path_resolver.py:156-158），无 .thumbnails 泄露；二次解码无穿越（见 Bug 13）；唯一越界为 ZIP 内部符号链接（Bug 4）。
2. 认证/授权：中间件顺序（security→metrics→auth）与 principal 能力映射正确；分享令牌 1h TTL 与 cookie 一致；订单 receipt/delivery 消费为 CAS+序列化（order_repository 序列化操作 + consume_download 条件 UPDATE），未发现越权与竞态重复扣减；免费下载配额为条件 UPDATE（free_download_quota_repository.py:151-160）无竞态。问题：SVG 预览 XSS（Bug 3）、爆破窗口（Bug 6）、枚举（Bug 7）、Lax cookie（Bug 14）。
3. 输入验证：分页/整数转换均有 try/except 兜底；shop 目录 page/page_size/sort 服务端校验（shop_service.py:269-276）；SQL 全参数化（LIKE ? ESCAPE），tag/quicksearch/metadata 搜索无注入。问题：projects 无上限（Bug 8）、allow_preview 类型（Bug 11）。
4. 响应：错误信息总体收敛（shop _error_response 对 500 打码）；Content-Disposition 经 sanitize_filename 防注入；SVG XSS 在 image.py 已排除但 thumbnails/shares 未排除（Bug 1/3）；stats/info 泄露（Bug 10）；CSV 公式注入（Bug 9）。
5. 并发/资源：配额/下载/交付消费原子性良好；zip 线程池 2 worker 有界；问题：thumbnails/batch 无限流（Bug 5）、临时 ZIP 残留（Bug 15）；WebSocket 广播仅发往 realtime 能力且逐连接复审（ws.py:462-473），无广播越权。
6. 状态机：订单/配额/分享下载计数全部为单条条件 UPDATE 或序列化操作，无重复扣减/并发领取问题。无。

