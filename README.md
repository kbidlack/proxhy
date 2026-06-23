# Proxhy

[![Latest Release](https://img.shields.io/github/v/release/kbidlack/proxhy?style=flat-square)](https://github.com/kbidlack/proxhy/releases/latest)
[![Discord](https://img.shields.io/discord/1517293954029195344?logo=discord&logoColor=white&label=Discord&labelColor=5865F2&color=gray)](https://discord.com/invite/3qFP9SQT)

[![macOS](https://img.shields.io/badge/macOS-000000?style=flat-square&logo=apple&logoColor=white)](https://github.com/kbidlack/proxhy-gui/releases/latest/download/Proxhy.zip)
[![Windows](https://img.shields.io/badge/Windows-0078D6?style=flat-square&logo=windows&logoColor=white)](https://github.com/kbidlack/proxhy-gui/releases/latest/download/Proxhy.exe)
[![Linux](https://img.shields.io/badge/Linux-FCC624?style=flat-square&logo=linux&logoColor=black)](https://github.com/kbidlack/proxhy-gui/releases/latest/download/Proxhy.AppImage)

An advanced, feature-rich Minecraft 1.8.9 proxy for players who want to level up their Hypixel experience! Proxhy is **free forever**.

Proxhy adds a multitude of customizable quality of life features, allows you to view player stats in the tab list, and can broadcast live games to your friends, allowing them to spectate while you play.

### [Download Proxhy!](#Download)

## Features

_All relevant features may be disabled at any time through the settings menu._

### General

&nbsp;&nbsp;&nbsp;&nbsp;[↗](#sc) `/sc` to view any player's game stats

&nbsp;&nbsp;&nbsp;&nbsp;[↗](#settings) Settings menu accessed via `/setting` lets you enable, disable, or customize any feature

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

### How to use

After opening the Proxhy app, press the "Start" button in the top-left corner. Then, join the server IP `localhost:41223` on Minecraft version 1.8.9 from any client.

## Alternative Installation

The easiest way to run Proxhy is to use [uv](https://docs.astral.sh/uv/):

```bash
uvx --index=https://kbidlack.github.io/proxhy/simple proxhy
```

This will fetch the latest Proxhy release and run it. To update, simply rerun the command. By default, this connects to `mc.hypixel.net:25565` and binds to `localhost:41223`.

You can also install Proxhy with uv:

```bash
uv tool install --index=https://kbidlack.github.io/proxhy/simple proxhy
```

### CLI Options

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

### Application

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
  <summary><h3><a id="sc"></a><strong><code>/sc</code> command</strong></h3></summary>
  
`/sc [player] [mode?] [window?] [stats...]` fetches and displays Hypixel stats for any player. Omitting the player name checks yourself.

The default view shows abbreviated mode breakdowns (Solo, Doubles, Threes, Fours for Bed Wars); append `full` (e.g. `/scfull`) to show all modes including Dream modes.

The optional `window` parameter limits stats to a recent time period in days — `/scw` and `/scweekly` are shortcuts for the last 7 days. You can also filter which stats are displayed by listing them explicitly.

Hovering over the stat output in chat shows per-mode breakdowns. If a player is currently online, `(ONLINE)` is shown next to their name.

Requires a valid Hypixel API key, stored securely in the system keyring. You can get one at [https://developer.hypixel.net](https://developer.hypixel.net)

</details>
<details>
  <summary><h3><a id="settings"></a><strong>Settings menu</strong></h3></summary>

`/s` opens a menu for browsing and toggling all Proxhy settings. Settings are organized into categories (Bed Wars, Compass, Broadcast); enabled settings are indicated with an enchantment glow. Hover over any item to read its description.

</details>
<details>
  <summary><h3><a id="autoboop"></a><strong>Autoboop</strong></h3></summary>

Autoboop automatically sends `/boop` to players on a personal list whenever they join as a friend or guild member.

Manage the list with `/ab`:

- `/ab add <player>` — add a player
- `/ab remove <player>` — remove a player
- `/ab list` — view the current list

</details>
<details>
  <summary><h3><a id="QOL"></a><strong>Quality of Life features</strong></h3></summary>

**`/rq` — Requeue**
Instantly re-joins the last gamemode you played.

**`//` — Send command output to chat**
Prefix any command with `//` instead of `/` to broadcast its output to all players in your game. For example, `//sc Player` sends the stat result as a chat message rather than showing it only to you.

**`/lastlogin` / `/ll` — Last login**
Shows when a player last logged into Hypixel, formatted with an ordinal date, time, and timezone (e.g. "January 1st, 2024 at 3:42 PM EST"). Defaults to yourself if no player is specified. Shows `(ONLINE)` if the player is currently connected.

**`/play` — Intuitive game joining**
An enhanced `/play` command with autocomplete for gamemodes and submodes (e.g. `/play bedwars solo`). Shows available options if an incomplete submode is provided, so you never need to memorize Hypixel's internal game IDs. However, internal game IDs (e.g. `/play bedwars_eight_one`) are still supported.

</details>
<details>
  <summary><h3><a id="broadcast"></a><strong>Broadcasts</strong></h3></summary>

Broadcasts let friends using Proxhy spectate your game in real time, or let you spectate theirs.

- `/broadcast join <player>` — Request to join another player's broadcast as a spectator. The request expires after 60 seconds if not accepted.
- `/broadcast invite <player>` — Invite another player to spectate your broadcast. Also expires after 60 seconds.
- `/broadcast accept <player>` — Accept a pending join request or invite.
- `/broadcast list` — List all spectators currently connected to your broadcast.
- `/broadcast chat [message]` — Send a message in the private broadcast chat channel. You can toggle broadcast chat with `/chat bc`.
- `/broadcast slime <player>` — Slime out\* a spectator from your broadcast.
- `/broadcast server` — Show your broadcast server node ID.

Trusted players (see [Broadcast whitelists](#broadcast-whitelist)) are accepted into your broadcast automatically without a prompt; use `/bc trust` to manage trusted players.

_\* Note: "slime out" is synonymous with "kick"._

</details>
<details>
  <summary><h3><a id="watch"></a><strong><code>/watch</code> Broadcast command</strong></h3></summary>

`/watch` is available to broadcast spectators and puts the camera into a cinematic follow mode. The camera locks onto the player you are spectating and tracks them from a fixed relative position, giving a smooth third-person view, reminiscent of an enhanced "F5" view. Sneak to exit cinematic mode.

</details>
<details>
  <summary><h3><a id="spectate-menu"></a><strong>Broadcast spectate menu</strong></h3></summary>

Right-clicking any player while spectating a broadcast opens a menu with live information about that player:

- **Player head** — Shows the player's skin, current health (in supported gamemodes), and Hypixel level.
- **Spectate** — Snaps your viewpoint to that player's perspective.
- **Watch** — Enters [cinematic camera mode](#watch) following that player.
- **Equipment slots** — Displays their current helmet, chestplate, leggings, boots, and main-hand item, updated every 0.5 seconds. Empty slots are shown as red glass panes.

The menu for the broadcast owner includes their current inventory and always shows health.

</details>
<details>
  <summary><h3><a id="broadcast-whitelist"></a><strong>Broadcast whitelists</strong></h3></summary>

Two separate lists control access to your broadcasts:

**Trusted players** (`/broadcast trust add|remove|list <player>`):

Players on this list have their join requests to your broadcast auto-accepted.

**Blocked players** (`/broadcast block add|remove|list <player>`):

Players on this list will not be able to invite you to their or join your broadcasts.

</details>
<details>
  <summary><h3><a id="tablist-stats"></a><strong>Tab list stats</strong></h3></summary>

Proxhy injects the Bed Wars tab list to show player stats alongside each name, replacing the need for external overlays. Each entry shows the player's star level and FKDR, color-coded by team.
Configurable options:

- **Mode-specific stats** — Show stats for the current Bed Wars mode (e.g. Doubles only) instead of lifetime overall stats.
- **Show rank name** — Display the player's rank (e.g. `MVP+`) alongside their team color prefix. This overrides their team color, making their name color in tab the same as their rank.

Stats are fetched from the Hypixel API when players appear in the tab list and updated as they load.

</details>
<details>
  <summary><h3><a id="respawn-timers"></a><strong>Respawn timers</strong></h3></summary>

When a Bed Wars player dies and enters the respawn state, a countdown timer (5 seconds normally, 10 seconds on reconnect) appears next to their name in the tab list, in gold.

</details>
<details>
  <summary><h3><a id="disconnect-respawning"></a><strong>Disconnected while respawning</strong></h3></summary>

If a player's respawn timer runs out and they never reappear in the tab list, Proxhy sends a chat message: `[PlayerName] disconnected while respawning.`

</details>
<details>
  <summary><h3><a id="show-eliminated"></a><strong>Eliminated players in tab list</strong></h3></summary>

Final-killed players are kept in the tab list as grayed-out, italic entries rather than disappearing entirely. This lets you track which teams are still in the game and who has been eliminated without losing the full player list.

</details>
<details>
  <summary><h3><a id="first-rush-highlight"></a><strong>First rush stat highlights</strong></h3></summary>

At the start of a Bed Wars game, Proxhy shows a title card with the stats of the players on the teams most likely to rush you first (based on map layout).

Three modes (configurable in settings):

- **Off** — disabled.
- **First Rush** — highlights the strongest player on the primary adjacent team.
- **Both Adjacent** — highlights the top player from each of the two adjacent teams.

</details>
<details>
  <summary><h3><a id="preface-top-stats"></a><strong>Preface top stats</strong></h3></summary>

Once all players have been statted at game start, Proxhy prints a ranked list of the top enemy players in chat. Teammates and yourself are excluded. The list can be sorted by FKDR, star level, or a combined index. Nicked players (those whose API lookup returned no data) are called out in a separate section at the top of the list.

</details>
<details>
  <summary><h3><a id="height-limit"></a><strong>Height limit warnings</strong></h3></summary>

When you get within a few blocks of the map's height boundaries during a Bed Wars game, Proxhy displays an actionbar warning and spawns redstone particles at the boundary plane around your position. The actionbar color shifts from green → yellow → orange → red as you get closer.

</details>
