# Proxhy

An advanced, feature-rich proxy for players who want to level up their Hypixel experience! Proxhy is **free forever**.

Proxhy adds a multitude of customizable quality of life features, allows you to view player stats in the tab list, and can broadcast live games to your friends, allowing them to spectate while you play.

### [Download Proxhy!](#Download)

## Features
*All relevant features may be disabled at any time through the settings menu.*

### General
&nbsp;&nbsp;&nbsp;&nbsp;[↗](#sc) `/sc` to view any player's game stats

&nbsp;&nbsp;&nbsp;&nbsp;[↗](#settings) Settings GUI accessed via `/setting` lets you enable, disable, or customize any feature

&nbsp;&nbsp;&nbsp;&nbsp;[↗](#autoboop) An Autoboop list to automatically `/boop` select players on your friend list when they join

&nbsp;&nbsp;&nbsp;&nbsp;[↗](#QOL) QOL: Re-queue games with `/rq`, send command outputs to chat with `//`, check a user's last login with `/lastlogin`, and use intuitive `/play` commands to join games

### Broadcasting
&nbsp;&nbsp;&nbsp;&nbsp;[↗](#broadcast) Spectate your friends' games and invite them to spectate yours with the `/broadcast join` and `/broadcast invite` commands

&nbsp;&nbsp;&nbsp;&nbsp;[↗](#watch) `/watch` to have your camera automatically follow the player you are spectating

&nbsp;&nbsp;&nbsp;&nbsp;[↗](#spectate-menu) Spectate menu accessed by right clicking players shows inventory (owner only), health, and armor

&nbsp;&nbsp;&nbsp;&nbsp;[↗](#broadcast-whitelist) Whitelist for security and privacy

### Bed Wars
&nbsp;&nbsp;&nbsp;&nbsp;[↗](#tablist-stats) Toggleable and customizable player stats in the tab list, replacing external overlays

&nbsp;&nbsp;&nbsp;&nbsp;[↗](#respawn-timers) Respawn timers in the tab list

&nbsp;&nbsp;&nbsp;&nbsp;[↗](#disconnect-respawning) Chat message when a player disconnects while respawning

&nbsp;&nbsp;&nbsp;&nbsp;[↗](#show-eliminated) Show elimiated players in the tab list, grayed out

&nbsp;&nbsp;&nbsp;&nbsp;[↗](#first-rush-highlight) Highlight the stats of your first rush team(s)

&nbsp;&nbsp;&nbsp;&nbsp;[↗](#preface-top-stats) Display the top player stats at the start of the game

&nbsp;&nbsp;&nbsp;&nbsp;[↗](#height-limit) Particles to visualize the lower and upper height limits when you get close to them

## Download

[![Latest Release](https://img.shields.io/github/v/release/kbidlack/proxhy?style=flat-square)](https://github.com/kbidlack/proxhy/releases/latest)

| Platform              | Download                                                                                           |
| --------------------- | -------------------------------------------------------------------------------------------------- |
| macOS (Apple Silicon) | [Proxhy.zip](https://github.com/kbidlack/proxhy-gui/releases/latest/download/Proxhy.zip)           |
| Windows (x64)         | [Proxhy.exe](https://github.com/kbidlack/proxhy-gui/releases/latest/download/Proxhy.exe)           |
| Linux (x64)           | [Proxhy.AppImage](https://github.com/kbidlack/proxhy-gui/releases/latest/download/Proxhy.AppImage) |

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


## Features (in-depth)
<details>
  <summary><a id="sc"></a><strong><code>/sc</code> command</strong></summary>

  ...

</details>
<details>
  <summary><a id="settings"></a><strong>Settings menu</strong></summary>

  ...

</details>
<details>
  <summary><a id="autoboop"></a><strong>Autoboop</strong></summary>

  ...

</details>
<details>
  <summary><a id="QOL"></a><strong>Quality of Life features</strong></summary>

  ...

</details>
<details>
  <summary><a id="broadcast"></a><strong>Broadcasts</strong></summary>

  ...

</details>
<details>
  <summary><a id="watch"></a><strong><code>/watch</code> Broadcast command</strong></summary>

  ...

</details>
<details>
  <summary><a id="spectate-menu"></a><strong>Broadcast spectate menu</strong></summary>

  ...

</details>
<details>
  <summary><a id="broadcast-whitelist"></a><strong>Broadcast whitelists</strong></summary>

  ...

</details>
<details>
  <summary><a id="tablist-stats"></a><strong>Tab list stats</strong></summary>

  ...

</details>
<details>
  <summary><a id="respawn-timers"></a><strong>Respawn timers</strong></summary>

  ...

</details>
<details>
  <summary><a id="disconnect-respawning"></a><strong>Disconnected while respawning</strong></summary>

  ...

</details>
<details>
  <summary><a id="show-eliminated"></a><strong>Eliminated players in tab list</strong></summary>

  ...

</details>
<details>
  <summary><a id="first-rush-highlight"></a><strong>First rush stat highlights</strong></summary>

  ...

</details>
<details>
  <summary><a id="preface-top-stats"></a><strong>Preface top stats</strong></summary>

  ...

</details>
<details>
  <summary><a id="height-limit"></a><strong>Height limit warnings</strong></summary>
