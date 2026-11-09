# Changelog

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
