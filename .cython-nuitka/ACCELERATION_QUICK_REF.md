# Cython & Nuitka 加速方案总结

## 快速参考

### Cython（开发阶段）

```bash
pip install cython
python build_cython.py
python test_performance.py
```

**优点**：编译快、可选择性优化、性能提升 2-10 倍  
**缺点**：需要相同 Python 版本、修改后需重新编译

### Nuitka（部署阶段）

```bash
pip install nuitka
python build_nuitka.py
dist\AssetManager.bat
```

**优点**：独立可执行文件、整体性能提升 2-5 倍、保护源代码  
**缺点**：编译时间长、需要处理 Qt 插件问题

---

## 常见错误速查

### Cython 错误

| 错误 | 解决方案 |
|------|----------|
| `UnicodeEncodeError` | 避免在 print 中使用 Unicode 字符 |
| `DLL load failed` | 确保 `.pyd` 文件与 `.py` 文件在同一目录 |
| 修改后不生效 | 重新运行 `python build_cython.py` |

### Nuitka 错误

| 错误 | 解决方案 |
|------|----------|
| `No module named nuitka` | 使用虚拟环境 Python |
| `Qt platform plugin` | 设置 `QT_PLUGIN_PATH` 或使用 standalone 模式 |
| `Python version not supported` | 等待 Nuitka 更新或使用 Python 3.13 |
| 编译时间过长 | 使用 `--lto=yes`、排除不需要模块 |

---

## 推荐工作流程

### 开发阶段（Cython）

1. 识别热点代码（缓存、数据库、颜色转换等）
2. 使用 Cython 编译这些模块
3. 测试性能提升
4. 继续开发迭代

### 部署阶段（Nuitka）

1. 使用 standalone 模式编译
2. 确保包含 Qt 插件
3. 测试编译后的应用
4. 打包分发

---

## 性能对比

| 操作 | 编译前 | 编译后 | 提升 |
|------|--------|--------|------|
| Cache Set | ~500K ops/sec | 1.1M ops/sec | **2.2x** |
| Cache Get | ~1.5M ops/sec | 3.8M ops/sec | **2.5x** |
| hex_to_rgb | ~800K ops/sec | 2.7M ops/sec | **3.4x** |
| rgb_to_hex | ~400K ops/sec | 1.2M ops/sec | **3.0x** |

---

## 关键注意事项

### Cython
- ✅ 只编译热点模块，不要全量编译
- ✅ 源代码修改后必须重新编译
- ✅ 使用 `language_level=3` 兼容 Python 3

### Nuitka
- ✅ 使用 standalone 模式避免 Qt 插件问题
- ✅ 必须包含 `PySide6/plugins` 目录
- ✅ 在虚拟环境中运行编译
- ✅ 排除不需要的模块减少编译时间

---

**完整文档**：`ACCELERATION_GUIDE.md`