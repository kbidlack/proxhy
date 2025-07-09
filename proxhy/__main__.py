import argparse
import asyncio
import os
import signal  # noqa
import sys
from asyncio import StreamReader, StreamWriter
from importlib import import_module
from pathlib import Path

from .ext import _methods
from .proxhy import Proxhy

instances: list[Proxhy] = []

# load proxhy extensions
for ext in os.listdir(Path(os.path.dirname(__file__)) / "ext"):
    if ext.startswith("_") or ext[-3:] != ".py":
        continue
    import_module(f"proxhy.ext.{ext[:-3]}", package="proxhy.ext")

# load methods -> Proxhy
for func in _methods.methods:
    setattr(Proxhy, func.__name__, func)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-rh",
        "--remote-host",
        default="mc.hypixel.net",
        help="Host to bind the server to (default: mc.hypixel.net)",
    )
    parser.add_argument(
        "-rp",
        "--remote-port",
        type=int,
        default=25565,
        help="Port to bind the server to (default: 25565)",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=41223,
        help="Port to bind the server to (default: 41223)",
    )
    parser.add_argument(
        "-d",
        "--dev",
        action="store_true",
        help="Shorthand to bind remote to localhost:25565 for development",
    )
    return parser.parse_args()


args = parse_args()  # ew

if args.dev:
    args.remote_host = "localhost"
    args.remote_port = 25565


class ProxhyServer(asyncio.Server):
    """A custom server class that tracks the number of cancels."""

    __slots__ = ("_srv", "num_cancels")
    num_cancels: int

    def __init__(self, srv: asyncio.Server) -> None:
        self._srv = srv
        self.num_cancels = 0

    def __getattr__(self, name: str):
        # delegate everything else back to the real server
        return getattr(self._srv, name)


async def handle_client(reader: StreamReader, writer: StreamWriter):
    instances.append(
        Proxhy(reader, writer, connect_host=(args.remote_host, args.remote_port))
    )


async def start(host: str = "localhost", port: int = 41223) -> ProxhyServer:
    server = await asyncio.start_server(handle_client, host, port)
    server = ProxhyServer(server)

    print(f"Started proxhy on {host}:{port} -> {args.remote_host}:{args.remote_port}")

    return server


# Function to handle graceful shutdown
async def shutdown(loop: asyncio.AbstractEventLoop, server: ProxhyServer, _):
    server.num_cancels += 1

    if server.num_cancels > 1:
        for instance in instances:
            await instance.close()
        loop.stop()
    elif server.num_cancels <= 1:
        if instances:
            print("\nWaiting for all clients to disconnect...", end="")
            # Close the server
            server.close()
            await server.wait_closed()
            print("done!")
        else:
            server.close()
            await server.wait_closed()


# Main entry point
async def main():
    # loop = asyncio.get_running_loop()
    # loop.add_signal_handler(
    #     signal.SIGINT,
    #     lambda: asyncio.create_task(shutdown(loop, server, signal.SIGINT)),
    # )
    # this doesn't work on windows
    # and i'm not going to fix it :D

    try:
        server = await start(
            host="localhost",
            port=args.port,
        )
        server.num_cancels = 0
        await server.serve_forever()
    except asyncio.CancelledError:
        pass  # hehe


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError:  # forced shutdown
        sys.exit()
