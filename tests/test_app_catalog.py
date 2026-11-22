import pytest

from nisha.app_catalog import AppCatalog
from nisha.desktop import DesktopAdapter
from nisha.errors import NishaError


def test_msix_discovery_is_exact_cached_and_refreshable():
    calls = []
    catalog = AppCatalog(
        reader=lambda: (
            calls.append(1)
            or [
                {"Name": "Claude", "AppID": "Claude_package!Claude"},
                {"Name": "Visual Studio Code", "AppID": "Code"},
            ]
        )
    )
    assert catalog.resolve("claude") == "shell:AppsFolder\\Claude_package!Claude"
    assert catalog.resolve("vscode") == "shell:AppsFolder\\Code"
    assert catalog.resolve("Claud") is None
    assert len(calls) == 1
    catalog.all(refresh=True)
    assert len(calls) == 2


def test_ambiguous_app_versions_require_full_name():
    catalog = AppCatalog(
        reader=lambda: [
            {"Name": "Blender 3.6", "AppID": "old"},
            {"Name": "Blender 5.2", "AppID": "new"},
        ]
    )
    with pytest.raises(NishaError, match="Several installed"):
        catalog.resolve("Blender")
    assert catalog.resolve("Blender 5.2") == "shell:AppsFolder\\new"


def test_installed_vendor_and_version_names_resolve_natural_app_names():
    catalog = AppCatalog(
        reader=lambda: [
            {"Name": "Adobe Premiere Pro 2023", "AppID": "premiere"},
            {"Name": "Adobe After Effects 2023", "AppID": "effects"},
        ]
    )
    assert catalog.resolve("Premiere Pro") == "shell:AppsFolder\\premiere"
    assert catalog.resolve("After Effects 2023") == "shell:AppsFolder\\effects"
    assert catalog.resolve("Adobe After Effects 23") == "shell:AppsFolder\\effects"
    assert catalog.resolve("effects") is None


def test_msix_launch_uses_discovered_identifier_without_shell(monkeypatch):
    adapter = DesktopAdapter()
    adapter.catalog = AppCatalog(
        reader=lambda: [{"Name": "Claude", "AppID": "Claude_package!Claude"}]
    )
    calls = []
    monkeypatch.setattr(
        "nisha.desktop.subprocess.Popen", lambda args, **kwargs: calls.append((args, kwargs))
    )
    adapter.open_app("claude")
    assert calls[0][0][0].casefold().endswith("explorer.exe")
    assert calls[0][0][1] == "shell:AppsFolder\\Claude_package!Claude"
    assert calls[0][1]["shell"] is False


def test_on_demand_document_association_launch_escapes_worker_job(tmp_path, monkeypatch):
    path = tmp_path / "user-document.pdf"
    path.write_bytes(b"synthetic fixture")
    calls = []
    monkeypatch.setattr("nisha.desktop.user_app_options", lambda: {"creationflags": 0x01000000})
    monkeypatch.setattr(
        "nisha.desktop.subprocess.Popen", lambda args, **kwargs: calls.append((args, kwargs))
    )
    DesktopAdapter().open_file(path)
    assert calls[0][0][0].casefold().endswith("explorer.exe")
    assert calls[0][0][1] == str(path)
    assert calls[0][1] == {"shell": False, "creationflags": 0x01000000}


def test_app_requests_and_inventory_do_not_fall_back_to_web(core):
    calls = []
    desktop = DesktopAdapter()
    desktop.catalog = AppCatalog(
        reader=lambda: [{"Name": "Claude", "AppID": "Claude_package!Claude"}]
    )
    desktop.open_app = calls.append
    core.workflows.desktop = desktop
    reply = core.chat("open Claude app", core.new_session())
    assert calls == ["claude"]
    assert "installed" in reply and not core.gateway.calls
    assert "couldn't find" in core.chat("open imaginary app", core.new_session())
    assert not core.gateway.calls
