"""Explicit local screen capture and analysis for Windows computer control."""

import os
import re
from io import BytesIO

from nisha.errors import NishaError
from nisha.vision import LocalVision


def screen_question(text):
    value = text.strip().strip(" .!?")
    match = re.fullmatch(
        r"(?:please )?(?:can you )?(?:describe (?:my )?screen|"
        r"what(?:'s| is) on (?:my )?screen|what does (?:my )?screen show)"
        r"(?:\s*[:,]\s*(.+))?",
        value,
        re.IGNORECASE,
    )
    return match[1].strip() if match and match[1] else "" if match else None


class ScreenService:
    """Capture a bounded desktop frame and describe it through verified local vision."""

    MAX_PIXELS = 16_000_000
    MAX_BYTES = 12_000_000

    def __init__(self, ollama_url, model="moondream", capture=None, vision_factory=LocalVision):
        self.ollama_url = ollama_url
        self.model = model
        self.capture_source = capture or self._capture_windows_screen
        self.vision_factory = vision_factory

    @staticmethod
    def _capture_windows_screen():
        if os.name != "nt":
            raise NishaError("Screen capture is available on Windows only.")
        try:
            from PIL import ImageGrab

            return ImageGrab.grab(all_screens=True)
        except (OSError, ImportError) as exc:
            raise NishaError("Windows screen capture is unavailable on this installation.") from exc

    def capture(self):
        """Return a bounded JPEG snapshot; callers must request screen analysis explicitly."""
        image = self.capture_source()
        try:
            if image.width < 1 or image.height < 1 or image.width * image.height > self.MAX_PIXELS:
                raise NishaError("The desktop image is outside the supported size limit.")
            image.thumbnail((2560, 1600))
            output = BytesIO()
            image.convert("RGB").save(output, format="JPEG", quality=82, optimize=True)
            data = output.getvalue()
            if len(data) > self.MAX_BYTES:
                raise NishaError("The desktop snapshot is too large to analyze safely.")
            return data
        except NishaError:
            raise
        except (OSError, ValueError, AttributeError) as exc:
            raise NishaError("Windows could not encode the captured desktop image.") from exc

    def analyze(self, question=None):
        data = self.capture()
        try:
            return self.vision_factory(self.ollama_url, self.model).describe(
                data, question=question
            )
        finally:
            data = b""
