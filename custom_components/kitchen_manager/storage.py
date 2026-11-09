"""Local persistent storage for Kitchen Manager."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any, TypeVar

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from .const import (
    DATA_SCHEMA_VERSION,
    DOMAIN,
    INVENTORY_UPDATED_SIGNAL,
    STORAGE_VERSION,
)
from .models import KitchenManagerData

_Result = TypeVar("_Result")


class KitchenManagerStorageError(HomeAssistantError):
    """Raised when persisted data cannot be safely read or verified."""


class KitchenManagerStorage:
    """Load and safely save the integration's versioned data."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize Home Assistant's atomic, versioned storage helper."""
        self._store: Store[dict[str, Any]] = Store(
            hass,
            STORAGE_VERSION,
            DOMAIN,
            atomic_writes=True,
            serialize_in_event_loop=False,
        )
        self._storage_path = Path(self._store.path)
        self._write_lock = asyncio.Lock()
        self._data = KitchenManagerData()

    async def async_load(self) -> KitchenManagerData:
        """Load and validate data, starting empty only for a new installation."""
        storage_existed = await self._store.hass.async_add_executor_job(
            self._storage_exists_or_was_quarantined, self._storage_path
        )
        stored_data = await self._store.async_load()
        if stored_data is None:
            if storage_existed:
                raise KitchenManagerStorageError(
                    "Kitchen Manager storage is corrupt or unreadable; "
                    "restore a backup before continuing"
                )
            return self.data

        self._data = KitchenManagerData.from_dict(stored_data)
        if stored_data.get("schema_version") != DATA_SCHEMA_VERSION:
            await self.async_save(self._data)
        return self.data

    @property
    def data(self) -> KitchenManagerData:
        """Return a detached snapshot so failed saves cannot alter runtime state."""
        return KitchenManagerData.from_dict(self._data.to_dict())

    async def async_save(self, data: KitchenManagerData) -> None:
        """Validate and verify atomic persistence before publishing the snapshot."""
        async with self._write_lock:
            snapshot = KitchenManagerData.from_dict(data.to_dict())
            await self._async_write_snapshot(snapshot)
            self._data = snapshot
            async_dispatcher_send(self._store.hass, INVENTORY_UPDATED_SIGNAL)

    async def async_update(
        self,
        mutator: Callable[[KitchenManagerData], tuple[_Result, bool]],
    ) -> _Result:
        """Serialize a read-modify-write operation and commit its snapshot."""
        async with self._write_lock:
            snapshot = self.data
            result, changed = mutator(snapshot)
            if not changed:
                return deepcopy(result)

            await self._async_write_snapshot(snapshot)
            self._data = snapshot
            async_dispatcher_send(self._store.hass, INVENTORY_UPDATED_SIGNAL)
            return deepcopy(result)

    async def _async_write_snapshot(self, snapshot: KitchenManagerData) -> None:
        """Persist a snapshot and verify its envelope through a fresh Store."""
        serialized = snapshot.to_dict()
        await self._store.async_save(serialized)

        verified_data = await Store(
            self._store.hass,
            STORAGE_VERSION,
            DOMAIN,
            atomic_writes=True,
            serialize_in_event_loop=False,
        ).async_load()
        if verified_data != serialized:
            raise KitchenManagerStorageError(
                "Kitchen Manager storage write could not be verified; "
                "the in-memory inventory was not updated"
            )

    @staticmethod
    def _storage_exists_or_was_quarantined(path: Path) -> bool:
        """Detect existing storage, including files quarantined by Home Assistant."""
        return path.exists() or next(
            path.parent.glob(f"{path.name}.corrupt.*"), None
        ) is not None
