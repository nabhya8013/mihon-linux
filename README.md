# Mihon Linux

A native Linux manga reader built with Python, GTK4, and libadwaita. Inspired by the popular Android app Mihon (formerly Tachiyomi), this application provides a clean, modern interface for browsing and reading manga from various online sources directly on your Linux desktop.

## Features

- **Modern UI**: Built with GTK4 and libadwaita for a seamless, native Linux experience.
- **Extensions**: Support for multiple manga providers via an extension system.
  - Currently includes built-in support for **MangaDex** and **AllManga**.
- **Browse & Search**: Discover new manga, view popular/latest updates, and search across extensions.
- **Library**: Track your favorite manga, organize by category, and track reading status.
- **Reader**: A built-in image viewer that loads and caches pages for smooth reading.
- **Asynchronous Loading**: Fast, non-blocking UI using background threads and caching for manga covers and chapter pages.

## Screenshots

*(Coming soon...)*

## Prerequisites

To run Mihon Linux, your system needs the GTK4 and libadwaita development libraries, along with several Python dependencies. You can install these using your distribution's package manager.

**For Debian/Ubuntu-based systems:**
```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-gi python3-requests \
    gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-pango-1.0
```

**For Fedora:**
```bash
sudo dnf install python3 python3-pip python3-gobject python3-requests \
    gtk4 libadwaita
```

**For Arch Linux:**
```bash
sudo pacman -S python python-pip python-gobject python-requests \
    gtk4 libadwaita
```

## Installation

1. Clone the repository:
```bash
git clone https://github.com/nabhya8013/mihon-linux.git
cd mihon-linux
```

2. (Optional) Install Python dependencies using pip:
```bash
pip install -r requirements.txt
```
*(Note: System packages for `python3-gi` and `python3-requests` are usually preferred on Linux to integrate smoothly with the system's GTK libraries.)*

## Usage

Simply run the application using the included runner script:

```bash
./mihon.sh
```

Alternatively, you can run the python script directly:

```bash
python3 run.py
```

## Folder Structure

- `mihon/`: Core application package
  - `core/`: Database (SQLite), image caching, models, and shared logic
  - `extensions/`: Manga provider modules (MangaDex, AllManga, etc.)
  - `ui/`: GTK4/Adwaita view classes and custom widgets
- `mihon.sh`: Convenience launcher script
- `run.py`: Application entry point

## License

This project is open source. All rights are reserved to the respective content providers linked in the extensions.