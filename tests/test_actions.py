import pytest

from nisha.actions import WebsiteActions


@pytest.mark.parametrize(
    "text", ["OPEN YOUTUBE", "Nisha, open YouTube", "Could you open YouTube please?"]
)
def test_explicit_website_request_executes_and_records_result(core, text):
    calls = []
    core.actions = WebsiteActions(lambda url, new: calls.append((url, new)) or True)
    session = core.new_session()
    reply = core.chat(text, session)
    assert calls == [("https://www.youtube.com/", 2)]
    assert "default browser" in reply
    assert not core.gateway.calls
    assert core.store.history(session)[1][-1]["content"] == reply


@pytest.mark.parametrize("result", [False, OSError("No browser")])
def test_failed_browser_launch_never_claims_success(core, result):
    def open_browser(*args, **kwargs):
        if isinstance(result, Exception):
            raise result
        return result

    core.actions = WebsiteActions(open_browser)
    reply = core.chat("open youtube", core.new_session())
    assert "couldn't open" in reply
    assert not core.gateway.calls


def test_unsupported_commands_never_reach_model_or_shell(core):
    calls = []
    core.actions = WebsiteActions(lambda *args, **kwargs: calls.append(args))
    reply = core.chat("open cmd.exe /c erase files", core.new_session())
    assert "haven't opened anything" in reply
    assert not calls and not core.gateway.calls


def test_mentioning_site_does_not_open_it_and_follow_up_resolves_context(core):
    calls = []
    core.actions = WebsiteActions(lambda url, new: calls.append(url) or True)
    session = core.new_session()
    core.chat("Tell me about YouTube", session)
    assert not calls
    core.chat("Open it", session)
    assert calls == ["https://www.youtube.com/"]
    core.chat("What was that website?", session)
    messages = core.gateway.calls[-1][1]
    assert any("default browser" in item["content"] for item in messages)


def test_ambiguous_website_follow_up_does_not_choose_for_user(core):
    calls = []
    core.actions = WebsiteActions(lambda *args, **kwargs: calls.append(args))
    session = core.new_session()
    core.chat("Compare YouTube and Wikipedia", session)
    assert "haven't opened" in core.chat("open it", session)
    assert not calls


def test_cloud_route_still_rejected_before_action(core):
    from nisha.errors import PrivacyError

    calls = []
    core.actions = WebsiteActions(lambda *args, **kwargs: calls.append(args))
    with pytest.raises(PrivacyError):
        core.chat("open youtube", core.new_session(), "cloud")
    assert not calls


@pytest.mark.parametrize(
    "spoken_request,url",
    [
        ("open example dot org", "https://example.org"),
        ("open example.com/about", "https://example.com/about"),
        ("open https://docs.python.org/3/", "https://docs.python.org/3/"),
        ("OpenExample.org", "https://example.org"),
    ],
)
def test_spoken_and_literal_custom_domains(core, spoken_request, url):
    calls = []
    core.actions = WebsiteActions(lambda target, new: calls.append(target) or True)
    core.chat(spoken_request, core.new_session())
    assert calls == [url]


def test_custom_domain_follow_up_uses_recent_context(core):
    calls = []
    core.actions = WebsiteActions(lambda url, new: calls.append(url) or True)
    session = core.new_session()
    core.chat("open example dot org", session)
    core.chat("open it", session)
    assert calls == ["https://example.org", "https://example.org"]


@pytest.mark.parametrize(
    "target",
    [
        "javascript:alert(1)",
        "file:///C:/secret",
        "cmd.exe /c erase",
        "https://user:password@example.com",
    ],
)
def test_browser_targets_never_accept_executables_or_unsafe_schemes(core, target):
    calls = []
    core.actions = WebsiteActions(lambda *args, **kwargs: calls.append(args))
    core.chat("open " + target, core.new_session())
    assert not calls
