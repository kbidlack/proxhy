import asyncio
import sys
from asyncio import StreamReader, StreamWriter

from .auth import load_auth_info
from .proxy import ProxyClient


async def handle_client(reader: StreamReader, writer: StreamWriter):
    ProxyClient(reader, writer)


async def main():
    await load_auth_info()
    server = await asyncio.start_server(handle_client, "localhost", 13876)

    print("Started proxhy!")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit()
