# Blockys Launcher

A Minecraft Java Edition launcher for Windows with isolated instances, automatic Java, and Fabric, Quilt, Forge and NeoForge support.

[Download](#download) | [Build from source](#build-from-source) | [Code signing policy](#code-signing-policy) | [Privacy](#privacy)

## About

Blockys is a free Minecraft Java Edition launcher built with Python and Tkinter. It manages isolated game instances with their own mods, resource packs, shaders, worlds, servers, screenshots, logs and settings. It automatically downloads Temurin Java and installs Vanilla, Fabric, Quilt, Forge and NeoForge. Blockys also includes Modrinth integration, offline and Microsoft accounts, skin management, a live console, Quick Play support, and a combined installer for 64-bit and 32-bit Windows.

Blockys does not include or distribute Minecraft. A legitimate Minecraft Java Edition license is required to play online with a premium account.

## Download

Download the latest installer from [GitHub Releases](https://github.com/nadiusk80-oss/blockys-launcher/releases/latest).

The combined installer automatically installs:

- The 64-bit build on 64-bit Windows.
- The 32-bit build on 32-bit Windows.

Release artifacts are built from the source in this repository by GitHub Actions and are signed through SignPath Foundation. Every signing request requires manual approval by a maintainer.

## What's new in 1.0.5

- World backups: back up one world or all worlds, restore them from the Worlds tab, and keep the previous version as a `.old` copy.
- Optional automatic backup before every launch, with a per-world retention limit.
- Each instance can run with its own account while the launcher keeps another one selected.
- Share a game log from the Logs tab: it is uploaded to mclo.gs and the link is copied to the clipboard.
- HTTP proxy support in Settings for downloads, Modrinth, Java and the game itself.
- Automatic updates: Blockys checks GitHub Releases on startup, downloads the new installer, installs it in the background and restarts updated. It can be disabled in Settings.
- The help centre documents backups, log sharing, the proxy and automatic updates.

To verify a signed release on Windows:

```bat
signtool verify /pa /v Blockys-Setup-*.exe
```

## Features

- Isolated instances with separate mods, resource packs, shaders, worlds, servers and settings.
- Vanilla, Fabric, Quilt, Forge and NeoForge support.
- Automatic Temurin Java download and per-instance Java selection.
- Modrinth search and installation for mods, resource packs and shaders.
- Offline accounts and optional Microsoft accounts.
- Per-instance account selection.
- Skin import, preview and upload for Microsoft accounts.
- World management with Quick Play.
- World backups with restoration, retention and automatic backups before launch.
- Server management through `servers.dat`.
- Live console with error and warning highlighting, plus log sharing through mclo.gs.
- HTTP proxy support for downloads and the game.
- Automatic updates from GitHub Releases, with an optional check at startup.
- Instance import and export.
- Combined 64-bit and 32-bit Windows installer.

## Requirements

### Running Blockys

- Windows 10 or Windows 11.
- Internet access on first launch to download Minecraft versions, libraries, loaders and Java.
- A Minecraft Java Edition license for online servers that require a premium account.

### Building Blockys

- Python 3.11 or newer.
- Pillow.
- PyInstaller.
- Inno Setup 6.
- A 32-bit Python installation for the 32-bit build.

## Build from source

Clone the repository:

```bat
git clone https://github.com/nadiusk80-oss/blockys-launcher.git
cd blockys-launcher
```

Create a virtual environment and install dependencies:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Run the launcher from source:

```bat
python run.py
```

Build the 64-bit application:

```bat
python build.py
```

Build the 32-bit application with a 32-bit Python installation:

```bat
python build.py --x86
```

Build the combined installer:

```bat
python build.py --installer
```

The combined build uses the current Python for the 64-bit application and the 32-bit Python found by `build.py` for the 32-bit application. Set `BLOCKYS_PYTHON32` to the full path of a 32-bit `python.exe` if automatic detection fails.

Build output is written to `dist/`:

- `dist/Blockys/Blockys.exe`: 64-bit application.
- `dist/Blockys32/Blockys.exe`: 32-bit application.
- `dist/Blockys-Setup-*.exe`: combined installer.

## Code signing policy

Free code signing provided by [SignPath.io](https://about.signpath.io), certificate by [SignPath Foundation](https://signpath.org).

### Team roles

- Authors and committers: [@nadiusk80-oss](https://github.com/nadiusk80-oss)
- Reviewers: [@nadiusk80-oss](https://github.com/nadiusk80-oss)
- Approvers: [@nadiusk80-oss](https://github.com/nadiusk80-oss)

External contributions are reviewed by the maintainer before merge. Every signing request is approved by a maintainer before the release is signed.

All maintainers use multi-factor authentication for GitHub and SignPath.

### Signing scope

Only artifacts built from this repository by GitHub Actions are submitted for signing. Third-party upstream binaries are not signed under this project's SignPath subscription.

### Release process

1. A release tag is created from the reviewed source.
2. GitHub Actions builds the 64-bit application, the 32-bit application and the combined installer.
3. A maintainer approves the SignPath signing request.
4. The signed artifacts and their SHA-256 checksums are published on GitHub Releases.

## Privacy

Blockys does not collect telemetry or analytics and does not send personal data to the maintainer.

Blockys contacts third-party services only to provide the features requested by the user:

- Mojang and Microsoft services for Minecraft versions, authentication and skins.
- Adoptium for Temurin Java downloads.
- Modrinth for mod and resource pack search and downloads.
- GitHub Releases to check for launcher updates. The check only reads the latest release metadata and the installer checksum.

Microsoft account tokens are stored locally. Blockys does not operate its own account server.

See [PRIVACY.md](PRIVACY.md) for the full privacy policy.

## Data and uninstall

Blockys stores its data in:

```text
%APPDATA%\BloqueLauncher
```

This folder contains accounts, instances, downloaded versions, Java runtimes, skins and logs.

To uninstall Blockys:

1. Open Windows Settings.
2. Go to Apps > Installed apps.
3. Find Blockys and select Uninstall.

The uninstaller removes the application but preserves `%APPDATA%\BloqueLauncher` so user instances and accounts are not lost. Delete that folder manually to remove all Blockys data.

## Contributing

Issues and pull requests are welcome. External pull requests are reviewed before merge. Changes to build scripts, CI configuration and release configuration receive additional review because they affect signed artifacts.

## Security

Report security vulnerabilities through GitHub private vulnerability reporting. Do not open a public issue for a security problem.

## License

Blockys is distributed under the terms of the [LICENSE](LICENSE) file.

## Blockys Mobile (Android)

Blockys Mobile is a separate project for Android: an unofficial fork of
[Amethyst-Android](https://github.com/AngelAuraMC/Amethyst-Android) by AngelAuraMC, which is
itself a fork of [PojavLauncher](https://github.com/PojavLauncherTeam/PojavLauncher) by
PojavLauncherTeam and Boardwalk. It is distributed under the GNU Lesser General Public License
v3.0 (LGPL-3.0).

It bundles Java 8 inside the APK and installs Java 17, 21 or 25 on demand, so recent Minecraft
versions that require Java 25 (26.3 and 26.4-snapshot) run without extra setup. The fork only
changes the app name, icons, logo, accent color and package id (`com.blockys.movil`), and uses
its own build workflow. The modified source, the attribution notices and the list of changes are
published in [nadiusk80-oss/Blockys-Movil](https://github.com/nadiusk80-oss/Blockys-Movil), and
the APK is available in its Releases section (`Blockys-Mobile-2.0.4.apk`).

## Blockys iOS (iPhone and iPad)

Blockys iOS is the iOS counterpart of Blockys Mobile: an unofficial fork of
[Amethyst-iOS](https://github.com/AngelAuraMC/Amethyst-iOS) by AngelAuraMC, which is itself
based on PojavLauncher and Boardwalk. It is distributed under the GNU General Public License
v3.0 (GPL-3.0). The fork changes the app name, icons, logo, interface strings, package id
(`com.blockys.ios`) and uses its own build workflow.

It runs Minecraft: Java Edition on iOS 14 to 18 with the Java 8, 17, 21 and 25 runtimes
included, and supports Forge, Fabric, NeoForge, Quilt and OptiFine profiles. Local (offline)
accounts work like in Blockys Mobile 2.0.4: create one, versions download with it and no
Microsoft account is needed. JIT is required (TrollStore or a JIT enabler such as AltStore,
SideStore or StikDebug), and iOS 26 or later is not supported because Apple removed the JIT
paths the launcher relies on. The IPA is built by GitHub Actions on a macOS runner and
published as `Blockys-iOS-1.0.2.ipa` (unsigned) and `Blockys-iOS-1.0.2-trollstore.tipa` in
[nadiusk80-oss/Blockys-iOS](https://github.com/nadiusk80-oss/Blockys-iOS), together with the
full modified source and the notice file.

## Legal notice

Blockys is not affiliated with Mojang, Microsoft, Modrinth, Prism Launcher, PojavLauncherTeam,
AngelAuraMC or Boardwalk. Minecraft is a trademark of Mojang Studios.
