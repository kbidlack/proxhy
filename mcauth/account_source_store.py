import inspect
import logging

from mcauth.account_sources import (
    ACCOUNT_SOURCE_PRESETS,
    get_account_source_preset,
)

__all__ = ["create_account_source_store"]


def create_account_source_store(config, save_config=None, logger=None):
    """Build a store object mirroring the JS ``createAccountSourceStore`` API.

    Args:
        config: A mutable mapping. The selection is read from and written to
            ``config["auth"]["accountSource"]`` (``{"id", "path"}``).
        save_config: Optional callable invoked with ``config`` after a change.
            May be sync or async; both are awaited correctly.
        logger: Optional ``logging.Logger`` (defaults to the ``proxhy`` logger).
    """
    logger = logger or logging.getLogger("proxhy")
    auth = config.setdefault("auth", {})

    def resolve_stored_path(source_id, raw_path):
        preset = get_account_source_preset(source_id)
        if preset.id == "custom":
            return raw_path if raw_path is not None else ""

        trimmed = raw_path.strip() if isinstance(raw_path, str) else ""
        return trimmed or preset.default_path

    account_source = auth.get("accountSource") or {}
    selected_id = account_source.get("id") or "lunar"
    selected_preset = get_account_source_preset(selected_id)

    state = {
        "id": selected_preset.id,
        "path": resolve_stored_path(selected_preset.id, account_source.get("path")),
    }

    async def _maybe_save():
        if save_config is None:
            return
        result = save_config(config)
        if inspect.isawaitable(result):
            await result

    class _AccountSourceStore:
        def list(self):
            return [
                {
                    "id": source.id,
                    "label": source.label,
                    "parser": source.parser,
                    "supported": source.supported,
                    "default_path": source.default_path,
                    "selected": source.id == state["id"],
                    "path": (
                        state["path"]
                        if source.id == state["id"]
                        else resolve_stored_path(source.id, source.default_path)
                    ),
                }
                for source in ACCOUNT_SOURCE_PRESETS
            ]

        def get(self):
            preset = get_account_source_preset(state["id"])
            return {
                "id": preset.id,
                "label": preset.label,
                "parser": preset.parser,
                "supported": preset.supported,
                "default_path": preset.default_path,
                "path": resolve_stored_path(state["id"], state["path"]),
            }

        async def set(self, id, path=None):
            preset = get_account_source_preset(id)
            state["id"] = preset.id
            state["path"] = resolve_stored_path(preset.id, path)
            auth["accountSource"] = {"id": state["id"], "path": state["path"]}
            await _maybe_save()
            suffix = f" ({state['path']})" if state["path"] else ""
            logger.info(f"Selected account source {state['id']}{suffix}")
            return self.get()

        def snapshot(self):
            return {"selected": self.get(), "presets": self.list()}

    return _AccountSourceStore()
