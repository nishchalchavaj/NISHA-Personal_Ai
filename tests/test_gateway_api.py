import json

import httpx
import pytest
from fastapi.testclient import TestClient

from nisha.api import create_app
from nisha.errors import ModelUnavailable
from nisha.gateway import Gateway, write_gateway_config


def test_sse_stream_handles_text_and_done(core):
    chunk = json.dumps({"choices": [{"delta": {"content": "Ready"}}]})

    def respond(request):
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"model_info": {"general.architecture": "llama"}})
        return httpx.Response(200, text="data: " + chunk + "\n\ndata: [DONE]\n\n")

    transport = httpx.MockTransport(respond)
    with httpx.Client(transport=transport) as client:
        gateway = Gateway(core.settings, client)
        assert gateway.complete("local_fast", [{"role": "user", "content": "Hi"}]) == "Ready"


def test_gateway_error_does_not_expose_response_body(core):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(401, text="sk-secret-provider-key")
    )
    with httpx.Client(transport=transport) as client, pytest.raises(ModelUnavailable) as exc:
        Gateway(core.settings, client).complete("local_fast", [])
    assert "sk-secret-provider-key" not in str(exc.value)


def test_incomplete_sse_is_an_error(core):
    def respond(request):
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"model_info": {"general.architecture": "llama"}})
        return httpx.Response(200, text="data: {}\n\n")

    transport = httpx.MockTransport(respond)
    with httpx.Client(transport=transport) as client, pytest.raises(ModelUnavailable):
        Gateway(core.settings, client).complete("local_fast", [])


def test_generated_gateway_has_no_cloud_fallback(core, monkeypatch):
    import yaml

    monkeypatch.setenv("NISHA_GATEWAY_KEY", "test")
    config = yaml.safe_load(write_gateway_config(core.settings).read_text(encoding="utf-8"))
    assert config["general_settings"]["master_key"] == "os.environ/NISHA_GATEWAY_KEY"
    assert "fallbacks" not in config["router_settings"]
    local = config["model_list"][0]["litellm_params"]
    assert local["api_base"] == core.settings.ollama_url
    assert local["timeout"] >= 180 and local["stream_timeout"] >= 180


def test_api_requires_auth_and_enforces_cloud_policy(core, monkeypatch):
    monkeypatch.setenv("NISHA_API_KEY", "test-token")
    client = TestClient(create_app(core.settings, core), base_url="http://127.0.0.1")
    assert client.get("/memories").status_code == 401
    assert client.get("/tools").status_code == 401
    assert client.get("/projects").status_code == 401
    assert client.get("/coding/candidates").status_code == 401
    assert client.get("/diagnostics").status_code == 401
    assert client.post("/computer/screen", json={}).status_code == 401
    assert client.post("/computer/click", json={"target": "Search"}).status_code == 401
    assert client.post("/terminal/prepare", json={}).status_code == 401
    assert client.post("/terminal/stop").status_code == 401
    assert client.get("/terminal/patches/" + "a" * 32).status_code == 401
    assert client.post("/research/web", json={}).status_code == 401
    client.headers["Authorization"] = "Bearer test-token"
    project = core.settings.data_dir / "configured-project"
    project.mkdir()
    (project / "main.py").write_text("print('hello')\n", encoding="utf-8")
    core.connections.save(
        json.dumps(
            {
                "projects": [{"name": "API project", "folder": str(project.resolve())}],
                "default_project": "API project",
            }
        )
    )
    assert client.get("/projects").json()["projects"][0]["name"] == "API project"
    assert client.get("/coding/candidates").json() == {"candidates": []}
    assert client.get("/diagnostics").status_code == 200
    approval = client.post(
        "/coding/candidates/00000000000000000000000000000000/promote",
        json={"approved": False, "confirmation": "PROMOTE"},
    )
    assert approval.status_code == 400
    assert "explicit approval" in approval.json()["detail"]
    inspect = client.post("/coding/inspect", json={"project": "API project"})
    assert inspect.status_code == 200 and "main.py" in inspect.json()["files"]
    catalog = client.get("/tools")
    assert catalog.status_code == 200
    assert [tool["name"] for tool in catalog.json()["tools"]] == [
        "list_files",
        "read_file",
        "delete_file",
        "run_terminal_command",
    ]
    terminal_prepare = client.post(
        "/terminal/prepare",
        json={"shell": "python", "project": "API project", "args": ["-c", "print('api-terminal')"]},
    )
    assert terminal_prepare.status_code == 200
    terminal_run = client.post(
        "/terminal/execute",
        json={"approval_id": terminal_prepare.json()["approval_id"], "approved": True},
    )
    assert terminal_run.status_code == 200 and "api-terminal" in terminal_run.json()["stdout"]
    assert client.post("/terminal/stop").json() == {"status": "no_active_sandbox_command"}
    assert client.get("/terminal/patches/" + "f" * 32).status_code == 404
    web_without_endpoint = client.post(
        "/research/web", json={"query": "public query", "session_id": "unused"}
    )
    assert web_without_endpoint.status_code == 400
    core.screen.analyze = lambda question: f"Local screen result: {question or 'overview'}"
    screen = client.post("/computer/screen", json={"question": "Which app is open?"})
    assert screen.status_code == 200
    assert screen.json() == {"description": "Local screen result: Which app is open?"}
    core.screen.visual_click = lambda target, controller: f"Clicked {target} locally."
    visual_click = client.post("/computer/click", json={"target": "Search icon"})
    assert visual_click.status_code == 200
    assert visual_click.json() == {"result": "Clicked Search icon locally."}
    assert client.post(
        "/computer/click", json={"target": "Search", "coordinates": [10, 20]}
    ).status_code == 422
    session = client.post("/sessions").json()["session_id"]
    rejected = client.post("/chat", json={"text": "Hi", "session_id": session, "model": "cloud"})
    assert rejected.status_code == 400 and core.gateway.calls == []
    accepted = client.post("/chat", json={"text": "Hi", "session_id": session})
    assert accepted.json()["reply"] == "Hello Nishchal."


def test_api_rejects_unknown_fields(core, monkeypatch):
    monkeypatch.setenv("NISHA_API_KEY", "test-token")
    client = TestClient(create_app(core.settings, core), base_url="http://127.0.0.1")
    client.headers["Authorization"] = "Bearer test-token"
    session = client.post("/sessions").json()["session_id"]
    assert (
        client.post(
            "/chat", json={"text": "Hi", "session_id": session, "bypass_privacy": True}
        ).status_code
        == 422
    )


def test_local_residency_cannot_be_attached_to_cloud_provider():
    from nisha.settings import ModelProfile

    with pytest.raises(ValueError):
        ModelProfile(model="openai/test", local=True, context_window=4096, max_output=256)


def test_cloud_backed_ollama_model_never_receives_prompt(core):
    requested = []

    def respond(request):
        requested.append(request.url.path)
        return httpx.Response(200, json={"remote_host": "https://ollama.com"})

    with (
        httpx.Client(transport=httpx.MockTransport(respond)) as client,
        pytest.raises(ModelUnavailable),
    ):
        Gateway(core.settings, client).complete(
            "local_fast", [{"role": "user", "content": "private"}]
        )
    assert requested == ["/api/show"]


@pytest.mark.parametrize("name", ["ollama_chat/gemma:cloud", "ollama_chat/gpt-oss:120b-cloud"])
def test_cloud_ollama_names_are_rejected(name):
    from nisha.settings import ModelProfile

    with pytest.raises(ValueError):
        ModelProfile(model=name, local=True, context_window=4096, max_output=256)
