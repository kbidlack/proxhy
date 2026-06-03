import shelve
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from platformdirs import user_config_dir

from petty.protocol.datatypes import TextComponent
from plugins.commands import CommandGroup
from plugins.commands._commands import CommandArg, CommandException

if TYPE_CHECKING:
    from plugins.commands._commands import CommandContext
    from proxhy.plugin import ProxhyPlugin


class PlayerList:
    """Low-level access to a named player list in the shared DB.

    Entries are stored as {lower_name: (proper_name, display_str, uuid)}.
    uuid is an empty string when not applicable.
    display_str is a plain string, optionally with § color codes.
    """

    DB_PATH: Path = Path(user_config_dir("proxhy")) / "player_lists.db"

    def __init__(self, key: str):
        self.key = key

    def all(self) -> dict[str, tuple[str, str, str]]:
        """Return {lower_name: (proper_name, display_str, uuid)}."""
        with shelve.open(str(self.DB_PATH)) as db:
            raw = db.get(self.key, {})
            return {k: (v[0], v[1], v[2] if len(v) > 2 else "") for k, v in raw.items()}

    def contains(self, name: str) -> bool:
        with shelve.open(str(self.DB_PATH)) as db:
            return name.lower() in db.get(self.key, {})

    def contains_uuid(self, uuid: str) -> bool:
        return any(entry[2] == uuid for entry in self.all().values())

    def add(self, name: str, display: str, uuid: str = "") -> None:
        with shelve.open(str(self.DB_PATH)) as db:
            players = db.get(self.key, {})
            players[name.lower()] = (name, display, uuid)
            db[self.key] = players

    def remove(self, name: str) -> tuple[str, str, str]:
        """Remove and return (proper_name, display_str, uuid). Raises KeyError if not found."""
        with shelve.open(str(self.DB_PATH)) as db:
            players = db.get(self.key, {})
            result = players.pop(name.lower())
            db[self.key] = players
            return result

    def names(self) -> list[str]:
        """Return sorted list of properly-capitalized player names."""
        return sorted(v[0] for v in self.all().values())


class PlayerListSystem:
    """Declarative player list: configure once, get list/add/remove commands for free.

    Usage::

        PlayerListSystem(
            "autoboop", "ab",
            key=lambda proxy: f"autoboop:{proxy.username}",
            add_type=HypixelPlayer,
            display=lambda player: get_rankname(player._player),
        ).register(self)

        PlayerListSystem(
            "trust",
            label="trusted players",
            help="Manage trusted players.",
            key=lambda proxy: "trusted",
            add_type=MojangPlayer,
            display=lambda player: player.name,
            uuid=lambda player: player.uuid,
        ).register(self, onto=bc_group)
    """

    def __init__(
        self,
        *names: str,
        label: str | None = None,
        help: str = "",
        key: Callable[[Any], str],
        add_type: type,
        display: Callable[[Any], str],
        uuid: Callable[[Any], str] | None = None,
        on_change: Callable[[Any], Any] | None = None,
    ):
        self._names = names
        self._label = label or names[0]
        self._help = help
        self._key = key
        self._add_type = add_type
        self._display = display
        self._uuid = uuid
        self._on_change = on_change

    def register(
        self,
        proxy: "ProxhyPlugin",
        *,
        onto: CommandGroup | None = None,
    ) -> CommandGroup:
        """Build and register list/add/remove subcommands.

        If *onto* is provided, creates a subgroup on it (e.g. bc.group(...)).
        Otherwise creates a standalone top-level group registered with the proxy.
        """
        system = self
        label = self._label

        # --- remove arg type: suggests from the list, no API call needed ---
        class _RemoveArg(CommandArg):
            def __init__(self, value: str):
                self.value = value

            @classmethod
            async def convert(cls, ctx: "CommandContext", value: str) -> "_RemoveArg":
                return cls(value)

            @classmethod
            async def suggest(cls, ctx: "CommandContext", partial: str) -> list[str]:
                pl = PlayerList(system._key(ctx.proxy))
                p = partial.lower()
                return [n for n in pl.names() if n.lower().startswith(p)]

        # --- build the group ---
        if onto is not None:
            group = onto.group(*system._names, help=system._help)
        else:
            group = CommandGroup(*system._names, help=system._help)

        # --- list ---
        async def _list(self: "ProxhyPlugin"):
            pl = PlayerList(system._key(self))
            entries = pl.all()
            if not entries:
                return TextComponent(f"No players in {label}!").color("green")
            self.downstream.chat(TextComponent(f"Players in {label}:").color("green"))
            msg = TextComponent("> ").color("green")
            for i, (_, (_, display, _uuid)) in enumerate(sorted(entries.items())):
                if i != 0:
                    msg.append(TextComponent(", ").color("green"))
                msg.append(TextComponent(display))
            return msg

        _list.__doc__ = f"List all players in {label}."
        group.command("list", "ls")(_list)

        # --- add ---
        async def _add(self: "ProxhyPlugin", player):
            display = system._display(player)
            uuid = system._uuid(player) if system._uuid else ""
            pl = PlayerList(system._key(self))
            if pl.contains(player.name):
                raise CommandException(
                    TextComponent(player.name)
                    .color("gold")
                    .appends(f"is already in {label}!")
                )
            pl.add(player.name, display, uuid)
            if system._on_change:
                try:
                    await system._on_change(self)
                except Exception:
                    pass
            return (
                TextComponent("Added ")
                .color("green")
                .append(TextComponent(display))
                .appends(TextComponent(f"to {label}!").color("green"))
            )

        _add.__doc__ = f"Add a player to {label}."
        _add.__annotations__ = {"player": system._add_type}
        group.command("add")(_add)

        # --- remove ---
        async def _remove(self: "ProxhyPlugin", player):
            pl = PlayerList(system._key(self))
            try:
                proper_name, display, _uuid = pl.remove(player.value)
            except KeyError:
                raise CommandException(
                    TextComponent(player.value)
                    .color("gold")
                    .appends(f"is not in {label}!")
                )
            if system._on_change:
                try:
                    await system._on_change(self)
                except Exception:
                    pass
            return (
                TextComponent("Removed ")
                .color("green")
                .append(TextComponent(display))
                .appends(TextComponent(f"from {label}!").color("green"))
            )

        _remove.__doc__ = f"Remove a player from {label}."
        _remove.__annotations__ = {"player": _RemoveArg}
        group.command("remove", "rm")(_remove)

        if onto is None:
            proxy.command_registry.register(group)

        return group
