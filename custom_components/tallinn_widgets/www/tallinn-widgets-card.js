let tallinnWidgetsCardCounter = 0;

class TallinnWidgetsCard extends HTMLElement {
  constructor() {
    super();
    tallinnWidgetsCardCounter += 1;
    this._instanceId = `tallinn-widgets-${tallinnWidgetsCardCounter}`;
  }

  setConfig(config) {
    this._config = {
      title: "Transit Board",
      transitTitle: "Buses + Trams",
      trainTitle: "Trains",
      windowMinutes: 60,
      ...config,
    };
    this._state = this._state || {
      transit: this._emptySection("transit"),
      elron: this._emptySection("elron"),
    };
    this._loadDefaults();
    if (this._hass && !this._initialized) {
      this._initialized = true;
      this._refreshDefaults();
    }
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._state && !this._initialized) {
      this._initialized = true;
      this._loadDefaults();
      this._refreshDefaults();
    }
  }

  getCardSize() {
    return 6;
  }

  _emptySection(kind) {
    return {
      kind,
      selected: "",
      defaultStation: "",
      query: "",
      stations: [],
      payload: null,
      updatedAt: "",
      loadingStations: false,
      loadingDepartures: false,
      error: "",
      timer: null,
      requestId: 0,
    };
  }

  _storageKey(kind) {
    return `tallinn-widgets-card:${kind}:default-station`;
  }

  _readLocalStorage(key) {
    try {
      return window.localStorage.getItem(key) || "";
    } catch (_err) {
      return "";
    }
  }

  _writeLocalStorage(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (_err) {
      // Local browser storage is optional; the card still works without it.
    }
  }

  _removeLocalStorage(key) {
    try {
      window.localStorage.removeItem(key);
    } catch (_err) {
      // Local browser storage is optional; the card still works without it.
    }
  }

  _loadDefaults() {
    if (!this._state) {
      return;
    }
    for (const kind of ["transit", "elron"]) {
      const value = this._readLocalStorage(this._storageKey(kind));
      this._state[kind].defaultStation = value;
      if (!this._state[kind].selected) {
        this._state[kind].selected = value;
        this._state[kind].query = value;
      }
    }
  }

  async _refreshDefaults() {
    for (const kind of ["transit", "elron"]) {
      if (this._state[kind].selected) {
        await this._loadDepartures(kind);
      }
    }
  }

  async _callApi(path) {
    if (!this._hass || typeof this._hass.callApi !== "function") {
      throw new Error("Home Assistant API is not ready");
    }
    return this._hass.callApi("GET", path);
  }

  _debouncedStationSearch(kind, query) {
    const section = this._state[kind];
    section.query = query;
    section.selected = query;
    section.error = "";
    section.payload = null;
    window.clearTimeout(section.timer);
    section.timer = window.setTimeout(() => this._loadStations(kind, query), 250);
    this._render();
  }

  async _loadStations(kind, query) {
    const section = this._state[kind];
    const trimmed = query.trim();
    if (!trimmed && kind === "transit") {
      section.stations = [];
      this._render();
      return;
    }
    if (kind === "transit" && trimmed.length < 2) {
      section.stations = [];
      this._render();
      return;
    }

    section.loadingStations = true;
    section.requestId += 1;
    const requestId = section.requestId;
    this._render();
    try {
      const path = `tallinn_widgets/${kind}/stations?q=${encodeURIComponent(
        trimmed
      )}&limit=50`;
      const payload = await this._callApi(path);
      if (requestId === section.requestId) {
        section.stations = payload.stations || [];
        section.error = "";
      }
    } catch (err) {
      if (requestId === section.requestId) {
        section.error = err.message || String(err);
      }
    } finally {
      if (requestId === section.requestId) {
        section.loadingStations = false;
      }
      this._render();
    }
  }

  async _loadDepartures(kind) {
    const section = this._state[kind];
    const station = section.selected.trim();
    if (!station) {
      section.payload = null;
      section.updatedAt = "";
      section.error = "";
      this._render();
      return;
    }

    section.loadingDepartures = true;
    this._render();
    try {
      const windowMinutes = Number(this._config.windowMinutes) || 60;
      const path = `tallinn_widgets/${kind}/departures?station=${encodeURIComponent(
        station
      )}&window=${windowMinutes}&limit=80`;
      const payload = await this._callApi(path);
      section.payload = payload.payload || null;
      section.updatedAt = payload.updated_at || "";
      section.error = (payload.errors || []).join(", ");
    } catch (err) {
      section.payload = null;
      section.updatedAt = "";
      section.error = err.message || String(err);
    } finally {
      section.loadingDepartures = false;
      this._render();
    }
  }

  _saveDefault(kind) {
    const station = this._state[kind].selected.trim();
    if (!station) {
      return;
    }
    this._writeLocalStorage(this._storageKey(kind), station);
    this._state[kind].defaultStation = station;
    this._render();
  }

  _clearDefault(kind) {
    this._removeLocalStorage(this._storageKey(kind));
    this._state[kind].defaultStation = "";
    this._render();
  }

  _stationOptions(kind) {
    return (this._state[kind].stations || [])
      .map((station) => {
        const label = station.modes ? station.modes.join(", ") : station.message || "";
        return `<option value="${this._escape(station.name)}" label="${this._escape(
          label
        )}"></option>`;
      })
      .join("");
  }

  _section(kind, title) {
    const section = this._state[kind];
    const selected = this._escape(section.selected);
    const listId = `${this._instanceId}-${kind}-stations`;
    const isTransit = kind === "transit";
    const placeholder = isTransit ? "Search stop" : "Search station";
    const defaultText = section.defaultStation
      ? `<span class="tw-default">Default: ${this._escape(section.defaultStation)}</span>`
      : "";

    return `
      <section class="tw-section">
        <div class="tw-section-header">
          <div>
            <h3>${this._escape(title)}</h3>
            <div class="tw-subtitle">Next ${Number(this._config.windowMinutes) || 60} minutes</div>
          </div>
          <button class="tw-icon-button" data-refresh="${kind}" title="Refresh" aria-label="Refresh ${
            isTransit ? "public transit" : "train"
          } departures">
            <ha-icon icon="mdi:refresh"></ha-icon>
          </button>
        </div>
        <div class="tw-controls">
          <input
            class="tw-input"
            list="${listId}"
            data-station-input="${kind}"
            aria-label="${isTransit ? "Public transit stop" : "Train station"}"
            placeholder="${placeholder}"
            value="${selected}"
            autocomplete="off"
          />
          <datalist id="${listId}">${this._stationOptions(kind)}</datalist>
          <button class="tw-primary" data-load="${kind}">Show</button>
          <button data-save-default="${kind}" ${selected ? "" : "disabled"}>Set default</button>
          <button data-clear-default="${kind}" ${section.defaultStation ? "" : "disabled"}>Clear</button>
        </div>
        ${defaultText}
        ${section.loadingStations ? `<div class="tw-muted">Searching...</div>` : ""}
        ${section.loadingDepartures ? `<div class="tw-muted">Loading...</div>` : ""}
        ${section.error ? `<div class="tw-error">${this._escape(section.error)}</div>` : ""}
        ${this._departures(kind)}
      </section>
    `;
  }

  _departures(kind) {
    const section = this._state[kind];
    const payload = section.payload;
    if (!payload || !payload.station) {
      return `<div class="tw-empty">No station selected.</div>`;
    }

    const rows = payload.departures || [];
    if (!rows.length) {
      return `<div class="tw-empty">No departures in the next ${
        payload.window_minutes || 60
      } minutes.</div>`;
    }

    const isTrain = kind === "elron";
    return `
      <div class="tw-list" role="table" aria-label="${this._escape(payload.station)} departures">
        <div class="tw-list-head" role="row">
          <span>Due</span>
          <span>Time</span>
          <span>${isTrain ? "Train" : "Line"}</span>
          <span>To</span>
          <span>${isTrain ? "Track" : "Stop"}</span>
        </div>
        ${rows.map((row) => this._departureRow(row, isTrain)).join("")}
      </div>
      <div class="tw-source">
        <span>${this._escape(payload.data_source || "")}</span>
        ${section.updatedAt ? `<span>${this._escape(this._formatUpdated(section.updatedAt))}</span>` : ""}
      </div>
    `;
  }

  _departureRow(row, isTrain) {
    const line = isTrain ? row.trip || row.line || "-" : row.route || "-";
    const mode = isTrain ? row.platform || "-" : row.mode || "-";
    const detail = isTrain ? row.line || "" : row.stop_code || "";
    return `
      <div class="tw-row" role="row">
        <span class="tw-due" role="cell">${this._escape(row.due || "-")}</span>
        <span class="tw-time" role="cell">${this._escape(row.time || "-")}</span>
        <span class="tw-service" role="cell">
          <span class="tw-route">${this._escape(line)}</span>
          ${detail ? `<span class="tw-detail">${this._escape(detail)}</span>` : ""}
        </span>
        <span class="tw-destination" role="cell">${this._escape(row.direction || "-")}</span>
        <span class="tw-mode" role="cell">${this._escape(mode)}</span>
      </div>
    `;
  }

  _render() {
    if (!this._config || !this._state) {
      return;
    }

    const focus = this._captureFocus();
    this.innerHTML = `
      <ha-card>
        <style>
          .tw-card {
            padding: 16px;
          }
          .tw-title-row {
            align-items: baseline;
            display: flex;
            gap: 8px;
            justify-content: space-between;
            margin-bottom: 16px;
          }
          .tw-title {
            color: var(--primary-text-color);
            font-size: 18px;
            font-weight: 600;
            line-height: 1.25;
            margin: 0;
          }
          .tw-window {
            color: var(--secondary-text-color);
            flex: 0 0 auto;
            font-size: 12px;
            font-weight: 500;
          }
          .tw-grid {
            display: grid;
            gap: 18px;
          }
          .tw-section {
            border-top: 1px solid var(--divider-color);
            padding-top: 16px;
          }
          .tw-section:first-of-type {
            border-top: 0;
            padding-top: 0;
          }
          .tw-section-header {
            align-items: center;
            display: flex;
            gap: 12px;
            justify-content: space-between;
          }
          h3 {
            color: var(--primary-text-color);
            font-size: 15px;
            font-weight: 600;
            line-height: 1.25;
            margin: 0;
          }
          .tw-subtitle,
          .tw-default,
          .tw-muted,
          .tw-empty,
          .tw-source,
          .tw-detail {
            color: var(--secondary-text-color);
            font-size: 12px;
            line-height: 1.4;
          }
          .tw-controls {
            display: grid;
            gap: 8px;
            grid-template-columns: minmax(180px, 1fr) auto auto auto;
            margin: 12px 0 8px;
          }
          .tw-input,
          button {
            background: var(--card-background-color);
            border: 1px solid var(--divider-color);
            border-radius: 6px;
            box-sizing: border-box;
            color: var(--primary-text-color);
            font: inherit;
            min-height: 36px;
          }
          .tw-input {
            padding: 0 10px;
            width: 100%;
          }
          button {
            cursor: pointer;
            font-size: 13px;
            font-weight: 500;
            padding: 0 10px;
          }
          button:disabled {
            cursor: default;
            opacity: 0.45;
          }
          button:focus-visible,
          .tw-input:focus-visible {
            outline: 2px solid var(--primary-color);
            outline-offset: 2px;
          }
          .tw-primary {
            background: var(--primary-color);
            border-color: var(--primary-color);
            color: var(--text-primary-color, #fff);
          }
          .tw-icon-button {
            align-items: center;
            display: inline-flex;
            justify-content: center;
            padding: 0;
            width: 36px;
          }
          .tw-icon-button ha-icon {
            --mdc-icon-size: 18px;
          }
          .tw-error {
            color: var(--error-color);
            font-size: 13px;
            line-height: 1.4;
            margin: 6px 0;
          }
          .tw-empty {
            border-top: 1px solid var(--divider-color);
            margin-top: 12px;
            padding-top: 12px;
          }
          .tw-list {
            display: grid;
            margin-top: 12px;
          }
          .tw-list-head,
          .tw-row {
            align-items: center;
            display: grid;
            gap: 8px;
            grid-template-columns: minmax(44px, 0.55fr) minmax(48px, 0.6fr) minmax(58px, 0.8fr) minmax(120px, 1.4fr) minmax(48px, 0.65fr);
          }
          .tw-list-head {
            border-bottom: 1px solid var(--divider-color);
            color: var(--secondary-text-color);
            font-size: 11px;
            font-weight: 600;
            padding: 0 0 6px;
            text-transform: uppercase;
          }
          .tw-row {
            border-bottom: 1px solid var(--divider-color);
            min-height: 44px;
            padding: 7px 0;
          }
          .tw-due {
            color: var(--primary-text-color);
            font-size: 14px;
            font-weight: 700;
            white-space: nowrap;
          }
          .tw-time,
          .tw-mode {
            color: var(--primary-text-color);
            font-size: 13px;
            white-space: nowrap;
          }
          .tw-service {
            align-items: center;
            display: flex;
            gap: 6px;
            min-width: 0;
          }
          .tw-route {
            background: color-mix(in srgb, var(--primary-color) 14%, transparent);
            border: 1px solid color-mix(in srgb, var(--primary-color) 34%, var(--divider-color));
            border-radius: 6px;
            color: var(--primary-text-color);
            display: inline-flex;
            font-size: 13px;
            font-weight: 700;
            justify-content: center;
            line-height: 1;
            min-width: 28px;
            padding: 5px 7px;
          }
          .tw-destination {
            color: var(--primary-text-color);
            font-size: 13px;
            min-width: 0;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
          }
          .tw-source {
            display: flex;
            gap: 8px;
            justify-content: space-between;
            margin-top: 8px;
          }
          @media (max-width: 720px) {
            .tw-title-row {
              align-items: flex-start;
              flex-direction: column;
              gap: 2px;
            }
            .tw-controls {
              grid-template-columns: 1fr 1fr 1fr;
            }
            .tw-input {
              grid-column: 1 / -1;
            }
            .tw-list-head {
              display: none;
            }
            .tw-row {
              gap: 4px 8px;
              grid-template-columns: minmax(48px, auto) minmax(54px, auto) 1fr;
            }
            .tw-service {
              justify-content: flex-end;
            }
            .tw-destination {
              grid-column: 1 / -1;
              white-space: normal;
            }
            .tw-mode {
              color: var(--secondary-text-color);
              grid-column: 1 / -1;
            }
          }
        </style>
        <div class="tw-card">
          <div class="tw-title-row">
            <h2 class="tw-title">${this._escape(this._config.title)}</h2>
            <span class="tw-window">${Number(this._config.windowMinutes) || 60} min</span>
          </div>
          <div class="tw-grid">
            ${this._section("transit", this._config.transitTitle)}
            ${this._section("elron", this._config.trainTitle)}
          </div>
        </div>
      </ha-card>
    `;
    this._bindEvents();
    this._restoreFocus(focus);
  }

  _bindEvents() {
    this.querySelectorAll("[data-station-input]").forEach((input) => {
      input.addEventListener("input", (event) =>
        this._debouncedStationSearch(input.dataset.stationInput, event.target.value)
      );
      input.addEventListener("change", (event) => {
        this._state[input.dataset.stationInput].selected = event.target.value;
        this._loadDepartures(input.dataset.stationInput);
      });
      input.addEventListener("keypress", (event) => event.stopPropagation(), true);
      input.addEventListener("keyup", (event) => event.stopPropagation(), true);
      input.addEventListener("keydown", (event) => {
        event.stopPropagation();
        if (event.key === "Enter") {
          event.preventDefault();
          this._state[input.dataset.stationInput].selected = event.target.value;
          this._loadDepartures(input.dataset.stationInput);
        }
      }, true);
    });
    this.querySelectorAll("[data-load]").forEach((button) =>
      button.addEventListener("click", () => this._loadDepartures(button.dataset.load))
    );
    this.querySelectorAll("[data-refresh]").forEach((button) =>
      button.addEventListener("click", () => this._loadDepartures(button.dataset.refresh))
    );
    this.querySelectorAll("[data-save-default]").forEach((button) =>
      button.addEventListener("click", () => this._saveDefault(button.dataset.saveDefault))
    );
    this.querySelectorAll("[data-clear-default]").forEach((button) =>
      button.addEventListener("click", () => this._clearDefault(button.dataset.clearDefault))
    );
  }

  _captureFocus() {
    const input = this.querySelector("[data-station-input]:focus");
    if (!input) {
      return null;
    }
    return {
      kind: input.dataset.stationInput,
      start: input.selectionStart,
      end: input.selectionEnd,
    };
  }

  _restoreFocus(focus) {
    if (!focus) {
      return;
    }
    const input = this.querySelector(`[data-station-input="${focus.kind}"]`);
    if (!input) {
      return;
    }
    this._restoringFocus = true;
    try {
      input.focus();
      input.setSelectionRange(focus.start, focus.end);
    } catch (_err) {
      // Some input implementations do not support selection ranges.
    } finally {
      this._restoringFocus = false;
    }
  }

  _formatUpdated(value) {
    const timestamp = Date.parse(value);
    if (Number.isNaN(timestamp)) {
      return "";
    }
    return new Date(timestamp).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  _escape(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }
}

if (!customElements.get("tallinn-widgets-card")) {
  customElements.define("tallinn-widgets-card", TallinnWidgetsCard);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "tallinn-widgets-card")) {
  window.customCards.push({
    type: "tallinn-widgets-card",
    name: "Tallinn Widgets",
    description: "Selectable Tallinn public transport and Elron station departures",
  });
}
