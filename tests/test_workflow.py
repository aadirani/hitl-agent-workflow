import copy
import json
import unittest
from pathlib import Path

from hitl import audit
from hitl.agents import IntakeAgent, RiskAgent
from hitl.tools import Environment, ToolError
from hitl.workflow import ScriptedApprover, process

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
TICKETS = {t["id"]: t for t in json.loads((EXAMPLES / "tickets.json").read_text(encoding="utf-8"))["tickets"]}
DECISIONS = json.loads((EXAMPLES / "approvals.json").read_text(encoding="utf-8"))["decisions"]


def run_all():
    env, log = Environment(), audit.AuditLog(clock=lambda: "2026-10-06T00:00:00+00:00")
    approver = ScriptedApprover(DECISIONS)
    results = {tid: [o["status"] for o in process(t, env, log, approver)] for tid, t in TICKETS.items()}
    return results, env, log


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results, cls.env, cls.log = run_all()

    def test_expected_outcomes(self):
        expected = {
            "T-1": ["DONE"],                 # low risk: automatic
            "T-2": ["DONE"],                 # medium: approved by IT staff
            "T-3": ["REJECTED"],             # high: security said no
            "T-4": ["BLOCKED"],              # RDP to the internet: never allowed
            "T-5": ["DONE"],                 # low risk restart
            "T-6": ["DONE"],                 # production restart approved by IT manager
            "T-7": ["DONE", "BLOCKED"],      # reset approved; self-elevation blocked
            "T-8": ["ESCALATED"],            # nothing the agents can do: human takes it
        }
        self.assertEqual(self.results, expected)

    def test_environment_changed_only_where_allowed(self):
        users = self.env.state["users"]
        self.assertFalse(users["j.doe"]["locked"])
        self.assertIn("Finance-Approvers", users["m.khoury"]["groups"])
        self.assertNotIn("Domain Admins", users["x.nasser"]["groups"])
        self.assertNotIn("Domain Admins", users["r.saad"]["groups"])
        self.assertEqual(self.env.state["firewall_rules"], [])

    def test_audit_chain_is_intact(self):
        ok, _ = audit.verify(self.log.entries)
        self.assertTrue(ok)

    def test_tampering_is_detected(self):
        entries = copy.deepcopy(self.log.entries)
        decision = next(e for e in entries if e["event"] == "approval_decision")
        decision["details"]["decision"] = "approve"   # someone rewrites history
        ok, message = audit.verify(entries)
        self.assertFalse(ok)
        self.assertIn("modified", message)

    def test_deleted_entry_is_detected(self):
        entries = copy.deepcopy(self.log.entries)
        del entries[3]
        self.assertFalse(audit.verify(entries)[0])


class GateTests(unittest.TestCase):
    def outcome(self, ticket, decision):
        env, log = Environment(), audit.AuditLog()
        return process(ticket, env, log, ScriptedApprover({ticket["id"]: decision}))[0]["status"]

    def test_requester_cannot_approve_own_ticket(self):
        ticket = TICKETS["T-6"]
        decision = {"approver": ticket["requester"], "role": "it-manager", "decision": "approve"}
        self.assertEqual(self.outcome(ticket, decision), "REJECTED")

    def test_wrong_role_cannot_approve_high_risk(self):
        decision = {"approver": "lina", "role": "it-staff", "decision": "approve"}
        self.assertEqual(self.outcome(TICKETS["T-6"], decision), "REJECTED")

    def test_no_decision_means_no_execution(self):
        self.assertEqual(self.outcome(TICKETS["T-2"], None), "REJECTED")

    def test_blocked_even_if_someone_approves(self):
        decision = {"approver": "omar", "role": "it-manager", "decision": "approve"}
        self.assertEqual(self.outcome(TICKETS["T-4"], decision), "BLOCKED")


class AgentTests(unittest.TestCase):
    def test_intake_finds_both_requests_and_flags_injection(self):
        intake = IntakeAgent().run(TICKETS["T-7"])
        self.assertEqual([r["tool"] for r in intake["requests"]], ["reset_password", "add_to_group"])
        self.assertTrue(intake["injection_suspected"])

    def test_injection_raises_low_risk_to_medium(self):
        ticket = TICKETS["T-7"]
        intake = IntakeAgent().run(ticket)
        level, reasons = RiskAgent().run(ticket, intake, {"tool": "reset_password", "args": {"user": "r.saad"}})
        self.assertEqual(level, "MEDIUM")

    def test_unknown_tool_blocked(self):
        intake = {"requests": [], "injection_suspected": False}
        level, _ = RiskAgent().run(TICKETS["T-1"], intake, {"tool": "delete_all_users", "args": {}})
        self.assertEqual(level, "BLOCKED")

    def test_tools_validate_and_are_idempotent(self):
        env = Environment()
        with self.assertRaises(ToolError):
            env.run("add_to_group", {"user": "nobody", "group": "Staff"})
        env.run("add_to_group", {"user": "m.khoury", "group": "Finance-Approvers"})
        env.run("add_to_group", {"user": "m.khoury", "group": "Finance-Approvers"})
        self.assertEqual(env.state["users"]["m.khoury"]["groups"].count("Finance-Approvers"), 1)


if __name__ == "__main__":
    unittest.main()
