"""
Mihon Linux - GTK4 manga reader application.
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, Gdk
import sys
import os
from .ui.main_window import MainWindow
from .ui.styles import CSS


class MihonApp(Adw.Application):

    def __init__(self):
        super().__init__(
            application_id="io.github.mihon.linux",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.connect("activate", self._on_activate)
        self.connect("startup", self._on_startup)

    def _on_startup(self, app):
        # Load CSS only when a display exists.
        display = Gdk.Display.get_default()
        if display is None:
            return

        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _on_activate(self, app):
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
            print(f"[mihon] Failed to initialize GTK window: {e}", file=sys.stderr)
            self.quit()
            return

        # Set dark style preference by default
        style_mgr = Adw.StyleManager.get_default()
        style_mgr.set_color_scheme(Adw.ColorScheme.PREFER_DARK)


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
