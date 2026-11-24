"""Explicit local screen capture and analysis for Windows computer control."""

import os
import re
from io import BytesIO

from nisha.errors import NishaError
from nisha.vision import LocalVision

SENSITIVE_VISUAL_TARGET = re.compile(
    r"\b(?:send|submit|publish|post|share|subscribe|unsubscribe|purchase|buy|pay|order|"
    r"delete|remove|erase|uninstall|format|reset|transfer|withdraw|confirm|approve|authorize|"
    r"allow|accept|sign[ -]?(?:in|out|up)|log[ -]?(?:in|out)|login|install|download|run|execute)\b",
    re.IGNORECASE,
)


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


def visual_click_request(text):
    match = re.fullmatch(
        r"(?:please )?(?:click|tap)\s+(?:on\s+)?(.+?)\s+on\s+(?:my\s+)?screen",
        text.strip().strip(" .!?"),
        re.IGNORECASE,
    )
    return match[1].strip() if match else None


class ScreenService:
    """Capture a bounded desktop frame and describe it through verified local vision."""

    MAX_PIXELS = 16_000_000
    MAX_BYTES = 12_000_000
    MIN_TARGET_CONFIDENCE = 0.90

    def __init__(
        self,
        ollama_url,
        model="moondream",
        capture=None,
        vision_factory=LocalVision,
        screen_bounds=None,
        monitor_regions=None,
    ):
        self.ollama_url = ollama_url
        self.model = model
        self.capture_source = capture or self._capture_windows_screen
        self.vision_factory = vision_factory
        self._requires_geometry = capture is None
        self.screen_bounds = screen_bounds or (
            self._windows_virtual_bounds if capture is None else lambda: None
        )
        self.monitor_regions = monitor_regions or (
            self._windows_monitor_regions if capture is None else lambda: None
        )

    @staticmethod
    def _capture_windows_screen():
        if os.name != "nt":
            raise NishaError("Screen capture is available on Windows only.")
        try:
            from PIL import ImageGrab

            return ImageGrab.grab(all_screens=True)
        except (OSError, ImportError, TypeError) as exc:
            raise NishaError("Windows screen capture is unavailable on this installation.") from exc

    @staticmethod
    def _windows_virtual_bounds():
        if os.name != "nt":
            return None
        import ctypes

        user32 = ctypes.windll.user32
        left, top = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
        width, height = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
        return (left, top, width, height) if width > 0 and height > 0 else None

    @staticmethod
    def _windows_monitor_regions():
        if os.name != "nt":
            return None
        import ctypes

        class Rect(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long),
            ]

        callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.POINTER(Rect), ctypes.c_ssize_t,
        )
        result = []

        def collect(_monitor, _dc, rect_ptr, _data):
            rect = rect_ptr.contents
            result.append((rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top))
            return 1

        callback = callback_type(collect)
        user32 = ctypes.windll.user32
        if not user32.EnumDisplayMonitors(None, None, callback, 0):
            raise NishaError("Windows couldn't enumerate the connected monitors.")
        return tuple(result)

    def _bounds_for(self, image):
        try:
            bounds = self.screen_bounds()
        except (OSError, AttributeError):
            bounds = None
        if (
            isinstance(bounds, (tuple, list))
            and len(bounds) == 4
            and bounds[2] == image.width
            and bounds[3] == image.height
        ):
            return tuple(int(value) for value in bounds)
        # Injected screenshots and systems without a Windows virtual desktop use
        # their own local origin; production Windows capture must match metrics.
        if self._requires_geometry and os.name == "nt":
            raise NishaError("The captured desktop no longer matches Windows display geometry.")
        return (0, 0, image.width, image.height)

    def _regions_for(self):
        try:
            regions = self.monitor_regions()
        except (OSError, AttributeError):
            regions = None
        if regions is None:
            return None
        normalized = []
        for region in regions:
            if (
                not isinstance(region, (tuple, list)) or len(region) != 4
                or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in region)
                or region[2] <= 0 or region[3] <= 0
            ):
                raise NishaError("Windows returned invalid monitor geometry; no click was sent.")
            normalized.append(tuple(int(value) for value in region))
        return tuple(normalized)

    def capture(self):
        """Return a bounded JPEG snapshot; callers must request screen analysis explicitly."""
        image = self.capture_source()
        return self._encode(image)

    def _encode(self, image):
        try:
            if image.width < 1 or image.height < 1 or image.width * image.height > self.MAX_PIXELS:
                raise NishaError("The desktop image is outside the supported size limit.")
            image = image.copy()
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

    def visual_click(self, target, controller):
        """Click one user-named visual target, only with high local-vision confidence."""
        target = target.strip()
        if not target or len(target) > 160:
            raise NishaError("Name one visible screen target in 1–160 characters.")
        if SENSITIVE_VISUAL_TARGET.search(target):
            raise NishaError("That target may trigger a sensitive action; visual clicking is blocked.")

        before = self.capture_source()
        before_size = (before.width, before.height)
        before_bounds = self._bounds_for(before)
        before_regions = self._regions_for()
        before_data = self._encode(before)
        vision = self.vision_factory(self.ollama_url, self.model)
        location = vision.locate(before_data, target)
        if not isinstance(location, dict) or location.get("found") is not True:
            raise NishaError("I couldn't locate that target with high enough confidence; no action was taken.")
        try:
            x, y = location["x"], location["y"]
            confidence = location["confidence"]
            evidence = location["evidence"]
            if (
                any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in (x, y, confidence))
                or not 0 <= x <= 1 or not 0 <= y <= 1
                or not 0 <= confidence <= 1 or not isinstance(evidence, str)
            ):
                raise ValueError("invalid location")
        except (KeyError, TypeError, ValueError) as exc:
            raise NishaError("Local vision returned an invalid location; no action was taken.") from exc
        if confidence < self.MIN_TARGET_CONFIDENCE:
            raise NishaError("I couldn't locate that target with high enough confidence; no action was taken.")
        if SENSITIVE_VISUAL_TARGET.search(evidence):
            raise NishaError("The visible control appears sensitive; visual clicking is blocked.")

        current = self.capture_source()
        if (
            (current.width, current.height) != before_size
            or self._bounds_for(current) != before_bounds
            or self._regions_for() != before_regions
            or self._visible_change(before, current)
        ):
            raise NishaError("The screen changed while I was locating the target; no click was sent.")
        pixel_x = min(before_size[0] - 1, round(x * (before_size[0] - 1)))
        pixel_y = min(before_size[1] - 1, round(y * (before_size[1] - 1)))
        desktop_x, desktop_y = before_bounds[0] + pixel_x, before_bounds[1] + pixel_y
        if before_regions is not None and not any(
            left <= desktop_x < left + width and top <= desktop_y < top + height
            for left, top, width, height in before_regions
        ):
            raise NishaError("The target is in a gap between monitors; no click was sent.")
        if hasattr(controller, "click_virtual_point"):
            controller.click_virtual_point(
                desktop_x,
                desktop_y,
                before_bounds,
            )
        else:
            controller.click_point(pixel_x, pixel_y, *before_size)

        # Never retry a click: a missing visual change must not duplicate a side effect.
        try:
            after = self.capture_source()
        except (NishaError, OSError, ValueError):
            return f"Clicked the visible target '{target}', but I couldn't recapture the screen to check it. I won't retry."
        if (
            (after.width, after.height) != before_size
            or self._bounds_for(after) != before_bounds
            or self._regions_for() != before_regions
        ):
            raise NishaError("The screen geometry changed after the click; stopped without retrying.")
        changed = self._visible_change(before, after)
        if changed:
            try:
                after_view = vision.describe(
                    self._encode(after), question="Briefly describe the current visible screen."
                )
            except (NishaError, OSError, ValueError):
                return f"Clicked the visible target '{target}'. The screenshot changed, but local vision couldn't describe it. I won't retry."
            return (
                f"Clicked the visible target '{target}'. The screenshot changed; local vision now sees: "
                f"{after_view[:500]}"
            )
        return f"Clicked the visible target '{target}', but no visible screen change was detected. I stopped without retrying."

    @staticmethod
    def _visible_change(before, after):
        """Return a conservative pixel-change signal; it is not proof of task completion."""
        try:
            from PIL import ImageChops

            size = (96, 60)
            left = before.convert("RGB").resize(size)
            right = after.convert("RGB").resize(size)
            difference = ImageChops.difference(left, right).convert("L")
            changed = difference.point(lambda value: 255 if value >= 24 else 0)
            return changed.getbbox() is not None and changed.tobytes().count(b"\xff") / (size[0] * size[1]) >= 0.01
        except (OSError, ValueError, AttributeError):
            return False

    def analyze(self, question=None):
        data = self.capture()
        try:
            return self.vision_factory(self.ollama_url, self.model).describe(
                data, question=question
            )
        finally:
            data = b""
