"""Event system for Proxhy framework."""
from __future__ import annotations

import asyncio
import inspect
from typing import Any, Awaitable, Callable, Dict, List, TypeVar
from collections import defaultdict

EventCallback = Callable[..., Any | Awaitable[Any]]
T = TypeVar('T')


class EventEmitter:
    """Simple event emitter for decoupling components."""
    
    def __init__(self):
        self._listeners: Dict[str, List[EventCallback]] = defaultdict(list)
    
    def on(self, event: str, callback: EventCallback) -> None:
        """Register an event listener."""
        self._listeners[event].append(callback)
    
    def off(self, event: str, callback: EventCallback) -> None:
        """Remove an event listener."""
        if event in self._listeners:
            try:
                self._listeners[event].remove(callback)
            except ValueError:
                pass
    
    async def emit(self, event: str, *args: Any, **kwargs: Any) -> List[Any]:
        """Emit an event and return results from all listeners."""
        results = []
        
        for callback in self._listeners[event]:
            try:
                if inspect.iscoroutinefunction(callback):
                    result = await callback(*args, **kwargs)
                else:
                    result = callback(*args, **kwargs)
                results.append(result)
            except Exception as e:
                # Log error but don't stop other listeners
                print(f"Error in event listener for '{event}': {e}")
        
        return results
    
    def emit_sync(self, event: str, *args: Any, **kwargs: Any) -> List[Any]:
        """Emit an event synchronously (for non-async listeners only)."""
        results = []
        
        for callback in self._listeners[event]:
            if not inspect.iscoroutinefunction(callback):
                try:
                    result = callback(*args, **kwargs)
                    results.append(result)
                except Exception as e:
                    print(f"Error in event listener for '{event}': {e}")
        
        return results


class EventBus:
    """Global event bus for plugin communication."""
    
    _instance: EventBus | None = None
    
    def __new__(cls) -> EventBus:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._emitter = EventEmitter()
        return cls._instance
    
    def on(self, event: str, callback: EventCallback) -> None:
        """Register a global event listener."""
        self._emitter.on(event, callback)
    
    def off(self, event: str, callback: EventCallback) -> None:
        """Remove a global event listener."""
        self._emitter.off(event, callback)
    
    async def emit(self, event: str, *args: Any, **kwargs: Any) -> List[Any]:
        """Emit a global event."""
        return await self._emitter.emit(event, *args, **kwargs)
    
    def emit_sync(self, event: str, *args: Any, **kwargs: Any) -> List[Any]:
        """Emit a global event synchronously."""
        return self._emitter.emit_sync(event, *args, **kwargs)


# Global event bus instance
event_bus = EventBus()