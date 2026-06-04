# Proxhy

A Hypixel proxy.

## Download

[![Latest Release](https://img.shields.io/github/v/release/kbidlack/proxhy?style=flat-square)](https://github.com/kbidlack/proxhy/releases/latest)

| Platform              | Download                                                                                               |
| --------------------- | ------------------------------------------------------------------------------------------------------ |
| macOS (Apple Silicon) | [proxhy-macos.zip](https://github.com/kbidlack/proxhy-gui/releases/latest/download/Proxhy.zip)         |
| Windows (x64)         | [proxhy-windows.zip](https://github.com/kbidlack/proxhy-gui/releases/latest/download/Proxhy.exe)       |
| Linux (x64)           | [proxhy-linux.tar.gz](https://github.com/kbidlack/proxhy-gui/releases/latest/download/Proxhy.AppImage) |

- **macOS:** Unzip → drag `Proxhy.app` to Applications → double-click.
- **Windows:** Run `Proxhy.exe`.
- **Linux:** Run `Proxhy.AppImage`.

> [!NOTE]  
> macOS will say the app is "damaged" because it's unsigned. To fix (after moving `Proxhy.app` to `/Applications`):

1. Open Terminal
2. Run: `xattr -cr /Applications/Proxhy.app`
3. Open Proxhy normally

## Alternative Installiation

You can also install and run Proxhy without a GUI.

The preferred method of installation is to use a Python package manager like `uv`:

```bash
uv tool install git+https://github.com/kbidlack/proxhy
```

You can also try out an ephemerally installed version with `uvx`:

```bash
uvx --from git+https://github.com/kbidlack/proxhy proxhy
```

### Upgrading

```bash
uv tool upgrade proxhy
```

### Usage

Start the proxy:

```bash
proxhy
```

or

```bash
uv tool run proxhy
```

By default, this connects to `mc.hypixel.net:25565` and binds to `localhost:41223`.

### Options

```
-rh, --remote-host HOST    Remote server host (default: mc.hypixel.net)
-rp, --remote-port PORT    Remote server port (default: 25565)
-p, --port PORT            Local proxy port (default: 41223)
--local                    Connect to localhost:25565 for development
--dev                      Bind proxy to localhost:41224 and disable compass client
-fh, --fake-host HOST      Host to report to the server (default: remote-host)
-fp, --fake-port PORT      Port to report to the server (default: remote-port)
```

## Uninstallation

> [!NOTE]
> Proxhy stores settings, cached data, login credentials, and logs in platform-specific directories, which are not automatically removed during uninstallation.

- **macOS**: `~/Library/Application Support/proxhy`, `~/Library/Caches/proxhy`, `~/Library/Logs/proxhy`
- **Linux**: `~/.config/proxhy`, `~/.cache/proxhy`, `~/.local/share/proxhy`, `~/.local/state/proxhy/log`
- **Windows**: `%LOCALAPPDATA%\proxhy`, `%LOCALAPPDATA%\proxhy\Cache`, `%LOCALAPPDATA%\proxhy\Logs`

### GUI

Delete the app file:

**macOS:** Remove `/Applications/Proxhy.app`

**Windows:** Delete `Proxhy.exe`

**Linux:** Delete `Proxhy.AppImage`

### CLI

```bash
uv tool uninstall proxhy
```
