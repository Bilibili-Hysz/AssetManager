"""S4 generator tests — Web CSS tokens come from Assets/Themes/*.json."""
from __future__ import annotations

import importlib.util
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
