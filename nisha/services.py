"""Start/recover local model services without blocking wake listening or downloading models."""

import logging
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from time import monotonic

import httpx

from nisha.settings import ROOT

logger = logging.getLogger("nisha")
_STARTING = {}


class LocalServices:
    def __init__(self, settings, client=None, launcher=None, clock=monotonic, wait=None):
        from threading import Event

        self.settings = settings
        self.client = client or httpx.Client(timeout=2, trust_env=False)
        self.owned_client = client is None
        self.launcher = launcher or subprocess.Popen
        self.clock, self.wait = clock, wait or Event().wait
        self.last_state = ""

    def close(self):
        if self.owned_client:
            self.client.close()

    def warm_fast(self, cancelled=None, transport=None):
        """Cancellable background warm-up; never download or displace a loaded model."""
        import asyncio

        from nisha.context import IDENTITY

        async def warm():
            async with httpx.AsyncClient(
                timeout=180, trust_env=False, transport=transport
            ) as client:
                response = await client.get(self.settings.ollama_url + "/api/ps")
                response.raise_for_status()
                if response.json().get("models"):
                    return
                profile = self.settings.models["local_fast"]
                name = profile.model.split("/", 1)[1]
                response = await client.post(
                    self.settings.ollama_url + "/api/show", json={"model": name}
                )
                response.raise_for_status()
                metadata = response.json()
                if (
                    metadata.get("remote_host")
                    or metadata.get("remote_model")
                    or not metadata.get("model_info", {}).get("general.architecture")
                ):
                    return
                response = await client.post(
                    self.settings.ollama_url + "/api/chat",
                    json={
                        "model": name,
                        "stream": False,
                        "keep_alive": "1h",
                        "messages": [
                            {"role": "system", "content": IDENTITY},
                            {"role": "user", "content": "Reply ready."},
                        ],
                        "options": {"num_ctx": profile.context_window, "num_predict": 1},
                    },
                )
                response.raise_for_status()
                logger.info("Local conversation model warmed in background.")

        async def supervised():
            if cancelled and cancelled():
                return
            task = asyncio.create_task(warm())
            try:
                while not task.done():
                    if cancelled and cancelled():
                        task.cancel()
                        break
                    await asyncio.sleep(0.1)
                await asyncio.gather(task, return_exceptions=False)
            except asyncio.CancelledError:
                pass
            except (httpx.HTTPError, ValueError, TypeError, AttributeError):
                logger.info("Local model warm-up deferred; normal recovery remains active.")

        asyncio.run(supervised())

    def probe(self):
        result = {"ollama": "unavailable", "gateway": "unavailable"}
        for name, url in [
            ("ollama", self.settings.ollama_url + "/api/tags"),
            ("gateway", self.settings.gateway_url + "/v1/models"),
        ]:
            try:
                response = self.client.get(url, headers=self.headers() if name == "gateway" else {})
                response.raise_for_status()
                data = response.json()
                if name == "ollama":
                    names = {m["name"] for m in data["models"]}
                    needed = [
                        p.model.split("/", 1)[1] for p in self.settings.models.values() if p.local
                    ]
                    result[name] = (
                        "ready"
                        if all(n in names or n + ":latest" in names for n in needed)
                        else "missing downloaded models"
                    )
                else:
                    names = {m["id"] for m in data["data"]}
                    result[name] = (
                        "ready"
                        if set(self.settings.models) <= names
                        else "model configuration differs"
                    )
            except httpx.HTTPStatusError:
                result[name] = "access/configuration error"
            except (httpx.HTTPError, ValueError, TypeError, KeyError):
                pass
        result["ready"] = all(result[n] == "ready" for n in ("ollama", "gateway"))
        return result

    @staticmethod
    def headers():
        key = os.getenv("NISHA_GATEWAY_KEY", "")
        return {"Authorization": f"Bearer {key}"} if key else {}

    @contextmanager
    def startup_lock(self):
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        with (self.settings.data_dir / "service-start.lock").open("a+b") as handle:
            import msvcrt

            handle.write(b"0")
            handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                yield False
            else:
                try:
                    yield True
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    def ollama_executable(self):
        path = shutil.which("ollama")
        if path:
            return path
        path = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Ollama/ollama.exe"
        return str(path) if path.is_file() else None

    def launch(self, name):
        service_key = (
            name,
            self.settings.ollama_url if name == "ollama" else self.settings.gateway_url,
        )
        previous = _STARTING.get(service_key)
        if previous is not None and previous.poll() is None:
            return True  # The previous launch is still starting; don't duplicate it.
        if name == "ollama":
            executable = self.ollama_executable()
            if not executable:
                logger.warning("Local Ollama executable is unavailable; no model was downloaded.")
                return False
            args = [executable, "serve"]
            environment = dict(os.environ, OLLAMA_HOST=self.settings.ollama_url)
            # An engine launched for NISHA must remain local independently of
            # the provider/task switch. Avoid retaining multiple large models
            # alongside the continuously resident speech recognizer.
            environment["OLLAMA_NO_CLOUD"] = "1"
            environment.setdefault("OLLAMA_MAX_LOADED_MODELS", "1")
            # Keep the active local model resident across ordinary breaks so the
            # next spoken turn does not pay a full cold-load delay.
            environment.setdefault("OLLAMA_KEEP_ALIVE", "1h")
        else:
            executable = Path(sys.executable)
            if executable.name.casefold() == "pythonw.exe":
                executable = executable.with_name("python.exe")
            args = [str(executable), "-m", "nisha", "gateway"]
            # The desktop and gateway must use the same effective configuration.
            config = self.settings.data_dir / "resident-config.yaml"
            import yaml

            config.write_text(
                yaml.safe_dump(self.settings.model_dump(mode="json")), encoding="utf-8"
            )
            args = [str(executable), "-m", "nisha", "--config", str(config), "gateway"]
            environment = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        try:
            with (
                (self.settings.data_dir / (name + "-service-out.log")).open("ab") as output,
                (self.settings.data_dir / (name + "-service-err.log")).open("ab") as error,
            ):
                process = self.launcher(
                    args,
                    cwd=str(ROOT),
                    env=environment,
                    stdout=output,
                    stderr=error,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                if hasattr(process, "poll"):
                    _STARTING[service_key] = process
            logger.info("Starting local service: %s.", name)
            return True
        except OSError:
            logger.warning("Couldn't start local service: %s.", name)
            return False

    def ensure(self, timeout=25, cancelled=None):
        deadline = self.clock() + timeout
        launched = set()
        while True:
            status = self.probe()
            state = f"Ollama {status['ollama']}; gateway {status['gateway']}"
            if state != self.last_state:
                if self.last_state or not status["ready"]:
                    logger.info("Local service health: %s.", state)
                self.last_state = state
            if status["ready"] or self.clock() >= deadline or (cancelled and cancelled()):
                return status
            if any(status[n] not in {"ready", "unavailable"} for n in ("ollama", "gateway")):
                return status  # Don't duplicate a live server or download missing models.
            with self.startup_lock() as owned:
                if owned:
                    # Recheck under the lock; another process may have started it.
                    status = self.probe()
                    for name in ("ollama", "gateway"):
                        if status[name] == "unavailable" and name not in launched:
                            if name == "gateway" and status["ollama"] != "ready":
                                continue
                            if self.launch(name):
                                launched.add(name)
                    # Keep ownership until launched services become ready or this
                    # attempt ends. Other callers probe, without launching duplicates.
                    while launched and self.clock() < deadline and not (cancelled and cancelled()):
                        self.wait(0.5)
                        status = self.probe()
                        if (
                            status["ollama"] == "ready"
                            and status["gateway"] == "unavailable"
                            and "gateway" not in launched
                            and self.launch("gateway")
                        ):
                            launched.add("gateway")
                        if status["ready"]:
                            logger.info("Local services are ready after recovery.")
                            return status
                    if launched:
                        return status
            self.wait(0.5)
