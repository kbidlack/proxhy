import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "DEFAULT_LUNAR_ACCOUNTS_PATH",
    "DEFAULT_VANILLA_ACCOUNTS_PATH",
    "DEFAULT_IAS_ACCOUNTS_PATH",
    "Session",
    "SelectedProfile",
    "ProfileHint",
    "MinecraftProfile",
    "load_account_source_session",
    "load_account_source_profile_hint_sync",
    "load_launcher_json_session",
    "load_lunar_active_session",
    "load_launcher_json_session_sync",
    "count_source_accounts",
    "find_launcher_account_session",
    "summarize_account_sources",
    "resolve_preset_default_path",
]


_HOME = Path.home()
_PLATFORM = sys.platform  # "win32", "darwin", "linux", ...


def _from_home(*segments: str) -> Path:
    return _HOME.joinpath(*segments)


def _first_existing_path(candidates, fallback: Path) -> Path:
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return Path(candidate)
    return fallback


def _lunar_accounts_candidates() -> list[Path]:
    candidates = [_from_home(".lunarclient", "settings", "game", "accounts.json")]

    if _PLATFORM == "darwin":
        candidates.insert(
            0,
            _from_home(
                "Library",
                "Application Support",
                "lunarclient",
                "settings",
                "game",
                "accounts.json",
            ),
        )

    return candidates


def _vanilla_accounts_candidates() -> list[Path]:
    if _PLATFORM == "darwin":
        base = _from_home("Library", "Application Support", "minecraft")
        return [
            base / "launcher_accounts.json",
            base / "launcher_accounts_microsoft_store.json",
        ]

    if _PLATFORM == "win32":
        base = _from_home("AppData", "Roaming", ".minecraft")
        return [
            base / "launcher_accounts.json",
            base / "launcher_accounts_microsoft_store.json",
        ]

    base = _from_home(".minecraft")
    return [
        base / "launcher_accounts.json",
        base / "launcher_accounts_microsoft_store.json",
    ]


def _ias_accounts_candidates() -> list[Path]:
    if _PLATFORM == "darwin":
        return [
            _from_home(
                "Library", "Application Support", "minecraft", "config", "ias.json"
            )
        ]

    if _PLATFORM == "win32":
        return [_from_home("AppData", "Roaming", ".minecraft", "config", "ias.json")]

    return [_from_home(".minecraft", "config", "ias.json")]


DEFAULT_LUNAR_ACCOUNTS_PATH = _first_existing_path(
    _lunar_accounts_candidates(), _lunar_accounts_candidates()[0]
)
DEFAULT_VANILLA_ACCOUNTS_PATH = _first_existing_path(
    _vanilla_accounts_candidates(), _vanilla_accounts_candidates()[0]
)
DEFAULT_IAS_ACCOUNTS_PATH = _first_existing_path(
    _ias_accounts_candidates(), _ias_accounts_candidates()[0]
)


# ============================================================================
# Data structures
# ============================================================================


@dataclass
class SelectedProfile:
    id: str  # undashed UUID
    name: str


@dataclass
class Session:
    username: str
    access_token_expires_at: object  # str | int | None (launcher-dependent)
    session: "SessionInner"


@dataclass
class SessionInner:
    access_token: str
    selected_profile: SelectedProfile


@dataclass
class MinecraftProfile:
    id: str  # undashed UUID
    name: str


@dataclass
class ProfileHint:
    username: str
    minecraft_profile: MinecraftProfile


# ============================================================================
# Parsing / account selection
# ============================================================================


def _undash_uuid(value) -> str:
    return str("" if value is None else value).replace("-", "")


def _parse_json_file(raw: str, error_prefix: str):
    import json

    try:
        return json.loads(raw)
    except ValueError as error:
        raise ValueError(f"{error_prefix}: {error}") from error


def _detect_json_parser(parsed) -> str:
    if isinstance(parsed, dict) and parsed.get("accounts") and parsed.get(
        "activeAccountLocalId"
    ):
        return "launcher-json"

    if (
        isinstance(parsed, dict)
        and isinstance(parsed.get("accounts"), list)
        and "version" in parsed
    ):
        return "ias-json"

    raise ValueError("Unsupported account JSON format")


def _select_launcher_account(parsed):
    active_account_local_id = parsed.get("activeAccountLocalId")
    if not active_account_local_id:
        raise ValueError("Launcher accounts file does not define activeAccountLocalId")

    account = (parsed.get("accounts") or {}).get(active_account_local_id)
    if not account:
        raise ValueError(
            f"Launcher active account {active_account_local_id} not found"
        )

    profile = account.get("minecraftProfile") or {}
    if not profile.get("id") or not profile.get("name"):
        raise ValueError(
            "Launcher active account is missing minecraftProfile.id or "
            "minecraftProfile.name"
        )

    return account


def _select_ias_account(parsed, options: dict | None = None):
    options = options or {}
    preferred_username = str(options.get("preferred_username") or "").strip().lower()
    accounts = parsed.get("accounts") or []

    def _name_matches(entry) -> bool:
        return str(entry.get("name") or "").strip().lower() == preferred_username

    if preferred_username:
        matching = next(
            (
                entry
                for entry in accounts
                if entry.get("isValid")
                and entry.get("accessToken")
                and entry.get("uuid")
                and _name_matches(entry)
            ),
            None,
        ) or next(
            (
                entry
                for entry in accounts
                if entry.get("accessToken")
                and entry.get("uuid")
                and _name_matches(entry)
            ),
            None,
        )

        if matching:
            return matching

    account = next(
        (
            entry
            for entry in accounts
            if entry.get("isValid")
            and entry.get("accessToken")
            and entry.get("uuid")
            and entry.get("name")
        ),
        None,
    ) or next(
        (
            entry
            for entry in accounts
            if entry.get("accessToken") and entry.get("uuid") and entry.get("name")
        ),
        None,
    )

    if not account:
        raise ValueError("IAS config does not contain a usable account")

    return account


# ============================================================================
# Session / profile-hint builders
# ============================================================================


def _build_launcher_session(account) -> Session:
    if not account.get("accessToken"):
        raise ValueError("Launcher active account has no accessToken")

    profile = account["minecraftProfile"]
    return Session(
        username=account.get("username"),
        access_token_expires_at=account.get("accessTokenExpiresAt"),
        session=SessionInner(
            access_token=account["accessToken"],
            selected_profile=SelectedProfile(
                id=_undash_uuid(profile["id"]),
                name=profile["name"],
            ),
        ),
    )


def _build_ias_session(account) -> Session:
    return Session(
        username=account.get("name"),
        access_token_expires_at=None,
        session=SessionInner(
            access_token=account["accessToken"],
            selected_profile=SelectedProfile(
                id=_undash_uuid(account["uuid"]),
                name=account["name"],
            ),
        ),
    )


def _build_launcher_profile_hint(account) -> ProfileHint:
    profile = account["minecraftProfile"]
    return ProfileHint(
        username=account.get("username"),
        minecraft_profile=MinecraftProfile(
            id=_undash_uuid(profile["id"]),
            name=profile["name"],
        ),
    )


def _build_ias_profile_hint(account) -> ProfileHint:
    return ProfileHint(
        username=account.get("name"),
        minecraft_profile=MinecraftProfile(
            id=_undash_uuid(account["uuid"]),
            name=account["name"],
        ),
    )


def _load_account_source_json(raw: str, parser: str = "auto-json", options=None):
    parsed = _parse_json_file(raw, "Failed to parse account source JSON")
    selected_parser = _detect_json_parser(parsed) if parser == "auto-json" else parser

    if selected_parser == "launcher-json":
        return selected_parser, parsed, _select_launcher_account(parsed)

    if selected_parser == "ias-json":
        return selected_parser, parsed, _select_ias_account(parsed, options)

    raise ValueError(f"Unsupported account source parser {selected_parser}")


def _default_path_for_parser(parser: str) -> Path:
    if parser == "ias-json":
        return DEFAULT_IAS_ACCOUNTS_PATH
    return DEFAULT_LUNAR_ACCOUNTS_PATH


def _resolve_vanilla_accounts_path(
    preferred_path: Path | str = DEFAULT_VANILLA_ACCOUNTS_PATH,
) -> Path:
    return _first_existing_path(
        [preferred_path, *_vanilla_accounts_candidates()], Path(preferred_path)
    )


# ============================================================================
# Public API
# ============================================================================


async def load_account_source_session(
    accounts_path: Path | str | None = None,
    parser: str = "auto-json",
    options: dict | None = None,
) -> Session:
    """Asynchronously read an account file and return a usable session."""
    path = Path(accounts_path) if accounts_path else _default_path_for_parser(parser)
    raw = await asyncio.to_thread(path.read_text, "utf-8")
    selected_parser, _parsed, account = _load_account_source_json(raw, parser, options)

    if selected_parser == "launcher-json":
        return _build_launcher_session(account)

    if selected_parser == "ias-json":
        return _build_ias_session(account)

    raise ValueError(f"Unsupported account source parser {selected_parser}")


def load_account_source_profile_hint_sync(
    accounts_path: Path | str | None = None,
    parser: str = "auto-json",
    options: dict | None = None,
) -> ProfileHint:
    """Synchronously read an account file and return only its profile hint."""
    path = Path(accounts_path) if accounts_path else _default_path_for_parser(parser)
    raw = path.read_text("utf-8")
    selected_parser, _parsed, account = _load_account_source_json(raw, parser, options)

    if selected_parser == "launcher-json":
        return _build_launcher_profile_hint(account)

    if selected_parser == "ias-json":
        return _build_ias_profile_hint(account)

    raise ValueError(f"Unsupported account source parser {selected_parser}")


async def load_launcher_json_session(
    accounts_path: Path | str = DEFAULT_LUNAR_ACCOUNTS_PATH,
) -> Session:
    return await load_account_source_session(accounts_path, "launcher-json")


async def load_lunar_active_session(
    accounts_path: Path | str = DEFAULT_LUNAR_ACCOUNTS_PATH,
) -> Session:
    return await load_launcher_json_session(accounts_path)


def load_launcher_json_session_sync(
    accounts_path: Path | str = DEFAULT_LUNAR_ACCOUNTS_PATH,
) -> ProfileHint:
    return load_account_source_profile_hint_sync(accounts_path, "launcher-json")


def count_source_accounts(
    accounts_path: Path | str, parser: str = "auto-json"
) -> int:
    """Return how many usable accounts an account file contains.

    - ``launcher-json`` files store accounts in a mapping; each entry with a
      ``minecraftProfile`` (id + name) is counted.
    - ``ias-json`` files store accounts in a list; each entry with a token,
      uuid and name is counted.

    Raises ``FileNotFoundError`` if the file is missing and ``ValueError`` if it
    cannot be parsed.
    """
    raw = Path(accounts_path).read_text("utf-8")
    parsed = _parse_json_file(raw, "Failed to parse account source JSON")
    selected_parser = _detect_json_parser(parsed) if parser == "auto-json" else parser

    if selected_parser == "launcher-json":
        accounts = parsed.get("accounts") or {}
        return sum(
            1
            for account in accounts.values()
            if (account.get("minecraftProfile") or {}).get("id")
            and (account.get("minecraftProfile") or {}).get("name")
        )

    if selected_parser == "ias-json":
        accounts = parsed.get("accounts") or []
        return sum(
            1
            for entry in accounts
            if entry.get("accessToken") and entry.get("uuid") and entry.get("name")
        )

    raise ValueError(f"Unsupported account source parser {selected_parser}")


def find_launcher_account_session(username: str) -> tuple[str, Session] | None:
    """Find an already-authenticated session for ``username`` in any launcher.

    Scans every supported preset's default account file (Lunar, vanilla
    launcher, IAS) for an account whose profile name matches ``username``
    (case-insensitive) and that carries a usable access token. Returns a
    ``(source_id, Session)`` tuple, or ``None`` if no match is found.
    """
    from mcauth.account_sources import ACCOUNT_SOURCE_PRESETS

    target = str(username or "").strip().lower()
    if not target:
        return None

    for preset in ACCOUNT_SOURCE_PRESETS:
        if not preset.supported or not preset.default_path:
            continue

        path = Path(preset.default_path)
        if not path.exists():
            continue

        try:
            parsed = _parse_json_file(
                path.read_text("utf-8"), "Failed to parse account source JSON"
            )
            parser = (
                _detect_json_parser(parsed)
                if preset.parser == "auto-json"
                else preset.parser
            )
        except (ValueError, OSError):
            continue

        if parser == "launcher-json":
            for account in (parsed.get("accounts") or {}).values():
                profile = account.get("minecraftProfile") or {}
                name = str(profile.get("name") or "").strip().lower()
                if name == target and account.get("accessToken") and profile.get("id"):
                    return preset.id, _build_launcher_session(account)

        elif parser == "ias-json":
            for entry in parsed.get("accounts") or []:
                name = str(entry.get("name") or "").strip().lower()
                if (
                    name == target
                    and entry.get("accessToken")
                    and entry.get("uuid")
                ):
                    return preset.id, _build_ias_session(entry)

    return None


def summarize_account_sources() -> list[dict]:
    """Scan every supported preset's default location and count its accounts.

    Returns one dict per supported source with keys ``id``, ``label``,
    ``path``, ``count`` and ``error`` (``None`` on success). Sources whose file
    does not exist are reported with ``count == 0`` and ``error == "not found"``.
    """
    from mcauth.account_sources import ACCOUNT_SOURCE_PRESETS

    summary = []
    for preset in ACCOUNT_SOURCE_PRESETS:
        if not preset.supported or not preset.default_path:
            continue

        path = Path(preset.default_path)
        entry = {
            "id": preset.id,
            "label": preset.label,
            "path": str(path),
            "count": 0,
            "error": None,
        }

        if not path.exists():
            entry["error"] = "not found"
        else:
            try:
                entry["count"] = count_source_accounts(path, preset.parser)
            except (ValueError, OSError) as error:
                entry["error"] = str(error)

        summary.append(entry)

    return summary


def resolve_preset_default_path(source_id: str, fallback_path: str | Path = "") -> Path | str:
    if source_id == "vanilla":
        return _resolve_vanilla_accounts_path(
            fallback_path or DEFAULT_VANILLA_ACCOUNTS_PATH
        )

    if source_id == "ias":
        return DEFAULT_IAS_ACCOUNTS_PATH

    if source_id == "lunar":
        return DEFAULT_LUNAR_ACCOUNTS_PATH

    return fallback_path
