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
      tramTitle: "Trams",
      busTitle: "Buses",
      transitTitle: "Buses + Trams",
      trainTitle: "Trains",
      windowMinutes: 60,
      softRouteFilter: true,
      ...config,
    };
    this._state = this._state || this._initialState();
    this._ensureSections();
    this._loadDefaults();
    if (this._hass && !this._initialized) {
      this._initialized = true;
      this._loadDefaultDepartures();
    }
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._state && !this._initialized) {
      this._initialized = true;
      this._loadDefaults();
      this._loadDefaultDepartures();
    }
  }

  getCardSize() {
    return 8;
  }

  _initialState() {
    return Object.fromEntries(this._sectionConfigs().map((section) => [
      section.kind,
      this._emptySection(section.kind),
    ]));
  }

  _ensureSections() {
    for (const section of this._sectionConfigs()) {
      this._state[section.kind] = this._state[section.kind] || this._emptySection(section.kind);
    }
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
      searchOpen: false,
      activeIndex: -1,
      routeFilter: "",
    };
  }

  _sectionConfigs() {
    return [
      {
        kind: "tram",
        apiKind: "transit",
        mode: "tram",
        title: this._config?.tramTitle || "Trams",
        placeholder: "Search tram stop",
        ariaLabel: "Tram stop",
        icon: "mdi:tram",
      },
      {
        kind: "bus",
        apiKind: "transit",
        mode: "bus",
        title: this._config?.busTitle || "Buses",
        placeholder: "Search bus stop",
        ariaLabel: "Bus stop",
        icon: "mdi:bus",
      },
      {
        kind: "elron",
        apiKind: "elron",
        mode: "",
        title: this._config?.trainTitle || "Trains",
        placeholder: "Search train station",
        ariaLabel: "Train station",
        icon: "mdi:train",
      },
    ];
  }

  _sectionConfig(kind) {
    return this._sectionConfigs().find((section) => section.kind === kind);
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
    for (const sectionConfig of this._sectionConfigs()) {
      const section = this._state[sectionConfig.kind];
      const value = this._readLocalStorage(this._storageKey(sectionConfig.kind));
      section.defaultStation = value;
      if (!section.selected) {
        section.selected = value;
        section.query = value;
      }
    }
  }

  async _loadDefaultDepartures() {
    for (const sectionConfig of this._sectionConfigs()) {
      if (this._state[sectionConfig.kind].selected) {
        await this._loadDepartures(sectionConfig.kind);
      }
    }
  }

  async _callApi(path) {
    if (!this._hass || typeof this._hass.callApi !== "function") {
      throw new Error("Home Assistant API is not ready");
    }
    return this._hass.callApi("GET", path);
  }

  _apiPath(kind, resource, params = {}) {
    const sectionConfig = this._sectionConfig(kind);
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== "") {
        search.set(key, String(value));
      }
    }
    if (sectionConfig.mode) {
      search.set("mode", sectionConfig.mode);
    }
    const suffix = search.toString();
    return `tallinn_widgets/${sectionConfig.apiKind}/${resource}${suffix ? `?${suffix}` : ""}`;
  }

  _debouncedStationSearch(kind, query) {
    const section = this._state[kind];
    section.query = query;
    section.selected = query;
    section.error = "";
    section.searchOpen = true;
    section.activeIndex = -1;
    this._syncPickerControls(kind);
    this._updateSearchStatus(kind);
    window.clearTimeout(section.timer);
    section.timer = window.setTimeout(() => this._loadStations(kind, query), 250);
  }

  async _loadStations(kind, query) {
    const section = this._state[kind];
    const trimmed = query.trim();
    section.requestId += 1;
    const requestId = section.requestId;

    if (trimmed.length < 2) {
      section.loadingStations = false;
      section.stations = [];
      section.searchOpen = Boolean(trimmed);
      this._updateSearchStatus(kind);
      this._updateStationResults(kind);
      return;
    }

    section.loadingStations = true;
    this._updateSearchStatus(kind);
    try {
      const path = this._apiPath(kind, "stations", {q: trimmed, limit: 50});
      const payload = await this._callApi(path);
      if (requestId === section.requestId) {
        section.stations = payload.stations || [];
        section.error = "";
        section.searchOpen = true;
      }
    } catch (err) {
      if (requestId === section.requestId) {
        section.error = err.message || String(err);
        section.stations = [];
        section.searchOpen = true;
      }
    } finally {
      if (requestId === section.requestId) {
        section.loadingStations = false;
      }
      this._updateSearchStatus(kind);
      this._updateStationResults(kind);
    }
  }

  async _loadDepartures(kind) {
    const section = this._state[kind];
    const station = section.selected.trim();
    if (!station) {
      section.payload = null;
      section.updatedAt = "";
      section.error = "";
      section.searchOpen = false;
      this._render();
      return;
    }

    section.loadingDepartures = true;
    section.searchOpen = false;
    this._render();
    try {
      const windowMinutes = Number(this._config.windowMinutes) || 60;
      const path = this._apiPath(kind, "departures", {
        station,
        window: windowMinutes,
        limit: 80,
      });
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

  _selectStation(kind, station) {
    const section = this._state[kind];
    section.selected = station;
    section.query = station;
    section.searchOpen = false;
    section.activeIndex = -1;
    section.routeFilter = "";
    const input = this.querySelector(`[data-station-input="${kind}"]`);
    if (input) {
      input.value = station;
    }
    this._updateStationResults(kind);
    this._syncPickerControls(kind);
    this._loadDepartures(kind);
  }

  _toggleRouteFilter(kind, route) {
    const section = this._state[kind];
    const nextRoute = String(route || "").trim();
    if (!section || !nextRoute || this._config.softRouteFilter === false) {
      return;
    }
    section.routeFilter = section.routeFilter === nextRoute ? "" : nextRoute;
    this._render();
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

  _moveActiveResult(kind, delta) {
    const section = this._state[kind];
    const count = section.stations.length;
    if (!count) {
      return;
    }
    section.searchOpen = true;
    section.activeIndex = (section.activeIndex + delta + count) % count;
    this._updateStationResults(kind);
  }

  _syncPickerControls(kind) {
    const section = this._state[kind];
    const saveButton = this.querySelector(`[data-save-default="${kind}"]`);
    if (saveButton) {
      saveButton.disabled = !section.selected.trim();
    }
  }

  _updateSearchStatus(kind) {
    const section = this._state[kind];
    const status = this.querySelector(`[data-search-status="${kind}"]`);
    if (!status) {
      return;
    }
    if (section.loadingStations) {
      status.textContent = "Searching...";
    } else if (section.error && section.searchOpen) {
      status.textContent = section.error;
    } else {
      status.textContent = "";
    }
  }

  _updateStationResults(kind) {
    const container = this.querySelector(`[data-results="${kind}"]`);
    if (!container) {
      return;
    }
    container.innerHTML = this._stationResults(kind);
    this._bindResultEvents(kind);
  }

  _stationResults(kind) {
    const section = this._state[kind];
    const query = section.query.trim();
    if (!section.searchOpen || query.length < 2) {
      return "";
    }
    if (!section.loadingStations && !section.stations.length && !section.error) {
      return `<div class="tw-result-empty">No matches</div>`;
    }
    if (!section.stations.length) {
      return "";
    }
    return `
      <div class="tw-results-list" role="listbox">
        ${section.stations
          .map((station, index) => this._stationResult(kind, station, index))
          .join("")}
      </div>
    `;
  }

  _stationResult(kind, station, index) {
    const section = this._state[kind];
    const active = index === section.activeIndex;
    const meta = station.modes ? station.modes.join(", ") : station.message || "";
    return `
      <button
        class="tw-result ${active ? "is-active" : ""}"
        data-result-kind="${this._escape(kind)}"
        data-result-station="${this._escape(station.name)}"
        role="option"
        aria-selected="${active ? "true" : "false"}"
        type="button"
      >
        <span>${this._escape(station.name)}</span>
        ${meta ? `<small>${this._escape(meta)}</small>` : ""}
      </button>
    `;
  }

  _section(kind, title) {
    const section = this._state[kind];
    const sectionConfig = this._sectionConfig(kind);
    const selected = this._escape(section.selected);
    const defaultText = section.defaultStation
      ? `Default: ${this._escape(section.defaultStation)}`
      : "No default set";

    return `
      <ha-card class="tw-section-card">
        <section class="tw-section" data-section="${this._escape(kind)}">
          <div class="tw-section-header">
            <div class="tw-heading">
              <ha-icon icon="${this._escape(sectionConfig.icon)}"></ha-icon>
              <div>
                <h3>${this._escape(title)}</h3>
                <div class="tw-subtitle">Next ${Number(this._config.windowMinutes) || 60} minutes</div>
              </div>
            </div>
            <button class="tw-icon-button" data-refresh="${kind}" title="Refresh" aria-label="Refresh ${this._escape(title)} departures">
              <ha-icon icon="mdi:refresh"></ha-icon>
            </button>
          </div>
          <div class="tw-picker">
            <div class="tw-search-row">
              <input
                class="tw-input"
                data-station-input="${kind}"
                aria-label="${this._escape(sectionConfig.ariaLabel)}"
                placeholder="${this._escape(sectionConfig.placeholder)}"
                value="${selected}"
                autocomplete="off"
                spellcheck="false"
              />
              <button class="tw-load-button" data-load="${kind}">Show</button>
            </div>
            <div class="tw-search-status" data-search-status="${kind}"></div>
            <div class="tw-results" data-results="${kind}">${this._stationResults(kind)}</div>
          </div>
          <div class="tw-meta-actions">
            <span class="tw-default">${defaultText}</span>
            <button class="tw-link-button" data-save-default="${kind}" ${selected ? "" : "disabled"}>Set default</button>
            <button class="tw-link-button" data-clear-default="${kind}" ${section.defaultStation ? "" : "disabled"}>Clear</button>
          </div>
          ${section.loadingDepartures ? `<div class="tw-muted">Loading...</div>` : ""}
          ${section.error && !section.searchOpen ? `<div class="tw-error">${this._escape(section.error)}</div>` : ""}
          ${this._departures(kind)}
        </section>
      </ha-card>
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
    const activeRouteFilter = this._config.softRouteFilter === false ? "" : section.routeFilter;
    const listClass = `tw-list${activeRouteFilter ? " has-route-filter" : ""}`;
    return `
      <div
        class="${listClass}"
        aria-label="${this._escape(payload.station)} departures"
        data-active-route="${this._escape(activeRouteFilter)}"
      >
        ${rows.map((row) => this._departureRow(row, isTrain, kind, activeRouteFilter)).join("")}
      </div>
      <div class="tw-source">
        <span>${this._escape(payload.data_source || "")}</span>
        ${section.updatedAt ? `<span>${this._escape(this._formatUpdated(section.updatedAt))}</span>` : ""}
      </div>
    `;
  }

  _departureRow(row, isTrain, kind, activeRouteFilter) {
    const line = this._routeLabel(row, isTrain);
    const tone = this._departureTone(row.due);
    const toneClass = tone ? ` ${tone}` : "";
    const routeValue = this._routeValue(row, isTrain);
    const canFilter = this._config.softRouteFilter !== false && routeValue && routeValue !== "-";
    const isSelectedRoute = Boolean(activeRouteFilter && routeValue === activeRouteFilter);
    const isMutedRoute = Boolean(activeRouteFilter && routeValue !== activeRouteFilter);
    const routeClass = `tw-route${isSelectedRoute ? " is-selected" : ""}`;
    const routeBadge = canFilter
      ? `
        <button
          class="${routeClass}"
          data-route-kind="${this._escape(kind)}"
          data-route-value="${this._escape(routeValue)}"
          aria-pressed="${isSelectedRoute ? "true" : "false"}"
          title="${isSelectedRoute ? "Clear route focus" : `Focus route ${this._escape(routeValue)}`}"
          type="button"
        >${this._escape(line)}</button>
      `
      : `<span class="${routeClass}">${this._escape(line)}</span>`;
    return `
      <div class="tw-row${toneClass}${isMutedRoute ? " is-muted-by-route" : ""}">
        <span class="tw-due">${this._escape(row.due || "-")}</span>
        ${routeBadge}
        <span class="tw-arrow" aria-hidden="true">&rarr;</span>
        <span class="tw-destination">${this._escape(row.direction || "-")}</span>
        <span class="tw-time">${this._escape(row.time || "-")}</span>
      </div>
    `;
  }

  _routeLabel(row, isTrain) {
    if (isTrain) {
      return row.line || row.trip || "-";
    }
    return row.route || row.line || "-";
  }

  _routeValue(row, isTrain) {
    return String(this._routeLabel(row, isTrain) || "").trim();
  }

  _departureTone(due) {
    const text = String(due || "").trim().toLowerCase();
    if (text === "now" || text === "0 min") {
      return "is-now";
    }
    const match = text.match(/^(\d+)/);
    if (match && Number(match[1]) <= 3) {
      return "is-soon";
    }
    return "";
  }

  _render() {
    if (!this._config || !this._state) {
      return;
    }

    const focus = this._captureFocus();
    this.innerHTML = `
      <style>
          tallinn-widgets-card {
            display: block;
          }
          .tw-board {
            box-sizing: border-box;
            display: grid;
            gap: 16px;
            width: 100%;
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
            gap: 20px;
            grid-template-columns: repeat(3, minmax(240px, 1fr));
          }
          .tw-section-card {
            display: block;
            min-width: 0;
          }
          .tw-section {
            box-sizing: border-box;
            min-width: 0;
            padding: 20px;
          }
          .tw-section-header {
            align-items: center;
            display: flex;
            gap: 12px;
            justify-content: space-between;
          }
          .tw-heading {
            align-items: center;
            display: flex;
            gap: 8px;
            min-width: 0;
          }
          .tw-heading ha-icon {
            --mdc-icon-size: 20px;
            color: var(--secondary-text-color);
            flex: 0 0 auto;
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
          .tw-search-status,
          .tw-result-empty {
            color: var(--secondary-text-color);
            font-size: 12px;
            line-height: 1.4;
          }
          .tw-picker {
            margin-top: 12px;
            position: relative;
          }
          .tw-search-row {
            align-items: center;
            display: grid;
            gap: 8px;
            grid-template-columns: minmax(0, 1fr) auto;
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
          .tw-search-status {
            min-height: 17px;
            padding-top: 4px;
          }
          .tw-results {
            left: 0;
            position: absolute;
            right: 0;
            top: 40px;
            z-index: 5;
          }
          .tw-results-list,
          .tw-result-empty {
            background: var(--card-background-color);
            border: 1px solid var(--divider-color);
            border-radius: 6px;
            box-shadow: 0 8px 16px rgba(0, 0, 0, 0.18);
            max-height: 220px;
            overflow: auto;
          }
          .tw-result-empty {
            padding: 10px;
          }
          .tw-result {
            align-items: flex-start;
            border: 0;
            border-bottom: 1px solid var(--divider-color);
            border-radius: 0;
            display: flex;
            flex-direction: column;
            gap: 2px;
            min-height: 42px;
            padding: 7px 10px;
            text-align: left;
            width: 100%;
          }
          .tw-result:last-child {
            border-bottom: 0;
          }
          .tw-result.is-active,
          .tw-result:hover {
            background: color-mix(in srgb, var(--primary-color) 12%, transparent);
          }
          .tw-result small {
            color: var(--secondary-text-color);
            font-size: 11px;
          }
          .tw-load-button {
            background: color-mix(in srgb, var(--primary-color) 12%, var(--card-background-color));
            border-color: color-mix(in srgb, var(--primary-color) 30%, var(--divider-color));
            color: var(--primary-text-color);
            min-width: 72px;
          }
          .tw-load-button:hover {
            background: color-mix(in srgb, var(--primary-color) 18%, var(--card-background-color));
          }
          .tw-meta-actions {
            align-items: center;
            display: flex;
            gap: 8px;
            margin: 2px 0 8px;
            min-height: 24px;
          }
          .tw-default {
            flex: 1 1 auto;
            min-width: 0;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
          }
          .tw-link-button {
            background: transparent;
            border: 0;
            color: var(--secondary-text-color);
            flex: 0 0 auto;
            font-size: 12px;
            min-height: 24px;
            min-width: 0;
            padding: 0 2px;
          }
          .tw-link-button:not(:disabled):hover {
            color: var(--primary-text-color);
          }
          .tw-icon-button {
            align-items: center;
            display: inline-flex;
            flex: 0 0 auto;
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
            margin-top: 10px;
          }
          .tw-row {
            align-items: center;
            border-bottom: 1px solid var(--divider-color);
            border-radius: 6px;
            display: grid;
            gap: 8px;
            grid-template-columns: minmax(42px, auto) minmax(28px, auto) auto minmax(0, 1fr) auto;
            min-height: 44px;
            margin: 0 -8px;
            padding: 8px;
          }
          .tw-row.is-now {
            background: color-mix(in srgb, var(--primary-color) 11%, transparent);
          }
          .tw-row.is-soon {
            background: color-mix(in srgb, var(--primary-color) 6%, transparent);
          }
          .tw-list.has-route-filter .tw-row:not(.is-muted-by-route) {
            background: color-mix(in srgb, var(--primary-color) 8%, transparent);
          }
          .tw-row.is-muted-by-route {
            filter: grayscale(0.75);
            opacity: 0.24;
          }
          .tw-row.is-muted-by-route:hover {
            opacity: 0.58;
          }
          .tw-row.is-now .tw-due,
          .tw-row.is-soon .tw-due {
            color: var(--primary-color);
          }
          .tw-due {
            color: var(--primary-text-color);
            font-size: 14px;
            font-weight: 700;
            white-space: nowrap;
          }
          .tw-time {
            color: var(--secondary-text-color);
            font-size: 12px;
            font-weight: 500;
            justify-self: end;
            text-align: right;
            white-space: nowrap;
          }
          .tw-route {
            background: color-mix(in srgb, var(--primary-color) 14%, transparent);
            border: 1px solid color-mix(in srgb, var(--primary-color) 34%, var(--divider-color));
            border-radius: 6px;
            box-sizing: border-box;
            color: var(--primary-text-color);
            display: inline-flex;
            font-size: 13px;
            font-weight: 700;
            justify-content: center;
            line-height: 1;
            max-width: 44px;
            min-height: 28px;
            min-width: 44px;
            overflow: hidden;
            padding: 5px 7px;
            text-overflow: ellipsis;
            white-space: nowrap;
            width: 44px;
          }
          button.tw-route {
            cursor: pointer;
          }
          button.tw-route:hover {
            background: color-mix(in srgb, var(--primary-color) 22%, transparent);
          }
          .tw-route.is-selected {
            background: var(--primary-color);
            border-color: var(--primary-color);
            box-shadow: 0 0 0 2px color-mix(in srgb, var(--primary-color) 18%, transparent);
            color: var(--text-primary-color);
          }
          .tw-arrow {
            color: var(--secondary-text-color);
            font-size: 12px;
            font-weight: 600;
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
          }
          .tw-source {
            margin-top: 8px;
          }
          @media (max-width: 1100px) {
            .tw-grid {
              grid-template-columns: 1fr;
            }
          }
          @media (max-width: 560px) {
            .tw-title-row {
              align-items: flex-start;
              flex-direction: column;
              gap: 2px;
            }
            .tw-search-row {
              grid-template-columns: 1fr;
            }
            .tw-load-button {
              width: 100%;
            }
            .tw-meta-actions {
              align-items: flex-start;
              flex-direction: column;
              gap: 2px;
            }
          }
      </style>
      <div class="tw-board">
        <div class="tw-title-row">
          <h2 class="tw-title">${this._escape(this._config.title)}</h2>
          <span class="tw-window">${Number(this._config.windowMinutes) || 60} min</span>
        </div>
        <div class="tw-grid">
          ${this._section("tram", this._config.tramTitle)}
          ${this._section("bus", this._config.busTitle)}
          ${this._section("elron", this._config.trainTitle)}
        </div>
      </div>
    `;
    this._bindEvents();
    this._restoreFocus(focus);
  }

  _bindEvents() {
    this.querySelectorAll("[data-station-input]").forEach((input) => {
      input.addEventListener("input", (event) =>
        this._debouncedStationSearch(input.dataset.stationInput, event.target.value)
      );
      input.addEventListener("keypress", (event) => event.stopPropagation(), true);
      input.addEventListener("keyup", (event) => event.stopPropagation(), true);
      input.addEventListener("keydown", (event) => {
        event.stopPropagation();
        const kind = input.dataset.stationInput;
        if (event.key === "Enter") {
          event.preventDefault();
          const section = this._state[kind];
          const station = section.activeIndex >= 0 && section.stations[section.activeIndex]
            ? section.stations[section.activeIndex].name
            : event.target.value;
          this._selectStation(kind, station);
        } else if (event.key === "ArrowDown") {
          event.preventDefault();
          this._moveActiveResult(kind, 1);
        } else if (event.key === "ArrowUp") {
          event.preventDefault();
          this._moveActiveResult(kind, -1);
        } else if (event.key === "Escape") {
          event.preventDefault();
          this._state[kind].searchOpen = false;
          this._updateStationResults(kind);
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
    this.querySelectorAll("[data-route-kind]").forEach((button) =>
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        this._toggleRouteFilter(button.dataset.routeKind, button.dataset.routeValue || "");
      })
    );
    for (const sectionConfig of this._sectionConfigs()) {
      this._bindResultEvents(sectionConfig.kind);
    }
  }

  _bindResultEvents(kind) {
    this.querySelectorAll(`[data-result-kind="${kind}"]`).forEach((button) => {
      button.addEventListener("mousedown", (event) => event.preventDefault());
      button.addEventListener("click", () =>
        this._selectStation(kind, button.dataset.resultStation || "")
      );
    });
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
