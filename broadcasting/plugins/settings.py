from pathlib import Path

from platformdirs import user_config_dir

from broadcasting.plugin import BroadcastPeerPlugin
from broadcasting.settings import BroadcastSettings
from core.events import listen_client, subscribe
from core.settings import Setting, SettingsStorage
from plugins.settings import SettingsPlugin
from protocol.datatypes import (
    Buffer,
    ByteArray,
    String,
)


class BroadcastPeerSettingsPluginState:
    settings: BroadcastSettings


class BroadcastPeerSettingsPlugin(BroadcastPeerPlugin, SettingsPlugin):
    settings: BroadcastSettings

    def _init_settings(self):
        pass  # override automatic creation of ProxhySettings

    @subscribe("login_success")
    async def _broadcast_peer_settings_event_login_success(self, _match, _data):
        config_dir = (
            Path(user_config_dir("proxhy", ensure_exists=True))
            / "broadcast_peer_settings"
        )
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / f"{self.username.lower()}.json"

        self.settings = BroadcastSettings(storage=SettingsStorage(config_path))
        self._send_abilities()

    @listen_client(0x17)
    async def packet_client_plugin_message(self, buff: Buffer):
        channel = buff.unpack(
            String
        )  # e.g. PROXHY|Settings for proxhy settings channel
        data = buff.read()

        await self.emit(f"plugin:{channel}", data)

    @subscribe(r"plugin:PROXHY\|Settings")
    async def _settings_event_plugin_message(self, _match, data: bytes):
        buff = Buffer(data)

        setting_path, old_value, new_value = (buff.unpack(String) for _ in range(3))

        # TODO: log these failures if they happen
        try:
            setting = self.settings.get_setting_by_path(setting_path)
        except AttributeError:
            print(f"Setting path '{setting_path}' not found")
            return
        if not isinstance(setting, Setting):
            print(f"Path '{setting_path}' is not a Setting, got {type(setting)}")
            return
        if new_value not in setting.states:
            print(
                f"Invalid state '{new_value}' for '{setting_path}', valid: {list(setting.states.keys())}"
            )
            return

        setting.set(new_value)  # ty: ignore[invalid-argument-type]

        await self.emit(f"setting:{setting_path}", [old_value, new_value])
