"""Read-only validation of policy targets after the pinned ELF-reader renames."""
from __future__ import annotations
from collections import defaultdict


def validate_policy_bindings(functions: list[dict], profile: dict, policy: dict,
                             reimplemented: set[str], ignored: set[str]) -> dict:
    by_name = defaultdict(list)
    entries = [f for f in functions if f["vram"] == profile["callable_entrypoint"]]
    if len(entries) != 1:
        raise ValueError("ELF must contain exactly one configured callable entrypoint.")
    for function in functions:
        if function["vram"] == profile["callable_entrypoint"]:
            name = "recomp_entrypoint"
        elif function["name"] in reimplemented | ignored:
            name = function["name"] + "_recomp"
        else:
            name = function["name"]
        by_name[name].append(function)
    checked = []
    for collection, address_field in (("instructionPatches", "vram"),
                                      ("functionHooks", "beforeVram")):
        for patch in policy.get(collection, []):
            targets = by_name.get(patch["function"], [])
            if len(targets) != 1:
                raise ValueError("Policy function is missing or ambiguous after the ELF-reader rename: "
                                 + patch["function"])
            function = targets[0]
            address = patch[address_field]
            address = int(address, 0) if isinstance(address, str) else address
            if not function["vram"] <= address < function["vram"] + function["size"]:
                raise ValueError("Policy address leaves its bound ELF function.")
            if patch.get("elfFunction", function["name"]) != function["name"]:
                raise ValueError("Policy ELF-name evidence differs from its bound function.")
            checked.append({"collection": collection, "function": patch["function"],
                            "elf_function": function["name"], "vram": address})
    return {"status": "PASS", "bindings": checked, "actual_n64recomp_executed": False}
