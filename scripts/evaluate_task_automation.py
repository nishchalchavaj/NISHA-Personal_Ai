"""Offline planning-quality check; uses synthetic routines and performs no actions."""

import json

from nisha.connections import Routine
from nisha.task_planning import build_plan, evaluate_plan

SCENARIOS = [
    ("open a project folder", [{"action": "open_folder", "target": r"E:\Demo"}]),
    ("open a document", [{"action": "open_file", "target": r"E:\Demo\notes.docx"}]),
    ("launch an app", [{"action": "open_app", "target": "notepad"}]),
    ("open a website", [{"action": "open_website", "target": "https://example.org"}]),
    ("search in Chrome", [{"action": "search_chrome", "target": "local AI"}]),
    ("operate a device", [{"action": "device_on", "target": "desk_light"}]),
    (
        "preserve a multi-step dependency order",
        [
            {"action": "open_folder", "target": r"E:\Demo"},
            {"action": "open_app", "target": "notepad"},
            {"action": "open_chrome_url", "target": "https://example.org"},
        ],
    ),
]


def main():
    rows = []
    for name, steps in SCENARIOS:
        routine = Routine(name=name, steps=steps)
        plan = build_plan(routine)
        checks = evaluate_plan(routine, plan)
        rows.append({"scenario": name, **checks})
    passed = sum(
        row["all_steps_supported"]
        and row["dependency_order_preserved"]
        and row["success_evidence_defined"]
        for row in rows
    )
    print(json.dumps({"passed": passed, "total": len(rows), "scenarios": rows}, indent=2))
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
