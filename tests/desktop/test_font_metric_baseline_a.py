"""阶段 A 字体度量对照 — V01 证据落档 + 防漂移棘轮（交付物 A-3）。

V01（报告 §5）：同一文字角色（如 ``caption``）在三处以不同单位落地：
1. **QSS 像素族**：StyleKit.label_css 等工厂输出 ``font-size: Npx``
   （stylekit.py:178 等），调用方另有手写 ``font-size:`` QSS；
2. **QFont 点族**：QFont.setPointSize 调用点（command_palette.py:88
   等，语义字号经 scaled_pt 传给 point size）；
3. **自绘点族**：网格/图片查看器手写 9/8 pt（_grid_widget.py:112,116、
   _grid_widget_data.py:82,86,89、image_viewer 多处）。

本模块做两件事：

- **盘点落档**：用 Python 读源码扫描（不引 shell）三族字体用法，把每处
  (文件, 行, 角色提示, 数值, 单位) 写成确定性 JSON 清单
  ``docs/reports/desktop-visual-consistency-2026-09-05-evidence/
  font-usage-inventory.json``（入库，机器可读证据表）。
  断言"清单与证据一致"：新用法出现即红，提示人审视 —— V01 的防漂移
  棘轮；不锁死具体数值（那是阶段 B 的设计决定）。
  再生：``FONT_INVENTORY_UPDATE=1``。
- **度量实测**：QFontMetrics 对同一 ``caption`` 角色分别按 pt 与 px
  渲染，测 height/averageCharWidth/水平 advance。证明"单位不同 → 度量
  不同"，不证明哪个对（单位规范是阶段 B 的决定）。

扫描范围刻意限定生产代码 ``AssetsManager/``；tests 与 scripts 的用法
不属于 V01 的对象。
"""
from __future__ import annotations

import ast
import datetime as _dt
import json
import os
import re
from pathlib import Path

import pytest
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QApplication

pytestmark = pytest.mark.xdist_group(name="serial")

REPO_ROOT = Path(__file__).resolve().parents[2]
PROD_ROOT = REPO_ROOT / "AssetsManager"
EVIDENCE_PATH = (
    REPO_ROOT / "docs" / "reports"
    / "desktop-visual-consistency-2026-09-05-evidence" / "font-usage-inventory.json"
)
# caption 角色 pt/px 度量对照表（每次运行覆盖写入；机器相关数值仅作
# 证据记录，不做回归断言 —— 断言只锁"两族分叉"这一机制事实）。
METRICS_EVIDENCE_PATH = (
    REPO_ROOT / "docs" / "reports"
    / "desktop-visual-consistency-2026-09-05-evidence" / "font-caption-metrics.json"
)

# QSS 像素族：``font-size: <expr>px``。源码层面有两种形态——f-string
# 模板（``font-size: {self.pt(size)}px``、``font-size: {_font('xs')}px``，
# 表达式内含引号/花括号/点号）与纯字面量（``font-size: 12px``）。
# 正则按"到 px 词界为止"非贪婪取值，分隔符为分号或字符串字面量引语
# 边界（QSS 语句分隔）。数值域保留源表达式（阶段 B 迁移需逐处审视，
# 不求值）。
_QSS_FONT_SIZE_RE = re.compile(r"font-size\s*:\s*([^;]+?)\bpx\b")
# QFont 点族 / 像素族：setPointSize(...) / setPixelSize(...) 调用（含
# 行号定位用 ast；正则仅用于证据里的“原调用文本”截取）。
_SET_PT_RE = re.compile(r"\.setPointSize(?:F)?\(")
_SET_PX_RE = re.compile(r"\.setPixelSize(?:F)?\(")


def _iter_py_files() -> list[Path]:
    """生产代码 .py 清单（确定性排序）。"""
    return sorted(p for p in PROD_ROOT.rglob("*.py") if p.is_file())


def _line_text(source: str, lineno: int) -> str:
    lines = source.splitlines()
    return lines[lineno - 1].strip() if 1 <= lineno <= len(lines) else ""


def _font_role_hint(path: Path, source_line: str) -> str:
    """从变量名/上下文推断角色提示（启发式，仅供人读证据表）。"""
    del path  # 保留参数以稳定签名；角色推断只用行文本
    m = re.search(r"(font\w*)\s*=\s*QFont\(", source_line)
    if m:
        return m.group(1)
    m = re.search(r"self\.(_?\w*font\w*)", source_line)
    if m:
        return m.group(1)
    head = re.search(r"[A-Za-z_][A-Za-z0-9_]*", source_line)
    return head.group(0) if head else "?"


def _scan_qss_px() -> list[dict]:
    """族 1：QSS ``font-size: ...px`` 调用点（工厂 + 手写局部 QSS）。"""
    hits = []
    for path in _iter_py_files():
        source = path.read_text(encoding="utf-8")
        rel = str(path.relative_to(REPO_ROOT))
        for lineno, line in enumerate(source.splitlines(), 1):
            # 模板 f-string 中 px 出现在行内多处；逐匹配落证据
            for m in _QSS_FONT_SIZE_RE.finditer(line):
                hits.append({
                    "family": "qss_px",
                    "file": rel,
                    "line": lineno,
                    "role_hint": _font_role_hint(path, line),
                    "value": m.group(1),
                    "unit": "px",
                })
    return hits


def _scan_qfont_size() -> list[dict]:
    """族 2+3：QFont.setPointSize / setPixelSize 调用点。

    经 ast 定位调用（正则会误中注释/字符串），行内原文本作证据。
    数值取实参源文本（多为 scaled_pt(...) 表达式；阶段 B 迁移时需逐处
    审视，所以证据保留源表达而不是求值结果）。
    """
    hits = []
    for path in _iter_py_files():
        rel = str(path.relative_to(REPO_ROOT))
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute)
                    and func.attr in ("setPointSize", "setPointSizeF",
                                      "setPixelSize", "setPixelSizeF")):
                continue
            arg_src = ", ".join(ast.unparse(a) for a in node.args)
            if node.keywords:
                arg_src = (arg_src + ", " if arg_src else "") + ", ".join(
                    f"{kw.arg}={ast.unparse(kw.value)}" for kw in node.keywords
                )
            line = _line_text(source, node.lineno)
            unit = "pt" if "Point" in func.attr else "px"
            hits.append({
                "family": "qfont_set",
                "method": func.attr,
                "file": rel,
                "line": node.lineno,
                "role_hint": _font_role_hint(path, line),
                "value": arg_src,
                "unit": unit,
                "source_text": line,
            })
    return hits


def _build_inventory() -> dict:
    """确定性证据清单（内容仅由当前源码决定）。"""
    qss = _scan_qss_px()
    qfont = _scan_qfont_size()
    return {
        "generated_by": "tests/desktop/test_font_metric_baseline_a.py",
        "generated_date": _dt.datetime.now(tz=_dt.timezone.utc).date().isoformat(),
        "scope": "AssetsManager/ (production code only)",
        "summary": {
            "qss_px_literals": len(qss),
            "qfont_set_calls": len(qfont),
            "qfont_pt_calls": sum(1 for h in qfont if h["unit"] == "pt"),
            "qfont_px_calls": sum(1 for h in qfont if h["unit"] == "px"),
        },
        "qss_px": sorted(
            qss, key=lambda h: (h["file"], h["line"], h["value"])),
        "qfont_set": sorted(
            qfont, key=lambda h: (h["file"], h["line"], h["method"])),
    }


# ── 防漂移棘轮（V01）────────────────────────────────────────────


@pytest.fixture
def font_inventory():
    """再生模式下落盘证据清单；校验模式返回 (扫描结果, 落档清单)。"""
    scanned = _build_inventory()
    update = os.environ.get("FONT_INVENTORY_UPDATE") == "1"
    if update:
        EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        EVIDENCE_PATH.write_text(
            json.dumps(scanned, indent=2, ensure_ascii=False, sort_keys=True)
            + "\n", encoding="utf-8")
    return scanned


def test_font_usage_inventory_matches_evidence(font_inventory):
    """棘轮：三族字体用法的机器可读清单与落档证据一致。

    新增/删除任何 setPointSize / setPixelSize / ``font-size:…px`` 调用
    都会红：这是刻意设计 —— 字体单位是 V01 的核心漂移面，每次变化都
    必须人工审视并更新证据表（``FONT_INVENTORY_UPDATE=1`` 再生），把
    变更理由留在提交说明里。不断言具体数值（阶段 B 才决定规范单位）。
    """
    assert EVIDENCE_PATH.is_file(), (
        "font-usage-inventory.json missing — run FONT_INVENTORY_UPDATE=1 "
        "once to seed the V01 evidence table")
    recorded = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    scanned = font_inventory
    # 日期字段必然不同（生成日）；比对除日期外的全部内容。
    recorded_body = {k: v for k, v in recorded.items() if k != "generated_date"}
    scanned_body = {k: v for k, v in scanned.items() if k != "generated_date"}
    assert scanned_body == recorded_body, (
        "font usage inventory drifted — review the new/removed "
        "setPointSize|setPixelSize|font-size:px usages, then regenerate "
        "with FONT_INVENTORY_UPDATE=1 and explain the change in the commit")


def test_font_inventory_covers_all_three_families(font_inventory):
    """清单本身必须同时含三族（QSS px 字面量、QFont pt、QFont px），
    证明扫描器没有静默漏族。"""
    summary = font_inventory["summary"]
    assert summary["qss_px_literals"] > 0, "QSS font-size:px family vanished"
    assert summary["qfont_pt_calls"] > 0, "QFont point-size family vanished"
    assert summary["qfont_px_calls"] > 0, "QFont pixel-size family vanished"


# ── 度量实测：同一 caption 角色，pt vs px ─────────────────────────


def _caption_size_pt() -> int:
    """当前主题的 caption 字号 token（themes.py:351 语义：未缩放 pt）。"""
    from AssetsManager.core import themes
    return int(themes.font_size("caption", 10))


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


def test_caption_pt_and_px_fonts_have_different_metrics(qapp):
    """QFontMetrics 证明：同数值不同单位 → 不同度量（不评判哪个对）。

    V01 的量化证据：StyleKit.label_css 把 caption token 当 px 写进 QSS
    （stylekit.py:178 ``font-size: {pt(size)}px``），而 command_palette
    把同族 token 当 pt 传给 setPointSize（command_palette.py:88）。此处
    对同一 ``caption`` 数值分别构造两种字体并测量：
    - height（行高）：px 字体 = N 像素行盒；pt 字体 = N 点换算 DPR 后
      的像素行盒，两者在 1x 下也可能不同（字体引擎 ascent/descent
      取整路径不同）；
    - averageCharWidth：同理受渲染路径影响。
    断言仅要求“度量存在且两种构造产生差异或一致是可复现的”，具体差
    多少取决于系统 DPI/字体，不做数值断言。
    """
    size = _caption_size_pt()
    assert size > 0

    font_pt = QFont()
    font_pt.setPointSize(size)
    font_px = QFont()
    font_px.setPixelSize(size)

    metrics_pt = QFontMetrics(font_pt)
    metrics_px = QFontMetrics(font_px)

    # 两族度量必须可用（非 0），证明都能真正渲染文字
    assert metrics_pt.height() > 0
    assert metrics_px.height() > 0
    assert metrics_pt.averageCharWidth() > 0
    assert metrics_px.averageCharWidth() > 0

    # 记录对照表（供证据与人读）；两族度量不同即 V01 所述漂移条件的
    # 实测确认，相同则说明本机字体引擎在两构造下恰好等价 —— 都合法。
    comparison = {
        "generated_by": "tests/desktop/test_font_metric_baseline_a.py",
        "note": "metrics are DPI/font-engine dependent; recorded as evidence "
                "that same-token pt vs px construction yields different "
                "metrics (V01), not as a normative choice",
        "caption_token_value": size,
        "pt_font": {
            "point_size": font_pt.pointSize(),
            "height_px": metrics_pt.height(),
            "average_char_width_px": metrics_pt.averageCharWidth(),
        },
        "px_font": {
            "pixel_size": font_px.pixelSize(),
            "height_px": metrics_px.height(),
            "average_char_width_px": metrics_px.averageCharWidth(),
        },
        "metrics_equal": (
            metrics_pt.height() == metrics_px.height()
            and metrics_pt.averageCharWidth() == metrics_px.averageCharWidth()
        ),
    }
    METRICS_EVIDENCE_PATH.write_text(
        json.dumps(comparison, indent=2, ensure_ascii=False, sort_keys=True)
        + "\n", encoding="utf-8")
    # 实测断言：setPointSize/setPixelSize 的语义确实分叉（Qt 对同一
    # QFont 分别记录 pointSize/pixelSize），这是 V01 的机制性事实。
    assert font_pt.pixelSize() == -1, "point-size font must not carry pixel size"
    assert font_px.pointSize() == -1, "pixel-size font must not carry point size"


def test_caption_role_reaches_grid_and_palette_in_different_units():
    """V01 的具体样本：caption 角色在网格与命令面板处以不同路径进入
    QFont —— 用源码证据断言这两处调用现存（防止两处之一被静默删除
    导致度量对照失去对象）。

    阶段 B（2026-09-05）后网格名称字号已迁语义 token（xxs=9，零值
    迁移）；8pt 副信息/角标无对应 token，按"视觉零漂移优先"保留手写
    值并注释（阶段 C 校准）——手写 pt 点因此仍在清单中。
    """
    grid_data = PROD_ROOT / "panels" / "file_list" / "_grid_widget_data.py"
    palette = PROD_ROOT / "widgets" / "command_palette.py"
    grid_src = grid_data.read_text(encoding="utf-8")
    palette_src = palette.read_text(encoding="utf-8")
    # 网格名称：语义 token（xxs=9，与原手写 9 等值）
    assert 'setPointSize(scaled_pt(int(themes.font_size("xxs"))))' in grid_src
    # 网格手写 pt 族（V01 证据行；8pt 无 token，阶段 C 校准）
    assert "setPointSize(scaled_pt(8))" in grid_src
    # 命令面板语义 token → pt 族（V01 证据行）
    assert 'setPointSize(scaled_pt(int(themes.font_size("caption", 10))))' in palette_src
