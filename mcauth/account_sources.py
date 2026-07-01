import sys
from dataclasses import dataclass
from pathlib import Path

from mcauth.session_loader import (
    DEFAULT_IAS_ACCOUNTS_PATH,
    DEFAULT_LUNAR_ACCOUNTS_PATH,
    DEFAULT_VANILLA_ACCOUNTS_PATH,
    resolve_preset_default_path,
)

__all__ = [
    "AccountSourcePreset",
    "ACCOUNT_SOURCE_PRESETS",
    "get_account_source_preset",
]


_HOME = Path.home()
_PLATFORM = sys.platform


def _minecraft_root() -> Path:
    if _PLATFORM == "darwin":
        return _HOME / "Library" / "Application Support" / "minecraft"

    if _PLATFORM == "win32":
        return _HOME / "AppData" / "Roaming" / ".minecraft"

    return _HOME / ".minecraft"


@dataclass(frozen=True)
class AccountSourcePreset:
    id: str
    label: str
    parser: str
    supported: bool
    default_path: str | Path


ACCOUNT_SOURCE_PRESETS: list[AccountSourcePreset] = [
    AccountSourcePreset(
        id="lunar",
        label="Lunar Client",
        parser="launcher-json",
        supported=True,
        default_path=resolve_preset_default_path("lunar", DEFAULT_LUNAR_ACCOUNTS_PATH),
    ),
    AccountSourcePreset(
        id="vanilla",
        label="Minecraft Launcher",
        parser="launcher-json",
        supported=True,
        default_path=resolve_preset_default_path(
            "vanilla", DEFAULT_VANILLA_ACCOUNTS_PATH
        ),
    ),
    AccountSourcePreset(
        id="ias",
        label="In-Game Account Switcher",
        parser="ias-json",
        supported=True,
        default_path=resolve_preset_default_path("ias", DEFAULT_IAS_ACCOUNTS_PATH),
    ),
    AccountSourcePreset(
        id="labymod",
        label="LabyMod",
        parser="unsupported",
        supported=False,
        default_path=_minecraft_root() / "LabyMod" / "accounts.json",
    ),
    AccountSourcePreset(
        id="essential",
        label="Essential",
        parser="unsupported",
        supported=False,
        default_path=_minecraft_root() / "essential",
    ),
    AccountSourcePreset(
        id="custom",
        label="Custom",
        parser="auto-json",
        supported=True,
        default_path="",
    ),
]


def get_account_source_preset(source_id: str) -> AccountSourcePreset:
    return next(
        (source for source in ACCOUNT_SOURCE_PRESETS if source.id == source_id),
        ACCOUNT_SOURCE_PRESETS[0],
    )
