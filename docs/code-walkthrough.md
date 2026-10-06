# Code walkthrough

A plain-language guide for explaining this project in an interview.

## The journey of one ticket (`workflow.py → process()`)

1. **Received:** the ticket text is logged. It's treated as *untrusted*: anyone can type anything.
2. **Intake** (`IntakeAgent`): patterns find requests such as "Password reset for user X" or "Add X to Y", and a check looks for instruction-like phrases ("ignore previous instructions", "you are now…"). The output is a list of requests plus an `injection_suspected` flag.
3. **Plan** (`PlannerAgent`): each request becomes a proposed tool call with a short rationale. If nothing matches, the plan says *escalate to a human*.
4. **Risk** (`RiskAgent`): each tool has a base risk, raised by context:
   - privileged group (Domain Admins) → HIGH. The requester adding *themselves* → BLOCKED
   - production server (DB-01) → HIGH
   - Remote Desktop, SSH or SMB port open to "any" → BLOCKED
   - injection suspected → at least MEDIUM
5. **Gate** (plain code): LOW runs. MEDIUM needs IT staff. HIGH needs security or an IT manager. **The approver must have the right role and must not be the requester.** No decision means no action. BLOCKED is never sent for approval.
6. **Execute** (`Environment.run`): only catalogue tools with the right arguments. Unknown users or groups raise an error, logged as FAILED.
7. **Verify** (`Environment.verify`): confirms the change is really there.
8. **Close:** the outcomes are logged.

## `tools.py`

`CATALOGUE` is the complete list of what agents may do: five tools, their arguments and base risk. `Environment` is a fake IT world (users, groups, services, firewall rules) held in a Python dictionary, so the demo is safe and repeatable. Adding someone to a group they're already in changes nothing (**idempotent**).

## `audit.py`: tamper-evident log

Each entry contains the previous entry's hash, and its own hash is SHA-256 over its content plus that previous hash. Changing any past entry changes its hash, which no longer matches the `prev_hash` stored in the next entry, so `verify()` finds the exact entry where the chain breaks. The tests rewrite a "reject" into an "approve" and delete an entry, and both are detected.

## `agents.py → ClaudePlanner` (optional)

It sends the ticket to Claude with the tool catalogue, asking for a JSON plan whose shape is enforced by a **JSON schema** (tool names limited to the catalogue). The system prompt tells the model the ticket is untrusted input. Even so, the plan goes through `RiskAgent` and the gate like any other. That's the core design point: **the model proposes, code decides.**

## The tests

The full demo gives exactly the expected outcome per ticket. Only the allowed changes happen in the environment (nobody becomes Domain Admin, no firewall rules). The audit chain verifies, and tampering or deletion is detected. The gates reject self-approval, wrong roles and missing decisions, and blocked actions stay blocked even when "approved". Intake finds both requests in the injection ticket, and tools validate inputs and are idempotent.

## Likely interview questions

- **"How do you stop prompt injection?"** You don't rely on the model to resist it. Permissions are enforced in code, suspicious tickets get human review, and some actions are impossible whatever the text says (ADR-001, ADR-005).
- **"Why not approve everything manually?"** People stop reading. Risk tiers keep human attention for decisions that matter (ADR-004).
- **"Why a hash chain?"** It makes tampering *detectable*. Add write-once storage to make it *preventable* (§4).
- **"Is this multi-agent?"** Yes, three specialised agents plus an orchestrator. The planner can be rule-based or an LLM without changing the safety layer (ADR-002, ADR-003).
- **"Does it touch real systems?"** No. It runs against a simulated environment. Production would swap in real connectors with least-privilege accounts (§8).
