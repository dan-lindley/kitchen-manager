"""Tests for meal persistence and the four-week planner."""

import asyncio
from collections.abc import Callable
from copy import deepcopy
from datetime import date
from typing import Any, TypeVar

import pytest

from custom_components.kitchen_manager.inventory import InventoryEngine
from custom_components.kitchen_manager.meals import MealError, MealPlanner
from custom_components.kitchen_manager.models import (
    InventoryItem,
    KitchenManagerData,
    Product,
)

_Result = TypeVar("_Result")
MONDAY = date(2025, 3, 3)


class MemoryStorage:
    """Atomic in-memory implementation of the storage interface."""

    def __init__(self) -> None:
        self._data = KitchenManagerData()
        self._lock = asyncio.Lock()

    @property
    def data(self) -> KitchenManagerData:
        return KitchenManagerData.from_dict(self._data.to_dict())

    async def async_update(
        self, mutator: Callable[[KitchenManagerData], tuple[_Result, bool]]
    ) -> _Result:
        async with self._lock:
            snapshot = self.data
            result, changed = mutator(snapshot)
            if changed:
                snapshot.validate()
                self._data = KitchenManagerData.from_dict(snapshot.to_dict())
            return deepcopy(result)


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage()


@pytest.fixture
def planner(storage: MemoryStorage) -> MealPlanner:
    return MealPlanner(storage, chooser=lambda options: options[0])


async def _save(
    planner: MealPlanner,
    name: str,
    *,
    days: list[int] | None = None,
    recurrence: dict[str, int] | None = None,
    meal_id: str | None = None,
) -> dict[str, Any]:
    return await planner.async_save_meal(
        name=name,
        effort="medium",
        time_minutes=30,
        eligible_weekdays=days,
        recurrence=recurrence,
        meal_id=meal_id,
        today=MONDAY,
    )


async def test_meal_defaults_are_valid_and_persist_across_reload(
    planner: MealPlanner, storage: MemoryStorage
) -> None:
    meal = await _save(planner, "Pasta")

    assert meal["eligible_weekdays"] == list(range(7))
    assert meal["ingredients"] == []
    assert meal["instructions"] is None

    reloaded = MealPlanner(storage)
    assert reloaded.list_meals()[0]["name"] == "Pasta"
    assert reloaded.get_planner(today=MONDAY)["start_date"] == "2025-03-03"


async def test_concurrent_meal_creates_do_not_overwrite_each_other(
    planner: MealPlanner,
) -> None:
    await asyncio.gather(_save(planner, "Rice bowls"), _save(planner, "Bean stew"))

    assert {meal["name"] for meal in planner.list_meals()} == {
        "Rice bowls",
        "Bean stew",
    }


async def test_meal_ingredient_must_reference_a_catalogue_product(
    planner: MealPlanner, storage: MemoryStorage
) -> None:
    inventory = InventoryEngine(storage)
    product = await inventory.async_create_product(name="Chopped tomatoes")
    meal = await planner.async_save_meal(
        name="Tomato pasta",
        effort="low",
        time_minutes=20,
        ingredients=[{"product_id": product["id"], "quantity": 1, "unit": "tin"}],
        today=MONDAY,
    )
    assert meal["ingredients"][0]["product_name"] == "Chopped tomatoes"

    with pytest.raises(MealError, match="not in the catalogue"):
        await planner.async_save_meal(
            name="Invalid",
            effort="low",
            time_minutes=10,
            ingredients=[{"product_id": "missing", "quantity": 1}],
            today=MONDAY,
        )


async def test_group_assignment_does_not_change_exact_recipe_product_reference(
    planner: MealPlanner,
    storage: MemoryStorage,
) -> None:
    inventory = InventoryEngine(storage)
    group = await inventory.async_create_product_group(name="Beans")
    product = await inventory.async_create_product(
        name="Baked beans",
        brand="Brand A",
    )
    meal = await planner.async_save_meal(
        name="Beans on toast",
        effort="low",
        time_minutes=10,
        ingredients=[{"product_id": product["id"], "quantity": 1, "unit": "tin"}],
        today=MONDAY,
    )

    await inventory.async_update_product(
        product_id=product["id"],
        group_id=group["id"],
    )

    saved_meal = planner.list_meals()[0]
    assert meal["ingredients"][0]["product_id"] == product["id"]
    assert saved_meal["ingredients"][0]["product_id"] == product["id"]


async def test_edit_preserves_meal_identity_and_updates_recurrence(
    planner: MealPlanner,
) -> None:
    meal = await _save(planner, "Soup")
    edited = await planner.async_save_meal(
        meal_id=meal["id"],
        name="Vegetable soup",
        effort="low",
        time_minutes=40,
        eligible_weekdays=[1, 3],
        recurrence={"weekday": 1, "interval_weeks": 2},
        today=MONDAY,
    )

    assert edited["id"] == meal["id"]
    assert edited["name"] == "Vegetable soup"
    assert edited["recurrence"]["interval_weeks"] == 2


async def test_generation_obeys_weekday_eligibility_and_is_stable(
    planner: MealPlanner,
) -> None:
    meal = await _save(planner, "Sunday roast", days=[6])

    generated = await planner.async_generate(today=MONDAY)
    days = [day for week in generated["weeks"] for day in week["days"]]
    assert len(days) == 28
    sunday = next(day for day in days if day["date"] == "2025-03-09")
    monday = next(day for day in days if day["date"] == "2025-03-03")
    assert sunday["meal_id"] == meal["id"]
    assert monday["mode"] == "unplanned"

    repeated = await planner.async_generate(today=MONDAY)
    assert repeated["weeks"][0]["days"][6]["meal_id"] == meal["id"]
    reloaded = planner.get_planner(today=MONDAY)
    assert reloaded["weeks"][0]["days"][6]["meal_id"] == meal["id"]


async def test_generation_uses_real_tuesday_and_recipe_weekdays(
    planner: MealPlanner,
) -> None:
    tuesday = date(2026, 11, 10)
    takeaway = await _save(
        planner, "De Bao Chinese Takeaway", days=[0, 2, 3, 4, 5, 6]
    )
    lasagne = await _save(planner, "Lasagne", days=[0, 4])
    await _save(planner, "Any-day fallback")

    generated = await planner.async_generate(today=tuesday)
    days = [
        day
        for week in generated["weeks"]
        for day in week["days"]
        if date.fromisoformat(day["date"]) >= tuesday
    ]

    assert date.fromisoformat("2026-11-10").weekday() == 1
    assert generated["eligible_meal_ids_by_weekday"]["1"]
    assert takeaway["id"] not in generated["eligible_meal_ids_by_weekday"]["1"]
    for day in days:
        weekday = date.fromisoformat(day["date"]).weekday()
        assert day["weekday"] == weekday
        if day["meal_id"] == takeaway["id"]:
            assert weekday in takeaway["eligible_weekdays"]
            assert weekday != 1
        if day["meal_id"] == lasagne["id"]:
            assert weekday in [0, 4]

    tuesday_assignment = next(day for day in days if day["date"] == "2026-11-10")
    assert tuesday_assignment["meal_id"] != takeaway["id"]


async def test_generation_avoids_recent_repetition_when_alternatives_exist(
    planner: MealPlanner,
) -> None:
    await _save(planner, "Pasta")
    await _save(planner, "Tacos")
    generated = await planner.async_generate(today=MONDAY)
    days = [
        day
        for week in generated["weeks"]
        for day in week["days"]
        if date.fromisoformat(day["date"]) >= MONDAY
    ]

    assert all(
        first_day["meal_id"] != second_day["meal_id"]
        for first_day, second_day in zip(days, days[1:])
    )


async def test_generation_preserves_fixed_and_recurring_assignments(
    planner: MealPlanner,
) -> None:
    recurring = await _save(
        planner, "Tuesday soup", days=[1], recurrence={"weekday": 1, "interval_weeks": 1}
    )
    fixed = await _save(planner, "Wednesday roast", days=[2])
    await planner.async_assign(day="2025-03-05", meal_id=fixed["id"])

    generated = await planner.async_generate(today=MONDAY)
    days = generated["weeks"][0]["days"]

    assert days[1]["mode"] == "recurring"
    assert days[1]["meal_id"] == recurring["id"]
    assert days[2]["mode"] == "fixed"
    assert days[2]["meal_id"] == fixed["id"]


async def test_generation_reports_and_preserves_days_without_eligible_meals(
    planner: MealPlanner,
) -> None:
    await _save(planner, "Sunday roast", days=[6])

    generated = await planner.async_generate(today=MONDAY)
    days = generated["weeks"][0]["days"]

    assert "2025-03-03" in generated["unavailable_dates"]
    assert days[0]["mode"] == "unplanned"
    assert days[6]["mode"] == "random"


async def test_existing_random_assignment_is_retained_when_eligibility_changes(
    planner: MealPlanner, storage: MemoryStorage
) -> None:
    meal = await _save(planner, "Pasta")
    await planner.async_generate(today=MONDAY)
    await _save(planner, "Pasta", days=[1], meal_id=meal["id"])
    await planner.async_generate(today=MONDAY)

    monday = MealPlanner(storage).get_planner(today=MONDAY)["weeks"][0]["days"][0]
    assert monday["mode"] == "random"
    assert monday["meal_id"] == meal["id"]
    assert monday["meal_eligible"] is False


async def test_shuffle_selects_only_meals_eligible_on_requested_date(
    planner: MealPlanner,
) -> None:
    await _save(planner, "Tuesday-only meal", days=[1])
    monday_meal = await _save(planner, "Monday meal", days=[0])

    shuffled = await planner.async_shuffle(day="2025-03-03", today=MONDAY)

    assert shuffled["meal_id"] == monday_meal["id"]
    assert shuffled["meal_eligible"] is True


async def test_planner_weekday_and_picker_eligibility_use_monday_zero(
    planner: MealPlanner,
) -> None:
    meals = [
        await _save(planner, f"Weekday {weekday}", days=[weekday])
        for weekday in range(7)
    ]

    planner_data = planner.get_planner(today=MONDAY)
    days = planner_data["weeks"][0]["days"]
    eligible_by_weekday = planner_data["eligible_meal_ids_by_weekday"]

    for weekday, day in enumerate(days):
        assert day["weekday"] == date.fromisoformat(day["date"]).weekday() == weekday
        assert eligible_by_weekday[str(weekday)] == [meals[weekday]["id"]]


async def test_recurrence_and_occurrence_override_are_persistent(
    planner: MealPlanner, storage: MemoryStorage
) -> None:
    recurring = await _save(
        planner, "Soup", days=[1], recurrence={"weekday": 1, "interval_weeks": 2}
    )
    replacement = await _save(planner, "Curry", days=[1])

    tuesday = "2025-03-04"
    initial = planner.get_planner(today=MONDAY)["weeks"][0]["days"][1]
    assert initial["mode"] == "recurring"
    assert initial["meal_id"] == recurring["id"]
    later = planner.get_planner(today=MONDAY)["weeks"][2]["days"][1]
    assert later["mode"] == "recurring"
    assert later["meal_id"] == recurring["id"]

    await planner.async_assign(day=tuesday, meal_id=replacement["id"])
    overridden = MealPlanner(storage).get_planner(today=MONDAY)["weeks"][0]["days"][1]
    assert overridden["mode"] == "override"
    assert overridden["meal_id"] == replacement["id"]
    assert overridden["recurring"]

    await planner.async_assign(day=tuesday, meal_id=None, use_recurrence=True)
    resumed = planner.get_planner(today=MONDAY)["weeks"][0]["days"][1]
    assert resumed["mode"] == "recurring"
    assert resumed["meal_id"] == recurring["id"]

    await planner.async_assign(day=tuesday, meal_id=None)
    unplanned = planner.get_planner(today=MONDAY)["weeks"][0]["days"][1]
    assert unplanned["mode"] == "override"
    assert unplanned["meal_id"] is None


async def test_shuffle_changes_only_requested_day_and_can_be_reloaded(
    planner: MealPlanner, storage: MemoryStorage
) -> None:
    pasta = await _save(planner, "Pasta")
    await _save(planner, "Tacos")
    await planner.async_assign(day="2025-03-03", meal_id=pasta["id"])
    await planner.async_assign(day="2025-03-04", meal_id=pasta["id"])

    await planner.async_shuffle(day="2025-03-03", today=MONDAY)
    reloaded = MealPlanner(storage).get_planner(today=MONDAY)["weeks"][0]["days"]

    assert reloaded[0]["meal_id"] != pasta["id"]
    assert reloaded[1]["meal_id"] == pasta["id"]


async def test_recurrence_weekday_must_be_recipe_eligible(
    planner: MealPlanner,
) -> None:
    with pytest.raises(MealError, match="eligible weekday"):
        await _save(
            planner,
            "Saturday curry",
            days=[5],
            recurrence={"weekday": 1, "interval_weeks": 1},
        )


async def test_manual_ineligible_assignment_requires_explicit_override(
    planner: MealPlanner,
) -> None:
    meal = await _save(planner, "Sunday roast", days=[6])

    with pytest.raises(MealError, match="not eligible"):
        await planner.async_assign(day="2025-03-03", meal_id=meal["id"])

    assigned = await planner.async_assign(
        day="2025-03-03", meal_id=meal["id"], allow_ineligible=True
    )
    assert assigned["meal_id"] == meal["id"]
    assert assigned["mode"] == "fixed"


async def test_recurrence_starts_on_next_matching_weekday(
    planner: MealPlanner,
) -> None:
    await planner.async_save_meal(
        name="Monday soup",
        effort="low",
        time_minutes=20,
        eligible_weekdays=[0],
        recurrence={"weekday": 0, "interval_weeks": 1},
        today=date(2025, 3, 5),
    )
    weeks = planner.get_planner(today=MONDAY)["weeks"]

    assert weeks[0]["days"][0]["mode"] == "unplanned"
    assert weeks[1]["days"][0]["mode"] == "recurring"


@pytest.mark.parametrize(
    ("interval", "expected_dates"),
    [
        (1, ["2025-03-04", "2025-03-11", "2025-03-18", "2025-03-25"]),
        (2, ["2025-03-04", "2025-03-18"]),
        (4, ["2025-03-04"]),
    ],
)
async def test_supported_recurrence_intervals(
    planner: MealPlanner, interval: int, expected_dates: list[str]
) -> None:
    await _save(
        planner,
        "Tuesday meal",
        days=[1],
        recurrence={"weekday": 1, "interval_weeks": interval},
    )
    weeks = planner.get_planner(today=MONDAY)["weeks"]
    actual = [
        day["date"]
        for week in weeks
        for day in week["days"]
        if day["mode"] == "recurring"
    ]

    assert actual == expected_dates


async def test_deleting_meal_keeps_history_and_clears_future(
    planner: MealPlanner, storage: MemoryStorage
) -> None:
    meal = await _save(planner, "Roast chicken")
    await planner.async_assign(day="2025-03-03", meal_id=meal["id"])
    await planner.async_assign(day="2025-03-10", meal_id=meal["id"])

    await planner.async_delete_meal(meal["id"], today=date(2025, 3, 5))
    data = storage.data

    assert "2025-03-03" in data.planner
    assert data.planner["2025-03-03"].meal_name == "Roast chicken"
    assert data.planner["2025-03-10"].mode.value == "unplanned"
    assert not data.meals


def test_schema_v4_migrates_without_changing_inventory() -> None:
    product = Product(id="milk", name="Milk")
    stock = InventoryItem(
        product_id=product.id, quantity=3, unit="item", location="fridge"
    )
    data = KitchenManagerData(
        products={product.id: product},
        inventory={
            KitchenManagerData.inventory_key(product.id, stock.location): stock
        },
    )
    old = data.to_dict()
    old["schema_version"] = 4
    old.pop("meals")
    old.pop("recurrences")
    old.pop("planner")
    old.pop("locations")
    old.pop("product_groups")

    migrated = KitchenManagerData.from_dict(old)

    assert migrated.meals == {}
    assert migrated.recurrences == {}
    assert migrated.planner == {}
    assert migrated.products[product.id].name == "Milk"
    assert migrated.inventory[
        KitchenManagerData.inventory_key(product.id, stock.location)
    ].quantity == 3
    assert migrated.to_dict()["schema_version"] == 7


def test_meal_weekdays_and_planner_dates_are_validated() -> None:
    raw = KitchenManagerData().to_dict()
    raw["meals"]["bad"] = {
        "id": "bad",
        "name": "Bad",
        "effort": "low",
        "time_minutes": 10,
        "eligible_weekdays": [7],
        "ingredients": [],
        "instructions": None,
        "created_at": "2025-03-03T00:00:00+00:00",
        "updated_at": "2025-03-03T00:00:00+00:00",
    }

    with pytest.raises(ValueError, match="weekday"):
        KitchenManagerData.from_dict(raw)
