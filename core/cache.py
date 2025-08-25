import asyncio
import pickle
from pathlib import Path

from platformdirs import user_cache_dir

user_cache_file = Path(user_cache_dir()) / "cache.pkl"


class Cache:
    def __init__(self, path: str = str(user_cache_file)):
        self._path = Path(path)
        self._lock = asyncio.Lock()
        if self._path.exists():
            with self._path.open("rb") as f:
                self._data = pickle.load(f)
        else:
            self._data = {}

    async def __aenter__(self):
        await self._lock.acquire()
        return self._data

    async def __aexit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("wb") as f:
                    pickle.dump(self._data, f)
        finally:
            self._lock.release()
