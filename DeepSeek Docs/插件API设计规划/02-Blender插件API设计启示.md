# 02 · Blender 插件 API 设计启示

> 目标：拆解 Blender 插件 API 的核心机制，逐条判断"哪些值得借鉴、哪些必须改造、哪些不能照搬"。

## 一、Blender 插件 API 的核心机制（2024+ 现状）

### 1. `bl_info` —— 规范化元数据字典
```python
bl_info = {
    "name": "My Addon",
    "author": "Me",
    "version": (1, 2, 0),
    "blender": (4, 0, 0),        # 最低 Blender 版本
    "location": "View3D > Sidebar",
    "description": "...",
    "category": "Material",
    "support": "COMMUNITY",
    "warning": "",
    "doc_url": "...",
}
```
**作用**：扩展管理器以此做版本兼容判定、分类、元信息展示。声明式、无副作用。

### 2. `register()` / `unregister()` —— 模块级生命周期钩子
```python
def register():
    bpy.utils.register_class(MyOperator)
    bpy.utils.register_class(MyPanel)

def unregister():
    bpy.utils.unregister_class(MyOperator)
    bpy.utils.unregister_class(MyPanel)
```
**作用**：幂等的模块加载/卸载约定。Blender 保证 register 前模块刚导入、unregister 后模块可安全删除。

### 3. `register_class()` 注册表 —— 唯一注册机制
**所有扩展点都是"类"，所有注册都走同一个函数**。类本身用属性声明元数据、用方法实现行为：

```python
class OBJECT_OT_add_cube(bpy.types.Operator):
    bl_idname = "object.add_cube"     # 唯一 ID
    bl_label = "Add Cube"
    bl_options = {"REGISTER", "UNDO"}  # 可撤销

    size: bpy.props.FloatProperty(name="Size", default=2.0)  # 参数

    @classmethod
    def poll(cls, context):            # 上下文过滤
        return context.object is not None

    def execute(self, context):        # 行为；返回 {'FINISHED'}
        bpy.ops.mesh.primitive_cube_add(size=self.size)
        return {'FINISHED'}
```

### 4. `bpy.context` —— 运行时上下文对象
插件执行时通过 `context` 读取**当时的**状态（活动对象、选区、场景、空间类型），不是注册时的快照。**UI 项可用性（poll）与操作执行（execute）都依赖它**。

### 5. `bpy.props` —— 声明式属性系统
`FloatProperty/EnumProperty/PointerProperty` 等：类型 + 默认值 + 范围 + 回调。属性**既是 Operator 参数、也是 UI 自动生成表单的数据源、也是属性面板的字段**——一份声明三处使用。

### 6. Operator / Panel / PropertyGroup / AddonPreferences —— 四大基类
| 基类 | 用途 |
|---|---|
| `Operator` | 可撤销操作，带属性参数与 poll |
| `Panel` | UI 面板（`bl_space_type`/`bl_category` 声明挂载位置，`draw()` 绘制） |
| `PropertyGroup` | 可持久化的数据结构（挂到场景/对象上，进 .blend 文件） |
| `AddonPreferences` | 插件设置（自动出现在系统偏好设置页，进 userpref） |

### 7. Handler 与 Keymap —— 事件与快捷键
- `bpy.app.handlers`：`frame_change_pre`/`scene_update_post` 等生命周期钩子
- Keymap：`bpy.context.window_manager.keyconfigs.addon.keymaps.new(...)` 注册快捷键

### 8. Extension 系统（4.2+）
- manifest（`blender_manifest.toml`）：`blender_version_min`、`dependencies`（可声明依赖其他扩展）、`tags`
- 远程仓库安装、自动依赖解析、扩展禁用不卸载

## 二、可借鉴性判断

| Blender 机制 | 借鉴 | 必须改造 | 不能照搬 | 理由 |
|---|---|---|---|---|
| bl_info 元数据 | ✅ | — | — | 当前 manifest 缺 min_version/author/category，补齐即可 |
| register/unregister 模块级 | ✅ | — | — | 当前已部分有（_FunctionAdapter.register），需成为**唯一**约定 |
| **register_class 注册表** | ✅ | — | — | 核心收益：一种注册机制覆盖所有扩展点，消灭 10 个零散方法 |
| 类属性声明（bl_idname/bl_options） | ✅ | — | — | 比 dict/位置参数自描述，且可静态校验 |
| **bpy.context 运行时上下文** | ✅ | — | — | 当前最大缺失；必须把"注册时快照"改成"执行时查询" |
| **Operator（参数/撤销/poll）** | ✅ | — | — | 命令升级为 Operator：参数化、可撤销（挂 UndoService）、poll 可用性 |
| bpy.props 属性系统 | — | ✅ | — | Blender 的复杂属性系统（PointerProperty/动态注册进类型）对单机工具过重；改为**参数描述 dict**（类型/默认/范围/标签），够用即可 |
| Panel 基类 | — | ✅ | — | 桌面是自绘网格/自建面板，无 Blender 的"注册到空间"概念；改为"Dock 面板贡献"（ToolWindow 的正式化） |
| PropertyGroup 持久化 | — | — | ❌ | 需要数据模型注册表 + 序列化系统，投入巨大；当前 file_meta/plugin_metadata 表已够用 |
| Handler 事件 | ✅ | — | — | 已有 EventBus，规范化为声明式 EventHook 类即可 |
| Keymap | — | ✅ | — | 桌面快捷键系统自定义（_shortcuts.py），需自定义注册 API，不能照搬 |
| Extension 依赖解析 | ✅ | — | — | 借鉴 manifest 的 dependencies 字段与 min_host_version |

## 三、Blender 设计哲学的提炼（对本次设计的指导原则）

1. **一个注册机制，而不是十个**：所有贡献都是"类 + `register_class()`"。插件作者只学一个概念。
2. **声明与行为分离**：类属性=声明（元数据/参数/权限/挂载点），类方法=行为（execute/draw/poll/parse）。静态可校验、UI 可自动生成。
3. **上下文贯穿一切**：poll(可用性)、execute(行为)、draw(展示) 全部接收同一个 `PluginContext`——插件永远知道"我在对什么操作"。
4. **可撤销是一等公民**：操作默认可进撤销栈，而不是事后追加。
5. **元数据完整、可版本化**：min_host_version/dependencies/author/category 让管理器能做兼容判定与生态展示。
6. **生命周期可逆**：register/unregister 严格对称，错误时逆序回滚。

## 四、必须保留的现有资产（不推翻重来）

| 资产 | 保留方式 |
|---|---|
| `PluginManagerService` 的状态机（discovered→loadable→active→error） | 状态机正确，保留 |
| `PluginHostContext.unregister_plugin` 的贡献清理 | 保留，迁移到注册表实现 |
| `EventBus.hook` 事件订阅（含 owner 跟踪与卸载清理） | 保留，规范化为 EventHook 类 |
| `parse_file` 的双路径合并逻辑 | 收敛为单一 FileParser 注册表 |
| plugin_metadata 持久化（插件禁用后字段仍显示） | 完全保留，这是正确设计 |
| `display_fields` 概念 | 升级为 MetadataProvider 正式化 |
| PluginManagerDialog 的整体结构 | 增强而非重写 |

## 五、设计目标（一句话）

**以"类声明 + 注册表 + 运行时上下文"为骨架，把现有 10 种零散注册收敛为 1 种，把 match/parse 特化协议归化为 1 个贡献类型，把权限系统从死代码变成真门禁，并补齐 Preferences/Operator/热重载/版本兼容四个缺口。**
