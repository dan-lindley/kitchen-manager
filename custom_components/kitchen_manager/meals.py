"""Meal repository and persistent four-week planner."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
import random
import uuid
from typing import Any, Protocol, TypeVar

from .models import (
    KitchenManagerData,
    Meal,
    MealEffort,
    MealIngredient,
    ModelValidationError,
    PlannerEntry,
    PlannerMode,
    RecurrenceRule,
)

_Result = TypeVar("_Result")


class MealStorage(Protocol):
    """Storage interface shared with the inventory engine."""

    @property
    def data(self) -> KitchenManagerData: ...

    async def async_update(
        self, mutator: Callable[[KitchenManagerData], tuple[_Result, bool]]
    ) -> _Result: ...


class MealError(ValueError):
    """Raised when a meal or planner operation cannot be completed."""


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


class MealPlanner:
    """Manage meals, recurrence rules, and saved planner selections."""

    def __init__(
        self,
        storage: MealStorage,
        *,
        chooser: Callable[[list[Meal]], Meal] = random.choice,
    ) -> None:
        self._storage = storage
        self._chooser = chooser

    def list_meals(self) -> list[dict[str, Any]]:
        """Return meals with their ingredient products and recurrence settings."""
        data = self._storage.data
        return [
            self._meal_dict(data, meal)
            for meal in sorted(data.meals.values(), key=lambda item: item.name.casefold())
        ]

    async def async_save_meal(
        self,
        *,
        name: str,
        effort: str,
        time_minutes: int,
        eligible_weekdays: list[int] | None = None,
        ingredients: list[dict[str, Any]] | None = None,
        instructions: str | None = None,
        meal_id: str | None = None,
        recurrence: dict[str, int] | None = None,
        today: date | None = None,
    ) -> dict[str, Any]:
        """Create or update a meal and its optional recurrence atomically."""
        meal_name = name.strip() if isinstance(name, str) else name
        weekdays = list(range(7)) if eligible_weekdays is None else eligible_weekdays
        try:
            selected_effort = MealEffort(effort)
        except (ValueError, TypeError) as err:
            raise MealError("Effort must be Low, Medium, or High.") from err
        if not isinstance(weekdays, list) or not weekdays:
            raise MealError("Select at least one eligible weekday.")
        if any(
            isinstance(day, bool) or not isinstance(day, int) or not 0 <= day <= 6
            for day in weekdays
        ):
            raise MealError("Eligible weekdays must be values from 0 to 6.")
        if len(set(weekdays)) != len(weekdays):
            raise MealError("Eligible weekdays must be unique.")
        if (
            isinstance(time_minutes, bool)
            or not isinstance(time_minutes, int)
            or time_minutes < 0
        ):
            raise MealError("Preparation/cooking time must be a non-negative integer.")
        if not isinstance(meal_name, str) or not meal_name or len(meal_name) > 200:
            raise MealError("Enter a meal name of at most 200 characters.")
        if instructions is not None and not isinstance(instructions, str):
            raise MealError("Cooking instructions must be text.")
        if instructions is not None:
            instructions = instructions.strip() or None
            if instructions is not None and len(instructions) > 20000:
                raise MealError("Cooking instructions are too long.")

        raw_ingredients = [] if ingredients is None else ingredients
        if not isinstance(raw_ingredients, list):
            raise MealError("Meal ingredients must be a list.")
        parsed_ingredients: list[MealIngredient] = []
        for raw in raw_ingredients:
            if not isinstance(raw, dict):
                raise MealError("Each ingredient must reference a catalogue product.")
            product_id = raw.get("product_id")
            quantity = raw.get("quantity")
            unit = raw.get("unit")
            if not isinstance(product_id, str) or not product_id:
                raise MealError("Each ingredient must reference a catalogue product.")
            ingredient = MealIngredient(product_id, quantity, unit)
            try:
                ingredient.validate()
            except ModelValidationError as err:
                raise MealError(str(err)) from err
            parsed_ingredients.append(ingredient)

        selected_recurrence: tuple[int, int] | None = None
        if recurrence is not None:
            if not isinstance(recurrence, dict):
                raise MealError("Recurrence must be a weekday and interval.")
            weekday = recurrence.get("weekday")
            interval = recurrence.get("interval_weeks")
            if (
                isinstance(weekday, bool)
                or not isinstance(weekday, int)
                or not 0 <= weekday <= 6
                or weekday not in weekdays
            ):
                raise MealError("The recurrence weekday must be an eligible weekday.")
            if (
                isinstance(interval, bool)
                or not isinstance(interval, int)
                or interval not in (1, 2, 4)
            ):
                raise MealError("Recurrence must be weekly, every two weeks, or every four weeks.")
            selected_recurrence = (weekday, interval)

        selected_today = today or date.today()
        if meal_id is not None and (not isinstance(meal_id, str) or not meal_id.strip()):
            raise MealError("Meal ID must be a non-empty string.")
        identifier = meal_id or str(uuid.uuid4())
        now = _timestamp()

        def mutate(data: KitchenManagerData) -> tuple[dict[str, Any], bool]:
            existing = data.meals.get(identifier)
            if meal_id is not None and existing is None:
                raise MealError("That meal no longer exists.")
            for ingredient in parsed_ingredients:
                if ingredient.product_id not in data.products:
                    raise MealError(
                        f"Ingredient product {ingredient.product_id} is not in the catalogue."
                    )
            meal = Meal(
                id=identifier,
                name=meal_name,
                effort=selected_effort,
                time_minutes=time_minutes,
                eligible_weekdays=sorted(weekdays),
                ingredients=parsed_ingredients,
                instructions=instructions,
                created_at=existing.created_at if existing else now,
                updated_at=now,
            )
            try:
                meal.validate()
            except ModelValidationError as err:
                raise MealError(str(err)) from err
            data.meals[identifier] = meal
            if selected_recurrence is None:
                data.recurrences.pop(identifier, None)
            else:
                if any(
                    other_id != identifier
                    and rule.weekday == selected_recurrence[0]
                    for other_id, rule in data.recurrences.items()
                ):
                    raise MealError(
                        "Another recurring meal is already assigned to that weekday."
                    )
                old_rule = data.recurrences.get(identifier)
                if old_rule and (
                    old_rule.weekday,
                    old_rule.interval_weeks,
                ) == selected_recurrence:
                    anchor = old_rule.anchor_date
                else:
                    first_weekday = selected_recurrence[0]
                    days_until = (first_weekday - selected_today.weekday()) % 7
                    anchor = (
                        selected_today + timedelta(days=days_until)
                    ).isoformat()
                rule = RecurrenceRule(
                    meal_id=identifier,
                    weekday=selected_recurrence[0],
                    interval_weeks=selected_recurrence[1],
                    anchor_date=anchor,
                )
                rule.validate()
                data.recurrences[identifier] = rule
            return self._meal_dict(data, meal), True

        return await self._storage.async_update(mutate)

    async def async_delete_meal(
        self, meal_id: str, *, today: date | None = None
    ) -> None:
        """Delete a meal while retaining past planner entries as history."""
        selected_today = today or date.today()

        def mutate(data: KitchenManagerData) -> tuple[None, bool]:
            meal = data.meals.get(meal_id)
            if meal is None:
                raise MealError("That meal no longer exists.")
            del data.meals[meal_id]
            data.recurrences.pop(meal_id, None)
            for day, entry in tuple(data.planner.items()):
                if entry.meal_id != meal_id:
                    continue
                if date.fromisoformat(day) >= selected_today:
                    data.planner[day] = PlannerEntry(
                        date=day,
                        mode=PlannerMode.UNPLANNED,
                        meal_id=None,
                        meal_name=None,
                    )
            return None, True

        await self._storage.async_update(mutate)

    def get_planner(self, *, today: date | None = None) -> dict[str, Any]:
        """Return four complete Monday-to-Sunday weeks."""
        current = today or date.today()
        return self._planner_from_data(self._storage.data, current)

    async def async_generate(
        self, *, today: date | None = None
    ) -> dict[str, Any]:
        """Regenerate random dates and fill unplanned future dates in this period."""
        current = today or date.today()
        first_day = _week_start(current)

        def mutate(data: KitchenManagerData) -> tuple[dict[str, Any], bool]:
            changed = False
            unavailable_dates: list[str] = []
            generated_count = 0
            replaced_count = 0
            unchanged_random_count = 0
            preserved_fixed_count = 0
            preserved_recurring_count = 0
            usage_counts: dict[str, int] = {}
            for offset in range(28):
                day = first_day + timedelta(days=offset)
                if day < current:
                    continue
                entry = data.planner.get(day.isoformat())
                recurring = self._recurring_meal(data, day)
                meal_id = (
                    entry.meal_id
                    if entry
                    and entry.mode in (PlannerMode.FIXED, PlannerMode.OVERRIDE)
                    else recurring.id
                    if recurring
                    else entry.meal_id
                    if entry and entry.mode is PlannerMode.RANDOM
                    else None
                )
                if meal_id:
                    usage_counts[meal_id] = usage_counts.get(meal_id, 0) + 1

            for offset in range(28):
                day = first_day + timedelta(days=offset)
                day_key = day.isoformat()
                if day < current:
                    continue

                entry = data.planner.get(day_key)
                if entry and entry.mode in (PlannerMode.FIXED, PlannerMode.OVERRIDE):
                    preserved_fixed_count += 1
                    continue

                recurring = self._recurring_meal(data, day)
                if recurring is not None:
                    if entry is not None:
                        del data.planner[day_key]
                        changed = True
                    preserved_recurring_count += 1
                    continue

                previous_random_id = None
                if entry and entry.mode is PlannerMode.RANDOM:
                    previous_random_id = entry.meal_id
                    if previous_random_id:
                        usage_counts[previous_random_id] -= 1
                        if usage_counts[previous_random_id] <= 0:
                            del usage_counts[previous_random_id]
                elif entry and entry.mode is PlannerMode.UNPLANNED:
                    pass
                elif entry is not None:
                    # Preserve explicit date overrides even if their recurrence
                    # rule has since been removed.
                    preserved_fixed_count += 1
                    continue

                choice = self._choose_suggestion(
                    data,
                    day,
                    usage_counts=usage_counts,
                    preferred_not_meal_id=previous_random_id,
                )
                if choice is None:
                    unavailable_dates.append(day.isoformat())
                    if previous_random_id:
                        del data.planner[day_key]
                        changed = True
                    continue

                if choice.id == previous_random_id:
                    unchanged_random_count += 1
                    usage_counts[choice.id] = usage_counts.get(choice.id, 0) + 1
                    continue
                data.planner[day_key] = PlannerEntry(
                    date=day_key,
                    mode=PlannerMode.RANDOM,
                    meal_id=choice.id,
                    meal_name=choice.name,
                )
                changed = True
                if previous_random_id:
                    replaced_count += 1
                else:
                    generated_count += 1
                usage_counts[choice.id] = usage_counts.get(choice.id, 0) + 1

            result = self._planner_from_data(data, current)
            result["unavailable_dates"] = unavailable_dates
            result["generated_count"] = generated_count
            result["replaced_count"] = replaced_count
            result["unchanged_random_count"] = unchanged_random_count
            result["preserved_fixed_count"] = preserved_fixed_count
            result["preserved_recurring_count"] = preserved_recurring_count
            result["changed"] = changed
            return result, changed

        return await self._storage.async_update(mutate)

    async def async_assign(
        self,
        *,
        day: str,
        meal_id: str | None,
        use_recurrence: bool = False,
        allow_ineligible: bool = False,
    ) -> dict[str, Any]:
        """Persist a fixed meal or an explicit unplanned/recurrence override."""
        try:
            selected_day = date.fromisoformat(day)
        except (TypeError, ValueError) as err:
            raise MealError("Select a valid planner date.") from err
        if selected_day.isoformat() != day:
            raise MealError("Select a valid planner date.")

        def mutate(data: KitchenManagerData) -> tuple[dict[str, Any], bool]:
            recurrence = self._recurring_meal(data, selected_day)
            if use_recurrence:
                if meal_id is not None or recurrence is None:
                    raise MealError("No recurring meal is configured for this date.")
                changed = data.planner.pop(day, None) is not None
                return self._day_dict(data, selected_day), changed
            if meal_id is None:
                mode = PlannerMode.OVERRIDE if recurrence else PlannerMode.UNPLANNED
                meal_name = None
            else:
                meal = data.meals.get(meal_id)
                if meal is None:
                    raise MealError("Choose a meal that still exists.")
                if not self._is_eligible_on(meal, selected_day) and not allow_ineligible:
                    raise MealError("That meal is not eligible on this weekday.")
                mode = PlannerMode.OVERRIDE if recurrence else PlannerMode.FIXED
                meal_name = meal.name
            entry = PlannerEntry(day, mode, meal_id, meal_name)
            data.planner[day] = entry
            return self._day_dict(data, selected_day), True

        return await self._storage.async_update(mutate)

    async def async_shuffle(
        self, *, day: str, today: date | None = None
    ) -> dict[str, Any]:
        """Shuffle one day and persist the result without changing other dates."""
        try:
            selected_day = date.fromisoformat(day)
        except (TypeError, ValueError) as err:
            raise MealError("Select a valid planner date.") from err
        if selected_day.isoformat() != day:
            raise MealError("Select a valid planner date.")

        def mutate(data: KitchenManagerData) -> tuple[dict[str, Any], bool]:
            current_entry = data.planner.get(day)
            recurring = self._recurring_meal(data, selected_day)
            if recurring is not None:
                raise MealError(
                    "This date has a recurring meal. Choose a meal manually to "
                    "override this occurrence, or restore its recurring assignment."
                )
            current_meal_id = (
                current_entry.meal_id
                if current_entry
                else (
                    self._recurring_meal(data, selected_day).id
                    if self._recurring_meal(data, selected_day)
                    else None
                )
            )
            selected = self._choose_suggestion(
                data, selected_day, exclude_meal_id=current_meal_id
            )
            if selected is None:
                selected = self._choose_suggestion(data, selected_day)
            if selected is None:
                raise MealError("No eligible meal is available for this date.")
            data.planner[day] = PlannerEntry(
                date=day,
                mode=PlannerMode.RANDOM,
                meal_id=selected.id,
                meal_name=selected.name,
            )
            return self._day_dict(data, selected_day), True

        return await self._storage.async_update(mutate)

    @staticmethod
    def _meal_dict(data: KitchenManagerData, meal: Meal) -> dict[str, Any]:
        """Serialize a meal with catalogue names for its ingredient references."""
        recurrence = data.recurrences.get(meal.id)
        return {
            **meal.to_dict(),
            "ingredients": [
                {
                    **ingredient.to_dict(),
                    "product_name": data.products[ingredient.product_id].name,
                    "product_unit": data.products[ingredient.product_id].package_unit,
                }
                for ingredient in meal.ingredients
            ],
            "recurrence": recurrence.to_dict() if recurrence else None,
        }

    @classmethod
    def _eligible_meals(
        cls,
        data: KitchenManagerData,
        day: date,
        *,
        max_effort: MealEffort | None = None,
        max_time_minutes: int | None = None,
    ) -> list[Meal]:
        """Apply weekday and any configured effort/time limits in one place."""
        return [
            meal
            for meal in data.meals.values()
            if cls._is_eligible_on(
                meal,
                day,
                max_effort=max_effort,
                max_time_minutes=max_time_minutes,
            )
        ]

    @staticmethod
    def _is_eligible_on(
        meal: Meal,
        day: date,
        *,
        max_effort: MealEffort | None = None,
        max_time_minutes: int | None = None,
    ) -> bool:
        """Check date eligibility and optional planner-day restrictions."""
        if day.weekday() not in meal.eligible_weekdays:
            return False
        effort_order = {
            MealEffort.LOW: 0,
            MealEffort.MEDIUM: 1,
            MealEffort.HIGH: 2,
        }
        if max_effort is not None and effort_order[meal.effort] > effort_order[max_effort]:
            return False
        return max_time_minutes is None or meal.time_minutes <= max_time_minutes

    def _choose_suggestion(
        self,
        data: KitchenManagerData,
        day: date,
        *,
        exclude_meal_id: str | None = None,
        usage_counts: dict[str, int] | None = None,
        preferred_not_meal_id: str | None = None,
    ) -> Meal | None:
        """Prefer non-recent, less-used eligible meals for this calendar date."""
        eligible = self._eligible_meals(data, day)
        candidates = [meal for meal in eligible if meal.id != exclude_meal_id]
        if not candidates:
            return None
        recent_ids = self._recent_meal_ids(data, day)
        less_repetitive = [
            meal for meal in candidates if meal.id not in recent_ids
        ]
        pool = less_repetitive
        if not pool:
            pool = candidates
        if usage_counts:
            least_used = min(usage_counts.get(meal.id, 0) for meal in pool)
            pool = [
                meal for meal in pool
                if usage_counts.get(meal.id, 0) == least_used
            ]
        if preferred_not_meal_id and len(pool) > 1:
            alternatives = [
                meal for meal in pool if meal.id != preferred_not_meal_id
            ]
            if alternatives:
                pool = alternatives
        selected = self._chooser(pool)
        if (
            selected not in pool
            or selected not in candidates
            or not self._is_eligible_on(selected, day)
        ):
            raise MealError(f"The selected meal is not eligible on {day.isoformat()}.")
        return selected

    @classmethod
    def _eligible_meal_ids_by_weekday(
        cls, data: KitchenManagerData
    ) -> dict[str, list[str]]:
        """Expose the backend's eligibility results for the picker."""
        monday = date(2024, 1, 1)
        return {
            str(weekday): [
                meal.id
                for meal in cls._eligible_meals(data, monday + timedelta(days=weekday))
            ]
            for weekday in range(7)
        }

    @staticmethod
    def _recurring_meal(data: KitchenManagerData, day: date) -> Meal | None:
        for rule in data.recurrences.values():
            anchor = date.fromisoformat(rule.anchor_date)
            if day.weekday() != rule.weekday or day < anchor:
                continue
            weeks = (day - _week_start(anchor)).days // 7
            if weeks % rule.interval_weeks == 0:
                meal = data.meals.get(rule.meal_id)
                if meal and MealPlanner._is_eligible_on(meal, day):
                    return meal
        return None

    @staticmethod
    def _recent_meal_ids(data: KitchenManagerData, day: date) -> set[str]:
        recent: set[str] = set()
        for offset in range(1, 8):
            previous = day - timedelta(days=offset)
            meal_id = MealPlanner._meal_id_on(data, previous)
            if meal_id:
                recent.add(meal_id)
        return recent

    @staticmethod
    def _meal_id_on(data: KitchenManagerData, day: date) -> str | None:
        entry = data.planner.get(day.isoformat())
        if entry:
            return entry.meal_id
        recurring = MealPlanner._recurring_meal(data, day)
        return recurring.id if recurring else None

    @classmethod
    def _day_dict(cls, data: KitchenManagerData, day: date) -> dict[str, Any]:
        key = day.isoformat()
        entry = data.planner.get(key)
        recurring = cls._recurring_meal(data, day)
        if entry:
            meal = data.meals.get(entry.meal_id) if entry.meal_id else None
            return {
                "date": key,
                "weekday": day.weekday(),
                "mode": str(entry.mode),
                "meal_id": entry.meal_id,
                "meal_name": meal.name if meal else entry.meal_name,
                "meal_eligible": (
                    cls._is_eligible_on(meal, day) if meal else None
                ),
                "recurring": recurring is not None,
                "recurrence_meal_id": recurring.id if recurring else None,
                "recurrence_meal_name": recurring.name if recurring else None,
            }
        return {
            "date": key,
            "weekday": day.weekday(),
            "mode": "recurring" if recurring else "unplanned",
            "meal_id": recurring.id if recurring else None,
            "meal_name": recurring.name if recurring else None,
            "meal_eligible": (
                cls._is_eligible_on(recurring, day) if recurring else None
            ),
            "recurring": recurring is not None,
            "recurrence_meal_id": recurring.id if recurring else None,
            "recurrence_meal_name": recurring.name if recurring else None,
        }

    @classmethod
    def _planner_from_data(
        cls, data: KitchenManagerData, today: date
    ) -> dict[str, Any]:
        first_day = _week_start(today)
        return {
            "weeks": [
                {
                    "start_date": (week_start := first_day + timedelta(weeks=index)).isoformat(),
                    "days": [
                        cls._day_dict(data, week_start + timedelta(days=offset))
                        for offset in range(7)
                    ],
                }
                for index in range(4)
            ],
            "start_date": first_day.isoformat(),
            "eligible_meal_ids_by_weekday": cls._eligible_meal_ids_by_weekday(data),
        }
