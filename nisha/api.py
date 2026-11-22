import hmac
import os
from contextlib import asynccontextmanager

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
