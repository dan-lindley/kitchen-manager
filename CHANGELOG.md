# Changelog

## 0.4.0

- Replaced the inventory cards with a searchable, sortable, filterable table
  and a product details dialog for stock adjustments, editing, and recent
  history.
- Replaced the recipe cards with a compact responsive tile grid, search,
  effort/time filters, and 25-meal pagination.
- Added a Settings tab for persistent storage-location creation, renaming, and
  safe deletion, using stable location IDs and a schema v5-to-v6 migration.
- Preserved legacy location-name calls while preventing case-only duplicate
  locations; added location migration, CRUD, rename, and deletion safeguards.
- Expiry dates are not modeled yet, so the inventory table identifies expiry
  as not tracked rather than fabricating a value.

## 0.3.2

- Centralized automatic meal eligibility and selection for planner generation
  and per-day shuffle, using the actual calendar weekday (Monday `0` through
  Sunday `6`).
- Made the picker consume backend-computed eligibility results instead of
  independently recalculating weekdays in JavaScript.
- Improved variety by preferring meals unused in the previous seven days and
  avoiding immediate repeats when another eligible choice exists.
- Preserved existing assignments when eligibility changes, visibly marked
  saved meals outside current weekday rules, and explained unplanned dates
  with no eligible recipe.

## 0.3.1

- Replaced planner recipe dropdowns and per-day controls with clickable
  calendar cards and a responsive meal picker.
- Added case-insensitive recipe search, combined filters, 25-meal pagination,
  display-only shuffle, and clear day / recurrence restoration actions.
- Preserved recurring rules when assigning or clearing a date and added an
  explicit option to select recipes outside the day's weekday eligibility.

## 0.3.0

- Added the authenticated Kitchen Manager sidebar panel for catalogue search,
  product creation/editing, stock changes, low-stock thresholds, and recent
  transaction history.
- Added optional product descriptions and reorder thresholds.
- Added per-product default storage locations, custom location names, location
  suggestions, and safe inference from existing stock during schema v4
  migration.
- Added persistent meal create, edit, delete, weekday eligibility, optional
  catalogue-product ingredients, and cooking instructions.
- Added a four-week Monday-to-Sunday planner with fixed assignments, saved
  random suggestions, per-day shuffle, and explicit unplanned dates.
- Added weekly, every-two-week, and every-four-week recurrence with date-level
  overrides and migration from stored schema version 4.
- Added Meals and Shopping navigation; Shopping shows configured low-stock
  suggestions without changing inventory behavior.

## 0.2.0

- Added product creation, update, case-insensitive search, and shared generic
  ingredient associations.
- Added stock add, consume, set, get, and inventory listing actions.
- Added per-location transaction history and bounded history queries.
- Added operation-ID idempotency and serialized concurrent updates.
- Added the aggregate inventory summary sensor.
- Added migration from the 0.1.0 stored data schema.
- Kept barcode web lookup, scanners, voice commands, and meal planning out of
  this phase.
