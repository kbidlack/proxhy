from dataclasses import dataclass


@dataclass
class Team:
    name: str
    display_name: str
    prefix: str
    suffix: str
    friendly_fire: int
    name_tag_visibility: str
    color: int
    players: set[str]


class Teams(list):
    def __getitem__(self, key) -> Team:
        return next((team for team in self if team.name == key), None)

    def __delitem__(self, key):
        team = self[key]
        if team:
            self.remove(team)


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
        # reset
        self.server = ""
        self.gametype = ""
        self.mode = ""
        self.map = ""
        self.lobbyname = ""

        for key, value in data.items():
            setattr(self, key, value)
