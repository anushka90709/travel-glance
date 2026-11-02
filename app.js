(() => {
  // If the session cookie expires while the tab is open, any /api/* call
  // starts 401ing - bounce back to sign-in instead of failing silently.
  const _fetch = window.fetch;
  window.fetch = async (...args) => {
    const res = await _fetch(...args);
    if (res.status === 401) {
      window.location.href = "/login";
    }
    return res;
  };

  // Surface ANY uncaught error or rejected promise directly on the page,
  // not just in the browser console - so a failure during something like the
  // Drive attach flow (async callbacks, OAuth popups, etc.) is visible and
  // reportable without needing DevTools open.
  function showGlobalError(text) {
    const banner = document.getElementById("uploadStatus");
    if (!banner) return;
    banner.hidden = false;
    banner.classList.add("error");
    banner.textContent = text;
  }
  window.addEventListener("error", (e) => {
    showGlobalError(`Script error: ${e.message} (${e.filename ? e.filename.split("/").pop() : "?"}:${e.lineno})`);
  });
  window.addEventListener("unhandledrejection", (e) => {
    const reason = e.reason;
    const msg = reason && reason.message ? reason.message : String(reason);
    showGlobalError(`Unhandled error: ${msg}`);
  });

  const state = {
    trips: [],
    viewDate: startOfMonth(new Date()),
    showCancelled: true,
    directoryQuery: "",
    tripTypeFilter: "all", // "all" | "domestic" | "international"
    directoryAirline: "all",
    directoryPlace: "all",
    directoryBookingSource: "all",
    directoryDateFrom: "",
    directoryDateTo: "",
  };

  const el = {
    sideTabs: document.getElementById("sideTabs"),
    sidebarToggleBtn: document.getElementById("sidebarToggleBtn"),
    themeToggleBtn: document.getElementById("themeToggleBtn"),
    logoutBtn: document.getElementById("logoutBtn"),
    topbarUserTrigger: document.getElementById("topbarUserTrigger"),
    topbarUserMenu: document.getElementById("topbarUserMenu"),
    tabCalendarBtn: document.getElementById("tabCalendarBtn"),
    tabDirectoryBtn: document.getElementById("tabDirectoryBtn"),
    calendarView: document.getElementById("calendarView"),
    directoryView: document.getElementById("directoryView"),
    viewTitle: document.getElementById("viewTitle"),
    viewTagline: document.getElementById("viewTagline"),
    travelerSearch: document.getElementById("travelerSearch"),
    directoryTypeFilter: document.getElementById("directoryTypeFilter"),
    directoryAirlineFilter: document.getElementById("directoryAirlineFilter"),
    directoryPlaceFilter: document.getElementById("directoryPlaceFilter"),
    directoryBookingSourceFilter: document.getElementById("directoryBookingSourceFilter"),
    dateFilterDropdown: document.getElementById("dateFilterDropdown"),
    dateFilterBtn: document.getElementById("dateFilterBtn"),
    dateFilterLabel: document.getElementById("dateFilterLabel"),
    dateFilterMenu: document.getElementById("dateFilterMenu"),
    dateFilterThisMonth: document.getElementById("dateFilterThisMonth"),
    dateFilterCustom: document.getElementById("dateFilterCustom"),
    directoryDateFrom: document.getElementById("directoryDateFrom"),
    directoryDateTo: document.getElementById("directoryDateTo"),
    directoryClearFiltersBtn: document.getElementById("directoryClearFiltersBtn"),
    directoryCount: document.getElementById("directoryCount"),
    directoryTableBody: document.getElementById("directoryTableBody"),
    directoryEmpty: document.getElementById("directoryEmpty"),

    driveAttachBtn: document.getElementById("driveAttachBtn"),
    deviceAttachBtn: document.getElementById("deviceAttachBtn"),
    deviceFileInput: document.getElementById("deviceFileInput"),
    uploadStatus: document.getElementById("uploadStatus"),
    statTotalTrips: document.getElementById("statTotalTrips"),
    statConfirmedTrips: document.getElementById("statConfirmedTrips"),
    statTravelers: document.getElementById("statTravelers"),
    monthLabel: document.getElementById("monthLabel"),
    monthPicker: document.getElementById("monthPicker"),
    monthPickerBtn: document.getElementById("monthPickerBtn"),
    monthPickerMenu: document.getElementById("monthPickerMenu"),
    monthPickerYearLabel: document.getElementById("monthPickerYearLabel"),
    monthPickerYearPrev: document.getElementById("monthPickerYearPrev"),
    monthPickerYearNext: document.getElementById("monthPickerYearNext"),
    monthPickerGrid: document.getElementById("monthPickerGrid"),
    calendarGrid: document.getElementById("calendarGrid"),
    legend: document.getElementById("legend"),
    prevMonth: document.getElementById("prevMonth"),
    nextMonth: document.getElementById("nextMonth"),
    todayBtn: document.getElementById("todayBtn"),
    showCancelled: document.getElementById("showCancelled"),
    clearAllBtn: document.getElementById("clearAllBtn"),

    modalBackdrop: document.getElementById("modalBackdrop"),
    modalCloseBtn: document.getElementById("modalCloseBtn"),
    modalTitle: document.getElementById("modalTitle"),
    modalStatusBadge: document.getElementById("modalStatusBadge"),
    tripForm: document.getElementById("tripForm"),
    fieldId: document.getElementById("fieldId"),
    fieldName: document.getElementById("fieldName"),
    fieldOrigin: document.getElementById("fieldOrigin"),
    fieldDestination: document.getElementById("fieldDestination"),
    fieldStart: document.getElementById("fieldStart"),
    fieldEnd: document.getElementById("fieldEnd"),
    fieldStartTime: document.getElementById("fieldStartTime"),
    fieldEndTime: document.getElementById("fieldEndTime"),
    legTimesRow: document.getElementById("legTimesRow"),
    fieldStartArrivalTime: document.getElementById("fieldStartArrivalTime"),
    fieldEndDepartureTime: document.getElementById("fieldEndDepartureTime"),
    fieldAirline: document.getElementById("fieldAirline"),
    fieldPnr: document.getElementById("fieldPnr"),
    fieldPrice: document.getElementById("fieldPrice"),
    fieldBookingSource: document.getElementById("fieldBookingSource"),
    fieldNotes: document.getElementById("fieldNotes"),
    sourceLink: document.getElementById("sourceLink"),
    sourceLinkAnchor: document.getElementById("sourceLinkAnchor"),
    cancelTripBtn: document.getElementById("cancelTripBtn"),
    restoreTripBtn: document.getElementById("restoreTripBtn"),
    legActionsRow: document.getElementById("legActionsRow"),
    toggleOutboundBtn: document.getElementById("toggleOutboundBtn"),
    toggleReturnBtn: document.getElementById("toggleReturnBtn"),
    deleteOutboundLegBtn: document.getElementById("deleteOutboundLegBtn"),
    deleteReturnLegBtn: document.getElementById("deleteReturnLegBtn"),
    deleteTripBtn: document.getElementById("deleteTripBtn"),

    dayModalBackdrop: document.getElementById("dayModalBackdrop"),
    dayModalCloseBtn: document.getElementById("dayModalCloseBtn"),
    dayModalTitle: document.getElementById("dayModalTitle"),
    dayTripList: document.getElementById("dayTripList"),
  };

  const MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
  ];

  function pad(n) { return String(n).padStart(2, "0"); }
  function isoDate(y, m, d) { return `${y}-${pad(m + 1)}-${pad(d)}`; }
  function todayISO() {
    const t = new Date();
    return isoDate(t.getFullYear(), t.getMonth(), t.getDate());
  }
  function startOfMonth(d) { return new Date(d.getFullYear(), d.getMonth(), 1); }

  function seriesIndexForName(name) {
    let hash = 0;
    for (let i = 0; i < name.length; i++) {
      hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
    }
    return (hash % 8) + 1;
  }

  function seriesVar(name) {
    return `var(--series-${seriesIndexForName(name)})`;
  }

  // ---------- Domestic / international classification ----------
  //
  // Best-effort, client-side only: origin/destination are free-text city
  // names (destination may be multiple cities joined with " -> " for
  // multi-city trips). A trip counts as domestic only if every city
  // mentioned is a recognized Indian city; unrecognized cities are treated
  // as international rather than silently mis-filed as domestic.

  const INDIAN_CITIES = new Set([
    "mumbai", "new delhi", "delhi", "bengaluru", "bangalore", "chennai", "kolkata",
    "hyderabad", "pune", "ahmedabad", "kochi", "cochin", "goa", "jaipur", "lucknow",
    "chandigarh", "patna", "guwahati", "ranchi", "thiruvananthapuram", "trivandrum",
    "varanasi", "indore", "bhubaneswar", "port blair", "surat", "nagpur",
    "vijayawada", "visakhapatnam", "madurai", "mangalore", "raipur", "agartala",
    "bagdogra", "srinagar", "jammu", "amritsar", "udaipur", "bhopal", "leh",
  ]);

  function classifyTripType(trip) {
    const cities = [];
    if (trip.origin) cities.push(...trip.origin.split("->"));
    if (trip.destination) cities.push(...trip.destination.split("->"));
    const names = cities.map((c) => c.trim().toLowerCase()).filter(Boolean);
    if (names.length === 0) return "unknown";
    return names.every((c) => INDIAN_CITIES.has(c)) ? "domestic" : "international";
  }

  function matchesTripTypeFilter(trip) {
    if (state.tripTypeFilter === "all") return true;
    return classifyTripType(trip) === state.tripTypeFilter;
  }

  function setTripTypeFilter(filter) {
    state.tripTypeFilter = filter;
    el.directoryTypeFilter.value = filter;
    renderCalendar();
    renderDirectory();
  }

  el.directoryTypeFilter.addEventListener("change", () => setTripTypeFilter(el.directoryTypeFilter.value));

  // ---------- Data loading ----------

  async function loadTrips() {
    const res = await fetch("/api/trips");
    state.trips = await res.json();
    render();
  }

  function render() {
    renderStats();
    renderCalendar();
    renderLegend();
    renderDirectory();
  }

  function renderStats() {
    const active = state.trips.filter((t) => t.status !== "cancelled");
    el.statTotalTrips.textContent = active.length;
    el.statConfirmedTrips.textContent = active.filter((t) => !t.needs_review).length;
    el.statTravelers.textContent = new Set(active.map((t) => t.traveler_name)).size;
  }

  // ---------- Tabs ----------

  const TABS = {
    calendar: {
      view: "calendarView", btn: "tabCalendarBtn",
      title: "Calendar", tagline: "Everyone's flights at a glance.",
    },
    directory: {
      view: "directoryView", btn: "tabDirectoryBtn",
      title: "Traveler Directory", tagline: "Search and manage every trip.",
    },
  };

  function setActiveTab(tab) {
    Object.entries(TABS).forEach(([key, cfg]) => {
      const isActive = key === tab;
      el[cfg.view].hidden = !isActive;
      el[cfg.btn].classList.toggle("active", isActive);
      el[cfg.btn].setAttribute("aria-selected", String(isActive));
    });
    el.viewTitle.textContent = TABS[tab].title;
    el.viewTagline.textContent = TABS[tab].tagline;
  }

  el.tabCalendarBtn.addEventListener("click", () => setActiveTab("calendar"));
  el.tabDirectoryBtn.addEventListener("click", () => setActiveTab("directory"));

  // ---------- Sidebar collapse ----------

  const SIDEBAR_COLLAPSED_KEY = "travelGlance.sidebarCollapsed";

  function setSidebarCollapsed(collapsed) {
    el.sideTabs.classList.toggle("collapsed", collapsed);
    el.sidebarToggleBtn.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? "1" : "0");
  }

  el.sidebarToggleBtn.addEventListener("click", () => {
    setSidebarCollapsed(!el.sideTabs.classList.contains("collapsed"));
  });

  setSidebarCollapsed(localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1");

  // ---------- Theme (light/dark) ----------

  const THEME_KEY = "travelGlance.theme";
  const root = document.documentElement;

  function systemPrefersDark() {
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function applyTheme(theme) {
    root.setAttribute("data-theme", theme);
    localStorage.setItem(THEME_KEY, theme);
    updateThemeIcon(theme === "dark");
  }

  function updateThemeIcon(isDark) {
    el.themeToggleBtn.classList.toggle("is-dark", isDark);
    el.themeToggleBtn.setAttribute("aria-label", isDark ? "Switch to light mode" : "Switch to dark mode");
  }

  const savedTheme = localStorage.getItem(THEME_KEY);
  if (savedTheme === "light" || savedTheme === "dark") {
    root.setAttribute("data-theme", savedTheme);
    updateThemeIcon(savedTheme === "dark");
  } else {
    updateThemeIcon(systemPrefersDark());
  }

  el.themeToggleBtn.addEventListener("click", () => {
    const current = root.getAttribute("data-theme") || (systemPrefersDark() ? "dark" : "light");
    applyTheme(current === "dark" ? "light" : "dark");
  });

  el.logoutBtn?.addEventListener("click", async () => {
    await fetch("/logout", { method: "POST" });
    window.location.href = "/login";
  });

  el.topbarUserTrigger?.addEventListener("click", (e) => {
    e.stopPropagation();
    const open = el.topbarUserMenu.hidden;
    el.topbarUserMenu.hidden = !open;
    el.topbarUserTrigger.setAttribute("aria-expanded", String(open));
  });
  document.addEventListener("click", () => {
    if (el.topbarUserMenu && !el.topbarUserMenu.hidden) {
      el.topbarUserMenu.hidden = true;
      el.topbarUserTrigger.setAttribute("aria-expanded", "false");
    }
  });

  // ---------- Traveler directory ----------

  function populateAirlineOptions() {
    const airlines = [...new Set(state.trips.map((t) => t.airline).filter(Boolean))].sort();
    const current = el.directoryAirlineFilter.value;
    el.directoryAirlineFilter.innerHTML = '<option value="all">All airlines</option>';
    airlines.forEach((a) => {
      const opt = document.createElement("option");
      opt.value = a;
      opt.textContent = a;
      el.directoryAirlineFilter.appendChild(opt);
    });
    el.directoryAirlineFilter.value = airlines.includes(current) ? current : "all";
    state.directoryAirline = el.directoryAirlineFilter.value;
  }

  function populatePlaceOptions() {
    const places = [...new Set(
      state.trips.flatMap((t) => [t.origin, t.destination]).filter(Boolean)
    )].sort();
    const current = el.directoryPlaceFilter.value;
    el.directoryPlaceFilter.innerHTML = '<option value="all">All places</option>';
    places.forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p;
      opt.textContent = p;
      el.directoryPlaceFilter.appendChild(opt);
    });
    el.directoryPlaceFilter.value = places.includes(current) ? current : "all";
    state.directoryPlace = el.directoryPlaceFilter.value;
  }

  function populateBookingSourceOptions() {
    const sources = [...new Set(state.trips.map((t) => t.booking_source).filter(Boolean))].sort();
    const current = el.directoryBookingSourceFilter.value;
    el.directoryBookingSourceFilter.innerHTML = '<option value="all">All booking apps</option>';
    sources.forEach((s) => {
      const opt = document.createElement("option");
      opt.value = s;
      opt.textContent = s;
      el.directoryBookingSourceFilter.appendChild(opt);
    });
    el.directoryBookingSourceFilter.value = sources.includes(current) ? current : "all";
    state.directoryBookingSource = el.directoryBookingSourceFilter.value;
  }

  function matchesDirectoryQuery(trip, query) {
    if (!query) return true;
    const haystack = [
      trip.traveler_name, trip.airline, trip.pnr, trip.origin, trip.destination, trip.booking_source,
    ].filter(Boolean).join(" ").toLowerCase();
    return haystack.includes(query);
  }

  function matchesDirectoryFilters(trip) {
    if (state.directoryAirline !== "all" && trip.airline !== state.directoryAirline) return false;
    if (state.directoryPlace !== "all" && trip.origin !== state.directoryPlace && trip.destination !== state.directoryPlace) return false;
    if (state.directoryBookingSource !== "all" && trip.booking_source !== state.directoryBookingSource) return false;
    if (state.directoryDateFrom && (!trip.start_date || trip.start_date < state.directoryDateFrom)) return false;
    if (state.directoryDateTo && (!trip.start_date || trip.start_date > state.directoryDateTo)) return false;
    return true;
  }

  function renderDirectory() {
    populateAirlineOptions();
    populatePlaceOptions();
    populateBookingSourceOptions();
    const query = state.directoryQuery.trim().toLowerCase();
    const matches = state.trips.filter(
      (t) => matchesDirectoryQuery(t, query) && matchesTripTypeFilter(t) && matchesDirectoryFilters(t)
    );

    const isFiltered = Boolean(query) || state.tripTypeFilter !== "all"
      || state.directoryAirline !== "all" || state.directoryPlace !== "all"
      || state.directoryBookingSource !== "all"
      || state.directoryDateFrom || state.directoryDateTo;
    el.directoryCount.textContent = isFiltered
      ? `${matches.length} of ${state.trips.length} trip(s)`
      : `${state.trips.length} trip(s)`;

    el.directoryTableBody.innerHTML = "";
    el.directoryEmpty.hidden = matches.length > 0;

    matches
      .slice()
      .sort((a, b) => (a.start_date || "").localeCompare(b.start_date || ""))
      .forEach((trip) => {
        const tr = document.createElement("tr");
        if (trip.status === "cancelled") tr.classList.add("cancelled");
        tr.addEventListener("click", () => openTripModal(trip));

        const nameCell = document.createElement("td");
        nameCell.className = "name-cell";
        const dot = document.createElement("span");
        dot.className = "dot";
        dot.style.background = seriesVar(trip.traveler_name);
        nameCell.appendChild(dot);
        nameCell.appendChild(document.createTextNode(trip.traveler_name));
        tr.appendChild(nameCell);

        const route = [trip.origin, trip.destination].filter(Boolean).join(" -> ") || "—";
        tr.appendChild(textCell(route));

        tr.appendChild(textCell(trip.start_date ? formatDateTimeCell(trip.start_date, trip.start_time, trip.start_arrival_time) : "—"));
        tr.appendChild(textCell(trip.end_date ? formatDateTimeCell(trip.end_date, trip.end_departure_time, trip.end_time) : "—"));
        tr.appendChild(textCell(trip.airline || "—", true));
        tr.appendChild(textCell(trip.pnr || "—", true));
        tr.appendChild(textCell(trip.price || "—", true));

        const statusCell = document.createElement("td");
        const oneLegCancelled = trip.start_date !== trip.end_date
          && (trip.outbound_status === "cancelled") !== (trip.return_status === "cancelled");
        const pill = document.createElement("span");
        let statusText = "Confirmed";
        let statusClass = "confirmed";
        if (trip.status === "cancelled") {
          statusText = "Cancelled";
          statusClass = "cancelled";
        } else if (oneLegCancelled) {
          statusText = trip.outbound_status === "cancelled" ? "Outbound cancelled" : "Return cancelled";
          statusClass = "partial";
        } else if (trip.needs_review) {
          statusText = "Needs review";
          statusClass = "review";
        }
        pill.className = `status-pill ${statusClass}`;
        pill.textContent = statusText;
        statusCell.appendChild(pill);
        tr.appendChild(statusCell);

        el.directoryTableBody.appendChild(tr);
      });
  }

  function textCell(text, muted) {
    const td = document.createElement("td");
    if (muted) td.classList.add("muted");
    td.textContent = text;
    return td;
  }

  function formatDateTimeCell(iso, primaryTime, secondaryTime) {
    const label = formatShortDate(iso);
    if (primaryTime && secondaryTime) return `${label}, ${primaryTime} → ${secondaryTime}`;
    const time = primaryTime || secondaryTime;
    return time ? `${label}, ${time}` : label;
  }

  el.travelerSearch.addEventListener("input", () => {
    state.directoryQuery = el.travelerSearch.value;
    renderDirectory();
  });

  el.directoryAirlineFilter.addEventListener("change", () => {
    state.directoryAirline = el.directoryAirlineFilter.value;
    renderDirectory();
  });
  el.directoryPlaceFilter.addEventListener("change", () => {
    state.directoryPlace = el.directoryPlaceFilter.value;
    renderDirectory();
  });
  el.directoryBookingSourceFilter.addEventListener("change", () => {
    state.directoryBookingSource = el.directoryBookingSourceFilter.value;
    renderDirectory();
  });
  // ---------- Date filter dropdown (All dates / This month / Today / Last 7 / Last 30 / Custom) ----------

  const DATE_PRESET_LABELS = {
    all: "All dates", today: "Today", last7: "Last 7 days", last30: "Last 30 days",
  };

  (function initThisMonthLabel() {
    const now = new Date();
    el.dateFilterThisMonth.textContent = `${MONTH_NAMES[now.getMonth()]} ${now.getFullYear()}`;
  })();

  function presetRange(preset) {
    const t = new Date();
    const today = todayISO();
    if (preset === "today") return { from: today, to: today };
    if (preset === "last7") {
      const from = new Date(t.getFullYear(), t.getMonth(), t.getDate() - 6);
      return { from: isoDate(from.getFullYear(), from.getMonth(), from.getDate()), to: today };
    }
    if (preset === "last30") {
      const from = new Date(t.getFullYear(), t.getMonth(), t.getDate() - 29);
      return { from: isoDate(from.getFullYear(), from.getMonth(), from.getDate()), to: today };
    }
    if (preset === "thisMonth") {
      const last = new Date(t.getFullYear(), t.getMonth() + 1, 0);
      return {
        from: isoDate(t.getFullYear(), t.getMonth(), 1),
        to: isoDate(last.getFullYear(), last.getMonth(), last.getDate()),
      };
    }
    return { from: "", to: "" }; // "all"
  }

  function openDateMenu() {
    el.dateFilterMenu.hidden = false;
    el.dateFilterBtn.setAttribute("aria-expanded", "true");
  }
  function closeDateMenu() {
    el.dateFilterMenu.hidden = true;
    el.dateFilterBtn.setAttribute("aria-expanded", "false");
  }

  el.dateFilterBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    el.dateFilterMenu.hidden ? openDateMenu() : closeDateMenu();
  });
  document.addEventListener("click", (e) => {
    if (!el.dateFilterDropdown.contains(e.target)) closeDateMenu();
  });

  el.dateFilterMenu.querySelectorAll(".date-filter-option").forEach((btn) => {
    btn.addEventListener("click", () => {
      const preset = btn.dataset.preset;
      el.dateFilterMenu.querySelectorAll(".date-filter-option").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");

      if (preset === "custom") {
        el.dateFilterCustom.hidden = false;
        el.dateFilterLabel.textContent = "Custom range";
        return; // keep menu open so the user can pick dates
      }

      el.dateFilterCustom.hidden = true;
      const { from, to } = presetRange(preset);
      state.directoryDateFrom = from;
      state.directoryDateTo = to;
      el.directoryDateFrom.value = from;
      el.directoryDateTo.value = to;
      el.dateFilterLabel.textContent = preset === "thisMonth" ? el.dateFilterThisMonth.textContent : DATE_PRESET_LABELS[preset];
      renderDirectory();
      closeDateMenu();
    });
  });

  function updateCustomRangeLabel() {
    if (state.directoryDateFrom && state.directoryDateTo) {
      el.dateFilterLabel.textContent = `${formatShortDate(state.directoryDateFrom)} – ${formatShortDate(state.directoryDateTo)}`;
    }
  }

  el.directoryDateFrom.addEventListener("change", () => {
    state.directoryDateFrom = el.directoryDateFrom.value;
    updateCustomRangeLabel();
    renderDirectory();
  });
  el.directoryDateTo.addEventListener("change", () => {
    state.directoryDateTo = el.directoryDateTo.value;
    updateCustomRangeLabel();
    renderDirectory();
  });

  function resetDateFilter() {
    state.directoryDateFrom = "";
    state.directoryDateTo = "";
    el.directoryDateFrom.value = "";
    el.directoryDateTo.value = "";
    el.dateFilterCustom.hidden = true;
    el.dateFilterLabel.textContent = "All dates";
    el.dateFilterMenu.querySelectorAll(".date-filter-option").forEach((b) => b.classList.toggle("active", b.dataset.preset === "all"));
  }

  el.directoryClearFiltersBtn.addEventListener("click", () => {
    state.directoryQuery = "";
    state.directoryAirline = "all";
    state.directoryPlace = "all";
    state.directoryBookingSource = "all";
    el.travelerSearch.value = "";
    resetDateFilter();
    setTripTypeFilter("all");
    renderDirectory();
  });

  // ---------- Needs review panel ----------

  // ---------- Calendar rendering ----------

  function renderCalendar() {
    const year = state.viewDate.getFullYear();
    const month = state.viewDate.getMonth();
    el.monthLabel.textContent = `${MONTH_NAMES[month]} ${year}`;

    const firstOfMonth = new Date(year, month, 1);
    const startWeekday = firstOfMonth.getDay(); // 0 = Sunday
    const gridStart = new Date(year, month, 1 - startWeekday);

    const today = todayISO();
    const visibleTrips = state.trips.filter(
      (t) => (state.showCancelled || t.status !== "cancelled") && matchesTripTypeFilter(t)
    );

    el.calendarGrid.innerHTML = "";
    for (let i = 0; i < 42; i++) {
      const cellDate = new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate() + i);
      const cellISO = isoDate(cellDate.getFullYear(), cellDate.getMonth(), cellDate.getDate());
      const cell = document.createElement("div");
      cell.className = "day-cell";
      if (cellDate.getMonth() !== month) cell.classList.add("outside");
      if (cellISO === today) cell.classList.add("today");

      const num = document.createElement("div");
      num.className = "day-num";
      num.textContent = cellDate.getDate();
      cell.appendChild(num);

      const dayTrips = visibleTrips.filter(
        (t) => t.start_date && t.end_date && t.start_date <= cellISO && cellISO <= t.end_date
      );

      const maxShown = 3;
      dayTrips.slice(0, maxShown).forEach((t) => cell.appendChild(buildChip(t, cellISO)));
      if (dayTrips.length > maxShown) {
        const more = document.createElement("button");
        more.className = "more-link";
        more.type = "button";
        more.textContent = `+${dayTrips.length - maxShown} more`;
        more.addEventListener("click", () => openDayModal(cellISO, dayTrips));
        cell.appendChild(more);
      }

      el.calendarGrid.appendChild(cell);
    }
  }

  function formatShortDate(iso) {
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(y, m - 1, d).toLocaleDateString(undefined, { day: "numeric", month: "short" });
  }

  function tripTooltip(trip) {
    const parts = [trip.traveler_name];
    const route = [trip.origin, trip.destination].filter(Boolean).join(" -> ");
    if (route) parts.push(route);
    if (trip.start_date) {
      const dep = trip.start_time ? `${trip.start_time}, ${formatShortDate(trip.start_date)}` : formatShortDate(trip.start_date);
      parts.push(trip.start_arrival_time ? `Departs ${dep} (arrives ${trip.start_arrival_time})` : `Departs ${dep}`);
    }
    if (trip.end_date) {
      const arr = trip.end_time ? `${trip.end_time}, ${formatShortDate(trip.end_date)}` : formatShortDate(trip.end_date);
      parts.push(trip.end_departure_time ? `Returns ${arr} (departs ${trip.end_departure_time})` : `Returns ${arr}`);
    }
    if (trip.price) parts.push(trip.price);
    return parts.join(" · ");
  }

  function legStatusForDate(trip, cellISO) {
    if (trip.start_date !== trip.end_date) {
      if (cellISO === trip.start_date) return trip.outbound_status;
      if (cellISO === trip.end_date) return trip.return_status;
    }
    return trip.status;
  }

  function buildChip(trip, cellISO) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "trip-chip";
    chip.style.setProperty("--chip-color", seriesVar(trip.traveler_name));
    if (legStatusForDate(trip, cellISO) === "cancelled") chip.classList.add("cancelled");
    if (trip.needs_review) chip.classList.add("needs-review");
    chip.title = tripTooltip(trip);

    const dot = document.createElement("span");
    dot.className = "dot";
    dot.style.background = seriesVar(trip.traveler_name);
    chip.appendChild(dot);

    const label = document.createElement("span");
    const place = trip.destination || trip.origin || "";
    label.textContent = place ? `${trip.traveler_name} · ${place}` : trip.traveler_name;
    chip.appendChild(label);

    chip.addEventListener("click", () => openTripModal(trip));
    return chip;
  }

  function renderLegend() {
    const names = [...new Set(state.trips.map((t) => t.traveler_name))].sort();
    el.legend.innerHTML = "";
    names.forEach((name) => {
      const item = document.createElement("div");
      item.className = "legend-item";
      const dot = document.createElement("span");
      dot.className = "dot";
      dot.style.background = seriesVar(name);
      item.appendChild(dot);
      item.appendChild(document.createTextNode(name));
      el.legend.appendChild(item);
    });
  }

  // ---------- Day modal (overflow list) ----------

  function openDayModal(iso, trips) {
    el.dayModalTitle.textContent = formatLongDate(iso);
    el.dayTripList.innerHTML = "";
    trips.forEach((t) => {
      const li = document.createElement("li");
      li.appendChild(buildChip(t, iso));
      el.dayTripList.appendChild(li);
    });
    el.dayModalBackdrop.hidden = false;
  }

  function formatLongDate(iso) {
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(y, m - 1, d).toLocaleDateString(undefined, {
      weekday: "long", year: "numeric", month: "long", day: "numeric",
    });
  }

  el.dayModalCloseBtn.addEventListener("click", () => { el.dayModalBackdrop.hidden = true; });
  el.dayModalBackdrop.addEventListener("click", (e) => {
    if (e.target === el.dayModalBackdrop) el.dayModalBackdrop.hidden = true;
  });

  // ---------- Trip modal (view / edit / cancel / delete) ----------

  let currentTripId = null;

  function openTripModal(trip) {
    currentTripId = trip.id;
    el.modalTitle.textContent = trip.traveler_name;
    el.modalStatusBadge.textContent = trip.status === "cancelled"
      ? "Cancelled"
      : (trip.needs_review ? "Needs review" : "Confirmed");
    el.modalStatusBadge.className = "badge " + (
      trip.status === "cancelled" ? "cancelled" : (trip.needs_review ? "review" : "confirmed")
    );

    el.fieldId.value = trip.id;
    el.fieldName.value = trip.traveler_name || "";
    el.fieldOrigin.value = trip.origin || "";
    el.fieldDestination.value = trip.destination || "";
    el.fieldStart.value = trip.start_date || "";
    el.fieldEnd.value = trip.end_date || "";
    el.fieldStartTime.value = trip.start_time || "";
    el.fieldEndTime.value = trip.end_time || "";
    el.fieldStartArrivalTime.value = trip.start_arrival_time || "";
    el.fieldEndDepartureTime.value = trip.end_departure_time || "";
    // Outbound-arrival / return-departure only make sense when there's an outbound
    // leg distinct from a return leg - i.e. the trip spans more than one day. A
    // single-day, one-way flight has nothing extra to show here.
    el.legTimesRow.hidden = !trip.start_date || !trip.end_date || trip.start_date === trip.end_date;
    el.fieldAirline.value = trip.airline || "";
    el.fieldPnr.value = trip.pnr || "";
    el.fieldPrice.value = trip.price || "";
    el.fieldBookingSource.value = trip.booking_source || "";
    el.fieldNotes.value = trip.notes || "";

    if (trip.drive_view_link) {
      el.sourceLink.hidden = false;
      el.sourceLinkAnchor.href = trip.drive_view_link;
    } else {
      el.sourceLink.hidden = true;
    }

    if (trip.status === "cancelled") {
      el.cancelTripBtn.hidden = true;
      el.restoreTripBtn.hidden = false;
    } else {
      el.cancelTripBtn.hidden = false;
      el.restoreTripBtn.hidden = true;
    }

    const isRoundTrip = Boolean(trip.start_date && trip.end_date && trip.start_date !== trip.end_date);
    el.legActionsRow.hidden = !isRoundTrip;
    if (isRoundTrip) {
      updateLegButton(el.toggleOutboundBtn, trip.outbound_status === "cancelled", "outbound");
      updateLegButton(el.toggleReturnBtn, trip.return_status === "cancelled", "return");
    }

    el.modalBackdrop.hidden = false;
  }

  function updateLegButton(btn, isCancelled, legLabel) {
    btn.textContent = isCancelled ? `Restore ${legLabel}` : `Cancel ${legLabel}`;
    btn.classList.toggle("is-cancelled", isCancelled);
  }

  function closeTripModal() {
    el.modalBackdrop.hidden = true;
    currentTripId = null;
  }

  el.modalCloseBtn.addEventListener("click", closeTripModal);
  el.modalBackdrop.addEventListener("click", (e) => {
    if (e.target === el.modalBackdrop) closeTripModal();
  });

  el.tripForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!currentTripId) return;

    if (el.fieldEnd.value < el.fieldStart.value) {
      alert("Return/end date can't be before the departure date.");
      return;
    }

    const payload = {
      traveler_name: el.fieldName.value.trim(),
      origin: el.fieldOrigin.value.trim(),
      destination: el.fieldDestination.value.trim(),
      start_date: el.fieldStart.value,
      end_date: el.fieldEnd.value,
      start_time: el.fieldStartTime.value,
      end_time: el.fieldEndTime.value,
      start_arrival_time: el.fieldStartArrivalTime.value,
      end_departure_time: el.fieldEndDepartureTime.value,
      airline: el.fieldAirline.value.trim(),
      pnr: el.fieldPnr.value.trim(),
      price: el.fieldPrice.value.trim(),
      booking_source: el.fieldBookingSource.value.trim(),
      notes: el.fieldNotes.value.trim(),
    };

    await fetch(`/api/trips/${currentTripId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    closeTripModal();
    await loadTrips();
  });

  el.cancelTripBtn.addEventListener("click", async () => {
    if (!currentTripId) return;
    if (!confirm("Mark this trip as cancelled? It will stay on the calendar, greyed out.")) return;
    await fetch(`/api/trips/${currentTripId}/status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "cancelled" }),
    });
    closeTripModal();
    await loadTrips();
  });

  el.restoreTripBtn.addEventListener("click", async () => {
    if (!currentTripId) return;
    await fetch(`/api/trips/${currentTripId}/status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "confirmed" }),
    });
    closeTripModal();
    await loadTrips();
  });

  async function toggleLeg(leg, currentlyCancelled) {
    if (!currentTripId) return;
    await fetch(`/api/trips/${currentTripId}/status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: currentlyCancelled ? "confirmed" : "cancelled", leg }),
    });
    closeTripModal();
    await loadTrips();
  }

  el.toggleOutboundBtn.addEventListener("click", () => {
    toggleLeg("outbound", el.toggleOutboundBtn.classList.contains("is-cancelled"));
  });
  el.toggleReturnBtn.addEventListener("click", () => {
    toggleLeg("return", el.toggleReturnBtn.classList.contains("is-cancelled"));
  });

  async function deleteLeg(leg, otherLegLabel) {
    if (!currentTripId) return;
    if (!confirm(`Permanently delete the ${leg} leg? This trip will become a one-way trip for the ${otherLegLabel} leg only - this can't be undone.`)) return;
    await fetch(`/api/trips/${currentTripId}/delete-leg`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ leg }),
    });
    closeTripModal();
    await loadTrips();
  }

  el.deleteOutboundLegBtn.addEventListener("click", () => deleteLeg("outbound", "return"));
  el.deleteReturnLegBtn.addEventListener("click", () => deleteLeg("return", "outbound"));

  el.deleteTripBtn.addEventListener("click", async () => {
    if (!currentTripId) return;
    if (!confirm("Permanently delete this trip and its uploaded file? This can't be undone.")) return;
    await fetch(`/api/trips/${currentTripId}`, { method: "DELETE" });
    closeTripModal();
    await loadTrips();
  });

  // ---------- Calendar nav ----------

  el.prevMonth.addEventListener("click", () => {
    state.viewDate = new Date(state.viewDate.getFullYear(), state.viewDate.getMonth() - 1, 1);
    renderCalendar();
  });
  el.nextMonth.addEventListener("click", () => {
    state.viewDate = new Date(state.viewDate.getFullYear(), state.viewDate.getMonth() + 1, 1);
    renderCalendar();
  });
  el.todayBtn.addEventListener("click", () => {
    state.viewDate = startOfMonth(new Date());
    renderCalendar();
  });

  // ---------- Month picker dropdown ----------

  const MONTH_ABBR = MONTH_NAMES.map((m) => m.slice(0, 3));
  let pickerYear = state.viewDate.getFullYear();

  function renderMonthPickerGrid() {
    el.monthPickerYearLabel.textContent = pickerYear;
    el.monthPickerGrid.innerHTML = "";
    MONTH_ABBR.forEach((abbr, idx) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = abbr;
      if (pickerYear === state.viewDate.getFullYear() && idx === state.viewDate.getMonth()) {
        btn.classList.add("active");
      }
      btn.addEventListener("click", () => {
        state.viewDate = new Date(pickerYear, idx, 1);
        renderCalendar();
        closeMonthPicker();
      });
      el.monthPickerGrid.appendChild(btn);
    });
  }

  function openMonthPicker() {
    pickerYear = state.viewDate.getFullYear();
    renderMonthPickerGrid();
    el.monthPickerMenu.hidden = false;
    el.monthPickerBtn.setAttribute("aria-expanded", "true");
  }
  function closeMonthPicker() {
    el.monthPickerMenu.hidden = true;
    el.monthPickerBtn.setAttribute("aria-expanded", "false");
  }

  el.monthPickerBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    el.monthPickerMenu.hidden ? openMonthPicker() : closeMonthPicker();
  });
  document.addEventListener("click", (e) => {
    if (!el.monthPicker.contains(e.target)) closeMonthPicker();
  });
  el.monthPickerYearPrev.addEventListener("click", () => {
    pickerYear -= 1;
    renderMonthPickerGrid();
  });
  el.monthPickerYearNext.addEventListener("click", () => {
    pickerYear += 1;
    renderMonthPickerGrid();
  });

  el.showCancelled.addEventListener("change", () => {
    state.showCancelled = el.showCancelled.checked;
    renderCalendar();
  });

  el.clearAllBtn.addEventListener("click", async () => {
    const count = state.trips.length;
    if (count === 0) {
      alert("There's nothing to clear — the calendar is already empty.");
      return;
    }
    const confirmed = confirm(
      `Delete all ${count} trip(s)? This permanently removes every uploaded itinerary ` +
      `and its PDF file for every traveler on this calendar. This can't be undone.`
    );
    if (!confirmed) return;

    await fetch("/api/trips", { method: "DELETE" });
    el.uploadStatus.hidden = false;
    el.uploadStatus.classList.remove("error");
    el.uploadStatus.textContent = `Cleared ${count} trip(s).`;
    await loadTrips();
  });

  // ---------- Upload result reporting (shared with Drive-attach) ----------

  function reportUploadResult(data) {
    // A clean add needs no banner - the calendar/stat cards already show it.
    // Only surface something worth acting on: trips needing review, or errors.
    const parts = [];
    const reviewCount = (data.created || []).filter((t) => t.needs_review).length;
    if (reviewCount) {
      parts.push(`${reviewCount} trip(s) need review.`);
    }
    el.uploadStatus.classList.remove("error");
    if (data.errors && data.errors.length) {
      const detail = data.errors.map((e) => `${e.filename}: ${e.error}`).join(" | ");
      parts.push(`${data.errors.length} file(s) failed — ${detail}`);
      el.uploadStatus.classList.add("error");
    }
    if (!parts.length) {
      el.uploadStatus.hidden = true;
      return;
    }
    el.uploadStatus.hidden = false;
    el.uploadStatus.textContent = parts.join(" ");
  }

  // ---------- Attach from Google Drive ----------
  //
  // Pick PDFs or a folder of tickets in Drive. Each PDF is copied into
  // uploads/ and parsed the same way as Attach from device. The original
  // Drive files are never deleted.

  const googleConfig = {
    clientId: document.body.dataset.googleClientId || "",
    apiKey: document.body.dataset.googleApiKey || "",
    appId: document.body.dataset.googleAppId || "",
    userEmail: (document.body.dataset.userEmail || "").trim(),
    allowedDomains: (document.body.dataset.allowedDomains || "")
      .split(",")
      .map((d) => d.trim().toLowerCase())
      .filter(Boolean),
  };

  let pickerTokenClient = null;
  let pickerAccessToken = null;
  let gapiReady = false;
  let gisReady = false;

  function maybeEnableDriveButton() {
    if (gapiReady && gisReady && googleConfig.clientId) {
      el.driveAttachBtn.hidden = false;
    }
  }

  // Attach-from-device doesn't touch Google client-side at all (see below),
  // so it's available immediately - no waiting on GIS/gapi to load.
  if (el.deviceAttachBtn) el.deviceAttachBtn.hidden = false;

  window.__gapiLoaded = function () {
    if (!googleConfig.clientId) return;
    gapi.load("client:picker", () => { gapiReady = true; maybeEnableDriveButton(); });
  };

  window.__gisLoaded = function () {
    if (!googleConfig.clientId) return;
    pickerTokenClient = google.accounts.oauth2.initTokenClient({
      client_id: googleConfig.clientId,
      scope: "https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/userinfo.email",
      hint: googleConfig.userEmail || undefined,
      callback: "", // set per-request below
    });
    gisReady = true;
    maybeEnableDriveButton();
  };

  if (el.driveAttachBtn) {
    el.driveAttachBtn.addEventListener("click", () => {
      pickerTokenClient.callback = async (response) => {
        if (response.error) {
          el.uploadStatus.hidden = false;
          el.uploadStatus.classList.add("error");
          el.uploadStatus.textContent = "Google sign-in failed: " + response.error;
          return;
        }
        pickerAccessToken = response.access_token;
        const driveAccountError = await checkDriveAccount(pickerAccessToken);
        if (driveAccountError) {
          el.uploadStatus.hidden = false;
          el.uploadStatus.classList.add("error");
          el.uploadStatus.textContent = driveAccountError;
          return;
        }
        openDrivePicker();
      };
      // See the device-attach handler below for why this is always "consent"
      // rather than conditionally silent - a silent (prompt:"") refresh hangs
      // indefinitely with no popup and no error when third-party cookies to
      // accounts.google.com are blocked.
      pickerTokenClient.requestAccessToken({
        prompt: "consent",
        hint: googleConfig.userEmail || undefined,
      });
    });
  }

  async function checkDriveAccount(accessToken) {
    const signedIn = googleConfig.userEmail.toLowerCase();
    try {
      const res = await fetch("https://www.googleapis.com/oauth2/v3/userinfo", {
        headers: { Authorization: "Bearer " + accessToken },
      });
      if (!res.ok) return "";
      const info = await res.json();
      const email = (info.email || "").trim().toLowerCase();
      if (!email) {
        return "Couldn't confirm which Google account is attaching from Drive. Try again.";
      }
      if (signedIn && email !== signedIn) {
        return (
          "Attach from Drive with the same Netcore or Unbxd account you used to sign in (" +
          googleConfig.userEmail +
          "), not a personal Gmail."
        );
      }
      const domain = email.split("@").pop();
      if (googleConfig.allowedDomains.length && !googleConfig.allowedDomains.includes(domain)) {
        return "Only Netcore and Unbxd Google accounts can attach from Drive.";
      }
    } catch (_) {
      // Backend still enforces this if userinfo is blocked in the browser.
    }
    return "";
  }

  function openDrivePicker() {
    const filesView = new google.picker.DocsView()
      .setIncludeFolders(true)
      .setSelectFolderEnabled(true)
      .setMimeTypes("application/pdf,application/vnd.google-apps.folder");

    const folderView = new google.picker.DocsView(google.picker.ViewId.FOLDERS)
      .setSelectFolderEnabled(true)
      .setIncludeFolders(true);

    const picker = new google.picker.PickerBuilder()
      .enableFeature(google.picker.Feature.MULTISELECT_ENABLED)
      .enableFeature(google.picker.Feature.SUPPORT_DRIVES)
      .setDeveloperKey(googleConfig.apiKey)
      .setAppId(googleConfig.appId)
      .setOAuthToken(pickerAccessToken)
      .addView(filesView)
      .addView(folderView)
      .setCallback(onPickerResult)
      .build();
    picker.setVisible(true);
  }

  function onPickerResult(data) {
    if (data.action !== google.picker.Action.PICKED) return;
    const docs = data[google.picker.Response.DOCUMENTS] || [];
    const fileIds = docs.map((d) => d[google.picker.Document.ID]);
    const folderCount = docs.filter((d) => {
      const mime = d[google.picker.Document.MIME_TYPE] || d.mimeType || "";
      return mime === "application/vnd.google-apps.folder";
    }).length;
    attachFromDrive(fileIds, folderCount);
  }

  async function attachFromDrive(fileIds, folderCount) {
    el.uploadStatus.hidden = false;
    el.uploadStatus.classList.remove("error");
    el.uploadStatus.textContent = folderCount
      ? `Reading ticket folder(s) from Google Drive...`
      : `Reading ${fileIds.length} file(s) from Google Drive...`;

    try {
      const res = await fetch("/api/attach-from-drive", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ access_token: pickerAccessToken, file_ids: fileIds }),
      });
      const data = await res.json();
      if (!res.ok) {
        el.uploadStatus.classList.add("error");
        el.uploadStatus.textContent = data.error || "Attach from Drive failed.";
        return;
      }
      reportUploadResult(data);
      await loadTrips();
    } catch (err) {
      el.uploadStatus.classList.add("error");
      el.uploadStatus.textContent = "Attach from Drive failed: " + err.message;
    }
  }

  // ---------- Attach from device ----------
  //
  // Pick PDFs from this computer. Same parse + local store as Drive attach.

  if (el.deviceAttachBtn) {
    el.deviceAttachBtn.addEventListener("click", () => {
      el.deviceFileInput.click();
    });
  }

  el.deviceFileInput.addEventListener("change", () => {
    const files = Array.from(el.deviceFileInput.files || []);
    el.deviceFileInput.value = ""; // allow re-picking the same file later
    if (!files.length) return;
    uploadFilesFromDevice(files);
  });

  async function uploadFilesFromDevice(files) {
    el.uploadStatus.hidden = false;
    el.uploadStatus.classList.remove("error");
    el.uploadStatus.textContent = `Uploading ${files.length} file(s)...`;

    const formData = new FormData();
    files.forEach((file) => formData.append("files", file, file.name));

    try {
      const res = await fetch("/api/upload", { method: "POST", body: formData });
      const data = await res.json();
      reportUploadResult(data);
      await loadTrips();
    } catch (err) {
      el.uploadStatus.hidden = false;
      el.uploadStatus.classList.add("error");
      el.uploadStatus.textContent = "Attach from device failed: " + err.message;
    }
  }

  loadTrips();
})();
