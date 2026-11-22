"""Real local-model smoke check using isolated synthetic conversation data."""

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

from nisha.core import NishaCore
from nisha.health import health
from nisha.settings import load_settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="local_fast")
    args = parser.parse_args()
    settings = load_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="verification-", dir=settings.data_dir) as directory:
        root = Path(directory).resolve()
        assert root.is_relative_to(settings.data_dir.resolve())
        settings = settings.model_copy(update={"data_dir": root})
        core = NishaCore(settings)
        try:
            checks = health(core, generate=True)
            assert all(value == "ok" for value in checks.values()), checks
            memory = core.store.remember("The NISHA verification code is SUNRISE42.")
            session = core.new_session()
            reply = core.chat(
                "What is the NISHA verification code? Reply with only the code.",
                session,
                args.model,
            )
            assert "SUNRISE42" in reply.upper(), "Model did not recall the synthetic memory."
            reply = core.chat("Repeat the code from your previous answer.", session, args.model)
            assert "SUNRISE42" in reply.upper(), "Model did not follow the synthetic conversation."
            assert len(core.store.history(session)[1]) == 4
            assert core.store.forget(memory)
            print(
                "PASS: live gateway, Ollama generation, streaming, memory retrieval and conversation context."
            )
        finally:
            core.close()


if __name__ == "__main__":
    main()
