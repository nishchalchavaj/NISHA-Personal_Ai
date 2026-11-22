"""Direct HTTP device commands, response-based status, and read-only camera viewing."""

import json
import math
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import RLock
from time import monotonic, time
from urllib.parse import quote, urlparse, urlunparse

import httpx

from nisha.errors import NishaError
from nisha.media import MediaAsset


@dataclass
class DeviceState:
    reachable: bool | None = None
    last_seen: float | None = None
    checked_at: float | None = None
    state: str = "unknown"

    def __post_init__(self):
        for value in (self.last_seen, self.checked_at):
            if value is not None and (
                type(value) not in {int, float} or not math.isfinite(value) or value < 0
            ):
                raise ValueError("Invalid cached device timestamp")
        if self.reachable is not None and type(self.reachable) is not bool:
            raise ValueError("Invalid cached device reachability")
        if not isinstance(self.state, str) or len(self.state) > 120:
            raise ValueError("Invalid cached device state")


class Devices:
    def __init__(self, connections, client=None, clock=time):
        self.connections, self.client, self.clock = connections, client, clock
        self.lock = RLock()
        self.path = connections.path.parent / "device-status.json"
        self.states = {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise TypeError("Invalid device cache")
            self.states = {key: DeviceState(**value) for key, value in raw.items()}
            # A persisted observation does not prove current reachability after a restart.
            for state in self.states.values():
                state.reachable = None
        except (OSError, ValueError, TypeError):
            pass

    def request(self, device, request, image=False):
        headers, auth = {}, None
        if device.auth != "none":
            credential = self.connections.credential(device.id)
            if device.auth == "bearer":
                headers["Authorization"] = "Bearer " + credential["secret"]
            elif device.auth == "digest":
                auth = httpx.DigestAuth(credential["username"], credential["secret"])
            else:
                auth = httpx.BasicAuth(credential["username"], credential["secret"])
        client = self.client or httpx.Client(timeout=3, trust_env=False, follow_redirects=False)
        try:
            deadline = monotonic() + 6
            with client.stream(
                request.method, request.url, json=request.body, headers=headers, auth=auth
            ) as response:
                response.raise_for_status()
                raw = bytearray()
                limit = 8_000_000 if image else 256_000
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > limit or monotonic() > deadline:
                        raise NishaError("The device response exceeded the size or time limit.")
                if image:
                    if not response.headers.get("content-type", "").startswith("image/"):
                        raise NishaError("The camera didn't return an image snapshot.")
                    return bytes(raw)
                try:
                    return json.loads(raw) if raw else {}
                except ValueError:
                    return {"state": bytes(raw).decode("utf-8", errors="replace").strip()[:120]}
        except (httpx.HTTPError, OSError) as exc:
            # Never include endpoints, authentication headers or camera passwords in receipts/logs.
            raise NishaError(
                "The device didn't return a successful response. Check its connection and credentials."
            ) from exc
        finally:
            if not self.client:
                client.close()

    def observe(self, device, reachable, value=None):
        with self.lock:
            previous = self.states.setdefault(device.id, DeviceState())
            previous.checked_at = self.clock()
            previous.reachable = reachable
            if reachable:
                previous.last_seen = previous.checked_at
                state = value
                if isinstance(value, dict):
                    for key in device.state_key.split("."):
                        state = state.get(key) if isinstance(state, dict) else None
                previous.state = (
                    str(state)[:80] if isinstance(state, (str, bool, int, float)) else "unknown"
                )
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps({key: vars(value) for key, value in self.states.items()}),
                encoding="utf-8",
            )
            temporary.replace(self.path)

    def check(self, device):
        request = device.status or (device.snapshot if device.kind == "camera" else None)
        if not request:
            return  # A camera stream alone isn't a health endpoint.
        try:
            result = self.request(device, request, image=request is device.snapshot)
            self.observe(device, True, result if request is device.status else "snapshot available")
        except NishaError:
            self.observe(device, False)

    def poll(self):
        devices = self.connections.load().devices
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(self.check, devices))
        return self.summary()

    def summary(self):
        devices = self.connections.load().devices
        if not devices:
            return "No devices configured. Open Ctrl+D or say 'setup devices' to add them."
        with self.lock:
            states = {device.id: self.states.get(device.id, DeviceState()) for device in devices}
            online = sum(state.reachable is True for state in states.values())
            lines = [f"{online} of {len(devices)} devices responded to their latest checks."]
            for device in devices:
                state = states[device.id]
                if state.reachable is True:
                    age = max(0, int(self.clock() - state.checked_at))
                    detail = f"reachable · {state.state} · checked {age}s ago"
                elif state.reachable is False:
                    age = max(0, int(self.clock() - state.last_seen)) if state.last_seen else None
                    detail = "didn't respond to the latest check"
                    detail += (
                        f" · last response {age // 60}m {age % 60}s ago"
                        if age is not None
                        else " · no successful response recorded"
                    )
                else:
                    detail = "not checked; configure a GET status or snapshot endpoint"
                lines.append(f"{device.name}: {detail}")
        return "\n".join(lines)

    def matches(self, name, kinds=None):
        name = name.casefold().strip().removeprefix("the ").removeprefix("my ")
        devices = [
            device
            for device in self.connections.load().devices
            if not kinds or device.kind in kinds
        ]
        exact = [
            d
            for d in devices
            if name in {d.id.casefold(), d.name.casefold(), *(a.casefold() for a in d.aliases)}
        ]
        if exact:
            return exact
        if name in {"lights", "all lights", "the lights"}:
            return [d for d in devices if d.kind == "light"]
        if name in {
            "cctv",
            "cctv camera",
            "cctv cameras",
            "cameras",
            "camera",
            "camera visuals",
            "all cameras",
            "all cctv cameras",
        }:
            return [d for d in devices if d.kind == "camera"]
        return []

    def control(self, device, enabled):
        request = device.on if enabled else device.off
        if device.kind not in {"light", "switch"} or not request:
            return f"{device.name}: that action isn't configured."
        try:
            self.request(device, request)
            self.observe(device, True)
        except NishaError:
            self.observe(device, False)
            return f"{device.name}: the command wasn't confirmed. Check its connection and credentials."
        self.check(device)
        state = self.states.get(device.id)
        expected = device.on_state if enabled else device.off_state
        if (
            device.status
            and state
            and state.reachable
            and state.state.casefold() == expected.casefold()
        ):
            return f"{device.name} is {'on' if enabled else 'off'} (reported by the device)."
        return f"{device.name} accepted the {'on' if enabled else 'off'} request; its resulting state wasn't verified."

    def handle(self, text, check_cancelled=None):
        text = text.casefold().strip(" .!?")
        if re.fullmatch(
            r"(?:what(?:'s| is) (?:the )?status of (?:the |my )?devices|(?:show|check|list) (?:my |the )?devices|device status)",
            text,
        ):
            return self.poll()
        command = re.fullmatch(r"(?:please )?(?:turn|switch) (on|off) (.+)", text)
        reverse = re.fullmatch(r"(?:please )?(?:turn|switch) (.+) (on|off)", text)
        if reverse:
            enabled, name = reverse[2] == "on", reverse[1]
        elif command:
            enabled, name = command[1] == "on", command[2]
        else:
            return None
        devices = self.matches(name, {"light", "switch"})
        if not devices:
            return "That device isn't configured. Open Ctrl+D to add its direct control endpoints."
        results = []
        for device in devices:
            if check_cancelled:
                check_cancelled()
            results.append(self.control(device, enabled))
        return "\n".join(results)

    def camera_assets(self, name):
        assets = []
        for device in self.matches(name, {"camera"}):
            if device.snapshot:
                assets.append(
                    MediaAsset(
                        "camera_snapshot",
                        device.name,
                        device.id,
                        caption="Live snapshots · kept in memory only",
                    )
                )
            elif device.stream:
                # Resolve credentials only inside the display adapter; the URL never enters chat history.
                assets.append(
                    MediaAsset(
                        "camera_stream",
                        device.name,
                        device.id,
                        caption="Live camera · audio muted · no recording",
                    )
                )
        return assets

    def image_bytes(self, asset):
        device = next((d for d in self.connections.load().devices if d.id == asset.location), None)
        if not device or not device.snapshot:
            raise NishaError("The configured camera snapshot is unavailable.")
        try:
            image = self.request(device, device.snapshot, image=True)
            self.observe(device, True, "snapshot available")
            return image
        except NishaError:
            self.observe(device, False)
            raise

    def stream_url(self, asset):
        device = next((d for d in self.connections.load().devices if d.id == asset.location), None)
        if not device or not device.stream:
            raise NishaError("The camera stream isn't configured.")
        url = device.stream
        if device.auth in {"basic", "digest"}:
            credential = self.connections.credential(device.id)
            parsed = urlparse(url)
            authority = (
                quote(credential["username"], safe="")
                + ":"
                + quote(credential["secret"], safe="")
                + "@"
                + parsed.netloc
            )
            url = urlunparse(parsed._replace(netloc=authority))
        elif device.auth == "bearer":
            raise NishaError("Use a snapshot endpoint for bearer-authenticated cameras.")
        return url
