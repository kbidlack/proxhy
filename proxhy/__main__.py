import asyncio
import signal  # noqa
import sys
from asyncio import StreamReader, StreamWriter

from .proxhy import Proxhy

instances: list[Proxhy] = []


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
    instances.append(Proxhy(reader, writer))


async def start(host: str = "localhost", port: int = 41223) -> ProxhyServer:
    server = await asyncio.start_server(handle_client, host, port)
    server = ProxhyServer(server)

    print(f"Started proxhy on {host}:{port}")

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
        server = await start()
        server.num_cancels = 0
        await server.serve_forever()
    except asyncio.CancelledError:
        pass  # hehe


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError:  # forced shutdown
        sys.exit()
