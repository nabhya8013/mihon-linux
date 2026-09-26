"""
Mihon Linux - GTK4 manga reader application.
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, Gdk
import sys
import os
import threading
import logging
from .core.logging_setup import configure_logging
from .ui.main_window import MainWindow
from .ui.styles import CSS
from .ui.theme import apply_appearance_theme

logger = logging.getLogger("app")

# Must match data/<APP_ID>.desktop, its metainfo file, and the installed icon
# name, or the shell cannot tie a running window to its launcher entry.
APP_ID = "io.github.nabhya8013.MihonLinux"


class MihonApp(Adw.Application):

    def __init__(self):
        super().__init__(
            # Reverse-DNS id under this repository's own namespace. The old
            # "io.github.mihon.linux" claimed the upstream Mihon org, which a
            # software centre would misattribute and Flathub would reject.
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.connect("activate", self._on_activate)
        self.connect("startup", self._on_startup)

    def _on_startup(self, app):
        configure_logging()

        # Load CSS only when a display exists.
        display = Gdk.Display.get_default()
        if display is None:
            return

        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # Keep the on-disk page cache inside its size limit. Pages accumulate
        # every time a chapter is read and nothing else removes them.
        try:
            from .core import disk_cache
            disk_cache.ensure_dirs()
            threading.Thread(target=disk_cache.prune, daemon=True).start()
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("Could not prune the page cache: %s", exc)

        # Deliver tracker updates that failed while the app was last running.
        # A sync fires exactly when the network is least reliable, so the queue
        # is normally non-empty after an offline session.
        try:
            from .core.tracking import get_track_manager
            threading.Thread(
                target=lambda: get_track_manager().process_queue(), daemon=True
            ).start()
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("Could not drain the tracking queue: %s", exc)

        # Start the JVM ↔ Python challenge handshake watcher so that
        # Cloudflare blocks raised inside bridge OkHttp requests can
        # be solved by the same WebKit UI used for Python requests.
        try:
            from .core.challenge_bridge import start_challenge_bridge
            start_challenge_bridge()
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("Could not start challenge bridge: %s", exc)

    def _on_activate(self, app):
        # Lets the shell match the window to the installed .desktop entry and
        # draw the right icon.
        Gtk.Window.set_default_icon_name(APP_ID)
        apply_appearance_theme()
        try:
            win = MainWindow(app=self)
            provider = Gtk.CssProvider()
            provider.load_from_string(CSS)
            Gtk.StyleContext.add_provider_for_display(
                win.get_display(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
            win.present()
        except RuntimeError as e:
            # Avoid hard traceback spam when started without a GUI session.
            logger.error("Failed to initialize GTK window: %s", e)
            self.quit()
            return


def main():
    # Fail fast and cleanly when launched without a graphical display.
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        print(
            "[mihon] No display server found. Run inside a desktop session "
            "with DISPLAY/WAYLAND_DISPLAY set.",
            file=sys.stderr,
        )
        return 1

    init_ok = Gtk.init_check()
    if isinstance(init_ok, tuple):
        init_ok = init_ok[0]
    if not init_ok or Gdk.Display.get_default() is None:
        print(
            "[mihon] GTK could not initialize. Run inside a desktop session "
            "with DISPLAY/WAYLAND_DISPLAY set.",
            file=sys.stderr,
        )
        return 1

    app = MihonApp()
    return app.run(sys.argv)
