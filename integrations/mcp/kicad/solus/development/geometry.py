"""Exact quarter-turn projection from symbol-local to sheet coordinates."""

from solus.development.library import LibraryPin
from solus.development.models import DevelopmentError, Point


def project_pin(pin: LibraryPin, at: Point, rotation_deg: int) -> Point:
    if isinstance(rotation_deg, bool) or rotation_deg not in (0, 90, 180, 270):
        raise DevelopmentError("invalid_geometry")
    # Rotate in the symbol's Cartesian system, then invert Y for the sheet.
    x, y = pin.x_mm, pin.y_mm
    for _ in range(rotation_deg // 90):
        x, y = -y, x
    result = Point(round(at.x_mm + x, 10), round(at.y_mm - y, 10))
    if not 0 <= result.x_mm <= 1000 or not 0 <= result.y_mm <= 1000:
        raise DevelopmentError("invalid_geometry")
    return result


def on_segment(point: Point, start: Point, end: Point) -> bool:
    return (
        start.x_mm == end.x_mm == point.x_mm
        and min(start.y_mm, end.y_mm) <= point.y_mm <= max(start.y_mm, end.y_mm)
    ) or (
        start.y_mm == end.y_mm == point.y_mm
        and min(start.x_mm, end.x_mm) <= point.x_mm <= max(start.x_mm, end.x_mm)
    )
