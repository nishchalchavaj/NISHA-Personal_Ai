import json

import httpx
import pytest

from nisha.connections import Connections, ConnectionsConfig
from nisha.devices import Devices
from nisha.errors import NishaError


@pytest.fixture
def connections(tmp_path):
    registry = Connections(tmp_path)
    registry.save(
        json.dumps(
            {
                "devices": [
                    {
                        "id": "desk",
                        "name": "Desk light",
                        "kind": "light",
                        "status": {"url": "http://device.test/status"},
                        "state_key": "power.state",
                        "on": {
                            "url": "http://device.test/on",
                            "method": "POST",
                            "body": {"power": True},
                        },
                        "off": {"url": "http://device.test/off", "method": "POST"},
                    },
                    {
                        "id": "camera",
                        "name": "Front camera",
                        "kind": "camera",
                        "snapshot": {"url": "http://camera.test/snapshot"},
                    },
                ]
            }
        )
    )
    return registry


def test_direct_command_verified_only_by_status(connections):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"power": {"state": "on"}})

    devices = Devices(connections, httpx.Client(transport=httpx.MockTransport(respond)))
    reply = devices.handle("turn on the lights")
    assert "is on (reported by the device)" in reply
    assert [r.method for r in requests] == ["POST", "GET"]
    assert json.loads(requests[0].content) == {"power": True}
    assert "1 of 2" in devices.summary()


def test_ack_does_not_claim_resulting_state(connections):
    def respond(request):
        return httpx.Response(200, json={"power": {"state": "off"}})

    devices = Devices(connections, httpx.Client(transport=httpx.MockTransport(respond)))
    assert "wasn't verified" in devices.handle("turn Desk light on")


def test_offline_age_is_from_actual_success_not_last_attempt(connections):
    now = [1000]
    fail = [False]

    def respond(request):
        if fail[0]:
            raise httpx.ConnectError("network unavailable", request=request)
        return httpx.Response(200, json={"power": {"state": "off"}})

    client = httpx.Client(transport=httpx.MockTransport(respond))
    devices = Devices(connections, client, clock=lambda: now[0])
    light = connections.load().devices[0]
    devices.check(light)
    fail[0] = True
    now[0] += 720
    devices.check(light)
    assert "last response 12m 0s ago" in devices.summary()
    now[0] += 60
    devices.check(light)
    assert "last response 13m 0s ago" in devices.summary()
    restored = Devices(connections, client)
    assert restored.states["desk"].last_seen == 1000
    assert restored.states["desk"].reachable is None


def test_unknown_device_and_never_seen_are_not_invented(connections):
    devices = Devices(connections)
    assert "isn't configured" in devices.handle("turn on garage")
    devices.observe(connections.load().devices[0], False)
    assert "no successful response recorded" in devices.summary()


def test_snapshot_is_readonly_memory_only_and_status_recorded(connections, tmp_path):
    def respond(request):
        assert request.method == "GET"
        return httpx.Response(200, content=b"jpeg-frame", headers={"content-type": "image/jpeg"})

    devices = Devices(connections, httpx.Client(transport=httpx.MockTransport(respond)))
    assets = devices.camera_assets("CCTV camera")
    assert assets[0].location == "camera" and assets[0].kind == "camera_snapshot"
    assert devices.image_bytes(assets[0]) == b"jpeg-frame"
    assert not list(tmp_path.glob("*.jpg"))
    assert "snapshot available" in devices.summary()


def test_snapshot_rejects_html_and_oversize(connections):
    devices = Devices(
        connections,
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, text="login page"))
        ),
    )
    with pytest.raises(NishaError, match="snapshot"):
        devices.image_bytes(devices.camera_assets("CCTV")[0])
    devices.client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, content=b"x" * 8_000_001, headers={"content-type": "image/jpeg"}
            )
        )
    )
    with pytest.raises(NishaError, match="size"):
        devices.image_bytes(devices.camera_assets("CCTV")[0])


def test_http_auth_is_separate_from_saved_config_and_receipts(connections):
    config = connections.load()
    config.devices[0].auth = "bearer"
    connections.save(config.model_dump_json())
    connections.credential = lambda _: {"secret": "private-token", "username": ""}

    def respond(request):
        assert request.headers["Authorization"] == "Bearer private-token"
        return httpx.Response(500, text="private-token")

    devices = Devices(connections, httpx.Client(transport=httpx.MockTransport(respond)))
    assert "private-token" not in devices.handle("turn on desk light")
    assert "private-token" not in connections.path.read_text()


def test_command_does_not_follow_redirects(connections):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "http://other.test"})

    devices = Devices(
        connections, httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=False)
    )
    assert "wasn't confirmed" in devices.handle("turn on lights")
    assert len(calls) == 1


@pytest.mark.parametrize(
    "device",
    [
        {
            "id": "x",
            "name": "X",
            "kind": "camera",
            "stream": "rtsp://user:secret@192.168.1.1/stream",
        },
        {"id": "x", "name": "X", "kind": "light", "status": {"url": "http://x", "method": "POST"}},
        {"id": "x", "name": "X", "kind": "camera", "on": {"url": "http://x"}},
        {"id": "x", "name": "X", "kind": "light", "on": {"url": "http://x?token=secret"}},
    ],
)
def test_invalid_device_configuration_is_rejected(device):
    with pytest.raises(ValueError):
        ConnectionsConfig(devices=[device])


def test_credential_url_only_exists_in_camera_player_input(connections):
    config = connections.load()
    camera = config.devices[1]
    camera.snapshot = None
    camera.stream = "rtsp://192.168.1.60/stream"
    camera.auth = "basic"
    connections.save(config.model_dump_json())
    connections.credential = lambda _: {"username": "viewer", "secret": "private@123"}
    devices = Devices(connections)
    asset = devices.camera_assets("cameras")[0]
    assert asset.location == "camera"
    assert "private%40123" in devices.stream_url(asset)
    assert "private" not in repr(asset) and "private" not in connections.path.read_text()
