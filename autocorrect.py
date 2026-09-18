import math
from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import QPainterPath


def replace_last_stroke(canvas, new_path):
    """
    Helper function to swap canvas.strokes[-1]['path'] with new_path
    and execute canvas.rebuild_buffer().

    Args:
        canvas: The DrawingCanvas instance.
        new_path: The replacement QPainterPath.

    Returns:
        bool: True if replacement succeeded, False otherwise.
    """
    if canvas is not None and hasattr(canvas, 'strokes') and canvas.strokes:
        if isinstance(canvas.strokes[-1], dict):
            canvas.strokes[-1]['path'] = new_path
        else:
            canvas.strokes[-1] = new_path
        canvas.rebuild_buffer()
        return True
    return False


def process(stroke_path, canvas=None):
    """
    Geometry-based shape detection and correction:
    - Lines: If the distance between the start and end points is >= 90% of total stroke length,
             snap to a straight line.
    - Rectangles: If end points are close and the stroke encloses a bounding box,
                  snap to a clean rectangle.
    - Circles/Ellipses: If the bounding box aspect ratio is approx 1:1 and end points are close,
                        snap to a smooth ellipse.

    Args:
        stroke_path: QPainterPath or DrawingCanvas instance.
        canvas: Optional DrawingCanvas instance.

    Returns:
        The processed (snapped or original) QPainterPath.
    """
    # Allow calling as process(canvas)
    if hasattr(stroke_path, 'strokes'):
        canvas = stroke_path
        if not canvas.strokes:
            return None
        last_item = canvas.strokes[-1]
        stroke_path = last_item.get('path') if isinstance(last_item, dict) else last_item

    if stroke_path is None:
        return None

    # Retrieve points (prefer raw sampled points if available from stroke)
    points = []
    if canvas is not None and hasattr(canvas, 'strokes') and canvas.strokes:
        last_item = canvas.strokes[-1]
        if isinstance(last_item, dict) and 'points' in last_item and last_item['points']:
            points = last_item['points']

    # Fallback to extracting elements from QPainterPath
    if not points and hasattr(stroke_path, 'elementCount'):
        for i in range(stroke_path.elementCount()):
            el = stroke_path.elementAt(i)
            points.append(QPointF(el.x, el.y))

    if len(points) < 3:
        return stroke_path

    p0 = points[0]
    p_end = points[-1]

    # Euclidean distance between start and end points
    d_start_end = math.hypot(p_end.x() - p0.x(), p_end.y() - p0.y())

    # Total stroke length
    total_length = sum(
        math.hypot(points[i + 1].x() - points[i].x(), points[i + 1].y() - points[i].y())
        for i in range(len(points) - 1)
    )

    if total_length < 10.0:
        return stroke_path

    # --- 1. Straight Line Detection ---
    # If the distance between the start and end points is >= 90% of total stroke length, snap to a straight line.
    if d_start_end >= 0.90 * total_length:
        new_path = QPainterPath()
        new_path.moveTo(p0)
        new_path.lineTo(p_end)
        if canvas is not None:
            replace_last_stroke(canvas, new_path)
        return new_path

    # Calculate bounding box
    xs = [p.x() for p in points]
    ys = [p.y() for p in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    w = max_x - min_x
    h = max_y - min_y
    diag = math.hypot(w, h)

    if diag < 15.0 or w < 10.0 or h < 10.0:
        return stroke_path

    bbox = QRectF(min_x, min_y, w, h)

    # Check if end points are close
    end_points_close = (d_start_end <= 0.25 * total_length) or (d_start_end <= 0.25 * diag)
    if not end_points_close or total_length < 1.4 * diag:
        return stroke_path

    # Check if stroke encloses the bounding box (visits corners and fills area)
    corners = [(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)]
    corner_dists = [min(math.hypot(p.x() - cx, p.y() - cy) for p in points) / diag for cx, cy in corners]
    avg_corner_dist = sum(corner_dists) / 4.0

    # Shoelace formula to compute stroke area
    n = len(points)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += points[i].x() * points[j].y() - points[j].x() * points[i].y()
    area_ratio = (abs(area) / 2.0) / (w * h)

    # A stroke encloses a bounding box when it reaches near all 4 corners or fills most bounding area
    encloses_bounding_box = (avg_corner_dist < 0.11) or (area_ratio >= 0.85 and avg_corner_dist < 0.14)

    # Aspect ratio
    aspect_ratio = min(w, h) / max(w, h)

    # --- 2. Rectangle Detection ---
    # If end points are close and the stroke encloses a bounding box, snap to a clean rectangle.
    if encloses_bounding_box:
        new_path = QPainterPath()
        new_path.addRect(bbox)
        if canvas is not None:
            replace_last_stroke(canvas, new_path)
        return new_path

    # --- 3. Circle / Ellipse Detection ---
    # If the bounding box aspect ratio is approx 1:1 and end points are close, snap to a smooth ellipse.
    if aspect_ratio >= 0.70:
        new_path = QPainterPath()
        new_path.addEllipse(bbox)
        if canvas is not None:
            replace_last_stroke(canvas, new_path)
        return new_path

    return stroke_path
