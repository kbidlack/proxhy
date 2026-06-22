import sys
import time
from importlib.metadata import version
from typing import TYPE_CHECKING

from petty.protocol.datatypes import TextComponent
from plugins.commands import CommandGroup
from proxhy.utils import zero_pad_calver

if TYPE_CHECKING:
    from proxhy.plugin import ProxhyPlugin


class SlashProxhy:
    def _init_slash_proxhy(self: ProxhyPlugin):
        self._setup_proxhy_commands()

        self._last_close_try_time = -1.0

    def _setup_proxhy_commands(self: ProxhyPlugin):
        proxhy = CommandGroup("proxhy", help="Proxhy utility commands.")

        @proxhy.command("version")
        async def _command_proxhy_version(self: ProxhyPlugin):
            """Get the current running version of Proxhy."""
            return (
                TextComponent("You are currently running Proxhy version")
                .color("yellow")
                .appends(
                    TextComponent(zero_pad_calver(version("proxhy"))).color("green")
                )
            )

        @proxhy.command("close")
        async def _command_proxhy_close(self: ProxhyPlugin):
            """Closes Proxhy. <!> Only do this if Proxhy is stuck <!>"""
            if time.monotonic() - self._last_close_try_time > 5:
                self._last_close_try_time = time.monotonic()

                self.downstream.chat(
                    TextComponent(
                        "<!> This command should only be run if Proxhy is stuck <!>"
                    ).color("red")
                )
                return self.downstream.chat(
                    TextComponent("Are you sure you want to do this? If you are, run")
                    .color("dark_red")
                    .appends(TextComponent("/proxhy close").color("gold"))
                    .appends("again.")
                )

            sys.exit()

        self.command_registry.register(proxhy)
