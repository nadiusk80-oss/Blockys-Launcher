# Privacy Policy

Blockys is a desktop launcher for Minecraft: Java Edition. It runs entirely on
the user's computer. The launcher does not contain telemetry, analytics, crash
reporting, advertising, or a Blockys-operated user account system, and it does
not send personal data to the developer or to any Blockys server.

## Data stored on your computer

All persistent data is stored locally under `%APPDATA%\BloqueLauncher`:

| Path | Content |
| --- | --- |
| `settings.json` | Launcher settings, including the optional Microsoft Client ID and Java preferences |
| `profiles.json` | Offline profiles and, for Microsoft accounts, access and refresh tokens |
| `instances.json` | Instances and their configuration |
| `instances\` | Game folders: mods, resource packs, shader packs, worlds, screenshots and logs |
| `data\` | Downloaded Minecraft versions, libraries, assets and Temurin Java runtimes |
| `skins\` | Imported skin files |
| `logs\` | Launcher and Forge/NeoForge installer logs |
| `cache\` | Temporary download files |

Nothing from these folders is uploaded to the developer. Removing an account in
the **Cuentas** window deletes its profile and imported skin.

## Microsoft account (optional)

Signing in with a Microsoft account is optional and only available if you
configure your own Azure application Client ID in the launcher settings. The
login runs directly between your computer and Microsoft; the launcher never
sends your credentials to the developer.

Tokens are stored in plain text inside `profiles.json` so the launcher can
renew the session without asking you to log in again. They are sent only to
Microsoft, Xbox Live and Mojang services to authenticate you and, when you press
**Subir**, to upload a skin to your Mojang profile. Deleting the account in the
launcher removes the stored tokens.

## Network connections

The launcher contacts the following services only to download game files,
install loaders, browse Modrinth, verify accounts and manage skins:

| Service | Purpose |
| --- | --- |
| `piston-meta.mojang.com`, `resources.download.minecraft.net`, `libraries.minecraft.net` and download hosts listed in Mojang manifests | Minecraft version catalog, libraries, assets and game files |
| `api.minecraftservices.com` | Microsoft login, Minecraft profile and skin upload |
| `login.microsoftonline.com`, `user.auth.xboxlive.com`, `xsts.auth.xboxlive.com` | Microsoft and Xbox Live authentication |
| `api.adoptium.net` (and its GitHub release download links) | Temurin Java runtimes |
| `meta.fabricmc.net`, `meta.quiltmc.org` | Fabric and Quilt loader profiles |
| `files.minecraftforge.net`, `maven.minecraftforge.net`, `maven.neoforged.net` | Forge and NeoForge installers |
| `api.modrinth.com`, `cdn.modrinth.com` | Mod, resource pack and shader search and downloads |

These third parties may log your IP address and user agent according to their
own privacy policies. The launcher sends a `Blockys/<version>` user agent when
downloading files. No data is shared with the developer.

## Data deletion

Uninstalling Blockys removes the application files but intentionally keeps
`%APPDATA%\BloqueLauncher` so that instances and accounts are not lost. To
delete all launcher data, remove that folder after uninstalling. Game folders
stored outside the launcher data folder (for example instances configured with a
custom directory) are not deleted automatically.

## Children

The launcher does not knowingly collect personal information from anyone,
including children. It has no account system of its own and transmits only the
data needed to authenticate with services you choose to use.

## Changes and contact

This policy is versioned together with the source code. Questions about privacy
can be raised as an issue in the public project repository.
