import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import UTC
from pathlib import Path
from urllib.parse import urlparse

from nisha.core import NishaCore
from nisha.errors import NishaError
from nisha.gateway import write_gateway_config
from nisha.health import health
from nisha.logging_setup import configure_logging
from nisha.settings import load_settings
from nisha.tools import ToolService


def conversation(core, args):
    session = args.session or core.new_session()
    alias = args.model
    core.route(session, alias)
    print(f"NISHA | session {session} | model {alias}")
    print("/new /models /use ALIAS /remember TEXT /remember KEY=TEXT /memories /forget ID")
    print("/files /read PATH /delete PATH /exit. Memories are local-only by default.")
    tools = ToolService(core.store, core.settings.data_dir / "workspace")
    while True:
        try:
            text = input("You: ").strip()
            if not text:
                continue
            if text == "/exit":
                core.end_conversation(session)
                return 0
            if text == "/new":
                core.end_conversation(session)
                session = core.new_session()
                print(f"New session: {session}")
            elif text == "/models":
                print(
                    ", ".join(
                        name for name, profile in core.settings.models.items() if profile.local
                    )
                )
            elif text.startswith("/use "):
                requested = text[5:].strip()
                if (
                    requested not in core.settings.models
                    or not core.settings.models[requested].local
                ):
                    print("Choose a configured local model alias.")
                    continue
                alias = requested
                print(f"Continuing session {session}; model {alias}")
            elif text.startswith("/remember "):
                memory = text[10:].strip()
                key, sep, value = memory.partition("=")
                print(
                    "Saved locally: "
                    + core.memory.remember(
                        value if sep else memory, key=key.strip() if sep else None
                    )
                )
            elif text == "/memories":
                for memory in core.memory.memories():
                    print(f"{memory['id']} | {memory['text']}")
            elif text.startswith("/forget "):
                print("Deleted." if core.memory.forget(text[8:].strip()) else "Memory not found.")
            elif text == "/files":
                print(json.dumps(tools.propose("list_files"), indent=2))
            elif text.startswith(("/read ", "/delete ")):
                command, name = text.split(" ", 1)
                action = tools.propose("read_file" if command == "/read" else "delete_file", name)
                if action["status"] == "confirmation_required":
                    approved = input(action["description"] + " Type yes: ") == "yes"
                    action = tools.confirm(action["approval_id"], approved)
                print(action.get("result", action["status"]))
            elif text in {"/feedback good", "/feedback bad", "/reinforcement"}:
                print(core.chat(text, session, alias))
            elif text.startswith("/"):
                print("Unknown command.")
            else:
                print("NISHA: ", end="", flush=True)
                for chunk in core.stream(text, session, alias):
                    print(chunk, end="", flush=True)
                print()
        except (NishaError, ValueError, OSError) as exc:
            print(f"\n{exc}")
        except (EOFError, KeyboardInterrupt):
            print("\nNISHA stopped.")
            return 0


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="NISHA personal assistant")
    parser.add_argument("--config", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    chat = sub.add_parser("chat", help="Text conversation; no microphone needed")
    chat.add_argument("--model", default="local_fast")
    chat.add_argument("--session")
    doctor = sub.add_parser("doctor", help="Check services; no generation unless requested")
    doctor.add_argument("--generate", action="store_true")
    sub.add_parser("gateway", help="Start the dedicated LiteLLM server")
    sub.add_parser("services", help="Start/recover local Ollama and model gateway")
    sub.add_parser("api", help="Start authenticated Core API on 127.0.0.1:8765")
    desktop = sub.add_parser("desktop", help="Desktop text chat with background wake listening")
    desktop.add_argument(
        "--background", action="store_true", help="Start hidden in the system tray"
    )
    desktop.add_argument("--quit", action="store_true", help="Gracefully stop the running desktop")
    sub.add_parser("voice", help="Push-to-talk voice conversation")
    sub.add_parser("backup", help="Create a consistent local SQLite backup")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s | %(message)s")
    try:
        settings = load_settings(args.config)
        configure_logging(settings.data_dir)
        if args.command == "services":
            from nisha.services import LocalServices

            services = LocalServices(settings)
            try:
                status = services.ensure(timeout=90)
                print(json.dumps(status))
                return 0 if status["ready"] else 1
            finally:
                services.close()
        if args.command == "gateway":
            path = write_gateway_config(settings)
            executable = Path(sys.executable).parent / (
                "litellm.exe" if os.name == "nt" else "litellm"
            )
            if not executable.exists():
                raise NishaError("Install gateway dependencies with scripts/setup.ps1.")
            environment = dict(
                os.environ,
                LITELLM_TELEMETRY="False",
                DO_NOT_TRACK="1",
                LITELLM_LOCAL_MODEL_COST_MAP="True",
                PYTHONUTF8="1",
                PYTHONIOENCODING="utf-8",
            )
            address = urlparse(settings.gateway_url)
            return subprocess.call(
                [
                    str(executable),
                    "--config",
                    str(path),
                    "--host",
                    address.hostname,
                    "--port",
                    str(address.port or 80),
                ],
                env=environment,
            )
        core = NishaCore(settings)
        try:
            if args.command == "doctor":
                checks = health(core, args.generate)
                print(json.dumps(checks, indent=2))
                return 0 if all(value == "ok" for value in checks.values()) else 1
            if args.command == "api":
                import uvicorn

                from nisha.api import create_app

                uvicorn.run(create_app(settings, core), host="127.0.0.1", port=8765, workers=1)
                return 0
            if args.command == "desktop":
                from nisha.ui.app import run_desktop

                return run_desktop(core, background=args.background, quit_running=args.quit)
            if args.command == "voice":
                from nisha.voice import voice_conversation

                return voice_conversation(core)
            if args.command == "backup":
                from datetime import datetime

                destination = settings.data_dir / (
                    "backup-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + ".sqlite3"
                )
                core.store.backup(destination)
                print(f"Backup saved: {destination}")
                return 0
            return conversation(core, args)
        finally:
            core.close()
    except (NishaError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ImportError:
        print(
            "Optional dependencies are missing. See README.md for desktop/voice setup.",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        return 0
