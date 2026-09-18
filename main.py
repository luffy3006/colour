import sys
import time
import math
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Protocol

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QSlider, QLabel, QColorDialog, QFrame, QLineEdit
)
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QPainterPath, QPixmap, QFont,
    QTransform, QPainterPathStroker, QUndoStack, QUndoCommand, QCursor, QFontMetrics
)
from PyQt6.QtCore import Qt, QPoint, QPointF, QSize, QRectF, QObject, pyqtSignal, QTimer, QEvent

import autocorrect


# =============================================================================
# 1. State Modeling: Data Classes, Enums, and Items
# =============================================================================

class Ink(Enum):
    """Semantic ink representation. DEFAULT resolves dynamically to the theme foreground."""
    DEFAULT = auto()


@dataclass
class Style:
    color: QColor | Ink = Ink.DEFAULT
    width: float = 5.0
    opacity: float = 1.0
    composition: QPainter.CompositionMode = QPainter.CompositionMode.CompositionMode_SourceOver


@dataclass
class StrokeItem:
    path: QPainterPath
    style: Style
    points: list[QPointF] = field(default_factory=list)
    raw_path: QPainterPath | None = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class TextItem:
    text: str
    pos: QPointF
    font: QFont
    style: Style
    timestamp: float = field(default_factory=time.time)


Item = StrokeItem | TextItem


# =============================================================================
# 2. Document & QUndoStack Commands (Document / View Separation)
# =============================================================================

class AddItemCommand(QUndoCommand):
    def __init__(self, doc: 'Document', item: Item):
        super().__init__("Draw")
        self.doc = doc
        self.item = item

    def redo(self):
        self.doc.items.append(self.item)
        self.doc.item_added.emit(self.item)

    def undo(self):
        if self.doc.items and self.doc.items[-1] is self.item:
            self.doc.items.pop()
        elif self.item in self.doc.items:
            self.doc.items.remove(self.item)
        self.doc.invalidated.emit()


class RemoveItemCommand(QUndoCommand):
    def __init__(self, doc: 'Document', item: Item):
        super().__init__("Erase")
        self.doc = doc
        self.item = item
        self.index = doc.items.index(item) if item in doc.items else len(doc.items)

    def redo(self):
        if self.item in self.doc.items:
            self.doc.items.remove(self.item)
            self.doc.invalidated.emit()

    def undo(self):
        idx = min(self.index, len(self.doc.items))
        self.doc.items.insert(idx, self.item)
        self.doc.invalidated.emit()


class ClearCommand(QUndoCommand):
    def __init__(self, doc: 'Document'):
        super().__init__("Clear Canvas")
        self.doc = doc
        self.saved_items = list(doc.items)

    def redo(self):
        self.doc.items.clear()
        self.doc.invalidated.emit()

    def undo(self):
        self.doc.items = list(self.saved_items)
        self.doc.invalidated.emit()


class AutocorrectCommand(QUndoCommand):
    def __init__(self, doc: 'Document', stroke: StrokeItem, new_path: QPainterPath):
        super().__init__("Autocorrect Shape")
        self.doc = doc
        self.stroke = stroke
        self.raw_path = stroke.raw_path or stroke.path
        self.new_path = new_path

    def redo(self):
        self.stroke.raw_path = self.raw_path
        self.stroke.path = self.new_path
        self.doc.invalidated.emit()

    def undo(self):
        self.stroke.path = self.raw_path
        self.doc.invalidated.emit()


class Document(QObject):
    item_added = pyqtSignal(object)
    invalidated = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.items: list[Item] = []
        self.undo_stack = QUndoStack(self)

    def add_item(self, item: Item):
        self.undo_stack.push(AddItemCommand(self, item))

    def remove_item(self, item: Item):
        self.undo_stack.push(RemoveItemCommand(self, item))

    def clear(self):
        if self.items:
            self.undo_stack.push(ClearCommand(self))

    def autocorrect_stroke(self, stroke: StrokeItem, new_path: QPainterPath):
        self.undo_stack.push(AutocorrectCommand(self, stroke, new_path))


# =============================================================================
# 3. Tool Protocol & Implementations
# =============================================================================

class Tool(Protocol):
    cursor: Qt.CursorShape

    def press(self, canvas: 'DrawingCanvas', pt: QPointF, event) -> None: ...
    def move(self, canvas: 'DrawingCanvas', pt: QPointF, event) -> None: ...
    def release(self, canvas: 'DrawingCanvas', pt: QPointF, event) -> Item | None: ...
    def paint_preview(self, painter: QPainter, canvas: 'DrawingCanvas') -> None: ...


class PenTool:
    cursor = Qt.CursorShape.CrossCursor

    def __init__(self):
        self.current_path: QPainterPath | None = None
        self.points: list[QPointF] = []
        self.last_point: QPointF | None = None

    def press(self, canvas: 'DrawingCanvas', pt: QPointF, event) -> None:
        self.current_path = QPainterPath()
        self.current_path.moveTo(pt)
        self.points = [pt]
        self.last_point = pt

    def move(self, canvas: 'DrawingCanvas', pt: QPointF, event) -> None:
        if self.current_path is not None and self.last_point is not None:
            mid_point = QPointF(
                (self.last_point.x() + pt.x()) / 2.0,
                (self.last_point.y() + pt.y()) / 2.0
            )
            self.current_path.quadTo(self.last_point, mid_point)
            self.last_point = pt
            self.points.append(pt)

    def release(self, canvas: 'DrawingCanvas', pt: QPointF, event) -> Item | None:
        if self.current_path is not None:
            self.current_path.lineTo(pt)
            self.points.append(pt)

            style = Style(
                color=canvas.current_color,
                width=canvas.current_width * canvas.stylus_pressure,
                opacity=1.0
            )
            stroke = StrokeItem(
                path=self.current_path,
                style=style,
                points=list(self.points),
                raw_path=QPainterPath(self.current_path),
                timestamp=time.time()
            )
            self.current_path = None
            self.points = []
            self.last_point = None
            return stroke
        return None

    def paint_preview(self, painter: QPainter, canvas: 'DrawingCanvas') -> None:
        if self.current_path is not None:
            color = canvas.get_display_color(canvas.current_color)
            pen = QPen(
                color, canvas.current_width * canvas.stylus_pressure,
                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin
            )
            painter.setPen(pen)
            painter.drawPath(self.current_path)


class HighlighterTool:
    cursor = Qt.CursorShape.CrossCursor

    def __init__(self):
        self.current_path: QPainterPath | None = None
        self.points: list[QPointF] = []
        self.last_point: QPointF | None = None

    def press(self, canvas: 'DrawingCanvas', pt: QPointF, event) -> None:
        self.current_path = QPainterPath()
        self.current_path.moveTo(pt)
        self.points = [pt]
        self.last_point = pt

    def move(self, canvas: 'DrawingCanvas', pt: QPointF, event) -> None:
        if self.current_path is not None and self.last_point is not None:
            mid_point = QPointF(
                (self.last_point.x() + pt.x()) / 2.0,
                (self.last_point.y() + pt.y()) / 2.0
            )
            self.current_path.quadTo(self.last_point, mid_point)
            self.last_point = pt
            self.points.append(pt)

    def release(self, canvas: 'DrawingCanvas', pt: QPointF, event) -> Item | None:
        if self.current_path is not None:
            self.current_path.lineTo(pt)
            self.points.append(pt)

            style = Style(
                color=canvas.current_color if canvas.current_color != Ink.DEFAULT else QColor("#FFEB3B"),
                width=max(20.0, canvas.current_width * 3.5),
                opacity=0.35
            )
            stroke = StrokeItem(
                path=self.current_path,
                style=style,
                points=list(self.points),
                raw_path=QPainterPath(self.current_path),
                timestamp=time.time()
            )
            self.current_path = None
            self.points = []
            self.last_point = None
            return stroke
        return None

    def paint_preview(self, painter: QPainter, canvas: 'DrawingCanvas') -> None:
        if self.current_path is not None:
            color = canvas.get_display_color(canvas.current_color if canvas.current_color != Ink.DEFAULT else QColor("#FFEB3B"))
            color = QColor(color)
            color.setAlphaF(0.35)
            pen = QPen(
                color, max(20.0, canvas.current_width * 3.5),
                Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap, Qt.PenJoinStyle.RoundJoin
            )
            painter.setPen(pen)
            painter.drawPath(self.current_path)


class EraserTool:
    cursor = Qt.CursorShape.CrossCursor

    def __init__(self):
        self.current_pos: QPointF | None = None

    def _erase_at(self, canvas: 'DrawingCanvas', pt: QPointF) -> None:
        radius = max(16.0, canvas.current_width * 2.5)
        eraser_rect = QRectF(pt.x() - radius, pt.y() - radius, radius * 2, radius * 2)

        stroker = QPainterPathStroker()
        # Find all intersecting items and remove them via QUndoStack
        for item in list(canvas.doc.items):
            if isinstance(item, StrokeItem):
                stroker.setWidth(max(item.style.width, 10.0))
                stroke_outline = stroker.createStroke(item.path)
                if stroke_outline.intersects(eraser_rect):
                    canvas.doc.remove_item(item)
            elif isinstance(item, TextItem):
                text_rect = QRectF(item.pos.x(), item.pos.y(), 200, 40)
                if text_rect.intersects(eraser_rect):
                    canvas.doc.remove_item(item)

    def press(self, canvas: 'DrawingCanvas', pt: QPointF, event) -> None:
        self.current_pos = pt
        self._erase_at(canvas, pt)

    def move(self, canvas: 'DrawingCanvas', pt: QPointF, event) -> None:
        self.current_pos = pt
        self._erase_at(canvas, pt)

    def release(self, canvas: 'DrawingCanvas', pt: QPointF, event) -> Item | None:
        self.current_pos = None
        return None

    def paint_preview(self, painter: QPainter, canvas: 'DrawingCanvas') -> None:
        if self.current_pos is not None:
            radius = max(16.0, canvas.current_width * 2.5)
            pen = QPen(QColor(180, 180, 180, 180), 1.5, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(QColor(240, 240, 240, 60))
            painter.drawEllipse(self.current_pos, radius, radius)


# =============================================================================
# 4. Floating Toolbar Widget (Clamped & Clean)
# =============================================================================

class FloatingPalette(QFrame):
    """
    A minimalist, floating, draggable, and collapsible palette.
    Automatically clamped to parent window to prevent being dragged off-screen.
    """
    def __init__(self, parent, canvas: 'DrawingCanvas'):
        super().__init__(parent)
        self.canvas = canvas
        self.drag_position = QPoint()
        self.is_dragging = False

        self.setObjectName("Palette")
        self.setStyleSheet("""
            QFrame#Palette {
                background-color: rgba(245, 245, 245, 235);
                border: 1px solid rgba(200, 200, 200, 160);
                border-radius: 12px;
            }
            QPushButton {
                border: none;
                border-radius: 6px;
                padding: 6px 9px;
                font-weight: bold;
                font-size: 11px;
                background-color: rgba(220, 220, 220, 200);
            }
            QPushButton:hover { background-color: rgba(200, 200, 200, 220); }
            QPushButton:pressed { background-color: rgba(180, 180, 180, 220); }
            QPushButton.activeTool {
                background-color: #2b7fff;
                color: white;
            }
            QSlider::groove:horizontal {
                border: 1px solid #bbb;
                background: white;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal { background: #555; border-radius: 3px; }
            QSlider::handle:horizontal {
                background: #333;
                border: 1px solid #333;
                width: 14px;
                margin-top: -4px;
                margin-bottom: -4px;
                border-radius: 7px;
            }
        """)

        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(8, 6, 8, 6)
        self.main_layout.setSpacing(8)

        self.drag_handle = QLabel("⋮⋮", self)
        self.drag_handle.setStyleSheet("color: #888; font-weight: bold; font-size: 14px; margin-right: 4px;")
        self.drag_handle.setCursor(Qt.CursorShape.SizeAllCursor)
        self.main_layout.addWidget(self.drag_handle)

        self.content_widget = QWidget(self)
        self.content_layout = QHBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(8)
        self.main_layout.addWidget(self.content_widget)

        # Tool selection buttons
        self.btn_pen = QPushButton("🖊️ Pen", self)
        self.btn_pen.clicked.connect(lambda: self.canvas.set_tool("pen"))
        self.content_layout.addWidget(self.btn_pen)

        self.btn_highlighter = QPushButton("🖍️ Highlight", self)
        self.btn_highlighter.clicked.connect(lambda: self.canvas.set_tool("highlighter"))
        self.content_layout.addWidget(self.btn_highlighter)

        self.btn_eraser = QPushButton("🧹 Erase", self)
        self.btn_eraser.clicked.connect(lambda: self.canvas.set_tool("eraser"))
        self.content_layout.addWidget(self.btn_eraser)

        # Colors
        self.btn_default = QPushButton("● Ink", self)
        self.btn_default.setStyleSheet("color: #111; font-weight: bold;")
        self.btn_default.clicked.connect(lambda: self.canvas.set_pen_color(Ink.DEFAULT))
        self.content_layout.addWidget(self.btn_default)

        self.btn_red = QPushButton("● Red", self)
        self.btn_red.setStyleSheet("color: #d32f2f; background-color: rgba(255, 230, 230, 200);")
        self.btn_red.clicked.connect(lambda: self.canvas.set_pen_color(QColor(Qt.GlobalColor.red)))
        self.content_layout.addWidget(self.btn_red)

        self.btn_blue = QPushButton("● Blue", self)
        self.btn_blue.setStyleSheet("color: #1976d2; background-color: rgba(230, 230, 255, 200);")
        self.btn_blue.clicked.connect(lambda: self.canvas.set_pen_color(QColor(Qt.GlobalColor.blue)))
        self.content_layout.addWidget(self.btn_blue)

        self.btn_custom = QPushButton("🎨 More", self)
        self.btn_custom.clicked.connect(self.choose_custom_color)
        self.content_layout.addWidget(self.btn_custom)

        # Thickness slider
        self.lbl_thickness = QLabel("Size: 5", self)
        self.lbl_thickness.setStyleSheet("font-size: 11px; font-weight: bold; color: #333;")
        self.content_layout.addWidget(self.lbl_thickness)

        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(1, 50)
        self.slider.setValue(5)
        self.slider.setFixedWidth(80)
        self.slider.valueChanged.connect(self.canvas.set_pen_width)
        self.content_layout.addWidget(self.slider)

        # Clear Canvas Button
        self.btn_clear = QPushButton("🗑️ Clear", self)
        self.btn_clear.setStyleSheet("background-color: rgba(255, 210, 210, 220); color: #aa0000;")
        self.btn_clear.clicked.connect(self.canvas.clear_canvas)
        self.content_layout.addWidget(self.btn_clear)

        # Collapse / Expand Toggle Button
        self.btn_collapse = QPushButton("◀", self)
        self.btn_collapse.setFixedWidth(28)
        self.btn_collapse.setStyleSheet("font-size: 10px; font-weight: bold;")
        self.btn_collapse.clicked.connect(self.toggle_collapse)
        self.main_layout.addWidget(self.btn_collapse)

        self.is_collapsed = False
        self.adjustSize()

    def choose_custom_color(self):
        curr = self.canvas.get_display_color(self.canvas.current_color)
        color = QColorDialog.getColor(curr, self, "Choose Pen Color")
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

    def update_thickness_label(self, width: int):
        self.lbl_thickness.setText(f"Size: {width}")
        if self.slider.value() != width:
            self.slider.blockSignals(True)
            self.slider.setValue(width)
            self.slider.blockSignals(False)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.drag_handle.geometry().contains(event.position().toPoint()) or event.position().y() < 15:
                self.is_dragging = True
                self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.is_dragging and (event.buttons() & Qt.MouseButton.LeftButton):
            parent_widget = self.parentWidget()
            new_pos = event.globalPosition().toPoint() - self.drag_position
            if parent_widget:
                max_x = max(0, parent_widget.width() - self.width())
                max_y = max(0, parent_widget.height() - self.height())
                clamped_x = max(0, min(max_x, new_pos.x()))
                clamped_y = max(0, min(max_y, new_pos.y()))
                self.move(clamped_x, clamped_y)
            else:
                self.move(new_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.is_dragging = False
        super().mouseReleaseEvent(event)


# =============================================================================
# 5. Canvas Text Input Overlay (Precise Baseline Alignment)
# =============================================================================

class CanvasLineEdit(QLineEdit):
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


# =============================================================================
# 6. High-Performance Drawing Canvas (Document View)
# =============================================================================

class DrawingCanvas(QWidget):
    """
    High-performance, zero-latency drawing surface.
    - HiDPI-aware offscreen QPixmap buffer.
    - View transform: 2D panning + Zoom-at-cursor with debounce re-rasterization.
    - Document / View separation backed by QUndoStack for full Undo/Redo.
    - Pure geometric autocorrect with undoable shape replacement.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Document & History Stack
        self.doc = Document()
        self.doc.item_added.connect(self._on_item_added)
        self.doc.invalidated.connect(self.rebuild_buffer)

        # HiDPI Offscreen pixmap buffer (3000x3000px)
        self.buffer_size = QSize(3000, 3000)
        self._init_buffer()

        # Theme & Background
        self.dark_mode = False
        self.bg_color = QColor("#FFFFFF")
        self.buffer.fill(self.bg_color)
        self.setStyleSheet("background-color: #FFFFFF;")

        # Navigation: 2D Pan and Zoom
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.zoom = 1.0
        self.is_panning = False
        self.is_space_pressed = False
        self.last_pan_pos = QPointF(0, 0)

        # Zoom settle timer for crisp re-rasterization
        self.zoom_settle_timer = QTimer(self)
        self.zoom_settle_timer.setSingleShot(True)
        self.zoom_settle_timer.setInterval(120)
        self.zoom_settle_timer.timeout.connect(self.rebuild_buffer)

        # Pen & Tool State
        self.current_color: QColor | Ink = Ink.DEFAULT
        self.current_width: float = 5.0
        self.stylus_pressure: float = 1.0

        self.tools = {
            "pen": PenTool(),
            "highlighter": HighlighterTool(),
            "eraser": EraserTool(),
        }
        self.active_tool: Tool = self.tools["pen"]
        self.setCursor(self.active_tool.cursor)

        # Text input overlay
        self.text_input = CanvasLineEdit(self)
        self.text_input.returnPressed.connect(self.commit_text)
        self.text_canvas_pos = QPointF(0, 0)
        self.palette: FloatingPalette | None = None

    # --- Backwards compatibility for strokes list ---
    @property
    def strokes(self):
        return self.doc.items

    def _init_buffer(self):
        dpr = self.devicePixelRatioF()
        w = int(self.buffer_size.width() * dpr)
        h = int(self.buffer_size.height() * dpr)
        self.buffer = QPixmap(w, h)
        self.buffer.setDevicePixelRatio(dpr)

    def set_palette(self, palette: FloatingPalette):
        self.palette = palette

    def set_tool(self, name: str):
        if name in self.tools:
            self.active_tool = self.tools[name]
            self.setCursor(self.active_tool.cursor)

    def set_pen_color(self, color: QColor | Ink):
        self.current_color = color

    def set_pen_width(self, width: float):
        self.current_width = max(1.0, min(50.0, float(width)))
        if self.palette:
            self.palette.update_thickness_label(int(self.current_width))

    def view_transform(self) -> QTransform:
        t = QTransform()
        t.translate(self.pan_x, self.pan_y)
        t.scale(self.zoom, self.zoom)
        return t

    def map_to_canvas(self, pos: QPointF | QPoint) -> QPointF:
        inv, ok = self.view_transform().inverted()
        if ok:
            return inv.map(QPointF(pos))
        return QPointF(pos)

    def get_display_color(self, color: QColor | Ink) -> QColor:
        """Resolves Ink.DEFAULT to theme foreground; preserves explicit RGB."""
        if color == Ink.DEFAULT:
            return QColor("#FFFFFF") if self.dark_mode else QColor("#000000")
        return QColor(color)

    def toggle_dark_mode(self):
        self.dark_mode = not self.dark_mode
        self.bg_color = QColor("#121212") if self.dark_mode else QColor("#FFFFFF")
        self.setStyleSheet(f"background-color: {'#121212' if self.dark_mode else '#FFFFFF'};")
        self.rebuild_buffer()

    def clear_canvas(self):
        self.doc.clear()
        if self.text_input.isVisible():
            self.text_input.clear()
            self.text_input.hide()

    def undo_stroke(self):
        self.doc.undo_stack.undo()

    def redo_stroke(self):
        self.doc.undo_stack.redo()

    def zoom_at(self, screen_pt: QPointF, factor: float):
        before = self.map_to_canvas(screen_pt)
        new_zoom = max(0.2, min(5.0, self.zoom * factor))
        if new_zoom == self.zoom:
            return
        self.zoom = new_zoom
        after = self.map_to_canvas(screen_pt)
        d = after - before
        self.pan_x += d.x() * self.zoom
        self.pan_y += d.y() * self.zoom
        self.zoom_settle_timer.start()
        self.update()

    # --- Unified Rendering Pipeline ---
    def _paint_item(self, painter: QPainter, item: Item):
        if isinstance(item, TextItem):
            painter.setFont(item.font)
            color = self.get_display_color(item.style.color)
            painter.setPen(color)
            fm = QFontMetrics(item.font)
            # Match exact QLineEdit vertical centering alignment
            baseline_y = item.pos.y() + (max(30.0, fm.height() * 1.4) - fm.height()) / 2.0 + fm.ascent()
            painter.drawText(QPointF(item.pos.x(), baseline_y), item.text)

        elif isinstance(item, StrokeItem):
            color = self.get_display_color(item.style.color)
            if item.style.opacity < 1.0:
                color = QColor(color)
                color.setAlphaF(item.style.opacity)
            pen = QPen(
                color, item.style.width,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.FlatCap if item.style.opacity < 1.0 else Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin
            )
            painter.setPen(pen)
            painter.drawPath(item.path)

    def _on_item_added(self, item: Item):
        """Incremental blit directly to offscreen buffer."""
        painter = QPainter(self.buffer)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self._paint_item(painter, item)
        painter.end()
        self.update()

    def rebuild_buffer(self):
        """Full buffer redraw from document items."""
        self.buffer.fill(self.bg_color)
        painter = QPainter(self.buffer)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        for item in self.doc.items:
            self._paint_item(painter, item)

        painter.end()
        self.update()

    def commit_text(self):
        text = self.text_input.text().strip()
        if text:
            style = Style(color=self.current_color, width=self.current_width)
            item = TextItem(
                text=text,
                pos=self.text_canvas_pos,
                font=self.text_input.font(),
                style=style,
                timestamp=time.time()
            )
            self.doc.add_item(item)
        self.text_input.hide()
        self.text_input.clear()

    # --- Mouse & Tablet Event Handlers ---
    def tabletEvent(self, event):
        event.accept()
        pos = self.map_to_canvas(event.position())
        pressure = event.pressure()
        if pressure > 0:
            self.stylus_pressure = max(0.4, min(1.8, pressure * 1.5))

        if event.type() == QEvent.Type.TabletPress:
            self.active_tool.press(self, pos, event)
        elif event.type() == QEvent.Type.TabletMove:
            self.active_tool.move(self, pos, event)
        elif event.type() == QEvent.Type.TabletRelease:
            item = self.active_tool.release(self, pos, event)
            if item is not None:
                self.doc.add_item(item)
                if isinstance(item, StrokeItem):
                    new_path = autocorrect.recognize(item.points)
                    if new_path is not None:
                        self.doc.autocorrect_stroke(item, new_path)
            self.stylus_pressure = 1.0
        self.update()

    def mousePressEvent(self, event):
        # 2D Panning: Middle-Click or Space + Left-Click
        if event.button() == Qt.MouseButton.MiddleButton or (event.button() == Qt.MouseButton.LeftButton and self.is_space_pressed):
            self.is_panning = True
            self.last_pan_pos = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton:
            if self.text_input.isVisible() or self.text_input.text():
                self.commit_text()

            pos = self.map_to_canvas(event.position())
            self.active_tool.press(self, pos, event)
            self.update()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.is_panning:
            delta = event.position() - self.last_pan_pos
            self.pan_x += delta.x()
            self.pan_y += delta.y()
            self.last_pan_pos = event.position()
            self.update()
            event.accept()
            return

        if event.buttons() & Qt.MouseButton.LeftButton:
            pos = self.map_to_canvas(event.position())
            self.active_tool.move(self, pos, event)
            self.update()
            event.accept()

    def mouseReleaseEvent(self, event):
        if self.is_panning:
            self.is_panning = False
            self.setCursor(Qt.CursorShape.OpenHandCursor if self.is_space_pressed else self.active_tool.cursor)
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton:
            pos = self.map_to_canvas(event.position())
            item = self.active_tool.release(self, pos, event)
            if item is not None:
                self.doc.add_item(item)
                # Geometric Shape Autocorrection
                if isinstance(item, StrokeItem):
                    new_path = autocorrect.recognize(item.points)
                    if new_path is not None:
                        self.doc.autocorrect_stroke(item, new_path)
            self.update()
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = self.map_to_canvas(event.position())
            # Precision double-click: only pop stroke if created in last 450ms at this exact location
            if self.doc.items:
                last_item = self.doc.items[-1]
                if isinstance(last_item, StrokeItem):
                    now = time.time()
                    if (now - last_item.timestamp < 0.45) and last_item.points:
                        p0 = last_item.points[0]
                        if math.hypot(p0.x() - pos.x(), p0.y() - pos.y()) < 35.0:
                            self.doc.items.pop()
                            self.rebuild_buffer()

            if self.text_input.isVisible():
                self.commit_text()

            click_pos = event.position().toPoint()
            self.text_canvas_pos = pos

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
            fm = QFontMetrics(font)
            input_height = max(30, int(fm.height() * 1.4))
            self.text_input.resize(400, input_height)
            self.text_input.show()
            self.text_input.setFocus()
            event.accept()

    def wheelEvent(self, event):
        # Ctrl + Wheel -> Zoom at cursor
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            angle = event.angleDelta().y()
            if angle != 0:
                factor = 1.0015 ** angle
                self.zoom_at(event.position(), factor)
            event.accept()
            return

        # Trackpad vs Mouse Wheel Panning
        pixel_delta = event.pixelDelta()
        if not pixel_delta.isNull():
            dx = float(pixel_delta.x())
            dy = float(pixel_delta.y())
        else:
            angle_delta = event.angleDelta()
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                dx = angle_delta.y() / 4.0
                dy = 0.0
            else:
                dx = angle_delta.x() / 4.0
                dy = angle_delta.y() / 4.0

        self.pan_x += dx
        self.pan_y += dy
        self.update()
        event.accept()

    def changeEvent(self, event):
        super().changeEvent(event)
        # Handle HiDPI DevicePixelRatio changes (e.g. dragged across monitors)
        if event.type() == QEvent.Type.DevicePixelRatioChange:
            self._init_buffer()
            self.rebuild_buffer()

    # --- Paint Event: High-Speed Sub-Rect Blit ---
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        target = event.rect()
        painter.fillRect(target, self.bg_color)

        inv, ok = self.view_transform().inverted()
        if ok:
            source = inv.mapRect(QRectF(target)).intersected(
                QRectF(0, 0, self.buffer_size.width(), self.buffer_size.height())
            )
            if not source.isEmpty():
                target_sub = self.view_transform().mapRect(source)
                painter.drawPixmap(target_sub, self.buffer, source)

        # Overlay active tool preview
        painter.save()
        painter.setTransform(self.view_transform())
        if self.active_tool:
            self.active_tool.paint_preview(painter, self)
        painter.restore()


# =============================================================================
# 7. Main Application Window
# =============================================================================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Minimalist Drawing Canvas (CP & Math)")
        self.resize(1050, 780)

        self.canvas = DrawingCanvas(self)
        self.setCentralWidget(self.canvas)

        self.palette = FloatingPalette(self, self.canvas)
        self.canvas.set_palette(self.palette)
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

    def keyPressEvent(self, event):
        if self.canvas.text_input.hasFocus():
            super().keyPressEvent(event)
            return

        # Space key for Pan Hand Tool
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self.canvas.is_space_pressed = True
            self.canvas.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return

        # Redo: Ctrl + Shift + Z or Ctrl + Y
        if (event.modifiers() == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier) and event.key() == Qt.Key.Key_Z) or \
           (event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_Y):
            self.canvas.redo_stroke()
            event.accept()
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

        # Clear Canvas: C or Ctrl + Shift + C
        elif event.key() == Qt.Key.Key_C:
            self.canvas.clear_canvas()
            event.accept()
            return

        # Pen width adjust: [ and ]
        elif event.key() == Qt.Key.Key_BracketLeft:
            self.canvas.set_pen_width(self.canvas.current_width - 1.0)
            event.accept()
            return
        elif event.key() == Qt.Key.Key_BracketRight:
            self.canvas.set_pen_width(self.canvas.current_width + 1.0)
            event.accept()
            return

        # Quick Colors: 1, 2, 3
        elif event.key() == Qt.Key.Key_1:
            self.canvas.set_pen_color(Ink.DEFAULT)
            event.accept()
            return
        elif event.key() == Qt.Key.Key_2:
            self.canvas.set_pen_color(QColor(Qt.GlobalColor.red))
            event.accept()
            return
        elif event.key() == Qt.Key.Key_3:
            self.canvas.set_pen_color(QColor(Qt.GlobalColor.blue))
            event.accept()
            return

        # Tool Shortcuts: P (Pen), H (Highlighter), E (Eraser)
        elif event.key() == Qt.Key.Key_P:
            self.canvas.set_tool("pen")
            event.accept()
            return
        elif event.key() == Qt.Key.Key_H:
            self.canvas.set_tool("highlighter")
            event.accept()
            return
        elif event.key() == Qt.Key.Key_E:
            self.canvas.set_tool("eraser")
            event.accept()
            return

        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self.canvas.is_space_pressed = False
            self.canvas.setCursor(self.canvas.active_tool.cursor)
            event.accept()
            return
        super().keyReleaseEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Whiteboard")
    app.setDesktopFileName("whiteboard")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
