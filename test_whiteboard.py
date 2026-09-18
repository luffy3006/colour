import unittest
import math
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QPainterPath

import main
import autocorrect

# Ensure single QApplication instance for Qt unit testing
app = QApplication.instance() or QApplication(sys.argv)


class TestGeometricRecognition(unittest.TestCase):
    def test_resample_points(self):
        pts = [QPointF(0, 0), QPointF(100, 0)]
        res = autocorrect.resample_points(pts, 64)
        self.assertEqual(len(res), 64)
        self.assertAlmostEqual(res[0].x(), 0.0)
        self.assertAlmostEqual(res[-1].x(), 100.0)

    def test_straight_line(self):
        line = [QPointF(i * 10, i * 10) for i in range(25)]
        path = autocorrect.recognize(line)
        self.assertIsNotNone(path)
        self.assertEqual(path.elementCount(), 2)

    def test_circle_recognition(self):
        circle = [
            QPointF(200 + 60 * math.cos(t), 200 + 60 * math.sin(t))
            for t in [i * 2 * math.pi / 50 for i in range(51)]
        ]
        path = autocorrect.recognize(circle)
        self.assertIsNotNone(path)
        # Ellipse painter path contains Bezier curve control points (> 5 elements)
        self.assertGreater(path.elementCount(), 4)

    def test_triangle_recognition(self):
        tri = []
        for i in range(15): tri.append(QPointF(100 + i * 5, 100 + i * 5))
        for i in range(15): tri.append(QPointF(175 - i * 5, 175 + i * 5))
        for i in range(15): tri.append(QPointF(100, 250 - i * 10))
        tri.append(tri[0])
        path = autocorrect.recognize(tri)
        self.assertIsNotNone(path)
        # Triangle has 3 lines + closeSubpath
        self.assertGreaterEqual(path.elementCount(), 3)

    def test_rectangle_recognition(self):
        rect = []
        for i in range(20): rect.append(QPointF(50 + i * 5, 50))
        for i in range(20): rect.append(QPointF(150, 50 + i * 5))
        for i in range(20): rect.append(QPointF(150 - i * 5, 150))
        for i in range(20): rect.append(QPointF(50, 150 - i * 5))
        rect.append(rect[0])
        path = autocorrect.recognize(rect)
        self.assertIsNotNone(path)


class TestDocumentStateAndUndo(unittest.TestCase):
    def setUp(self):
        self.doc = main.Document()

    def test_add_undo_redo(self):
        p1 = QPointF(10, 10)
        p2 = QPointF(50, 50)
        path = QPainterPath()
        path.moveTo(p1)
        path.lineTo(p2)
        stroke = main.StrokeItem(path=path, style=main.Style(), points=[p1, p2])

        self.doc.add_item(stroke)
        self.assertEqual(len(self.doc.items), 1)
        self.assertTrue(self.doc.undo_stack.canUndo())

        # Undo
        self.doc.undo_stack.undo()
        self.assertEqual(len(self.doc.items), 0)
        self.assertTrue(self.doc.undo_stack.canRedo())

        # Redo
        self.doc.undo_stack.redo()
        self.assertEqual(len(self.doc.items), 1)

    def test_autocorrect_command(self):
        p1 = QPointF(0, 0)
        p2 = QPointF(100, 100)
        raw_path = QPainterPath()
        raw_path.moveTo(p1)
        raw_path.lineTo(p2)
        stroke = main.StrokeItem(path=raw_path, style=main.Style(), points=[p1, p2], raw_path=raw_path)
        self.doc.add_item(stroke)

        corrected_path = QPainterPath()
        corrected_path.addRect(0, 0, 100, 100)
        self.doc.autocorrect_stroke(stroke, corrected_path)
        self.assertEqual(stroke.path, corrected_path)

        # Undo restores original raw path
        self.doc.undo_stack.undo()
        self.assertEqual(stroke.path, raw_path)

    def test_clear_is_undoable(self):
        stroke = main.StrokeItem(path=QPainterPath(), style=main.Style())
        self.doc.add_item(stroke)
        self.assertEqual(len(self.doc.items), 1)

        self.doc.clear()
        self.assertEqual(len(self.doc.items), 0)

        # Undo restores cleared items
        self.doc.undo_stack.undo()
        self.assertEqual(len(self.doc.items), 1)


class TestCanvasFeatures(unittest.TestCase):
    def setUp(self):
        self.canvas = main.DrawingCanvas()

    def test_semantic_ink_resolution(self):
        # Default ink
        self.canvas.dark_mode = False
        self.assertEqual(self.canvas.get_display_color(main.Ink.DEFAULT), QColor("#000000"))
        self.canvas.dark_mode = True
        self.assertEqual(self.canvas.get_display_color(main.Ink.DEFAULT), QColor("#FFFFFF"))

        # Explicit color never inverts
        red = QColor(Qt.GlobalColor.red)
        self.assertEqual(self.canvas.get_display_color(red), red)

    def test_zoom_and_transform(self):
        anchor = QPointF(300, 200)
        before_canvas = self.canvas.map_to_canvas(anchor)
        self.canvas.zoom_at(anchor, 2.0)
        after_canvas = self.canvas.map_to_canvas(anchor)
        # Point under cursor remains anchored
        self.assertAlmostEqual(before_canvas.x(), after_canvas.x(), delta=1.0)
        self.assertAlmostEqual(before_canvas.y(), after_canvas.y(), delta=1.0)


if __name__ == "__main__":
    unittest.main()
