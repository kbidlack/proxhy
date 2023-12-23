import asyncio
import sys
from asyncio import StreamReader, StreamWriter

from auth import load_auth_info
from proxy import ProxyClient


async def handle_client(
    reader: StreamReader,
    writer: StreamWriter,
    access_token: str,
    uuid: str,
    username: str,
):
    access_token, uuid, username = await load_auth_info()
    ProxyClient(reader, writer, access_token, uuid, username)


async def main():
    access_token, uuid, username = await load_auth_info()
    server = await asyncio.start_server(
        lambda r, w: handle_client(r, w, access_token, uuid, username),
        "localhost",
        13876,
    )

    print("Started proxhy!")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit()
