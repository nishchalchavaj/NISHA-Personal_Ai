"""Small, auditable plans for user-configured routines."""

from dataclasses import dataclass

INSTRUCTIONS = {
    "open_folder": ("Open the configured folder in Explorer", "Windows accepted the open request"),
    "open_file": ("Open the configured document", "The document exists and the default app accepted it"),
    "open_path": ("Open the configured local path", "Windows accepted the open request"),
    "open_app": ("Launch the configured installed app", "The app launch request was accepted"),
    "open_website": ("Open the configured website", "The browser accepted the URL"),
    "open_chrome_url": ("Open the configured page in Chrome", "Chrome accepted the URL"),
    "search_chrome": ("Search Chrome for the saved phrase", "Chrome accepted the search request"),
    "device_on": ("Turn on the configured device", "The device API accepted or reported the state"),
    "device_off": ("Turn off the configured device", "The device API accepted or reported the state"),
}


@dataclass(frozen=True)
class PlannedStep:
    number: int
    action: str
    target: str
    instruction: str
    success_evidence: str


def build_plan(routine):
    """Build a plan only from an already validated, user-saved Routine."""
    plan = []
    for number, step in enumerate(routine.steps, 1):
        instruction, evidence = INSTRUCTIONS[step.action]
        plan.append(PlannedStep(number, step.action, step.target, instruction, evidence))
    return tuple(plan)


def evaluate_plan(routine, plan):
    """Return deterministic planning checks; this never executes a device/app action."""
    expected = [(step.action, step.target) for step in routine.steps]
    actual = [(step.action, step.target) for step in plan]
    return {
        "step_count": len(plan),
        "all_steps_supported": all(step.action in INSTRUCTIONS for step in plan),
        "dependency_order_preserved": actual == expected,
        "success_evidence_defined": all(bool(step.success_evidence) for step in plan),
    }
