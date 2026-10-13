"""WCAG 2.x contrast ratios for the design directions' palettes (no dependencies)."""

from __future__ import annotations


def _channel(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def luminance(hex_color: str) -> float:
    """Relative luminance (WCAG 2.2, section 'relative luminance')."""
    r, g, b = (_channel(v / 255) for v in rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(fg: str, bg: str) -> float:
    """Contrast ratio between two opaque colours, 1.0 to 21.0."""
    a, b = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def over(top: str, alpha: float, bottom: str) -> str:
    """`top` at `alpha` opacity composited over `bottom` (e.g. a photo scrim over white)."""
    t, b = rgb(top), rgb(bottom)
    mixed = (round(alpha * x + (1 - alpha) * y) for x, y in zip(t, b))
    return "#" + "".join(f"{v:02X}" for v in mixed)


# Minimums per text role (WCAG 2.2 AA, 1.4.3 and 1.4.11).
MINIMUM = {"body": 4.5, "large": 3.0, "ui": 3.0}
