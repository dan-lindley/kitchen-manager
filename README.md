# Kitchen Manager

A local-first Home Assistant custom integration for household food inventory
and future meal planning. Kitchen Manager does not use Grocy, an external
database, or Home Assistant's Recorder database.

## Installation

1. Copy `custom_components/kitchen_manager` into the `custom_components`
   directory in your Home Assistant configuration directory. Create
   `custom_components` if it does not exist.
2. Restart Home Assistant.
3. In **Settings → Devices & services**, select **Add integration**, search for
   **Kitchen Manager**, and finish setup.

The integration creates one household config entry and an empty local store.
It does not yet expose inventory actions, product editing, sensors, or
per-product entities. The product, ingredient, and inventory models are in
place for later development.

## Storage architecture

Kitchen Manager uses Home Assistant's versioned `homeassistant.helpers.storage.Store`
helper to write a validated JSON document in Home Assistant's managed `.storage`
directory. The store uses atomic writes to reduce the risk of a partial file
after an interrupted write. Home Assistant manages this directory as part of
its configuration and includes it in configuration backups; include the
Home Assistant configuration in backups to protect Kitchen Manager data.

This is the appropriate first-phase choice because the catalogue is local,
modest in size, and does not need relational queries or concurrent access by
other applications. It avoids introducing a database dependency and keeps
backup and file lifecycle handling within Home Assistant. A dedicated SQLite
database would add schema migration, backup coordination, and concurrency
responsibilities without a current need. Recorder is never used for application
storage.

The persisted document has a schema version and separate ingredient, product,
and inventory collections. Records and cross-references are validated before
being accepted or saved.
Structurally invalid data fails setup visibly rather than being silently
replaced with an empty catalogue. If the storage file itself is malformed JSON,
Home Assistant's Store helper logs the problem and preserves a `.corrupt`
copy; Kitchen Manager also refuses to start with an empty inventory in that
case. Each save is atomic and then reloaded through a fresh Store instance;
the integration reports a failed verification instead of updating runtime data.
Normal inventory storage has no network dependency.

The manifest does not advertise a documentation URL because the project has no
published repository or documentation site yet. Add the real HTTPS project
documentation URL before publishing or submitting the integration to Hassfest;
no repository URL is assumed.

## Development

Use the Python version supported by your target Home Assistant release.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements_test.txt
python -m pytest
```

The tests use `pytest-homeassistant-custom-component` for Home Assistant
config-entry and integration setup tests.

## Development roadmap

1. **Foundation (current):** UI setup, versioned local persistence, and validated
   product, ingredient, and inventory models.
2. **Inventory operations:** shared add, consume, set, and get operations;
   auditable stock history; duplicate-submission protection; service actions.
3. **Product catalogue:** manual product management, local barcode lookup, and
   validated Open Food Facts lookup with offline operation preserved.
4. **Household workflows:** shopping-list integration, low-stock summaries,
   and a small set of useful dashboard sensors/actions rather than per-product
   entities.
5. **Recipes and recommendations:** recipe models and ingredient-aware
   recommendations, using configurable calendar entities rather than
   installation-specific entity IDs.
6. **Voice and scanner:** route voice and scanner input through the same
   inventory operations; no voice processing or scanner hardware is included
   in this phase.

Recipe execution, stock history, barcode lookup, sensors, actions, shopping-list
integration, and calendar-based meal recommendations are roadmap items, not
implemented features.
