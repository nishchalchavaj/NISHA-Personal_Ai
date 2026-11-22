"""Monitor prioritized microphones concurrently and choose usable speech."""

import logging
from collections import deque
from time import monotonic

import numpy as np

logger = logging.getLogger("nisha")


def microphone_priority(name):
    name = name.casefold()
    if "airwave" in name or "noise" in name and "headset" in name:
        return 0
    if "usb" in name and "microphone" in name:
        return 1
    if "webcam" in name or "4mp" in name:
        return 2
    return 3


class MicSelector:
    def __init__(self, clock=monotonic, hold_seconds=1.2):
        self.clock = clock
        self.hold_seconds = hold_seconds
        self.penalties = {}
        self.selected_index = None
        self.last_speech = float("-inf")

    def penalize(self, index):
        self.penalties[index] = self.clock() + 30

    def choose(self, snapshots):
        now = self.clock()
        usable = [item for item in snapshots if item["alive"] and now - item["updated"] < 1]
        if not usable:
            return None
        speaking = [item for item in usable if item["speech"] and item["quality"] >= 1.3]
        current = next((item for item in usable if item["index"] == self.selected_index), None)
        # VAD and quality fluctuate between syllables. Changing inputs at each
        # fluctuation cuts the wake phrase and resets the listener's speech buffer.
        # Keep a healthy source through the speech and its endpoint; dead/stale
        # inputs still fall back immediately, and silent inputs never earn a hold.
        if current is not None and self.penalties.get(current["index"], 0) <= now:
            if current["speech"] and current["quality"] >= 1.3:
                self.last_speech = now
            if now - self.last_speech < self.hold_seconds:
                return current
        if speaking:
            best = max(item["quality"] for item in speaking)
            candidates = [item for item in speaking if item["quality"] >= best * 0.3]
        else:
            candidates = usable
        selected = min(
            candidates,
            key=lambda item: (
                self.penalties.get(item["index"], 0) > now,
                item["priority"],
                -item["quality"],
            ),
        )
        if selected["index"] != self.selected_index:
            self.last_speech = float("-inf")
        self.selected_index = selected["index"]
        if selected["speech"] and selected["quality"] >= 1.3:
            self.last_speech = now
        return selected


def capture_microphone(index, settings, samples, metadata, lock, stop, ready, enabled, paused_ack):
    """Keep the worker warm; close hardware while muted or NISHA is speaking."""
    import sounddevice as sd

    from nisha.listening import SpeechDetector

    detector = SpeechDetector(settings.vad_threshold)
    noise = 0.001
    array = np.frombuffer(samples, dtype=np.float32).reshape(12, 1600)
    while not stop.is_set():
        if not enabled.is_set():
            paused_ack.set()
            stop.wait(0.05)
            continue
        paused_ack.clear()
        detector.reset()
        try:
            with sd.InputStream(
                samplerate=16000, channels=1, dtype="float32", device=None if index == -1 else index
            ) as stream:
                while not stop.is_set() and enabled.is_set():
                    block, overflow = stream.read(1600)
                    block = np.asarray(block, dtype=np.float32).reshape(-1)
                    speech = detector.feed(block) if not overflow else False
                    rms = float(np.sqrt(np.mean(block * block)))
                    if not speech:
                        noise = 0.95 * noise + 0.05 * max(rms, 0.0001)
                    quality = rms / max(noise, 0.0001)
                    if np.mean(np.abs(block) >= 0.98) > 0.02:
                        quality = 0
                    with lock:
                        version = int(metadata[0])
                        array[version % 12] = block
                        metadata[:] = [version + 1, monotonic(), quality, int(speech), 1]
                    ready.set()
        except Exception:
            logger.debug("Microphone capture unavailable", exc_info=True)
            stop.wait(0.5)
        finally:
            with lock:
                metadata[:] = [0, 0, 0, 0, 0]
            paused_ack.set()
            ready.set()


class MicCapture:
    def __init__(self, index, name, settings, ready):
        import multiprocessing

        context = multiprocessing.get_context("spawn")
        self.index, self.name = index, name
        self.lock, self.stop = context.Lock(), context.Event()
        self.enabled, self.paused_ack = context.Event(), context.Event()
        self.enabled.set()
        self.samples = context.RawArray("f", 12 * 1600)
        self.metadata = context.RawArray("d", 5)
        self.started = monotonic()
        self.thread = context.Process(
            target=capture_microphone,
            args=(
                index,
                settings,
                self.samples,
                self.metadata,
                self.lock,
                self.stop,
                ready,
                self.enabled,
                self.paused_ack,
            ),
            daemon=True,
        )

    def snapshot(self):
        if not self.lock.acquire(timeout=0.02):
            return {
                "index": self.index,
                "name": self.name,
                "priority": microphone_priority(self.name),
                "speech": False,
                "quality": 0,
                "updated": 0,
                "alive": False,
                "version": 0,
                "frames": [],
            }
        try:
            version, updated, quality, speech, alive = self.metadata[:]
            count = int(version)
            array = np.frombuffer(self.samples, dtype=np.float32).reshape(12, 1600)
            frames = [array[i % 12].copy() for i in range(max(0, count - 12), count)]
            return {
                "index": self.index,
                "name": self.name,
                "priority": microphone_priority(self.name),
                "speech": bool(speech),
                "quality": quality,
                "updated": updated,
                "alive": bool(alive) and self.thread.is_alive(),
                "version": count,
                "frames": frames,
            }
        finally:
            self.lock.release()

    def close(self):
        self.stop.set()
        self.enabled.set()
        self.thread.join(timeout=0.3)
        if self.thread.is_alive():
            self.thread.terminate()
            self.thread.join(timeout=1)


class AutoMicrophoneStream:
    """InputStream-compatible adapter; workers never block Qt or model inference."""

    def __init__(self, settings, selector=None, should_stop=None, **kwargs):
        self.settings = settings
        self.selector = selector or MicSelector(hold_seconds=settings.silence_seconds + 0.2)
        self.should_stop = should_stop or (lambda: False)
        self.captures = {}
        import multiprocessing

        self.ready = multiprocessing.get_context("spawn").Event()
        self.selected_index = None
        self.source_name = ""
        self.pending = deque()
        self.last_version = -1
        self.next_scan = 0
        self.default_identity = None
        self.source_epoch = 0

    def discover(self):
        import sounddevice as sd

        if self.settings.microphone is None and not self.settings.auto_microphone:
            from nisha.system_microphone import system_default_microphone

            identity, name = system_default_microphone()
            previous = self.captures.get(-1)
            if (
                identity != self.default_identity
                or previous is None
                or not previous.thread.is_alive()
            ):
                for capture in self.captures.values():
                    capture.close()
                self.captures.clear()
                self.pending.clear()
                self.selected_index, self.last_version = None, -1
                self.selector.selected_index = None
                self.selector.last_speech = float("-inf")
                capture = MicCapture(-1, "Windows default · " + name, self.settings, self.ready)
                self.captures[-1] = capture
                capture.thread.start()
                self.default_identity = identity
                self.source_epoch += 1
                logger.info("Following Windows default microphone: %s", name)
            self.next_scan = monotonic() + 3
            return

        # Prefer MME, whose shared input supports 16 kHz across these devices;
        # keep one host entry for each physical microphone, up to four sources.
        devices, apis = sd.query_devices(), sd.query_hostapis()
        candidates = {}
        for index, device in enumerate(devices):
            if self.settings.microphone is not None and index != self.settings.microphone:
                continue
            if not device["max_input_channels"]:
                continue
            name = device["name"]
            if any(
                word in name.casefold()
                for word in ["sound mapper", "primary sound", "droidcam", "midi"]
            ):
                continue
            group = name.casefold().replace("(", "").replace(")", "").strip()
            if "airwave" in group:
                group = "airwave headset"
            elif "usb audio device" in group:
                group = "usb microphone"
            elif "4mp" in group or "webcam" in group:
                group = "webcam microphone"
            elif "high definition" in group:
                group = "built-in microphone"
            previous = candidates.get(group)
            mme = apis[device["hostapi"]]["name"] == "MME"
            if previous is None or mme:
                candidates[group] = (index, mme, name)
        ranked = sorted(candidates.values(), key=lambda value: microphone_priority(value[2]))[:4]
        for index, _, name in ranked:
            old = self.captures.get(index)
            if old is None or not old.thread.is_alive():
                capture = MicCapture(index, name, self.settings, self.ready)
                self.captures[index] = capture
                capture.thread.start()
        self.next_scan = monotonic() + 3

    def __enter__(self):
        self.pending.clear()
        self.last_version = -1
        self.discover()
        for capture in self.captures.values():
            capture.enabled.set()
        return self

    def read(self, frames):
        if frames != 1600:
            raise ValueError("Automatic microphone capture requires 16 kHz / 100 ms blocks.")
        started = monotonic()
        while True:
            if self.should_stop():
                return np.zeros((frames, 1), dtype=np.float32), False
            if self.pending:
                return self.pending.popleft().reshape(-1, 1), False
            if monotonic() >= self.next_scan:
                self.discover()
            snapshots = [capture.snapshot() for capture in self.captures.values()]
            if self.settings.microphone is not None:
                snapshots = [
                    item for item in snapshots if item["index"] == self.settings.microphone
                ]
            selected = self.selector.choose(snapshots)
            if selected is not None:
                if selected["index"] != self.selected_index:
                    self.selected_index, self.source_name = selected["index"], selected["name"]
                    self.last_version = selected["version"]
                    self.pending.extend(selected["frames"][-7:])
                    logger.info("Active microphone: %s", self.source_name)
                elif selected["version"] > self.last_version:
                    difference = selected["version"] - self.last_version
                    self.pending.extend(selected["frames"][-min(difference, 12) :])
                    self.last_version = selected["version"]
                if self.pending:
                    continue
            if monotonic() - started > 5:
                raise RuntimeError("No microphone is delivering audio.")
            self.ready.wait(0.1)
            self.ready.clear()

    def __exit__(self, *args):
        for capture in self.captures.values():
            capture.enabled.clear()
        for capture in self.captures.values():
            if not capture.paused_ack.wait(0.3):
                capture.close()
        self.pending.clear()

    def close(self):
        for capture in self.captures.values():
            capture.close()
