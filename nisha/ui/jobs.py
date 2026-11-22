"""Background jobs for import, isolated external tasks and visual lookup."""

import logging

from PySide6.QtCore import QThread, Signal

from nisha.errors import NishaError


class ServiceJob(QThread):
    status = Signal(object)

    def __init__(self, settings):
        super().__init__()
        self.settings = settings

    def run(self):
        from nisha.services import LocalServices

        services = LocalServices(self.settings)
        try:
            status = services.ensure(cancelled=self.isInterruptionRequested)
            self.status.emit(status)
            if status["ready"] and not self.isInterruptionRequested():
                services.warm_fast(cancelled=self.isInterruptionRequested)
        except (OSError, ValueError):
            logging.getLogger("nisha").warning("Local service recovery deferred.")
        finally:
            services.close()


class ActionJob(QThread):
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, core, session, alias, text, history=None):
        super().__init__()
        self.core, self.session, self.alias, self.text = core, session, alias, text
        self.history = history

    def run(self):
        from nisha.errors import OperationCancelled

        try:
            reply = self.core.background_action(
                self.text, self.session, self.alias, self.isInterruptionRequested, self.history
            )
            if not self.isInterruptionRequested():
                self.done.emit(reply)
        except OperationCancelled:
            pass
        except (NishaError, ValueError, OSError) as exc:
            self.failed.emit(
                str(exc)
                if isinstance(exc, (NishaError, ValueError))
                else "The background action failed."
            )
        except Exception:
            logging.getLogger("nisha").exception("Background action failed")
            self.failed.emit("The background action failed. Check the local log.")


class ImportJob(QThread):
    done = Signal(str)

    def __init__(self, knowledge, files=None, text="", name="Pasted reference"):
        super().__init__()
        self.knowledge, self.files, self.text, self.name = knowledge, files or [], text, name

    def run(self):
        messages = []
        for filename in self.files:
            try:
                source = self.knowledge.import_file(filename)
                messages.append(f"Added {filename} · {source}")
            except (NishaError, OSError, ValueError) as exc:
                messages.append(str(exc))
        if self.text.strip():
            try:
                source = self.knowledge.add_text(self.name, self.text)
                messages.append("Added pasted reference · " + source)
            except (NishaError, OSError, ValueError) as exc:
                messages.append(str(exc))
        self.done.emit("\n".join(messages))


class VisualJob(QThread):
    found = Signal(object, int)
    image = Signal(bytes, int, int)
    failed = Signal(str, int)

    def __init__(self, service, generation, text=None, private=False, asset=None, index=0):
        super().__init__()
        self.service, self.generation = service, generation
        self.text, self.private, self.asset, self.index = text, private, asset, index

    def run(self):
        try:
            if self.asset:
                self.image.emit(self.service.image_bytes(self.asset), self.index, self.generation)
            else:
                self.found.emit(self.service.find(self.text, self.private), self.generation)
        except Exception:
            if self.asset and self.asset.kind.startswith("camera_"):
                logging.getLogger("nisha").info("Camera frame unavailable")
            else:
                logging.getLogger("nisha").exception("Visual job failed")
            message = (
                "Camera snapshot unavailable. Check Ctrl+D endpoints and credentials."
                if self.asset and self.asset.kind.startswith("camera_")
                else "Visual lookup unavailable. Your local answer is still available."
            )
            self.failed.emit(message, self.generation)


class ExternalTaskJob(QThread):
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, core, approval):
        super().__init__()
        self.core, self.approval = core, approval

    def run(self):
        try:
            if not self.core.settings.external_tasks_enabled:
                raise NishaError("External tasks are disabled in this local-only installation.")
            result = self.core.workers.run(self.approval, approved=True)
            self.core.store.save_task(
                self.approval.provider + "/" + self.approval.model, self.approval.text, result
            )
            if self.approval.learn:
                self.core.reinforcement.propose_teacher(
                    self.approval.provider + "/" + self.approval.model,
                    self.approval.text,
                    result,
                )
                result += (
                    "\n\nSaved for local review in Ctrl+L → Response learning and teacher answers."
                )
            self.done.emit(result)
        except Exception as exc:
            logging.getLogger("nisha").exception("External task job failed")

            self.failed.emit(
                str(exc) if isinstance(exc, NishaError) else "The external task couldn't finish."
            )


class DevicePollJob(QThread):
    done = Signal(str)

    def __init__(self, devices):
        super().__init__()
        self.devices = devices

    def run(self):
        try:
            self.done.emit(self.devices.poll())
        except (NishaError, OSError, ValueError):
            self.done.emit("Device status unavailable · review Ctrl+D configuration")


class VisionJob(QThread):
    done = Signal(str, int, int)

    def __init__(self, vision, data, index, generation):
        super().__init__()
        self.vision, self.data, self.index, self.generation = vision, data, index, generation

    def run(self):
        try:
            description = self.vision.describe(self.data)
        except (NishaError, OSError, ValueError):
            description = "Local image description unavailable. I can only identify the source title, not the image contents."
        self.done.emit(description, self.index, self.generation)
        self.data = b""


class CameraVisionJob(QThread):
    done = Signal(str, int)

    def __init__(self, devices, vision, asset, question, generation):
        super().__init__()
        self.devices, self.vision, self.asset = devices, vision, asset
        self.question, self.generation = question, generation

    def run(self):
        try:
            data = self.devices.image_bytes(self.asset)
            result = self.vision.describe(data, question=self.question)
            data = b""
            self.done.emit(result, self.generation)
        except (NishaError, OSError, ValueError):
            logging.getLogger("nisha").info("Local camera vision unavailable")
            self.done.emit(
                "I couldn't analyze a current camera snapshot. Check the camera snapshot endpoint and local vision model.",
                self.generation,
            )
