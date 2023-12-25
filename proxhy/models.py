from dataclasses import dataclass


@dataclass
class Game:
    server: str = ""
    gametype: str = ""
    mode: str = ""
    map: str = ""
    lobbyname: str = ""

    def __setattr__(self, name: str, value) -> None:
        if isinstance(value, str):
            super().__setattr__(name.casefold(), value.casefold())
        else:
            super().__setattr__(name, value)

    def update(self, data: dict):
        for key, value in data.items():
            setattr(self, key, value)
