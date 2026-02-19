import argparse
import asyncio
import errno
import platform
import signal
import sys
from asyncio import StreamReader, StreamWriter

import pyroh

import auth
from core.proxy import Proxy
from proxhy.proxhy import Proxhy

if platform.system() == "Windows":
    import winloop as loop_impl
else:
    import uvloop as loop_impl

loop_impl.install()

instances: list[Proxy] = []

auth.set_client_id("6dd7ede8-1d77-4fff-a7ea-6e07c09d6163")


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
        help="Enable developer mode",
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
    args.dev = True
    args.port = 41224
else:
    args.dev = False

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
        connect_host=(args.remote_host, args.remote_port),
        autostart=False,
        fake_connect_host=(args.fake_host, args.fake_port),
        dev_mode=args.dev,
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
    try:
        server = await asyncio.start_server(handle_client, host, port)
    except OSError as e:
        if (e.errno == errno.EADDRINUSE) or (getattr(e, "winerror", None) == 10048):
            print(
                f"Error: could not bind to {host}:{port}. "
                "(Do you already have another instance of Proxhy running?)",
                sep="\n",
            )
            sys.exit(1)
        raise

    server = ProxhyServer(server)

    print(
        f"Started proxhy on {host}:{port} -> {args.remote_host}:{args.remote_port} ({args.fake_host}:{args.fake_port})"
    )
    if args.dev:
        print("==> DEV MODE ACTIVATED <==")

    return server


async def shutdown(loop: asyncio.AbstractEventLoop, server: ProxhyServer, _):
    """Handle graceful shutdown with force option on second interrupt."""
    server.num_cancels += 1

    if server.num_cancels > 1:
        print("\nForcing shutdown...", end=" ", flush=True)
        close_tasks = [instance.close(force=True) for instance in instances]
        if close_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*close_tasks, return_exceptions=True),
                    timeout=1.0,
                )
            except asyncio.TimeoutError:
                pass  # continue anyway

        pending = [
            t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()
        ]
        for task in pending:
            task.cancel()

        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        print("done!")
        loop.stop()
        return

    if instances:
        logged_in_instances = []
        non_logged_in_instances = []
        for i, instance in enumerate(instances):
            if getattr(instance, "logged_in", False):
                logged_in_instances.append(instance)
            else:
                non_logged_in_instances.append(instance)

        # force non logged in instances to close immediately
        # these are ones probably just created to check server status
        # TODO: time these out so we don't always have to close them here?
        # ^ and so that they don't clutter the instances list
        if non_logged_in_instances:
            print(
                f"\nClosing {len(non_logged_in_instances)} non-logged-in connection(s)..."
            )
            await asyncio.gather(
                *(inst.close(force=True) for inst in non_logged_in_instances),
                return_exceptions=True,
            )

        if logged_in_instances:
            print(f"Waiting for {len(logged_in_instances)} client(s) to disconnect...")

            instance_info = []
            for i, instance in enumerate(logged_in_instances):
                username = getattr(instance, "username", None) or f"instance_{i}"
                pending_tasks = [
                    attr
                    for attr in dir(instance)
                    if isinstance(getattr(instance, attr, None), asyncio.Task)
                    and not getattr(instance, attr).done()
                ]
                instance_info.append((instance, username, pending_tasks))
                print(
                    f"  - {username} (open={instance.open}, closed={instance.closed.is_set()})"
                )
                if pending_tasks:
                    print(f"    Pending tasks: {pending_tasks}")

            async def wait_for_disconnect(instance, username):
                await instance.closed.wait()
                print(f"  - {username} disconnected!")

            print("Waiting...")
            await asyncio.gather(
                *(wait_for_disconnect(inst, uname) for inst, uname, _ in instance_info)
            )

            # only print if not interrupted by forced shutdown
            if server.num_cancels == 1:
                print("All clients disconnected!")
    else:
        print("Shutting down...", end=" ", flush=True)
        server.close()
        await server.wait_closed()
        print("done!")

    loop.stop()


# Main entry point
async def _main():
    pyroh.setup_event_loop()

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
