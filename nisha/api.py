import hmac
import os
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class ImprovementRequest(BaseModel):
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


class CandidateCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class CandidateVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suite: Literal["pytest", "ruff"] = "pytest"


class CandidateRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=1000)


class CandidateApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved: bool
    confirmation: Literal["PROMOTE", "ROLLBACK"]


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=80)
    query: str = Field(min_length=2, max_length=500)


class WebResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=2, max_length=500)
    session_id: str = Field(min_length=1, max_length=100)
    model: str = "auto"


class DebugRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str | None = Field(default=None, max_length=80)
    query: str | None = Field(default=None, max_length=500)


class TerminalPrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shell: Literal["powershell", "cmd", "python", "git"]
    project: str = Field(min_length=1, max_length=80)
    args: list[str] | None = Field(default=None, max_length=32)
    script: str | None = Field(default=None, max_length=12000)

    @model_validator(mode="after")
    def validate_command_kind(self):
        if (self.args is None) == (self.script is None):
            raise ValueError("Supply args for Python/Git or script for PowerShell/CMD, not both.")
        if self.shell in {"powershell", "cmd"} and self.script is None:
            raise ValueError("PowerShell and CMD require a script.")
        if self.shell in {"python", "git"} and self.args is None:
            raise ValueError("Python and Git require an argument list.")
        return self


class TerminalApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_id: str = Field(pattern=r"^[0-9a-f]{32}$")
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

    @app.get("/tools")
    def list_tools():
        return {"tools": tools.catalog()}

    @app.post("/terminal/prepare")
    def prepare_terminal(request: TerminalPrepareRequest):
        try:
            return instance.terminal.prepare(
                request.shell, request.project, args=request.args, script=request.script
            )
        except (NishaError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/terminal/execute")
    def execute_terminal(request: TerminalApprovalRequest):
        try:
            return instance.terminal.execute(request.approval_id, request.approved)
        except (NishaError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/terminal/stop")
    def stop_terminal():
        return instance.terminal.stop()

    @app.get("/terminal/patches/{patch_id}")
    def read_terminal_patch(patch_id: str):
        try:
            return instance.terminal.read_patch(patch_id)
        except NishaError as exc:
            raise HTTPException(404, str(exc)) from exc

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

    @app.post("/coding/improve")
    def run_improvement(request: ImprovementRequest):
        try:
            return instance.improvement.run(
                request.goal,
                request.project,
                request.files,
                instance,
                request.session_id,
                request.model,
            )
        except (NishaError, OSError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/coding/verify")
    def verify_project(request: CodingVerifyRequest):
        try:
            return instance.coding.verify(request.project, request.suite)
        except (NishaError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/coding/candidates")
    def create_candidate(request: CandidateCreateRequest):
        try:
            return instance.candidates.create(request.proposal_id)
        except (NishaError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/coding/candidates")
    def list_candidates():
        return {"candidates": instance.candidates.list()}

    @app.post("/coding/candidates/{experiment_id}/verify")
    def verify_candidate(experiment_id: str, request: CandidateVerifyRequest):
        try:
            return instance.candidates.verify(experiment_id, request.suite)
        except (NishaError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/coding/candidates/{experiment_id}/reject")
    def reject_candidate(experiment_id: str, request: CandidateRejectRequest):
        try:
            return instance.candidates.reject(experiment_id, request.reason)
        except (NishaError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/coding/candidates/{experiment_id}/promote")
    def promote_candidate(experiment_id: str, request: CandidateApprovalRequest):
        try:
            return instance.candidates.promote(
                experiment_id, request.approved, request.confirmation
            )
        except (NishaError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/coding/candidates/{experiment_id}/rollback")
    def rollback_candidate(experiment_id: str, request: CandidateApprovalRequest):
        try:
            return instance.candidates.rollback(
                experiment_id, request.approved, request.confirmation
            )
        except (NishaError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/coding/candidates/{experiment_id}/benchmark")
    def benchmark_candidate(experiment_id: str):
        try:
            return instance.candidates.benchmark(experiment_id)
        except (NishaError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/research")
    def research(request: ResearchRequest):
        try:
            return instance.diagnostics.research(request.project, request.query)
        except NishaError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/research/web")
    def web_research(request: WebResearchRequest):
        try:
            return instance.research_agent.research(
                request.query, instance, request.session_id, request.model
            )
        except (NishaError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/debug")
    def debug(request: DebugRequest):
        try:
            return instance.diagnostics.debug(request.project, request.query)
        except NishaError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/diagnostics")
    def diagnostics():
        return instance.diagnostics.analyze()

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
