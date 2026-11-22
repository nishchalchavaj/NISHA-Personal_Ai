"""Keep the archived renderer inert to untrusted states/URLs without activating it."""

import base64
import hashlib
import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QUrl

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "archived_orb_security", ROOT / "legacy/prototype/ui/orb_web_widget.py"
)
ORB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ORB)


@pytest.mark.parametrize(
    "state",
    [
        "');fetch('https://attacker.invalid');//",
        "<script>alert(1)</script>",
        "thinking\nalert(1)",
        None,
        [],
    ],
)
def test_archived_webview_rejects_untrusted_state_before_javascript(state):
    dummy = SimpleNamespace(page=lambda: pytest.fail("Untrusted state reached JavaScript"))
    ORB.OrbWebWidget.set_state(dummy, state)


@pytest.mark.parametrize("state", ["idle", "listening", "thinking", "speaking"])
def test_archived_webview_preserves_fixed_state_commands(state):
    calls = []
    dummy = SimpleNamespace(page=lambda: SimpleNamespace(runJavaScript=calls.append))
    ORB.OrbWebWidget.set_state(dummy, state)
    assert calls == [f'setOrbState("{state}");']


@pytest.mark.parametrize(
    "location",
    [
        "https://attacker.invalid/",
        "file:///C:/private.txt",
        "data:text/html,<script>x</script>",
        "javascript:alert(1)",
    ],
)
def test_archived_renderer_blocks_every_non_bundled_resource(location):
    decisions = []
    dummy = SimpleNamespace(allowed={"file:///trusted/orb.html", "file:///trusted/three.min.js"})
    info = SimpleNamespace(requestUrl=lambda: QUrl(location), block=decisions.append)
    ORB.OrbRequests.interceptRequest(dummy, info)
    assert decisions == [True]


def test_archived_renderer_csp_hash_matches_only_the_bundled_inline_script():
    html = (ROOT / "legacy/prototype/ui/orb_web/orb.html").read_text(encoding="utf-8")
    scripts = re.findall(r"<script>([\s\S]*?)</script>", html)
    assert len(scripts) == 1
    digest = base64.b64encode(hashlib.sha256(scripts[0].encode()).digest()).decode()
    assert "'sha256-" + digest + "'" in html
    assert "default-src 'none'" in html and "connect-src 'none'" in html
