# Library Controls Spec (Epic 2 - Initial Freeze)

This is the initial behavior contract for advanced library controls.

## Sort Options

- `title` (default): ascending by title
- `unread_count`: descending by default on first select
- `recently_added`: descending by default on first select
- `last_read`: descending by default on first select

User can force ascending/descending for any sort option.

## Display Modes

- `grid` (default)
- `list`

Display mode is persisted per category.

## Filters

- Reading status multi-select:
  - `reading`
  - `completed`
  - `on_hold`
  - `dropped`
  - `plan_to_read`
- `unread_only` (boolean)
- `downloaded_only` (boolean)

Search is text-based (title + author) and combines with all active filters.

## Persistence

- Global key:
  - `library_prefs_global`
- Per-category key:
  - `library_prefs_category_<category_id>`

Preference schema:

```json
{
  "sort_by": "title",
  "sort_desc": false,
  "display_mode": "grid",
  "status_filters": [],
  "unread_only": false,
  "downloaded_only": false
}
```

## Batch Actions

- Mark all chapters as read for currently filtered manga
- Remove currently filtered manga from library

## Non-goals (This Slice)

- Drag-drop category management
- Custom filter presets
- True multi-select with undo stack
