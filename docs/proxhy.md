The proxhy file contains the main `Proxhy` class that inherits from `proxy.Proxy`. The `Proxhy` class contains all the code necessary for any Proxhy-specific features that are used when playing on `Proxhy`.

### Adding New Commands
1. Create method with `@command` decorator
2. Use proper type hints for parameter validation
3. Raise `CommandException` for user-friendly errors
4. Return `TextComponent` or string for output

```python
@command
def add(self, a: int, b: int) -> int:
    return a + b

@command("hello")
def greet(self, user: str) -> str:
    return f"Hello, {user}!"
```

You can add aliases as parameters to `command` so the command can be run, for example, hello can be run as `/greet` or `/hello`.

You can then use `/greet Alice` or `/add 2 3` in chat to invoke these commands.

### Extending Packet Handling
Use `@listen_client` or `@listen_server` decorators

```python
@listen_client(State.PLAY, 0x0F)  # Listen for packet ID 0x0F in the "play" state from the client
def on_client_chat(self, packet):
    # idk what packet 0x0F is but this is just an example
    print(f"Client sent chat: {packet['message']}")

@listen_server(State.LOGIN, 0x02)  # Listen for packet ID 0x02 in the "login" state from the server
def on_server_login_success(self, packet):
    print("Login successful!")
```