"""Run feature smoke checks with saved local logs, one subprocess per check."""

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta, timezone
from time import monotonic

import psutil

from nisha.settings import ROOT

GROUPS = {
    "ui": [
        ("verify_desktop.py", []),
        ("verify_conversation.py", []),
        ("verify_visuals.py", []),
        ("verify_connections.py", []),
        ("verify_learning_ui.py", []),
        ("verify_credentials.py", []),
        ("verify_voice_enrollment.py", []),
        ("verify_microphones.py", []),
        ("verify_window_actions.py", []),
    ],
    "voice": [
        ("verify_voice.py", []),
        ("verify_speech_accuracy.py", []),
        ("verify_wake_phrases.py", []),
        ("verify_enrolled_wakes.py", []),
        ("verify_personal_speech.py", []),
        ("verify_wake_desktop.py", ["--enrolled"]),
        ("verify_wake_desktop.py", ["--manual"]),
        ("verify_fresh_conversation.py", []),
        ("verify_interruption.py", []),
        ("verify_listening.py", []),
    ],
    "models": [
        ("verify_local.py", ["--model", "local_fast"]),
        ("verify_local.py", ["--model", "local_smart"]),
        ("verify_learning.py", []),
        ("verify_workflows.py", []),
        ("verify_project_model.py", []),
        ("verify_response_completion.py", []),
        ("verify_conversation_learning.py", []),
        ("verify_service_recovery.py", []),
        ("verify_local_vision.py", []),
    ],
    "editors": [
        ("verify_editor_actions.py", ["--launch"]),
        ("verify_editor_window_actions.py", ["--launch"]),
    ],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", choices=GROUPS, required=True)
    parser.add_argument("--only", help="Optional script name within the selected group")
    args = parser.parse_args()
    zone = timezone(timedelta(hours=5, minutes=30))
    stamp = datetime.now(UTC).astimezone(zone).strftime("%Y-%m-%d")
    folder = ROOT / "data/reports" / ("full-check-" + stamp)
    folder.mkdir(parents=True, exist_ok=True)
    result_file = folder / (args.group + "-results.json")
    checks = json.loads(result_file.read_text(encoding="utf-8")) if result_file.exists() else []
    this_run = []
    for index, (name, options) in enumerate(GROUPS[args.group]):
        if args.only and name != args.only:
            continue
        path = ROOT / "scripts" / name
        # Synthetic temporary tests should not start asynchronous learning just
        # as their databases are removed. The dedicated review test uses the
        # real worker, explicitly waits for it, and verifies its results.
        wrapper = "import runpy,sys; "
        if name != "verify_conversation_learning.py":
            wrapper += "from nisha.conversation_learning import ConversationLearning; ConversationLearning.launch=lambda self:None; "
        wrapper += "import os; sys.argv=sys.argv[1:]; sys.path.insert(0,os.path.dirname(sys.argv[0])); runpy.run_path(sys.argv[0],run_name='__main__')"
        command = [sys.executable, "-c", wrapper, str(path), *options]
        log = folder / f"{args.group}-{index + 1:02d}-{path.stem}.log"
        if log.exists():
            log = log.with_stem(log.stem + "-retry-" + datetime.now(UTC).strftime("%H%M%S"))
        start = monotonic()
        print("START:", name, " ".join(options), flush=True)
        with log.open("w", encoding="utf-8") as output:
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdout=output,
                stderr=subprocess.STDOUT,
                env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"),
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            try:
                code = process.wait(timeout=420)
            except subprocess.TimeoutExpired:
                owned = psutil.Process(process.pid).children(recursive=True)
                for child in reversed(owned):
                    try:
                        child.terminate()
                    except psutil.NoSuchProcess:
                        pass
                process.terminate()
                _, alive = psutil.wait_procs(owned, timeout=5)
                for child in alive:
                    child.kill()
                process.wait(timeout=5)
                code = 124
        detail = log.read_text(encoding="utf-8", errors="replace")
        check = {
            "script": name,
            "options": options,
            "exit_code": code,
            "seconds": round(monotonic() - start, 2),
            "log": str(log),
            "status": "pass" if code == 0 else "fail",
        }
        checks.append(check)
        this_run.append(check)
        print(f"{check['status'].upper()}: {name} ({check['seconds']}s)", flush=True)
        print("\n".join(detail.splitlines()[-12:]), flush=True)
        result_file.write_text(json.dumps(checks, indent=2), encoding="utf-8")
    return int(any(check["exit_code"] for check in this_run))


if __name__ == "__main__":
    raise SystemExit(main())
