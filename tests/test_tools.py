import pytest

from nisha.errors import NishaError
from nisha.tools import ToolService


def test_catalog_describes_registered_safe_and_approval_gated_tools(core, tmp_path):
    tools = ToolService(core.store, tmp_path / "workspace")
    catalog = tools.catalog()
    assert [tool["name"] for tool in catalog] == [
        "list_files", "read_file", "delete_file", "run_terminal_command"
    ]
    delete = next(tool for tool in catalog if tool["name"] == "delete_file")
    assert delete["risk"] == "sensitive"
    assert delete["requires_confirmation"] is True
    terminal = next(tool for tool in catalog if tool["name"] == "run_terminal_command")
    assert terminal["requires_confirmation"] is True
    assert all(tool["name"] != "run_python" for tool in catalog)
    catalog[0]["parameters"]["unexpected"] = "value"
    assert "unexpected" not in tools.catalog()[0]["parameters"]


def test_delete_requires_preview_and_one_use_approval(core, tmp_path):
    trashed = []
    tools = ToolService(core.store, tmp_path / "workspace", trash=trashed.append)
    path = tools.workspace / "note.txt"
    path.write_text("keep this", encoding="utf-8")
    preview = tools.propose("delete_file", "note.txt")
    assert path.exists() and trashed == []
    assert preview["status"] == "confirmation_required"
    tools.confirm(preview["approval_id"], True)
    assert trashed == [str(path)]
    with pytest.raises(NishaError):
        tools.confirm(preview["approval_id"], True)


def test_cancel_and_changed_file_do_not_execute(core, tmp_path):
    trashed = []
    tools = ToolService(core.store, tmp_path / "workspace", trash=trashed.append)
    path = tools.workspace / "note.txt"
    path.write_text("old", encoding="utf-8")
    preview = tools.propose("delete_file", "note.txt")
    tools.confirm(preview["approval_id"], False)
    preview = tools.propose("delete_file", "note.txt")
    path.write_text("new", encoding="utf-8")
    with pytest.raises(NishaError):
        tools.confirm(preview["approval_id"], True)
    assert trashed == []


@pytest.mark.parametrize("name", ["../test.sqlite3", "C:/Windows/system.ini", "note.txt:stream"])
def test_paths_cannot_escape_workspace(core, tmp_path, name):
    tools = ToolService(core.store, tmp_path / "workspace")
    with pytest.raises(NishaError):
        tools.propose("read_file", name)


def test_arbitrary_shell_tools_are_blocked(core, tmp_path):
    tools = ToolService(core.store, tmp_path / "workspace")
    with pytest.raises(NishaError):
        tools.propose("run_python", "anything.py")
