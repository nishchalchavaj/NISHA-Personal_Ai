"""Evidence-first local research, failure review, and self-analysis."""

import json
import re
from pathlib import Path

from nisha.coding import redact_sensitive_text
from nisha.errors import NishaError


class Diagnostics:
    def __init__(self, coding, store, data_dir):
        self.coding = coding
        self.store = store
        self.data_dir = Path(data_dir)

    def research(self, project, query, limit=30):
        """Search configured local source and documentation; return cited file/line evidence."""
        terms = [term for term in query.split() if len(term) > 1]
        if not terms or len(query) > 500:
            raise NishaError("Give a research question of at most 500 characters.")
        matches = []
        for term in terms[:12]:
            matches.extend(self.coding.search(project, re.escape(term), limit=limit))
        unique = {}
        for item in matches:
            unique[(item["path"], item["line"])] = item
        evidence = list(unique.values())[:limit]
        return {
            "project": project,
            "query": query,
            "scope": "configured project source and documentation only",
            "evidence": evidence,
            "result_count": len(evidence),
        }

    def failures(self, limit=20):
        path = self.data_dir / "reports" / "coding-commands.jsonl"
        if not path.exists():
            return []
        failures = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[-500:]
        except OSError:
            return []
        for line in reversed(lines):
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if item.get("exit_code") or item.get("timed_out"):
                failures.append(
                    {
                        "suite": item.get("suite"),
                        "command": item.get("command"),
                        "working_directory": item.get("working_directory"),
                        "start_time": item.get("start_time"),
                        "exit_code": item.get("exit_code"),
                        "timed_out": item.get("timed_out", False),
                        "stdout": redact_sensitive_text(item.get("stdout", ""))[-4000:],
                        "stderr": redact_sensitive_text(item.get("stderr", ""))[-4000:],
                    }
                )
            if len(failures) >= limit:
                break
        return failures

    def debug(self, project=None, query=None):
        evidence = self.failures()
        source = self.research(project, query) if project and query else None
        observations = []
        for failure in evidence:
            if failure["timed_out"]:
                observation = "verification command exceeded its configured timeout"
            else:
                observation = f"{failure['suite']} exited with code {failure['exit_code']}"
            observations.append({"observation": observation, "evidence": failure})
        return {
            "observations": observations,
            "source_evidence": source,
            "hypotheses": [],
            "note": "No cause is asserted unless the captured output directly identifies it.",
        }

    def analyze(self):
        failures = self.failures(limit=100)
        repeated = {}
        for failure in failures:
            output = failure["stderr"] or failure["stdout"]
            first_line = output.splitlines()[0] if output else ""
            key = (
                failure["suite"],
                failure["exit_code"],
                failure["timed_out"],
                first_line,
            )
            repeated.setdefault(key, []).append(failure["start_time"])
        repeated_failures = [
            {
                "suite": key[0],
                "exit_code": key[1],
                "timed_out": key[2],
                "evidence_count": len(times),
                "timestamps": times,
            }
            for key, times in repeated.items()
            if len(times) > 1
        ]
        audits = []
        outcomes = []
        with self.store.connect() as db:
            audits = [dict(row) for row in db.execute(
                "SELECT action,outcome,created_at FROM audit ORDER BY id DESC LIMIT 100"
            )]
            outcomes = [dict(row) for row in db.execute(
                "SELECT status,detail,created_at FROM turn_outcomes ORDER BY id DESC LIMIT 100"
            )]
            outcome_counts = {
                row["status"]: row["count"]
                for row in db.execute("SELECT status,COUNT(*) AS count FROM turn_outcomes GROUP BY status")
            }
            feedback_count = db.execute("SELECT COUNT(*) FROM user_observations").fetchone()[0]
        slow = []
        command_path = self.data_dir / "reports" / "coding-commands.jsonl"
        if command_path.exists():
            try:
                for line in command_path.read_text(encoding="utf-8").splitlines()[-500:]:
                    item = json.loads(line)
                    if float(item.get("duration_seconds", 0)) >= 2:
                        slow.append({
                            "suite": item.get("suite"),
                            "duration_seconds": item.get("duration_seconds"),
                            "start_time": item.get("start_time"),
                            "exit_code": item.get("exit_code"),
                        })
            except (OSError, ValueError, TypeError):
                pass
        benchmarks = []
        experiments = self.data_dir / "experiments"
        for path in sorted(experiments.glob("[0-9a-f]" * 32 + ".json"))[-100:]:
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            result = manifest.get("benchmarks", {}).get("fixed_suites")
            if result:
                benchmarks.append({
                    "experiment_id": manifest.get("experiment_id"),
                    "status": manifest.get("status"),
                    "completed_at": result.get("completed_at"),
                    "ready_for_human_review": result.get("ready_for_human_review"),
                    "performance_delta_pct": result.get("performance_delta_pct"),
                    "candidate_quality_passed": result.get("candidate_quality_passed"),
                })
        return {
            "evidence_window": {"audit_events": len(audits), "turn_outcomes": len(outcomes), "commands": 500},
            "failed_commands": failures,
            "repeated_failures": repeated_failures,
            "slow_commands_over_2_seconds": slow[-50:],
            "candidate_benchmarks": benchmarks,
            "audit_outcomes": audits,
            "turn_outcomes": outcomes,
            "turn_outcome_counts": outcome_counts,
            "recorded_user_observation_count": feedback_count,
            "resource_usage": self._resource_usage(),
            "conclusions": [],
            "note": "This report lists observations; it does not infer causes from sparse telemetry.",
        }

    @staticmethod
    def _resource_usage():
        try:
            import psutil
        except ImportError:
            return {"available": False, "reason": "psutil isn't installed in this environment."}
        process = psutil.Process()
        return {
            "available": True,
            "process_cpu_percent": process.cpu_percent(interval=0.1),
            "process_rss_bytes": process.memory_info().rss,
            "system_cpu_percent": psutil.cpu_percent(interval=None),
            "system_memory_percent": psutil.virtual_memory().percent,
        }
