"""New main entry point using the framework architecture."""
import argparse
import asyncio
import signal
import sys
from asyncio import StreamReader, StreamWriter
from pathlib import Path

from proxhy.core import (
    ProxhyFrameworkFactory,
    plugin_loader,
    plugin_registry
)

# Global state
instances = []
factory = None


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
        "--plugins",
        nargs="*",
        default=["gamestate", "statistics", "commands"],
        help="Plugins to load (default: gamestate statistics commands)",
    )
    return parser.parse_args()


async def setup_plugins():
    """Setup and register plugins."""
    # Add plugin directories
    current_dir = Path(__file__).parent
    plugins_dir = current_dir / "plugins"
    plugin_loader.add_plugin_directory(str(plugins_dir))
    
    # Register plugins
    registered = plugin_loader.register_discovered_plugins()
    print(f"Registered plugins: {registered}")
    
    return registered


async def handle_client(reader: StreamReader, writer: StreamWriter):
    """Handle new client connection."""
    global factory, instances
    
    args = parse_args()  # Get args (in real implementation, pass this as parameter)
    
    # Create framework instance
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
    
    # Start the instance
    await instance.start()


async def start_server(host: str = "localhost", port: int = 41223):
    """Start the proxy server."""
    server = await asyncio.start_server(handle_client, host, port)
    
    args = parse_args()
    print(f"Started Proxhy Framework on {host}:{port} -> {args.remote_host}:{args.remote_port}")
    
    return server


async def shutdown_handler(signum=None):
    """Handle graceful shutdown."""
    global factory, instances
    
    print(f"\nReceived shutdown signal {signum if signum else ''}. Shutting down...")
    
    # Shutdown all instances
    if factory:
        await factory.shutdown_all()
    
    # Clear instances list
    instances.clear()
    
    # Stop the event loop
    loop = asyncio.get_running_loop()
    loop.stop()


async def main():
    """Main application entry point."""
    global factory
    
    try:
        # Parse arguments
        args = parse_args()
        
        if args.dev:
            args.remote_host = "localhost"
            args.remote_port = 25565
        
        if not args.fake_host:
            args.fake_host = args.remote_host
        
        if args.fake_port == -1:
            args.fake_port = args.remote_port
        
        # Setup plugins
        await setup_plugins()
        
        # Create framework factory
        factory = ProxhyFrameworkFactory(plugin_registry)
        
        # Setup signal handlers for graceful shutdown
        if sys.platform != "win32":  # Unix systems
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown_handler(s)))
        
        # Start server
        server = await start_server(host="localhost", port=args.port)
        
        # Serve forever
        await server.serve_forever()
        
    except KeyboardInterrupt:
        await shutdown_handler("KeyboardInterrupt")
    except Exception as e:
        print(f"Fatal error: {e}")
        await shutdown_handler("Exception")
    finally:
        print("Proxhy Framework shutdown complete.")


def run():
    """Entry point for the application."""
    try:
        asyncio.run(main())
    except RuntimeError:
        pass  # Expected on shutdown


if __name__ == "__main__":
    run()