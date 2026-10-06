"""The orchestrator: runs the agents, enforces the approval gates, executes, verifies, logs.

Approval rules (enforced in code, whatever any agent says):
  LOW      -> executed automatically
  MEDIUM   -> one approval from IT staff (not the requester)
  HIGH     -> one approval from role 'security' or 'it-manager' (not the requester)
  BLOCKED  -> rejected without asking anyone
"""

from .agents import IntakeAgent, PlannerAgent, RiskAgent
from .tools import ToolError

APPROVER_ROLES = {"MEDIUM": {"it-staff", "security", "it-manager"}, "HIGH": {"security", "it-manager"}}


class ScriptedApprover:
    """Approval decisions read from a file: for demos, CI and tests."""

    def __init__(self, decisions):
        self.decisions = decisions

    def decide(self, ticket, action, level, reasons):
        return self.decisions.get(ticket["id"])


class ConsoleApprover:
    """Ask a human at the terminal."""

    def __init__(self, name, role):
        self.name, self.role = name, role

    def decide(self, ticket, action, level, reasons):
        print(f"\nAPPROVAL NEEDED [{level}] {ticket['id']}: {action['tool']} {action['args']}")
        for r in reasons:
            print(f"  - {r}")
        answer = input("approve? [y/N] ").strip().lower()
        return {"approver": self.name, "role": self.role,
                "decision": "approve" if answer == "y" else "reject", "comment": "console"}


def process(ticket, env, audit, approver, planner=None):
    """Run one ticket through the whole workflow. Returns a list of per-action outcomes."""
    intake_agent, risk_agent = IntakeAgent(), RiskAgent()
    planner = planner or PlannerAgent()

    audit.record(ticket["id"], "received", requester=ticket["requester"], text=ticket["text"])
    intake = intake_agent.run(ticket)
    audit.record(ticket["id"], "intake", **intake)
    plan = planner.run(ticket, intake)
    audit.record(ticket["id"], "plan", actions=plan)

    outcomes = []
    for action in plan:
        if action["tool"] is None:
            audit.record(ticket["id"], "escalated", reason=action["rationale"])
            outcomes.append({"action": action, "status": "ESCALATED"})
            continue

        level, reasons = risk_agent.run(ticket, intake, action)
        audit.record(ticket["id"], "risk", tool=action["tool"], args=action["args"], level=level, reasons=reasons)

        if level == "BLOCKED":
            audit.record(ticket["id"], "rejected", tool=action["tool"], by="policy", reasons=reasons)
            outcomes.append({"action": action, "status": "BLOCKED", "level": level, "reasons": reasons})
            continue

        if level in APPROVER_ROLES:
            audit.record(ticket["id"], "approval_requested", tool=action["tool"], level=level)
            d = approver.decide(ticket, action, level, reasons)
            valid = (d is not None and d.get("decision") == "approve"
                     and d.get("role") in APPROVER_ROLES[level]
                     and d.get("approver") != ticket["requester"])
            audit.record(ticket["id"], "approval_decision", tool=action["tool"],
                         decision=(d or {}).get("decision", "none"), approver=(d or {}).get("approver"),
                         role=(d or {}).get("role"), comment=(d or {}).get("comment"), accepted=valid)
            if not valid:
                outcomes.append({"action": action, "status": "REJECTED", "level": level})
                continue

        try:
            result = env.run(action["tool"], action["args"])
        except ToolError as err:
            audit.record(ticket["id"], "failed", tool=action["tool"], error=str(err))
            outcomes.append({"action": action, "status": "FAILED", "level": level, "error": str(err)})
            continue
        verified = env.verify(action["tool"], action["args"])
        audit.record(ticket["id"], "executed", tool=action["tool"], result=result, verified=verified)
        outcomes.append({"action": action, "status": "DONE" if verified else "UNVERIFIED", "level": level})

    audit.record(ticket["id"], "closed", outcomes=[o["status"] for o in outcomes])
    return outcomes
