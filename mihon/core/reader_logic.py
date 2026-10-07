"""
Reader decisions that do not need GTK: tap zones, page sizing, chapter
order, and which webtoon strip is on screen.

Kept apart from ``mihon.ui.reader`` so the rules can be tested without a
display, the same way ``page_cache`` holds the prefetch rules.
"""
from __future__ import annotations

import bisect
from typing import List, Optional, Sequence, Tuple

ZOOM_MIN = 0.3
ZOOM_MAX = 3.0

# Height-to-width ratio assumed for a webtoon strip that has not loaded yet.
# Only a placeholder: the real ratio replaces it once the image decodes.
DEFAULT_STRIP_RATIO = 1.5


def clamp_zoom(zoom: float) -> float:
    return max(ZOOM_MIN, min(ZOOM_MAX, zoom))


def tap_action(x_fraction: float, rtl: bool, invert: bool = False) -> str:
    """
    Map a click's horizontal position to "prev", "next" or "menu".

    The screen splits into thirds. The middle toggles the menu. The outer
    thirds turn pages, the left one going forward when reading right to left,
    as on Android; ``invert`` swaps the two.
    """
    if x_fraction < 1 / 3:
        side = "left"
    elif x_fraction > 2 / 3:
        side = "right"
    else:
        return "menu"
    forward_side = "left" if rtl else "right"
    if invert:
        forward_side = "right" if forward_side == "left" else "left"
    return "next" if side == forward_side else "prev"


def fit_sizes(
    images: Sequence[Tuple[int, int]],
    view_w: int,
    view_h: int,
    scale_type: str = "fit_page",
    zoom: float = 1.0,
    spacing: int = 0,
) -> List[Tuple[int, int]]:
    """
    Display size for one page, or for pages shown side by side.

    Pages in a row share one height, so a spread lines up. ``fit_page`` makes
    the whole row fit the viewport; ``fit_width`` makes it as wide as the
    viewport and lets it run past the bottom, where the scrolled window takes
    over. ``zoom`` scales the result. Aspect ratios are always kept, so the
    picture can be drawn with ContentFit.FILL without distortion.
    """
    valid = [(w, h) for w, h in images if w > 0 and h > 0]
    if not valid or view_w <= 0 or view_h <= 0:
        return [(0, 0) for _ in images]

    # Widths each page would have at a common height of 1.
    unit_widths = [w / h for w, h in valid]
    row_unit_width = sum(unit_widths)
    gaps = spacing * (len(valid) - 1)
    usable_w = max(view_w - gaps, 1)

    height_for_width = usable_w / row_unit_width
    if scale_type == "fit_width":
        row_h = height_for_width
    else:
        row_h = min(view_h, height_for_width)
    row_h *= clamp_zoom(zoom)

    sizes = iter((max(1, round(u * row_h)), max(1, round(row_h))) for u in unit_widths)
    return [next(sizes) if w > 0 and h > 0 else (0, 0) for w, h in images]


def strip_height(img_w: int, img_h: int, width: int) -> int:
    """Height of a webtoon strip drawn ``width`` pixels wide."""
    if width <= 0:
        return 0
    if img_w <= 0 or img_h <= 0:
        return max(1, round(width * DEFAULT_STRIP_RATIO))
    return max(1, round(width * img_h / img_w))


def page_at_offset(tops: Sequence[float], offset: float) -> int:
    """
    Index of the strip under ``offset`` in a vertical stack.

    ``tops`` holds each strip's top edge in ascending order, starting at 0.
    """
    if not tops:
        return 0
    return max(0, bisect.bisect_right(tops, offset) - 1)


def window_range(index: int, total: int, behind: int, ahead: int) -> range:
    """Indices to keep loaded around ``index``."""
    if total <= 0:
        return range(0)
    index = max(0, min(index, total - 1))
    return range(max(0, index - behind), min(total, index + ahead + 1))


def reading_order(chapters: Sequence) -> list:
    """
    Chapters oldest first, the order a reader moves through them.

    Sources list chapters newest first and ``source_order`` records that
    position, so a higher number is older. That is the only ordering that
    works for chapters without a number. When a source never set it (every
    value equal), fall back to the chapter number, with unnumbered chapters
    kept in the order they were stored.
    """
    chapters = list(chapters)
    orders = {getattr(c, "source_order", 0) for c in chapters}
    if len(orders) > 1:
        return sorted(
            chapters,
            key=lambda c: (-getattr(c, "source_order", 0), c.chapter_number),
        )

    def by_number(c):
        number = c.chapter_number
        unnumbered = number is None or number < 0
        return (unnumbered, number if not unnumbered else 0, c.id or 0)

    return sorted(chapters, key=by_number)


def adjacent_chapter(chapters: Sequence, current, step: int) -> Optional[object]:
    """
    The chapter ``step`` places after ``current`` in reading order (-1 = previous).

    ``current`` is found by id. A chapter missing from the list, which should
    not happen, falls back to the nearest chapter number in that direction.
    """
    ordered = reading_order(chapters)
    for i, chapter in enumerate(ordered):
        if current.id is not None and chapter.id == current.id:
            target = i + step
            return ordered[target] if 0 <= target < len(ordered) else None

    number = current.chapter_number
    if step > 0:
        later = [c for c in ordered if c.chapter_number > number]
        return later[0] if later else None
    earlier = [c for c in ordered if 0 <= c.chapter_number < number]
    return earlier[-1] if earlier else None


__all__ = [
    "DEFAULT_STRIP_RATIO",
    "ZOOM_MAX",
    "ZOOM_MIN",
    "adjacent_chapter",
    "clamp_zoom",
    "fit_sizes",
    "page_at_offset",
    "reading_order",
    "strip_height",
    "tap_action",
    "window_range",
]
