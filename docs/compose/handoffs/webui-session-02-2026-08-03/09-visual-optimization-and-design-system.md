# 09 — WebUI 视觉优化与设计系统路线

## 1. 来源与适用范围

本路线提炼自以下 DeepSeek Docs：

- `DeepSeek Docs/未来方向/05-桌面端UI视觉改进规划.md`
- `DeepSeek Docs/未来方向/06-现代化界面技术路线评估.md`
- `DeepSeek Docs/未来方向/07-桌面端性能优化计划.md`
- `DeepSeek Docs/架构与设计评价/03-UI与UX设计评价.md`
- `DeepSeek Docs/未来方向/03-橱窗化双端UI设计.md`
- `DeepSeek Docs/未来方向/04-DeviantArt式橱窗前端UI形态设计.md`

可迁移的是设计原则和验收方法；不能直接迁移的是 QSS、`QPropertyAnimation`、`QGraphicsDropShadowEffect`、QML 和 Qt 自绘 API。WebUI 继续使用 React/Vite、Tailwind/CSS variables 和 `lucide-react`，不引入第二套平行视觉系统。

## 2. 视觉总原则

1. 图片优先：缩略图、画廊和项目卡片承担主要识别任务，装饰不能抢占内容。
2. 操作界面保持信息密度：Browse、Detail、Admin 不改造成营销首页；Gate/未来 Storefront 才允许更强的展示性。
3. 同一 SPA、不同视觉域：卖家工作台复用现有 AppLayout；未来 Storefront 可使用单独布局，但共享 API、hooks、stores 和组件基础。
4. 所有视觉变化必须兼容 loading、empty、error、unauthorized、recovery、focus-visible 和 reduced motion。
5. 先建立 token 和组件语义，再做局部特效；禁止通过散落的 Tailwind 魔法值产生第三套风格。

## 3. 当前 WebUI 基线

- [`webui/src/index.css`](../../../../webui/src/index.css) 已有 dark/light CSS variables，并对 Tailwind slate utilities 做了 light 映射。
- [`webui/DESIGN.md`](../../../../webui/DESIGN.md) 已为 Gate 首页定义真实 thumbnail wall、单一 CTA、375px、focus 和 reduced-motion 约束。
- [`webui/src/components/files/ProjectGrid.tsx`](../../../../webui/src/components/files/ProjectGrid.tsx) 当前使用 `repeat(auto-fill,minmax(168px,1fr))` 和左侧 padding。
- [`ProjectCard.tsx`](../../../../webui/src/components/files/ProjectCard.tsx) 已有正方形 thumbnail、状态 badge、选中状态、focus ring、hover transition 和键盘行为。
- `lucide-react` 已是现有图标依赖；不要重新引入 emoji 或第二个图标运行时。

## 4. 建议的 WebUI token 契约

先在 CSS variables 中统一语义，组件只消费语义 token；具体色值可以随着主题 JSON 单一来源工作另行调整。

| 类别 | 建议语义 |
|---|---|
| 色彩 | `bg`、`surface`、`elevated`、`border`、`text`、`muted`、`accent`、`success`、`warning`、`danger` |
| 间距 | `xs=4`、`sm=8`、`md=12`、`lg=16`、`xl=24`、`2xl=32` |
| 圆角 | 控件 6、卡片 8、浮层 12、Gate/大型面板 16；不要同时出现大量近似值 |
| 字阶 | caption 11/12、body 13/14、label 14、title 16/20、heading 24；正文和 badge 禁止过小到不可读 |
| 阴影 | 只用于浮层、对话框和必要的 hover 层次；滚动内容不要逐卡套重阴影 |
| 动效 | 120–150ms hover/opacity，180–220ms panel/dialog；仅在必要时使用 transform |

原桌面规划中的“图标、按钮变体、间距、字阶、深度、空状态、对比度”应在 WebUI 形成对应语义：`primary`、`secondary`、`ghost`、`danger`，而不是每个页面自行组合颜色。

## 5. 卡片式文件管理器视觉规范

### Grid 阵列

目标是“左对齐、固定阅读节奏、卡片宽度稳定”，不是居中画廊：

- 网格容器使用 `justify-content: start`，禁止为剩余卡片启用 `justify-content: center`。
- 卡片轨道建议从 `176–184px` 起步；桌面宽屏可以限制到约 `220px`，移动端降到一列或两列。
- 缩略图统一 `aspect-ratio: 1 / 1`、`object-fit: cover`；不要让不同源图尺寸改变卡片高度。
- 卡片正文固定名称一行截断，辅助信息一行；长标签不能把同一行卡片撑高。
- 选中态使用 border/overlay/checkmark，不改变布局尺寸；拖动、hover 和选中不能造成 reflow。
- 空余空间留在行尾比把卡片集中到中间更符合文件管理器心智。

### 缩放和 hover 动画

- 默认只动画 `opacity`、`transform`、border/color；不动画 width、height、grid track、padding、font-size。
- hover 提升控制在 `scale(1.01)` 左右，transform origin 为卡片中心；不要用大幅放大遮挡相邻文件。
- 选中、hover、focus-visible 三种状态必须可以同时识别；focus 不能只依赖 hover。
- 首次进入可以使用轻量错峰 opacity，但不为数百个卡片各自创建无限动画。
- 图片加载使用固定比例容器和 Skeleton，避免图片到达后卡片跳动。
- `prefers-reduced-motion: reduce` 时关闭错峰、缩放、涟漪和连续 shimmer，只保留即时状态变化。

### 详情与展示域

- DetailPage 的图片区域优先，桌面可采用约 65/35 的图片/信息分配，移动端信息栏折叠到图片之后。
- Storefront/S1 是未来独立视觉域，不应为了现在的 Browse 改成商品页，也不应引入价格、购买、社交功能。
- ProjectCard、LayeredPreview、ImageViewer、TagChip 和 Skeleton 应共享图片比例、状态和加载语义。

## 6. 状态、反馈与无障碍

- 每个页面都有可见 loading、empty、error、retry/refresh 状态；失败不能只写 console。
- Toast 用于非阻塞成功/失败，Modal 仅用于需要确认或输入的场景；危险操作使用明确的 danger 语义。
- 所有可操作元素有 `focus-visible`；触控目标原则上至少 44px；卡片键盘行为必须与鼠标行为等价。
- 正文对比度目标 WCAG AA 4.5:1；浅色主题不能只反转背景而留下低对比度 slate 文本。
- 图标要有 aria-label 或隐藏文字；emoji 不作为核心操作图标。
- 对真实 375px、768px、1024px、1440px viewport 做状态截图/浏览器验收，而不是只看 desktop jsdom。

## 7. 性能约束

DeepSeek 性能计划的可迁移结论是“先测量、优化策略，不重写技术栈”：

- 网格滚动优先控制渲染数量、缩略图并发、缓存命中和无意义 re-render。
- 虚拟滚动只有在真实数据集证明全量 DOM 成为瓶颈后再引入；先定义 item 数量、缩略图大小和滚动场景。
- hover/zoom 期间避免整页 state 更新；局部状态和 CSS transform 优先。
- 真实图片 benchmark 需要固定 manifest、确定性采样、cold/warm 定义、重复次数和 P50/P95；合成目录的结果不能直接成为发布门。
- 不为了视觉效果引入 QML、QWebEngine、全量 canvas 重写或大型动画库。

## 8. 视觉验收门

一个视觉切片只有同时满足以下条件才算完成：

1. 组件行为测试覆盖新状态和键盘路径；
2. dark/light、空态、错误态、缩略图失败态有证据；
3. 375px 和桌面宽度布局无溢出、无不可达控件；
4. reduced-motion 下无强制动画；
5. 真实浏览器截图或明确记录环境阻塞；
6. WebSocket、权限、下载和 stale response 行为没有被视觉改动破坏；
7. `npm test`、typecheck、build 和 `git diff --check` 通过。

## 9. 当前不做

- 不把整个 SPA 改成 Storefront；
- 不引入社交、评论、关注、徽章和推荐；
- 不为追求玻璃拟态重写渲染技术；
- 不将 WebSocket 改成组件私有连接；
- 不把 Gate 的展示性视觉直接复制到操作密集的 Browse/Admin 页面。
