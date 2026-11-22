from time import monotonic

from nisha.microphones import MicSelector, microphone_priority


def mic(index, name, speech, quality=10, alive=True):
    return {
        "index": index,
        "name": name,
        "priority": microphone_priority(name),
        "speech": speech,
        "quality": quality,
        "alive": alive,
        "updated": monotonic(),
    }


def test_headset_usb_webcam_priority_and_silent_headset_fallback():
    time = [monotonic()]
    selector = MicSelector(clock=lambda: time[0])
    headset = mic(1, "Headset Noise Airwave", True)
    usb = mic(2, "Microphone USB Audio Device", True)
    webcam = mic(3, "Microphone HD 4MP WEBCAM", True)
    assert selector.choose([webcam, usb, headset])["index"] == 1
    headset["speech"] = False
    time[0] += 1.3
    for source in [headset, usb, webcam]:
        source["updated"] = time[0]
    assert selector.choose([webcam, usb, headset])["index"] == 2
    usb["alive"] = False
    assert selector.choose([webcam, usb, headset])["index"] == 3


def test_bad_headset_quality_and_uncertain_decode_fall_back():
    selector = MicSelector()
    headset = mic(1, "Noise Airwave headset", True, quality=2)
    usb = mic(2, "USB microphone", True, quality=20)
    assert selector.choose([headset, usb])["index"] == 2
    headset["quality"] = 20
    selector.penalize(1)
    assert selector.choose([headset, usb])["index"] == 2


def test_stale_and_disconnected_sources_are_not_selected():
    selector = MicSelector()
    stale = mic(1, "Noise Airwave headset", True)
    stale["updated"] -= 3
    dead = mic(2, "USB microphone", True, alive=False)
    assert selector.choose([stale, dead]) is None


def test_syllable_gaps_and_quality_fluctuations_do_not_cut_wake_phrase():
    start = monotonic()
    time = [start]
    selector = MicSelector(clock=lambda: time[0])
    usb = mic(2, "USB microphone", False)
    webcam = mic(3, "Webcam microphone", True)
    assert selector.choose([usb, webcam])["index"] == 3
    for offset in [0.1, 0.4, 0.8, 1.1]:
        time[0] = start + offset
        webcam["speech"] = False
        # A preferred device detects a syllable later than the selected source.
        usb["speech"] = True
        usb["updated"] = time[0]
        webcam["updated"] = time[0]
        assert selector.choose([usb, webcam])["index"] == 3
    time[0] = start + 1.3
    usb["updated"] = webcam["updated"] = time[0]
    assert selector.choose([usb, webcam])["index"] == 2


def test_dead_source_breaks_speech_hold_and_silent_preferred_source_does_not_hold():
    selector = MicSelector()
    usb = mic(2, "USB microphone", False)
    webcam = mic(3, "Webcam microphone", False)
    assert selector.choose([usb, webcam])["index"] == 2
    webcam["speech"] = True
    assert selector.choose([usb, webcam])["index"] == 3
    webcam["alive"] = False
    assert selector.choose([usb, webcam])["index"] == 2


def test_system_default_starts_only_one_worker_and_reopens_on_endpoint_change(monkeypatch):
    from types import SimpleNamespace

    from nisha.microphones import AutoMicrophoneStream
    from nisha.settings import VoiceSettings

    identity = ["usb-one", "USB microphone"]
    workers = []

    class Capture:
        def __init__(self, index, name, settings, ready):
            self.index, self.name, self.closed, self.alive = index, name, False, False
            self.thread = SimpleNamespace(is_alive=lambda: self.alive, start=self.start)
            workers.append(self)

        def start(self):
            self.alive = True

        def close(self):
            self.closed = True
            self.alive = False

    monkeypatch.setattr(
        "nisha.system_microphone.system_default_microphone", lambda: tuple(identity)
    )
    monkeypatch.setattr("nisha.microphones.MicCapture", Capture)
    stream = AutoMicrophoneStream(VoiceSettings())
    stream.discover()
    assert list(stream.captures) == [-1] and len(workers) == 1
    assert "USB microphone" in workers[0].name
    stream.discover()
    assert len(workers) == 1  # Unchanged default does not reopen continuously.
    epoch = stream.source_epoch
    identity[:] = ["headset-two", "Default headset"]
    stream.discover()
    assert workers[0].closed and len(workers) == 2
    assert stream.source_epoch == epoch + 1
    assert "Default headset" in workers[1].name
    stream.close()
