The [proxy.py](../proxhy/proxy.py) file contains base models (most notably `Proxy`) to handle the connection between the client, proxy, and server. Note that this file is named *Proxy*, not *Proxhy*. [proxhy.py](../proxhy/proxhy.py) contains a subclass of `Proxy` which implements any features, packet handlers, methods, etc. that are related to the user-facing and Hypixel-specific features of Proxhy.

There are a couple models to keep in mind here:
```py
class State(Enum):
    HANDSHAKING = 0
    STATUS = 1
    LOGIN = 2
    PLAY = 3
```

An enumeration that provides abstract access to server connection states. More can be found in the Minecraft protocol documentation.

```py
class Proxy
```
The base proxy class. On its own, this class provides a default MOTD, handles server list ping connections, and implements the Minecraft 1.8.9 login flow.

In this class, a notable method is `handle_client` (or `handle_server` for the server side of the connection). It's worth understanding how this works.

When creating an instance of `Proxy`, one passes in an async `StreamReader` and `StreamWriter` class, which are connections received from the client (see [entry.md](entry.md)).

During class initialization, a task is created for `handle_client`.

```py
def __init__(self, ...):
    ...
    asyncio.create_task(self.handle_client())
```

This function is then run for as long as the proxy receives data from the Client.

```py
async def handle_client(self):
    # read a VarInt. if the VarInt exists (there is a packet)
    # then run the loop. if there is nothing (the client disconnected)
    # the loop is terminated.
    while packet_length := await VarInt.unpack_stream(self.client_stream):
        # data is read. if there is data, continue
        if data := await self.client_stream.read(packet_length):
```

A `Buffer` object is then created with the data, and the packet ID and packet data are read from the buffer:
```py
buff = Buffer(data)

packet_id = buff.unpack(VarInt)
packet_data = buff.read()
```

Once the packet data is read, a packet handler is called. These are defined globally with the `client_listeners` and `server_listeners` dictionaries, accessible via `proxy.client_listeners` and `proxy.client_listeners`, respectively. 

To add handlers, the `listen_server` and `listen_client` decorators are used. For example, to read a packet with ID 1 in the `PLAY` state from the clien, one would define a function:
```py
@listen_client(0x01, State.PLAY)
def my_handler(self, buff: Buffer):
    ... # packet data is accessible via buff.read()
```

Back to the `handle_client` loop example, the packet handler is called. There is also an optional blocking field in the decorator (by default set to `False`). This will block the main thread and is not recommended unless something has to run synchronously, which, for now, is only the case for some existing login flow packets. 

Otherwise, the packet is called with `asyncio.create_task()`. This way, if there are any blocking requests that need to be made during the packet handler (such as a network request to the Hypixel API), provided that they are made asynchronously, they will not block Proxhy from continuing to handle the connection while those requests are waited for, such that the client connection can stay stable.

```py
# call packet handler
result = client_listeners.get((packet_id, self.state))
if result:
    handler, blocking = result
    if blocking:
        await handler(self, Buffer(packet_data))
    else:
        asyncio.create_task(handler(self, Buffer(packet_data)))
else:
    self.server_stream.send_packet(packet_id, packet_data)
```