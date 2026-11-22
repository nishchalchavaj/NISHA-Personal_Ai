"""Probe configured input without transcribing or saving microphone audio."""

import time

from nisha.microphones import AutoMicrophoneStream
from nisha.settings import load_settings


def main():
    start = time.monotonic()
    stream = AutoMicrophoneStream(load_settings().voice)
    with stream:
        for _ in range(30):
            block, _overflow = stream.read(1600)
            assert block.shape == (1600, 1)
        print("Active input:", stream.source_name, flush=True)
        for capture in stream.captures.values():
            state = capture.snapshot()
            print(
                "Monitor:",
                state["name"],
                "available:",
                state["alive"],
                "priority:",
                state["priority"],
                flush=True,
            )
    # A second listening turn reuses the healthy workers, avoiding process startup lag.
    warm_start = time.monotonic()
    with stream:
        stream.read(1600)
    print("Warm resume seconds:", round(time.monotonic() - warm_start, 2), flush=True)
    stream.close()
    assert all(not capture.thread.is_alive() for capture in stream.captures.values())
    print(
        "PASS: configured microphone capture, warm resume and isolated clean shutdown.", flush=True
    )
    print("Elapsed seconds:", round(time.monotonic() - start, 2), flush=True)


if __name__ == "__main__":
    main()
