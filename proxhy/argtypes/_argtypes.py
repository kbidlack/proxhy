from typing import Any


def _resolve_in_proxy_chain(obj: Any, attr: str) -> Any:
    """
    Search for attribute `attr` on `obj` and down the `.proxy` chain,
    returning the value found furthest down the chain.
    Prevents infinite loops by tracking visited objects.
    """
    # reversed because we want to prioritize proxy gamestate over self gamestate

    # collect the full chain first
    chain = []
    seen = set()
    current = obj
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        current = getattr(current, "proxy", None)

    # search from the far end back
    for node in reversed(chain):
        if hasattr(node, attr):
            return getattr(node, attr)
    return None
