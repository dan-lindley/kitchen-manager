# Kitchen Manager

A local-first Home Assistant custom integration for household food inventory
and future meal planning. Kitchen Manager does not use Grocy, an external
database, or Home Assistant's Recorder database.

## My Kitchen panel

After adding Kitchen Manager, open **Kitchen Manager** from the Home Assistant
sidebar. The panel is served by Home Assistant from the integration package;
it uses authenticated Home Assistant WebSocket commands and the same inventory
engine and persistent store as the integration actions.

The current panel supports:

- Searching the local catalogue by product name, brand, or barcode.
- Creating and editing products, including optional descriptions and reorder
  thresholds.
- Viewing stock across storage locations, adding stock, consuming stock, and
  correcting quantities.
- Reviewing the latest 30 stock transactions.

Products below their optional reorder threshold are highlighted, including
products with no stock. The panel does not expose a public inventory endpoint.
It registers one sidebar panel for the single Kitchen Manager config entry and
removes the panel when that entry unloads.

## Installation

### HACS

1. In Home Assistant, open **HACS → Integrations**.
2. Select **Custom repositories** from the top-right menu.
3. Add `https://github.com/dan-lindley/kitchen-manager` with category
   **Integration**.
4. Download **Kitchen Manager**, restart Home Assistant, and add the integration
   from **Settings → Devices & services → Add integration**.

### Manual

Copy `custom_components/kitchen_manager` into the `custom_components` directory
in your Home Assistant configuration directory, restart Home Assistant, then
add **Kitchen Manager** from **Settings → Devices & services**.

## Available actions

All actions return response data. In scripts and automations, capture it with
`response_variable`. Inventory quantities are counts of items/packages; the
product's package-size metadata is descriptive and is not multiplied into stock.

| Action | Required inputs | Optional inputs | Response |
| --- | --- | --- | --- |
| `kitchen_manager.create_product` | `name` | `brand`, `barcode`, `description`, `package_size`, `package_unit`, `ingredient_name`, `reorder_threshold` | `product` |
| `kitchen_manager.update_product` | `product_id` | Product fields to update, `clear_fields` | `product` |
| `kitchen_manager.find_product` | `search_term` | — | `products`, `count` |
| `kitchen_manager.add_stock` | `product_id` **or** `barcode`, `quantity`, `location` | `operation_id` | Updated product/location quantity and transaction ID |
| `kitchen_manager.consume_stock` | `product_id` **or** `barcode`, `quantity` | `location`, `operation_id` | Updated product/location quantity and transaction ID |
| `kitchen_manager.set_stock` | `product_id` **or** `barcode`, `quantity`, `location` | `operation_id` | Updated product/location quantity and transaction ID |
| `kitchen_manager.get_stock` | Exactly one of `product_id`, `barcode`, `search_term` | `location` | `products`, `count` |
| `kitchen_manager.list_inventory` | — | `location`, `product_name` | Positive-stock `inventory`, `count` |
| `kitchen_manager.get_stock_history` | — | `product_id`, `barcode`, `limit` (default 50, max 200) | Newest-first `transactions`, `count` |

`find_product` searches names and brands case-insensitively and treats an exact
barcode as a match. Creating a product without a barcode is supported. A
provided barcode must be unique. Products with the same generic ingredient name
share one ingredient record.

### Example action calls

Create a product and capture its generated internal ID:

```yaml
sequence:
  - action: kitchen_manager.create_product
    data:
      name: Whole milk
      brand: Example Dairy
      package_size: 2
      package_unit: L
      ingredient_name: Milk
    response_variable: created
```

Add stock using the ID from the previous response:

```yaml
sequence:
  - action: kitchen_manager.add_stock
    data:
      product_id: "{{ created.product.id }}"
      quantity: 2
      location: fridge
      operation_id: milk-delivery-2026-11-09
    response_variable: stock_change
```

Query all products matching a name or brand:

```yaml
sequence:
  - action: kitchen_manager.get_stock
    data:
      search_term: milk
    response_variable: milk_stock
```

Consume stock. If stock exists in more than one location, provide `location`;
Kitchen Manager never chooses a location arbitrarily.

```yaml
sequence:
  - action: kitchen_manager.consume_stock
    data:
      barcode: "0123456789012"
      quantity: 1
      location: fridge
      operation_id: used-milk-carton-2026-11-09
    response_variable: consumed
```

Errors such as unknown products, invalid locations, duplicate barcodes,
conflicting operation IDs, and insufficient stock are raised as Home Assistant
action errors; failed operations do not create transactions. Repeating a
successful stock request with the same `operation_id` and same inputs returns
the original response without changing stock again. Reusing the ID with
different inputs is an error.

For example, `add_stock` and `consume_stock` return:

```yaml
product_id: "<internal product ID>"
product_name: Whole milk
quantity: 2.0
unit: item
location: fridge
transaction_id: "<transaction ID>"
operation_id: milk-delivery-2026-11-09
```

`create_product` and `update_product` return a `product` object. Search and
query actions return a list and `count`; stock history entries include the
operation, signed quantity change, previous/new quantities, location,
timestamp, and optional operation ID.

## Inventory summary sensor

The integration creates one aggregate sensor, **Kitchen Manager Inventory
Summary** (`sensor.kitchen_manager_inventory_summary`). Its state is the number
of distinct products with positive stock. Attributes report the total number of
product records, number of locations in use, and last stock transaction time.
It updates after a persisted catalogue or inventory change and does not expose
individual products as Home Assistant entities.

## Persistence and migration

Kitchen Manager stores a versioned JSON document with Home Assistant's
`Store` helper in the managed `.storage` directory. Products, generic
ingredients, inventory by location, transaction history, and idempotency
records are saved together. Writes use atomic storage and are read back for
verification before becoming the runtime snapshot. Inventory changes are
serialized so concurrent requests cannot overwrite one another. Home
Assistant's configuration backups include this storage; include Home Assistant
settings in backups.

Version 1 data from Kitchen Manager 0.1.0 and version 2 data from 0.2.0 are
migrated automatically. Existing product, inventory, and transaction IDs and
stock are preserved. The new description and reorder threshold fields are
optional and default to empty for existing products. Version 1 stock retains
its saved location (or defaults to `other` if no location was saved), and its
transaction history starts empty because that version did not record
transactions. No history is automatically deleted.

## Current limitations

- Barcode lookup is local catalogue matching only; Open Food Facts integration
  and scanner hardware are not implemented.
- Best-before/use-by stock batches are not implemented; stock is currently
  tracked as a per-product, per-location total.
- Stock quantities are item/package counts and currently use the generic `item`
  unit; package-size conversion is not implemented.
- Meal repository, four-week planner, shopping list, and scanning/voice
  workflows are planned, not implemented.

## Development

Use the Python version supported by your target Home Assistant release.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements_test.txt
python -m pytest
```

The test suite uses `pytest-homeassistant-custom-component` for Home Assistant
config-entry, action, sensor, and storage integration tests.
