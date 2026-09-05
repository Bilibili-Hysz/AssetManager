"""阶段 A 视觉基线夹具 — 确定性样本库构造器（交付物 A-1）。

`build_sample_library(tmp_path, profile)` 产出**确定性**样本库：同一
profile 每次运行产出 byte 级相同的文件内容、固定的 mtime epoch（经
`os.utime` 钉死）与固定的标签集合。真实标签写入走库会话的
TagService（与 test_file_list_ai_tag._make_image + add_tag 同一惯例），
使截图中的标签胶囊、目录树、信息面板呈现真实业务数据而非桩。

profiles（对应报告 §9.2 的“数据”维度的代表子集）：
- ``empty``          空目录（空态截图）
- ``minimal``        1 个 txt + 1 个 PIL 纯色 png
- ``representative`` 长名文件、多标签图片、PIL 彩图、子目录、
                      不同 mtime、大小差异

返回 ``(root, metadata)``；metadata 是文件清单 + 字节数 + mtime 的
普通 dict，供断言与 manifest 记录（不携带任何 Qt 对象，便于 json 落盘）。

ui_scale 钉 1.0 由测试模块的 fixture 负责（`pin_ui_scale`），本模块
只负责文件系统与库会话侧的数据确定性。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

# 所有 profile 统一使用的固定 mtime epoch（2020-01-02 03:04:05Z 等），
# 与文件内容写死字节同为确定性来源：不同机器、不同运行时间产出
# 相同的 stat 结果。
MTIME_EPOCHS = {
    "old": 1_577_934_000,   # 2020-01-02T03:04:05Z
    "mid": 1_600_000_000,   # 2020-09-13T12:26:40Z
    "new": 1_700_000_000,   # 2023-11-14T22:13:20Z
}


@dataclass(frozen=True)
class _FileSpec:
    """写死字节的单个样本文件描述。"""

    relpath: str
    data: bytes
    mtime_epoch: int


@dataclass(frozen=True)
class SampleLibrary:
    """确定性样本库 + 其元数据清单。"""

    profile: str
    root: Path
    # (相对路径, 字节数, mtime) 三元组，按路径排序 —— metadata 快照。
    files: tuple[tuple[str, int, int], ...] = ()
    # (相对路径, 标签列表) —— 经真实 TagService 写入的标签集合。
    tags: tuple[tuple[str, tuple[str, ...]], ...] = ()
    extra: dict[str, Any] = field(default_factory=dict, hash=False)

    def metadata(self) -> dict[str, Any]:
        """可 JSON 落盘的确定性 metadata（报告 §9.3 记录要求）。"""
        return {
            "profile": self.profile,
            "files": [
                {"path": p, "bytes": n, "mtime": t} for p, n, t in self.files
            ],
            "tags": [
                {"path": p, "tags": list(ts)} for p, ts in self.tags
            ],
        }


def _write(root: Path, spec: _FileSpec) -> None:
    """写入写死字节并以 os.utime 钉死 mtime（写后立即钉，杜绝漂移）。"""
    path = root / spec.relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(spec.data)
    os.utime(path, (spec.mtime_epoch, spec.mtime_epoch))


def _png_bytes(color: tuple[int, int, int], size: tuple[int, int] = (24, 24)) -> bytes:
    """PIL 生成纯色 PNG 的字节（24x24 惯例与 test_file_list_ai_tag 一致）。

    每次 Image.new + save 的输出对同一 (色, 尺寸) 是确定性的
    （PNG 编码无时间戳字段），这里返回 bytes 由测试再落盘。
    """
    import io

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _png_gradient_bytes(size: tuple[int, int] = (24, 24)) -> bytes:
    """真实彩图（非纯色）：横向渐变 + 固定伪随机噪点，内容确定性。"""
    import io

    img = Image.new("RGB", size)
    px = img.load()
    assert px is not None  # load() 在内存图上恒可用；空值仅理论路径
    for y in range(size[1]):
        for x in range(size[0]):
            # 固定公式（无随机种子依赖），同一输入恒定输出
            r = (x * 11 + y * 3) % 256
            g = (x * 5 + y * 17) % 256
            b = (x * 29 + y * 7) % 256
            px[x, y] = (r, g, b)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── profile 定义（文件与标签集合写死于此，改动即破坏确定性快照）──────

_MINIMAL_SPECS: tuple[_FileSpec, ...] = (
    _FileSpec("note.txt", b"minimal sample note\n", MTIME_EPOCHS["mid"]),
    _FileSpec("photo.png", _png_bytes((10, 120, 40)), MTIME_EPOCHS["mid"]),
)

_LONG_NAME = (
    "a-very-long-asset-file-name-designed-to-exercise-truncation-and-eliding"
    "-in-the-grid-and-details-views-final-vendor-shot-2020.png"
)

_REPRESENTATIVE_SPECS: tuple[_FileSpec, ...] = (
    # 大小差异：tiny 1 字节 → large 8 KiB
    _FileSpec("tiny.bin", b"\x00", MTIME_EPOCHS["old"]),
    _FileSpec("large.bin", bytes(range(256)) * 32, MTIME_EPOCHS["new"]),
    # 纯色图（PIL 生成）
    _FileSpec("solid.png", _png_bytes((10, 120, 40)), MTIME_EPOCHS["old"]),
    # 真实彩图（渐变 + 固定噪点）
    _FileSpec("gradient.png", _png_gradient_bytes(), MTIME_EPOCHS["mid"]),
    # 长名文件（截断/省略路径）
    _FileSpec(_LONG_NAME, _png_bytes((200, 60, 30)), MTIME_EPOCHS["new"]),
    # 子目录内文件（目录树 + 网格文件夹卡）
    _FileSpec("sub/inner.txt", b"inner file\n", MTIME_EPOCHS["mid"]),
    _FileSpec("sub/nested.png", _png_bytes((30, 60, 200)), MTIME_EPOCHS["new"]),
)

_REPRESENTATIVE_TAGS: dict[str, tuple[str, ...]] = {
    "solid.png": ("hero", "landscape"),
    "gradient.png": ("favorite", "hero", "wallpaper"),
    _LONG_NAME: ("favorite",),
    "sub/nested.png": ("reference",),
}

_SPECS_BY_PROFILE: dict[str, tuple[_FileSpec, ...]] = {
    "empty": (),
    "minimal": _MINIMAL_SPECS,
    "representative": _REPRESENTATIVE_SPECS,
}

_TAGS_BY_PROFILE: dict[str, dict[str, tuple[str, ...]]] = {
    "empty": {},
    "minimal": {},
    "representative": _REPRESENTATIVE_TAGS,
}


def build_sample_library(tmp_path: Path | str, profile: str, *,
                         tag_service: Any = None) -> SampleLibrary:
    """构造确定性样本库。

    ``tmp_path`` 是库根（必须为空或不存在）；``profile`` 见模块 docstring。
    ``tag_service`` 传入库会话的真实 ``services.tag_service`` 时按写死的
    标签集合写入（参考 test_file_list_ai_tag.py:94 的 add_tag 惯例）；
    不传则只落文件（面板单测场景），标签记入 metadata 待后续写入。
    """
    root = Path(tmp_path)
    root.mkdir(parents=True, exist_ok=True)
    if profile not in _SPECS_BY_PROFILE:
        raise ValueError(f"unknown profile: {profile!r}")

    for spec in _SPECS_BY_PROFILE[profile]:
        _write(root, spec)

    files = tuple(
        (spec.relpath, len(spec.data), spec.mtime_epoch)
        for spec in sorted(_SPECS_BY_PROFILE[profile], key=lambda s: s.relpath)
    )

    tags_plan = _TAGS_BY_PROFILE[profile]
    applied: list[tuple[str, tuple[str, ...]]] = []
    if tag_service is not None:
        for relpath in sorted(tags_plan):
            absolute = str((root / relpath).resolve())
            for tag in tags_plan[relpath]:
                tag_service.add_tag(str(root), absolute, tag)
            # 读回 canonical 标签集合 —— 库侧的规范化结果才是真实呈现
            applied.append(
                (relpath, tuple(tag_service.get_tags(str(root), absolute)))
            )
    elif tags_plan:
        # 未提供 service：把计划标签记入 metadata（声明数据意图）。
        applied = sorted((p, tuple(ts)) for p, ts in tags_plan.items())

    return SampleLibrary(
        profile=profile,
        root=root,
        files=files,
        tags=tuple(applied),
    )
