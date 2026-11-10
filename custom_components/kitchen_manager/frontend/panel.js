class KitchenManagerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = undefined;
    this._products = [];
    this._groups = [];
    this._mealProducts = [];
    this._history = [];
    this._meals = [];
    this._planner = { weeks: [] };
    this._locations = [
      { id: "cupboard", name: "Cupboard" },
      { id: "fridge", name: "Fridge" },
      { id: "freezer", name: "Freezer" },
      { id: "other", name: "Other" },
    ];
    this._view = "kitchen";
    this._mealIngredients = [];
    this._search = "";
    this._loading = true;
    this._error = "";
    this._plannerMessage = "";
    this._modal = null;
    this._modalError = "";
    this._picker = null;
    this._pickerSaving = false;
    this._returnToPicker = false;
    this._plannerGenerating = false;
    this._inventoryPage = 1;
    this._expandedGroups = new Set();
    this._inventorySort = { key: "name", direction: "asc" };
    this._locationFilter = "any";
    this._lowStockFilter = "any";
    this._mealQuery = "";
    this._mealPage = 1;
    this._mealEffort = "any";
    this._mealMaxTime = "";
    this._onDialogKeydown = (event) => this._handleDialogKeydown(event);
  }

  async _suggestPickerDay() {
    if (!this._picker || this._pickerSaving) return;
    this._pickerSaving = true;
    this._error = "";
    this._render();
    try {
      const updatedDay = await this._request("planner/shuffle", {
        date: this._picker.date,
      });
      this._updatePlannerDay(updatedDay);
      this._closePicker();
      if (!await this._loadMeals()) {
        this._error = `The date was saved, but the planner could not be refreshed: ${this._error}`;
        this._render();
      }
    } catch (error) {
      this._pickerSaving = false;
      this._error = error.message || "A random meal could not be assigned. Your previous selection is unchanged.";
      this._render();
    }
  }

  _locationOptions(selectedId) {
    return this._locations.map((location) => `<option value="${this._escape(location.id)}" ${location.id === selectedId ? "selected" : ""}>${this._escape(location.name)}</option>`).join("");
  }

  set hass(hass) {
    this._hass = hass;
    if (this.isConnected && this._loading) {
      this._load();
    }
  }

  async _loadSettings() {
    this._loading = true;
    this._error = "";
    this._render();
    try {
      const catalog = await this._request("catalog");
      this._locations = catalog.locations || this._locations;
      this._groups = catalog.product_groups || this._groups;
    } catch (error) {
      this._error = error.message || "Storage locations could not be loaded.";
    } finally {
      this._loading = false;
      this._render();
    }
  }

  connectedCallback() {
    document.addEventListener("keydown", this._onDialogKeydown);
    this._render();
    if (this._hass) {
      this._load();
    }
  }

  disconnectedCallback() {
    document.removeEventListener("keydown", this._onDialogKeydown);
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
        this._request("catalog"),
        this._request("history", { limit: 30 }),
      ]);
      this._products = catalog.products;
      this._groups = catalog.product_groups || this._groups;
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
    let succeeded = false;
    try {
      const [mealResult, planner, catalog] = await Promise.all([
        this._request("meals"),
        this._request("planner"),
        this._request("catalog"),
      ]);
      this._meals = mealResult.meals;
      this._planner = planner;
      this._mealProducts = catalog.products;
      this._groups = catalog.product_groups || this._groups;
      succeeded = true;
    } catch (error) {
      this._error = error.message || "Meals could not be loaded.";
    } finally {
      this._loading = false;
      this._render();
    }
    return succeeded;
  }

  async _navigate(view) {
    this._view = view;
    if (view === "meals") {
      await this._loadMeals();
    } else if (view === "shopping") {
      await this._loadShopping();
    } else if (view === "settings") {
      await this._loadSettings();
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
      this._locations = catalog.locations || this._locations;
      this._groups = catalog.product_groups || this._groups;
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
    const activeElement = this.shadowRoot.activeElement;
    const focusKey = activeElement?.dataset?.focusKey;
    const selectionStart = activeElement?.selectionStart;
    const selectionEnd = activeElement?.selectionEnd;
    const transactions = this._history.map((item) => this._transactionRow(item)).join("");
    const title = {
      kitchen: ["My Kitchen", "Products, stock and recent changes"],
      meals: ["Meals", "Your recipe collection and four-week planner"],
      shopping: ["Shopping", "Suggested purchases from your reorder thresholds"],
      settings: ["Settings", "Manage storage locations and product groups"],
    }[this._view];
    let content = "";
    if (this._view === "kitchen") {
      content = this._renderKitchen(transactions);
    } else if (this._view === "meals") {
      content = this._renderMeals();
    } else if (this._view === "settings") {
      content = this._renderSettings();
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
          .notice { margin: 16px 0; padding: 12px 14px; border-radius: 8px; color: var(--primary-text-color); background: var(--secondary-background-color); border-left: 3px solid var(--primary-color); }
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
        .week-grid { grid-template-columns: repeat(7, minmax(0, 1fr)); overflow: visible; }
        .day-card {
          appearance: none;
          display: flex;
          flex-direction: column;
          align-items: stretch;
          width: 100%;
          min-width: 0;
          min-height: 132px;
          padding: 13px;
          color: var(--primary-text-color);
          text-align: left;
          background: var(--card-background-color, var(--secondary-background-color));
          border: 1px solid var(--divider-color);
          border-radius: 14px;
          box-shadow: var(--ha-card-box-shadow, 0 1px 3px #0002);
          transition: border-color 140ms ease, transform 140ms ease, box-shadow 140ms ease;
        }
        .day-card:hover, .day-card:focus-visible {
          border-color: var(--primary-color);
          box-shadow: 0 4px 14px #0002;
          transform: translateY(-2px);
          outline: none;
        }
        .day-card:focus-visible { box-shadow: 0 0 0 2px var(--primary-color); }
        .day-date { font-size: .82rem; color: var(--secondary-text-color); }
        .day-card h3 { margin: 3px 0 12px; font-size: 1rem; }
        .day-meal { min-height: 0; margin: auto 0 12px; font-weight: 650; line-height: 1.35; overflow-wrap: anywhere; }
        .day-status { align-self: flex-start; border-radius: 999px; padding: 4px 9px; color: var(--secondary-text-color); background: var(--secondary-background-color); font-size: .76rem; font-weight: 650; }
        .day-status[data-status="fixed"] { color: var(--primary-color); }
        .day-status[data-status="random"] { color: var(--success-color, var(--primary-color)); }
        .day-status[data-status="recurring"] { color: var(--accent-color, var(--primary-color)); }
        .day-warning { align-self: flex-start; color: var(--warning-color, var(--error-color)); font-size: .75rem; font-weight: 650; }
        .picker-backdrop { position: fixed; inset: 0; z-index: 30; display: grid; place-items: center; padding: 18px; background: rgb(0 0 0 / 58%); animation: picker-fade 140ms ease-out; }
        .picker-dialog { display: flex; flex-direction: column; width: min(1180px, 100%); max-height: min(92vh, 960px); overflow: hidden; padding: clamp(18px, 3vw, 30px); border-radius: 20px; color: var(--primary-text-color); background: var(--card-background-color, var(--primary-background-color)); box-shadow: var(--ha-dialog-box-shadow, 0 16px 54px #0006); animation: picker-rise 160ms ease-out; }
        .picker-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
        .picker-heading h2 { font-size: 1.5rem; }
        .picker-heading p { margin: 5px 0 0; color: var(--secondary-text-color); }
        .picker-tools { display: grid; grid-template-columns: minmax(220px, 1fr) repeat(3, minmax(140px, .42fr)) auto; gap: 10px; align-items: end; margin: 20px 0 14px; }
        .picker-search { display: grid; gap: 5px; }
        .picker-tools label { display: grid; gap: 5px; margin: 0; font-size: .82rem; color: var(--secondary-text-color); }
        .picker-tools input, .picker-tools select { min-height: 44px; }
        .eligible-toggle { display: flex !important; align-items: center; align-self: center; gap: 8px !important; padding: 0 4px; color: var(--primary-text-color) !important; white-space: nowrap; }
        .eligible-toggle input { width: 18px; min-height: 18px; accent-color: var(--primary-color); }
        .picker-grid { display: grid; flex: 1 1 auto; min-height: 0; grid-template-columns: repeat(5, minmax(0, 1fr)); grid-auto-rows: minmax(132px, auto); gap: 12px; overflow-y: auto; overscroll-behavior: contain; padding: 2px 3px 10px; }
        .meal-tile { position: relative; display: flex; flex-direction: column; align-items: flex-start; width: 100%; min-width: 0; min-height: 132px; padding: 15px; color: var(--primary-text-color); text-align: left; background: var(--secondary-background-color); border: 1px solid var(--divider-color); border-radius: 15px; cursor: pointer; transition: background 140ms ease, border-color 140ms ease, box-shadow 140ms ease, transform 140ms ease; }
        .meal-tile:hover, .meal-tile:focus-visible { border-color: var(--primary-color); background: var(--primary-background-color); box-shadow: 0 5px 18px #0002; transform: translateY(-2px); outline: none; }
        .meal-tile:focus-visible { box-shadow: 0 0 0 2px var(--primary-color); }
        .meal-tile[aria-pressed="true"] { border: 2px solid var(--primary-color); background: var(--primary-background-color); }
        .meal-tile-name { width: 100%; font-size: 1rem; font-weight: 700; line-height: 1.35; overflow-wrap: anywhere; }
        .meal-tile-meta { display: flex; flex-wrap: wrap; gap: 6px; margin-top: auto; padding-top: 12px; color: var(--secondary-text-color); font-size: .8rem; }
        .meal-tile-meta span { border-radius: 999px; padding: 4px 8px; background: var(--primary-background-color); }
        .meal-tile-current { position: absolute; top: 8px; right: 8px; color: var(--primary-color); font-size: .76rem; font-weight: 700; }
        .picker-empty { display: grid; place-items: center; min-height: 220px; text-align: center; color: var(--secondary-text-color); }
        .picker-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 14px; border-top: 1px solid var(--divider-color); }
        .picker-pages { display: flex; align-items: center; gap: 10px; }
        .picker-page-count { min-width: 140px; text-align: center; color: var(--secondary-text-color); font-size: .9rem; }
        .picker-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
        .picker-saving { position: absolute; inset: 0; z-index: 2; display: grid; place-items: center; border-radius: inherit; background: color-mix(in srgb, var(--card-background-color, var(--primary-background-color)) 84%, transparent); font-weight: 700; }
        .picker-error { margin: -4px 0 12px; padding: 10px 12px; border-radius: 9px; color: var(--error-color); background: var(--secondary-background-color); }
        .inventory-toolbar { display: grid; grid-template-columns: minmax(240px, 1fr) repeat(2, minmax(160px, .35fr)) auto; }
        .table-scroll { overflow-x: auto; border: 1px solid var(--divider-color); border-radius: 12px; background: var(--card-background-color, var(--secondary-background-color)); }
        .inventory-table { width: 100%; border-collapse: collapse; text-align: left; }
        .inventory-table th, .inventory-table td { padding: 10px 12px; border-bottom: 1px solid var(--divider-color); vertical-align: middle; }
        .inventory-table th { white-space: nowrap; color: var(--secondary-text-color); font-size: .82rem; }
        .inventory-table tr:last-child td { border-bottom: 0; }
        .inventory-table tbody tr { cursor: pointer; transition: background 120ms ease; }
        .inventory-table tbody tr:hover, .inventory-table tbody tr:focus-visible { background: var(--secondary-background-color); outline: 2px solid var(--primary-color); outline-offset: -2px; }
        .inventory-table tbody .group-row { background: var(--secondary-background-color); font-weight: 650; }
        .inventory-table .group-row td:first-child { white-space: nowrap; }
        .inventory-table .group-row small, .inventory-table .variant-row small { display: block; margin-top: 3px; color: var(--secondary-text-color); font-size: .78rem; font-weight: 400; white-space: normal; }
        .inventory-table .variant-row td:first-child { padding-left: 32px; }
        .group-toggle { min-width: 30px; min-height: 30px; margin-right: 8px; padding: 2px; border: 1px solid var(--divider-color); border-radius: 50%; color: var(--primary-text-color); background: var(--card-background-color, var(--primary-background-color)); }
        .group-toggle:hover, .group-toggle:focus-visible { border-color: var(--primary-color); outline: 2px solid var(--primary-color); }
        .table-sort { min-height: 34px; padding: 4px 2px; border: 0; color: inherit; background: transparent; font-size: inherit; text-align: left; }
        .pagination { display: flex; justify-content: center; align-items: center; gap: 14px; padding: 14px 0 4px; color: var(--secondary-text-color); }
        .recipe-tools { display: grid; grid-template-columns: minmax(240px, 1fr) minmax(150px, .35fr) minmax(150px, .35fr); gap: 10px; align-items: end; margin: 14px 0; }
        .recipe-tools label { display: grid; gap: 4px; margin: 0; color: var(--secondary-text-color); font-size: .82rem; }
        .recipe-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 9px; }
        .recipe-tile { display: flex; flex-direction: column; align-items: flex-start; min-width: 0; min-height: 84px; padding: 11px 12px; color: var(--primary-text-color); text-align: left; background: var(--card-background-color, var(--secondary-background-color)); border: 1px solid var(--divider-color); border-radius: 12px; }
        .recipe-tile:hover, .recipe-tile:focus-visible { border-color: var(--primary-color); outline: 2px solid var(--primary-color); outline-offset: 1px; }
        .recipe-tile strong { overflow-wrap: anywhere; line-height: 1.3; }
        .recipe-tile span { margin-top: auto; padding-top: 8px; color: var(--secondary-text-color); font-size: .78rem; }
        .section-toolbar { margin-bottom: 12px; }
        .location-create { display: grid; grid-template-columns: 1fr auto; gap: 8px; align-items: end; max-width: 560px; margin: 14px 0 20px; }
        .location-create label { grid-column: 1 / -1; margin: 0; }
        .location-list { max-width: 760px; padding: 0; list-style: none; }
        .location-list li { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 10px 0; border-top: 1px solid var(--divider-color); }
        .location-list li > span:first-child { display: grid; gap: 3px; overflow-wrap: anywhere; }
        .location-list small { color: var(--secondary-text-color); }
        .detail-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 14px; margin: 10px 0; }
        .detail-history { max-height: 230px; overflow: auto; padding-left: 20px; }
        .recipe-delete { margin-right: auto; }
        @media (min-width: 601px) and (max-width: 980px) {
          .recipe-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
          .inventory-toolbar { grid-template-columns: 1fr 1fr; }
        }
        @keyframes picker-fade { from { opacity: 0; } to { opacity: 1; } }
        @keyframes picker-rise { from { transform: translateY(8px); opacity: .7; } to { transform: translateY(0); opacity: 1; } }
        @media (max-width: 600px) {
          main { padding: 20px 12px 36px; }
          header { align-items: center; }
          header button { padding-inline: 10px; }
          .history-list li { grid-template-columns: 1fr auto; }
          .history-list li span:last-child { grid-column: 1 / -1; }
          .week-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
          .day-card { min-height: 124px; }
          .recipe-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; }
          .recipe-tile { min-height: 78px; padding: 10px; }
          .recipe-tools, .inventory-toolbar { grid-template-columns: 1fr 1fr; }
          .recipe-tools label:first-child, .inventory-toolbar input { grid-column: 1 / -1; }
          .table-scroll { overflow: visible; border: 0; background: transparent; }
          .inventory-table, .inventory-table tbody { display: block; width: 100%; }
          .inventory-table thead { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0, 0, 0, 0); }
          .inventory-table tr { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 10px; margin: 0 0 9px; padding: 10px; border: 1px solid var(--divider-color); border-radius: 12px; background: var(--card-background-color, var(--secondary-background-color)); }
          .inventory-table td { display: grid; grid-template-columns: minmax(82px, .7fr) 1fr; gap: 8px; padding: 4px 0; border: 0; font-size: .86rem; }
          .inventory-table td::before { content: attr(data-label); color: var(--secondary-text-color); font-size: .76rem; }
          .inventory-table td:first-child { grid-column: 1 / -1; font-size: 1rem; }
          .inventory-table td:first-child::before { content: ""; }
          .pagination { gap: 8px; font-size: .82rem; }
          .pagination button { padding-inline: 9px; }
          .location-list li { align-items: flex-start; }
          .location-list .actions { justify-content: flex-end; }
          .detail-grid { grid-template-columns: 1fr; }
          .picker-backdrop { padding: 0; }
          .picker-dialog { width: 100%; height: 100%; max-height: 100dvh; padding: max(14px, env(safe-area-inset-top)) 14px max(14px, env(safe-area-inset-bottom)); border-radius: 0; }
          .picker-heading h2 { font-size: 1.25rem; }
          .picker-tools { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin: 14px 0 10px; }
          .picker-search { grid-column: 1 / -1; }
          .picker-tools > button { min-height: 44px; }
          .picker-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); grid-auto-rows: minmax(124px, auto); gap: 9px; }
          .meal-tile { min-height: 124px; padding: 12px; }
          .meal-tile-name { font-size: .94rem; }
          .picker-footer { align-items: stretch; flex-direction: column; gap: 10px; }
          .picker-pages { justify-content: space-between; }
          .picker-actions { display: grid; grid-template-columns: 1fr 1fr; }
          .picker-actions button { min-height: 46px; }
        }
        @media (min-width: 601px) and (max-width: 980px) {
          .week-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
          .picker-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
          .picker-tools { grid-template-columns: repeat(3, minmax(0, 1fr)); }
          .picker-search { grid-column: span 2; }
        }
      </style>
      <main>
        <header>
          <div>
            <h1>${title[0]}</h1>
            <div class="muted">${title[1]}</div>
          </div>
          ${this._view === "kitchen" ? `<div class="actions"><button class="secondary" type="button" data-action="scan-barcode">Scan barcode</button><button type="button" data-action="create">Add product</button></div>` : this._view === "meals" ? `<button type="button" data-action="create-meal">Add meal</button>` : ""}
        </header>
        <nav aria-label="Kitchen Manager sections">
          <button type="button" data-action="navigate" data-view="kitchen" aria-current="${this._view === "kitchen" ? "page" : "false"}">My Kitchen</button>
          <button type="button" data-action="navigate" data-view="meals" aria-current="${this._view === "meals" ? "page" : "false"}">Meals</button>
          <button type="button" data-action="navigate" data-view="shopping" aria-current="${this._view === "shopping" ? "page" : "false"}">Shopping</button>
          <button type="button" data-action="navigate" data-view="settings" aria-current="${this._view === "settings" ? "page" : "false"}">Settings</button>
        </nav>
        <div class="error" data-error role="alert" ${this._error ? "" : "hidden"}>${this._escape(this._error)}</div>
        <div class="notice" role="status" ${this._plannerMessage ? "" : "hidden"}>${this._escape(this._plannerMessage)}</div>
        ${this._loading ? `<div class="loading" role="status">Loading ${this._view === "meals" ? "meals and planner" : this._view === "shopping" ? "shopping suggestions" : "kitchen inventory"}…</div>` : content}
        ${this._modal ? this._renderModal() : ""}
      </main>`;
    this._bindEvents();
    if (focusKey) {
      const restored = this.shadowRoot.querySelector(`[data-focus-key="${focusKey}"]`);
      restored?.focus();
      if (typeof selectionStart === "number" && typeof selectionEnd === "number") {
        restored?.setSelectionRange?.(selectionStart, selectionEnd);
      }
    } else if (this._modal?.type === "picker") {
      this.shadowRoot.querySelector("[data-picker-search]")?.focus();
    } else if (this._modal?.type === "barcode-scan") {
      this.shadowRoot.querySelector("#scan-barcode")?.focus();
    }
  }

  _renderKitchen(transactions) {
    const filtered = this._filteredInventory();
    const pageCount = Math.max(1, Math.ceil(filtered.length / 20));
    this._inventoryPage = Math.min(this._inventoryPage, pageCount);
    const pageItems = filtered.slice((this._inventoryPage - 1) * 20, this._inventoryPage * 20);
    const sortHeader = (key, label) => `<th scope="col"><button class="table-sort" type="button" data-action="sort-inventory" data-sort="${key}" aria-label="Sort by ${label}">${label}${this._inventorySort.key === key ? (this._inventorySort.direction === "asc" ? " ▲" : " ▼") : ""}</button></th>`;
    return `
      <div class="toolbar inventory-toolbar">
        <input data-product-search data-focus-key="product-search" type="search" value="${this._escape(this._search)}" placeholder="Search name, brand or barcode" aria-label="Search products">
        <select data-location-filter aria-label="Filter by storage location">
          <option value="any">All locations</option>
          ${this._locations.map((item) => `<option value="${this._escape(item.id)}" ${this._locationFilter === item.id ? "selected" : ""}>${this._escape(item.name)}</option>`).join("")}
        </select>
        <select data-low-stock-filter aria-label="Filter by low-stock status">
          <option value="any" ${this._lowStockFilter === "any" ? "selected" : ""}>All stock levels</option>
          <option value="low" ${this._lowStockFilter === "low" ? "selected" : ""}>Low stock</option>
          <option value="ok" ${this._lowStockFilter === "ok" ? "selected" : ""}>Not low</option>
        </select>
        <button class="secondary" type="button" data-action="refresh">Refresh</button>
      </div>
      ${!this._products.length ? `
        <section class="empty">
          <h2>${this._search ? "No matching products" : "Your catalogue is empty"}</h2>
          <p class="muted">${this._search ? "Try another search, or clear the search field." : "Create your first product to start tracking household stock."}</p>
          ${this._search ? `<button class="secondary" type="button" data-action="clear-search">Clear search</button>` : `<button type="button" data-action="create">Add product</button>`}
        </section>` : filtered.length ? `
      <div class="table-scroll">
        <table class="inventory-table">
          <thead><tr>${sortHeader("name", "Product")}${sortHeader("brand", "Brand")}${sortHeader("location", "Default location")}${sortHeader("quantity", "Current stock")}${sortHeader("low", "Status")}${sortHeader("expiry", "Nearest expiry")}</tr></thead>
          <tbody>${pageItems.map((row) => row.kind === "group" ? this._groupInventoryRows(row) : this._inventoryRow(row.record)).join("")}</tbody>
        </table>
      </div>
      <div class="pagination" aria-label="Inventory pages">
        <button class="secondary" type="button" data-action="inventory-previous" ${this._inventoryPage <= 1 ? "disabled" : ""}>Previous</button>
        <span>Page ${this._inventoryPage} of ${pageCount} — ${filtered.length} inventory rows</span>
        <button class="secondary" type="button" data-action="inventory-next" ${this._inventoryPage >= pageCount ? "disabled" : ""}>Next</button>
      </div>` : `<section class="empty"><h2>No products match these filters</h2><p class="muted">Try another search or filter.</p><button class="secondary" type="button" data-action="reset-inventory-filters">Clear filters</button></section>`}
      <section class="section history">
        <h2>Recent stock changes</h2>
        ${transactions ? `<ul class="history-list">${transactions}</ul>` : `<p class="muted">No stock changes recorded yet.</p>`}
      </section>`;
  }

  _filteredInventory() {
    const query = this._search.trim().toLocaleLowerCase();
    const matches = (record) => {
      const { product } = record;
      return (!query || [product.name, product.brand, product.barcode]
        .some((value) => String(value || "").toLocaleLowerCase().includes(query)))
        && (this._locationFilter === "any" || product.default_storage_location === this._locationFilter)
        && (this._lowStockFilter === "any" || (this._lowStockFilter === "low") === record.low_stock);
    };
    const rows = [];
    const groupedIds = new Set();
    for (const group of this._groups) {
      const members = this._products.filter((record) => record.product.group_id === group.id);
      members.forEach((record) => groupedIds.add(record.product.id));
      const locationMatches = this._locationFilter === "any"
        || members.some((record) => record.stock.some((stock) => stock.location === this._locationFilter)
          || record.product.default_storage_location === this._locationFilter);
      const searchMatches = !query
        || group.name.toLocaleLowerCase().includes(query)
        || members.some((record) => [record.product.name, record.product.brand, record.product.barcode]
          .some((value) => String(value || "").toLocaleLowerCase().includes(query)));
      const low = members.some((record) => record.low_stock);
      const lowMatches = this._lowStockFilter === "any"
        || (this._lowStockFilter === "low") === low;
      if (members.length && locationMatches && searchMatches && lowMatches) {
        rows.push({ kind: "group", group, members });
      }
    }
    for (const record of this._products) {
      if (!groupedIds.has(record.product.id) && matches(record)) {
        rows.push({ kind: "product", record });
      }
    }
    const { key, direction } = this._inventorySort;
    const value = (row) => {
      const group = row.kind === "group" ? row.group : null;
      const record = row.record;
      return ({
      name: (group?.name || record.product.name).toLocaleLowerCase(),
      brand: group ? row.members.map((item) => item.product.brand || "").join(", ").toLocaleLowerCase() : (record.product.brand || "").toLocaleLowerCase(),
      location: group ? row.group.locations.map((location) => this._locationName(location)).join(", ").toLocaleLowerCase() : this._locationName(record.product.default_storage_location).toLocaleLowerCase(),
      quantity: group ? row.group.stock_totals.reduce((sum, total) => sum + total.quantity, 0) : record.total_quantity,
      low: (group ? row.group.low_stock : record.low_stock) ? 0 : 1,
      expiry: "",
    })[key];
    };
    return rows.sort((left, right) => {
      const a = value(left);
      const b = value(right);
      const compare = typeof a === "number" ? a - b : String(a).localeCompare(String(b));
      return direction === "asc" ? compare : -compare;
    });
  }

  _groupInventoryRows(row) {
    const { group, members } = row;
    const expanded = this._expandedGroups.has(group.id);
    const locations = group.locations.map((location) => this._locationName(location));
    const locationLabel = locations.length === 1 ? locations[0] : locations.length ? "Multiple locations" : "—";
    const variants = expanded ? members.map((record) => this._inventoryRow(record, true)).join("") : "";
    return `<tr class="group-row">
      <td data-label="Product"><button class="group-toggle" type="button" data-action="toggle-group" data-group-id="${this._escape(group.id)}" aria-expanded="${expanded}" aria-label="${expanded ? "Collapse" : "Expand"} ${this._escape(group.name)}">${expanded ? "−" : "+"}</button><strong>${this._escape(group.name)}</strong><small>${group.variant_count} ${group.variant_count === 1 ? "variant" : "variants"}</small></td>
      <td data-label="Brand">—</td>
      <td data-label="Default location">${this._escape(locationLabel)}</td>
      <td data-label="Current stock">${this._escape(this._groupStockSummary(group))}</td>
      <td data-label="Status">${group.low_stock ? `<span class="badge">Low stock</span>` : "—"}</td>
      <td data-label="Nearest expiry">Not tracked</td>
    </tr>${variants}`;
  }

  _groupStockSummary(group) {
    if (!group.stock_totals.length) return "0 items";
    return group.stock_totals.map((total) => {
      const count = this._number(total.quantity);
      const stockUnit = total.unit === "item"
        ? (total.quantity === 1 ? "item" : "items")
        : total.unit;
      const packageInfo = total.package_size == null
        ? ""
        : ` · ${this._number(total.package_size)} ${total.package_unit} each`;
      return `${count} ${stockUnit}${packageInfo}`;
    }).join("; ");
  }

  _inventoryRow(record, variant = false) {
    const product = record.product;
    const stockLocations = [...new Set(record.stock.map((item) => item.location_name || this._locationName(item.location)))];
    const locationLabel = stockLocations.length
      ? stockLocations.join(", ")
      : this._locationName(product.default_storage_location);
    return `<tr class="${variant ? "variant-row" : ""}" tabindex="0" role="button" data-action="product-detail" data-product-id="${this._escape(product.id)}" aria-label="View ${this._escape(product.name)} details">
      <td data-label="Product"><strong>${this._escape(product.name)}</strong>${variant && product.package_size != null ? `<small>${this._number(product.package_size)} ${this._escape(product.package_unit)} each${product.barcode ? ` · Barcode ${this._escape(product.barcode)}` : ""}</small>` : ""}${variant && product.package_size == null && product.barcode ? `<small>Barcode ${this._escape(product.barcode)}</small>` : ""}</td>
      <td data-label="Brand">${this._escape(product.brand || "—")}</td>
      <td data-label="${variant ? "Storage location" : "Default location"}">${this._escape(locationLabel)}</td>
      <td data-label="Current stock">${this._escape(this._stockSummary(record))}</td>
      <td data-label="Status">${record.low_stock ? `<span class="badge">Low stock</span>` : "—"}</td>
      <td data-label="Nearest expiry">Not tracked</td>
    </tr>`;
  }

  _locationName(identifier) {
    return this._locations.find((item) => item.id === identifier)?.name || identifier || "—";
  }

  _stockSummary(record) {
    const stocked = record.stock.filter((item) => item.quantity > 0);
    if (!stocked.length) {
      return `0 ${record.stock[0]?.unit || "items"}`;
    }
    const units = new Set(stocked.map((item) => item.unit));
    if (units.size === 1) {
      return `${this._number(record.total_quantity)} ${stocked[0].unit}`;
    }
    return stocked.map((item) =>
      `${this._number(item.quantity)} ${item.unit} (${this._locationName(item.location)})`
    ).join("; ");
  }

  _renderSettings() {
    return `<section class="section">
      <div class="section-toolbar"><div><h2>Storage locations</h2><p class="muted">Location IDs remain stable when names change. Locations with product or stock history cannot be deleted.</p></div></div>
      <form class="location-create" data-form="location-create"><label for="new-location">Add location</label><input id="new-location" name="name" required maxlength="64" placeholder="e.g. Pantry"><button type="submit">Add location</button></form>
      ${this._locations.length ? `<ul class="location-list">${this._locations.map((item) => `<li><span><strong>${this._escape(item.name)}</strong><small>${this._escape(item.id)}</small></span><span class="actions"><button class="secondary" type="button" data-action="rename-location" data-location-id="${this._escape(item.id)}">Rename</button><button class="secondary danger" type="button" data-action="delete-location" data-location-id="${this._escape(item.id)}">Delete</button></span></li>`).join("")}</ul>` : `<div class="empty"><p>No locations configured.</p></div>`}
    </section>
    <section class="section group-settings">
      <div class="section-toolbar"><div><h2>Product groups</h2><p class="muted">Group related variants for inventory display. Product records and recipe references remain separate.</p></div></div>
      <form class="location-create" data-form="group-create"><label for="new-group">Create group</label><input id="new-group" name="name" required maxlength="100" placeholder="e.g. Lentils"><button type="submit">Create group</button></form>
      ${this._groups.length ? `<ul class="location-list">${this._groups.map((item) => `<li><span><strong>${this._escape(item.name)}</strong><small>${item.variant_count} ${item.variant_count === 1 ? "variant" : "variants"}</small></span><span class="actions"><button class="secondary" type="button" data-action="rename-group" data-group-id="${this._escape(item.id)}">Rename</button><button class="secondary danger" type="button" data-action="delete-group" data-group-id="${this._escape(item.id)}">Delete</button></span></li>`).join("")}</ul>` : `<div class="empty"><p>No product groups configured.</p></div>`}
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
    const matchingMeals = this._filteredMeals();
    const mealPageCount = Math.max(1, Math.ceil(matchingMeals.length / 25));
    this._mealPage = Math.min(this._mealPage, mealPageCount);
    const pageMeals = matchingMeals.slice((this._mealPage - 1) * 25, this._mealPage * 25);
    const mealTiles = pageMeals.map((meal) => `
      <button class="recipe-tile" type="button" data-action="edit-meal" data-meal-id="${this._escape(meal.id)}" aria-label="View and edit ${this._escape(meal.name)}">
        <strong>${this._escape(meal.name)}</strong>
        <span>${this._escape(meal.effort[0].toUpperCase() + meal.effort.slice(1))} · ${meal.time_minutes} min</span>
      </button>`).join("");
    const weeks = this._planner.weeks.map((week) => `
      <section class="week">
        <h2>Week of ${this._escape(this._formatDate(week.start_date))}</h2>
        <div class="week-grid">${week.days.map((day) => this._plannerDay(day)).join("")}</div>
      </section>`).join("");
    return `
      <section class="section">
        <div class="planner-toolbar"><div><h2>Four-week meal planner</h2><p class="muted">Suggestions are saved and can be regenerated. Choosing a meal makes it fixed; recurring meals repeat only when configured.</p></div>
          <button class="secondary" type="button" data-action="generate-planner" ${this._plannerGenerating || this._loading ? "disabled" : ""}>${this._plannerGenerating ? "Suggesting..." : "Suggest meals"}</button>
        </div>
        ${this._planner.weeks.length ? weeks : `<div class="loading">The planner is being prepared.</div>`}
      </section>
      <section class="section" style="margin-top:24px">
        <div class="planner-toolbar"><div><h2>Your meals</h2><p class="muted">Recipes can have optional ingredients and instructions.</p></div><button type="button" data-action="create-meal">Add meal</button></div>
        ${this._meals.length ? `<div class="recipe-tools">
          <label>Search recipes<input data-meal-search data-focus-key="meal-search" type="search" value="${this._escape(this._mealQuery)}" placeholder="Search recipe names"></label>
          <label>Effort<select data-meal-effort><option value="any">Any effort</option>${["low", "medium", "high"].map((item) => `<option value="${item}" ${this._mealEffort === item ? "selected" : ""}>${item[0].toUpperCase()}${item.slice(1)}</option>`).join("")}</select></label>
          <label>Maximum time<input data-meal-time type="number" min="0" step="1" value="${this._escape(this._mealMaxTime)}" placeholder="Any time"></label>
        </div>
        ${mealTiles ? `<div class="recipe-grid" aria-label="Recipes">${mealTiles}</div>
          <div class="pagination"><button class="secondary" type="button" data-action="recipe-previous" ${this._mealPage <= 1 ? "disabled" : ""}>Previous</button><span>Page ${this._mealPage} of ${mealPageCount} — ${matchingMeals.length} meals</span><button class="secondary" type="button" data-action="recipe-next" ${this._mealPage >= mealPageCount ? "disabled" : ""}>Next</button></div>`
          : `<div class="empty"><h3>No meals match these filters</h3><p class="muted">Try another search or adjust the effort and time filters.</p></div>`}`
          : `<div class="empty"><h3>No meals yet</h3><p class="muted">Add a meal to start building your recipe collection and planner.</p><button type="button" data-action="create-meal">Add your first meal</button></div>`}
      </section>`;
  }

  _filteredMeals() {
    const query = this._mealQuery.trim().toLocaleLowerCase();
    const maxTime = this._mealMaxTime === "" ? null : Number(this._mealMaxTime);
    return [...this._meals]
      .filter((meal) => (!query || meal.name.toLocaleLowerCase().includes(query))
        && (this._mealEffort === "any" || meal.effort === this._mealEffort)
        && (maxTime === null || meal.time_minutes <= maxTime))
      .sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
  }

  _plannerDay(day) {
    const status = this._dayStatus(day);
    return `<button type="button" class="day-card" data-action="open-picker" data-day-date="${this._escape(day.date)}" aria-label="${this._weekdayNames[day.weekday]}, ${this._formatDate(day.date)}: ${this._escape(day.meal_name || "Unplanned")}, ${status}${day.meal_eligible === false ? ", outside eligible weekdays" : ""}" aria-haspopup="dialog">
      <span class="day-date">${this._escape(this._formatDate(day.date, true))}</span>
      <h3>${this._weekdayNames[day.weekday]}</h3>
      <span class="day-meal">${this._escape(day.meal_name || "Unplanned")}</span>
      <span class="day-status" data-status="${status.toLowerCase()}">${status}</span>
      ${day.meal_eligible === false ? `<span class="day-warning">Outside eligible weekdays</span>` : ""}
    </button>`;
  }

  _dayStatus(day) {
    if (day.mode === "recurring") return "Recurring";
    if (day.mode === "random") return "Random";
    if (day.mode === "fixed") return "Fixed";
    if (day.mode === "override") {
      if (!day.recurring) return day.meal_id ? "Fixed" : "Unplanned";
      return day.meal_id ? "Override of recurring" : "Unplanned override";
    }
    return "Unplanned";
  }

  _openPicker(day) {
    this._picker = {
      date: day,
      search: "",
      effort: "any",
      maxTime: "",
      eligibleOnly: true,
      page: 1,
      order: this._meals.map((meal) => meal.id),
    };
    this._pickerSaving = false;
    this._error = "";
    this._modal = { type: "picker" };
    this._render();
  }

  _closePicker() {
    const day = this._picker?.date;
    this._picker = null;
    this._pickerSaving = false;
    this._modal = null;
    this._returnToPicker = false;
    this._render();
    if (day) {
      this.shadowRoot.querySelector(`[data-day-date="${day}"]`)?.focus();
    }
  }

  _filteredPickerMeals() {
    if (!this._picker) return [];
    const query = this._picker.search.trim().toLocaleLowerCase();
    const maxTime = this._picker.maxTime === "" ? null : Number(this._picker.maxTime);
    const selectedDay = this._planner.weeks
      .flatMap((week) => week.days)
      .find((day) => day.date === this._picker.date);
    const assignedMealId = selectedDay?.meal_id;
    const eligibleMealIds = new Set(
      this._planner.eligible_meal_ids_by_weekday?.[String(selectedDay?.weekday)] || [],
    );
    const byId = new Map(this._meals.map((meal) => [meal.id, meal]));
    const ordered = [
      ...this._picker.order.map((id) => byId.get(id)).filter(Boolean),
      ...this._meals.filter((meal) => !this._picker.order.includes(meal.id)),
    ];
    return ordered.filter((meal) =>
      (!query || meal.name.toLocaleLowerCase().includes(query))
      && (this._picker.effort === "any" || meal.effort === this._picker.effort)
      && (maxTime === null || meal.time_minutes <= maxTime)
      && (!this._picker.eligibleOnly || eligibleMealIds.has(meal.id) || meal.id === assignedMealId)
    );
  }

  _shufflePickerOrder() {
    if (!this._picker) return;
    const visibleIds = this._filteredPickerMeals().map((meal) => meal.id);
    const shuffled = [...visibleIds];
    for (let index = shuffled.length - 1; index > 0; index -= 1) {
      const other = Math.floor(Math.random() * (index + 1));
      [shuffled[index], shuffled[other]] = [shuffled[other], shuffled[index]];
    }
    if (shuffled.length > 1 && shuffled.every((id, index) => id === visibleIds[index])) {
      [shuffled[0], shuffled[1]] = [shuffled[1], shuffled[0]];
    }
    const visibleSet = new Set(visibleIds);
    this._picker.order = [
      ...shuffled,
      ...this._picker.order.filter((id) => !visibleSet.has(id)),
    ];
    this._picker.page = 1;
    this._render();
  }

  _renderPicker() {
    const picker = this._picker;
    if (!picker) return "";
    const matches = this._filteredPickerMeals();
    const pageCount = Math.max(1, Math.ceil(matches.length / 25));
    picker.page = Math.min(Math.max(picker.page, 1), pageCount);
    const pageMeals = matches.slice((picker.page - 1) * 25, picker.page * 25);
    const selected = this._planner.weeks
      .flatMap((week) => week.days)
      .find((day) => day.date === picker.date);
    const titleDate = selected
      ? `${this._weekdayNames[selected.weekday]}, ${this._formatDate(selected.date)}`
      : this._formatDate(picker.date);
    return `<div class="picker-backdrop" data-action="picker-backdrop">
      <section class="picker-dialog" role="dialog" aria-modal="true" aria-labelledby="picker-title" aria-describedby="picker-description" tabindex="-1">
        <div class="picker-heading">
          <div><h2 id="picker-title">Choose a meal</h2><p id="picker-description">${this._escape(titleDate)} · ${this._escape(selected?.meal_name ? `Currently ${selected.meal_name}` : "Currently unplanned")}</p></div>
          <button class="secondary" type="button" data-action="close-picker" aria-label="Close meal picker" ${this._pickerSaving ? "disabled" : ""}>Close</button>
        </div>
        <div class="picker-tools">
          <label class="picker-search">Search meals
            <input data-picker-search data-focus-key="picker-search" type="search" autocomplete="off" placeholder="Search recipe names" value="${this._escape(picker.search)}">
          </label>
          <label>Effort
            <select data-picker-effort data-focus-key="picker-effort">
              ${[["any", "Any effort"], ["low", "Low"], ["medium", "Medium"], ["high", "High"]].map(([value, label]) => `<option value="${value}" ${picker.effort === value ? "selected" : ""}>${label}</option>`).join("")}
            </select>
          </label>
          <label>Maximum time (minutes)
            <input data-picker-time data-focus-key="picker-time" type="number" min="0" step="1" placeholder="Any time" value="${this._escape(picker.maxTime)}">
          </label>
          <label class="eligible-toggle"><input data-picker-eligible data-focus-key="picker-eligible" type="checkbox" ${picker.eligibleOnly ? "checked" : ""}> Eligible for ${this._weekdayNames[selected?.weekday ?? this._weekdayIndex(picker.date)]}</label>
          <button class="secondary" type="button" data-action="shuffle-picker" title="Shuffle the displayed recipes">Shuffle</button>
        </div>
        ${this._error ? `<div class="picker-error" role="alert">${this._escape(this._error)}</div>` : ""}
        ${pageMeals.length ? `<div class="picker-grid" aria-label="Meals, page ${picker.page}">${pageMeals.map((meal) => `
          <button type="button" class="meal-tile" data-action="choose-meal" data-meal-id="${this._escape(meal.id)}" aria-pressed="${selected?.meal_id === meal.id}" ${this._pickerSaving ? "disabled" : ""}>
            ${selected?.meal_id === meal.id ? `<span class="meal-tile-current">Currently assigned</span>` : ""}
            <span class="meal-tile-name">${this._escape(meal.name)}</span>
            <span class="meal-tile-meta"><span>${this._escape(meal.effort[0].toUpperCase() + meal.effort.slice(1))}</span>${meal.time_minutes > 0 ? `<span>${meal.time_minutes} min</span>` : ""}</span>
          </button>`).join("")}</div>` : `<div class="picker-empty" role="status"><div><strong>${this._meals.length ? "No meals match these options" : "Your meal collection is empty"}</strong><p>${this._meals.length ? "Try another search or adjust the filters." : "Create a meal to start filling your planner."}</p></div></div>`}
        <div class="picker-footer">
          <div class="picker-pages">
            <button class="secondary" type="button" data-action="picker-previous" ${picker.page <= 1 || this._pickerSaving ? "disabled" : ""}>Previous</button>
            <span class="picker-page-count">Page ${picker.page} of ${pageCount} — ${matches.length} ${matches.length === 1 ? "meal" : "meals"}</span>
            <button class="secondary" type="button" data-action="picker-next" ${picker.page >= pageCount || this._pickerSaving ? "disabled" : ""}>Next</button>
          </div>
          <div class="picker-actions">
            ${selected?.recurring && selected.mode !== "recurring" ? `<button class="secondary" type="button" data-action="restore-recurrence" ${this._pickerSaving ? "disabled" : ""}>Use recurring meal</button>` : ""}
            ${!selected?.recurring ? `<button class="secondary" type="button" data-action="suggest-day" ${this._pickerSaving ? "disabled" : ""}>${["fixed", "override"].includes(selected?.mode) ? "Release to random" : "Suggest a random meal"}</button>` : ""}
            <button class="secondary" type="button" data-action="clear-picker-day" ${this._pickerSaving ? "disabled" : ""}>${selected?.meal_id ? "Clear day" : "Leave unplanned"}</button>
            <button class="secondary" type="button" data-action="picker-add-meal" ${this._pickerSaving ? "disabled" : ""}>Add new meal</button>
          </div>
        </div>
        ${this._pickerSaving ? `<div class="picker-saving" role="status">Saving meal…</div>` : ""}
      </section>
    </div>`;
  }

  _weekdayIndex(day) {
    const date = new Date(`${day}T12:00:00`);
    return Number.isNaN(date.valueOf()) ? 0 : (date.getDay() + 6) % 7;
  }

  async _choosePickerMeal(mealId) {
    if (!this._picker || this._pickerSaving) return;
    this._pickerSaving = true;
    this._error = "";
    this._render();
    try {
      const updatedDay = await this._request("planner/set", {
        date: this._picker.date,
        meal_id: mealId,
        allow_ineligible: !this._picker.eligibleOnly,
      });
      this._updatePlannerDay(updatedDay);
      this._closePicker();
      await this._loadMeals();
    } catch (error) {
      this._pickerSaving = false;
      this._error = error.message || "The meal could not be saved. Your previous selection is unchanged.";
      this._render();
    }
  }

  async _clearPickerDay() {
    if (!this._picker || this._pickerSaving) return;
    this._pickerSaving = true;
    this._error = "";
    this._render();
    try {
      const updatedDay = await this._request("planner/set", {
        date: this._picker.date,
        meal_id: null,
      });
      this._updatePlannerDay(updatedDay);
      this._closePicker();
      await this._loadMeals();
    } catch (error) {
      this._pickerSaving = false;
      this._error = error.message || "The day could not be cleared. Your previous selection is unchanged.";
      this._render();
    }
  }

  async _restorePickerRecurrence() {
    if (!this._picker || this._pickerSaving) return;
    this._pickerSaving = true;
    this._error = "";
    this._render();
    try {
      const updatedDay = await this._request("planner/set", {
        date: this._picker.date,
        meal_id: null,
        use_recurrence: true,
      });
      this._updatePlannerDay(updatedDay);
      this._closePicker();
      await this._loadMeals();
    } catch (error) {
      this._pickerSaving = false;
      this._error = error.message || "The recurring meal could not be restored. Your previous selection is unchanged.";
      this._render();
    }
  }

  _updatePlannerDay(day) {
    if (!day?.date) return;
    for (const week of this._planner.weeks) {
      const index = week.days.findIndex((entry) => entry.date === day.date);
      if (index !== -1) {
        week.days[index] = day;
        return;
      }
    }
  }

  _handleDialogKeydown(event) {
    if (!this._modal) return;
    if (event.key === "Escape") {
      if (this._pickerSaving) return;
      event.preventDefault();
      if (this._modal.type === "picker") {
        this._closePicker();
      } else {
        this._closeModal();
      }
      return;
    }
    if (event.key !== "Tab") return;
    const dialog = this.shadowRoot.querySelector('[role="dialog"]');
    if (!dialog) return;
    const focusable = [...dialog.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]')];
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && this.shadowRoot.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && this.shadowRoot.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  _closeModal() {
    if (this._modal?.type === "meal" && this._returnToPicker) {
      this._modal = { type: "picker" };
      this._returnToPicker = false;
      this._modalError = "";
      this._render();
      return;
    }
    this._modal = null;
    this._modalError = "";
    this._render();
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

  _transactionRow(item) {
    const date = new Date(item.timestamp);
    const time = Number.isNaN(date.valueOf()) ? item.timestamp : date.toLocaleString();
    const changed = item.quantity_changed > 0 ? `+${this._number(item.quantity_changed)}` : this._number(item.quantity_changed);
    return `<li>
      <span>${this._escape(time)}</span>
      <span>${this._escape(item.operation)} · ${this._escape(this._locationName(item.location))}</span>
      <span>${changed} → ${this._number(item.new_quantity)}</span>
    </li>`;
  }

  _renderModal() {
    if (this._modal.type === "picker") {
      return this._renderPicker();
    }
    if (this._modal.type === "barcode-scan") {
      return `<div class="modal-backdrop" data-action="backdrop"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
        <div class="modal-head"><h2 id="modal-title">Add stock by barcode</h2><button class="secondary" type="button" data-action="close" aria-label="Close">×</button></div>
        ${this._modalErrorMarkup()}
        <p class="muted">Scan or enter a barcode. A known barcode updates its exact product variant; new products are confirmed before they are saved.</p>
        <form data-form="barcode-scan" data-operation-id="${this._escape(this._modal.operationId)}">
          <label for="scan-barcode">Barcode</label><input id="scan-barcode" name="barcode" required autocomplete="off" inputmode="numeric">
          <label for="scan-quantity">Quantity to add</label><input id="scan-quantity" name="quantity" type="number" min="0.000001" step="any" value="1" required>
          <div class="form-actions"><button class="secondary" type="button" data-action="close">Cancel</button><button type="submit">Look up barcode</button></div>
        </form>
      </section></div>`;
    }
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
          ${this._modalErrorMarkup()}
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
            <div class="form-actions">
              ${meal ? `<button class="secondary danger recipe-delete" type="button" data-action="delete-meal" data-meal-id="${this._escape(meal.id)}">Delete meal</button>` : ""}
              <button class="secondary" type="button" data-action="close">Cancel</button><button type="submit">${meal ? "Save changes" : "Create meal"}</button>
            </div>
          </form>
        </section>
      </div>`;
    }
    if (this._modal.type === "product-detail") {
      const record = this._products.find((item) => item.product.id === this._modal.productId);
      if (!record) return "";
      const product = record.product;
      const recent = this._history.filter((item) => item.product_id === product.id).slice(0, 8);
      return `<div class="modal-backdrop" data-action="backdrop">
        <section class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
          <div class="modal-head"><h2 id="modal-title">${this._escape(product.name)}</h2><button class="secondary" type="button" data-action="close" aria-label="Close">×</button></div>
          ${this._modalErrorMarkup()}
          <div class="detail-grid">
            <div><strong>Brand</strong><div>${this._escape(product.brand || "—")}</div></div>
            <div><strong>Group</strong><div>${this._escape(product.group_name || "Ungrouped")}</div></div>
            <div><strong>Default location</strong><div>${this._escape(this._locationName(product.default_storage_location))}</div></div>
            <div><strong>Barcode</strong><div>${this._escape(product.barcode || "—")}</div></div>
            <div><strong>Package</strong><div>${product.package_size == null ? "—" : `${this._number(product.package_size)} ${this._escape(product.package_unit || "")}`}</div></div>
          </div>
          ${product.description ? `<p>${this._escape(product.description)}</p>` : ""}
          <h3>Current stock</h3>
          ${record.stock.length ? `<ul class="stock-list">${record.stock.map((item) => `<li><span>${this._escape(item.location_name || this._locationName(item.location))}</span><strong>${this._number(item.quantity)} ${this._escape(item.unit)}</strong></li>`).join("")}</ul>` : `<p class="muted">No stock recorded.</p>`}
          <div class="actions">
            <button type="button" data-action="stock" data-operation="add" data-product-id="${this._escape(product.id)}">Add stock</button>
            <button class="secondary" type="button" data-action="stock" data-operation="consume" data-product-id="${this._escape(product.id)}">Consume</button>
            <button class="secondary" type="button" data-action="stock" data-operation="set" data-product-id="${this._escape(product.id)}">Correct</button>
            <button class="secondary" type="button" data-action="edit" data-product-id="${this._escape(product.id)}">Edit</button>
          </div>
          <h3>Recent stock history</h3>
          ${recent.length ? `<ul class="detail-history">${recent.map((item) => `<li>${this._escape(item.operation)} ${this._number(Math.abs(item.quantity_changed))} ${this._escape(this._locationName(item.location))} · ${this._escape(new Date(item.timestamp).toLocaleString())}</li>`).join("")}</ul>` : `<p class="muted">No recent stock changes.</p>`}
        </section>
      </div>`;
    }
    if (this._modal.type === "location") {
      const location = this._modal.location;
      return `<div class="modal-backdrop" data-action="backdrop"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
        <div class="modal-head"><h2 id="modal-title">Rename location</h2><button class="secondary" type="button" data-action="close" aria-label="Close">×</button></div>
        ${this._modalErrorMarkup()}
        <form data-form="location-rename" data-location-id="${this._escape(location.id)}"><label for="location-name">Display name</label><input id="location-name" name="name" required maxlength="64" value="${this._escape(location.name)}"><div class="form-actions"><button class="secondary" type="button" data-action="close">Cancel</button><button type="submit">Save name</button></div></form>
      </section></div>`;
    }
    if (this._modal.type === "product-group") {
      const group = this._modal.group;
      return `<div class="modal-backdrop" data-action="backdrop"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
        <div class="modal-head"><h2 id="modal-title">Rename product group</h2><button class="secondary" type="button" data-action="close" aria-label="Close">×</button></div>
        ${this._modalErrorMarkup()}
        <form data-form="group-rename" data-group-id="${this._escape(group.id)}"><label for="group-name">Name</label><input id="group-name" name="name" required maxlength="100" value="${this._escape(group.name)}"><div class="form-actions"><button class="secondary" type="button" data-action="close">Cancel</button><button type="submit">Save name</button></div></form>
      </section></div>`;
    }
    if (this._modal.type === "product") {
      const product = this._modal.product || this._modal.prefill;
      const editing = Boolean(this._modal.product);
      const selectedGroupId = this._modal.selectedGroupId ?? product?.group_id ?? "";
      const productName = String(product?.name || "").toLocaleLowerCase();
      const suggestedGroupIds = new Set(
        this._groups
          .filter((group) => productName.includes(group.name.toLocaleLowerCase()))
          .map((group) => group.id),
      );
      return `<div class="modal-backdrop" data-action="backdrop">
        <section class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
          <div class="modal-head"><h2 id="modal-title">${editing ? "Edit product" : "Add product"}</h2><button class="secondary" type="button" data-action="close" aria-label="Close">×</button></div>
          ${this._modalErrorMarkup()}
          ${this._modal.lookupError ? `<div class="error" role="alert">Barcode lookup failed: ${this._escape(this._modal.lookupError)} Enter the product details manually below; the barcode and requested quantity will still be saved.</div>` : ""}
          <form data-form="product" data-product-id="${this._escape(this._modal.product?.id || "")}">
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
            <select id="default-location" name="default_storage_location" required>
              ${this._locationOptions(product?.default_storage_location || "cupboard")}
            </select>
            <label for="product-group">Inventory group (optional)</label>
            <select id="product-group" name="group_id">
              <option value="">Ungrouped</option>
              ${this._groups.map((group) => `<option value="${this._escape(group.id)}" ${group.id === selectedGroupId ? "selected" : ""}>${this._escape(group.name)}${suggestedGroupIds.has(group.id) ? " (suggested)" : ""}</option>`).join("")}
              <option value="__new__" ${selectedGroupId === "__new__" ? "selected" : ""}>Create a new group...</option>
            </select>
            <div data-new-group-fields ${selectedGroupId === "__new__" ? "" : "hidden"}>
              <label for="product-new-group">New group name</label>
              <input id="product-new-group" name="new_group_name" maxlength="100" ${selectedGroupId === "__new__" ? "required" : "disabled"}>
            </div>
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
        ${this._modalErrorMarkup()}
        <form data-form="stock" data-product-id="${this._escape(this._modal.productId)}" data-operation="${operation}">
          <label for="stock-quantity">${operation === "set" ? "New quantity" : "Quantity"}</label>
          <input id="stock-quantity" name="quantity" type="number" min="${operation === "set" ? "0" : "0.000001"}" step="any" required>
          <label for="stock-location">${operation === "add" ? "Storage location" : "Storage location override (optional)"}</label>
          <select id="stock-location" name="location">
            ${operation === "consume" ? `<option value="">Automatic when unambiguous</option>` : ""}
            ${this._locations.map((location) => `<option value="${this._escape(location.id)}" ${operation !== "consume" && location.id === (product?.default_storage_location || "cupboard") ? "selected" : ""}>${this._escape(location.name)}</option>`).join("")}
          </select>
          <div class="form-actions"><button class="secondary" type="button" data-action="close">Cancel</button><button type="submit">${operationLabel}</button></div>
        </form>
      </section>
    </div>`;
  }

  _modalErrorMarkup() {
    return this._modalError
      ? `<div class="error modal-error" role="alert">${this._escape(this._modalError)}</div>`
      : "";
  }

  _bindEvents() {
    this.shadowRoot.querySelectorAll("[data-action]").forEach((element) => {
      element.addEventListener("click", (event) => this._handleAction(event));
      if (element.matches("tr[role='button']")) {
        element.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            this._handleAction({ currentTarget: element, target: element });
          }
        });
      }
    });
    this.shadowRoot.querySelectorAll("form").forEach((form) => {
      form.addEventListener("submit", (event) => this._handleSubmit(event));
    });
    const inventorySearch = this.shadowRoot.querySelector("[data-product-search]");
    inventorySearch?.addEventListener("input", () => {
      this._search = inventorySearch.value;
      this._inventoryPage = 1;
      this._render();
    });
    this.shadowRoot.querySelector("[data-location-filter]")?.addEventListener("change", (event) => {
      this._locationFilter = event.currentTarget.value;
      this._inventoryPage = 1;
      this._render();
    });
    this.shadowRoot.querySelector("[data-low-stock-filter]")?.addEventListener("change", (event) => {
      this._lowStockFilter = event.currentTarget.value;
      this._inventoryPage = 1;
      this._render();
    });
    const productGroup = this.shadowRoot.querySelector("#product-group");
    productGroup?.addEventListener("change", () => {
      this._modal.selectedGroupId = productGroup.value;
      const newGroupFields = this.shadowRoot.querySelector("[data-new-group-fields]");
      const newGroupName = newGroupFields.querySelector("input");
      const createGroup = productGroup.value === "__new__";
      newGroupFields.hidden = !createGroup;
      newGroupName.disabled = !createGroup;
      newGroupName.required = createGroup;
      if (createGroup) newGroupName.focus();
    });
    const mealSearch = this.shadowRoot.querySelector("[data-meal-search]");
    mealSearch?.addEventListener("input", () => {
      this._mealQuery = mealSearch.value;
      this._mealPage = 1;
      this._render();
    });
    this.shadowRoot.querySelector("[data-meal-effort]")?.addEventListener("change", (event) => {
      this._mealEffort = event.currentTarget.value;
      this._mealPage = 1;
      this._render();
    });
    this.shadowRoot.querySelector("[data-meal-time]")?.addEventListener("input", (event) => {
      this._mealMaxTime = event.currentTarget.value;
      this._mealPage = 1;
      this._render();
    });
    const search = this.shadowRoot.querySelector("[data-picker-search]");
    search?.addEventListener("input", () => {
      this._picker.search = search.value;
      this._picker.page = 1;
      this._render();
    });
    const effort = this.shadowRoot.querySelector("[data-picker-effort]");
    effort?.addEventListener("change", () => {
      this._picker.effort = effort.value;
      this._picker.page = 1;
      this._render();
    });
    const maxTime = this.shadowRoot.querySelector("[data-picker-time]");
    maxTime?.addEventListener("input", () => {
      this._picker.maxTime = maxTime.value;
      this._picker.page = 1;
      this._render();
    });
    const eligible = this.shadowRoot.querySelector("[data-picker-eligible]");
    eligible?.addEventListener("change", () => {
      this._picker.eligibleOnly = eligible.checked;
      this._picker.page = 1;
      this._render();
    });
  }

  async _handleAction(event) {
    const element = event.currentTarget;
    const action = element.dataset.action;
    if (action === "backdrop" && event.target !== element) {
      return;
    }
    if (action === "picker-backdrop") {
      if (event.target === element && !this._pickerSaving) this._closePicker();
      return;
    } else if (action === "navigate") {
      await this._navigate(element.dataset.view);
      return;
    } else if (action === "create") {
      this._modalError = "";
      this._modal = { type: "product" };
    } else if (action === "scan-barcode") {
      this._modalError = "";
      this._modal = { type: "barcode-scan", operationId: this._newOperationId() };
    } else if (action === "edit") {
      const record = this._products.find((item) => item.product.id === element.dataset.productId);
      this._modalError = "";
      this._modal = {
        type: "product",
        product: record.product,
        ingredientName: record.ingredient_name || "",
      };
    } else if (action === "product-detail") {
      this._modal = { type: "product-detail", productId: element.dataset.productId };
    } else if (action === "stock") {
      this._modalError = "";
      this._modal = {
        type: "stock",
        productId: element.dataset.productId,
        operation: element.dataset.operation,
      };
    } else if (action === "create-meal") {
      this._modalError = "";
      this._mealIngredients = [];
      this._returnToPicker = this._picker !== null;
      this._modal = { type: "meal" };
    } else if (action === "edit-meal") {
      const meal = this._meals.find((item) => item.id === element.dataset.mealId);
      this._modalError = "";
      this._mealIngredients = meal.ingredients.map((item) => ({ ...item }));
      this._modal = { type: "meal", meal };
    } else if (action === "delete-meal") {
      const meal = this._meals.find((item) => item.id === element.dataset.mealId);
      if (meal && window.confirm(`Delete "${meal.name}"? Past planner entries will be retained.`)) {
        try {
          await this._request("meal/delete", { meal_id: meal.id });
          this._modal = null;
          this._modalError = "";
          await this._loadMeals();
        } catch (error) {
          this._showModalError(error.message || "The meal could not be deleted.");
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
      if (this._plannerGenerating) return;
      this._plannerGenerating = true;
      this._error = "";
      this._plannerMessage = "";
      this._render();
      try {
        const result = await this._request("planner/generate");
        const refreshed = await this._loadMeals();
        if (!refreshed) {
          this._error = `Suggestions were saved, but the planner could not be refreshed: ${this._error}`;
          return;
        }
        const changes = result.generated_count + result.replaced_count;
        const unavailable = result.unavailable_dates || [];
        const details = [];
        if (result.generated_count) details.push(`${result.generated_count} unplanned date${result.generated_count === 1 ? "" : "s"} filled`);
        if (result.replaced_count) details.push(`${result.replaced_count} random suggestion${result.replaced_count === 1 ? "" : "s"} replaced`);
        if (result.unchanged_random_count) details.push(`${result.unchanged_random_count} random suggestion${result.unchanged_random_count === 1 ? "" : "s"} unchanged because no better eligible alternative was available`);
        if (result.preserved_fixed_count) details.push(`${result.preserved_fixed_count} fixed assignment${result.preserved_fixed_count === 1 ? "" : "s"} kept`);
        if (result.preserved_recurring_count) details.push(`${result.preserved_recurring_count} recurring date${result.preserved_recurring_count === 1 ? "" : "s"} kept`);
        if (unavailable.length) {
          details.push(`no eligible meals for ${unavailable.map((day) => this._formatDate(day, true)).join(", ")}`);
        }
        this._plannerMessage = changes
          ? `Planner updated: ${details.join("; ")}.`
          : `No dates changed${details.length ? `: ${details.join("; ")}` : ": all dates are already fixed, recurring, or unavailable"}.`;
        this._render();
      } catch (error) {
        this._error = error.message || "Suggestions could not be generated.";
        this._render();
      } finally {
        this._plannerGenerating = false;
        this._render();
      }
      return;
    } else if (action === "open-picker") {
      this._openPicker(element.dataset.dayDate);
      return;
    } else if (action === "close-picker") {
      this._closePicker();
      return;
    } else if (action === "choose-meal") {
      await this._choosePickerMeal(element.dataset.mealId);
      return;
    } else if (action === "suggest-day") {
      await this._suggestPickerDay();
      return;
    } else if (action === "clear-picker-day") {
      await this._clearPickerDay();
      return;
    } else if (action === "restore-recurrence") {
      await this._restorePickerRecurrence();
      return;
    } else if (action === "shuffle-picker") {
      this._shufflePickerOrder();
      return;
    } else if (action === "picker-previous" || action === "picker-next") {
      const maxPage = Math.max(1, Math.ceil(this._filteredPickerMeals().length / 25));
      this._picker.page += action === "picker-next" ? 1 : -1;
      this._picker.page = Math.min(Math.max(this._picker.page, 1), maxPage);
      this._render();
      this.shadowRoot.querySelector('[data-action="picker-previous"]')?.focus();
      return;
    } else if (action === "sort-inventory") {
      const key = element.dataset.sort;
      this._inventorySort = {
        key,
        direction: this._inventorySort.key === key && this._inventorySort.direction === "asc" ? "desc" : "asc",
      };
      this._render();
      return;
    } else if (action === "toggle-group") {
      const groupId = element.dataset.groupId;
      if (this._expandedGroups.has(groupId)) {
        this._expandedGroups.delete(groupId);
      } else {
        this._expandedGroups.add(groupId);
      }
      this._render();
      return;
    } else if (action === "inventory-previous" || action === "inventory-next") {
      this._inventoryPage += action === "inventory-next" ? 1 : -1;
      this._render();
      return;
    } else if (action === "recipe-previous" || action === "recipe-next") {
      this._mealPage += action === "recipe-next" ? 1 : -1;
      this._render();
      return;
    } else if (action === "reset-inventory-filters") {
      this._search = "";
      this._locationFilter = "any";
      this._lowStockFilter = "any";
      this._inventoryPage = 1;
      this._render();
      return;
    } else if (action === "rename-location") {
      const location = this._locations.find((item) => item.id === element.dataset.locationId);
      if (location) {
        this._modalError = "";
        this._modal = { type: "location", location };
      }
    } else if (action === "rename-group") {
      const group = this._groups.find((item) => item.id === element.dataset.groupId);
      if (group) {
        this._modalError = "";
        this._modal = { type: "product-group", group };
      }
    } else if (action === "delete-group") {
      const group = this._groups.find((item) => item.id === element.dataset.groupId);
      if (group && window.confirm(`Delete "${group.name}"? Unassign all its variants first.`)) {
        try {
          await this._request("product-group/delete", { group_id: group.id });
          await this._loadSettings();
        } catch (error) {
          this._error = error.message || "The group could not be deleted.";
          this._render();
        }
      }
      return;
    } else if (action === "delete-location") {
      const location = this._locations.find((item) => item.id === element.dataset.locationId);
      if (location && window.confirm(`Delete the unused location "${location.name}"?`)) {
        try {
          await this._request("location/delete", { location_id: location.id });
          await this._loadSettings();
        } catch (error) {
          this._error = error.message || "The location could not be deleted.";
          this._render();
        }
      }
      return;
    } else if (action === "picker-add-meal") {
      this._mealIngredients = [];
      this._returnToPicker = true;
      this._modalError = "";
      this._modal = { type: "meal" };
      this._render();
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
      this._closeModal();
      return;
    } else if (action === "refresh") {
      await (this._view === "meals"
        ? this._loadMeals()
        : this._view === "shopping"
          ? this._loadShopping()
          : this._view === "settings"
            ? this._loadSettings()
            : this._load());
      return;
    } else if (action === "clear-search") {
      this._search = "";
      this._inventoryPage = 1;
      this._render();
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
      if (form.dataset.form === "barcode-scan") {
        const barcode = String(data.get("barcode") || "").trim();
        const quantity = Number(data.get("quantity"));
        const operationId = form.dataset.operationId;
        let lookup = null;
        let lookupError = "";
        try {
          lookup = await this._request("barcode/lookup", { barcode });
        } catch (error) {
          lookupError = error.message || "The product service is unavailable.";
        }
        if (!lookupError && lookup.matched) {
          const product = lookup.product;
          await this._request("barcode/register", {
            name: product.name,
            barcode,
            quantity,
            brand: product.brand || undefined,
            package_size: product.package_size ?? undefined,
            package_unit: product.package_unit || undefined,
            group_id: product.group_id || undefined,
            default_storage_location: product.default_storage_location,
            data_source: product.data_source,
            operation_id: operationId,
          });
          this._modal = null;
          this._modalError = "";
          await this._load();
          return;
        }
        this._modal = {
          type: "product",
          prefill: lookup?.product || { barcode },
          pendingBarcode: barcode,
          pendingQuantity: quantity,
          pendingOperationId: operationId,
          dataSource: lookup?.product?.data_source || "manual",
          lookupError,
        };
        this._modalError = "";
        this._render();
        return;
      }
      if (form.dataset.form === "location-create") {
        await this._request("location/create", { name: String(data.get("name") || "").trim() });
        await this._loadSettings();
        return;
      }
      if (form.dataset.form === "location-rename") {
        await this._request("location/rename", {
          location_id: form.dataset.locationId,
          name: String(data.get("name") || "").trim(),
        });
        this._modalError = "";
        this._modal = null;
        await this._loadSettings();
        return;
      }
      if (form.dataset.form === "group-create") {
        await this._request("product-group/create", {
          name: String(data.get("name") || "").trim(),
        });
        await this._loadSettings();
        return;
      }
      if (form.dataset.form === "group-rename") {
        await this._request("product-group/update", {
          group_id: form.dataset.groupId,
          name: String(data.get("name") || "").trim(),
        });
        this._modalError = "";
        this._modal = null;
        await this._loadSettings();
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
        const returnToPicker = this._returnToPicker;
        this._returnToPicker = false;
        this._modal = returnToPicker ? { type: "picker" } : null;
        this._modalError = "";
        this._mealIngredients = [];
        await this._loadMeals();
        return;
      } else {
        if (String(data.get("group_id") || "") === "__new__") {
          const groupName = String(data.get("new_group_name") || "").trim();
          this._modal.selectedGroupId = "__new__";
          if (!groupName) {
            throw new Error("Enter a name for the new product group.");
          }
          const result = await this._request("product-group/create", {
            name: groupName,
          });
          this._groups.push({ ...result.group, variant_count: 0 });
          this._modal.selectedGroupId = result.group.id;
          data.set("group_id", result.group.id);
        }
        const fields = this._productFields(data, form.dataset.productId);
        if (form.dataset.productId) {
          await this._request("product/update", {
            product_id: form.dataset.productId,
            ...fields.update,
          });
        } else {
          if (this._modal.pendingBarcode) {
            await this._request("barcode/register", {
              ...fields.create,
              barcode: this._modal.pendingBarcode,
              quantity: this._modal.pendingQuantity,
              operation_id: this._modal.pendingOperationId,
            });
          } else {
            await this._request("product/create", fields.create);
          }
        }
      }
      this._modal = null;
      this._modalError = "";
      await (this._view === "meals"
        ? this._loadMeals()
        : this._view === "settings"
          ? this._loadSettings()
          : this._load());
    } catch (error) {
      const message = error.message || "The change could not be saved.";
      if (this._modal) {
        this._showModalError(message);
      } else {
        this._error = message;
        this._showError(message);
      }
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
    const groupId = String(data.get("group_id") || "").trim();
    if (!defaultLocation) {
      throw new Error("Enter a default storage location.");
    }
    if (Boolean(packageSize) !== Boolean(packageUnit)) {
      throw new Error("Enter both package size and package unit, or leave both blank.");
    }
    const create = { name, default_storage_location: defaultLocation };
    const update = { name, default_storage_location: defaultLocation, clear_fields: [] };
    if (groupId) {
      create.group_id = groupId;
      update.group_id = groupId;
    } else if (productId) {
      const current = this._products.find((item) => item.product.id === productId);
      if (current?.product.group_id) update.clear_fields.push("group");
    }
    if (!productId && this._modal.dataSource) {
      create.data_source = this._modal.dataSource;
    }
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

  _newOperationId() {
    return window.crypto?.randomUUID?.()
      || `scan-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }

  _showError(message) {
    const error = this.shadowRoot.querySelector("[data-error]");
    if (error) {
      error.textContent = message;
      error.hidden = false;
    }
  }

  _showModalError(message) {
    this._modalError = message;
    const dialog = this.shadowRoot.querySelector('[role="dialog"]');
    const heading = dialog?.querySelector(".modal-head");
    if (!dialog || !heading) return;
    let error = dialog.querySelector(".modal-error");
    if (!error) {
      error = document.createElement("div");
      error.className = "error modal-error";
      error.setAttribute("role", "alert");
      heading.insertAdjacentElement("afterend", error);
    }
    error.textContent = message;
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
