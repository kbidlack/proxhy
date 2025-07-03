To run Proxhy, one would run `py -m proxhy` in the top level proxhy directory. This will run `__main__.py`.

`__main__.py` does one core thing: start the server that listens for client connections. This is done in the `main` function:
```py
# Main entry point
async def main():
    try:
        server = await start()
        server.num_cancels = 0
        await server.serve_forever()
    except asyncio.CancelledError:
        pass 
```

Notably, when it starts, it creates an asyncio server (`ProxhyServer` here is just an asyncio server with another attribute added).

```py
async def start(host: str = "localhost", port: int = 41223) -> ProxhyServer:
    server = await asyncio.start_server(handle_client, host, port)
    server = ProxhyServer(server)

    print(f"Started proxhy on {host}:{port}")

    return server
```

Note that the server is started with `handle_client` as a callback function:
```py
async def handle_client(reader: StreamReader, writer: StreamWriter):
    instances.append(Proxhy(reader, writer))
```

An instance of `Proxhy` is then created, and the code hands off the client connection to the `Proxhy` class, which is what ultimately drives the rest of the connection throughout a player's session. 

Also note that multiple instances are supported--this is mainly so that custom clients like Lunar Client can create new connections for things like ping checking in the background while the player is playing. In this case, a new `Proxhy` class is created temporarily to handle those connections, which is separate from the main player connection.