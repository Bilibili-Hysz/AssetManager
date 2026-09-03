# WebUI 样式治理方案（F-3 立项）

> 产出：`docs/reports/re-audit-2026-09-03.md` F-3 的立项方案。方法论对齐桌面端 `desktop-ui-unification-audit-2026-09-03.md`（先分类、后立禁令、棘轮只降不升）。

## 1. 背景与目标

统一复审（re-audit-2026-09-03）发现 webui 侧无对等样式门禁，桌面端已建成 G1/G2/G3 三道静态防线，webui 成为方言回潮的敞口。本方案目标：**为 webui 建立等价的 inline-color 棘轮门禁，并清偿存量真实方言**。

## 2. 现状普查（2026-09-03 实测）

- 全量 hex 字面量（src/**/*.{ts,tsx}）：**133 处**
- token 层现状：`src/index.css` 定义 **35 个 CSS 变量**（`--color-*` / `--space-*` / `--radius-*` / `--shadow-*`）；**21 个 tsx 文件**已消费 `var(--…)`——token 消费习惯已存在，缺的是禁令
- 分布高度集中：

| 文件 | 处数 | 定性 |
|---|---|---|
| `src/components/ui/EmptyState.tsx` | 113 | SVG 插画渐变 `stopColor`（资产，非 chrome） |
| `DominantPaletteStrip.test.tsx` 等 3 个测试 | 21 | 测试断言 fixture |
| 其余 7 个文件 | ~14 | **真实 chrome 方言**（见 §3-C） |

## 3. 分类学（先分类，后立禁令）

**A 类 — 插画资产（豁免）**：EmptyState.tsx 的 113 处均为内联 SVG 渐变的 `stopColor`/`stopOpacity`，属插画作品色彩，与桌面端"内容资产不进 chrome 门禁"同语义。登记入豁免清单。

**B 类 — 数据驱动 / 回退值（登记豁免）**：
- `DominantPaletteStrip.tsx:61`：按提取色亮度二选一的对比文本色——数据驱动件
- `AmbientBackdrop.tsx:9`：`var(--color-accent, #6366f1)` 的 fallback 形态——合规模式
- `LandingPage.tsx:48`：`fallbackAccent` 提取失败回退——数据回退

**C 类 — 真实 chrome 方言（迁移目标，~9 处 / 6 文件）**：

| 位点 | 现值 | 迁移目标 |
|---|---|---|
| `MasonryView.tsx:149` | `#f59e0b`（文件夹琥珀）/ `#64748b`（文件灰） | 新增语义 token `--color-icon-folder` / `--color-icon-file`（或复用既有语义） |
| `MasonryView.tsx:180,182` | `#fbbf24`（收藏星） | 新增 `--color-star` |
| `NotFoundPage.tsx:22`、`ErrorBoundary.tsx:60` | `#4f46e5` + `#ffffff` 按钮 | `var(--color-accent)` + `var(--color-accent-text)` |
| `AmbientBackdrop.tsx:10` | `secondaryAccent='#a78bfa'` | 走变量（如 `--color-accent-2`） |
| `ProjectList.tsx:117` | 选中态 `#ffffff` | `var(--color-accent-text)` |

## 4. 门禁设计（W1）

- **脚本**：`webui/scripts/check-inline-colors.mjs`（node 直跑，无需装依赖）——扫描 `src/**/*.{ts,tsx}` 中 `#hex` 字面量，对照 `webui-style-ledger.json` 的 per-file 额度；**只降不升**；`--update` 显式重算
- **账本**：`webui/webui-style-ledger.json`，含 `_comment` 登记豁免类别（A 插画 / B 数据驱动）与理由；测试文件（`*.test.*`）默认排除
- **CI 接入**：现有 lint workflow 增加 `node webui/scripts/check-inline-colors.mjs` 步骤
- **豁免行内标记**：`/* inline-color: exempt <reason> */` 行级豁免，供 B 类与未来特例使用

## 5. 路线

| 阶段 | 内容 | 规模 |
|---|---|---|
| W0 | 按本方案 §3 落账本初版（现值即额度） | S |
| W1 | 门禁脚本 + CI 接入 | S |
| W2 | C 类 9 处迁移 + 新增 3-4 个语义 token | M |
| W3（可选） | EmptyState 插画渐变改从 props/css 变量取 accent（插画与主题联动），随后把其额度从账本剥离 | M |

## 6. DoD

1. `node webui/scripts/check-inline-colors.mjs` 在 CI 绿灯，人为新增 hex 字面量会红灯
2. C 类 9 处全部走 CSS 变量，grep 复扫 chrome 层零裸 hex
3. 账本豁免类别均有 `_comment` 理由登记
4. 桌面/web 双端方法论对称：均为"先分类 → 棘轮 → 只降不升"
