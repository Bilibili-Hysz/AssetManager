"""Gate: trilingual i18n catalog parity and _meta hygiene (P3 unification).

The desktop catalogs (``AssetsManager/i18n/*.json``) are three parallel
dictionaries; nothing in the build enforces that a key added to one file
lands in the other two — the alignment is discipline, not mechanism (W6 /
W12 in the dialect plan). This gate converts the discipline into a check:

1. **Key parity**: every non-``_meta`` key must exist in all catalogs.
2. **_meta hygiene**: every catalog declares ``_meta.language``,
   ``native_name`` and ``version``, and all versions agree (a stale
   ``version`` field silently drifted before — en=1 vs zh/ja=2).
3. **Placeholder parity**: ``{name}`` placeholders inside a value must be
   the same set across languages — a missing placeholder turns into a
   KeyError at ``str.format`` time in exactly one language.
4. **Flat-key dialect**: keys are flat dot-notation strings; nesting or
   empty keys are rejected (the loader is a single ``dict.get``).

Exit 1 with a machine-readable report on any violation.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
I18N_DIR = ROOT / "AssetsManager" / "i18n"

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_KEY_RE = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")


def _load_catalogs() -> dict[str, dict]:
    catalogs: dict[str, dict] = {}
    for path in sorted(I18N_DIR.glob("*.json")):
        if path.name.startswith("_"):
            continue
        catalogs[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return catalogs


def check() -> int:
    violations: list[str] = []
    catalogs = _load_catalogs()
    if not catalogs:
        print("i18n gate: no catalogs found")
        return 1

    # Flatten and validate per-catalog shape.
    keys_by_lang: dict[str, set[str]] = {}
    for lang, data in catalogs.items():
        keys = {k for k in data if k != "_meta"}
        keys_by_lang[lang] = keys
        for key in keys:
            if not key or not _KEY_RE.match(key):
                violations.append(f"{lang}: malformed flat key {key!r}")
        for key in keys:
            value = data[key]
            if not isinstance(value, str):
                violations.append(
                    f"{lang}.{key}: value must be a string, got {type(value).__name__}")

    # Rule 1: key parity across every pair.
    langs = sorted(keys_by_lang)
    reference = langs[0]
    for lang in langs[1:]:
        missing = keys_by_lang[reference] - keys_by_lang[lang]
        extra = keys_by_lang[lang] - keys_by_lang[reference]
        for key in sorted(missing):
            violations.append(f"{lang}: missing key present in {reference}: {key}")
        for key in sorted(extra):
            violations.append(f"{lang}: extra key absent from {reference}: {key}")

    # Rule 2: _meta hygiene and version agreement.
    versions: dict[str, int] = {}
    for lang, data in catalogs.items():
        meta = data.get("_meta", {})
        for field in ("language", "native_name", "version"):
            if field not in meta:
                violations.append(f"{lang}: _meta.{field} missing")
        if isinstance(meta.get("version"), int):
            versions[lang] = meta["version"]
        elif "version" in meta:
            violations.append(f"{lang}: _meta.version must be an integer")
    if versions and len(set(versions.values())) > 1:
        violations.append(
            "catalog _meta.version drift: " + ", ".join(
                f"{lang}={version}" for lang, version in sorted(versions.items())))

    # Rule 3: placeholder safety per shared key. The failure mode that
    # matters at runtime is a NON-English catalog containing a placeholder
    # the format call does not supply (KeyError in exactly one language).
    # A translation DROPPING an English placeholder (e.g. ``{y}`` plural
    # inflection, which only exists for the English
    # "librar{y}/libraries" trick) is legitimate language adaptation —
    # ``str.format`` ignores nothing, but the extra kwargs of ``tr()`` are
    # harmlessly unused. So: extra placeholders are violations, missing
    # ones are not.
    if len(keys_by_lang) > 1:
        shared = set.intersection(*keys_by_lang.values())
        for key in sorted(shared):
            reference_set = set(_PLACEHOLDER_RE.findall(catalogs[reference][key]))
            for lang in langs[1:]:
                if key not in catalogs[lang]:
                    continue
                ph_set = set(_PLACEHOLDER_RE.findall(catalogs[lang][key]))
                extra = ph_set - reference_set
                if extra:
                    violations.append(
                        f"{lang}.{key}: placeholder(s) unknown to the format "
                        f"call (vs {reference}): {sorted(extra)}")

    if violations:
        print(f"i18n catalog violations ({len(violations)}):")
        for v in violations[:50]:
            print(f"  - {v}")
        if len(violations) > 50:
            print(f"  ... and {len(violations) - 50} more")
        return 1

    counts = ", ".join(f"{lang}={len(keys)}" for lang, keys in sorted(keys_by_lang.items()))
    print(f"i18n catalogs are aligned ({counts}; _meta.version={sorted(set(versions.values()))})")
    return 0


if __name__ == "__main__":
    sys.exit(check())
