import pytest

from nisha.core import NishaCore
from nisha.errors import ModelUnavailable
from nisha.settings import ModelProfile, Settings
from nisha.storage import Store


class FakeGateway:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.summary_fail = False

    def stream(self, alias, messages):
        self.calls.append((alias, messages))
        yield "Hello "
        if self.fail:
            raise ModelUnavailable("Simulated outage")
        yield "Nishchal."

    def complete(self, alias, messages):
        if self.summary_fail:
            raise ModelUnavailable("Simulated summary outage")
        return "The user is developing NISHA."

    def close(self):
        pass

    def headers(self):
        return {}


@pytest.fixture
def core(tmp_path):
    settings = Settings(
        instant_smalltalk=False,  # Most unit tests exercise generated-answer paths.
        background_actions=False,  # UI tests explicitly opt in with mocked desktop actions.
        external_tasks_enabled=True,
        data_dir=tmp_path,
        models={
            "local_fast": ModelProfile(
                model="ollama_chat/llama3.2", local=True, context_window=4096, max_output=256
            ),
            "cloud": ModelProfile(
                model="openai/test", local=False, context_window=4096, max_output=256
            ),
        },
        recent_exchanges=2,
    )
    return NishaCore(settings, FakeGateway(), Store(tmp_path / "test.sqlite3"))
