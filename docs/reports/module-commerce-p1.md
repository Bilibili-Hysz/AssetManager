# 模块排 Bug 清单（module-commerce-p1.md · 2026-08-11 P1 第1轮）

> 来源: 只读探索代理审计（ZCode Explore），行号经源码逐一核对，调用点经 grep 交叉验证。
> 范围: share_service.py / shop_service.py / shop_buyer_service.py / order_service.py / quota_service.py / free_download_quota_service.py / seller_auth_service.py / seller_profile_service.py / storefront_analytics_service.py / domain/share.py / lan/routes/shop.py / lan/routes/quota.py 及对应仓库层（share_repository / quota_repository / order_repository / free_download_quota_repository / shop_buyer_repository / shop_repository / storefront_analytics_repository）与 lan/routes/shares.py、downloads.py、commerce_policy.py、lan/principal.py、core/database.py（db_write_lock）、core/schema_defs.py。
> 状态: 审计完成,15 项缺陷（高 3 / 中 6 / 低 6）。基线事实:LAN 全库单连接（lan/server.py:1023-1048 返回 self._db_conn）,db_write_lock 为该连接级 RLock（core/database.py:902-933）,所有仓库写操作 CAS + 连接锁双保险。

## 一、缺陷清单

### 高（3）

**H1 — 分享密码最小长度仅 4 且无暴力破解防护**
- 位置: `AssetsManager/application/share_service.py:138-139`（validate_password 允许 4 字符）;`AssetsManager/lan/routes/shares.py:211-239`（handle_verify_share_password 每请求 PBKDF2 校验、失败 401,无任何限速/锁定）。
- 触发路径: 4 字符纯数字/小写密码空间 ≤ 10⁴~10⁵;PBKDF2-SHA256 100k 迭代约 10-50ms/次,LAN 内（或经仓库内 cloudflared 暴露公网）数分钟~数小时可爆破;成功后取得 1 小时分享令牌,可下载分享内全部文件。
- 修复: 最小长度提到 8 并复用 domain/auth.py 的强度规则;对同一 share_id 失败计数（内存/DB）超阈值延迟或拒绝;verify_password 失败与成功路径耗时对齐。

**H2 — 投递令牌无法撤销 + rotate 每次铸造全新满额配额（旧令牌永不失效）**
- 位置: `AssetsManager/application/order_service.py:558-620`（rotate_delivery → order_repository.rotate_fulfilled_delivery 插入新 token,download_count=0、max_downloads 全新）;`AssetsManager/repositories/order_repository.py:414-462`;`AssetsManager/repositories/quota_repository.py:124-133`（revoke 为死代码,全仓无调用方）;`order_service.py:627-631`（_validate_delivery 检查 revoked_at,但没有任何代码路径设置该列）。
- 触发路径: ① 订单 fulfilled 后投递令牌泄露（URL 分享/日志）→ 无任何 API 可作废,只能等 TTL（默认 7 天）到期;② 卖家可无限次 rotate_delivery,每次铸造一个满 max_downloads（上限 100）的新令牌,旧令牌全部继续有效 → 单订单下载总量无上限,get_quota 的 download_limit（=Σmax_downloads）随之无限膨胀。
- 修复: 新增 seller 接口撤销某 order 全部投递令牌（UPDATE shop_delivery_tokens SET revoked_at=? WHERE order_id=?）;rotate 时以该 order 累计 download_count 为基准继承已消耗配额（max_downloads_new = max_downloads_old - download_count_old）,或先撤旧发新;revoked_at 检查保留。

**H3 — 匿名免费配额身份在反向代理（cloudflared）部署下坍缩为代理 IP,单用户可耗尽全局桶**
- 位置: `AssetsManager/lan/routes/quota.py:57-71`（free_download_quota_identity 未认证回退 ip:{request.remote} —— request.remote 是 socket 对端,即代理 IP;注释明确"不信任 XFF"）。
- 触发路径: 仓库根目录存在 cloudflared-windows-amd64.exe,隧道部署为现实场景;所有公网访客共享同一个 IP 桶（默认 20 次/日）,一个活跃下载者即可让全体访客 429,且被波及者无法自行恢复（身份粒度不可控）。
- 修复: 为匿名身份引入浏览器签发的高熵 cookie token（参照 storefront_analytics.py:41-46 的签名 cookie 模式）作为身份键,IP 仅作兜底;或在配置中显式声明信任的反代链。

### 中（6）

**M1 — 免费配额在文件/ZIP 准备成功前扣减,失败即烧配额**
- 位置: `AssetsManager/lan/routes/downloads.py:103`（单文件: consume_free_download_quota 在 web.FileResponse 构造前）、`:141`（目录: consume 在 build_zip_async 前）。
- 触发路径: 文件在 validate 后被删 → FileResponse 抛错;ZIP 构建失败（build_zip_async 返回 None）→ 配额已扣,用户重试又被扣。与 delivery 流程（shop.py:968-1027 "consume only after preparation"）行为相反。
- 修复: 对齐 delivery 模式,先准备响应（构造 FileResponse / 打完 ZIP）,成功后再 consume;consume 失败时返回 429 并清理临时文件。

**M2 — 分享下载计数在响应发送前扣减,客户端中断也消耗配额**
- 位置: `AssetsManager/lan/routes/shares.py:283`（increment_download 在 web.FileResponse 返回前）;`AssetsManager/repositories/share_repository.py:361-373`。
- 触发路径: max_downloads=3 的分享,弱网客户端反复断流重试,3 次即可把配额烧光,真实完成下载数远小于计数。
- 修复: 接受"发送即计数"语义则应在文档注明;更优做法是计数与响应完成解耦（如按字节流完成后置位）或至少重试窗口内豁免。

**M3 — guest 购物车/心愿单合并遇单个禁用商品即整体失败（含心愿单一并回滚）**
- 位置: `AssetsManager/application/shop_buyer_service.py:279-285`（current_items 构建时 item is None or not enabled → raise NotFoundError）;`:272-302`（整个 merge 在同一 _transaction 内,任一 line 抛错 → 购物车+心愿单全部回滚）。
- 触发路径: guest 加入购物车后卖家禁用该商品 → 用户登录触发合并 → 404,合并完全不生效;必须等商品重新启用才能重试。
- 修复: 禁用/已删商品跳过并标记 line_status='unavailable'（schema 已支持该取值,shop_buyer_repository.py:198-200 可直接复用）,而非整体失败;或把购物车与心愿单合并拆成两个独立事务。

**M4 — 投递令牌明文进入 URL 与 JSON,Referer/日志泄露面**
- 位置: `AssetsManager/lan/routes/shop.py:562-563`、`:599-600`（fulfill/rotate 响应返回 delivery_url: "/api/shop/delivery/{token}"）、`:953-958`（handle_delivery 返回含令牌的 download_url）;`order_service.py:540`（secrets.token_urlsafe(32) 裸令牌）。
- 触发路径: 买家页面从 delivery 页跳转其它站点 → Referer 携带完整令牌 URL;服务器访问日志记录路径。令牌是唯一凭证,泄露即任意下载。
- 修复: 交付响应改走 receipt cookie 流程（已有 handle_order_delivery）,或令牌经 Authorization/自定义头传递;delivery_url 至少改为 /api/shop/delivery/ 加独立短 id 映射。

**M5 — 结账金额双重读取的 TOCTOU（潜伏）**
- 位置: `AssetsManager/application/shop_buyer_service.py:466-475`（第一次读 item 价格并校验）vs `AssetsManager/application/order_service.py:213-214,239-243`（_create_order 内部第二次 shop_repo.get_item,以第二次价格计算 amount_cents）。两次读取在同一个 _transaction 内。
- 触发路径: 当前单连接 + 写锁下不可交错,故仅为潜伏缺陷;若未来引入多连接/多进程（如 sqlite WAL 多连接）,卖家在两次读取之间改价且 accept_price_changes=True 时,买家订单金额可与校验时不一致。
- 修复: 把 fresh 循环中已读取的 item 传给 _create_order（amount_cents 显式传入已存在,只需去掉第二次 get_item 的隐式定价路径）,或在校验后于同一事务内加行锁重读。

**M6 — 结账幂等键非规范化（大小写敏感）+ request_key 明文入库**
- 位置: `AssetsManager/application/shop_buyer_service.py:416-418`（request_key.strip() 后原样使用）;`AssetsManager/repositories/shop_buyer_repository.py:347-358`（checkout_record 明文存 request_key）。
- 触发路径: 客户端重试时大小写/首尾空白变化 → find_checkout 失配 → 同一次结账生成两批订单（同一购物车内容重复下单）;shop_cart_checkouts.request_key 明文虽非机密,但无必要落库。
- 修复: 幂等键规范化（casefold + 压缩空白）后使用,且与 request_fingerprint 相同只存哈希（sha256(request_key)）——唯一约束 UNIQUE(cart_id, checkout_generation, request_key) 自动继续生效。

### 低（6）

**L1 — price_cents 无上限,超大值乘 999 可溢出 SQLite 64 位 INTEGER**
- `AssetsManager/application/shop_service.py:161-168`（int(payload.get("price_cents", 0)) 只校验 >=0）;触发: price_cents > 9.2e18/999 时绑定报 OverflowError → 路由兜底 500。修复: 增加上限（如 ≤ 10^12）。

**L2 — 分享下载端点错误码区分泄露分享存在性/限额状态**
- `AssetsManager/lan/routes/shares.py:258-268`: 无密码分享 401/403/410 与 404 可区分"分享存在但需密码/超限/过期"。修复: 统一折叠为 404（参照 get_public_item 的折叠策略）。

**L3 — 分享校验逻辑双实现,ShareService.validate_access 未被路由使用**
- `AssetsManager/application/share_service.py:330-353`（validate_access 含 is_path_allowed/限额检查）与 `shares.py:242-295` 路由内联实现（_resolve_share_target + 手工检查）并存,未来易漂移。修复: 路由改为调用 validate_access 或删除其一。

**L4 — GET 类端点产生写副作用**
- `AssetsManager/repositories/shop_buyer_repository.py:47-58`（cart.get → _ensure_cart 建行）、`:421-453`（wishlist list → _owner 建 owner 行）;`lan/routes/shop.py:757` GET cart 无 cookie 时下发新 cookie。修复: GET 走 existing 只读路径。

**L5 — expires_in（fulfill/rotate）无上限**
- `AssetsManager/application/order_service.py:538-539,602-606`（_positive_int 未设 maximum）;max_downloads 有 100 上限而 TTL 可传数年。修复: TTL 设上限（如 ≤ 365 天）。

**L6 — 卖家登录异常吞并为 400,DB 故障与凭证错误不可区分**
- `AssetsManager/lan/routes/seller_auth.py:52-55`（except Exception: return 400）。修复: 仅捕获预期异常,其余记日志返回 500。

## 二、检查点结论（无问题项）

- **配额竞态（原子性）**: 通过。三层防护——单连接 + db_write_lock 序列化;仓库层全部条件 UPDATE:免费配额 CAS（free_download_quota_repository.py:151-160）、投递配额 CAS（quota_repository.py:112-121、order_repository.py:748-759/869-882）、分享计数 CAS（share_repository.py:365-371）;schema CHECK（download_count>=0、download_count<=max_downloads）。并发超卖不可达;重置窗口边界由 window_start 分窗 + DELETE 自愈,无负值路径。残余问题仅为身份粒度（H3）与扣减时序（M1/M2）。
- **订单状态机**: 通过。_ALLOWED_TRANSITIONS（order_service.py:30-35）服务层校验 + 仓库 WHERE id=? AND status=? CAS 双保险;非法迁移（fulfilled/revoked 终态）被拒;并发同改一单后者得到 "changed concurrently";confirm_by_receipt 回放安全;结账幂等 = request_key + checkout_generation + fingerprint,schema UNIQUE 兜底;投递请求级幂等 = shop_delivery_attempts UNIQUE 三键 + consumed 回放不重复扣。
- **金额精度**: 通过。全链路整数 cents,乘法为 int*int,无浮点、无折扣、无汇率换算;stats 与 CSV 导出均整数;currency 三字母大写校验 + 结账时行/商品比对。唯一边界为 L1 无上限。
- **越权**: 通过。买家作用域 (owner_type, owner_key) 贯穿 cart/order/wishlist/checkout_group;卖家端 require_seller 门与 admin 约束一致;公开目录/详情只暴露 active+authorized 项并折叠为 404;storefront 分析仅存 sha256 哈希与日聚合计数,无 PII。
- **错误处理/事务**: 通过。结账单事务原子（失败整体回滚）;_error_response 对 5xx 隐藏异常文本;quota/analytics 失败不阻塞下载与页面。
- **分享路径安全**: 通过。创建时 resolve()+is_relative_to(root),下载时 _resolve_share_target 同样防穿越且 resolve 消除 symlink 逃逸;is_path_allowed 前缀边界正确（拒绝 a/bc 类误匹配）;increment_download 的 WHERE 重查 active/expiry/limit,删除分享即时阻断下载与令牌。

## 三、统计

- 高 3 / 中 6 / 低 6,共 15 项。
- Top 风险: ① 配额竞态——无超卖,残余为身份粒度（H3）与扣减时序（M1/M2）;② 订单状态机——流转安全,缺口在投递令牌生命周期（H2）;③ 金额精度——干净,唯一边界 price_cents 无上限（L1）;④ 分享安全——最大风险是弱密码可爆破（H1）,路径/令牌边界本身正确。

## 四、修复分组（按文件集互不相交）

- 组 A 分享安全: application/share_service.py + lan/routes/shares.py + domain/share.py → H1、M2、L2、L3
- 组 B1 投递令牌/配额: application/order_service.py + repositories/order_repository.py + repositories/quota_repository.py + lan/routes/shop.py → H2、M4、L5
- 组 B2 免费配额: application/free_download_quota_service.py + repositories/free_download_quota_repository.py + lan/routes/quota.py + lan/routes/downloads.py → H3、M1
- 组 B3 购物车/结账: application/shop_buyer_service.py + repositories/shop_buyer_repository.py → M3、M5、M6、L4
- 组 B4 商品/卖家: application/shop_service.py + lan/routes/seller_auth.py → L1、L6
- 组间零重叠;H2 涉及 B1 内部 order+quota 两仓库,建议同批修改并补并发/撤销测试。
