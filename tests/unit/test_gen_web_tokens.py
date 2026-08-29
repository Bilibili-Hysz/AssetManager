"""S4 generator tests — Web CSS tokens come from Assets/Themes/*.json."""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = ROOT / "scripts" / "gen_web_tokens.py"
_spec = importlib.util.spec_from_file_location("gen_web_tokens", _SCRIPT)
assert _spec is not None and _spec.loader is not None
gen_web_tokens = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = gen_web_tokens
_spec.loader.exec_module(gen_web_tokens)


def test_generated_web_tokens_are_current():
    generated = gen_web_tokens.generate_css()
    on_disk = gen_web_tokens.OUTPUT_PATH.read_text(encoding="utf-8")
    assert generated == on_disk


def test_generated_manifest_is_current():
    manifest = gen_web_tokens.generate_manifest()
    on_disk = gen_web_tokens.MANIFEST_PATH.read_text(encoding="utf-8")
    assert manifest == on_disk


def test_generated_css_contains_dark_and_light_blocks():
    generated = gen_web_tokens.generate_css()
    assert ":root {" in generated
    assert "html.light {" in generated
    assert "--color-accent:" in generated
    assert "--color-bg:" in generated
    assert "color-scheme: dark;" in generated
    assert "color-scheme: light;" in generated


def test_generator_reads_theme_json_sources():
    dark = gen_web_tokens._load_colors(gen_web_tokens.DARK_THEME)
    light = gen_web_tokens._load_colors(gen_web_tokens.LIGHT_THEME)
    assert dark["accent"]
    assert light["accent"]
    assert dark["base"] != light["base"]


def test_every_shipped_theme_gets_a_full_identity_block():
    """All 24 shipped palettes emit a complete html[data-am-theme] block so
    the WebUI can follow the owner's theme identity (A1)."""
    themes = gen_web_tokens.iter_themes()
    assert len(themes) == 24
    generated = gen_web_tokens.generate_css()
    for theme in themes:
        selector = f'html[data-am-theme="{theme["_slug"]}"]'
        assert selector + " {" in generated, selector
        block = generated.split(selector + " {", 1)[1].split("}", 1)[0]
        for css_var in gen_web_tokens.COLOR_MAP:
            assert f"  {css_var}: " in block, (selector, css_var)
        assert "--color-overlay:" in block
        expected_scheme = "light" if theme.get("dark") is not True else "dark"
        assert f"color-scheme: {expected_scheme};" in block


def test_theme_slugs_are_kebab_case_and_unique():
    themes = gen_web_tokens.iter_themes()
    slugs = [theme["_slug"] for theme in themes]
    assert len(slugs) == len(set(slugs)), "duplicate slugs"
    for slug in slugs:
        assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug), slug


def test_kebab_case_slugify_examples():
    slugify = gen_web_tokens.theme_slug
    assert slugify("Rose Pine") == "rose-pine"
    assert slugify("Navy") == "navy"
    assert slugify("  Mint  ") == "mint"


def test_manifest_matches_css_theme_set():
    """The TS manifest and the CSS identity blocks describe the same set."""
    manifest = gen_web_tokens.generate_manifest()
    generated = gen_web_tokens.generate_css()
    themes = gen_web_tokens.iter_themes()
    for theme in themes:
        entry = f"{{ name: '{theme['name']}', slug: '{theme['_slug']}', dark: {str(theme.get('dark') is not False).lower()} }},"
        assert entry in manifest, entry
        assert f'html[data-am-theme="{theme["_slug"]}"]' in generated
    assert manifest.count("\n  { name:") == len(themes)


def test_identity_blocks_never_emit_accent_text():
    """--color-accent-text stays owned by index.css (per light/dark mode);
    a theme-palette value here would regress the 4.5:1 text contrast fix."""
    generated = gen_web_tokens.generate_css()
    assert "--color-accent-text" not in generated
