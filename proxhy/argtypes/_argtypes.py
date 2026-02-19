from typing import Any


def _resolve_in_proxy_chain(obj: Any, attr: str) -> Any:
    """
    Search for attribute `attr` on `obj` and up the `.proxy` chain.
    Returns the attribute value if found, otherwise None.
    Prevents infinite loops by tracking visited objects.
    """
    # this is so stupid but it works lmao
    seen = set()
    current = obj
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if hasattr(current, attr):
            return getattr(current, attr)
        current = getattr(current, "proxy", None)
    return None
