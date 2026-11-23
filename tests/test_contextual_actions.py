from pathlib import Path

from nisha.actions import WebsiteActions


def test_my_pc_drive_followup_stays_in_explorer(core):
    special, folders = [], []
    core.workflows.desktop.open_special = special.append
    core.workflows.desktop.navigate_explorer = lambda path, current: folders.append((path, current))
    core.workflows.desktop.app_path = lambda _name: None
    session = core.new_session()

    assert "Explorer" in core.chat("open My PC", session)
    assert "Explorer" in core.chat("open Local Disk C", session)
    assert special == ["this pc"]
    assert folders == [(Path("C:\\"), "this pc")]
    assert core.system_actions.explorer_location[session] == Path("C:\\").resolve()
    assert not core.gateway.calls


def test_recent_explorer_back_this_pc_and_drive_followups(core, tmp_path):
    child = tmp_path / "AMD"
    child.mkdir()
    moves = []
    core.workflows.desktop.navigate_explorer = lambda path, current: moves.append((path, current))
    core.workflows.desktop.app_path = lambda _name: None
    session = core.new_session()
    core.system_actions.explorer_location[session] = tmp_path
    core.current_surface[session] = tmp_path.name

    assert "same window" in core.chat("Open AMD", session)
    assert core.system_actions.explorer_location[session] == child
    assert "go back" in core.chat("Go back", session)
    assert core.system_actions.explorer_location[session] == tmp_path
    assert "This PC" in core.chat("Go to this PC", session)
    assert core.system_actions.explorer_location[session] == "this pc"
    assert "same window" in core.chat("Local Disk C", session)
    assert core.system_actions.explorer_location[session] == Path("C:\\").resolve()
    assert "This PC" in core.chat("Go to Just PC", session)
    assert "same window" in core.chat("Go to Disk E", session)
    assert core.system_actions.explorer_location[session] == Path("E:\\").resolve()
    assert moves == [
        (child, tmp_path), (tmp_path, child), ("this pc", tmp_path),
        (Path("C:\\"), "this pc"), ("this pc", Path("C:\\").resolve()),
        (Path("E:\\"), "this pc"),
    ]
    assert not core.gateway.calls


def test_misheard_local_dixie_only_maps_to_c_drive_in_this_pc(core):
    core.workflows.desktop.navigate_explorer = lambda *_: None
    session = core.new_session()
    core.system_actions.explorer_location[session] = "this pc"
    reply = core.chat("Go to local Dixie", session)
    assert "same window" in reply
    assert core.system_actions.explorer_location[session] == Path("C:\\").resolve()


def test_folder_followups_use_exact_current_child_and_preserve_unknowns(core, tmp_path):
    child = tmp_path / "Project"
    child.mkdir()
    (tmp_path / "Project.txt").write_text("hello", encoding="utf-8")
    folders, files = [], []
    core.workflows.desktop.navigate_explorer = lambda path, current: folders.append((path, current))
    core.workflows.desktop.open_file = files.append
    core.workflows.desktop.app_path = lambda name: "app.exe" if name == "project" else None
    session = core.new_session()
    core.system_actions.explorer_location[session] = tmp_path
    core.current_surface[session] = tmp_path.name

    assert "default app" in core.chat("open Project.txt", session)
    assert files == [tmp_path / "Project.txt"]
    assert not folders
    assert core.system_actions.explorer_location.get(session) is None
    assert core.current_surface[session] == "Project.txt"
    core.system_actions.explorer_location[session] = tmp_path
    assert "Explorer" in core.chat("open Project", session)
    assert folders == [(child, tmp_path)]
    assert core.system_actions.explorer_location[session] == child.resolve()


def test_last_app_receives_short_controls_and_explicit_app_switches(core):
    launches, controls = [], []
    core.workflows.desktop.app_path = lambda name: "app.exe" if name in {"notepad", "chrome"} else None
    core.workflows.desktop.open_app = launches.append
    original = core.pc_control.handle

    def control(text, current_app=None):
        controls.append((text, current_app))
        return "Clicked 'Save' in Notepad. Check the app for the result." if text == "click Save" else None

    core.pc_control.handle = control
    core.pc_control.launch_and_focus = (
        lambda desktop, name: desktop.open_app(name)
        or "Focused and verified Google Chrome is the foreground window."
    )
    session = core.new_session()
    assert "launch the installed notepad" in core.chat("open Notepad", session).casefold()
    assert core.current_surface[session] == "notepad"
    assert "Clicked" in core.chat("click Save", session)
    assert controls[-1] == ("click Save", "notepad")
    assert "Focused and verified" in core.chat("open Chrome", session)
    assert launches == ["notepad", "chrome"]
    assert core.current_surface[session] == "chrome"
    core.pc_control.handle = original


def test_last_webapp_receives_short_controls(core):
    controls = []
    core.actions = WebsiteActions(lambda *_args, **_kwargs: True)
    core.workflows.desktop.app_path = lambda _name: None

    def control(text, current_app=None):
        controls.append((text, current_app))
        return "Clicked 'Videos' in YouTube. Check the app for the result." if text == "click Videos" else None

    core.pc_control.handle = control
    session = core.new_session()
    assert "YouTube" in core.chat("open YouTube", session)
    assert core.current_surface[session] == "YouTube"
    assert "Clicked" in core.chat("click Videos", session)
    assert controls[-1] == ("click Videos", "YouTube")
    assert "Gmail" in core.chat("open Gmail", session)
    assert core.current_surface[session] == "Gmail"
    assert not core.gateway.calls


def test_open_unknown_item_first_tries_current_app_control(core):
    requested = []
    core.workflows.desktop.app_path = lambda _name: None
    session = core.new_session()
    core.current_surface[session] = "Chrome"
    core.pc_control.handle = lambda *_args, **_kwargs: None
    core.pc_control.open_control = lambda label, app: requested.append((label, app)) or "Opened 'Settings' in Chrome."
    core.actions = WebsiteActions(lambda *_args, **_kwargs: False)

    reply = core.handle_action("open Settings", session, [], "local_fast")
    assert "Opened 'Settings'" in reply
    assert requested == [("settings", "Chrome")]
    assert core.current_surface[session] == "Chrome"


def test_short_search_follows_current_webapp_even_after_other_turns(core):
    searches = []
    core.actions = WebsiteActions(lambda url, **_kwargs: searches.append(url) or True)
    core.workflows.desktop.app_path = lambda _name: None
    session = core.new_session()
    core.chat("open YouTube", session)
    for _ in range(6):
        core.chat("thanks", session)
    reply = core.chat("search Dr Bro", session)
    assert "search YouTube for Dr Bro" in reply
    assert searches[-1].endswith("search_query=Dr+Bro")
    assert core.current_surface[session] == "YouTube"


def test_chrome_short_search_uses_browser_not_new_tab_controls(core):
    searches = []
    core.current_surface["test-session"] = "chrome"
    core.workflows.desktop.search_in_browser = lambda browser, query: searches.append((browser, query))
    core.pc_control.handle = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("UIA used"))
    reply = core.handle_action("Search YouTube", "test-session", [], "local_fast")
    assert searches == [("chrome", "YouTube")]
    assert "Asked chrome" in reply


def test_explicit_chrome_site_overrides_current_youtube_context(core):
    opened = []
    session = core.new_session()
    core.current_surface[session] = "YouTube"
    core.workflows.desktop.open_url_in_browser = lambda browser, url: opened.append((browser, url))
    core.pc_control.handle = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("UIA used"))
    reply = core.handle_action("Open www.youtube.com in Chrome", session, [], "local_fast")
    assert opened == [("chrome", "https://www.youtube.com")]
    assert "chrome" in reply
    assert core.current_surface[session] == "YouTube"


def test_desktop_item_uses_redirected_desktop(core, tmp_path):
    item = tmp_path / "stuti"
    item.mkdir()
    core.workflows.desktop.desktop_directory = lambda: tmp_path
    opened = []
    core.workflows.desktop.open_folder = opened.append
    core.workflows.desktop.app_path = lambda _name: None
    reply = core.chat("open file stuti", core.new_session())
    assert opened == [item]
    assert "is a folder" in reply
