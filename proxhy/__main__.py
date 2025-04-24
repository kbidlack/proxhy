import asyncio
import signal  # noqa
import sys
from asyncio import StreamReader, StreamWriter

from .proxhy import Proxhy

instances: list[Proxhy] = []


async def handle_client(reader: StreamReader, writer: StreamWriter):
    instances.append(Proxhy(reader, writer))


async def start(host: str = "localhost", port: int = 41223) -> asyncio.Server:
    server = await asyncio.start_server(handle_client, host, port)
    print(f"Started proxhy on {host}:{port}")

    return server


# Function to handle graceful shutdown
async def shutdown(loop: asyncio.AbstractEventLoop, server: asyncio.Server, _):
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
