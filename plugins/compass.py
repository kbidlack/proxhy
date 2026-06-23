import asyncio
from typing import TYPE_CHECKING

import mcauth as auth
from compass import CompassClient, RequestFailure
from petty.protocol.datatypes import TextComponent
from plugins.commands import CommandGroup

if TYPE_CHECKING:
    from proxhy.plugin import ProxhyPlugin


BROKER_URL = "http://163.192.4.69:8080/ticket"


class CompassPlugin:
    # TODO: add /compass restart and /compass close (or deinit) if needed

    def _init_compass(self: ProxhyPlugin):
        self.compass_client = CompassClient(
            broker_url=BROKER_URL,
            username="",
            uuid="",
            access_token="",
        )  # so I can say that compass_client is not optional lol

        self._setup_compass_commands()

    def _setup_compass_commands(self: ProxhyPlugin):
        compass = CommandGroup("compass", help="Compass client commands.")

        @compass.command("status")
        async def _command_compass_status(self: ProxhyPlugin):
            """Get the compass client status."""

            return (
                TextComponent("Compass Client Status:\n")
                .color("gold")
                .append(TextComponent("Registered:").color("green"))
                .appends(
                    TextComponent(str(self.compass_client.registered)).color("yellow")
                )
                .appends(TextComponent("Broker URL:").color("green"), separator="\n")
                .appends(
                    TextComponent(self.compass_client.broker_url)
                    .color("yellow")
                    .hover_text(TextComponent("Click to copy").color("yellow"))
                    .click_event("suggest_command", self.compass_client.broker_url)
                )
            )

    async def initialize_cc(self: ProxhyPlugin):
        self.access_token, self.username, self.uuid = await auth.load_auth_info(
            self.username
        )
        self.uuid = self.uuid

        self.compass_client = CompassClient(
            broker_url=BROKER_URL,
            username=self.username,
            uuid=str(self.uuid),
            access_token=self.access_token,
        )

        if self.endpoint is None:
            self.downstream.chat(
                TextComponent(
                    "Failed to initialize the compass client. (this should not happen!)"
                ).color("red")
            )
            return  # TODO: log

        try:
            async with asyncio.timeout(5):
                await self.compass_client.register(self.endpoint)
        except TimeoutError:
            return self.downstream.chat(
                TextComponent("Failed to initialize compass client (timed out)!").color(
                    "red"
                )
            )
        except RequestFailure as e:
            return self.downstream.chat(
                TextComponent(f"Failed to initialize the compass client! ({e.details})")
            )
        except Exception as e:
            return self.downstream.chat(
                TextComponent(
                    f"Failed to initialize compass client due to an unknown error! ({e})"
                ).color("red")
            )

        if self.dev_mode:
            self.downstream.chat(
                TextComponent("✓ Compass client initialized!").color("green")
            )
