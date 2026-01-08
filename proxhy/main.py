import argparse
import asyncio
import platform
import signal
import sys
from asyncio import StreamReader, StreamWriter

from core.proxy import Proxy
from proxhy.proxhy import Proxhy

if platform.system() == "Windows":
    import winloop as loop_impl
else:
    import uvloop as loop_impl

loop_impl.install()

instances: list[Proxy] = []


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
        "--local",
        action="store_true",
        help="Shorthand to bind remote to localhost:25565 for development",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Shorthand to bind proxhy to localhost:41224 to develop on a separate instance",
    )
    parser.add_argument(
        "-fh",
        "--fake-host",
        default="",
        help="Host to send to the server as what the client is connecting to (default: remote_host)",
    )
    parser.add_argument(
        "-fp",
        "--fake-port",
        type=int,
        default=-1,
        help="Port to send to the server as what the client is connecting to (default: remote_port)",
    )
    return parser.parse_args()


args = parse_args()  # ew

if args.local:
    args.remote_host = "localhost"
    args.remote_port = 25565

if args.dev:
    args.port = 41224

if not args.fake_host:
    args.fake_host = args.remote_host

if args.fake_port == -1:
    args.fake_port = args.remote_port


class ProxhyServer:
    """A custom server class that tracks the number of cancels."""

    __slots__ = ("_srv", "num_cancels")
    num_cancels: int

    def __init__(self, srv: asyncio.Server) -> None:
        self._srv = srv
        self.num_cancels = 0

    def close(self):
        return self._srv.close()

    def wait_closed(self):
        return self._srv.wait_closed()

    async def serve_forever(self):
        return await self._srv.serve_forever()

    def __getattr__(self, name: str):
        # delegate everything else back to the real server
        return getattr(self._srv, name)


async def handle_client(reader: StreamReader, writer: StreamWriter):
    proxy = Proxhy(
        reader,
        writer,
        connect_host=(
            args.remote_host,
            args.remote_port,
            args.fake_host,
            args.fake_port,
        ),
        autostart=False,
    )
    instances.append(proxy)

    while proxy:
        next_proxy = await proxy.run()
        if next_proxy:
            try:
                idx = instances.index(proxy)
                instances[idx] = next_proxy
            except ValueError:
                instances.append(next_proxy)
            proxy = next_proxy
        else:
            try:
                instances.remove(proxy)
            except ValueError:
                pass
            proxy = None


async def start(host: str = "localhost", port: int = 41223) -> ProxhyServer:
    server = await asyncio.start_server(handle_client, host, port)
    server = ProxhyServer(server)

    print(
        f"Started proxhy on {host}:{port} -> {args.remote_host}:{args.remote_port} ({args.fake_host}:{args.fake_port})"
    )

    return server


async def shutdown(loop: asyncio.AbstractEventLoop, server: ProxhyServer, _):
    """Handle graceful shutdown with force option on second interrupt."""
    server.num_cancels += 1

    if server.num_cancels > 1:
        print("\nForcing shutdown...", end=" ", flush=True)
        for instance in instances:
            try:
                await instance.close()
            except Exception as e:
                print(f"Error while trying to close instance: {e}")
        print("done!")
        loop.stop()
        return

    if instances:
        print("Waiting for all clients to disconnect...", end="", flush=True)
        for instance in instances:
            await instance.closed.wait()
        # only print if not interrupted by forced shutdown
        if server.num_cancels == 1:
            print("done!")
    else:
        print("Shutting down...", end=" ", flush=True)
        server.close()
        await server.wait_closed()
        print("done!")

    loop.stop()


# Main entry point
async def _main():
    # Start server first so the signal handler can reference it safely
    server = await start(
        host="localhost",
        port=args.port,
    )
    server.num_cancels = 0

    loop = asyncio.get_running_loop()

    # Cross-platform SIGINT handling: use loop.add_signal_handler where supported;
    # on Windows, fall back to signal.signal + loop.call_soon_threadsafe.
    def _on_sigint():
        asyncio.create_task(shutdown(loop, server, signal.SIGINT))

    try:
        try:
            loop.add_signal_handler(signal.SIGINT, _on_sigint)
        except (NotImplementedError, AttributeError):
            # Windows / event loops without add_signal_handler
            signal.signal(
                signal.SIGINT,
                lambda s, f: loop.call_soon_threadsafe(_on_sigint),
            )

        await server.serve_forever()
    except asyncio.CancelledError:
        pass  # hehe


def main():
    try:
        asyncio.run(_main())
    except RuntimeError:  # forced shutdown
        sys.exit()


if __name__ == "__main__":
    main()
