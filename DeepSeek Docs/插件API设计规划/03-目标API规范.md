# 03 · 目标 API 规范（manifest v2 + 注册表模型）

> 本规范是插件 API 的**唯一权威定义**。实施时以此为准；旧文档（Plugins/Docs/*）同步重写。

## 一、设计总纲

```
插件 = 目录（plugin.json + Python 包）
    │
    │ 加载时：模块级 register(host) 被调用（唯一入口约定）
    │        └→ host.register_class(MyOperator, MyParser, MyPreferences...)   ← 唯一注册机制
    │
    │ 运行时：host.plugin_context() 提供当前状态（库/选区/目录）               ← 唯一上下文
    │
    │ 卸载时：模块级 unregister(host) 被调用 → 注册表自动逆序回收
```

三条铁律：
1. **唯一入口**：`register(host)` / `unregister(host)` 是唯一生命周期协议（旧 match/parse 函数式协议仅经兼容层支持）
2. **唯一注册机制**：所有贡献都是"类"，统一 `host.register_class(cls)`；取消 dict/位置参数混用
3. **唯一上下文**：所有回调（execute/poll/parse/draw/when）统一接收 `PluginContext`

## 二、manifest v2（plugin.json 完整 Schema）

```json
{
  "id": "booth_link",
  "name": "Booth Link Parser",
  "version": "1.2.0",
  "api_version": 2,
  "min_host_version": "1.5.0",
  "author": "User",
  "description": "Parse Booth _link/*.txt files",
  "category": "metadata",
  "tags": ["booth", "link"],
  "entry": "parser.py:register",
  "dependencies": [],
  "enabled_by_default": true,
  "permissions": ["filesystem.read", "database.read", "network.request"],
  "permission_mode": "advisory"
}
```

| 字段 | 类型 | 必填 | 说明 | 对应问题修复 |
|---|---|---|---|---|
| `id` | string | ✅ | 唯一 ID（`[a-z0-9_]+`） | P7 |
| `name` / `version` | string | ✅ | 展示名 / semver | — |
| `api_version` | int | ✅ | **声明所用 API 版本**；host 版本过旧则拒绝加载（提示升级） | P10 |
| `min_host_version` | string | ✅ | 最低宿主版本 | P10 |
| `author` / `description` / `category` / `tags` | string/list | — | 管理器展示与分组 | P7/P14 |
| `entry` | string | ✅ | `模块:函数`，默认 `parser.py:register` | P1 |
| `dependencies` | list | — | 依赖的插件 id（加载时校验，缺失→ERROR 且提示） | P10 |
| `enabled_by_default` | bool | — | **仅声明默认值**；用户状态存 AppSettings（单一事实来源） | P11 |
| `permissions` | list | — | 申请的权限（见 §六） | P4 |
| `permission_mode` | enum | — | `"advisory"`（警告）或 `"enforced"`（阻止+可选确认） | P4 |

**删除/废弃字段**：`enabled`（→enabled_by_default）、`provides`（未实现过，不再承诺）、`config_schema`（由 Preferences 类替代）、`display_fields`（由 MetadataProvider 类替代）、`kind`（不再需要，类型由注册的类决定）。

## 三、核心对象

### 1. `PluginContext`（运行时上下文，类 bpy.context）

```python
class PluginContext:
    @property
    def library_root(self) -> Path | None        # 当前库根（无库时 None）
    @property
    def session(self) -> LibrarySession | None   # 当前库会话
    @property
    def current_directory(self) -> Path | None   # 文件列表当前目录
    @property
    def selected_paths(self) -> tuple[Path, ...] # 当前选中（文件列表/详情/侧边栏联动）
    @property
    def focused_path(self) -> Path | None        # 信息面板当前文件
    @property
    def window(self) -> object | None            # 主窗口（仅桌面端非空）
    def services(self) -> ServiceBundle          # 当前会话的 scoped 服务（见 §五 权限）
    def show_notification(self, message: str, level: str = "info") -> None
    def refresh(self, domains: list[str] | None = None) -> None   # 请求界面刷新（投影域）
    def open_share_dialog(self, paths: list[Path]) -> None        # 打开分享对话框
    def log(self, message: str, level: str = "info") -> None      # 写插件日志（管理器可查）
```

**关键语义**：`PluginContext` 是**动态查询**（每次访问读当前 UI 状态），不是注册时快照。插件在执行时通过它获知"我在对什么操作"——修复 P3。

### 2. `PluginHost`（注册表，类 bpy.utils 注册器）

```python
class PluginHost:
    def register_class(self, cls: type) -> bool      # 唯一注册入口
    def unregister_class(self, cls: type) -> None
    def plugin_context(self) -> PluginContext        # 运行时上下文获取
    def declare_permission(self, permission: str, mode: str) -> None  # 由 manifest 自动调用
```

`register_class` 的**类型分派**（按基类自动归类到对应注册表）：
`CommandOperator` → 命令表；`FileParser` → 解析器表；`MenuContributor` → 菜单表；`PanelContributor` → 停靠面板表；`Preferences` → 设置表；`EventHook` → 事件表；`ColumnContributor` → 列表；`SearchProvider` → 搜索表；`CategoryContributor` → 分类表；`ThemeTokenContributor` → 主题 token 表；`ContextMenuItem` → 右键菜单表；`KeymapContributor` → 快捷键表。

## 四、12 种贡献类型规范

### 1. `CommandOperator`（升级自 Command；Blender Operator 的轻量版）

```python
from AssetsManager.plugin_api import CommandOperator, PluginContext, OperatorParams

class MyCommand(CommandOperator):
    id = "my_plugin.do_thing"          # 唯一 ID（插件前缀强制）
    title = "Do Thing"
    icon = "wand"                      # 主题图标名（非 emoji）
    menu_paths = ("tools",)            # 出现在哪些菜单
    shortcut = "Ctrl+Shift+T"          # 可选；提交到 KeymapContributor 冲突检测
    undoable = True                    # 是否进撤销栈（默认 False；True 需实现 do/undo）

    params = OperatorParams(
        pattern=dict(type="str", label="Pattern", default="*.png", required=True),
        recursive=dict(type="bool", label="Recursive", default=True),
    )                                   # 声明式参数 → 自动生成参数对话框

    @classmethod
    def poll(cls, ctx: PluginContext) -> bool:
        return ctx.selected_paths and ctx.session is not None

    def execute(self, ctx: PluginContext, params: dict) -> None:
        # params 由对话框/快捷键默认值填充；撤销操作经 self.record_undo(...)
        ...
```

**关键点**：
- `poll` 决定命令可用性（菜单置灰/隐藏）——替代 `enabled: bool`
- `params` 声明式参数 → 自动参数对话框（修复"命令无参数"）
- `undoable=True` 时自动接入 UndoService（记录/撤销由框架处理）——修复"插件操作不可撤销"
- `execute` 统一收 `PluginContext`——修复双执行路径（P13）

### 2. `ContextMenuItem`（升级：统一签名 + 动态子菜单）

```python
class SendToArchive(ContextMenuItem):
    id = "my_plugin.send_archive"
    label = "Send to Archive"
    order = 10
    command_id = "my_plugin.do_thing"     # 关联 CommandOperator

    @classmethod
    def poll(cls, ctx: PluginContext, file_path: str) -> bool:
        return file_path.endswith(".psd")
```

### 3. `FileParser`（归化 match/parse 协议——最重要的一次收敛）

```python
class BoothLinkParser(FileParser):
    id = "booth_link.parser"
    output_fields = (                       # 取代 manifest display_fields
        ("url",    "info.field_link", "url"),
        ("name",   "info.field_name", "text"),
    )
    @classmethod
    def match(cls, ctx: PluginContext, file_path: str) -> bool: ...
    def parse(self, ctx: PluginContext, file_path: str) -> dict: ...
```

**语义**：旧函数式 match/parse 模块自动经兼容层包装成此类。`output_fields` 与 `parse()` 返回键**在加载时静态校验**（键集不匹配 → 诊断警告）——修复 P2 的静默丢弃。

### 4. `MetadataProvider`（升级自 display_fields）

```python
class DownloadStats(MetadataProvider):
    id = "download_tracker.stats"
    fields = (("last_downloaded", "info.field_last_downloaded", "text"),)
    def provide(self, ctx: PluginContext, file_path: str) -> dict | None:
        # 从 plugin_metadata 表读取；返回 None = 不显示
```

与 FileParser 的区别：Parser 是"文件内容 → 字段"，Provider 是"任意来源 → 字段"。两者统一进 InfoPanel 的元数据区，输出都经 `plugin_metadata` 表持久化。

### 5. `PanelContributor`（修复 ToolWindow 死代码）

```python
class MyPanel(PanelContributor):
    id = "my_plugin.panel"
    title = "My Panel"
    area = "right"                        # left/right/bottom（QDock 区域）
    singleton = True
    def build(self, ctx: PluginContext) -> QWidget:
        # 返回 Qt 组件；由 DockFactory 挂载为 QDockWidget
```

**消费点**：WindowCoordinator 注册时创建 dock；`tool_windows()` 移除——修复 P5。

### 6. `CategoryContributor` / `ThemeTokenContributor`（修复 apply 无调用者）

```python
class CadCategory(CategoryContributor):
    id = "cad"
    label = "CAD Files"
    extensions = frozenset({".dwg", ".dxf"})

class MyToken(ThemeTokenContributor):
    token = "plugin_accent"
    fallback = "#7c3aed"
```

**修复**：注册时立即 `apply_registered_categories`（管理器在 register_class 成功时自动调用），卸载时自动回收（现有 remove_* 保留）。

### 7. `SearchProvider`（升级：上下文 + 可选异步）

```python
class BoothSearch(SearchProvider):
    id = "booth.search"
    label = "Booth"
    def search(self, ctx: PluginContext, query: str) -> list[dict]:
        return [{"name": ..., "path": ..., "extension": ...}]
```

### 8. `ColumnContributor`（升级：提供取值函数而非仅声明）

```python
class AuthorColumn(ColumnContributor):
    id = "plugin_author"
    label = "Author"
    width = 140
    def value(self, ctx: PluginContext, file_path: str) -> str:
        return self.plugin_metadata_get(file_path, "author", "")
```

### 9. `EventHook`（规范化 hook）

```python
class OnLibraryOpened(EventHook):
    event = "LibraryOpened"
    def handle(self, ctx: PluginContext, event: DomainEvent) -> None: ...
```

### 10. `Preferences`（新增：插件设置，Blender AddonPreferences）

```python
class MyPreferences(Preferences):
    settings = OperatorParams(
        api_key=dict(type="str", label="API Key", secret=True),
        auto_sync=dict(type="bool", label="Auto Sync", default=False),
    )
```
- 持久化：`RuntimeData/Shared/plugin_prefs/{plugin_id}.json`（JsonStore 原子写）
- UI：设置对话框新增"插件"Tab，按插件分组渲染表单（由参数 schema 自动生成——`OperatorParams` 一处定义两处使用，同 Blender props 哲学）
- API：`ctx.services().preferences(plugin_id)` 读写

### 11. `KeymapContributor`（新增）

```python
class MyKeys(KeymapContributor):
    bindings = (("my_plugin.do_thing", "Ctrl+Shift+T"),)
```
- 冲突检测：注册时与现有快捷键表比对，冲突 → 诊断警告 + 不注册（而非静默覆盖）

### 12. `MenuContributor`（升级：动态构建）

```python
class RecentSharesMenu(MenuContributor):
    id = "my_plugin.recent"
    menu_path = "plugins"                  # tools/plugins/context 三处固定位 + 插件区
    def items(self, ctx: PluginContext) -> list[tuple[str, str]]:
        return [(label, command_id), ...]   # 动态菜单项
```

## 五、服务访问与权限门禁

### 插件能碰什么（sanctioned surface）

```python
ctx.services() -> ServiceBundle
    # 白名单服务，由权限授予动态决定：
    #   filesystem.read   → asset_service, search_service(只读路径)
    #   filesystem.write  → file_operation_service（受 PathGuard 约束）
    #   database.read     → tag_service/metadata_service 读方法
    #   database.write    → tag_service/metadata_service 写方法
    #   network.request   → 允许网络（在插件线程执行）
    #   settings.read/write → settings 访问
    #   clipboard.*       → 剪贴板
```

### 权限执行模型（修复 P4）

| 模式 | 行为 |
|---|---|
| `advisory`（默认） | 越权调用打 warning + 写入插件诊断；**不阻止**（与现行为一致，但至少被记录） |
| `enforced` | 越权调用**抛出 `PermissionError`**，由框架捕获 → 插件诊断 + 操作失败提示 |

实施方式：`ServiceBundle` 返回**包装代理**（permission-checking proxy），对非授权方法抛 PermissionError。授权依据 = manifest 声明的 `permissions` ∩ host 授予集（默认全授予 manifest 声明项）。**这意味着权限系统首次真正生效**。

## 六、生命周期状态机（完整化）

```
discovered ──解析成功──▶ loadable ──load──▶ active ──unload──▶ loadable
     │                     │  ▲                │
     │ 解析失败            │  │ unload失败      │ load失败
     ▼                     ▼  └──▶ error ◀──────┘
   invalid              error（可 reload 重试）
```

| 事件 | 行为 |
|---|---|
| 启用（UI） | `enable_plugin` → **立即 load**（修复 P10：不再等重启）；load 失败回滚 enabled=False |
| 禁用（UI） | unload → enabled=False（持久化 plugin_disabled_ids） |
| 重载（UI 新增） | unload → load（热重载插件开发） |
| 依赖缺失 | ERROR + 诊断"缺少依赖: xxx" |
| api_version 过旧 | 拒绝加载 + 诊断"需要宿主 vX.Y+" |

**模块作用域隔离**（修复 P12）：插件加载时包一层 `importlib` 命名空间包装（`_plugins.{id}` 前缀），卸载只删自己命名空间，不动共享模块。

## 七、示例：booth_link 用新 API 重写

```python
"""plugin.json"""
{
  "id": "booth_link",
  "name": "Booth Link Parser",
  "version": "1.2.0",
  "api_version": 2,
  "min_host_version": "1.5.0",
  "author": "User",
  "category": "metadata",
  "entry": "parser.py:register",
  "permissions": ["filesystem.read", "database.read"]
}

"""parser.py"""
from AssetsManager.plugin_api import (
    FileParser, PluginContext, PluginHost, CommandOperator,
)

class BoothLinkParser(FileParser):
    id = "booth_link.parser"
    output_fields = (
        ("url", "info.field_link", "url"),
        ("name", "info.field_name", "text"),
        ("author", "info.field_author", "text"),
        ("item_id", "info.field_id", "text"),
    )
    @classmethod
    def match(cls, ctx, file_path):
        return file_path.lower().endswith(".txt") and Path(file_path).parent.name == "_link"
    def parse(self, ctx, file_path):
        ...  # 原逻辑，返回 {"url": ..., "name": ..., "author": ..., "item_id": ...}

class OpenBoothPage(CommandOperator):
    id = "booth_link.open_page"
    title = "Open Booth Page"
    menu_paths = ("context",)
    @classmethod
    def poll(cls, ctx):
        return bool(ctx.focused_path)
    def execute(self, ctx, params):
        import webbrowser
        url = ctx.services().metadata().plugin_field(ctx.focused_path, "booth_link", "url")
        if url:
            webbrowser.open(url)

def register(host: PluginHost):
    host.register_class(BoothLinkParser)
    host.register_class(OpenBoothPage)

def unregister(host: PluginHost):
    pass  # 注册表自动回收；无需手写
```

**对比旧版**：协议从"约定 match/parse 两个函数名"变成"继承 FileParser 类"；展示字段从 manifest 移入类属性（一处维护）；新增命令可复用解析数据；权限真实生效。

## 八、API 面定义（插件能 import 什么）

```python
# AssetsManager/plugin_api/__init__.py —— 唯一 sanctioned 入口
from AssetsManager.plugin_api.types import (
    PluginContext, PluginHost, OperatorParams,
    CommandOperator, ContextMenuItem, FileParser, MetadataProvider,
    PanelContributor, CategoryContributor, ThemeTokenContributor,
    SearchProvider, ColumnContributor, EventHook, Preferences,
    MenuContributor, KeymapContributor,
)
```

**规则**：插件只能 `import AssetsManager.plugin_api`；import 其他 `AssetsManager.*` 内部模块 → 诊断警告（advisory）或拒绝（enforced 模式）。这是"API 边界"的物理表达——修复"插件可以摸到一切"的现状。
