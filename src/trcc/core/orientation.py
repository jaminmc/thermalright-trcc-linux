"""Display orientation geometry — pure functions, no I/O.

C# equivalents:
    effective_resolution → directionB + is{W}x{H} flags → GetFileListMBDir()
    image_rotation       → directionB → RotateImg() dispatch in ImageToJpg
"""
from __future__ import annotations


def effective_resolution(w: int, h: int, rotation: int) -> tuple[int, int]:
    """Canvas resolution after rotation — swaps w,h for non-square at 90/270.

    This is about the physical device shape, not directory existence.
    Square displays are unaffected. Non-square always swap.
    """
    if w != h and rotation in (90, 270):
        return (h, w)
    return (w, h)


def image_rotation(w: int, h: int, rotation: int) -> int:
    """Rotation angle to apply to images.

    Non-square at 90/270: canvas is already portrait (effective_resolution
    swapped dims), so no image rotation needed — return 0.
    Square or 0/180: return actual rotation angle.
    """
    if w != h and rotation in (90, 270):
        return 0
    return rotation
