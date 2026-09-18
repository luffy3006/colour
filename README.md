# PyQt6 Minimalist Whiteboard

A high-performance, minimalist whiteboard and scratchpad built with PyQt6, designed for fast drawing, note-taking, math, and competitive programming scratch work.

## Features

- **Quad-Bezier Smoothing**: Real-time quadratic Bezier curve interpolation (`quadTo`) between incoming mouse coordinates for smooth, anti-aliased freehand strokes.
- **Offscreen Pixmap Buffer**: A 3000x3000 offscreen `QPixmap` buffer (`self.buffer`) that avoids $O(N)$ redraw latency by baking finished strokes into the buffer.
- **Canvas Navigation**: Mouse-wheel vertical panning for seamless navigation across the 3000x3000 canvas in compact windows.
- **On-Canvas Text Typing**: Double-click anywhere to summon a frameless text input matching the current pen width and color. Press <kbd>Enter</kbd> to render text directly onto the canvas.
- **Dark Mode**: Toggle between light (`#FFFFFF`) and dark (`#121212`) background with shortcut <kbd>D</kbd>, with automatic black/white stroke color inversion.
- **Shape Recognition & Autocorrect**:
  - **Lines**: Snaps to straight lines when end-to-end distance is $\ge 90\%$ of stroke length.
  - **Circles/Ellipses**: Snaps to smooth ellipses when aspect ratio is $\approx 1:1$ and end points are close.
  - **Rectangles**: Snaps to clean rectangles when end points are close and stroke encloses the bounding box.
- **Floating Palette**: Draggable and collapsible toolbar for color selection, pen thickness adjustment, and canvas clearing.

## Keyboard Shortcuts

| Shortcut | Action |
| --- | --- |
| <kbd>D</kbd> | Toggle Dark Mode |
| <kbd>C</kbd> | Clear Canvas |
| <kbd>[</kbd> / <kbd>]</kbd> | Decrease / Increase Pen Thickness |
| <kbd>1</kbd> / <kbd>2</kbd> / <kbd>3</kbd> | Quick Pen Colors (Black, Red, Blue) |
| <kbd>Ctrl</kbd> + <kbd>Z</kbd> | Undo Last Stroke |
| <kbd>Double Click</kbd> | Open Frameless Text Input |
| <kbd>Enter</kbd> | Commit Text to Canvas |
| <kbd>Esc</kbd> | Cancel Text Input |

## Installation & Running

```bash
pip install -r requirements.txt
python3 main.py
```
