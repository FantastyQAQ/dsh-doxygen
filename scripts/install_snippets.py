#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Install the doxygen-comment snippets into a VS Code style IDE.

Merges <skill>/assets/cpp.json into <IDE user dir>\\snippets\\cpp.json.
Windows Explorer and VS Code both read that file as UTF-8, and VS Code accepts
plain JSON here (JSONC with comments is also tolerated).

Dry run by default: nothing is written unless --apply is passed.

Usage:
    python install_snippets.py                            # detect IDEs, show merge plan
    python install_snippets.py --list                     # only list detected targets
    python install_snippets.py --apply --create           # create cpp.json if absent
    python install_snippets.py --target <file> --apply    # explicit target
    python install_snippets.py --force --apply            # overwrite same-name keys
    python install_snippets.py --uninstall --apply        # remove what this skill installed
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SKILL_DIR = Path(__file__).resolve().parent.parent
SOURCE = SKILL_DIR / "assets" / "cpp.json"
TARGET_NAME = "cpp.json"

# (label, user dir relative to %APPDATA%)
IDE_ROOTS = [
    ("CodeBuddy CN", r"CodeBuddy CN\User"),
    ("VS Code", r"Code\User"),
    ("CodeBuddy", r"CodeBuddy\User"),
    ("Cursor", r"Cursor\User"),
    ("Windsurf", r"Windsurf\User"),
]


def detect() -> list[tuple[str, Path, bool]]:
    """Return (label, snippets_dir, snippets_dir_exists)."""
    appdata = os.environ.get("APPDATA")
    out: list[tuple[str, Path, bool]] = []
    if not appdata:
        return out
    for label, rel in IDE_ROOTS:
        user_dir = Path(appdata) / rel
        snippets_dir = user_dir / "snippets"
        out.append((label, snippets_dir, user_dir.exists()))
    return out


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig") as fh:
        text = fh.read().strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            "ERROR: %s is not valid JSON (%s).\n"
            "       If it contains // comments (JSONC), strip them or merge manually."
            % (path, exc)
        )
    if not isinstance(data, dict):
        raise SystemExit("ERROR: %s top level is not an object" % path)
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description="Install doxygen-comment IDE snippets (dry run by default).")
    ap.add_argument("--apply", action="store_true", help="actually write (default: dry run)")
    ap.add_argument("--create", action="store_true", help="create the snippets file if it does not exist")
    ap.add_argument("--force", action="store_true", help="overwrite keys that already exist")
    ap.add_argument("--target", help="explicit target file path")
    ap.add_argument("--uninstall", action="store_true", help="remove the snippets this skill installed")
    ap.add_argument("--list", action="store_true", help="only list detected targets")
    args = ap.parse_args()

    if not SOURCE.exists():
        raise SystemExit("ERROR: snippet source not found: %s" % SOURCE)
    incoming = load_json(SOURCE)
    prefixes = sorted(p for p in (v.get("prefix") for v in incoming.values() if isinstance(v, dict)) if p)
    print("source  : %s" % SOURCE)
    print("entries : %d" % len(incoming))
    print("prefixes: %s" % ", ".join(prefixes))
    print("")

    if args.target:
        target = Path(args.target).expanduser()
        candidates = [("--target", target.parent, True)]
    else:
        candidates = detect()
        if not candidates:
            raise SystemExit("ERROR: %%APPDATA%% not set; pass --target explicitly")

    print("detected IDEs:")
    present = []
    for label, snippets_dir, exists in candidates:
        target = snippets_dir / TARGET_NAME
        state = "user dir OK" if exists else "not installed"
        tstate = "snippet file exists" if target.exists() else "snippet file missing"
        print("  [%-13s] %-14s %-21s %s" % (label, state, tstate, target))
        if exists:
            present.append((label, snippets_dir, target))
            others = sorted(p.name for p in snippets_dir.glob("*.json") if p.name != TARGET_NAME) if snippets_dir.exists() else []
            if others:
                print("  %-15s  other snippet files here (scope differs): %s" % ("", ", ".join(others)))

    if args.list:
        return 0
    if not present:
        print("")
        print("no IDE user directory found -- nothing to do")
        return 1

    rc = 0
    for label, snippets_dir, target in present:
        print("")
        if not target.exists():
            if args.uninstall:
                print("target  : [%s] %s -- MISSING, nothing to do" % (label, target))
                continue
            if not args.create:
                print("target  : [%s] %s -- MISSING (add --create to create it)" % (label, target))
                rc = 1
                continue
            if not args.apply:
                print("target  : [%s] %s -- would be CREATED" % (label, target))
                print("          + %d entries: %s" % (len(incoming), ", ".join(incoming)))
                print("          DRY RUN -- nothing written. Re-run with --apply --create to write.")
                continue
            snippets_dir.mkdir(parents=True, exist_ok=True)

        current = load_json(target)

        if args.uninstall:
            removed = [k for k in incoming if k in current]
            print("target  : [%s] %s" % (label, target))
            print("  will remove   : %d" % len(removed))
            for key in removed:
                print("      - %s" % key)
            if not args.apply:
                print("  DRY RUN -- nothing written. Re-run with --apply to write.")
                continue
            if not removed:
                print("  nothing to do.")
                continue
            for key in removed:
                del current[key]
            backup = target.with_name(target.name + ".bak-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
            shutil.copy2(target, backup)
            with target.open("w", encoding="utf-8", newline="\n") as fh:
                json.dump(current, fh, ensure_ascii=False, indent="\t")
                fh.write("\n")
            print("  backup        : %s" % backup)
            print("  written       : %s" % target)
            continue

        pre_count = len(current)
        added, skipped = [], []
        for key, value in incoming.items():
            if key in current and not args.force:
                skipped.append(key)
            else:
                added.append(key)
                current[key] = value

        print("target  : [%s] %s" % (label, target))
        print("  existing keys : %d" % pre_count)
        print("  will add      : %d" % len(added))
        for key in added:
            print("      + %s" % key)
        if skipped:
            print("  already there : %d (use --force to overwrite)" % len(skipped))
            for key in skipped:
                print("      = %s" % key)

        if not args.apply:
            print("  DRY RUN -- nothing written. Re-run with --apply to write.")
            continue
        if not added:
            print("  nothing to do.")
            continue

        if target.exists():
            backup = target.with_name(target.name + ".bak-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
            shutil.copy2(target, backup)
            print("  backup        : %s" % backup)
        with target.open("w", encoding="utf-8", newline="\n") as fh:
            json.dump(current, fh, ensure_ascii=False, indent="\t")
            fh.write("\n")
        print("  written       : %s" % target)
        print("  reload the IDE window to pick up the snippets (no restart required).")

    return rc


if __name__ == "__main__":
    sys.exit(main())
