"""Isolated real local-engine latency check; no microphone or external providers."""

import json
import socket
import threading
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import monotonic

from nisha.core import NishaCore
from nisha.process_lifetime import attach_child_lifetime
from nisha.services import LocalServices
from nisha.settings import load_settings


def port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def main():
    attach_child_lifetime()
    original = load_settings()
    report = original.data_dir / "reports" / "response-latency.json"
    results = []
    with TemporaryDirectory(prefix="nisha-latency-", ignore_cleanup_errors=True) as directory:
        settings = original.model_copy(
            update={
                "data_dir": Path(directory),
                "models": {"local_fast": original.models["local_fast"]},
                "gateway_url": f"http://127.0.0.1:{port()}",
                "ollama_url": f"http://127.0.0.1:{port()}",
                "instant_smalltalk": True,
                "external_tasks_enabled": False,
            }
        )
        core = NishaCore(settings)
        session = core.new_session()
        started = monotonic()
        reply = core.chat("What's up, baby?", session)
        results.append(
            {
                "case": "greeting_before_services",
                "seconds": round(monotonic() - started, 3),
                "reply": reply,
            }
        )
        services = LocalServices(settings)
        started = monotonic()
        state = services.ensure(timeout=90)
        results.append(
            {
                "case": "service_start",
                "seconds": round(monotonic() - started, 3),
                "ready": state["ready"],
            }
        )
        print(json.dumps(results), flush=True)
        if not state["ready"]:
            raise RuntimeError("Isolated local services did not become ready.")
        started = monotonic()
        services.warm_fast()
        results.append({"case": "background_warmup", "seconds": round(monotonic() - started, 3)})
        print(json.dumps(results[-1]), flush=True)
        for prompt in (
            "I had a busy day. Reply briefly.",
            "What can we talk about? Keep it short.",
            "Tell me one useful fact about water. Keep it short.",
        ):
            started = monotonic()
            first = None
            chunks = []
            for chunk in core.stream(prompt, session, cancelled=lambda: False):
                first = first if first is not None else monotonic() - started
                chunks.append(chunk)
            results.append(
                {
                    "case": prompt,
                    "first_text_seconds": round(first or 0, 3),
                    "total_seconds": round(monotonic() - started, 3),
                    "reply": "".join(chunks),
                }
            )
            print(json.dumps(results[-1]), flush=True)
        # Sustained generation across growing conversation history, using the
        # same cancellable transport as the desktop. All prompts are synthetic.
        durations = []
        for index in range(20):
            prompt = (
                "I finished my college project today. Reply naturally in one short sentence."
                if index % 2 == 0
                else "Tell me a different useful everyday fact in one short sentence."
            )
            started = monotonic()
            reply = "".join(core.stream(prompt, session, cancelled=lambda: False))
            assert reply.strip() and "Cannot get a complete" not in reply
            durations.append(round(monotonic() - started, 3))
        results.append(
            {
                "case": "20_sustained_generated_turns",
                "count": len(durations),
                "median_seconds": median(durations),
                "max_seconds": max(durations),
                "seconds": durations,
            }
        )
        print(json.dumps(results[-1]), flush=True)
        from nisha.errors import OperationCancelled

        stop = threading.Event()
        timer = threading.Timer(0.25, stop.set)
        timer.start()
        started = monotonic()
        try:
            list(
                core.stream(
                    "Write a detailed 2000-word explanation of the solar system.",
                    core.new_session(),
                    cancelled=stop.is_set,
                )
            )
            raise AssertionError("The long generation completed before cancellation was exercised")
        except OperationCancelled:
            elapsed = round(monotonic() - started, 3)
            assert elapsed < 6, "Cancellation exceeded metadata plus transport deadline"
            results.append({"case": "cancel_live_generation", "seconds": elapsed})
        finally:
            timer.cancel()
        with core.store.connect() as db:
            assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(results, indent=2), encoding="utf-8")
        services.close()
        core.gateway.close()  # Do not queue synthetic chats for conversation review.
    print("Report: " + str(report), flush=True)


if __name__ == "__main__":
    main()
