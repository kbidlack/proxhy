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
    async def _broadcast_peer_settings_event_login_success(self, _):
        config_dir = (
            Path(user_config_dir("proxhy", ensure_exists=True))
            / "broadcast_peer_settings"
        )
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / f"{self.username.lower()}.json"

        self.settings = BroadcastSettings(storage=SettingsStorage(config_path))
        self._send_abilities()

    @listen_client(0x17)
    async def packet_server_plugin_message(self, buff: Buffer):
        channel = buff.unpack(
            String
        )  # e.g. PROXHY|SETTINGS for proxhy settings channel
        data = buff.unpack(ByteArray)

        await self.emit(f"plugin:{channel}", data)

    @subscribe("plugin:PROXHY|SETTINGS")
    async def _settings_event_plugin_message(self, data: bytes):
        buff = Buffer(data)
        setting_path = buff.unpack(String)
        value = buff.unpack(String)

        try:
            setting = self.settings.get_setting_by_path(setting_path)
        except AttributeError:
            return
        if not isinstance(setting, Setting):
            return
        if value not in setting.states:
            return
        setting.set(value)
