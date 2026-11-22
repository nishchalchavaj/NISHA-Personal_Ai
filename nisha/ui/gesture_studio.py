"""Opt-in, local hand tracking canvas for NISHA."""

from math import cos, pi, sin
import logging

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class HandTrackingWorker(QThread):
    frame_ready = Signal(QImage, float, float, bool)
    status = Signal(str)

    def __init__(self, camera_index=0, parent=None):
        super().__init__(parent)
        self.camera_index = camera_index
        self._stopping = False
        self.show_pose = False
        self.show_faces = False

    def set_overlays(self, pose, faces):
        self.show_pose, self.show_faces = pose, faces

    def stop(self):
        self._stopping = True

    def run(self):
        capture = None
        pose = None
        try:
            import cv2
            import mediapipe as mp

            if not hasattr(mp, "solutions"):
                raise RuntimeError(
                    "Installed MediaPipe version lacks the solutions API; reinstall desktop dependencies."
                )

            capture = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
            if not capture.isOpened():
                self.status.emit("NISHA couldn't open the camera. Check Windows camera permission.")
                return
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self.status.emit("Camera is on · pinch thumb and index finger to draw")
            with mp.solutions.hands.Hands(
                static_image_mode=False,
                max_num_hands=1,
                model_complexity=0,
                min_detection_confidence=0.55,
                min_tracking_confidence=0.5,
            ) as hands:
                face_detector = cv2.CascadeClassifier(
                    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
                )
                while not self._stopping:
                    ok, frame = capture.read()
                    if not ok:
                        self.status.emit("Camera frame unavailable. Check the camera and try again.")
                        break
                    frame = cv2.flip(frame, 1)
                    height, width = frame.shape[:2]
                    result = hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                    x = y = 0.0
                    drawing = False
                    if result.multi_hand_landmarks:
                        hand = result.multi_hand_landmarks[0]
                        mp.solutions.drawing_utils.draw_landmarks(
                            frame, hand, mp.solutions.hands.HAND_CONNECTIONS
                        )
                        thumb, index = hand.landmark[4], hand.landmark[8]
                        x, y = float(index.x), float(index.y)
                        # Pinch is deliberately the only drawing gesture.
                        drawing = ((thumb.x - index.x) ** 2 + (thumb.y - index.y) ** 2) ** 0.5 < 0.055
                    if self.show_pose:
                        if pose is None:
                            self.status.emit("Loading the local pose model. First use may download it once.")
                            pose = mp.solutions.pose.Pose(
                                static_image_mode=False, model_complexity=0, smooth_landmarks=True,
                                min_detection_confidence=0.5, min_tracking_confidence=0.5,
                            )
                        pose_result = pose.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                        if pose_result.pose_landmarks:
                            mp.solutions.drawing_utils.draw_landmarks(
                                frame, pose_result.pose_landmarks, mp.solutions.pose.POSE_CONNECTIONS
                            )
                    if self.show_faces:
                        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                        faces = face_detector.detectMultiScale(gray, 1.1, 5, minSize=(40, 40))
                        for fx, fy, fw, fh in faces:
                            cv2.rectangle(frame, (fx, fy), (fx + fw, fy + fh), (40, 220, 190), 2)
                        cv2.putText(frame, f"Faces: {len(faces)}", (12, 28),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (40, 220, 190), 2)
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    image = QImage(rgb.data, width, height, rgb.strides[0], QImage.Format_RGB888)
                    self.frame_ready.emit(image.copy(), x, y, drawing)
        except ImportError as exc:
            self.status.emit(f"Camera vision dependency missing: {exc}. Run scripts\\setup.ps1 -Desktop.")
        except Exception as exc:
            logging.getLogger("nisha").exception("Camera gesture studio failed")
            self.status.emit(f"Camera vision couldn't start: {type(exc).__name__}: {str(exc)[:180]}")
        finally:
            if pose is not None:
                pose.close()
            if capture is not None:
                capture.release()
            if self._stopping:
                self.status.emit("Camera off · nothing was recorded")


class DrawingCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 260)
        self.setStyleSheet("background:#101b29; border:1px solid #2b4658; border-radius:12px;")
        self.strokes = []
        self.current = []

    def add_point(self, x, y, drawing):
        point = (max(0.0, min(1.0, x)), max(0.0, min(1.0, y)))
        if drawing:
            if not self.current:
                self.strokes.append(self.current)
            self.current.append(point)
        else:
            self.current = []
        self.update()

    def clear(self):
        self.current = []
        self.strokes.clear()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#101b29"))
        painter.setPen(QPen(QColor("#29e0bf"), 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        width, height = self.width(), self.height()
        for stroke in self.strokes:
            for first, second in zip(stroke, stroke[1:]):
                painter.drawLine(int(first[0] * width), int(first[1] * height),
                                 int(second[0] * width), int(second[1] * height))

    def save_png(self, path):
        pixmap = QPixmap(self.size())
        pixmap.fill(QColor("#101b29"))
        self.render(pixmap)
        return pixmap.save(path, "PNG")


class ShapeViewport(QWidget):
    """Small wireframe 3D shape preview rotated by the tracked index fingertip."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 260)
        self.shape = "Cube"
        self.rotation_x = 0.25
        self.rotation_y = 0.5
        self.setStyleSheet("background:#101b29; border:1px solid #2b4658; border-radius:12px;")

    def set_shape(self, name):
        self.shape = name
        self.update()

    def set_hand_position(self, x, y):
        self.rotation_y = (x - 0.5) * 2 * pi
        self.rotation_x = (y - 0.5) * 2 * pi
        self.update()

    def project(self, point):
        x, y, z = point
        cy, sy = cos(self.rotation_y), sin(self.rotation_y)
        cx, sx = cos(self.rotation_x), sin(self.rotation_x)
        x, z = x * cy - z * sy, x * sy + z * cy
        y, z = y * cx - z * sx, y * sx + z * cx
        scale = min(self.width(), self.height()) * 0.28 / (3.2 + z)
        return (self.width() / 2 + x * scale, self.height() / 2 + y * scale)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#101b29"))
        painter.setPen(QPen(QColor("#29e0bf"), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        if self.shape == "Cube":
            vertices = [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
            edges = [(a, b) for a in range(8) for b in range(a + 1, 8)
                     if sum(vertices[a][i] != vertices[b][i] for i in range(3)) == 1]
        elif self.shape == "Pyramid":
            vertices = [(-1, 0.8, -1), (1, 0.8, -1), (1, 0.8, 1), (-1, 0.8, 1), (0, -1, 0)]
            edges = [(0, 1), (1, 2), (2, 3), (3, 0), (0, 4), (1, 4), (2, 4), (3, 4)]
        else:
            # Sphere and torus use sampled latitude/longitude wireframes.
            vertices, edges = [], []
            major, minor = (12, 10) if self.shape == "Sphere" else (20, 8)
            for row in range(major):
                for col in range(minor):
                    u, v = 2 * pi * row / major, 2 * pi * col / minor
                    if self.shape == "Sphere":
                        point = (sin(pi * row / major) * cos(v), cos(pi * row / major),
                                 sin(pi * row / major) * sin(v))
                    else:
                        radius = 0.62 + 0.28 * cos(v)
                        point = (radius * cos(u), 0.28 * sin(v), radius * sin(u))
                    vertices.append(point)
            for row in range(major):
                for col in range(minor):
                    here = row * minor + col
                    edges.append((here, row * minor + (col + 1) % minor))
                    if self.shape == "Sphere" or col == 0:
                        edges.append((here, ((row + 1) % major) * minor + col))
        for first, second in edges:
            p1, p2 = self.project(vertices[first]), self.project(vertices[second])
            painter.drawLine(int(p1[0]), int(p1[1]), int(p2[0]), int(p2[1]))
        painter.setPen(QColor("#b9d1df"))
        painter.drawText(14, 24, f"{self.shape} · move your hand to rotate")


class GestureStudioDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("NISHA · Hand Drawing Studio")
        self.resize(980, 620)
        self.worker = None
        layout = QVBoxLayout(self)
        intro = QLabel("Draw with your hand · pinch thumb and index finger to draw. Open palm pauses.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        columns = QHBoxLayout()
        self.preview = QLabel("Camera is off")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(360, 260)
        self.preview.setStyleSheet("background:#101b29; color:#b9d1df; border-radius:12px;")
        self.canvas = DrawingCanvas()
        self.shape_view = ShapeViewport()
        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self.canvas)
        self.view_stack.addWidget(self.shape_view)
        columns.addWidget(self.preview, 1)
        columns.addWidget(self.view_stack, 1)
        layout.addLayout(columns, 1)
        self.mode_picker = QComboBox()
        self.mode_picker.addItems(["Hand drawing", "3D shape creator"])
        self.mode_picker.currentIndexChanged.connect(self.view_stack.setCurrentIndex)
        self.mode_picker.currentIndexChanged.connect(lambda index: self.mouse_toggle.setEnabled(index == 0))
        layout.addWidget(self.mode_picker)
        self.status = QLabel("Camera off · no video is stored")
        layout.addWidget(self.status)
        modes = QHBoxLayout()
        self.pose_toggle = QCheckBox("Show body pose keypoints")
        self.faces_toggle = QCheckBox("Show face outlines and count")
        self.mouse_toggle = QCheckBox("Control mouse · index moves, pinch clicks")
        self.pose_toggle.toggled.connect(self.set_overlays)
        self.faces_toggle.toggled.connect(self.set_overlays)
        modes.addWidget(self.pose_toggle)
        modes.addWidget(self.faces_toggle)
        modes.addWidget(self.mouse_toggle)
        layout.addLayout(modes)
        self.shape_picker = QComboBox()
        self.shape_picker.addItems(["Cube", "Sphere", "Torus", "Pyramid"])
        self.shape_picker.currentTextChanged.connect(self.shape_view.set_shape)
        self.shape_picker.setEnabled(False)
        layout.addWidget(self.shape_picker)
        self.mode_picker.currentIndexChanged.connect(lambda index: self.shape_picker.setEnabled(index == 1))
        self.camera_picker = QComboBox()
        for camera_index in range(4):
            self.camera_picker.addItem(f"Camera {camera_index}", camera_index)
        layout.addWidget(self.camera_picker)
        controls = QHBoxLayout()
        self.start_button = QPushButton("Start camera")
        self.start_button.clicked.connect(self.start_camera)
        controls.addWidget(self.start_button)
        clear_button = QPushButton("Clear drawing")
        clear_button.clicked.connect(self.canvas.clear)
        controls.addWidget(clear_button)
        save_button = QPushButton("Save PNG…")
        save_button.clicked.connect(self.save_drawing)
        controls.addWidget(save_button)
        controls.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        controls.addWidget(close_button)
        layout.addLayout(controls)

    def start_camera(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.start_button.setText("Start camera")
            return
        self.worker = HandTrackingWorker(self.camera_picker.currentData(), parent=self)
        self.worker.frame_ready.connect(self.on_frame)
        self.worker.status.connect(self.status.setText)
        self.set_overlays()
        self.worker.finished.connect(lambda: self.start_button.setText("Start camera"))
        self.worker.start()
        self.start_button.setText("Stop camera")

    def on_frame(self, image, x, y, drawing):
        self.preview.setPixmap(QPixmap.fromImage(image).scaled(
            self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        ))
        if x or y:
            if self.view_stack.currentIndex() == 1:
                self.shape_view.set_hand_position(x, y)
            elif self.mouse_toggle.isChecked():
                try:
                    import pyautogui

                    screen_width, screen_height = pyautogui.size()
                    pyautogui.moveTo(int(x * screen_width), int(y * screen_height), duration=0)
                    now = __import__("time").monotonic()
                    if (
                        drawing
                        and not getattr(self, "_was_pinching", False)
                        and now - getattr(self, "_last_click", 0) > 0.45
                    ):
                        pyautogui.click()
                        self._last_click = now
                    self._was_pinching = drawing
                except Exception:
                    self.status.setText("Mouse control isn't available. Turn it off and try again.")
                    self.mouse_toggle.setChecked(False)
            else:
                self.canvas.add_point(x, y, drawing)
        elif not drawing:
            self.canvas.current = []
            self._was_pinching = False

    def set_overlays(self):
        if self.worker and self.worker.isRunning():
            self.worker.set_overlays(self.pose_toggle.isChecked(), self.faces_toggle.isChecked())

    def save_drawing(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save drawing", "NISHA-drawing.png", "PNG image (*.png)")
        if path:
            target = self.view_stack.currentWidget()
            pixmap = QPixmap(target.size())
            pixmap.fill(QColor("#101b29"))
            target.render(pixmap)
            if not pixmap.save(path, "PNG"):
                QMessageBox.warning(self, "Save failed", "NISHA couldn't save that image.")

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(2500)
        event.accept()
