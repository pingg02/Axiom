#!/usr/bin/env python3
"""Repository secret scan gate (对标 DSH repo-invariant gates).

Scans every Git-tracked text file for high-confidence credential patterns.
Generated protobuf files, lockfiles, and binary assets are skipped; a "value"
that is only an uppercase env-var NAME (e.g. AXIOM_COMPATIBLE_API_KEY) is not
a credential.

Exit 0 when clean; exit 1 with a hit list otherwise.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SKIP_SUFFIXES = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".pdf",
    ".lock",  # package-lock.json etc.
    ".pyi",
)
# Generated protobuf payloads contain serialized bytes that can false-positive.
SKIP_PARTS = ("reasonix/grpc/security_pb2",)

PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    re.compile(
        r'(?i)(?:api[_-]?key|apikey|secret|token)\s*[=:]\s*["\'][A-Za-z0-9+/=_.-]{20,}["\']'
    ),
]

# An env-var NAME (uppercase letters/digits/underscore) is a reference, not a key.
_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]+$")
# Values that are obviously test/example placeholders, never real credentials.
_PLACEHOLDER_RE = re.compile(
    r"(?i)(test|fake|example|dummy|placeholder|not-a-real|sample|your[_-]?key)"
)


def tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return [ROOT / line for line in out.stdout.splitlines() if line.strip()]


def main() -> int:
    hits: list[tuple[str, int, str]] = []
    for path in tracked_files():
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        if any(part in path.as_posix() for part in SKIP_PARTS):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pattern in PATTERNS:
                match = pattern.search(line)
                if not match:
                    continue
                value = match.group(0)
                if _NAME_RE.match(value.strip("\"'")):
                    continue
                if _PLACEHOLDER_RE.search(value):
                    continue
                hits.append((path.as_posix().replace("\\", "/"), lineno, line.strip()[:160]))
                break

    if hits:
        print(f"[FAIL] {len(hits)} potential credential(s) found:")
        for rel_path, lineno, line in hits:
            print(f"  {rel_path}:{lineno}: {line}")
        return 1
    print("[OK] no high-confidence credential patterns in tracked files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
