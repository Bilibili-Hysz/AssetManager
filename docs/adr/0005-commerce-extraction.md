# ADR 0005: Commerce Extraction (Removal of Storefront/Seller Runtime)

> 维护状态:**LIVING** · updated: 2026-08-30
> 记录商城（Storefront / Seller / Legacy）运行时代码被移出核心包这一决策的理由、
> **被移除的确切清单**，以及**如何完整恢复**。

## Status

Accepted (2026-08-30, product strategy session).

商城运行时代码从核心包移除。**设计文档、数据库迁移、schema 表定义全部保留。**
本 ADR 是恢复商城时的唯一权威索引。

## Context

### 为什么移除

商城在代码库中占比巨大，但从未真正启用：

| 事实 | 证据 |
|---|---|
| **默认关闭** | `AssetsManager/lan/routes/system.py:115-116` `lan_commerce_enabled` 默认 `False`；`webui/src/App.tsx:49` 要求 `flags.commerce && flags[feature]` |
| **全站无入口** | `webui/src/components/layout/AppHeader.tsx` grep `storefront\|seller\|commerce` **零命中**；导航只有 Gallery + Workspace |
| **一次性投放** | 18 个页面全部来自单提交 `43742f6`（2026-08-11，15,444 行）。此后 `StorefrontPage` 仅 2 次提交，对比 `BrowsePage` 26 次 |
| **用户从未启用** | 项目所有者确认（2026-08-30）：商城功能从未使用，相关数据为空 |
| **泄漏进桌面端** | `AssetsManager/application/` 下 9 个商城服务，创作者每天启动都被加载 |
| **维护成本** | 占 dist 15 chunk / 116K（903K 的 **13%**）；`e2e/a11y.spec.ts` 9 条路由中占 3 条（**33%** 预算），且 mock 写 `commerce:true`（非生产默认） |

### 产品定位决策

见 `docs/plans/development-roadmap-2026-08-30.md`：

> 面向创作者/收藏者的**本地优先 + 局域网自托管**数字资产库。
> 桌面端负责生产整理，局域网 Web 负责分享与交付。**它不是商城。**

同类竞品 Serpent（`D:\~Vibe-Coding\Projects\_REF_Serpent`）零电商，1.5 个月 257 star——
资源全部投入核心能力，是这一定位的外部佐证。

## Decision

**移除运行时代码，保留设计文档与数据迁移链。**

### 删除清单（恢复时的权威索引）

#### 1. Web 页面与测试（32 个文件，`webui/src/pages/`）

```
Legacy*     LegacyStorefrontGalleryPage.tsx / .test.tsx
            LegacyStorefrontItemPage.tsx / .test.tsx

Seller*     SellerDashboardPage.tsx / .test.tsx
            SellerLoginPage.tsx / .test.tsx
            SellerOrdersPage.tsx / .test.tsx
            SellerProductsPage.tsx / .test.tsx
            SellerSettingsPage.tsx / .test.tsx

Storefront* StorefrontBuyerOrdersPage.tsx / .test.tsx
            StorefrontCartPage.tsx              ← 注意：无测试文件
            StorefrontCheckoutGroupPage.tsx / .test.tsx
            StorefrontCheckoutPage.tsx / .test.tsx
            StorefrontDeliveryPage.tsx / .test.tsx
            StorefrontMediaFallback.test.tsx
            StorefrontPage.tsx / .test.tsx
            StorefrontProductPage.tsx / .test.tsx
            StorefrontProductsPage.tsx / .test.tsx
            StorefrontWishlistPage.tsx / .test.tsx
```

#### 2. LAN 路由（`AssetsManager/lan/routes/`）

```
shop/                      目录（__init__.py / _common.py / cart.py /
                                 catalog.py / delivery.py / orders.py）
seller_auth.py
seller_profile.py
storefront_analytics.py
```

> **quota.py 保留**——它是混合文件：
> - `handle_free_quota`（`:293`，`/api/quota`）是**访客免费下载配额**，
>   被核心页面消费（`GalleryCard` / `StatusBar` / `BrowsePage` / `DetailPage` /
>   `AuthContext` → `useQuota` → `system.ts:getQuota`）。**不是商城功能。**
> - 仅删除其中的 `handle_delivery_quota`（`:307`）与别名
>   `handle_quota = handle_delivery_quota`（`:318`），它们只服务
>   `/api/shop/quota`（`api.py:405`，`seller_required` 商城语义）。
> - 注册点 `api.py:111,405` 一并移除。

#### 3. 桌面端服务（`AssetsManager/application/`，8 个）

```
order_service.py
quota_service.py                  ← 仅被 shop/_common.py 引用，确认可删
seller_auth_service.py
seller_profile_service.py
shop_authorization.py
shop_buyer_service.py
shop_service.py
storefront_analytics_service.py
```

配套（`AssetsManager/repositories/`）：`order_repository.py`
（仅被 `order_service.py` 引用；其 ORDER_STATUSES / ALLOWED_TRANSITIONS
设计已由 ADR 0004 完整记录）。

> ⚠️ **两个易错点**：
> 1. `AssetsManager/application/activity_recorder.py` **不是商城**，
>    它是 `activity_log` 的写入器。文件名含 "rec**order**"，
>    会被 `grep order` 误匹配。**不要删除。**
> 2. `AssetsManager/application/free_download_quota_service.py` **不是纯商城**，
>    被 `quota.py:17` 引用、经 `/api/quota` 服务核心页面。**不要删除。**

#### 4. 配套清理

- `webui/src/App.tsx` 中的商城路由注册与 lazy import
- `webui/src/components/storefront/` 组件目录
- `e2e/a11y.spec.ts` 中的商城路由扫描（3 条）
- 上述服务的 import 引用点（约 12 处）

### 保留清单（**绝不可删**）

| 保留项 | 理由 |
|---|---|
| **`AssetsManager/core/db_migrations.py` 中的 13 次商城迁移**<br>v8 / v10 / v11 / v12 / v13 / v16 / v18 / v19 / v20 / v21 / v22 / v23 / v25 | `db_migrations.py:1274` `_validate_history` **锁死迁移链**。删除会导致所有老库无法升级——远比商城本身糟糕 |
| **schema 表定义**（`shop_orders`、`shop_order_receipts`、`free_download_quota` 等） | 同上。表保留但无写入方，属无害孤儿表 |
| **`docs/adr/0004-order-state-machine-placement.md`** | LIVING 状态，记录"订单状态机住在仓储层"的决策理由与重启条件 |
| `docs/architecture.md` 中的商城描述（6/205 行） | 占比极小，保留并加标注 |
| 本 ADR | 恢复索引 |

### 恢复步骤

代码在 git 历史中完整保留，恢复按以下顺序执行：

```bash
# 1. 找到剥离提交的前一个 commit
git log --oneline --diff-filter=D -- "webui/src/pages/StorefrontPage.tsx"
#    记下该 commit 的父 commit 为 <BASE>
#
#    ⚠️ 当前仓库（2026-08-30 因 pack-e5f99c 丢失而重建）：
#    剥离改动落在整合提交 6a49b86（"从工作树重建仓库"），其父提交
#    bf33b7a1 即剥离前基点，树完整可读，可直接用作 <BASE>。
#    历史早期（a0585146 的父对象）存在断链，`git log` 全历史遍历会
#    在末尾报 fatal: cannot simplify——不影响上面的定位输出；
#    若需脚本化，加 `--first-parent` 或直接指定 `git log HEAD~1..HEAD`。

# 2. 恢复文件
git checkout <BASE> -- webui/src/pages/          # 商城页面与测试
git checkout <BASE> -- AssetsManager/lan/routes/shop/ \
                       AssetsManager/lan/routes/quota.py \
                       AssetsManager/lan/routes/seller_auth.py \
                       AssetsManager/lan/routes/seller_profile.py \
                       AssetsManager/lan/routes/storefront_analytics.py
git checkout <BASE> -- AssetsManager/application/order_service.py \
                       AssetsManager/application/quota_service.py \
                       AssetsManager/application/seller_auth_service.py \
                       AssetsManager/application/seller_profile_service.py \
                       AssetsManager/application/shop_authorization.py \
                       AssetsManager/application/shop_buyer_service.py \
                       AssetsManager/application/shop_service.py \
                       AssetsManager/application/storefront_analytics_service.py \
                       AssetsManager/application/free_download_quota_service.py

# 3. 恢复路由注册与引用（需人工对照剥离提交的 diff 反向应用）
git show <剥离 commit> -- webui/src/App.tsx | git apply -R

# 4. 恢复迁移与 schema（若期间未被清理，本就未动）
#    若已被清理，从 <BASE> 恢复 db_migrations.py 的商城步骤

# 5. 验证
#    - lan_commerce_enabled = True 时路由可达
#    - 迁移链完整（对老库跑一次升级）
```

**注意**：恢复后需重新接线 `bootstrap.py` 中的服务注册（约 12 处 import），
这部分在剥离提交中被删除，需反向应用对应 diff。

### 重启条件

出现以下任一情况时，重新评估商城是否回归核心包：

1. 有真实用户启用商城并产生交易数据
2. 产品定位转向"创作 + 交易"一体化
3. 出现需要交易闭环的具体商业需求（而非"可能有用"）

在此之前，商城的合理形态是**独立插件包**，而非核心功能。

## Consequences

### 正面

- dist 体积减少约 13%（116K）
- a11y 门禁预算回收 33%（9 条路由 → 6 条）
- 桌面端启动不再加载 9 个商城服务
- 商城运行时代码（页面 / 路由 / 服务 / 事件）已从核心包清除；`grep` 仅命中
  被刻意保留的迁移链（`db_migrations.py`）、schema 定义（`schema_defs.py`）
  与仓储基类命名（`repositories/_common.py` 的 `_CommerceRepository`）
- 商城专属技术债一笔勾销（`StorefrontCartPage` 0 测试、46 处 inline style、硬编码圆角）

### 负面 / 风险

- 迁移链中保留了 13 次商城迁移与对应表，形成**无害孤儿表**（无写入方）
- 若将来恢复，需按上述步骤反向接线（约 12 处 import + 路由注册）
- `legacy` 分享链接（`/store/gallery/:tag`、`/store/*`）指向的页面被移除，
  需确认是否要保留重定向（见 `webui/src/App.tsx` 的 Legacy 路由处理）

## 相关文档

- `docs/plans/development-roadmap-2026-08-30.md` —— 战略定位与路线图
- `docs/reports/serpent-reference-study-2026-08-30.md` —— 竞品零电商的外部佐证
- `docs/adr/0004-order-state-machine-placement.md` —— 订单状态机决策（保留）
