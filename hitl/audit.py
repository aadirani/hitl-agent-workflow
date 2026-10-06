"""Append-only, hash-chained audit log (tamper-evident).

Each entry stores the hash of the previous entry. Changing, deleting or reordering any
past entry breaks every hash after it, so verify() can tell the log was altered.
"""

import hashlib
import json
from datetime import datetime, timezone

GENESIS = "0" * 64


def _digest(prev_hash, body):
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((prev_hash + canonical).encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, path=None, clock=None):
        self.entries = []
        self.path = path
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
        if path:
            open(path, "w", encoding="utf-8").close()  # start a fresh log file

    def record(self, ticket_id, event, **details):
        prev = self.entries[-1]["hash"] if self.entries else GENESIS
        body = {"seq": len(self.entries) + 1, "time": self.clock(), "ticket": ticket_id,
                "event": event, "details": details, "prev_hash": prev}
        entry = dict(body, hash=_digest(prev, body))
        self.entries.append(entry)
        if self.path:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry


def verify(entries):
    """Return (ok, message). Checks every link of the chain."""
    prev = GENESIS
    for i, entry in enumerate(entries, start=1):
        body = {k: v for k, v in entry.items() if k != "hash"}
        if entry.get("prev_hash") != prev or entry.get("seq") != i:
            return False, f"chain broken at entry {i}"
        if _digest(prev, body) != entry.get("hash"):
            return False, f"entry {i} was modified"
        prev = entry["hash"]
    return True, f"{len(entries)} entries, chain intact"


def load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
