import json
from importlib.resources import files


def load_json_asset(filename: str):
    with files("assets").joinpath(filename).open("r", encoding="utf-8") as f:
        return json.load(f)
