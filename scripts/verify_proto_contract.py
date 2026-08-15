#!/usr/bin/env python3
"""gRPC contract gate: checked-in Python pb2 must match security.proto.

The Java side regenerates protobuf classes from security.proto at build time,
but the Python side ships a hand-committed generated file
(reasonix/grpc/security_pb2.py). If security.proto changes and the Python file
is not regenerated, Java and Python silently disagree at runtime. This gate
parses security.proto as the single source of truth and asserts the Python
descriptor matches field-for-field and method-for-method.

Exit 0 when consistent; exit 1 with a diff summary otherwise.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "reasonix-py"))

PROTO_PATH = ROOT / "reasonix-java" / "src" / "main" / "proto" / "security.proto"

FIELD_RE = re.compile(r"^\s{2}(?P<type>[\w.]+)\s+(?P<name>\w+)\s*=\s*(?P<number>\d+);")
RPC_RE = re.compile(r"^\s{2}rpc\s+(?P<name>\w+)\s*\(")


def parse_proto(text: str) -> tuple[dict[str, dict[str, int]], list[str]]:
    """Return {message_name: {field_name: number}} and the list of rpc names."""
    messages: dict[str, dict[str, int]] = {}
    rpcs: list[str] = []
    depth = 0
    current: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        message_match = re.match(r"^message\s+(\w+)\s*\{", stripped)
        if message_match:
            current = message_match.group(1)
            messages.setdefault(current, {})
            depth = 1
            continue
        service_match = re.match(r"^service\s+(\w+)\s*\{", stripped)
        if service_match:
            current = None
            depth = 1
            continue
        if stripped == "}":
            depth = 0
            current = None
            continue
        if current is not None:
            field = FIELD_RE.match(line)
            if field and field.group("type") != "enum":
                messages[current][field.group("name")] = int(field.group("number"))
        rpc = RPC_RE.match(line)
        if rpc:
            rpcs.append(rpc.group("name"))
    return messages, rpcs


def main() -> int:
    from reasonix.grpc import security_pb2

    proto_text = PROTO_PATH.read_text(encoding="utf-8")
    expected_messages, expected_rpcs = parse_proto(proto_text)

    problems: list[str] = []
    descriptor = security_pb2.DESCRIPTOR

    for message_name, expected_fields in expected_messages.items():
        message_desc = descriptor.message_types_by_name.get(message_name)
        if message_desc is None:
            problems.append(f"message {message_name}: missing from Python pb2")
            continue
        actual_fields = {f.name: f.number for f in message_desc.fields}
        for field_name, field_number in expected_fields.items():
            actual = actual_fields.get(field_name)
            if actual != field_number:
                problems.append(
                    f"message {message_name}.{field_name}: proto={field_number}, "
                    f"pb2={actual if actual is not None else 'missing'}"
                )

    service_desc = descriptor.services_by_name.get("SecurityService")
    if service_desc is None:
        problems.append("service SecurityService: missing from Python pb2")
    else:
        actual_rpcs = set(service_desc.methods_by_name)
        for rpc in expected_rpcs:
            if rpc not in actual_rpcs:
                problems.append(f"rpc {rpc}: missing from Python pb2")

    if problems:
        print(f"[FAIL] Python pb2 drifted from {PROTO_PATH.name}:")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print(
        f"[OK] Python pb2 matches security.proto: "
        f"{len(expected_messages)} messages, {len(expected_rpcs)} rpcs"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
