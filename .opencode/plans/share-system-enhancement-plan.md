# Share System 增强与简化计划（Qt 桌面端）

> 创建时间：2026-06-08
> 状态：待执行
> 预计总工时：15-20 小时

---

## 一、现状分析

### 当前架构

```
MainWindow (LanSharingMixin)
    ├── _toggle_sharing() → 启动/停止 LanServer
    ├── _open_sharing_settings() → 打开 SharingSettingsDialog
    └── _apply_sharing_settings() → 重启服务器

SharingSettingsDialog (TabbedDialog)
    ├── Tab 1: Share — 状态、URL、QR、隧道
    └── Tab 2: Settings — 7 个可折叠区域

LanServer (lan/server.py)
    ├── aiohttp Web 服务器
    ├── 认证中间件
    ├── 安全中间件
    └── 隧道管理器
```

### 已识别问题（13 项）

| 编号 | 问题 | 严重度 | 影响 |
|------|------|--------|------|
| P1 | `_share_label` 未创建，状态指示器失效 | 高 | 用户无法看到分享状态 |
| P2 | `ShareManager` 未被使用，死代码 | 中 | 架构混乱 |
| P3 | Qt 端无分享链接管理 UI | 高 | 功能缺失 |
| P4 | 设置对话框不反映实时服务器状态 | 中 | 用户体验差 |
| P5 | 应用设置时重启服务器，断开连接 | 中 | 用户体验差 |
| P6 | 密码哈希使用弱算法 | 高 | 安全风险 |
| P7 | 主窗口无分享状态指示器 | 高 | 用户体验差 |
| P8 | 隧道 UI 阻塞主线程 | 中 | 界面冻结 |
| P9 | 分享范围设置未生效 | 高 | 功能无效 |
| P10 | QR 码依赖可选库 | 低 | 用户体验 |
| P11 | 自动启动分享未实现 | 中 | 功能缺失 |
| P12 | Qt 端分享代码无测试 | 中 | 质量风险 |
| P13 | ShareManager/LanServer 双重架构 | 中 | 架构混乱 |

---

## 二、目标

### 增强目标
1. **状态可见** — 主窗口清晰显示分享状态
2. **功能完整** — 分享链接可在 Qt 端创建和管理
3. **实时反馈** — 服务器状态实时更新
4. **设置生效** — 分享范围设置真正生效
5. **安全增强** — 统一密码哈希算法

### 简化目标
1. **一键分享** — 从右键菜单直接分享文件/文件夹
2. **状态栏集成** — 分享状态始终可见
3. **快捷操作** — 常用操作一键完成
4. **智能默认** — 减少配置项

---

## 三、执行计划

### Phase 1: 状态可见性（2-3h）

**目标**: 让用户始终看到分享状态

| 任务 | 文件 | 描述 |
|------|------|------|
| 1.1 | `window.py` | 添加状态栏分享指示器（图标 + 文字） |
| 1.2 | `window.py` | 添加工具栏分享切换按钮 |
| 1.3 | `lan_sharing.py` | 修复 `_update_share_status()` 使用新指示器 |
| 1.4 | `window.py` | 分享状态变化时更新指示器颜色/图标 |

**UI 设计**:
```
状态栏: [🟢 Sharing: http://192.168.1.100:8080] 或 [⚫ Sharing Off]
工具栏: [🌐 Share] 按钮（点击切换）
```

### Phase 2: 分享链接管理（3-4h）

**目标**: 在 Qt 端创建和管理分享链接

| 任务 | 文件 | 描述 |
|------|------|------|
| 2.1 | `core/share_link_dialog.py` | 新建分享链接创建对话框（独立） |
| 2.2 | `core/share_link_manager.py` | 新建分享链接管理对话框（列表、删除） |
| 2.3 | `window.py` | 添加右键菜单 "Share Link..." |
| 2.4 | `lan/api.py` | 确保 API 支持 Qt 端调用 |

**UI 设计**:
```
右键菜单:
  📁 MyProject
  ├── Open
  ├── Open in Explorer
  ├── ─────────────
  ├── 🔗 Create Share Link...  ← 新增
  ├── 📋 Copy Path
  └── ─────────────
  └── Properties

分享链接创建对话框 (ShareLinkDialog):
  ┌─────────────────────────────────┐
  │ Create Share Link               │
  ├─────────────────────────────────┤
  │ Path: MyProject                 │
  │                                 │
  │ Password: [____________] (opt)  │
  │ Expires:  [24 hours ▼]         │
  │ Max Downloads: [____] (opt)     │
  │                                 │
  │ [✓] Allow preview               │
  │                                 │
  │ ─────────────────────────────── │
  │ Link: https://192.168.1.100:... │
  │ [Copy] [Open] [QR Code]        │
  └─────────────────────────────────┘

分享链接管理对话框 (ShareLinkManager):
  ┌─────────────────────────────────┐
  │ Share Links                     │
  ├─────────────────────────────────┤
  │ Path          Expires    Link   │
  │ MyProject     24h        [Copy] │
  │ MyFolder      Never      [Copy] │
  │                                 │
  │ [Delete Selected] [Refresh]     │
  └─────────────────────────────────┘
```

### Phase 3: 实时状态更新（2h）

**目标**: 设置对话框显示实时服务器状态

| 任务 | 文件 | 描述 |
|------|------|------|
| 3.1 | `sharing_settings_dialog.py` | 添加 QTimer 轮询服务器状态 |
| 3.2 | `sharing_settings_dialog.py` | 更新状态卡片显示连接数、请求数、流量 |
| 3.3 | `lan/api.py` | 确保 `/api/stats` 返回完整信息 |

**UI 设计**:
```
状态卡片 (每 2 秒更新):
  🟢 Sharing Active
  http://192.168.1.100:8080
  
  3 clients · 1,234 requests · 45.2 MB
  [Stop Sharing]
```

### Phase 4: 设置热重载（2-3h）

**目标**: 部分设置无需重启服务器即可生效

| 任务 | 文件 | 描述 |
|------|------|------|
| 4.1 | `lan/server.py` | 添加 `reload_settings()` 方法 |
| 4.2 | `lan/api.py` | 实现设置热重载（品牌、模糊标签、排除模式） |
| 4.3 | `sharing_settings_dialog.py` | 区分需要重启和无需重启的设置 |
| 4.4 | `lan_sharing.py` | 修改 `_apply_sharing_settings()` 使用热重载 |

**设置分类**:
```
无需重启:
  - 分享名称 (lan_share_name)
  - 主题颜色 (lan_theme_color)
  - 欢迎消息 (lan_welcome_msg)
  - 页脚文本 (lan_footer_text)
  - 模糊标签 (lan_blur_tags)
  - 排除模式 (lan_exclude_patterns)
  - 显示隐藏文件 (lan_show_hidden)
  - 最大深度 (lan_max_depth)
  - 包含类型 (lan_include_types)

需要重启:
  - 端口 (lan_port)
  - 绑定地址 (lan_bind)
  - 认证模式 (lan_auth_mode)
  - 密码 (lan_password)
  - SSL 证书/密钥 (lan_ssl_cert, lan_ssl_key)
  - 最大连接数 (lan_max_connections)
  - 速率限制 (lan_rate_limit)
  - IP 黑名单 (lan_blocked_ips)
```

### Phase 5: 分享范围生效（2h）

**目标**: 让分享范围设置真正生效

| 任务 | 文件 | 描述 |
|------|------|------|
| 5.1 | `lan/api.py` | `handle_files` 读取并应用分享范围设置 |
| 5.2 | `lan/api.py` | `handle_projects` 读取并应用分享范围设置 |
| 5.3 | `lan/api.py` | `handle_tree` 读取并应用分享范围设置 |
| 5.4 | `lan/server.py` | 在请求上下文中注入设置 |

**实现逻辑**:
```python
async def handle_files(request):
    lan = _get_lan(request)
    settings = lan.current_settings  # 从服务器获取
    
    # 应用文件类型过滤
    if settings.include_types:
        items = [i for i in items if i.category in settings.include_types]
    
    # 应用隐藏文件过滤
    if not settings.show_hidden:
        items = [i for i in items if not i.name.startswith('.')]
    
    # 应用排除模式
    if settings.exclude_patterns:
        items = [i for i in items if not matches_exclude(i.path, settings.exclude_patterns)]
    
    # 应用最大深度
    if settings.max_depth > 0:
        items = [i for i in items if depth(i.path) <= settings.max_depth]
```

### Phase 6: 安全增强（1-2h）

**目标**: 统一密码哈希算法，修复安全问题

| 任务 | 文件 | 描述 |
|------|------|------|
| 6.1 | `sharing_settings_dialog.py` | 使用 `lan/auth.py` 的 `hash_password()` |
| 6.2 | `lan/server.py` | 统一密码验证逻辑 |
| 6.3 | `lan/auth.py` | 添加密码强度验证 |

### Phase 7: 简化操作（2-3h）

**目标**: 减少用户操作步骤

| 任务 | 文件 | 描述 |
|------|------|------|
| 7.1 | `window.py` | 添加 "Quick Share" 右键菜单（一键分享） |
| 7.2 | `window.py` | 分享后自动复制链接到剪贴板 |
| 7.3 | `window.py` | 添加分享历史记录（最近分享的链接） |

**Quick Share 工作流**:
```
右键文件/文件夹 → Quick Share
  → 使用默认设置创建分享链接（无密码、24h过期、无限下载）
  → 自动复制到剪贴板
  → 显示通知: "Link copied to clipboard"
  → 可选: 显示 QR 码弹窗
```

### Phase 8: 自动启动与隧道（1-2h）

**目标**: 实现自动启动和隧道集成

| 任务 | 文件 | 描述 |
|------|------|------|
| 8.1 | `app.py` | 启动时检查 `lan_auto_start` 设置 |
| 8.2 | `window.py` | 自动启动分享（如果启用） |
| 8.3 | `sharing_settings_dialog.py` | 改进隧道 UI，避免阻塞主线程 |

---

## 四、执行顺序

```
Phase 1 (状态可见性) → Phase 2 (分享链接管理) → Phase 3 (实时状态)
    ↓
Phase 4 (热重载) → Phase 5 (分享范围生效) → Phase 6 (安全增强)
    ↓
Phase 7 (简化操作) → Phase 8 (自动启动)
```

**预计总工时: 15-20 小时**

---

## 五、验收标准

| 标准 | 验证方法 |
|------|---------|
| 状态栏始终显示分享状态 | 启动/停止分享，观察状态栏变化 |
| 右键菜单可创建分享链接 | 右键文件 → Create Share Link → 验证链接 |
| 设置对话框实时更新 | 打开对话框，观察连接数变化 |
| 分享范围设置生效 | 设置文件类型过滤，验证 Web 端只显示过滤后的文件 |
| 密码哈希使用 PBKDF2 | 检查数据库中的密码哈希格式 |
| Quick Share 一键完成 | 右键 → Quick Share → 验证链接已复制 |
| 自动启动生效 | 启用自动启动 → 重启应用 → 验证分享已启动 |

---

## 六、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 热重载可能导致状态不一致 | 中 | 添加版本号，强制重启时清除缓存 |
| 分享链接管理增加复杂度 | 低 | 独立对话框，不增加主对话框复杂度 |
| QR 码库依赖 | 低 | 提供下载链接或内置替代方案 |
| 测试覆盖不足 | 中 | 每个 Phase 完成后添加单元测试 |

---

## 七、决策记录

| 决策 | 选项 | 选择 | 理由 |
|------|------|------|------|
| 分享链接管理 UI | A: 独立对话框 / B: 新增 Tab | A | 更清晰，不增加主对话框复杂度 |
| Quick Share 默认设置 | A: 无密码/24h/无限 / B: 无密码/永不过期/无限 / C: 上次设置 | A | 安全性与便利性平衡 |
| ShareManager | A: 删除 / B: 保留为 LanServer 包装器 / C: 独立状态管理器 | B | 保持架构清晰，减少重复 |
