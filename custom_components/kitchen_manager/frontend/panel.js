class KitchenManagerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = undefined;
    this._products = [];
    this._mealProducts = [];
    this._history = [];
    this._meals = [];
    this._planner = { weeks: [] };
    this._locations = ["cupboard", "fridge", "freezer", "other"];
    this._view = "kitchen";
    this._mealIngredients = [];
    this._search = "";
    this._loading = true;
    this._error = "";
    this._modal = null;
  }

  _locationOptions() {
    return `<datalist id="storage-locations">${this._locations.map((location) => `<option value="${this._escape(location)}"></option>`).join("")}</datalist>`;
  }

  set hass(hass) {
    this._hass = hass;
    if (this.isConnected && this._loading) {
      this._load();
    }
  }

  connectedCallback() {
    this._render();
    if (this._hass) {
      this._load();
    }
  }

  async _request(type, data = {}) {
    if (!this._hass) {
      throw new Error("Home Assistant is not connected yet.");
    }
    return this._hass.callWS({ type: `kitchen_manager/${type}`, ...data });
  }

  async _load(search = this._search) {
    this._search = search;
    this._loading = true;
    this._error = "";
    this._render();
    try {
      const [catalog, history] = await Promise.all([
        this._request("catalog", search ? { search_term: search } : {}),
        this._request("history", { limit: 30 }),
      ]);
      this._products = catalog.products;
      this._history = history.transactions;
      this._locations = catalog.locations || this._locations;
    } catch (error) {
      this._error = error.message || "Kitchen Manager could not load its data.";
    } finally {
      this._loading = false;
      this._render();
    }
  }

  async _loadMeals() {
    this._loading = true;
    this._error = "";
    this._render();
    try {
      const [mealResult, planner, catalog] = await Promise.all([
        this._request("meals"),
        this._request("planner"),
        this._request("catalog"),
      ]);
      this._meals = mealResult.meals;
      this._planner = planner;
      this._mealProducts = catalog.products;
    } catch (error) {
      this._error = error.message || "Meals could not be loaded.";
    } finally {
      this._loading = false;
      this._render();
    }
  }

  async _navigate(view) {
    this._view = view;
    if (view === "meals") {
      await this._loadMeals();
    } else if (view === "shopping") {
      await this._loadShopping();
    } else {
      await this._load("");
    }
  }

  async _loadShopping() {
    this._loading = true;
    this._error = "";
    this._render();
    try {
      const catalog = await this._request("catalog");
      this._products = catalog.products;
    } catch (error) {
      this._error = error.message || "Shopping suggestions could not be loaded.";
    } finally {
      this._loading = false;
      this._render();
    }
  }

  _render() {
    if (!this.shadowRoot) {
      return;
    }
    const products = this._products.map((record) => this._productCard(record)).join("");
    const transactions = this._history.map((item) => this._transactionRow(item)).join("");
    const title = {
      kitchen: ["My Kitchen", "Products, stock and recent changes"],
      meals: ["Meals", "Your recipe collection and four-week planner"],
      shopping: ["Shopping", "Suggested purchases from your reorder thresholds"],
    }[this._view];
    let content = "";
    if (this._view === "kitchen") {
      content = this._renderKitchen(products, transactions);
    } else if (this._view === "meals") {
      content = this._renderMeals();
    } else {
      content = this._renderShopping();
    }
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          color: var(--primary-text-color);
          background: var(--primary-background-color);
          min-height: 100%;
          font-family: var(--paper-font-body1_-_font-family, inherit);
        }
        * { box-sizing: border-box; }
        main { max-width: 1180px; margin: 0 auto; padding: 28px 20px 48px; }
        header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
        h1 { font-size: 1.8rem; margin: 0 0 6px; }
        h2 { font-size: 1.2rem; margin: 0; }
        p { line-height: 1.5; }
        .muted { color: var(--secondary-text-color); }
        button, input, select, textarea {
          font: inherit;
        }
        button {
          min-height: 42px;
          border: 0;
          border-radius: 10px;
          padding: 9px 15px;
          color: var(--text-primary-color, var(--primary-text-color));
          background: var(--primary-color);
          cursor: pointer;
          font-weight: 600;
        }
        button.secondary {
          color: var(--primary-text-color);
          background: var(--secondary-background-color);
          border: 1px solid var(--divider-color);
        }
        button.danger { color: var(--error-color); }
        button:disabled { opacity: .6; cursor: wait; }
        .toolbar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin: 22px 0; }
        .search { display: flex; flex: 1 1 280px; gap: 8px; }
        input, select, textarea {
          width: 100%;
          min-height: 42px;
          border: 1px solid var(--outline-color, var(--divider-color));
          border-radius: 8px;
          padding: 9px 11px;
          color: var(--primary-text-color);
          background: var(--card-background-color, var(--primary-background-color));
        }
        textarea { resize: vertical; }
        .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 310px), 1fr)); gap: 14px; }
        article, .section, .empty {
          background: var(--card-background-color, var(--secondary-background-color));
          border: 1px solid var(--divider-color);
          border-radius: 14px;
          padding: 18px;
        }
        .product-head { display: flex; justify-content: space-between; gap: 12px; }
        .product-head h2 { overflow-wrap: anywhere; }
        .brand { margin: 4px 0 12px; color: var(--secondary-text-color); }
        .badge {
          display: inline-block;
          align-self: flex-start;
          border-radius: 999px;
          padding: 4px 9px;
          background: var(--warning-color, #b26a00);
          color: var(--text-primary-color, white);
          font-size: .78rem;
          font-weight: 700;
          white-space: nowrap;
        }
        .stock-list { margin: 10px 0 14px; padding: 0; list-style: none; }
        .stock-list li { display: flex; justify-content: space-between; gap: 8px; padding: 5px 0; border-bottom: 1px solid var(--divider-color); }
        .actions { display: flex; flex-wrap: wrap; gap: 7px; }
        .actions button { flex: 1 1 72px; padding-inline: 8px; }
        .error { margin: 16px 0; padding: 12px 14px; border-radius: 8px; color: var(--error-color); background: var(--secondary-background-color); }
        .empty { text-align: center; padding: 32px 18px; }
        .history { margin-top: 24px; }
        .history-list { padding: 0; margin: 12px 0 0; list-style: none; }
        .history-list li { display: grid; grid-template-columns: minmax(100px, 1fr) minmax(130px, 1.4fr) minmax(120px, 1fr); gap: 10px; padding: 10px 0; border-top: 1px solid var(--divider-color); }
        .modal-backdrop { position: fixed; inset: 0; z-index: 20; display: grid; place-items: center; padding: 16px; background: rgb(0 0 0 / 55%); }
        .modal { width: min(100%, 520px); max-height: 90vh; overflow: auto; padding: 20px; border-radius: 16px; background: var(--card-background-color, var(--primary-background-color)); box-shadow: var(--ha-dialog-box-shadow, 0 12px 40px #0005); }
        .modal-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 14px; }
        .modal-head button { min-width: 42px; padding: 6px; }
        label { display: block; margin: 12px 0 5px; font-size: .92rem; font-weight: 600; }
        .form-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 20px; }
        .loading { padding: 30px 0; text-align: center; }
        nav { display: flex; gap: 8px; margin: 20px 0 12px; border-bottom: 1px solid var(--divider-color); }
        nav button { border-radius: 10px 10px 0 0; background: transparent; color: var(--secondary-text-color); }
        nav button[aria-current="page"] { color: var(--primary-color); border-bottom: 3px solid var(--primary-color); }
        .meal-card h2 { overflow-wrap: anywhere; }
        .meal-meta { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
        .meal-meta span, .tag { border-radius: 999px; padding: 4px 9px; background: var(--secondary-background-color); font-size: .85rem; }
        .planner-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 22px 0 12px; }
        .week { margin: 16px 0 24px; }
        .week-grid { display: grid; grid-template-columns: repeat(7, minmax(138px, 1fr)); gap: 8px; overflow-x: auto; padding: 4px 0 10px; }
        .day-card { min-width: 138px; min-height: 210px; padding: 12px; background: var(--card-background-color, var(--secondary-background-color)); border: 1px solid var(--divider-color); border-radius: 12px; }
        .day-card h3 { margin: 0 0 8px; font-size: .96rem; }
        .day-card select { margin: 8px 0; min-height: 38px; }
        .day-card .actions button { min-height: 36px; font-size: .83rem; }
        .day-meal { min-height: 42px; margin: 8px 0; font-weight: 650; }
        .day-mode { color: var(--secondary-text-color); font-size: .78rem; text-transform: capitalize; }
        .weekday-list { display: flex; flex-wrap: wrap; gap: 5px 12px; margin: 8px 0; }
        .weekday-list label { display: inline-flex; align-items: center; gap: 5px; margin: 2px 0; font-weight: 400; }
        .weekday-list input { width: auto; min-height: auto; }
        .ingredient-row { display: grid; grid-template-columns: 2fr 1fr 1fr auto; gap: 7px; align-items: center; margin: 8px 0; }
        .ingredient-row input, .ingredient-row select { min-width: 0; }
        details { margin-top: 12px; }
        details summary { cursor: pointer; font-weight: 600; }
        .shopping-list { list-style: none; padding: 0; }
        .shopping-list li { padding: 12px 0; border-bottom: 1px solid var(--divider-color); }
        @media (max-width: 600px) {
          main { padding: 20px 12px 36px; }
          header { align-items: center; }
          header button { padding-inline: 10px; }
          .history-list li { grid-template-columns: 1fr auto; }
          .history-list li span:last-child { grid-column: 1 / -1; }
        }
      </style>
      <main>
        <header>
          <div>
            <h1>${title[0]}</h1>
            <div class="muted">${title[1]}</div>
          </div>
          ${this._view === "kitchen" ? `<button type="button" data-action="create">Add product</button>` : this._view === "meals" ? `<button type="button" data-action="create-meal">Add meal</button>` : ""}
        </header>
        <nav aria-label="Kitchen Manager sections">
          <button type="button" data-action="navigate" data-view="kitchen" aria-current="${this._view === "kitchen" ? "page" : "false"}">My Kitchen</button>
          <button type="button" data-action="navigate" data-view="meals" aria-current="${this._view === "meals" ? "page" : "false"}">Meals</button>
          <button type="button" data-action="navigate" data-view="shopping" aria-current="${this._view === "shopping" ? "page" : "false"}">Shopping</button>
        </nav>
        <div class="error" data-error role="alert" ${this._error ? "" : "hidden"}>${this._escape(this._error)}</div>
        ${this._loading ? `<div class="loading" role="status">Loading ${this._view === "meals" ? "meals and planner" : this._view === "shopping" ? "shopping suggestions" : "kitchen inventory"}…</div>` : content}
        ${this._modal ? this._renderModal() : ""}
      </main>`;
    this._bindEvents();
  }

  _renderKitchen(products, transactions) {
    return `
      <div class="toolbar">
        <form class="search" data-form="search">
          <input name="search" type="search" value="${this._escape(this._search)}" placeholder="Search name, brand or barcode" aria-label="Search products">
          <button type="submit">Search</button>
        </form>
        <button class="secondary" type="button" data-action="refresh">Refresh</button>
      </div>
      ${!this._products.length ? `
        <section class="empty">
          <h2>${this._search ? "No matching products" : "Your catalogue is empty"}</h2>
          <p class="muted">${this._search ? "Try another search, or clear the search field." : "Create your first product to start tracking household stock."}</p>
          ${this._search ? `<button class="secondary" type="button" data-action="clear-search">Clear search</button>` : `<button type="button" data-action="create">Add product</button>`}
        </section>` : ""}
      <section class="grid" aria-label="Products">${products}</section>
      <section class="section history">
        <h2>Recent stock changes</h2>
        ${transactions ? `<ul class="history-list">${transactions}</ul>` : `<p class="muted">No stock changes recorded yet.</p>`}
      </section>`;
  }

  _renderShopping() {
    const lowStock = this._products.filter((record) => record.low_stock);
    return `<section class="section">
      <h2>Suggested purchases</h2>
      <p class="muted">Products at or below their saved reorder threshold.</p>
      ${lowStock.length ? `<ul class="shopping-list">${lowStock.map(({ product, total_quantity }) => `
        <li><strong>${this._escape(product.name)}</strong> · ${this._number(total_quantity)} ${this._escape(product.package_unit || "items")} in stock</li>
      `).join("")}</ul>` : `<div class="empty"><p>No products currently meet a reorder threshold. Set a threshold when editing a product to see it here.</p></div>`}
    </section>`;
  }

  _renderMeals() {
    const mealCards = this._meals.map((meal) => `
      <article class="meal-card">
        <h2>${this._escape(meal.name)}</h2>
        <div class="meal-meta"><span>${this._escape(meal.effort[0].toUpperCase() + meal.effort.slice(1))}</span><span>${meal.time_minutes} min</span><span>${meal.eligible_weekdays.length} eligible days</span></div>
        ${meal.ingredients.length ? `<p class="muted">${meal.ingredients.map((item) => `${this._escape(item.product_name)} · ${this._number(item.quantity)} ${this._escape(item.unit || item.product_unit || "")}`).join(", ")}</p>` : ""}
        ${meal.recurrence ? `<p class="muted">Repeats ${meal.recurrence.interval_weeks === 1 ? "weekly" : `every ${meal.recurrence.interval_weeks} weeks`} on ${this._weekdayNames[meal.recurrence.weekday]}.</p>` : ""}
        <div class="actions">
          <button class="secondary" type="button" data-action="edit-meal" data-meal-id="${this._escape(meal.id)}">Edit</button>
          <button class="secondary danger" type="button" data-action="delete-meal" data-meal-id="${this._escape(meal.id)}">Delete</button>
        </div>
      </article>`).join("");
    const weeks = this._planner.weeks.map((week) => `
      <section class="week">
        <h2>Week of ${this._escape(this._formatDate(week.start_date))}</h2>
        <div class="week-grid">${week.days.map((day) => this._plannerDay(day)).join("")}</div>
      </section>`).join("");
    return `
      <section class="section">
        <div class="planner-toolbar"><div><h2>Four-week meal planner</h2><p class="muted">Selections are saved automatically and remain fixed when you return.</p></div>
          <button class="secondary" type="button" data-action="generate-planner">Suggest meals</button>
        </div>
        ${this._planner.weeks.length ? weeks : `<div class="loading">The planner is being prepared.</div>`}
      </section>
      <section class="section" style="margin-top:24px">
        <div class="planner-toolbar"><div><h2>Your meals</h2><p class="muted">Recipes can have optional ingredients and instructions.</p></div></div>
        ${mealCards ? `<section class="grid">${mealCards}</section>` : `<div class="empty"><h3>No meals yet</h3><p class="muted">Add a meal to start building your recipe collection and planner.</p><button type="button" data-action="create-meal">Add your first meal</button></div>`}
      </section>`;
  }

  _plannerDay(day) {
    const mealOptions = this._meals.filter((meal) => meal.eligible_weekdays.includes(day.weekday));
    const options = mealOptions.map((meal) => `<option value="${this._escape(meal.id)}" ${day.meal_id === meal.id && !(day.recurring && day.mode === "override") ? "selected" : ""}>${this._escape(meal.name)}</option>`).join("");
    const recurrenceOption = day.recurring
      ? `<option value="__recurrence__" ${day.mode === "override" ? "selected" : ""}>Use recurrence: ${this._escape(day.recurrence_meal_name || "scheduled meal")}</option>`
      : "";
    return `<article class="day-card">
      <h3>${this._weekdayNames[day.weekday]} <span class="muted">${this._escape(this._formatDate(day.date, true))}</span></h3>
      <div class="day-mode">${day.mode}${day.recurring && day.mode !== "recurring" ? " · recurring" : ""}</div>
      <div class="day-meal">${this._escape(day.meal_name || "Unplanned")}</div>
      <select aria-label="Meal for ${this._weekdayNames[day.weekday]} ${this._escape(day.date)}" data-day-select="${this._escape(day.date)}">
        <option value="">Unplanned</option>${recurrenceOption}${options}
      </select>
      <div class="actions"><button type="button" data-action="assign-day" data-date="${this._escape(day.date)}">Save day</button>
      <button class="secondary" type="button" data-action="shuffle-day" data-date="${this._escape(day.date)}" ${mealOptions.length < 2 ? "disabled" : ""}>Shuffle</button></div>
    </article>`;
  }

  get _weekdayNames() {
    return ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  }

  _formatDate(value, short = false) {
    const parsed = new Date(`${value}T12:00:00`);
    return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleDateString(undefined, short
      ? { month: "short", day: "numeric" }
      : { month: "long", day: "numeric", year: "numeric" });
  }

  _productCard(record) {
    const product = record.product;
    const stock = record.stock.length
      ? `<ul class="stock-list">${record.stock.map((item) => `
          <li><span>${this._escape(item.location)}</span><strong>${this._number(item.quantity)} ${this._escape(item.unit)}</strong></li>
        `).join("")}</ul>`
      : `<p class="muted">No stock recorded</p>`;
    const meta = [
      product.package_size == null ? "" : `${this._number(product.package_size)} ${product.package_unit || ""}`,
      product.barcode ? `Barcode ${product.barcode}` : "",
      `Default: ${product.default_storage_location}`,
      record.ingredient_name ? `Ingredient: ${record.ingredient_name}` : "",
      product.reorder_threshold == null ? "" : `Reorder below ${this._number(product.reorder_threshold)}`,
    ].filter(Boolean).join(" · ");
    return `
      <article>
        <div class="product-head">
          <div><h2>${this._escape(product.name)}</h2><div class="brand">${this._escape(product.brand || "No brand")}</div></div>
          ${record.low_stock ? `<span class="badge">Low stock</span>` : ""}
        </div>
        ${meta ? `<p class="muted">${this._escape(meta)}</p>` : ""}
        ${product.description ? `<p>${this._escape(product.description)}</p>` : ""}
        ${stock}
        <div class="actions">
          <button type="button" data-action="stock" data-operation="add" data-product-id="${this._escape(product.id)}">Add</button>
          <button class="secondary" type="button" data-action="stock" data-operation="consume" data-product-id="${this._escape(product.id)}">Use</button>
          <button class="secondary" type="button" data-action="stock" data-operation="set" data-product-id="${this._escape(product.id)}">Correct</button>
          <button class="secondary" type="button" data-action="edit" data-product-id="${this._escape(product.id)}">Edit</button>
        </div>
      </article>`;
  }

  _transactionRow(item) {
    const date = new Date(item.timestamp);
    const time = Number.isNaN(date.valueOf()) ? item.timestamp : date.toLocaleString();
    const changed = item.quantity_changed > 0 ? `+${this._number(item.quantity_changed)}` : this._number(item.quantity_changed);
    return `<li>
      <span>${this._escape(time)}</span>
      <span>${this._escape(item.operation)} · ${this._escape(item.location)}</span>
      <span>${changed} → ${this._number(item.new_quantity)}</span>
    </li>`;
  }

  _renderModal() {
    if (this._modal.type === "meal") {
      const meal = this._modal.meal;
      const eligible = meal?.eligible_weekdays || [0, 1, 2, 3, 4, 5, 6];
      const recurrence = meal?.recurrence;
      const ingredients = this._mealIngredients.map((item, index) => `
        <div class="ingredient-row">
          <select name="ingredient_product_${index}" aria-label="Ingredient product" required>
            <option value="">Choose product</option>
            ${this._mealProducts.map(({ product }) => `<option value="${this._escape(product.id)}" ${item.product_id === product.id ? "selected" : ""}>${this._escape(product.name)}${product.brand ? ` (${this._escape(product.brand)})` : ""}</option>`).join("")}
          </select>
          <input name="ingredient_quantity_${index}" type="number" min="0.000001" step="any" value="${this._escape(item.quantity ?? "")}" aria-label="Ingredient quantity" placeholder="Qty">
          <input name="ingredient_unit_${index}" value="${this._escape(item.unit || item.product_unit || "")}" aria-label="Ingredient unit" placeholder="Unit">
          <button class="secondary danger" type="button" data-action="remove-ingredient" data-index="${index}" aria-label="Remove ingredient">×</button>
        </div>`).join("");
      return `<div class="modal-backdrop" data-action="backdrop">
        <section class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
          <div class="modal-head"><h2 id="modal-title">${meal ? "Edit meal" : "Add meal"}</h2><button class="secondary" type="button" data-action="close" aria-label="Close">×</button></div>
          <form data-form="meal" data-meal-id="${this._escape(meal?.id || "")}">
            <label for="meal-name">Name</label>
            <input id="meal-name" name="name" required maxlength="200" value="${this._escape(meal?.name || "")}">
            <div class="grid">
              <div><label for="meal-effort">Effort</label><select id="meal-effort" name="effort">
                ${["low", "medium", "high"].map((item) => `<option value="${item}" ${(meal?.effort || "medium") === item ? "selected" : ""}>${item[0].toUpperCase()}${item.slice(1)}</option>`).join("")}
              </select></div>
              <div><label for="meal-time">Preparation/cooking time (minutes)</label><input id="meal-time" name="time_minutes" type="number" min="0" step="1" required value="${meal?.time_minutes ?? ""}"></div>
            </div>
            <label>Eligible weekdays</label>
            <div class="weekday-list">${this._weekdayNames.map((day, index) => `<label><input type="checkbox" name="eligible_weekdays" value="${index}" ${eligible.includes(index) ? "checked" : ""}>${day.slice(0, 3)}</label>`).join("")}</div>
            <details ${this._mealIngredients.length || meal?.instructions || recurrence ? "open" : ""}>
              <summary>Ingredients and instructions (optional)</summary>
              <div style="margin-top:12px">
                <strong>Ingredients from product catalogue</strong>
                <p class="muted">${this._mealProducts.length ? "Ingredients reference products, whether or not they are currently in stock." : "Create products in My Kitchen before adding recipe ingredients."}</p>
                ${ingredients}
                <button class="secondary" type="button" data-action="add-ingredient">Add ingredient</button>
                <label for="meal-instructions">Cooking instructions</label>
                <textarea id="meal-instructions" name="instructions" rows="4" maxlength="20000">${this._escape(meal?.instructions || "")}</textarea>
              </div>
            </details>
            <details ${recurrence ? "open" : ""}>
              <summary>Recurring meal (optional)</summary>
              <div class="grid">
                <div><label for="meal-recurrence">Repeats</label><select id="meal-recurrence" name="recurrence_interval">
                  <option value="" ${!recurrence ? "selected" : ""}>Does not repeat</option>
                  ${[1, 2, 4].map((interval) => `<option value="${interval}" ${recurrence?.interval_weeks === interval ? "selected" : ""}>${interval === 1 ? "Weekly" : `Every ${interval} weeks`}</option>`).join("")}
                </select></div>
                <div><label for="meal-recurrence-day">Weekday</label><select id="meal-recurrence-day" name="recurrence_weekday">
                  ${this._weekdayNames.map((day, index) => `<option value="${index}" ${recurrence?.weekday === index ? "selected" : ""}>${day}</option>`).join("")}
                </select></div>
              </div>
              <p class="muted">An individual date can be changed without removing this recurrence.</p>
            </details>
            <div class="form-actions"><button class="secondary" type="button" data-action="close">Cancel</button><button type="submit">${meal ? "Save changes" : "Create meal"}</button></div>
          </form>
        </section>
      </div>`;
    }
    if (this._modal.type === "product") {
      const product = this._modal.product;
      const editing = Boolean(product);
      return `<div class="modal-backdrop" data-action="backdrop">
        <section class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
          <div class="modal-head"><h2 id="modal-title">${editing ? "Edit product" : "Add product"}</h2><button class="secondary" type="button" data-action="close" aria-label="Close">×</button></div>
          <form data-form="product" data-product-id="${this._escape(product?.id || "")}">
            <label for="product-name">Name</label>
            <input id="product-name" name="name" required maxlength="200" value="${this._escape(product?.name || "")}">
            <label for="product-brand">Brand (optional)</label>
            <input id="product-brand" name="brand" value="${this._escape(product?.brand || "")}">
            <label for="product-barcode">Barcode (optional)</label>
            <input id="product-barcode" name="barcode" inputmode="numeric" value="${this._escape(product?.barcode || "")}">
              <div class="grid">
              <div><label for="package-size">Package size</label><input id="package-size" name="package_size" type="number" min="0.000001" step="any" value="${product?.package_size ?? ""}"></div>
              <div><label for="package-unit">Package unit</label><input id="package-unit" name="package_unit" value="${this._escape(product?.package_unit || "")}" placeholder="g, ml, pack"></div>
            </div>
            <label for="reorder-threshold">Reorder below (optional)</label>
            <input id="reorder-threshold" name="reorder_threshold" type="number" min="0" step="any" value="${product?.reorder_threshold ?? ""}" placeholder="No threshold">
              <label for="default-location">Default storage location</label>
              <input id="default-location" name="default_storage_location" list="storage-locations" required maxlength="64" value="${this._escape(product?.default_storage_location || "cupboard")}">
              ${this._locationOptions()}
              <label for="ingredient-name">Generic ingredient (optional)</label>
              <input id="ingredient-name" name="ingredient_name" value="${this._escape(this._modal.ingredientName || "")}" placeholder="For sharing recipes later">
              <label for="product-description">Description (optional)</label>
            <textarea id="product-description" name="description" rows="3">${this._escape(product?.description || "")}</textarea>
            <div class="form-actions"><button class="secondary" type="button" data-action="close">Cancel</button><button type="submit">${editing ? "Save changes" : "Create product"}</button></div>
          </form>
        </section>
      </div>`;
    }

    const product = this._products.find((item) => item.product.id === this._modal.productId)?.product;
    const operation = this._modal.operation;
    const operationLabel = { add: "Add stock", consume: "Consume stock", set: "Correct stock" }[operation];
    return `<div class="modal-backdrop" data-action="backdrop">
      <section class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
        <div class="modal-head"><h2 id="modal-title">${operationLabel}: ${this._escape(product?.name || "")}</h2><button class="secondary" type="button" data-action="close" aria-label="Close">×</button></div>
        <form data-form="stock" data-product-id="${this._escape(this._modal.productId)}" data-operation="${operation}">
          <label for="stock-quantity">${operation === "set" ? "New quantity" : "Quantity"}</label>
          <input id="stock-quantity" name="quantity" type="number" min="${operation === "set" ? "0" : "0.000001"}" step="any" required>
          <label for="stock-location">Storage location override (optional)</label>
          <input id="stock-location" name="location" list="storage-locations" maxlength="64" value="${operation === "consume" ? "" : this._escape(product?.default_storage_location || "cupboard")}" placeholder="${operation === "consume" ? "Leave blank if stock is in one location" : "Uses the product default"}">
          ${this._locationOptions()}
          <div class="form-actions"><button class="secondary" type="button" data-action="close">Cancel</button><button type="submit">${operationLabel}</button></div>
        </form>
      </section>
    </div>`;
  }

  _bindEvents() {
    this.shadowRoot.querySelectorAll("[data-action]").forEach((element) => {
      element.addEventListener("click", (event) => this._handleAction(event));
    });
    this.shadowRoot.querySelectorAll("form").forEach((form) => {
      form.addEventListener("submit", (event) => this._handleSubmit(event));
    });
  }

  async _handleAction(event) {
    const element = event.currentTarget;
    const action = element.dataset.action;
    if (action === "backdrop" && event.target !== element) {
      return;
    }
    if (action === "navigate") {
      await this._navigate(element.dataset.view);
      return;
    } else if (action === "create") {
      this._modal = { type: "product" };
    } else if (action === "edit") {
      const record = this._products.find((item) => item.product.id === element.dataset.productId);
      this._modal = {
        type: "product",
        product: record.product,
        ingredientName: record.ingredient_name || "",
      };
    } else if (action === "stock") {
      this._modal = {
        type: "stock",
        productId: element.dataset.productId,
        operation: element.dataset.operation,
      };
    } else if (action === "create-meal") {
      this._mealIngredients = [];
      this._modal = { type: "meal" };
    } else if (action === "edit-meal") {
      const meal = this._meals.find((item) => item.id === element.dataset.mealId);
      this._mealIngredients = meal.ingredients.map((item) => ({ ...item }));
      this._modal = { type: "meal", meal };
    } else if (action === "delete-meal") {
      const meal = this._meals.find((item) => item.id === element.dataset.mealId);
      if (meal && window.confirm(`Delete "${meal.name}"? Past planner entries will be retained.`)) {
        try {
          await this._request("meal/delete", { meal_id: meal.id });
          await this._loadMeals();
        } catch (error) {
          this._error = error.message || "The meal could not be deleted.";
          this._render();
        }
      }
      return;
    } else if (action === "add-ingredient" || action === "remove-ingredient") {
      this._mealIngredients = this._readIngredientRows();
      if (action === "add-ingredient") {
        this._mealIngredients.push({ product_id: "", quantity: "", unit: "" });
      } else {
        this._mealIngredients.splice(Number(element.dataset.index), 1);
      }
    } else if (action === "generate-planner") {
      try {
        await this._request("planner/generate");
        await this._loadMeals();
      } catch (error) {
        this._error = error.message || "Suggestions could not be generated.";
        this._render();
      }
      return;
    } else if (action === "assign-day") {
      const date = element.dataset.date;
      const select = this.shadowRoot.querySelector(`[data-day-select="${date}"]`);
      try {
        await this._request("planner/set", {
          date,
          ...(select.value === "__recurrence__"
            ? { use_recurrence: true }
            : { meal_id: select.value || null }),
        });
        await this._loadMeals();
      } catch (error) {
        this._error = error.message || "The planner date could not be saved.";
        this._render();
      }
      return;
    } else if (action === "shuffle-day") {
      try {
        await this._request("planner/shuffle", { date: element.dataset.date });
        await this._loadMeals();
      } catch (error) {
        this._error = error.message || "This day could not be shuffled.";
        this._render();
      }
      return;
    } else if (action === "close" || action === "backdrop") {
      this._modal = null;
    } else if (action === "refresh") {
      await (this._view === "meals" ? this._loadMeals() : this._view === "shopping" ? this._loadShopping() : this._load());
      return;
    } else if (action === "clear-search") {
      await this._load("");
      return;
    } else {
      return;
    }
    this._render();
  }

  async _handleSubmit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const submit = form.querySelector('button[type="submit"]');
    submit.disabled = true;
    this._error = "";
    try {
      if (form.dataset.form === "search") {
        await this._load(String(data.get("search") || "").trim());
        return;
      }
      if (form.dataset.form === "stock") {
        await this._request("stock/change", {
          operation: form.dataset.operation,
          product_id: form.dataset.productId,
          quantity: Number(data.get("quantity")),
          ...(String(data.get("location") || "").trim()
            ? { location: String(data.get("location")).trim() }
            : {}),
        });
      } else if (form.dataset.form === "meal") {
        const weekdays = data.getAll("eligible_weekdays").map(Number);
        if (!weekdays.length) {
          throw new Error("Select at least one eligible weekday.");
        }
        const ingredients = [];
        for (let index = 0; index < this._mealIngredients.length; index += 1) {
          const productId = String(data.get(`ingredient_product_${index}`) || "");
          const quantity = String(data.get(`ingredient_quantity_${index}`) || "").trim();
          const unit = String(data.get(`ingredient_unit_${index}`) || "").trim();
          if (!productId || !quantity || !Number.isFinite(Number(quantity)) || Number(quantity) <= 0) {
            throw new Error("Choose a catalogue product and enter a positive quantity for each ingredient.");
          }
          ingredients.push({
            product_id: productId,
            quantity: Number(quantity),
            ...(unit ? { unit } : {}),
          });
        }
        const interval = String(data.get("recurrence_interval") || "");
        const recurrenceWeekday = Number(data.get("recurrence_weekday"));
        if (interval && !weekdays.includes(recurrenceWeekday)) {
          throw new Error("The recurring weekday must also be selected as an eligible weekday.");
        }
        const recurrence = interval
          ? {
            weekday: recurrenceWeekday,
            interval_weeks: Number(interval),
          }
          : null;
        await this._request("meal/save", {
          ...(form.dataset.mealId ? { meal_id: form.dataset.mealId } : {}),
          name: String(data.get("name") || "").trim(),
          effort: data.get("effort"),
          time_minutes: Number(data.get("time_minutes")),
          eligible_weekdays: weekdays,
          ingredients,
          instructions: String(data.get("instructions") || "").trim() || null,
          recurrence,
        });
        this._modal = null;
        this._mealIngredients = [];
        await this._loadMeals();
        return;
      } else {
        const fields = this._productFields(data, form.dataset.productId);
        if (form.dataset.productId) {
          await this._request("product/update", {
            product_id: form.dataset.productId,
            ...fields.update,
          });
        } else {
          await this._request("product/create", fields.create);
        }
      }
      this._modal = null;
      await (this._view === "meals" ? this._loadMeals() : this._load());
    } catch (error) {
      this._error = error.message || "The change could not be saved.";
      this._showError(this._error);
    } finally {
      if (submit.isConnected) {
        submit.disabled = false;
      }
    }
  }

  _readIngredientRows() {
    return [...this.shadowRoot.querySelectorAll(".ingredient-row")].map((row) => ({
      product_id: row.querySelector("select").value,
      quantity: row.querySelector('input[name^="ingredient_quantity_"]').value,
      unit: row.querySelector('input[name^="ingredient_unit_"]').value,
    }));
  }

  _productFields(data, productId) {
    const name = String(data.get("name") || "").trim();
    const brand = String(data.get("brand") || "").trim();
    const barcode = String(data.get("barcode") || "").trim();
    const packageSize = String(data.get("package_size") || "").trim();
    const packageUnit = String(data.get("package_unit") || "").trim();
    const description = String(data.get("description") || "").trim();
    const threshold = String(data.get("reorder_threshold") || "").trim();
    const ingredientName = String(data.get("ingredient_name") || "").trim();
    const defaultLocation = String(data.get("default_storage_location") || "").trim();
    if (!defaultLocation) {
      throw new Error("Enter a default storage location.");
    }
    if (Boolean(packageSize) !== Boolean(packageUnit)) {
      throw new Error("Enter both package size and package unit, or leave both blank.");
    }
    const create = { name, default_storage_location: defaultLocation };
    const update = { name, default_storage_location: defaultLocation, clear_fields: [] };
    if (ingredientName) {
      create.ingredient_name = ingredientName;
      update.ingredient_name = ingredientName;
    } else if (productId) {
      const current = this._products.find((item) => item.product.id === productId);
      if (current?.ingredient_name) {
        update.clear_fields.push("ingredient");
      }
    }
    if (brand) {
      create.brand = brand;
      update.brand = brand;
    } else if (productId) {
      update.clear_fields.push("brand");
    }
    if (barcode) {
      create.barcode = barcode;
      update.barcode = barcode;
    } else if (productId) {
      update.clear_fields.push("barcode");
    }
    if (description) {
      create.description = description;
      update.description = description;
    } else if (productId) {
      update.clear_fields.push("description");
    }
    if (packageSize) {
      create.package_size = Number(packageSize);
      create.package_unit = packageUnit;
      update.package_size = Number(packageSize);
      update.package_unit = packageUnit;
    } else if (productId) {
      update.clear_fields.push("package");
    }
    if (threshold) {
      create.reorder_threshold = Number(threshold);
      update.reorder_threshold = Number(threshold);
    } else if (productId) {
      update.clear_fields.push("reorder_threshold");
    }
    return { create, update };
  }

  _number(value) {
    return new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 }).format(value);
  }

  _showError(message) {
    const error = this.shadowRoot.querySelector("[data-error]");
    if (error) {
      error.textContent = message;
      error.hidden = false;
    }
  }

  _escape(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[character]);
  }
}

if (!customElements.get("kitchen-manager-panel")) {
  customElements.define("kitchen-manager-panel", KitchenManagerPanel);
}
