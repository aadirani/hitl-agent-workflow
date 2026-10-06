"""Command line:
  python -m hitl run --tickets examples/tickets.json --approvals examples/approvals.json --audit audit.jsonl
  python -m hitl run --interactive --name omar --role it-manager      (approve at the terminal)
  python -m hitl verify-audit audit.jsonl
"""

import argparse
import json
import sys
from pathlib import Path

from . import audit as audit_mod
from .tools import Environment
from .workflow import ConsoleApprover, ScriptedApprover, process


def cmd_run(a):
    tickets = json.loads(Path(a.tickets).read_text(encoding="utf-8"))["tickets"]
    if a.interactive:
        approver = ConsoleApprover(a.name, a.role)
    else:
        approver = ScriptedApprover(json.loads(Path(a.approvals).read_text(encoding="utf-8"))["decisions"])
    planner = None
    if a.llm:
        from .agents import ClaudePlanner
        planner = ClaudePlanner()

    env, log = Environment(), audit_mod.AuditLog(a.audit)
    for ticket in tickets:
        print(f"{ticket['id']}  ({ticket['requester']}) {ticket['text']}")
        for o in process(ticket, env, log, approver, planner):
            act = o["action"]
            label = f"{act['tool']} {act['args']}" if act["tool"] else act["rationale"]
            level = f"[{o['level']}] " if o.get("level") else ""
            print(f"    {o['status']:<10} {level}{label}")
        print()
    ok, message = audit_mod.verify(log.entries)
    print(f"audit log: {message} -> {a.audit}")


def cmd_verify(a):
    ok, message = audit_mod.verify(audit_mod.load(a.audit))
    print(("OK: " if ok else "TAMPERED: ") + message)
    if not ok:
        sys.exit(1)


def main(argv=None):
    p = argparse.ArgumentParser(prog="hitl", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="process tickets")
    r.add_argument("--tickets", default="examples/tickets.json")
    r.add_argument("--approvals", default="examples/approvals.json")
    r.add_argument("--audit", default="audit.jsonl")
    r.add_argument("--interactive", action="store_true", help="ask for approvals at the terminal")
    r.add_argument("--name", default="operator")
    r.add_argument("--role", default="it-manager", choices=["it-staff", "security", "it-manager"])
    r.add_argument("--llm", action="store_true", help="plan with Claude (needs: pip install anthropic)")
    r.set_defaults(func=cmd_run)
    v = sub.add_parser("verify-audit", help="check the audit log hash chain")
    v.add_argument("audit", nargs="?", default="audit.jsonl")
    v.set_defaults(func=cmd_verify)
    a = p.parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    main()
