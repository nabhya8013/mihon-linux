"""
CSS styles for Mihon Linux.
"""

CSS = """
/* ── Base ─────────────────────────────────────────────────────────────── */

window {
    background-color: @window_bg_color;
}

/* ── Sidebar ──────────────────────────────────────────────────────────── */

.sidebar {
    background-color: @sidebar_bg_color;
    min-width: 200px;
}

.navigation-sidebar row {
    border-radius: 8px;
    margin: 2px 8px;
}

.navigation-sidebar row:selected {
    background-color: alpha(@accent_color, 0.15);
    color: @accent_color;
}

.navigation-sidebar row:selected image {
    color: @accent_color;
}

/* ── Manga card ───────────────────────────────────────────────────────── */

.manga-card {
    border-radius: 8px;
    background-color: @card_bg_color;
    transition: all 200ms ease;
}

.manga-card-hover {
    background-color: alpha(@accent_color, 0.08);
    transform: translateY(-2px);
}

.manga-cover {
    border-radius: 8px 8px 0 0;
}

.manga-cover-placeholder {
    border-radius: 8px 8px 0 0;
    background-color: @headerbar_bg_color;
    min-height: 220px;
}

.manga-card-title {
    font-size: 12px;
    color: @window_fg_color;
}

/* Unread badge */
.unread-badge {
    background-color: @accent_bg_color;
    color: @accent_fg_color;
    border-radius: 12px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: bold;
    min-width: 20px;
}

/* ── Tags / Chips ─────────────────────────────────────────────────────── */

.tag {
    background-color: alpha(@accent_color, 0.15);
    color: @accent_color;
    border-radius: 12px;
    padding: 2px 10px;
}

/* ── Reader ───────────────────────────────────────────────────────────── */

.reader-bg {
    background-color: #000000;
}

.reader-header {
    background-color: alpha(#1a1a1a, 0.92);
    color: white;
}

.reader-bottom-bar {
    background-color: alpha(#1a1a1a, 0.92);
    color: white;
    padding: 4px 16px;
}

.reader-page {
    background-color: transparent;
}

.reader-spinner {
    color: white;
}

/* ── Loading / Empty states ───────────────────────────────────────────── */

.dim-label {
    opacity: 0.55;
}

/* ── Boxed list tweaks ────────────────────────────────────────────────── */

.boxed-list {
    border-radius: 12px;
}

/* ── Header bars ──────────────────────────────────────────────────────── */

headerbar {
    background-color: @headerbar_bg_color;
}
"""
