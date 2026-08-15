"""Tag library — Pixiv-style canonical tags with multi-language synonyms.

All tag lookups pass through the library: user input → canonical name.
Hover tooltips show synonyms in all supported languages.
"""
import json
import logging
import os
import tempfile
import threading

from AssetsManager.core.path_resolver import SHARED_DIR
from AssetsManager.core.singleton import ThreadSafeSingleton

_log = logging.getLogger(__name__)


DEFAULT_SYNONYMS = {
    "Texture":       ["贴图", "テクスチャ", "纹理", "材质"],
    "Character":     ["角色", "キャラクター", "人物", "キャラ"],
    "Background":    ["背景", "はいけい", "场景", "背景图"],
    "Reference":     ["参考", "リファレンス", "参考资料"],
    "Model":         ["模型", "モデル", "3D模型"],
    "Rig":           ["骨骼", "リグ", "绑定", "骨架"],
    "Animation":     ["动画", "アニメーション", "動画"],
    "Weapon":        ["武器", "ぶき"],
    "Armor":         ["盔甲", "鎧", "よろい", "装甲"],
    "Environment":   ["环境", "環境", "かんきょう"],
    "UI":            ["界面", "UI素材", "インターフェース"],
    "Icon":          ["图标", "アイコン"],
    "Concept":       ["概念", "コンセプト", "设定", "原画"],
    "Sketch":        ["草图", "スケッチ", "线稿", "草稿"],
    "Illustration":  ["插画", "イラスト", "插图"],
    "Photoreal":     ["写实", "リアル", "照片级"],
    "Stylized":      ["风格化", "スタイライズド", "卡通"],
    "Anime":         ["动漫", "アニメ", "二次元"],
    "PBR":           ["PBR", "物理渲染"],
    "NPR":           ["NPR", "非真实感渲染", "三渲二"],
    "Hair":          ["头发", "髪", "かみ", "毛发"],
    "Face":          ["脸部", "顔", "かお", "面部"],
    "Body":          ["身体", "体", "からだ"],
    "Cloth":         ["服装", "衣服", "服", "ふく"],
    "Shoes":         ["鞋子", "靴", "くつ"],
    "Props":         ["道具", "プロップ", "配件"],
    "Vehicle":       ["载具", "乗り物", "のりもの", "车辆"],
    "Creature":      ["生物", "クリーチャー", "怪物"],
    "Mecha":         ["机甲", "メカ", "机械"],
    "Building":      ["建筑", "建物", "たてもの"],
    "Vegetation":    ["植被", "植物", "しょくぶつ", "树木"],
    "Terrain":       ["地形", "ちけい"],
    "Water":         ["水", "みず", "水面", "液体"],
    "Sky":           ["天空", "空", "そら"],
    "Lighting":      ["灯光", "照明", "しょうめい", "光照"],
    "VFX":           ["特效", "エフェクト", "视觉特效"],
    "Fur":           ["ファー", "毛皮"],
    "Sculpt":        ["雕刻", "スカルプト", "雕塑"],
    "LowPoly":       ["低模", "ローポリ", "低面"],
    "HighPoly":      ["高模", "ハイポリ", "高面"],
    "Retopo":        ["拓扑", "リトポ", "重拓扑"],
    "Bake":          ["烘焙", "ベイク", "贴图烘焙"],
    "UV":            ["UV", "展UV", "UV展开"],
    "GameReady":     ["游戏用", "ゲーム用", "游戏资源"],
    "Cinematic":     ["影视", "シネマティック", "电影"],
    "VR":            ["VR", "虚拟现实"],
    "AR":            ["AR", "增强现实"],
    "VRChat":        ["VRChat", "VRCHAT"],
    "MMD":           ["MMD", "MikuMikuDance"],
    "Blender":       ["Blender"],
    "Maya":          ["Maya"],
    "3dsMax":        ["3dsMax", "3DSMAX"],
    "ZBrush":        ["ZBrush", "ZB"],
    "Substance":     ["Substance", "SP", "SD", "Substance Painter"],
    "Unity":         ["Unity", "Unity3D"],
    "Unreal":        ["Unreal", "UE", "UE4", "UE5", "虚幻"],
    "Houdini":       ["Houdini"],
    "Marvelous":     ["Marvelous", "MD", "Marvelous Designer"],
    "PSD":           ["PSD", "Photoshop", "PS"],
    "FBX":           ["FBX"],
    "OBJ":           ["OBJ"],
    "GLTF":          ["glTF", "GLB"],
    "Vroid":         ["Vroid", "VRoid"],
    "PMX":           ["PMX"],
    "Avatar":        ["头像", "アバター", "化身"],
    "FanArt":        ["同人", "ファンアート", "二创"],
    "Original":      ["原创", "オリジナル"],
    "Commission":    ["委托", "コミッション", "约稿"],
    "WIP":           ["制作中", "WIP", "未完成"],
    "NSFW":          ["NSFW", "R18", "18禁"],
    "SFW":           ["SFW", "全年龄"],
}


class TagLibrary:
    def __init__(self):
        self._path = SHARED_DIR / "tag_library.json"
        self._synonyms: dict[str, list[str]] = {}
        self._reverse: dict[str, str] = {}
        self._loaded = False
        # TagLibrary is shared across threads (e.g. the tag-editor worker
        # removes tags while the UI thread resolves suggestions); guard all
        # state access with a reentrant lock.
        self._lock = threading.RLock()

    def _ensure_loaded(self):
        with self._lock:
            if self._loaded:
                return
            try:
                if self._path.exists():
                    data = json.loads(self._path.read_text(encoding="utf-8"))
                    synonyms = data.get("synonyms") if isinstance(data, dict) else None
                    if not isinstance(synonyms, dict):
                        # Structurally damaged library (missing or odd
                        # 'synonyms' key): fall back to the default tag set
                        # instead of silently operating on an empty library.
                        # No explicit rewrite here; the file is repaired on
                        # the next save (e.g. by _deduplicate_conflicts or a
                        # later mutation).
                        _log.warning(
                            "Tag library %s has no object-valued 'synonyms' "
                            "key; falling back to default tag set",
                            self._path,
                        )
                        self._synonyms = dict(DEFAULT_SYNONYMS)
                    else:
                        self._synonyms = synonyms
                else:
                    self._synonyms = dict(DEFAULT_SYNONYMS)
                    self._save()
            except Exception:
                self._synonyms = dict(DEFAULT_SYNONYMS)
            self._deduplicate_conflicts()
            self._build_reverse()
            self._loaded = True

    def _deduplicate_conflicts(self):
        """Drop alias collisions left in an on-disk library.

        Older tag_library.json files can map one alias to several canonical
        tags (e.g. 场景/毛发); the first canonical wins and the conflicting
        alias is removed so later writes do not silently re-introduce it.
        """
        seen: dict[str, str] = {}
        changed = False
        for canonical in list(self._synonyms):
            aliases = [
                a for a in self._synonyms.get(canonical, [])
                if not self._alias_conflicts(a, canonical, seen)
            ]
            if len(aliases) != len(self._synonyms.get(canonical, [])):
                changed = True
            for alias in aliases:
                seen.setdefault(alias.lower(), canonical)
            self._synonyms[canonical] = aliases
        if changed:
            self._save()

    @staticmethod
    def _alias_conflicts(alias: str, canonical: str, seen: dict[str, str]) -> bool:
        if not alias.strip():
            return True
        key = alias.lower()
        if key in seen and seen[key] != canonical:
            return True
        if key == canonical.lower():
            return True
        return False

    def _build_reverse(self):
        self._reverse.clear()
        for canonical, aliases in self._synonyms.items():
            canonical_lower = canonical.lower()
            self._reverse[canonical_lower] = canonical
            for alias in aliases:
                self._reverse[alias.lower()] = canonical

    def _save(self):
        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                data = json.dumps({"synonyms": self._synonyms}, indent=2, ensure_ascii=False)
                fd, tmp = tempfile.mkstemp(dir=str(self._path.parent),
                                            suffix=".tmp", prefix="taglib_")
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, str(self._path))
            except Exception:
                _log.exception("Failed to save tag library")

    def canonical(self, name: str) -> str:
        """Resolve any tag name (alias or canonical) to its canonical form."""
        with self._lock:
            self._ensure_loaded()
            clean = name.strip().lower()
            return self._reverse.get(clean, name.strip())

    def synonyms_of(self, name: str) -> list[str]:
        """Return all known synonyms for the canonical tag name."""
        with self._lock:
            self._ensure_loaded()
            canonical = self.canonical(name)
            return self._synonyms.get(canonical, [])

    def all_synonyms_text(self, name: str) -> str:
        """Return human-readable synonym list for tooltip display."""
        synonyms = self.synonyms_of(name)
        if not synonyms:
            return ""
        labels = [f"· {s}" for s in synonyms[:12]]
        if len(synonyms) > 12:
            labels.append(f"· ... ({len(synonyms)} total)")
        return "\n".join(labels)

    def all_canonicals(self) -> list[str]:
        """Return all canonical tag names."""
        with self._lock:
            self._ensure_loaded()
            return sorted(self._synonyms.keys(), key=str.lower)

    def add_synonym(self, canonical: str, alias: str) -> bool:
        """Register a new synonym for a canonical tag.

        Returns True when the synonym was newly registered.  Returns False
        (instead of silently overwriting ``_reverse``) when the input is
        empty, the alias is already registered, the alias equals the
        canonical name, or the alias already maps to a different canonical
        tag — mirroring ``_deduplicate_conflicts``/``_build_reverse`` which
        treat "one alias → one canonical" as the library invariant.
        """
        with self._lock:
            self._ensure_loaded()
            canonical = canonical.strip()
            alias = alias.strip()
            if not canonical or not alias:
                return False
            entry = self._synonyms.setdefault(canonical, [])
            if alias in entry:
                return False
            existing = self._reverse.get(alias.lower())
            if existing is not None and existing != canonical:
                return False
            if alias.lower() == canonical.lower():
                return False
            entry.append(alias)
            self._reverse[alias.lower()] = canonical
            self._save()
            return True

    def register_tag(self, canonical: str, synonyms: list[str] | None = None):
        """Register a new canonical tag with optional synonyms."""
        with self._lock:
            self._ensure_loaded()
            canonical = canonical.strip()
            if not canonical:
                return
            if canonical not in self._synonyms:
                self._synonyms[canonical] = list(synonyms or [])
            elif synonyms:
                for s in synonyms:
                    if s.strip() and s.strip() not in self._synonyms[canonical]:
                        self._synonyms[canonical].append(s.strip())
            self._build_reverse()
            self._save()

    def remove_canonical(self, canonical: str):
        """Remove a canonical tag and all its synonyms from the library."""
        with self._lock:
            self._ensure_loaded()
            # Remove from synonyms dict first
            for c in list(self._synonyms):
                if c.lower() == canonical.lower():
                    del self._synonyms[c]
                    break
            self._build_reverse()
            self._save()


def get_library() -> TagLibrary:
    return ThreadSafeSingleton.get(TagLibrary)
