<div align="center">
  <br>
  <img src="https://raw.githubusercontent.com/FortAwesome/Font-Awesome/6.x/svgs/solid/book-open-reader.svg" width="120" height="120" alt="Mihon Linux Logo">
  
  <h1>📖 Mihon Linux</h1>
  <p><b>A modern, beautiful, and blazing-fast native GTK4 Manga Reader for the Linux Desktop.</b></p>

  <p>
    <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python"></a>
    <a href="https://www.gtk.org/"><img src="https://img.shields.io/badge/GTK-4.0-7EBC6F?style=for-the-badge&logo=gtk&logoColor=white" alt="GTK4"></a>
    <a href="https://gnome.pages.gitlab.gnome.org/libadwaita/help/"><img src="https://img.shields.io/badge/Libadwaita-Modern-blue?style=for-the-badge&logo=gnome&logoColor=white" alt="Libadwaita"></a>
    <a href="#license"><img src="https://img.shields.io/badge/License-GPL_3.0-ff69b4?style=for-the-badge" alt="License"></a>
  </p>

  <p><i>Building the native manga experience Linux users deserve. Inspired by <a href="https://mihon.app">Mihon Android</a>.</i></p>

  ---
</div>

## ✨ The Vision

Linux deserves a first-class reading experience that feels like it belongs. **Mihon Linux** is built from the ground up using **GTK4 and Libadwaita**, ensuring perfect integration with modern desktop environments like GNOME. 

🚀 **No Electron. No Web Wrappers. No Bloat.** Just pure, hardware-accelerated performance and a buttery-smooth UI.

---

## 🚀 Key Features

| Feature | Description |
| :--- | :--- |
| **🎨 Modern Adwaita UI** | A gorgeous, adaptive interface that supports Dark Mode and follows system colors. |
| **🤖 Android APK Bridge** | Native support for Tachiyomi/Mihon APK extensions via an embedded JVM bridge. |
| **🔌 Built-in Sources** | Ships with high-quality Python implementations for **MangaDex** and **AllManga**. |
| **📚 Library & Tracking** | Sophisticated library management with categories, history, and unread tracking. |
| **⚡ Smart Reader** | Asynchronous image loading, background prefetching, and native `GdkPixbuf` scaling. |
| **🔍 Universal Search** | Find your favorite series across all sources with a unified search interface. |

---

## 📸 Screenshots

> [!NOTE]
> *Visual greatness is in progress! Check back soon for the full UI showcase.*

---

## 🛠️ Getting Started

### 1. Prerequisites

You'll need the development headers for GTK4 and Libadwaita. Choose your distro below:

<details>
<summary><b>🐧 Ubuntu / Debian / Pop!_OS</b></summary>

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-gi python3-requests \
    gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-pango-1.0 openjdk-21-jdk
```
</details>

<details>
<summary><b>🎩 Fedora</b></summary>

```bash
sudo dnf install python3 python3-pip python3-gobject python3-requests \
    gtk4 libadwaita java-21-openjdk
```
</details>

<details>
<summary><b>🏹 Arch Linux / Manjaro</b></summary>

```bash
sudo pacman -S python python-pip python-gobject python-requests \
    gtk4 libadwaita jdk21-openjdk
```
</details>

### 2. Installation

```bash
# Clone the repository
git clone https://github.com/nabhya8013/mihon-linux.git
cd mihon-linux

# Install Python requirements
pip install -r requirements.txt

# (Optional) Build the JVM Bridge for APK support
cd bridge && ./gradlew jar && cd ..

# Launch the app!
./mihon.sh
```

---

## 🏗️ Architecture

Mihon Linux is designed for modularity and performance:

```text
mihon/
├── 🎨 ui/          # GTK4/Adwaita layouts and custom widgets
├── 🧠 core/        # SQLite DB, Image Downloader, and Data Models
├── 🔌 extensions/  # Source scrapers & JVM Bridge Proxy
└── 🛠️ assets/      # Icons and CSS styles
```

---

## 🤝 Community & Support

Love manga? Love Linux? Join us! 
- **Found a bug?** Open an [issue](https://github.com/nabhya8013/mihon-linux/issues).
- **Want to contribute?** We love Pull Requests! New extensions, UI tweaks, or performance fixes are all welcome.
- **Stay updated:** Star the repo to see our progress!

---

## ⚖️ License & Disclaimer

*This project is an independent open-source application and is not directly affiliated with the original Android Mihon/Tachiyomi team. All manga content is provided by the respective extension sources; this app does not host any content.*

**Mihon Linux is shared under the GPL-3.0 License.**