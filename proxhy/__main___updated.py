"""Updated main entry point with backward compatibility and new framework support."""
import argparse
import asyncio
import os
import signal
import sys
from asyncio import StreamReader, StreamWriter
from importlib import import_module
from pathlib import Path

# Add option to use new or old architecture
USE_NEW_FRAMEWORK = os.environ.get("PROXHY_USE_NEW_FRAMEWORK", "false").lower() == "true"

if USE_NEW_FRAMEWORK:
    print("🚀 Using new framework architecture")
    from .core import ProxhyFrameworkFactory, plugin_loader, plugin_registry
    
    instances: list = []
    factory = None
    
    async def setup_new_framework():
        global factory
        # Setup plugin loader
        current_dir = Path(__file__).parent
        plugins_dir = current_dir / "plugins"
        plugin_loader.add_plugin_directory(str(plugins_dir))
        
        # Register plugins
        registered = plugin_loader.register_discovered_plugins()
        print(f"Registered plugins: {registered}")
        
        # Create factory
        factory = ProxhyFrameworkFactory(plugin_registry)
        return factory

else:
    print("🔧 Using legacy architecture with compatibility bridge")
    from .legacy_bridge import Proxhy
    from .ext import _methods
    
    instances: list[Proxhy] = []

    # Load legacy extensions
    for ext in os.listdir(Path(os.path.dirname(__file__)) / "ext"):
        if ext.startswith("_") or ext[-3:] != ".py":
            continue
        try:
            import_module(f"proxhy.ext.{ext[:-3]}", package="proxhy.ext")
        except ImportError as e:
            print(f"Warning: Could not load legacy extension {ext}: {e}")

    # Load methods into Proxhy class
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
    parser.add_argument(
        "--framework",
        action="store_true",
        help="Use new framework architecture (can also set PROXHY_USE_NEW_FRAMEWORK=true)",
    )
    parser.add_argument(
        "--plugins",
        nargs="*",
        default=["gamestate", "statistics", "commands"],
        help="Plugins to load (new framework only)",
    )
    return parser.parse_args()


args = parse_args()

# Override framework setting from command line
if args.framework:
    USE_NEW_FRAMEWORK = True

if args.dev:
    args.remote_host = "localhost"
    args.remote_port = 25565

if not args.fake_host:
    args.fake_host = args.remote_host

if args.fake_port == -1:
    args.fake_port = args.remote_port


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


async def handle_client_new_framework(reader: StreamReader, writer: StreamWriter):
    """Handle client connection with new framework."""
    global factory, instances
    
    instance = factory.create_instance(
        reader,
        writer,
        connect_host=(
            args.remote_host,
            args.remote_port,
            args.fake_host,
            args.fake_port,
        ),
        plugins=args.plugins
    )
    
    instances.append(instance)
    await instance.start()


async def handle_client_legacy(reader: StreamReader, writer: StreamWriter):
    """Handle client connection with legacy architecture."""
    instances.append(
        Proxhy(
            reader,
            writer,
            connect_host=(
                args.remote_host,
                args.remote_port,
                args.fake_host,
                args.fake_port,
            ),
        )
    )


async def start(host: str = "localhost", port: int = 41223) -> ProxhyServer:
    """Start the proxy server."""
    if USE_NEW_FRAMEWORK:
        global factory
        factory = await setup_new_framework()
        handler = handle_client_new_framework
        arch_info = "Framework"
    else:
        handler = handle_client_legacy  
        arch_info = "Legacy"
    
    server = await asyncio.start_server(handler, host, port)
    server = ProxhyServer(server)

    print(f"Started Proxhy ({arch_info}) on {host}:{port} -> {args.remote_host}:{args.remote_port} ({args.fake_host}:{args.fake_port})")

    return server


async def shutdown(loop: asyncio.AbstractEventLoop, server: ProxhyServer, _):
    """Handle graceful shutdown."""
    server.num_cancels += 1

    if server.num_cancels > 1:
        # Force shutdown
        if USE_NEW_FRAMEWORK:
            global factory
            if factory:
                await factory.shutdown_all()
        else:
            for instance in instances:
                await instance.close()
        loop.stop()
    elif server.num_cancels <= 1:
        # Graceful shutdown
        if instances:
            print("\\nWaiting for all clients to disconnect...", end="")
            server.close()
            await server.wait_closed()
            print("done!")
        else:
            server.close()
            await server.wait_closed()


async def _main():
    """Main application loop."""
    try:
        server = await start(
            host="localhost",
            port=args.port,
        )
        server.num_cancels = 0
        await server.serve_forever()
    except asyncio.CancelledError:
        pass


def main():
    """Entry point."""
    try:
        asyncio.run(_main())
    except RuntimeError:
        sys.exit()


if __name__ == "__main__":
    main()