import math
from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import QPainterPath


def resample_points(points: list[QPointF], n: int = 64) -> list[QPointF]:
    """
    Uniformly resamples a stroke polyline to n points by cumulative arclength.
    Immune to speed/sample-rate differences in mouse or stylus hardware.
    """
    if len(points) < 2:
        return points

    dists = [0.0]
    for i in range(len(points) - 1):
        d = math.hypot(points[i + 1].x() - points[i].x(), points[i + 1].y() - points[i].y())
        dists.append(dists[-1] + d)

    total_len = dists[-1]
    if total_len == 0:
        return [points[0]] * n

    step = total_len / (n - 1)
    resampled = [points[0]]
    curr_idx = 0

    for i in range(1, n - 1):
        target_d = i * step
        while curr_idx < len(dists) - 1 and dists[curr_idx + 1] < target_d:
            curr_idx += 1
        d0, d1 = dists[curr_idx], dists[curr_idx + 1]
        t = (target_d - d0) / (d1 - d0) if d1 > d0 else 0.0
        p0, p1 = points[curr_idx], points[curr_idx + 1]
        resampled.append(
            QPointF(p0.x() + t * (p1.x() - p0.x()), p0.y() + t * (p1.y() - p0.y()))
        )

    resampled.append(points[-1])
    return resampled


def point_line_dist(pt: QPointF, p1: QPointF, p2: QPointF) -> float:
    """Computes perpendicular distance from pt to line segment (p1, p2)."""
    dx = p2.x() - p1.x()
    dy = p2.y() - p1.y()
    l2 = dx * dx + dy * dy
    if l2 == 0:
        return math.hypot(pt.x() - p1.x(), pt.y() - p1.y())
    return abs(dy * pt.x() - dx * pt.y() + p2.x() * p1.y() - p2.y() * p1.x()) / math.sqrt(l2)


def douglas_peucker(pts: list[QPointF], epsilon: float) -> list[QPointF]:
    """Ramer-Douglas-Peucker polyline simplification algorithm."""
    if len(pts) <= 2:
        return pts
    dmax = 0.0
    index = 0
    p1 = pts[0]
    p2 = pts[-1]
    for i in range(1, len(pts) - 1):
        d = point_line_dist(pts[i], p1, p2)
        if d > dmax:
            index = i
            dmax = d
    if dmax > epsilon:
        rec1 = douglas_peucker(pts[: index + 1], epsilon)
        rec2 = douglas_peucker(pts[index:], epsilon)
        return rec1[:-1] + rec2
    else:
        return [p1, p2]


def recognize(points: list[QPointF]) -> QPainterPath | None:
    """
    Pure, side-effect-free geometry recognizer:
    1. Resamples to 64 equidistant points.
    2. Straight line: max chord deviation < 5% chord length.
    3. Closed shapes: endpoints within 25% diagonal.
       - Radial variance < 15% -> smooth circle/ellipse.
       - Douglas-Peucker:
         - 3 vertices -> Triangle.
         - 4 vertices -> Rectangle / Quad.
    """
    if len(points) < 4:
        return None

    res = resample_points(points, 64)
    p0 = res[0]
    p_end = res[-1]
    chord_len = math.hypot(p_end.x() - p0.x(), p_end.y() - p0.y())

    # --- 1. Line Test: Perpendicular Chord Deviation ---
    if chord_len > 15.0:
        max_dev = max(point_line_dist(p, p0, p_end) for p in res)
        if max_dev / chord_len < 0.055:
            path = QPainterPath()
            path.moveTo(p0)
            path.lineTo(p_end)
            return path

    # Bounding Box calculations
    xs = [p.x() for p in res]
    ys = [p.y() for p in res]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    w = max_x - min_x
    h = max_y - min_y
    diag = math.hypot(w, h)

    if diag < 20.0 or w < 10.0 or h < 10.0:
        return None

    # Endpoints close check (loop / closed shape)
    if chord_len > 0.28 * diag:
        return None

    bbox = QRectF(min_x, min_y, w, h)
    cx, cy = bbox.center().x(), bbox.center().y()

    # --- 2. Ellipse / Circle Test: Radial Variance ---
    radii = [math.hypot(p.x() - cx, p.y() - cy) for p in res]
    mean_r = sum(radii) / len(radii)
    if mean_r > 0:
        std_r = math.sqrt(sum((r - mean_r) ** 2 for r in radii) / len(radii))
        rad_var = std_r / mean_r
        aspect_ratio = min(w, h) / max(w, h)
        if rad_var < 0.16 and aspect_ratio >= 0.65:
            path = QPainterPath()
            path.addEllipse(bbox)
            return path

    # --- 3. Polygon Classification via Douglas-Peucker ---
    epsilon = 0.045 * diag
    simplified = douglas_peucker(res, epsilon)
    # Exclude redundant closing point if connected to start
    verts = simplified[:-1] if len(simplified) > 1 and math.hypot(simplified[-1].x() - simplified[0].x(), simplified[-1].y() - simplified[0].y()) < 0.15 * diag else simplified

    # Triangle (3 vertices)
    if len(verts) == 3:
        path = QPainterPath()
        path.moveTo(verts[0])
        path.lineTo(verts[1])
        path.lineTo(verts[2])
        path.closeSubpath()
        return path

    # Quad / Rectangle (4 vertices)
    if len(verts) == 4:
        # Check if roughly axis-aligned
        angles = []
        for i in range(4):
            p_a, p_b = verts[i], verts[(i + 1) % 4]
            angle_deg = abs(math.degrees(math.atan2(p_b.y() - p_a.y(), p_b.x() - p_a.x()))) % 90
            angles.append(min(angle_deg, 90 - angle_deg))
        # If all edges are within 12 degrees of cardinal axes, snap to axis-aligned rect
        if max(angles) < 12.0:
            path = QPainterPath()
            path.addRect(bbox)
            return path
        else:
            path = QPainterPath()
            path.moveTo(verts[0])
            for v in verts[1:]:
                path.lineTo(v)
            path.closeSubpath()
            return path

    return None


def replace_last_stroke(canvas, new_path: QPainterPath) -> bool:
    """
    Backwards-compatible helper to swap the active path and rebuild buffer.
    """
    if canvas is not None and hasattr(canvas, 'strokes') and canvas.strokes:
        last_item = canvas.strokes[-1]
        if hasattr(last_item, 'path'):
            last_item.raw_path = last_item.path
            last_item.path = new_path
        elif isinstance(last_item, dict):
            last_item['raw_path'] = last_item.get('path')
            last_item['path'] = new_path
        canvas.rebuild_buffer()
        return True
    return False


def process(stroke_path, canvas=None) -> QPainterPath | None:
    """
    Backwards-compatible wrapper that invokes pure recognize() and updates canvas.
    """
    if hasattr(stroke_path, 'strokes'):
        canvas = stroke_path
        if not canvas.strokes:
            return None
        last_item = canvas.strokes[-1]
        stroke_path = last_item.path if hasattr(last_item, 'path') else (last_item.get('path') if isinstance(last_item, dict) else last_item)

    if stroke_path is None:
        return None

    points = []
    if canvas is not None and hasattr(canvas, 'strokes') and canvas.strokes:
        last_item = canvas.strokes[-1]
        if hasattr(last_item, 'points') and last_item.points:
            points = last_item.points
        elif isinstance(last_item, dict) and 'points' in last_item and last_item['points']:
            points = last_item['points']

    if not points and hasattr(stroke_path, 'elementCount'):
        for i in range(stroke_path.elementCount()):
            el = stroke_path.elementAt(i)
            points.append(QPointF(el.x, el.y))

    new_path = recognize(points)
    if new_path is not None and canvas is not None:
        replace_last_stroke(canvas, new_path)
    return new_path if new_path is not None else stroke_path
