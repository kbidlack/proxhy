from importlib.resources import files

import orjson


def load_json_asset(filename: str):
    with files("assets").joinpath(filename).open("rb") as f:
        return orjson.loads(f.read())
