The [mcmodels.py](../proxhy/mcmodels.py) file provides miscellaneous models for Minecraft protocol or Hypixel-specific concepts.

```py
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
```

```py
@dataclass
class Game:
    server: str = ""
    gametype: str = ""
    mode: str = ""
    map: str = ""
    lobbyname: str = ""
```

```py
@dataclass
class Pos:
    """integer block position"""

    x: int = 0
    y: int = 0
    z: int = 0
```

```py
@dataclass
class Nick:
    """nicknamed player on Hypixel"""
    name: str
    uuid: str = field(init=False)
```
