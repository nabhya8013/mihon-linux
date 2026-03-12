"""
Mihon Linux - GTK4 manga reader application.
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GLib
import sys
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
        # Load CSS
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        display = self.get_style_manager().get_display() if hasattr(self.get_style_manager(), 'get_display') else None
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
        else:
            # Fallback: apply on first window show
            pass

    def _on_activate(self, app):
        # Apply CSS to default display
        display = self.get_windows()[0].get_display() if self.get_windows() else None
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)

        win = MainWindow(app=self)
        # Apply CSS now that we have a display
        Gtk.StyleContext.add_provider_for_display(
            win.get_display(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        win.present()

        # Set dark style preference by default
        style_mgr = Adw.StyleManager.get_default()
        style_mgr.set_color_scheme(Adw.ColorScheme.PREFER_DARK)


def main():
    app = MihonApp()
    return app.run(sys.argv)
