"""Tag library — Pixiv-style canonical tags with multi-language synonyms.

All tag lookups pass through the library: user input → canonical name.
Hover tooltips show synonyms in all supported languages.
"""
import json
import logging
import os
import tempfile

from AssetsManager.core.database import SHARED_DIR
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
    "Environment":   ["环境", "環境", "かんきょう", "场景"],
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
    "Fur":           ["毛发", "ファー", "毛皮"],
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

    def _ensure_loaded(self):
        if self._loaded:
            return
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._synonyms = data.get("synonyms", {})
            else:
                self._synonyms = dict(DEFAULT_SYNONYMS)
                self._save()
        except Exception:
            self._synonyms = dict(DEFAULT_SYNONYMS)
        self._build_reverse()
        self._loaded = True

    def _build_reverse(self):
        self._reverse.clear()
        for canonical, aliases in self._synonyms.items():
            canonical_lower = canonical.lower()
            self._reverse[canonical_lower] = canonical
            for alias in aliases:
                self._reverse[alias.lower()] = canonical

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.dumps({"synonyms": self._synonyms}, indent=2, ensure_ascii=False)
            fd, tmp = tempfile.mkstemp(dir=str(self._path.parent),
                                        suffix=".tmp", prefix="taglib_")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data)
            os.replace(tmp, str(self._path))
        except Exception:
            _log.exception("Failed to save tag library")

    def canonical(self, name: str) -> str:
        """Resolve any tag name (alias or canonical) to its canonical form."""
        self._ensure_loaded()
        clean = name.strip().lower()
        return self._reverse.get(clean, name.strip())

    def synonyms_of(self, name: str) -> list[str]:
        """Return all known synonyms for the canonical tag name."""
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
        self._ensure_loaded()
        return sorted(self._synonyms.keys(), key=str.lower)

    def add_synonym(self, canonical: str, alias: str):
        """Register a new synonym for a canonical tag."""
        self._ensure_loaded()
        canonical = canonical.strip()
        alias = alias.strip()
        if not canonical or not alias:
            return
        entry = self._synonyms.setdefault(canonical, [])
        if alias not in entry:
            entry.append(alias)
            self._reverse[alias.lower()] = canonical
            self._save()

    def register_tag(self, canonical: str, synonyms: list[str] | None = None):
        """Register a new canonical tag with optional synonyms."""
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
