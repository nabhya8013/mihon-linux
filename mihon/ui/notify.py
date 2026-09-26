"""
User-facing notifications.

Errors used to end at a ``print()`` in a terminal the user never sees. This
module routes them to an ``Adw.Toast`` on the main window instead, and logs
them at the same time so a terminal run still has the detail.

Any widget can call :func:`notify`; it walks up to the toplevel to find the
window's toast overlay. When there is no overlay — a widget not yet added to
a window, or a unit test — the message is logged and dropped rather than
raising.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

logger = logging.getLogger("notify")

# An error stays up longer than a confirmation: the user has to read it, and
# may want to hit the retry button.
INFO_TIMEOUT = 3
ERROR_TIMEOUT = 8


def find_toast_overlay(widget) -> Optional[Adw.ToastOverlay]:
    """The nearest toast overlay above ``widget``, or None."""
    if widget is None:
        return None

    root = widget.get_root() if hasattr(widget, "get_root") else None
    overlay = getattr(root, "toast_overlay", None)
    if isinstance(overlay, Adw.ToastOverlay):
        return overlay

    # Fall back to walking the parent chain, so a widget inside a dialog that
    # carries its own overlay still works.
    node = widget
    while node is not None:
        if isinstance(node, Adw.ToastOverlay):
            return node
        node = node.get_parent() if hasattr(node, "get_parent") else None
    return None


def notify(
    widget,
    message: str,
    *,
    is_error: bool = False,
    action_label: str = "",
    on_action: Optional[Callable] = None,
    timeout: Optional[int] = None,
) -> bool:
    """
    Show ``message`` as a toast on the window containing ``widget``.

    Pass ``action_label`` and ``on_action`` to attach a button — a Retry on a
    failed network call, for instance. Returns whether a toast was shown.
    """
    if not message:
        return False

    if is_error:
        logger.error(message)
    else:
        logger.info(message)

    overlay = find_toast_overlay(widget)
    if overlay is None:
        return False

    toast = Adw.Toast.new(message)
    toast.set_timeout(timeout if timeout is not None else (ERROR_TIMEOUT if is_error else INFO_TIMEOUT))
    toast.set_priority(Adw.ToastPriority.HIGH if is_error else Adw.ToastPriority.NORMAL)

    if action_label and on_action is not None:
        toast.set_button_label(action_label)
        # Adw.Toast has no user-data on "button-clicked", so bind it here.
        toast.connect("button-clicked", lambda _toast: on_action())

    overlay.add_toast(toast)
    return True


def notify_error(widget, message: str, **kwargs) -> bool:
    """Shorthand for an error toast."""
    return notify(widget, message, is_error=True, **kwargs)


def notify_retry(widget, message: str, on_retry: Callable) -> bool:
    """An error toast with a Retry button."""
    return notify_error(widget, message, action_label="Retry", on_action=on_retry)


__all__ = [
    "ERROR_TIMEOUT",
    "INFO_TIMEOUT",
    "find_toast_overlay",
    "notify",
    "notify_error",
    "notify_retry",
]
