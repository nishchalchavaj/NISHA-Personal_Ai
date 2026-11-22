"""Local, durable review worker; never invokes PC tools, voice, or external models."""

import sys

from dotenv import load_dotenv

from nisha.conversation_learning import ConversationLearning
from nisha.gateway import Gateway
from nisha.logging_setup import configure_logging
from nisha.settings import ROOT, Settings
from nisha.storage import Store


def main():
    load_dotenv(ROOT / ".env", override=False)
    settings = Settings.model_validate_json(sys.stdin.buffer.read())
    configure_logging(settings.data_dir)
    learning = ConversationLearning(settings, Store(settings.data_dir / "nisha.sqlite3"))
    gateway = Gateway(settings)
    try:
        while learning.step(gateway):
            pass
    finally:
        gateway.close()


if __name__ == "__main__":
    main()
