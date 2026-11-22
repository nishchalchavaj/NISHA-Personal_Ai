"""User-configured local connections and declarative routines; never model-generated commands."""

import json
import re
from pathlib import Path
from threading import RLock
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator

from nisha.errors import NishaError


def endpoint(value, camera=False):
    parsed = urlparse(value)
    schemes = {"http", "https", "rtsp", "rtsps"} if camera else {"http", "https"}
    if (
        parsed.scheme not in schemes
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError("Use an HTTP(S) endpoint or camera RTSP URL without embedded credentials.")
    if any(
        word in key.casefold()
        for key in parsed.query.split("&")
        for word in ("password", "token", "secret", "api_key")
    ):
        raise ValueError("Use the masked credential fields instead of secrets in URLs.")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def normalized_trigger(value):
    """Match harmless speech spacing and punctuation differences in saved commands."""
    return re.sub(r"[^\w]+", "", value.casefold())


class Request(StrictModel):
    url: str
    method: Literal["GET", "POST", "PUT"] = "GET"
    body: dict | None = None

    @model_validator(mode="after")
    def validate_request(self):
        endpoint(self.url)
        if self.body and any(
            re.search(r"password|token|secret|api.?key", str(key), re.IGNORECASE)
            for key in self.body
        ):
            raise ValueError(
                "Keep credentials out of request bodies; use the masked device credentials."
            )
        return self


class Device(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["light", "switch", "sensor", "camera"]
    aliases: list[str] = Field(default_factory=list, max_length=12)
    status: Request | None = None
    state_key: str = "state"
    on_state: str = "on"
    off_state: str = "off"
    on: Request | None = None
    off: Request | None = None
    stream: str = ""
    snapshot: Request | None = None
    auth: Literal["none", "bearer", "basic", "digest"] = "none"

    @model_validator(mode="after")
    def validate_device(self):
        if self.stream:
            endpoint(self.stream, camera=True)
        if self.status and self.status.method != "GET":
            raise ValueError("Device status checks must be read-only GET requests.")
        if self.snapshot and self.snapshot.method != "GET":
            raise ValueError("Camera snapshots must use GET.")
        if self.kind in {"camera", "sensor"} and (self.on or self.off):
            raise ValueError("Camera and sensor adapters are read-only.")
        return self


class Step(StrictModel):
    action: Literal[
        "open_folder", "open_file", "open_app", "open_website", "device_on", "device_off",
        "open_chrome_url", "search_chrome", "open_path",
    ]
    target: str = Field(min_length=1, max_length=2048)

    @model_validator(mode="after")
    def normalize_local_path(self):
        if self.action == "open_path":
            value = self.target.strip()
            if len(value) >= 2 and value[0] == value[-1] == '"':
                self.target = value[1:-1]
        return self


class Routine(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    trigger: str = Field(default="", max_length=100)
    aliases: list[str] = Field(default_factory=list, max_length=12)
    steps: list[Step] = Field(min_length=1, max_length=12)


class Project(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    folder: str
    aliases: list[str] = Field(default_factory=list, max_length=12)
    requirements: str = Field(default="", max_length=8000)
    budget: str = Field(default="", max_length=300)
    public_research_query: str = Field(default="", max_length=500)
    presentation: str = ""
    supporting_files: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def validate_paths(self):
        if not Path(self.folder).is_absolute():
            raise ValueError("Project folders must be absolute paths.")
        for item in [self.presentation, *self.supporting_files]:
            if item and not (Path(self.folder) / item).resolve().is_relative_to(
                Path(self.folder).resolve()
            ):
                raise ValueError(
                    "Presentation and supporting files must stay inside the project folder."
                )
        return self


class ConnectionsConfig(StrictModel):
    devices: list[Device] = Field(default_factory=list, max_length=40)
    projects: list[Project] = Field(default_factory=list, max_length=20)
    default_project: str = ""
    routines: list[Routine] = Field(default_factory=list, max_length=30)
    search_url: str = ""

    @model_validator(mode="after")
    def validate_names(self):
        for items in [self.devices, self.projects, self.routines]:
            names = [
                str(name).casefold().strip()
                for item in items
                for name in [item.name, *item.aliases]
            ]
            if len(names) != len(set(names)) or any(not name or len(name) > 80 for name in names):
                raise ValueError(
                    "Names and aliases must be distinct, non-empty and at most 80 characters."
                )
        ids = [device.id for device in self.devices]
        triggers = [normalized_trigger(r.trigger) for r in self.routines if r.trigger.strip()]
        if len(triggers) != len(set(triggers)):
            raise ValueError("Routine command phrases must be distinct.")
        if len(ids) != len(set(ids)):
            raise ValueError("Device IDs must be unique.")
        if self.default_project and self.default_project not in [p.name for p in self.projects]:
            raise ValueError("Choose a configured default project name.")
        if self.search_url:
            endpoint(self.search_url)
        for routine in self.routines:
            for step in routine.steps:
                if (
                    step.action in {"open_folder", "open_file", "open_path"}
                    and not Path(step.target).is_absolute()
                ):
                    raise ValueError("Routine local paths must be absolute paths.")
                if step.action == "open_file" and Path(step.target).suffix.casefold() not in {
                    ".txt",
                    ".md",
                    ".pdf",
                    ".docx",
                    ".pptx",
                    ".xlsx",
                    ".csv",
                }:
                    raise ValueError(
                        "Routine file opening supports documents, not executable files."
                    )
                if step.action in {"open_website", "open_chrome_url"}:
                    endpoint(step.target)
                if step.action == "search_chrome" and not step.target.strip():
                    raise ValueError("Chrome search steps need a query.")
                if step.action.startswith("device_") and step.target not in ids:
                    raise ValueError("Routine device steps must reference a configured device ID.")
        return self


class Connections:
    def __init__(self, data_dir):
        self.path = Path(data_dir) / "connections.json"
        self.lock = RLock()

    def load(self):
        with self.lock:
            if not self.path.exists():
                return ConnectionsConfig()
            try:
                return ConnectionsConfig.model_validate_json(self.path.read_text(encoding="utf-8"))
            except (ValueError, OSError) as exc:
                raise NishaError(
                    "Connections configuration is invalid. Open Ctrl+D to review it."
                ) from exc

    def save(self, raw):
        try:
            config = ConnectionsConfig.model_validate_json(raw)
        except ValueError as exc:
            # Do not echo supplied values; they could contain pasted credentials.
            messages = "; ".join(error["msg"] for error in exc.errors())
            raise NishaError("Configuration wasn't saved: " + messages) from None
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(config.model_dump_json(indent=2), encoding="utf-8")
            temporary.replace(self.path)
        return config

    def credential(self, device_id):
        import win32cred

        try:
            record = win32cred.CredRead("NISHA/Device/" + device_id, win32cred.CRED_TYPE_GENERIC)
            blob = record["CredentialBlob"]
            raw = blob.decode("utf-16-le") if isinstance(blob, bytes) else blob
            return json.loads(raw)
        except Exception as exc:
            raise NishaError("Device credentials are missing. Enter them in Ctrl+D.") from exc

    def save_credential(self, device_id, username, secret):
        import win32cred

        if device_id not in {device.id for device in self.load().devices} or not secret:
            raise NishaError("Choose a configured device and enter its credential.")
        try:
            win32cred.CredWrite(
                {
                    "Type": win32cred.CRED_TYPE_GENERIC,
                    "TargetName": "NISHA/Device/" + device_id,
                    "UserName": username,
                    "CredentialBlob": json.dumps({"username": username, "secret": secret}),
                    "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
                },
                0,
            )
        except Exception as exc:
            raise NishaError(
                "The device credential couldn't be saved in Windows Credential Manager."
            ) from exc


EXAMPLE = {
    "devices": [
        {
            "id": "desk_light",
            "name": "Desk light",
            "kind": "light",
            "aliases": ["lights"],
            "status": {"url": "http://192.168.1.50/status"},
            "state_key": "state",
            "on": {"url": "http://192.168.1.50/power", "method": "POST", "body": {"state": "on"}},
            "off": {"url": "http://192.168.1.50/power", "method": "POST", "body": {"state": "off"}},
            "auth": "none",
        },
        {
            "id": "front_camera",
            "name": "Front camera",
            "kind": "camera",
            "aliases": ["CCTV"],
            "stream": "rtsp://192.168.1.60:554/stream1",
            "snapshot": {"url": "http://192.168.1.60/snapshot.jpg"},
            "auth": "basic",
        },
    ],
    "projects": [
        {
            "name": "My project",
            "folder": "E:\\YOUR_PROJECT",
            "requirements": "Add your requirements",
            "budget": "Add your budget",
            "public_research_query": "",
            "presentation": "",
            "supporting_files": [],
        }
    ],
    "default_project": "My project",
    "routines": [
        {
            "name": "Usual setup",
            "steps": [
                {"action": "open_folder", "target": "E:\\YOUR_PROJECT"},
                {"action": "open_app", "target": "notepad"},
                {"action": "device_on", "target": "desk_light"},
            ],
        }
    ],
    "search_url": "",
}
