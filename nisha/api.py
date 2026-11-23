import hmac
import os
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from nisha.api_security import LocalApiBoundary
from nisha.core import NishaCore
from nisha.errors import NishaError
from nisha.health import health
from nisha.tools import ToolService


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=50_000)
    session_id: str
    model: str = "auto"


class MemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=2000)
    key: str | None = None
    category: str = "fact"


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str
    path: str = ""


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_id: str
    approved: bool


class ScreenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str | None = Field(default=None, max_length=500)


class CodingInspectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=80)
    path: str | None = Field(default=None, max_length=1024)
    pattern: str | None = Field(default=None, max_length=200)


class CodingProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=80)
    goal: str = Field(min_length=1, max_length=4000)
    files: list[str] = Field(min_length=1, max_length=8)
    session_id: str = Field(min_length=1, max_length=100)
    model: str = "auto"


class CodingVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=80)
    suite: Literal["pytest", "ruff"] = "pytest"


def create_app(settings, core=None):
    api_key = os.getenv("NISHA_API_KEY", "")
    if not api_key:
        raise NishaError("NISHA_API_KEY is missing. Run scripts/setup.ps1 before starting the API.")
    instance = core or NishaCore(settings)
    tools = ToolService(instance.store, settings.data_dir / "workspace")

    def authenticate(authorization: str = Header(default="")):
        if not hmac.compare_digest(
            authorization.encode("utf-8"), ("Bearer " + api_key).encode("utf-8")
        ):
            raise HTTPException(401, "Authentication required.")

    @asynccontextmanager
    async def lifespan(app):
        yield
        instance.close()

    app = FastAPI(
        title="NISHA Core",
        version="0.1.0",
        lifespan=lifespan,
        dependencies=[Depends(authenticate)],
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(LocalApiBoundary)

    @app.get("/health")
    def check_health():
        checks = health(instance)
        return {"ready": all(value == "ok" for value in checks.values()), "components": checks}

    @app.post("/sessions")
    def new_session():
        return {"session_id": instance.new_session()}

    @app.post("/chat")
    def chat(request: ChatRequest):
        try:
            reply = instance.chat(request.text, request.session_id, request.model)
            return {"session_id": request.session_id, "reply": reply}
        except (NishaError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/memories")
    def memories():
        return instance.memory.memories()

    @app.post("/memories")
    def remember(request: MemoryRequest):
        try:
            return {"id": instance.memory.remember(**request.model_dump())}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.delete("/memories/{memory_id}")
    def forget(memory_id: str):
        return {"deleted": instance.memory.forget(memory_id)}

    @app.get("/tools")
    def list_tools():
        return {"tools": tools.catalog()}

    @app.post("/computer/screen")
    def analyze_screen(request: ScreenRequest):
        try:
            return {"description": instance.screen.analyze(request.question)}
        except (NishaError, OSError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/projects")
    def list_projects():
        try:
            return {"projects": instance.coding.projects()}
        except NishaError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/coding/inspect")
    def inspect_project(request: CodingInspectRequest):
        try:
            if request.path:
                return instance.coding.read_file(request.project, request.path)
            if request.pattern:
                return {"matches": instance.coding.search(request.project, request.pattern)}
            return {"files": instance.coding.list_files(request.project)}
        except NishaError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/coding/propose")
    def propose_coding_change(request: CodingProposalRequest):
        try:
            return instance.coding.propose(
                request.goal,
                request.project,
                request.files,
                instance,
                request.session_id,
                request.model,
            )
        except (NishaError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/coding/verify")
    def verify_project(request: CodingVerifyRequest):
        try:
            return instance.coding.verify(request.project, request.suite)
        except (NishaError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/tools/propose")
    def propose(request: ToolRequest):
        try:
            return tools.propose(request.action, request.path)
        except (NishaError, OSError, UnicodeError) as exc:
            raise HTTPException(
                400, str(exc) if isinstance(exc, NishaError) else "File operation failed."
            ) from exc

    @app.post("/tools/confirm")
    def confirm(request: ApprovalRequest):
        try:
            return tools.confirm(request.approval_id, request.approved)
        except (NishaError, OSError) as exc:
            raise HTTPException(
                400, str(exc) if isinstance(exc, NishaError) else "File operation failed."
            ) from exc

    return app
