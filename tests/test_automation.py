import json
from zipfile import ZipFile

import httpx
import pytest

from nisha.actions import WebsiteActions
from nisha.connections import ConnectionsConfig, Routine


class Desktop:
    def __init__(self):
        self.opened = []

    def app_path(self, name):
        return "notepad.exe" if name == "notepad" else None

    def open_app(self, name):
        self.opened.append(("app", name))

    def open_folder(self, path):
        self.opened.append(("folder", path))

    def open_file(self, path):
        self.opened.append(("file", path))

    def open_path(self, path):
        self.opened.append(("path", path))

    def open_url_in_browser(self, name, url):
        self.opened.append(("url", name, url))

    def search_in_browser(self, name, query):
        self.opened.append(("search", name, query))


@pytest.fixture
def automation(core, tmp_path):
    folder = tmp_path / "Project"
    folder.mkdir()
    desktop = Desktop()
    core.workflows.desktop = desktop
    core.connections.save(
        json.dumps(
            {
                "projects": [
                    {
                        "name": "Test project",
                        "folder": str(folder),
                        "requirements": "48V motor with warranty",
                        "budget": "INR 10000",
                        "public_research_query": "48V motor options",
                        "presentation": "deck.pptx",
                        "supporting_files": ["requirements.md"],
                    }
                ],
                "default_project": "Test project",
            }
        )
    )
    return core, folder, desktop


def test_folder_command_invokes_adapter_not_model(automation):
    core, folder, desktop = automation
    assert "Explorer" in core.chat("open my project folder", core.new_session())
    assert desktop.opened == [("folder", folder)]
    assert not core.gateway.calls


def test_missing_config_and_routine_dont_generate_fake_actions(core):
    session = core.new_session()
    assert "Ctrl+D" in core.chat("open my project folder", session)
    assert "isn't saved" in core.chat("do the usual setup", session)
    assert "Ctrl+D" in core.chat("prepare everything for tomorrow's presentation", session)
    assert not core.gateway.calls


def test_routine_runs_only_saved_steps_and_stops_after_failure(automation):
    core, folder, desktop = automation
    config = core.connections.load()
    config.routines = [
        Routine.model_validate(
            {
                "name": "usual setup",
                "steps": [
                    {"action": "open_folder", "target": str(folder)},
                    {"action": "open_file", "target": str(folder / "missing.pdf")},
                    {"action": "open_app", "target": "notepad"},
                ],
            }
        )
    ]
    core.connections.save(config.model_dump_json())
    result = core.chat("do the usual setup", core.new_session())
    assert "Remaining steps stopped" in result
    assert desktop.opened == [("folder", folder)]


def test_custom_command_runs_ordered_browser_and_app_steps(automation):
    core, _, desktop = automation
    config = core.connections.load()
    config.routines = [Routine.model_validate({
        "name": "College studies",
        "trigger": "Get ready for College studies",
        "steps": [
            {"action": "open_chrome_url", "target": "https://www.youtube.com/watch?v=abc123"},
            {"action": "search_chrome", "target": "Python class course notes"},
            {"action": "open_app", "target": "notepad"},
        ],
    })]
    core.connections.save(config.model_dump_json())
    result = core.chat("Get ready for College studies", core.new_session())
    assert "Chrome" in result
    assert desktop.opened == [
        ("url", "chrome", "https://www.youtube.com/watch?v=abc123"),
        ("search", "chrome", "Python class course notes"),
        ("app", "notepad"),
    ]
    assert not core.gateway.calls


def test_routine_opens_saved_local_path(automation):
    core, folder, desktop = automation
    config = core.connections.load()
    config.routines = [Routine.model_validate({
        "name": "Timepass",
        "trigger": "Let's Time Pass",
        "steps": [{"action": "open_path", "target": f'"{folder}"'}],
    })]
    core.connections.save(config.model_dump_json())

    assert "Asked Windows to open" in core.chat("Let's Time Pass", core.new_session())
    assert desktop.opened == [("path", folder)]
    assert core.connections.load().routines[0].steps[0].target == str(folder)


def test_saved_routine_learns_actual_actions_not_transcript_guesses(automation):
    core, folder, desktop = automation
    session = core.new_session()
    core.chat("open my project folder", session)
    result = core.chat("remember this as usual setup", session)
    assert "Saved routine" in result
    config = core.connections.load()
    assert config.routines[0].steps[0].target == str(folder)
    assert "already exists" in core.chat(
        "remember this as usual setup", session
    ) or "First perform" in core.chat("remember this as usual setup", session)
    core.chat("do the usual setup", session)
    assert desktop.opened[-1] == ("folder", folder)


def test_no_cross_session_routine_learning(automation):
    core, _, _ = automation
    core.chat("open my project folder", core.new_session())
    assert "First perform" in core.chat("remember this as usual setup", core.new_session())


def test_named_unknown_folder_does_not_launch_default_project(automation):
    core, _, desktop = automation
    assert "Ctrl+D" in core.chat("open unrelated folder", core.new_session())
    assert not desktop.opened


def test_successful_website_action_can_be_saved_in_a_routine(automation):
    core, _, _ = automation
    core.actions = WebsiteActions(lambda *args, **kwargs: True)
    session = core.new_session()
    core.chat("open youtube", session)
    core.chat("remember this as video setup", session)
    step = core.connections.load().routines[0].steps[0]
    assert step.action == "open_website" and step.target == "https://www.youtube.com/"


def test_question_about_presentation_does_not_prepare_files(automation):
    core, _, desktop = automation
    core.chat("how do I prepare a presentation?", core.new_session())
    assert not desktop.opened and not list(core.workflows.workspace.glob("presentation-ready-*"))


@pytest.mark.parametrize(
    "step",
    [
        {"action": "shell", "target": "del *"},
        {"action": "open_file", "target": "C:\\temp\\script.ps1"},
        {"action": "open_folder", "target": "relative"},
        {"action": "device_on", "target": "unknown"},
    ],
)
def test_routines_reject_unknown_commands_and_executables(step):
    with pytest.raises(ValueError):
        ConnectionsConfig(routines=[{"name": "usual setup", "steps": [step]}])


def test_project_paths_cannot_escape_selected_root(tmp_path):
    with pytest.raises(ValueError):
        ConnectionsConfig(
            projects=[
                {"name": "Project", "folder": str(tmp_path), "supporting_files": ["../secret.txt"]}
            ]
        )


def test_presentation_bundle_copies_real_files_and_notes(automation):
    core, folder, desktop = automation
    deck = folder / "deck.pptx"
    with ZipFile(deck, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/></Types>',
        )
        archive.writestr(
            "ppt/presentation.xml",
            '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>',
        )
        archive.writestr(
            "ppt/slides/slide1.xml",
            '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:t>48V project deadline</a:t></p:sld>',
        )
    (folder / "requirements.md").write_text("Budget INR 10000")
    calls = []

    def generate(*args):
        calls.append(args)
        return "Speaker notes: explain the motor requirement. Verify cost."

    core.generate_content = generate
    result = core.chat("prepare everything for tomorrow's presentation", core.new_session())
    assert "48V project deadline" in calls[0][0]
    bundle = next(core.workflows.workspace.glob("presentation-ready-*"))
    assert (bundle / "01-deck.pptx").read_bytes() == deck.read_bytes()
    assert "Verify cost" in (bundle / "speaker-notes.txt").read_text()
    assert json.loads((bundle / "readiness.json").read_text())["issues"] == []
    assert desktop.opened == [("folder", bundle), ("file", deck)]
    assert "2 files" in result and deck.exists()


def test_presentation_requires_explicit_deck_and_reports_missing_files(automation):
    core, _, _ = automation
    session = core.new_session()
    assert "isn't available" in core.chat("prepare tomorrow's presentation", session)
    config = core.connections.load()
    config.projects[0].presentation = ""
    core.connections.save(config.model_dump_json())
    assert "Choose the presentation" in core.chat("prepare tomorrow's presentation", session)


def test_research_sends_only_public_query_and_compares_locally(automation):
    core, _, _ = automation
    config = core.connections.load()
    config.search_url = "http://127.0.0.1:8888/search"
    config.projects[0].requirements += " PRIVATE_PROJECT_DETAIL"
    core.connections.save(config.model_dump_json())
    requests, prompts = [], []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Motor A",
                        "url": "https://example.org/motor",
                        "content": "48V, warranty 2 years",
                    }
                ]
            },
        )

    core.automation.client = httpx.Client(transport=httpx.MockTransport(respond))
    core.generate_content = lambda *args: (
        prompts.append(args[0]) or "Compare warranty; price is unverified."
    )
    result = core.chat("find the best option for this project", core.new_session())
    assert "PRIVATE_PROJECT_DETAIL" not in str(requests[0].url)
    assert requests[0].url.params["q"] == "48V motor options"
    assert "PRIVATE_PROJECT_DETAIL" in prompts[0]
    assert "https://example.org/motor" in result


def test_research_missing_budget_and_search_failure_are_truthful(automation):
    core, _, _ = automation
    config = core.connections.load()
    config.search_url = "http://127.0.0.1:8888/search"
    core.connections.save(config.model_dump_json())
    core.automation.client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(403))
    )
    assert "didn't provide usable results" in core.chat("find the best option", core.new_session())
    config.projects[0].budget = ""
    core.connections.save(config.model_dump_json())
    assert "budget" in core.chat("find the best option", core.new_session())
