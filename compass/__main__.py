import argparse
import asyncio
import random
import signal
import sys

import pyroh
from aiohttp import web

from .server import CompassServer

parser = argparse.ArgumentParser(prog="compass")
parser.add_argument("-k", "--keyfile")
parser.add_argument("-p", "--http-port", type=int, default=None)
args = parser.parse_args()

routes = web.RouteTableDef()


async def wait_for_ctrl_c():
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    loop.add_signal_handler(signal.SIGINT, future.set_result, None)
    await future

    print("Exiting...")


async def main():
    server = CompassServer()

    if args.keyfile is None:
        key_bytes = random.randbytes(32)
        print("No keyfile was specified! Using a dynamically generated key")
    else:
        try:
            with open(args.keyfile, "rb") as file:
                key_bytes = file.read()
                if len(key_bytes) != 32:
                    return f"Key file {args.keyfile} contains invalid data!"
        except OSError as e:
            return f"Failed to open key file at {args.keyfile}: {e}"

    key = pyroh.SecretKey.from_bytes(key_bytes)

    endpoint = await pyroh.Endpoint.bind(
        key=key,
        alpns=[b"compass/1"],
    )

    app = web.Application()

    async def ticket_handler(request):
        ticket = endpoint.ticket
        return web.Response(text=ticket)

    app.router.add_get("/ticket", ticket_handler)

    runner = None

    if args.http_port:
        runner = web.AppRunner(app)
        await runner.setup()

        site = web.TCPSite(
            runner,
            "0.0.0.0",
            args.http_port,
        )

        await site.start()

        print(
            f"Server is online at {endpoint.id} "
            f"and HTTP server is live on port {args.http_port}"
        )
    else:
        print(f"Server is online at {endpoint.id}")

    # tokio::select! type thing
    task1 = asyncio.create_task(server.run_endpoint(endpoint))
    task2 = asyncio.create_task(wait_for_ctrl_c())

    done, pending = await asyncio.wait(
        [task1, task2],
        return_when=asyncio.FIRST_COMPLETED,
    )

    for task in pending:
        task.cancel()

    if runner is not None:
        await runner.cleanup()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
