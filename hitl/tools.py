"""The tools agents may use, and a SIMULATED IT environment they act on.

Nothing here touches a real system: the "directory", services and firewall are Python
dictionaries. Each tool checks its inputs, and each has a verification step that
confirms the change actually happened.
"""

import copy

# The only actions an agent can ever take. Anything else is rejected by the workflow.
CATALOGUE = {
    "reset_password":     {"args": ["user"], "base_risk": "LOW"},
    "unlock_account":     {"args": ["user"], "base_risk": "LOW"},
    "add_to_group":       {"args": ["user", "group"], "base_risk": "MEDIUM"},
    "restart_service":    {"args": ["host", "service"], "base_risk": "LOW"},
    "open_firewall_port": {"args": ["port", "source"], "base_risk": "HIGH"},
}

DEMO_ENVIRONMENT = {
    "users": {
        "j.doe": {"locked": True, "groups": ["Staff"]},
        "m.khoury": {"locked": False, "groups": ["Staff", "Finance"]},
        "x.nasser": {"locked": False, "groups": ["Contractors"]},
        "r.saad": {"locked": False, "groups": ["Staff"]},
    },
    "groups": ["Staff", "Finance", "Finance-Approvers", "Contractors", "Domain Admins"],
    "services": {"PRINT-01/print spooler": "running", "DB-01/PostgreSQL": "running"},
    "firewall_rules": [],
}


class ToolError(Exception):
    pass


class Environment:
    def __init__(self, state=None):
        self.state = copy.deepcopy(state or DEMO_ENVIRONMENT)
        self.restarts = {}

    def _user(self, name):
        if name not in self.state["users"]:
            raise ToolError(f"unknown user '{name}'")
        return self.state["users"][name]

    def run(self, tool, args):
        if tool not in CATALOGUE:
            raise ToolError(f"tool '{tool}' is not in the catalogue")
        missing = [a for a in CATALOGUE[tool]["args"] if a not in args]
        if missing:
            raise ToolError(f"missing argument(s): {', '.join(missing)}")
        return getattr(self, tool)(**{a: args[a] for a in CATALOGUE[tool]["args"]})

    # --- tools -------------------------------------------------------------
    def reset_password(self, user):
        u = self._user(user)
        u["locked"] = False
        u["password_reset"] = True
        return f"temporary password issued to {user} (must change at next login)"

    def unlock_account(self, user):
        self._user(user)["locked"] = False
        return f"{user} unlocked"

    def add_to_group(self, user, group):
        if group not in self.state["groups"]:
            raise ToolError(f"unknown group '{group}'")
        groups = self._user(user)["groups"]
        if group not in groups:  # idempotent: adding twice changes nothing
            groups.append(group)
        return f"{user} is a member of {group}"

    def restart_service(self, host, service):
        key = f"{host}/{service}"
        if key not in self.state["services"]:
            raise ToolError(f"unknown service '{service}' on {host}")
        self.restarts[key] = self.restarts.get(key, 0) + 1
        self.state["services"][key] = "running"
        return f"{service} restarted on {host}"

    def open_firewall_port(self, port, source):
        rule = {"port": int(port), "source": source}
        if rule not in self.state["firewall_rules"]:
            self.state["firewall_rules"].append(rule)
        return f"port {port} opened from {source}"

    # --- verification ------------------------------------------------------
    def verify(self, tool, args):
        """Check the post-condition of a tool run. Returns True if the change is in place."""
        if tool in ("reset_password", "unlock_account"):
            return not self._user(args["user"])["locked"]
        if tool == "add_to_group":
            return args["group"] in self._user(args["user"])["groups"]
        if tool == "restart_service":
            return self.state["services"].get(f"{args['host']}/{args['service']}") == "running"
        if tool == "open_firewall_port":
            return {"port": int(args["port"]), "source": args["source"]} in self.state["firewall_rules"]
        return False
