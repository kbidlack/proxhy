from __future__ import annotations
# "proxy" for any connected broadcast clients
# we are just reusing proxy code and then omitting the server
# to be able to take advantage of all the prebuilt plugins
# and packet handling stuff from proxy, just for a client connection


from broadcasting.plugin import BroadcastPeerPlugin


class BroadcastPeerProxy(BroadcastPeerPlugin): ...
