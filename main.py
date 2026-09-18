import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QSlider, QLabel, QColorDialog, QFrame, QLineEdit
)
from PyQt6.QtGui import QPainter, QPen, QColor, QPainterPath, QPixmap, QFont
from PyQt6.QtCore import Qt, QPoint, QPointF, QSize, QRectF

import autocorrect


class FloatingPalette(QFrame):
    """
    A minimalist, floating, and draggable palette that allows users to pick colors,
    adjust stroke thickness, and clear the canvas. It can also be collapsed.
    """
    def __init__(self, parent, canvas):
        super().__init__(parent)
        self.canvas = canvas

        # Dragging variables
        self.drag_position = QPoint()
        self.is_dragging = False

        # Set stylesheet for a gorgeous modern frosted / borderless floating look
        self.setObjectName("Palette")
        self.setStyleSheet("""
            QFrame#Palette {
                background-color: rgba(245, 245, 245, 230);
                border: 1px solid rgba(200, 200, 200, 150);
                border-radius: 12px;
            }
            QPushButton {
                border: none;
                border-radius: 6px;
                padding: 6px 10px;
                font-weight: bold;
                font-size: 11px;
                background-color: rgba(220, 220, 220, 200);
            }
            QPushButton:hover {
                background-color: rgba(200, 200, 200, 200);
            }
            QPushButton:pressed {
                background-color: rgba(180, 180, 180, 200);
            }
            QSlider::groove:horizontal {
                border: 1px solid #bbb;
                background: white;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #555;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #333;
                border: 1px solid #333;
                width: 14px;
                margin-top: -4px;
                margin-bottom: -4px;
                border-radius: 7px;
            }
        """)

        # Main layout
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(8, 6, 8, 6)
        self.main_layout.setSpacing(10)

        # Drag Handle (visual cue)
        self.drag_handle = QLabel("⋮⋮", self)
        self.drag_handle.setStyleSheet("color: #888; font-weight: bold; font-size: 14px; margin-right: 4px;")
        self.drag_handle.setCursor(Qt.CursorShape.SizeAllCursor)
        self.main_layout.addWidget(self.drag_handle)

        # Content Container (so we can collapse it)
        self.content_widget = QWidget(self)
        self.content_layout = QHBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(10)
        self.main_layout.addWidget(self.content_widget)

        # Quick Colors
        self.btn_black = QPushButton("● Black", self)
        self.btn_black.setStyleSheet("color: black; background-color: rgba(230, 230, 230, 150);")
        self.btn_black.clicked.connect(lambda: self.canvas.set_pen_color(Qt.GlobalColor.black))
        self.content_layout.addWidget(self.btn_black)

        self.btn_red = QPushButton("● Red", self)
        self.btn_red.setStyleSheet("color: red; background-color: rgba(255, 230, 230, 200);")
        self.btn_red.clicked.connect(lambda: self.canvas.set_pen_color(Qt.GlobalColor.red))
        self.content_layout.addWidget(self.btn_red)

        self.btn_blue = QPushButton("● Blue", self)
        self.btn_blue.setStyleSheet("color: blue; background-color: rgba(230, 230, 255, 200);")
        self.btn_blue.clicked.connect(lambda: self.canvas.set_pen_color(Qt.GlobalColor.blue))
        self.content_layout.addWidget(self.btn_blue)

        self.btn_green = QPushButton("● Green", self)
        self.btn_green.setStyleSheet("color: green; background-color: rgba(230, 255, 230, 200);")
        self.btn_green.clicked.connect(lambda: self.canvas.set_pen_color(Qt.GlobalColor.green))
        self.content_layout.addWidget(self.btn_green)

        # Custom Color Picker Button
        self.btn_custom = QPushButton("🎨 More", self)
        self.btn_custom.clicked.connect(self.choose_custom_color)
        self.content_layout.addWidget(self.btn_custom)

        # Separator / Label for Thickness
        self.lbl_thickness = QLabel("Size: 5", self)
        self.lbl_thickness.setStyleSheet("font-size: 11px; font-weight: bold; color: #333;")
        self.content_layout.addWidget(self.lbl_thickness)

        # Slider
        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(1, 50)
        self.slider.setValue(5)
        self.slider.setFixedWidth(100)
        self.slider.valueChanged.connect(self.canvas.set_pen_width)
        self.content_layout.addWidget(self.slider)

        # Clear Canvas Button
        self.btn_clear = QPushButton("🗑️ Clear", self)
        self.btn_clear.setStyleSheet("background-color: rgba(255, 200, 200, 200); color: #aa0000;")
        self.btn_clear.clicked.connect(self.canvas.clear_canvas)
        self.content_layout.addWidget(self.btn_clear)

        # Collapse / Expand Toggle Button
        self.btn_collapse = QPushButton("◀", self)
        self.btn_collapse.setFixedWidth(30)
        self.btn_collapse.setStyleSheet("font-size: 10px; font-weight: bold;")
        self.btn_collapse.clicked.connect(self.toggle_collapse)
        self.main_layout.addWidget(self.btn_collapse)

        self.is_collapsed = False

        # Adjust size based on layout
        self.adjustSize()

    def choose_custom_color(self):
        color = QColorDialog.getColor(self.canvas.current_color, self, "Choose Pen Color")
        if color.isValid():
            self.canvas.set_pen_color(color)

    def toggle_collapse(self):
        if self.is_collapsed:
            self.content_widget.show()
            self.btn_collapse.setText("◀")
            self.is_collapsed = False
        else:
            self.content_widget.hide()
            self.btn_collapse.setText("▶")
            self.is_collapsed = True
        self.adjustSize()

    def update_thickness_label(self, width):
        self.lbl_thickness.setText(f"Size: {width}")
        if self.slider.value() != width:
            self.slider.blockSignals(True)
            self.slider.setValue(width)
            self.slider.blockSignals(False)

    # --- Draggable functionality ---
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Drag if click is on the drag handle or top frame edges
            if self.drag_handle.geometry().contains(event.position().toPoint()) or event.position().y() < 15:
                self.is_dragging = True
                self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.is_dragging and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.is_dragging = False
        super().mouseReleaseEvent(event)


class CanvasLineEdit(QLineEdit):
    """
    A frameless, transparent overlay text input for direct canvas typing.
    Pressing Escape clears and dismisses the input.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrame(False)
        self.hide()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.clear()
            self.hide()
            event.accept()
            return
        super().keyPressEvent(event)


class DrawingCanvas(QWidget):
    """
    High-performance drawing canvas featuring:
    - 3000x3000 offscreen QPixmap buffer
    - Quad-Bezier smoothed drawing interpolation
    - Mouse-wheel vertical panning
    - Frameless on-canvas text typing overlay
    - Dark mode with automatic black/white color inversion
    """
    def __init__(self, parent=None):
        super().__init__(parent)

        # Offscreen pixmap buffer (3000x3000)
        self.buffer_size = QSize(3000, 3000)
        self.buffer = QPixmap(self.buffer_size)

        # Dark mode state and background color
        self.dark_mode = False
        self.bg_color = QColor("#FFFFFF")
        self.buffer.fill(self.bg_color)
        self.setStyleSheet("background-color: #FFFFFF;")

        # Canvas navigation / panning offset
        self.pan_x = 0
        self.pan_y = 0

        # Pen configuration
        self.current_color = QColor(Qt.GlobalColor.black)
        self.current_width = 5

        # Stroke history: list of dicts with stroke/text data
        self.strokes = []
        self.current_path = None
        self.current_points = []
        self.last_point = None
        self.palette = None

        # Frameless text typing overlay
        self.text_input = CanvasLineEdit(self)
        self.text_input.returnPressed.connect(self.commit_text)
        self.text_canvas_pos = QPointF(0, 0)

    def set_palette(self, palette):
        self.palette = palette

    def set_pen_color(self, color):
        self.current_color = QColor(color)

    def set_pen_width(self, width):
        self.current_width = max(1, min(50, width))
        if self.palette:
            self.palette.update_thickness_label(self.current_width)

    def map_to_canvas(self, pos):
        """Maps widget coordinates (QPoint or QPointF) to canvas buffer coordinates."""
        if hasattr(pos, 'position'):
            pos = pos.position()
        return QPointF(pos.x() - self.pan_x, pos.y() - self.pan_y)

    def get_display_color(self, color):
        """
        Returns display color, automatically inverting black/white in dark/light mode.
        """
        c = QColor(color)
        if self.dark_mode:
            # Black strokes invert to white against dark (#121212) background
            if c.name().lower() in ("#000000", "#121212") or c == QColor(Qt.GlobalColor.black):
                return QColor("#FFFFFF")
        else:
            # White strokes invert to black against light (#FFFFFF) background
            if c.name().lower() == "#ffffff" or c == QColor(Qt.GlobalColor.white):
                return QColor("#000000")
        return c

    def toggle_dark_mode(self):
        """Toggles between white (#FFFFFF) and dark (#121212) background and rebuilds buffer."""
        self.dark_mode = not self.dark_mode
        self.bg_color = QColor("#121212") if self.dark_mode else QColor("#FFFFFF")
        self.setStyleSheet(f"background-color: {'#121212' if self.dark_mode else '#FFFFFF'};")
        self.rebuild_buffer()

    def clear_canvas(self):
        """Clears all strokes and resets the offscreen buffer."""
        self.strokes = []
        self.current_path = None
        self.current_points = []
        self.last_point = None
        if self.text_input.isVisible():
            self.text_input.clear()
            self.text_input.hide()
        self.rebuild_buffer()

    def undo_stroke(self):
        """Undoes the most recent stroke or text item and updates the buffer."""
        if self.strokes:
            self.strokes.pop()
            self.rebuild_buffer()

    def draw_stroke_to_buffer(self, stroke):
        """Draws a single completed stroke or text element onto self.buffer."""
        painter = QPainter(self.buffer)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        if stroke.get('type') == 'text':
            painter.setFont(stroke['font'])
            painter.setPen(self.get_display_color(stroke['color']))
            fm = painter.fontMetrics()
            baseline_y = stroke['pos'].y() + fm.ascent()
            painter.drawText(QPointF(stroke['pos'].x(), baseline_y), stroke['text'])
        else:
            color = self.get_display_color(stroke['color'])
            pen = QPen(
                color, stroke['width'],
                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin
            )
            painter.setPen(pen)
            painter.drawPath(stroke['path'])

        painter.end()

    def rebuild_buffer(self):
        """Rebuilds the entire 3000x3000 buffer from strokes history."""
        self.buffer.fill(self.bg_color)
        painter = QPainter(self.buffer)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        for stroke in self.strokes:
            if stroke.get('type') == 'text':
                painter.setFont(stroke['font'])
                painter.setPen(self.get_display_color(stroke['color']))
                fm = painter.fontMetrics()
                baseline_y = stroke['pos'].y() + fm.ascent()
                painter.drawText(QPointF(stroke['pos'].x(), baseline_y), stroke['text'])
            else:
                color = self.get_display_color(stroke['color'])
                pen = QPen(
                    color, stroke['width'],
                    Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin
                )
                painter.setPen(pen)
                painter.drawPath(stroke['path'])

        painter.end()
        self.update()

    def commit_text(self):
        """Renders typed text onto self.buffer using QPainter.drawText and hides input."""
        text = self.text_input.text().strip()
        if text:
            stroke = {
                'type': 'text',
                'text': text,
                'pos': self.text_canvas_pos,
                'font': self.text_input.font(),
                'color': self.current_color,
                'width': self.current_width
            }
            self.strokes.append(stroke)
            self.draw_stroke_to_buffer(stroke)
            self.update()
        self.text_input.hide()
        self.text_input.clear()

    # --- Mouse Drawing Events ---
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.text_input.isVisible():
                self.commit_text()

            pos = self.map_to_canvas(event.position())
            self.current_path = QPainterPath()
            self.current_path.moveTo(pos)
            self.last_point = pos
            self.current_points = [pos]
            self.update()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self.current_path is not None:
            pos = self.map_to_canvas(event.position())
            # Quad-Bezier Interpolation:
            # Compute midpoint between incoming raw mouse coordinates
            mid_point = QPointF(
                (self.last_point.x() + pos.x()) / 2.0,
                (self.last_point.y() + pos.y()) / 2.0
            )
            # Render quadratic Bezier curve (quadTo) to midpoint
            self.current_path.quadTo(self.last_point, mid_point)
            self.last_point = pos
            self.current_points.append(pos)
            self.update()
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.current_path is not None:
            pos = self.map_to_canvas(event.position())
            self.current_path.lineTo(pos)
            self.current_points.append(pos)

            # Complete the stroke and store it
            stroke = {
                'type': 'stroke',
                'path': self.current_path,
                'color': self.current_color,
                'width': self.current_width,
                'points': list(self.current_points)
            }
            self.strokes.append(stroke)
            self.current_path = None
            self.current_points = []
            self.last_point = None

            # Draw onto offscreen buffer immediately
            self.draw_stroke_to_buffer(stroke)

            # Pass stroke through autocorrect hook
            autocorrect.process(stroke['path'], self)

            self.update()
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Clean up any accidental dot created by the first click of double-click
            if self.strokes and self.strokes[-1].get('type') != 'text':
                last_pts = self.strokes[-1].get('points', [])
                if len(last_pts) <= 3:
                    self.strokes.pop()
                    self.rebuild_buffer()

            if self.text_input.isVisible():
                self.commit_text()

            click_pos = event.position().toPoint()
            self.text_canvas_pos = self.map_to_canvas(event.position())

            # Configure font size and color matching active pen
            font_size = max(12, int(self.current_width * 2.5))
            font = self.text_input.font()
            font.setPointSize(font_size)
            self.text_input.setFont(font)

            display_color = self.get_display_color(self.current_color)
            self.text_input.setStyleSheet(f"""
                QLineEdit {{
                    background: transparent;
                    border: none;
                    outline: none;
                    padding: 0px;
                    color: {display_color.name()};
                    selection-background-color: #3399ff;
                }}
            """)

            self.text_input.setText("")
            self.text_input.move(click_pos)
            self.text_input.resize(400, max(30, int(font_size * 2)))
            self.text_input.show()
            self.text_input.setFocus()
            event.accept()

    def wheelEvent(self, event):
        # Mouse-wheel vertical panning for navigating 3000x3000 canvas in small windows
        delta_y = event.angleDelta().y()
        max_pan = 0
        min_pan = min(0, self.height() - self.buffer.height())
        self.pan_y = min(max_pan, max(min_pan, self.pan_y + delta_y))

        if self.text_input.isVisible():
            self.text_input.move(
                int(self.text_canvas_pos.x() + self.pan_x),
                int(self.text_canvas_pos.y() + self.pan_y)
            )

        self.update()
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        min_pan = min(0, self.height() - self.buffer.height())
        self.pan_y = min(0, max(min_pan, self.pan_y))

    # --- Paint Event ---
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # Fill background
        painter.fillRect(self.rect(), self.bg_color)

        # Draw offscreen pixmap buffer with panning offset
        painter.drawPixmap(self.pan_x, self.pan_y, self.buffer)

        # Overlay only the active stroke currently being drawn
        if self.current_path is not None:
            painter.save()
            painter.translate(self.pan_x, self.pan_y)
            color = self.get_display_color(self.current_color)
            pen = QPen(
                color, self.current_width,
                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin
            )
            painter.setPen(pen)
            painter.drawPath(self.current_path)
            painter.restore()


class MainWindow(QMainWindow):
    """
    Main Application Window holding the full-screen canvas and floating palette.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Minimalist Drawing Canvas (CP & Math)")
        self.resize(1000, 750)

        # Set central widget
        self.canvas = DrawingCanvas(self)
        self.setCentralWidget(self.canvas)

        # Floating palette widget
        self.palette = FloatingPalette(self, self.canvas)
        self.canvas.set_palette(self.palette)

        # Positional alignment on startup (Top-Center)
        self.reposition_palette()

    def reposition_palette(self):
        palette_width = self.palette.width()
        window_width = self.width()
        x = (window_width - palette_width) // 2
        y = 15
        self.palette.move(max(10, x), y)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reposition_palette()

    # --- Keyboard Shortcuts Handler ---
    def keyPressEvent(self, event):
        # Allow typing into QLineEdit without triggering window shortcuts
        if self.canvas.text_input.hasFocus():
            super().keyPressEvent(event)
            return

        # Undo: Ctrl + Z
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_Z:
            self.canvas.undo_stroke()
            event.accept()
            return

        # Dark Mode: D
        elif event.key() == Qt.Key.Key_D:
            self.canvas.toggle_dark_mode()
            event.accept()
            return

        # Clear Screen: C
        elif event.key() == Qt.Key.Key_C:
            self.canvas.clear_canvas()
            event.accept()
            return

        # Pen width adjust: [ and ]
        elif event.key() == Qt.Key.Key_BracketLeft:
            self.canvas.set_pen_width(self.canvas.current_width - 1)
            event.accept()
            return
        elif event.key() == Qt.Key.Key_BracketRight:
            self.canvas.set_pen_width(self.canvas.current_width + 1)
            event.accept()
            return

        # Quick Colors: 1, 2, 3
        elif event.key() == Qt.Key.Key_1:
            self.canvas.set_pen_color(Qt.GlobalColor.black)
            event.accept()
            return
        elif event.key() == Qt.Key.Key_2:
            self.canvas.set_pen_color(Qt.GlobalColor.red)
            event.accept()
            return
        elif event.key() == Qt.Key.Key_3:
            self.canvas.set_pen_color(Qt.GlobalColor.blue)
            event.accept()
            return

        super().keyPressEvent(event)


def main():
    app = QApplication(sys.argv)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
