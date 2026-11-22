"""Real cold service startup on isolated ports using already downloaded weights."""

import socket
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import psutil

from nisha.gateway import Gateway
from nisha.services import LocalServices
from nisha.settings import load_settings


def free_port():
    with socket.socket() as handle:
        handle.bind(("127.0.0.1", 0))
        return handle.getsockname()[1]


def main():
    settings = load_settings()
    children = []

    def launch(args, **kwargs):
        child = subprocess.Popen(args, **kwargs)
        children.append(child)
        return child

    with TemporaryDirectory(prefix="services-check-", dir=settings.data_dir) as directory:
        root = Path(directory).resolve()
        assert root.is_relative_to(settings.data_dir.resolve())
        isolated = settings.model_copy(
            update={
                "data_dir": root,
                "ollama_url": f"http://127.0.0.1:{free_port()}",
                "gateway_url": f"http://127.0.0.1:{free_port()}",
                "models": {"local_fast": settings.models["local_fast"]},
            }
        )
        services = LocalServices(isolated, launcher=launch)
        gateway = None
        try:
            assert not services.probe()["ready"], "Test ports must start empty"
            assert services.ensure(timeout=90)["ready"], (
                "Cold local services failed to become ready"
            )
            assert len(children) == 2, "Only one Ollama and one gateway should launch"
            assert services.ensure()["ready"] and len(children) == 2
            print(
                "PASS: real stopped Ollama and gateway started on isolated ports; repeated health checks launched no duplicates.",
                flush=True,
            )
            gateway = Gateway(isolated, services=services)
            answer = gateway.complete(
                "local_fast", [{"role": "user", "content": "Reply with exactly READY."}]
            )
            assert "READY" in answer.upper(), answer
            print(
                "PASS: cold downloaded local model completed an actual response through the recovered gateway.",
                flush=True,
            )
        finally:
            if gateway:
                gateway.close()
            else:
                services.close()
            # Only subprocesses created by this test and their descendants.
            for child in reversed(children):
                if child.poll() is not None:
                    continue
                parent = psutil.Process(child.pid)
                owned = parent.children(recursive=True)
                for process in reversed(owned):
                    try:
                        process.terminate()
                    except psutil.NoSuchProcess:
                        pass
                parent.terminate()
                _, alive = psutil.wait_procs(owned + [parent], timeout=5)
                for process in alive:
                    process.kill()
                psutil.wait_procs(alive, timeout=5)
                child.wait(timeout=5)


if __name__ == "__main__":
    main()
