<div align="center">
  <img src="https://raw.githubusercontent.com/FortAwesome/Font-Awesome/6.x/svgs/solid/book-open-reader.svg" width="100" height="100" alt="Mihon Linux Logo">
  <h1>📖 Mihon Linux</h1>
  <p><b>A beautiful, native GTK4 Manga Reader for Linux desktops.</b></p>
  
  [![Python](https://img.shields.io/badge/Python-3.10+-blue.svg?logo=python&logoColor=white)](https://www.python.org)
  [![GTK4](https://img.shields.io/badge/GTK-4.0-green.svg?logo=gtk&logoColor=white)](https://www.gtk.org/)
  [![License](https://img.shields.io/badge/License-Open%20Source-ff69b4.svg)](#license)
  
  <p><i>Inspired by the legendary Android app Mihon (formerly Tachiyomi).</i></p>
</div>

<hr>

## ✨ Why Mihon Linux?

Linux deserves a native, hardware-accelerated, and beautiful manga reading experience. Mihon Linux utilizes **GTK4 and libadwaita** to deliver a seamless UI that perfectly integrates with modern Linux desktop environments (like GNOME). 

No Electron bloat. No web wrappers. Just pure, native Python and GTK.

## 🚀 Features

- **🎨 Modern Adwaita UI:** Gorgeous, adaptive design perfectly matched for Linux.
- **🔌 Extensible Sources:** Read from multiple sources. Ships with built-in extensions for **MangaDex** and **AllManga**.
- **🤖 Android APK Support:** Native support for Tachiyomi APK extensions via an embedded JVM bridge.
- **📚 Personal Library:** Save your favorite manga, organize them with categories, and effortlessly track your reading status.
- **🔍 Seamless Discovery:** Browse popular manga, check latest updates, or search directly from the UI.
- **⚡ Blazing Fast Reader:** Asynchronous image loading and background caching ensure your reading experience is buttery smooth without blocking the UI.
- **🖼️ Smart Image Handling:** Images are processed directly into native `GdkPixbuf` data.

---

## 📸 Screenshots

*(Awesome screenshots coming soon...)*

---

## 🛠️ Installation

Because Mihon Linux is built natively, you'll need the GTK4 and libadwaita development libraries. Don't worry, they're super easy to get on modern Linux!

### 1. Install System Dependencies

**Ubuntu / Debian / Pop!_OS:**
```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-gi python3-requests \
    gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-pango-1.0 openjdk-21-jdk
```

**Fedora:**
```bash
sudo dnf install python3 python3-pip python3-gobject python3-requests \
    gtk4 libadwaita java-21-openjdk
```

**Arch Linux / Manjaro:**
```bash
sudo pacman -S python python-pip python-gobject python-requests \
    gtk4 libadwaita jdk21-openjdk
```

### 2. Clone & Run

```bash
# Clone the repository
git clone https://github.com/nabhya8013/mihon-linux.git
cd mihon-linux

# Install Python packages
pip install -r requirements.txt

# (Optional) Build the JVM Bridge for Android extensions
# Skip this if you only use built-in MangaDex/AllManga
cd bridge && ./gradlew jar && cd ..

# Launch the app!
./mihon.sh
```
*(You can also run it directly using `python3 run.py`)*

---

## 🏗️ Architecture Under the Hood

Curious how it works? 
- **`mihon/ui/`**: All the shiny GTK4/Adwaita interfaces and custom widgets (`FlowBox`, `Gtk.Stack`, gestures).
- **`mihon/core/`**: The backbone of the app — an asynchronous image downloader, SQLite database management, and robust data models.
- **`mihon/extensions/`**: Pluggable modules fetching data from Manga APIs using REST/GraphQL.

---

## 🤝 Contributing

Love manga? Love Linux? Pull requests are absolutely welcome! Whether it's adding a new extension, fixing a UI bug, or improving the image caching—feel free to fork and contribute.

## ⚖️ Disclaimer

*This project is an independent open-source application and is not directly affiliated with the original Android Mihon/Tachiyomi team. All manga content is provided by the respective extension sources; this app does not host any content.*