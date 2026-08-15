#!/usr/bin/env python3
"""Repository version consistency gate (对标 DSH verify-package-invariants).

Asserts that every in-repo version definition equals one another:
- reasonix-py/pyproject.toml                 (project.version)
- reasonix-py/reasonix/__init__.py           (__version__)
- reasonix-java/pom.xml                      (reasonix-security version)
- desktop/electron/package.json              (version)
- desktop/python-frontend/package.json       (version)
- desktop/electron/preload.js                (version field)
- desktop/installer.nsi                      (PRODUCT_VERSION)

Exit 0 when all agree; exit 1 and print the mismatch otherwise.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def version_sources() -> list[tuple[str, str]]:
    sources: list[tuple[str, str]] = []

    pyproject = read(ROOT / "reasonix-py" / "pyproject.toml")
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    sources.append(("reasonix-py/pyproject.toml", match.group(1) if match else ""))

    init = read(ROOT / "reasonix-py" / "reasonix" / "__init__.py")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', init, re.MULTILINE)
    sources.append(("reasonix-py/reasonix/__init__.py", match.group(1) if match else ""))

    pom = read(ROOT / "reasonix-java" / "pom.xml")
    match = re.search(
        r"<artifactId>reasonix-security</artifactId>\s*<version>([^<]+)</version>",
        pom,
    )
    sources.append(("reasonix-java/pom.xml", match.group(1) if match else ""))

    for rel in ("desktop/electron/package.json", "desktop/python-frontend/package.json"):
        data = json.loads(read(ROOT / rel))
        sources.append((rel, str(data.get("version", ""))))

    preload = read(ROOT / "desktop" / "electron" / "preload.js")
    match = re.search(r"version:\s*'([^']+)'", preload)
    sources.append(("desktop/electron/preload.js", match.group(1) if match else ""))

    nsi = read(ROOT / "desktop" / "installer.nsi")
    match = re.search(r'!define PRODUCT_VERSION\s+"([^"]+)"', nsi)
    sources.append(("desktop/installer.nsi", match.group(1) if match else ""))

    return sources


def main() -> int:
    sources = version_sources()
    missing = [rel for rel, value in sources if not value]
    if missing:
        print(f"[FAIL] could not read version from: {', '.join(missing)}")
        return 1

    expected = sources[0][1]
    bad = [(rel, value) for rel, value in sources if value != expected]
    if bad:
        print(f"[FAIL] version drift: expected {expected!r} everywhere")
        for rel, value in bad:
            print(f"  {rel}: {value!r}")
        return 1

    print(f"[OK] all {len(sources)} version sources agree: {expected}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
