import asyncio
import sys
from asyncio import StreamReader, StreamWriter

from .auth import load_auth_info, users
from .proxy import Proxhy


async def handle_client(reader: StreamReader, writer: StreamWriter):
    Proxhy(reader, writer)


async def start():
    if len(sys.argv) < 2:
        sys.argv.append("")

    if sys.argv[1] == "login":
        await load_auth_info()
    elif opt := sys.argv[1]:
        print(f"Unknown option '{opt}'!")
        sys.exit()
    else:
        for user in users():
            await load_auth_info(user)

    server = await asyncio.start_server(handle_client, "localhost", 13876)

    print("Started proxhy!")
    async with server:
        await server.serve_forever()


def main():
    try:
        asyncio.run(start())
    except KeyboardInterrupt:
        sys.exit()


if __name__ == "__main__":
    main()
