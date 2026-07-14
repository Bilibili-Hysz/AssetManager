"""Tests for core/tag_library.py — canonical tags with multi-language synonyms."""
import json

import pytest


@pytest.fixture
def tag_library(tmp_path):
    """Create a TagLibrary instance with a temporary file."""
    from AssetsManager.core.tag_library import TagLibrary
    lib = TagLibrary()
    lib._path = tmp_path / "tag_library.json"
    lib._loaded = False
    lib._synonyms = {}
    lib._reverse = {}
    return lib


class TestTagLibrary:

    def test_canonical_known_tag(self, tag_library):
        tag_library._synonyms = {"Texture": ["贴图", "テクスチャ"]}
        tag_library._build_reverse()
        tag_library._loaded = True

        assert tag_library.canonical("Texture") == "Texture"
        assert tag_library.canonical("贴图") == "Texture"
        assert tag_library.canonical("テクスチャ") == "Texture"
        assert tag_library.canonical("texture") == "Texture"

    def test_canonical_unknown_tag(self, tag_library):
        tag_library._loaded = True
        tag_library._synonyms = {}
        tag_library._reverse = {}

        # Unknown tags return the input as-is
        assert tag_library.canonical("UnknownTag") == "UnknownTag"

    def test_synonyms_of(self, tag_library):
        tag_library._synonyms = {"Texture": ["贴图", "テクスチャ"]}
        tag_library._build_reverse()
        tag_library._loaded = True

        synonyms = tag_library.synonyms_of("Texture")
        assert "贴图" in synonyms
        assert "テクスチャ" in synonyms

    def test_synonyms_of_unknown(self, tag_library):
        tag_library._loaded = True
        tag_library._synonyms = {}
        tag_library._reverse = {}

        assert tag_library.synonyms_of("Unknown") == []

    def test_all_canonicals(self, tag_library):
        tag_library._synonyms = {"Texture": [], "Model": [], "Animation": []}
        tag_library._loaded = True

        canonicals = tag_library.all_canonicals()
        assert "Animation" in canonicals
        assert "Model" in canonicals
        assert "Texture" in canonicals

    def test_add_synonym(self, tag_library):
        tag_library._synonyms = {"Texture": ["贴图"]}
        tag_library._build_reverse()
        tag_library._loaded = True

        tag_library.add_synonym("Texture", "テクスチャ")
        assert "テクスチャ" in tag_library.synonyms_of("Texture")
        assert tag_library.canonical("テクスチャ") == "Texture"

    def test_add_synonym_duplicate(self, tag_library):
        tag_library._synonyms = {"Texture": ["贴图"]}
        tag_library._build_reverse()
        tag_library._loaded = True

        tag_library.add_synonym("Texture", "贴图")  # Already exists
        assert tag_library.synonyms_of("Texture").count("贴图") == 1

    def test_register_tag_new(self, tag_library):
        tag_library._synonyms = {}
        tag_library._reverse = {}
        tag_library._loaded = True

        tag_library.register_tag("VRChat", ["VRChat", "VRCHAT"])
        assert "VRChat" in tag_library._synonyms
        assert tag_library.canonical("VRCHAT") == "VRChat"

    def test_register_tag_existing_with_synonyms(self, tag_library):
        tag_library._synonyms = {"Texture": ["贴图"]}
        tag_library._build_reverse()
        tag_library._loaded = True

        tag_library.register_tag("Texture", ["テクスチャ"])
        assert "テクスチャ" in tag_library._synonyms["Texture"]
        assert "贴图" in tag_library._synonyms["Texture"]

    def test_remove_canonical(self, tag_library):
        tag_library._synonyms = {"Texture": ["贴图"], "Model": ["模型"]}
        tag_library._build_reverse()
        tag_library._loaded = True

        tag_library.remove_canonical("Texture")
        assert "Texture" not in tag_library._synonyms
        assert "Model" in tag_library._synonyms

    def test_ensure_loaded_creates_defaults(self, tag_library):
        # No file exists, should create defaults
        tag_library._ensure_loaded()
        assert tag_library._loaded is True
        assert len(tag_library._synonyms) > 0
        assert "Texture" in tag_library._synonyms

    def test_ensure_loaded_reads_existing_file(self, tag_library):
        # Write a custom file
        data = {"synonyms": {"CustomTag": ["alias1", "alias2"]}}
        tag_library._path.write_text(json.dumps(data), encoding="utf-8")

        tag_library._ensure_loaded()
        assert tag_library._loaded is True
        assert "CustomTag" in tag_library._synonyms
        assert tag_library.canonical("alias1") == "CustomTag"

    def test_save_creates_file(self, tag_library):
        tag_library._synonyms = {"Test": ["alias"]}
        tag_library._save()
        assert tag_library._path.exists()
        data = json.loads(tag_library._path.read_text(encoding="utf-8"))
        assert "Test" in data["synonyms"]

    def test_all_synonyms_text(self, tag_library):
        tag_library._synonyms = {"Texture": ["贴图", "テクスチャ", "纹理", "材质"]}
        tag_library._build_reverse()
        tag_library._loaded = True

        text = tag_library.all_synonyms_text("Texture")
        assert "· 贴图" in text
        assert "· テクスチャ" in text

    def test_all_synonyms_text_truncation(self, tag_library):
        synonyms = [f"syn{i}" for i in range(20)]
        tag_library._synonyms = {"Big": synonyms}
        tag_library._build_reverse()
        tag_library._loaded = True

        text = tag_library.all_synonyms_text("Big")
        assert "20 total" in text

    def test_all_synonyms_text_unknown(self, tag_library):
        tag_library._loaded = True
        tag_library._synonyms = {}
        tag_library._reverse = {}

        assert tag_library.all_synonyms_text("Unknown") == ""

    def test_add_synonym_empty_inputs(self, tag_library):
        tag_library._synonyms = {}
        tag_library._loaded = True

        tag_library.add_synonym("", "alias")
        tag_library.add_synonym("Tag", "")
        assert len(tag_library._synonyms) == 0

    def test_register_tag_empty(self, tag_library):
        tag_library._synonyms = {}
        tag_library._loaded = True

        tag_library.register_tag("")
        assert len(tag_library._synonyms) == 0
