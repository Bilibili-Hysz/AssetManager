"""Gate: repository session-binding dialect hygiene (D1 unification).

The repository family converges on one dialect (2026-09-04, plan
``docs/plans/dialect-unification-plan-2026-09-04.md`` P1):

- Session binding flows through ``_SessionBoundRepository`` (strict
  ``require_library_session`` token + captured ``RootIdentity``).
- Duck-typed session-root lookups (``session.root`` / ``session.root_str``
  probed at bind time) and hand-rolled ``Path(session.root).resolve()``
  comparisons are gone; the canonical resolution is
  ``session.context.root_identity``.
- SAVEPOINT writes go through the base ``_write_scope`` (or asset_index's
  ``transaction_scope``); no ad-hoc SAVEPOINT strings elsewhere.

Rules:
1. ``repositories/*.py`` must not define a local ``_session_root`` or
   ``_require_session_contract`` (they exist once, in ``_common``).
2. Session classes may keep ``root``/``root_str`` *properties*; what is
   forbidden is repositories reading them to derive identity at bind time —
   matched as ``getattr(session, "root"...)`` probes.
3. Raw-only repositories (no ``for_session``) must appear in the ledger
   below; the list shrinks monotonically (ratchet, never grows).
4. No repository outside ``_common.py`` may execute a bare ``SAVEPOINT``
   SQL string (asset_index ``transaction_scope`` is allowlisted via the
   same marker every other write uses — the base ``_write_scope`` — plus
   its own ``BEGIN``; see the allowlist below for the retained local
   transaction scopes).

Exit 1 with a machine-readable report on any violation.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPOS = ROOT / "AssetsManager" / "repositories"

# Repositories still on the raw-connection path (no for_session). This list
# is a ratchet: remove entries as they are onboarded, never add new ones.
# Each remaining entry is an audited decision (2026-09-05 dialect audit) —
# the full "why raw / when revisit" rationale lives in the repository module
# docstring; keep it current when adding or removing entries.
RAW_ONLY_LEDGER = [
    # Single-row projection cache for one root_key; the sole consumer
    # (gallery/_persistence.py) is root-parameter and stateless-per-call.
    # Raw until GalleryService itself becomes session-scoped.
    "gallery_home_repository.py",
    # Token revocation is an auth-host concept: digests, no library paths;
    # AuthService owns one host connection shared across sessions.
    "revoked_token_repository.py",
    # Versioned cache keys (v2/v3/legacy coexist) + a cross-repository
    # commit=False staging contract settled by an unguarded public commit.
    "thumbnail_repository.py",
]

# Light-dialect repositories (own local for_session but still duck-type the
# session root). Ratchet: onboard to the strict base and remove from here.
LIGHT_DIALECT_LEDGER = [
    "plugin_metadata_repository.py",  # own light binding; P1-5 onboarding
]

# Local savepoint contexts retained by design (documented in the plan §P1).
SAVEPOINT_ALLOWLIST = {
    # asset_index transaction_scope: external savepoint names + BEGIN guard —
    # deliberately NOT the base _write_scope (see repository docstring).
    "asset_index_repository.py",
    # share/auth init_table compatibility shims predate the base scope and
    # own their schema DDL savepoints.
    "share_repository.py",
    "auth_repository.py",
    "revoked_token_repository.py",
    "free_download_quota_repository.py",
}

FORBIDDEN_HELPERS = ("_session_root", "_require_session_contract")


_STRICT_BASES = {"_SessionBoundRepository", "_CommerceRepository"}


def _is_strict_dialect(tree: ast.AST) -> bool:
    """A repository is strict-dialect when it inherits the shared base.

    ``_CommerceRepository`` is the retained legacy alias of the same base
    (see _common), so subclasses of either count as strict.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                name = base.id if isinstance(base, ast.Name) else (
                    base.attr if isinstance(base, ast.Attribute) else None)
                if name in _STRICT_BASES:
                    return True
    return False


def _class_defines_for_session(tree: ast.AST) -> bool:
    """Light-dialect marker: a local for_session classmethod exists."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "for_session":
            return True
    return False


def check() -> int:
    violations: list[str] = []

    for path in sorted(REPOS.glob("*.py")):
        rel = path.name
        if rel.startswith("_") or rel == "__init__.py":
            continue
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)

        # Rule 1: no local dialect helpers
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in FORBIDDEN_HELPERS:
                violations.append(
                    f"{rel}: defines local dialect helper "
                    f"'{node.name}' — import from _common instead")

        # Rule 2: no duck-typed session-root probes in repositories
        # (scan code only — docstrings may describe the history)
        code_only = "\n".join(
            seg for seg in src.split("\n")
            if not seg.lstrip().startswith(("#", '"', "'"))
        )
        for match in re.finditer(
            r'getattr\(\s*session\s*,\s*"(root|root_str)"', code_only
        ):
            line = src[: match.start()].count("\n") + 1
            violations.append(
                f"{rel}:{line}: duck-typed session root probe — use "
                f"session.context.root_identity (strict dialect)")

        # Rule 2b: no Path(session.root) hand-rolled comparisons (code only)
        for match in re.finditer(r"Path\(session\.root\)", code_only):
            line = src[: match.start()].count("\n") + 1
            violations.append(
                f"{rel}:{line}: hand-rolled Path(session.root) comparison — "
                f"use session.context.root_identity")

        # Rule 3: binding-mode ratchet. Strict (inherits the base) or
        # light (local for_session, duck-typed — legacy, tracked by rule 2)
        # are binding modes; anything else must sit in the raw-only ledger.
        strict = _is_strict_dialect(tree)
        binds = strict or _class_defines_for_session(tree)
        if not binds and rel not in RAW_ONLY_LEDGER:
            violations.append(
                f"{rel}: no for_session and not in RAW_ONLY_LEDGER — either "
                f"onboard the strict dialect or extend the ledger with a reason")
        if rel in RAW_ONLY_LEDGER and binds:
            violations.append(
                f"{rel}: has session binding but still listed in RAW_ONLY_LEDGER "
                f"— remove the ledger entry")

        # Rule 4: no ad-hoc SAVEPOINT outside the base/allowlisted scopes
        if rel not in SAVEPOINT_ALLOWLIST:
            for match in re.finditer(r'["\']SAVEPOINT ', src):
                line = src[: match.start()].count("\n") + 1
                violations.append(
                    f"{rel}:{line}: bare SAVEPOINT string — route through "
                    f"_SessionBoundRepository._write_scope")

    if violations:
        print("repository dialect violations:")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("repository dialects are current")
    print(f"  strict-dialect repositories: "
          f"{len([p for p in REPOS.glob('*.py') if not p.name.startswith('_') and p.name != '__init__.py']) - len(RAW_ONLY_LEDGER)}")
    print(f"  raw-only ledger (ratchet): {len(RAW_ONLY_LEDGER)}")
    return 0


if __name__ == "__main__":
    sys.exit(check())
