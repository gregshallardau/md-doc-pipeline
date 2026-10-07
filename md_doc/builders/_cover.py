"""Shared physical positioning for cover decorations."""

from typing import Any

from ..config import coerce_bool


def footer_band_geometry(config: dict[str, Any], band_mm: float) -> tuple[float, float] | None:
    """Place an explicitly white footer inside its dark bottom band.

    Returns (bottom gap, footer height) in mm. Ordinary cover footers retain
    their established position above the band.
    """
    color = str(config.get("cover_footer_color", "")).strip().lower()
    if (
        color not in ("white", "#fff", "#ffffff")
        or not coerce_bool(config.get("cover_bar"), True)
        or config.get("cover_bar_position", "top") not in ("both", "bottom")
    ):
        return None
    height = 8 * 1.65 * 25.4 / 72
    if coerce_bool(config.get("cover_footer_line"), True):
        height += 4.35
    if band_mm < height + 2:
        return None
    return (band_mm - height) / 2, height
