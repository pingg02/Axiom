"""
Evidence ledger — tracks tool call receipts for delivery-first verification.

Maintains an append-only list of Receipts with file-level read/write tracking
to support stale anchor edit detection and delivery criteria.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class Receipt:
    """Record of one tool call in the current turn. Mirrors Go's evidence.Receipt."""

    tool_name: str
    args: str = ""
    success: bool = True
    command: str = ""
    step: str = ""
    paths: list[str] = field(default_factory=list)
    read: bool = False
    write: bool = False
    mutation: bool = False


class Ledger:
    """Append-only receipt ledger for one turn. Mirrors Go's evidence.Ledger."""

    def __init__(self) -> None:
        self.receipts: list[Receipt] = []

    def record(self, receipt: Receipt) -> None:
        self.receipts.append(receipt)

    def latest_write_index(self, paths: list[str]) -> tuple[int, bool]:
        """Last successful write touching any of the given paths.

        Mirrors Go's LatestSuccessfulWriteIndex().
        """
        wanted = set(paths)
        latest = -1
        for i, r in enumerate(self.receipts):
            if r.success and r.write:
                for p in r.paths:
                    if p in wanted:
                        latest = i
        return latest, latest >= 0

    def has_anchor_refresh_after(self, paths: list[str], after: int) -> bool:
        """Was there a full read_file (anchor refresh) after the given index?

        Mirrors Go's HasSuccessfulAnchorRefreshReadAfter().
        Only counts read_file without offset/limit (full file reads).
        """
        wanted = set(paths)
        for i in range(after + 1, len(self.receipts)):
            r = self.receipts[i]
            if r.success and r.tool_name == "read_file" and r.read:
                # Anchor refresh = read_file without offset/limit
                args = json.loads(r.args) if r.args else {}
                if "offset" not in args and "limit" not in args:
                    for p in r.paths:
                        if p in wanted:
                            return True
        return False

    def stale_anchor_edit_blocked(self, tool_name: str, args_json: str) -> str | None:
        """Check if an edit_file/delete_range is blocked by stale anchor.

        Returns a block message or None. Mirrors Go's staleAnchorEditBlock().
        """
        if tool_name not in ("edit_file", "delete_range"):
            return None

        try:
            args = json.loads(args_json) if args_json else {}
        except json.JSONDecodeError:
            return None

        path = args.get("path", args.get("old_string", ""))
        if not path:
            return None

        write_idx, found = self.latest_write_index([path])
        if not found:
            return None  # never written → safe

        if self.has_anchor_refresh_after([path], write_idx):
            return None  # re-read after write → safe

        return (
            f"[fresh read required] '{tool_name}' targets {path}, "
            f"which was already modified earlier this turn. "
            f"Re-read with read_file before editing."
        )
