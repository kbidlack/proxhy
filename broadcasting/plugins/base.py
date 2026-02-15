import asyncio
import uuid
from typing import Literal, Optional

from broadcasting.plugin import BroadcastPeerPlugin
from core.events import subscribe
from protocol.datatypes import (
    UUID,
    Byte,
    Double,
    Float,
    TextComponent,
    VarInt,
)
from proxhy.argtypes import ServerPlayer
from proxhy.command import command
from proxhy.errors import CommandException
from proxhy.gamestate import PlayerAbilityFlags


class BroadcastPeerBasePluginState:
    flight: Literal[0, PlayerAbilityFlags.ALLOW_FLYING]
    flying: Literal[0, PlayerAbilityFlags.FLYING]


class BroadcastPeerBasePlugin(BroadcastPeerPlugin):
    # base functionality

    def _init_broadcast_peer(self):
        self.uuid = ""
        self.spec_eid: Optional[int] = None
        self.flight: Literal[0, PlayerAbilityFlags.ALLOW_FLYING] = (
            PlayerAbilityFlags.ALLOW_FLYING
        )  # alternatively 0 if off
        self.flying: Literal[0, PlayerAbilityFlags.FLYING] = PlayerAbilityFlags.FLYING

    @subscribe("close")
    async def _broadcast_peer_base_event_close(self, _match, _data):
        # remove this client
        if self in self.proxy.clients:
            self.proxy.clients.remove(self)  # ty: ignore[invalid-argument-type]

        try:
            self.writer.close()
            await asyncio.wait_for(self.writer.wait_closed(), timeout=0.5)
        except asyncio.TimeoutError:
            pass

        try:
            self.username
        except AttributeError:
            # username not set; handshake only?
            return

        self.proxy.client.chat(
            TextComponent(self.username)
            .color("aqua")
            .appends(TextComponent("left the broadcast!").color("red"))
        )

        # Play UI click sound at low pitch for leave
        self.proxy._play_sound("random.click", pitch=40)

        self.proxy.client.send_packet(
            0x38,
            VarInt.pack(4),  # action: remove player
            VarInt.pack(1),  # number of players
            UUID.pack(uuid.UUID(self.uuid)),
        )

    @command("tp", "teleport", usage=["<player>", "<x> <y> <z>"])
    async def _command_tp(
        self,
        target_or_x: ServerPlayer | float,
        y: float | None = None,
        z: float | None = None,
    ) -> TextComponent:
        """Teleport to a player or coordinate set."""
        if isinstance(target_or_x, ServerPlayer):
            target = target_or_x
            # compare by username since UUIDs may differ in offline/local mode
            if target.name.casefold() == self.proxy.username.casefold():
                pos = self.proxy.gamestate.position
            else:
                # another player, check that they're spawned nearby
                if target.uuid is None:
                    raise CommandException(
                        TextComponent("Player '")
                        .append(TextComponent(target.name).color("gold"))
                        .append("' is not nearby!")
                    )
                entity = self.proxy.gamestate.get_player_by_uuid(target.uuid)
                if not entity:
                    raise CommandException(
                        TextComponent("Player '")
                        .append(TextComponent(target.name).color("gold"))
                        .append("' is not nearby!")
                    )
                pos = entity.position

            self.client.send_packet(
                0x08,
                Double.pack(pos.x),
                Double.pack(pos.y),
                Double.pack(pos.z),
                Float.pack(self.proxy.gamestate.rotation.yaw),
                Float.pack(self.proxy.gamestate.rotation.pitch),
                Byte.pack(0),  # flags: all absolute
            )
            return (
                TextComponent("Teleported to ")
                .color("green")
                .append(TextComponent(target.name).color("aqua"))
            )

        # target is a float (x coordinate)
        x = target_or_x
        if y is None or z is None:
            raise CommandException(
                "Position teleport requires x, y, and z coordinates!"
            )
        self.client.send_packet(
            0x08,
            Double.pack(x),
            Double.pack(y),
            Double.pack(z),
            Float.pack(self.proxy.gamestate.rotation.yaw),
            Float.pack(self.proxy.gamestate.rotation.pitch),
            Byte.pack(0),  # flags: all absolute
        )
        return (
            TextComponent("Teleported to ")
            .color("green")
            .append(TextComponent(f"{x:.1f}, {y:.1f}, {z:.1f}").color("gold"))
        )

    @command("pos")
    async def _command_pos(self):
        self.client.chat(str(self.gamestate.position))

    @command("fly")
    async def _command_fly(self):
        if self.flight == PlayerAbilityFlags.ALLOW_FLYING:
            self.flight = 0
            self.flying = 0
        else:  # self.flight == 0
            self.flight = PlayerAbilityFlags.ALLOW_FLYING

        self.client.send_packet(
            0x39,
            Byte.pack(PlayerAbilityFlags.INVULNERABLE | self.flying | self.flight)
            + Float.pack(self.flight_speed)
            + Float.pack(self.proxy.gamestate.field_of_view_modifier),
        )

        return TextComponent(f"Turned flight {'on' if self.flight else 'off'}!").color(
            "green"
        )

    @command("locraw")
    async def _command_locraw(self):
        # just do nothing
        # not really sure what we should be doing otherwise
        pass

    @command("tip")
    async def _command_tip(self):
        # see above
        pass
