"""
Optional WebKit-based anti-bot challenge solver.

The HTTP layer calls into this solver after a 403/503. The solver must run UI
work on the GTK main loop and return cookies to the blocked worker thread.
"""
from __future__ import annotations

from http.cookies import SimpleCookie
import threading
from typing import Optional

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from ..core.http_client import ChallengeRequest, ChallengeSolution
import logging

logger = logging.getLogger("challenge_solver")


def _load_webkit():
    try:
        gi.require_version("WebKit", "6.0")
        from gi.repository import WebKit

        return WebKit
    except (ImportError, ValueError):
        return None


WEBKIT = _load_webkit()


def _parse_cookie_string(cookie_string: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    if not cookie_string:
        return cookies
    for part in cookie_string.split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        if name:
            cookies[name] = value.strip()
    return cookies


def _parse_set_cookie_header(header_value: str) -> dict[str, str]:
    parsed = SimpleCookie()
    parsed.load(header_value or "")
    return {name: morsel.value for name, morsel in parsed.items()}


class WebKitCookieSolver:
    def __init__(self, parent: Gtk.Window):
        self._parent = parent

    @property
    def available(self) -> bool:
        return WEBKIT is not None

    def solve(self, request: ChallengeRequest) -> Optional[ChallengeSolution]:
        if WEBKIT is None:
            logger.warning("WebKitGTK 6.0 is not available")
            return None
        if threading.current_thread() is threading.main_thread():
            logger.warning("cannot block the GTK main thread for challenge solving")
            return None

        done = threading.Event()
        result: dict[str, Optional[ChallengeSolution]] = {"solution": None}

        def present_solver():
            self._present_solver_window(request, done, result)
            return False

        GLib.idle_add(present_solver)
        done.wait()
        return result["solution"]

    def _present_solver_window(self, request, done, result):
        win = Adw.Window(transient_for=self._parent, modal=True)
        win.set_title("Solve Site Challenge")
        win.set_default_size(960, 720)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label="Solve Site Challenge"))
        box.append(header)

        status = Gtk.Label(
            label="Complete the browser challenge, then choose Use Cookies."
        )
        status.set_margin_start(12)
        status.set_margin_end(12)
        status.set_margin_top(8)
        status.set_margin_bottom(8)
        status.set_wrap(True)
        status.add_css_class("dim-label")
        box.append(status)

        webview = WEBKIT.WebView()
        webview.set_vexpand(True)
        webview.set_hexpand(True)
        webview.load_uri(request.url)
        box.append(webview)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.set_halign(Gtk.Align.END)
        actions.set_margin_start(12)
        actions.set_margin_end(12)
        actions.set_margin_top(8)
        actions.set_margin_bottom(8)

        cancel_btn = Gtk.Button(label="Cancel")
        use_btn = Gtk.Button(label="Use Cookies")
        use_btn.add_css_class("suggested-action")
        actions.append(cancel_btn)
        actions.append(use_btn)
        box.append(actions)

        def finish(solution=None, close_window=True):
            if done.is_set():
                return
            result["solution"] = solution
            done.set()
            if close_window:
                win.close()

        cancel_btn.connect("clicked", lambda *_: finish(None))
        win.connect("close-request", lambda *_: (finish(None, False), False)[1])
        use_btn.connect(
            "clicked",
            lambda *_: self._collect_solution(webview, status, finish),
        )

        win.set_content(box)
        win.present()

    def _collect_solution(self, webview, status, finish):
        user_agent = self._get_user_agent(webview)

        def done_with_cookie_string(cookie_string: str):
            cookies = _parse_cookie_string(cookie_string)
            if not cookies:
                status.set_label("No cookies were found yet. Finish the challenge first.")
                return
            finish(ChallengeSolution(cookies=cookies, user_agent=user_agent))

        if hasattr(webview, "evaluate_javascript"):
            webview.evaluate_javascript(
                "document.cookie",
                -1,
                None,
                None,
                None,
                self._on_javascript_cookie_result,
                done_with_cookie_string,
            )
        elif hasattr(webview, "run_javascript"):
            webview.run_javascript(
                "document.cookie",
                None,
                self._on_javascript_cookie_result,
                done_with_cookie_string,
            )
        else:
            status.set_label("This WebKitGTK build cannot extract browser cookies.")

    @staticmethod
    def _get_user_agent(webview) -> Optional[str]:
        try:
            settings = webview.get_settings()
            return settings.get_user_agent()
        except Exception:
            return None

    @staticmethod
    def _on_javascript_cookie_result(webview, result, callback):
        cookie_string = ""
        try:
            if hasattr(webview, "evaluate_javascript_finish"):
                js_value = webview.evaluate_javascript_finish(result)
            else:
                js_value = webview.run_javascript_finish(result)
            if hasattr(js_value, "to_string"):
                cookie_string = js_value.to_string()
            elif hasattr(js_value, "get_js_value"):
                cookie_string = js_value.get_js_value().to_string()
        except Exception as exc:
            logger.error("cookie extraction failed: %s", exc)
        callback(cookie_string or "")
