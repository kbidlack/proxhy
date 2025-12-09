# Proxhy

A Hypixel proxy.

## Installation

The preferred method of installation is to use a Python package manager like `pipx` or `uv`:
```bash
pipx install proxhy
```
or
```bash
uv tool install proxhy
```

Alternatively, you can install it using `pip`.
```bash
pip install proxhy
```

## Upgrading

With pipx or uv:
```bash
pipx upgrade proxhy  # or: uv tool upgrade proxhy
```

With pip:
```bash
pip install --upgrade proxhy
```

## Usage

Start the proxy:
```bash
proxhy
```

By default, this connects to `mc.hypixel.net:25565` and binds to `localhost:41223`.

### Options
```
-rh, --remote-host HOST    Remote server host (default: mc.hypixel.net)
-rp, --remote-port PORT    Remote server port (default: 25565)
-p, --port PORT            Local proxy port (default: 41223)
--local                    Connect to localhost:25565 for development
--dev                      Bind proxy to localhost:41224 for development
-fh, --fake-host HOST      Host to report to the server (default: remote-host)
-fp, --fake-port PORT      Port to report to the server (default: remote-port)
```

## Uninstallation
With pipx or uv:
```bash
pipx uninstall proxhy  # or: uv tool uninstall proxhy
```

With pip:
```bash
pip uninstall proxhy
```

**Note**: Proxhy stores settings, cached data, and login credentials in platform-specific directories:
- **macOS**: `~/Library/Application Support/proxhy`, `~/Library/Caches/proxhy`
- **Linux**: `~/.config/proxhy`, `~/.cache/proxhy`, `~/.local/share/proxhy`
- **Windows**: `%LOCALAPPDATA%\proxhy`, `%LOCALAPPDATA%\proxhy\Cache`

These directories are not automatically removed during uninstallation.
