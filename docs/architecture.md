## System Architecture

Proxhy sits in between the Minecraft client and the Hypixel server.

```
┌─────────────────────────────────────────────────────────────────┐
│                        Minecraft Client                         │
└────────────┬────────────────────────────────────────────────────┘
             │ Minecraft Protocol (TCP) (UNENCRYPTED)
┌────────────▼────────────────────────────────────────────────────┐
│                      Proxhy Proxy Server                        │
│  ┌─────────────────┬─────────────────┬─────────────────────────┐ │
│  │   Command       │   Packet        │      Game State         │ │
│  │   System        │   Handlers      │      Management         │ │
│  └─────────────────┼─────────────────┼─────────────────────────┘ │
│  ┌─────────────────┼─────────────────┼─────────────────────────┐ │
│  │   Data Types    │   Stream        │      Settings           │ │
│  │   & Protocol    │   Management    │      System             │ │
│  └─────────────────┴─────────────────┴─────────────────────────┘ │
└────────────┬────────────────────────────────────────────────────┘
             │ Minecraft Protocol (TCP) (ENCRYPTED)
┌────────────▼───────────────────────────────────────────────────┐
│                      Hypixel Server                             │
└─────────────────────────────────────────────────────────────────┘
```

A vanilla Minecraft client will always attempt to encrypt connections, unless the server is hosted locally. Therefore, we can leave the connection from the client to Proxhy (on localhost) unencrypted. Proxhy then handles an encrypted connection to Hypixel. Packets are sent from the Minecraft client to Proxhy, which Proxhy then encrypts, potentially compresses, and then sends to the server. The server then will send back packets which are unencrypted, uncompressed, and then passed down to the client.