"""Extract the dated atlas diagrams and inventory without importing the app."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


OUTPUT = Path(__file__).resolve().parent
ROOT = OUTPUT.parents[2]
ATLAS = ROOT / "docs/architecture-code-atlas-2026-09-06.md"


def source_paths() -> list[Path]:
    paths: set[Path] = set()
    for folder, suffixes in (
        ("AssetsManager", {".py", ".json"}),
        ("Plugins/Addons", {".py", ".json"}),
        ("webui/src", {".ts", ".tsx", ".css", ".json"}),
        ("assets", {".json"}),
        (".github/workflows", {".yml", ".yaml"}),
    ):
        for path in (ROOT / folder).rglob("*"):
            if path.is_file() and path.suffix in suffixes:
                if not any(part in {"__pycache__", "node_modules"} for part in path.parts):
                    if ".test." not in path.name and ".spec." not in path.name:
                        paths.add(path)
    for name in (
        "main.py", "run.py", "build.py", "AssetManager.spec", "pytest.ini",
        "ruff.toml", "pyrightconfig.json", "webui/package.json",
        "webui/vite.config.ts", "webui/playwright.config.ts",
    ):
        path = ROOT / name
        if path.is_file():
            paths.add(path)
    paths.update(ROOT.glob("requirements*.txt"))
    return sorted(paths, key=lambda path: path.relative_to(ROOT).as_posix())


def python_details(source: str) -> dict:
    tree = ast.parse(source)
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend({"module": item.name, "line": node.lineno} for item in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append({
                "module": "." * node.level + (node.module or ""),
                "names": [item.name for item in node.names],
                "line": node.lineno,
            })
    symbols = []
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            symbol = {"name": node.name, "kind": type(node).__name__, "line": node.lineno}
            if isinstance(node, ast.ClassDef):
                symbol["bases"] = [ast.unparse(base) for base in node.bases]
            symbols.append(symbol)
    return {"imports": imports, "top_level_symbols": symbols}


def route_inventory() -> list[dict]:
    path = ROOT / "AssetsManager/lan/api.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    routes = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "_add" or len(node.args) < 4:
            continue
        method, route = node.args[1:3]
        if not isinstance(method, ast.Constant) or not isinstance(route, ast.Constant):
            continue
        policy = next((ast.unparse(k.value) for k in node.keywords if k.arg == "policy"), "_DEFAULT")
        routes.append({
            "method": method.value, "path": route.value,
            "handler": ast.unparse(node.args[3]), "declared_policy": policy,
            "line": node.lineno,
        })
    return sorted(routes, key=lambda item: item["line"])


def main() -> None:
    source = ATLAS.read_text(encoding="utf-8")
    headings = list(re.finditer(r"^## (\d{2}) (.+)$", source, re.MULTILINE))
    diagrams = []
    for index, heading in enumerate(headings):
        section = source[heading.end():headings[index + 1].start() if index + 1 < len(headings) else len(source)]
        match = re.search(r"```mermaid\n(.*?)\n```", section, re.DOTALL)
        if match is None:
            raise ValueError(f"Missing diagram: {heading.group(0)}")
        filename = f"{heading.group(1)}.mmd"
        (OUTPUT / filename).write_text(match.group(1) + "\n", encoding="utf-8")
        diagrams.append({"id": heading.group(1), "title": heading.group(2), "file": filename})

    files = []
    for path in source_paths():
        raw = path.read_bytes()
        item = {"path": path.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(raw).hexdigest()}
        if path.suffix == ".py":
            item.update(python_details(raw.decode("utf-8-sig")))
        files.append(item)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    status = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"], cwd=ROOT, text=True)
    inventory = {
        "date": "2026-09-06", "head": head,
        "basis": "working tree, including uncommitted files; no application imports or runtime tests",
        "git_status_at_capture": status.splitlines(),
        "static_import_caveat": "Includes local and TYPE_CHECKING imports; does not infer runtime calls or resolve dynamic loading.",
        "routes_caveat": "Explicit _add registrations only; excludes implicit HEAD/static resources and later policy overrides.",
        "diagrams": diagrams, "files": files, "routes": route_inventory(),
    }
    (OUTPUT / "source-inventory.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# 当前代码架构图源与索引", "",
        "[架构图册正文](../../architecture-code-atlas-2026-09-06.md) · [浏览图册](index.html) · [机器可读索引](source-inventory.json)", "",
        f"源码基准：`{head}` 加捕获时工作区。统计：{len(files)} 个生产源码/配置文件，{len(inventory['routes'])} 个显式 HTTP 注册项，{len(diagrams)} 张图。", "",
        "本清单排除生产目录内的 `.test.` / `.spec.` 文件，不包含用户资产或运行数据库。顶层符号和 import 由 Python AST 提取；前端列出源文件，不推断 TypeScript 调用图。", "",
        "## 图源", "", "| 图 | Mermaid | SVG |", "|---|---|---|",
    ]
    lines.extend(f"| {d['id']} {d['title']} | [{d['file']}]({d['file']}) | [{d['id']}.svg]({d['id']}.svg) |" for d in diagrams)
    lines.extend(["", "## HTTP 显式注册项", "", "策略列是 `_add` 调用参数，不包含后续覆盖，例如 `/api/files` 的 GET 策略另被 `declare` 设为 browse。aiohttp 自动 HEAD 和静态资源另由框架注册。", "", "| 方法 | 路径 | Handler | 声明策略 | 源码行 |", "|---|---|---|---|---|"])
    lines.extend(f"| {r['method']} | `{r['path']}` | `{r['handler']}` | `{r['declared_policy']}` | [L{r['line']}](../../../AssetsManager/lan/api.py#L{r['line']}) |" for r in inventory["routes"])
    lines.extend(["", "## 生产模块清单", "", "| 文件 | 顶层类与函数 |", "|---|---|"])
    for item in files:
        names = ", ".join(f"`{s['name']}`" for s in item.get("top_level_symbols", [])) or "配置 / 前端 / 模块声明"
        lines.append(f"| [{item['path']}](../../../{item['path']}) | {names} |")
    lines.extend(["", "## 重新生成", "", "从仓库根目录执行：", "", "```powershell", "python docs/diagrams/code-atlas-2026-09-06/build_atlas.py", "node docs/diagrams/code-atlas-2026-09-06/render_atlas.mjs", "```", "", "先更新正文中的分图再生成。`build_atlas.py` 仅解析与哈希源码；`render_atlas.mjs` 使用现有 Playwright 和 Mermaid 生成静态 SVG 与离线 HTML，首次渲染需要获取固定版本 Mermaid。重新捕获源码会更新清单，不自动证明人工分图仍准确。", ""])
    (OUTPUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    sys.stdout.write(json.dumps({"files": len(files), "routes": len(inventory["routes"]), "diagrams": len(diagrams), "output": str(OUTPUT)}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
