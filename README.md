# Proxhy

A Hypixel proxy.

## Installation

The preferred method of installation is to use a Python package manager like `uv`:

```bash
uv tool install git+https://github.com/kbidlack/proxhy
```

You can also try out an ephemerally installed version with `uvx`:

```bash
uvx --from git+https://github.com/kbidlack/proxhy proxhy
```

## Upgrading

```bash
uv upgrade proxhy
```

## Usage

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

```bash
uv tool uninstall proxhy
```

**Note**: Proxhy stores settings, cached data, login credentials, and logs in platform-specific directories:

- **macOS**: `~/Library/Application Support/proxhy`, `~/Library/Caches/proxhy`, `~/Library/Logs/proxhy`
- **Linux**: `~/.config/proxhy`, `~/.cache/proxhy`, `~/.local/share/proxhy`, `~/.local/state/proxhy/log`
- **Windows**: `%LOCALAPPDATA%\proxhy`, `%LOCALAPPDATA%\proxhy\Cache`, `%LOCALAPPDATA%\proxhy\Logs`

These directories are not automatically removed during uninstallation.
