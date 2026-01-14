from core.plugin import Plugin
from proxhy.proxhy import Proxhy

class BroadcastPeerPlugin(Plugin):
    proxy: Proxhy
    eid: int
