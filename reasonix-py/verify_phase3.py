"""Verify Phase 3 — all built-in tools registered correctly."""
import sys

from reasonix.boot import _default_tools

reg = _default_tools()
snap = reg.snapshot()
names = sorted(t.name for t in snap.all())
print(f"Total tools: {len(names)}")
print(f"Tools: {names}")

expected = {
    "ask", "bash", "complete_step", "edit_file",
    "glob", "grep", "read_file", "task",
    "todo_write", "web_fetch", "write_file",
}
missing = expected - set(names)
if missing:
    print(f"MISSING: {missing}")
    sys.exit(1)

print("All expected tools registered OK")
