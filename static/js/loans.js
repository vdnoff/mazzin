/* Loan Options funnel (/loans). One IIFE, no framework, no build step.
 *
 * Not the swipe engine: this page does not load engine.js and has no funnel
 * config. It asks six closed questions, posts the answers once, and shows
 * labelled advertisements. It holds no name, contact detail or free text, and
 * a network call that fails is never shown and never blocks a tap.
 */
(function () {
  "use strict";

  // The related-search rows on the last view, in display order. PRE-FEED:
  // while `url` is "" a row is drawn as a disabled non-link and the page says
  // offers are not available yet. Phase 2 fills the urls in.
  var OFFERS = [
    { id: "personal-loans-online", label: "Personal Loans Online", url: "" },
    { id: "small-personal-loans", label: "Small Personal Loans", url: "" },
    { id: "personal-loans-near-me", label: "Personal Loans Near Me", url: "" },
    { id: "compare-personal-loan-rates", label: "Compare Personal Loan Rates", url: "" },
    { id: "loans-for-fair-credit", label: "Loans for Fair Credit", url: "" },
    { id: "1-year-personal-loan", label: "1 Year Personal Loan", url: "" }
  ];

  var STATES = [
    ["AL", "Alabama"], ["AK", "Alaska"], ["AZ", "Arizona"], ["AR", "Arkansas"],
    ["CA", "California"], ["CO", "Colorado"], ["CT", "Connecticut"],
    ["DE", "Delaware"], ["DC", "District of Columbia"], ["FL", "Florida"],
    ["GA", "Georgia"], ["HI", "Hawaii"], ["ID", "Idaho"], ["IL", "Illinois"],
    ["IN", "Indiana"], ["IA", "Iowa"], ["KS", "Kansas"], ["KY", "Kentucky"],
    ["LA", "Louisiana"], ["ME", "Maine"], ["MD", "Maryland"],
    ["MA", "Massachusetts"], ["MI", "Michigan"], ["MN", "Minnesota"],
    ["MS", "Mississippi"], ["MO", "Missouri"], ["MT", "Montana"],
    ["NE", "Nebraska"], ["NV", "Nevada"], ["NH", "New Hampshire"],
    ["NJ", "New Jersey"], ["NM", "New Mexico"], ["NY", "New York"],
    ["NC", "North Carolina"], ["ND", "North Dakota"], ["OH", "Ohio"],
    ["OK", "Oklahoma"], ["OR", "Oregon"], ["PA", "Pennsylvania"],
    ["RI", "Rhode Island"], ["SC", "South Carolina"], ["SD", "South Dakota"],
    ["TN", "Tennessee"], ["TX", "Texas"], ["UT", "Utah"], ["VT", "Vermont"],
    ["VA", "Virginia"], ["WA", "Washington"], ["WV", "West Virginia"],
    ["WI", "Wisconsin"], ["WY", "Wyoming"]
  ];

  var LABELS = {
    purpose: {
      emergency: "Emergency expense", debt: "Pay off debt", car: "Car repair",
      home: "Home improvement", medical: "Medical bill", other: "Something else"
    },
    employment: {
      employed: "Employed", self: "Self-employed", benefits: "Benefits",
      retired: "Retired"
    },
    credit: {
      excellent: "Excellent credit", good: "Good credit", fair: "Fair credit",
      building: "Building credit"
    }
  };
  var INCOMES = ["lt1000", "1000_2000", "2000_3000", "3000_4500", "gt4500"];

  // The flow is a straight line, and the history stack is always a prefix of
  // it: forward is a pushState, back is the browser's own back.
  var VIEWS = ["landing", "purpose", "income", "credit", "options", "offers"];
  var STEP_OF = { purpose: 1, income: 2, credit: 3 };
  var ATTRIBUTION = ["subid", "utm_source", "utm_campaign", "utm_content", "utm_term"];
  var STORE_KEY = "mazzin_loans";
  var AMOUNT_MIN = 100, AMOUNT_MAX = 5000, AMOUNT_STEP = 100, AMOUNT_DEFAULT = 500;

  function $(id) { return document.getElementById(id); }

  // --- state ---------------------------------------------------------------

  function uuid() {
    if (window.crypto && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }
    var b = new Uint8Array(16);
    if (window.crypto && crypto.getRandomValues) {
      crypto.getRandomValues(b);
    } else {
      for (var i = 0; i < 16; i++) b[i] = Math.floor(Math.random() * 256);
    }
    b[6] = (b[6] & 0x0f) | 0x40;
    b[8] = (b[8] & 0x3f) | 0x80;
    var h = [];
    for (var j = 0; j < 16; j++) h.push((b[j] + 256).toString(16).slice(1));
    return h.slice(0, 4).join("") + "-" + h.slice(4, 6).join("") + "-" +
      h.slice(6, 8).join("") + "-" + h.slice(8, 10).join("") + "-" +
      h.slice(10).join("");
  }

  function load() {
    try {
      var saved = JSON.parse(sessionStorage.getItem(STORE_KEY) || "null");
      if (saved && typeof saved === "object" && typeof saved.sid === "string") {
        saved.answers = saved.answers || {};
        saved.sent = saved.sent || {};
        saved.attr = saved.attr || {};
        return saved;
      }
    } catch (e) { /* private mode, or junk: start clean */ }
    return { sid: uuid(), answers: {}, sent: {}, attr: {}, view: "landing" };
  }

  function save() {
    try { sessionStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch (e) {}
  }

  function validAmount(n) {
    return typeof n === "number" && n >= AMOUNT_MIN && n <= AMOUNT_MAX &&
      n % AMOUNT_STEP === 0;
  }

  function stateName(code) {
    for (var i = 0; i < STATES.length; i++) {
      if (STATES[i][0] === code) return STATES[i][1];
    }
    return "";
  }

  var state = load();
  var a = state.answers;
  if (!validAmount(a.amount)) a.amount = AMOUNT_DEFAULT;
  if (!LABELS.purpose[a.purpose]) delete a.purpose;
  if (!LABELS.employment[a.employment]) delete a.employment;
  if (INCOMES.indexOf(a.income) < 0) delete a.income;
  if (!LABELS.credit[a.credit]) delete a.credit;
  if (!stateName(a.state)) delete a.state;

  // Read once. What the landing URL carried is kept for the session, so a
  // trip to the terms page and back does not lose it.
  (function readAttribution() {
    var params;
    try { params = new URLSearchParams(window.location.search); } catch (e) { return; }
    var found = {}, any = false;
    ATTRIBUTION.forEach(function (k) {
      var v = params.get(k);
      if (v) { found[k] = v; any = true; }
    });
    if (any) state.attr = found;
  })();
  save();

  // --- network: fire and forget --------------------------------------------

  function withAttribution(payload) {
    payload.session_id = state.sid;
    ATTRIBUTION.forEach(function (k) {
      if (state.attr[k]) payload[k] = state.attr[k];
    });
    return JSON.stringify(payload);
  }

  function post(url, body) {
    try {
      fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body,
        keepalive: true,
        credentials: "omit"
      }).catch(function () {});
    } catch (e) { /* never the visitor's problem */ }
  }

  function track(event, step, extra) {
    var payload = { event: event };
    if (step != null) payload.step = step;
    if (extra) payload.extra = extra;
    var body = withAttribution(payload);
    try {
      if (navigator.sendBeacon && navigator.sendBeacon("/api/loans/event", body)) return;
    } catch (e) { /* fall through to fetch */ }
    post("/api/loans/event", body);
  }

  // Once per session, so a reload or an edited answer does not count twice.
  function trackOnce(key, event, step) {
    if (state.sent[key]) return;
    state.sent[key] = 1;
    save();
    track(event, step);
  }

  function sendLead() {
    post("/api/loans/lead", withAttribution({
      amount: a.amount, purpose: a.purpose, employment: a.employment,
      income: a.income, credit: a.credit, state: a.state
    }));
  }

  // --- views ---------------------------------------------------------------

  function ready(view) {
    switch (view) {
      case "income": return !!a.purpose;
      case "credit": return !!(a.purpose && a.employment && a.income);
      case "options":
      case "offers":
        return !!(a.purpose && a.employment && a.income && a.credit && a.state);
      default: return true;
    }
  }

  // The furthest view at or before `view` that the answers so far allow.
  function resolve(view) {
    var target = VIEWS.indexOf(view);
    if (target < 0) return "landing";
    for (var i = 1; i <= target; i++) {
      if (!ready(VIEWS[i])) return VIEWS[i - 1];
    }
    return view;
  }

  function money(n) { return "$" + Number(n).toLocaleString("en-US"); }

  function setPressed(container, value) {
    var buttons = container.querySelectorAll("button[data-value]");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].setAttribute("aria-pressed",
        buttons[i].getAttribute("data-value") === value ? "true" : "false");
    }
  }

  function renderHeader(view) {
    var label = $("top-label"), link = $("top-link"), bar = $("progress");
    var step = STEP_OF[view];
    link.hidden = true;
    label.hidden = false;
    bar.hidden = !step;
    if (step) {
      label.textContent = "Step " + step + " of 3";
      bar.setAttribute("aria-label", "Step " + step + " of 3");
      var segs = bar.children;
      for (var i = 0; i < segs.length; i++) {
        segs[i].className = i < step ? "is-on" : "";
      }
    } else if (view === "landing") {
      label.textContent = "Free to compare";
    } else {
      label.hidden = true;
      link.hidden = false;
      link.textContent = view === "options" ? "Edit answers" : "Back";
    }
  }

  function renderAmount() {
    var input = $("amount");
    input.value = a.amount;
    $("amount-value").textContent = money(a.amount);
    input.setAttribute("aria-valuetext", money(a.amount));
    input.style.setProperty("--fill",
      ((a.amount - AMOUNT_MIN) / (AMOUNT_MAX - AMOUNT_MIN) * 100) + "%");
  }

  function renderOptions() {
    var place = a.state === "DC" ? "Washington, DC" : stateName(a.state);
    $("options-title").textContent =
      "Options for a " + money(a.amount) + " loan in " + place;
    var chips = $("options-chips");
    chips.textContent = "";
    [LABELS.purpose[a.purpose], LABELS.employment[a.employment],
      LABELS.credit[a.credit]].forEach(function (text) {
      var li = document.createElement("li");
      li.textContent = text;
      chips.appendChild(li);
    });
  }

  function chevron() {
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("class", "ico");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    var path = document.createElementNS(ns, "path");
    path.setAttribute("d", "m9 6 6 6-6 6");
    svg.appendChild(path);
    return svg;
  }

  function renderOffers() {
    var list = $("offers"), pending = false;
    list.textContent = "";
    OFFERS.forEach(function (offer) {
      var li = document.createElement("li");
      var row = document.createElement("a");
      row.className = "offer";
      var text = document.createElement("span");
      text.textContent = offer.label;
      row.appendChild(text);
      if (offer.url) {
        row.href = offer.url;
        row.rel = "sponsored noopener";
        row.target = "_blank";
        row.appendChild(chevron());
        row.addEventListener("click", function () {
          track("offer_tap", null, { slot: offer.id });
        });
      } else {
        // No href: a link that goes nowhere is never shipped.
        pending = true;
        row.setAttribute("role", "link");
        row.setAttribute("aria-disabled", "true");
      }
      li.appendChild(row);
      list.appendChild(li);
    });
    $("offers-empty").hidden = !pending;
  }

  function syncButtons() {
    $("go-credit").disabled = !(a.employment && a.income);
    $("go-options").disabled = !(a.credit && a.state);
  }

  var current = null;

  function show(view, focus) {
    var sections = document.querySelectorAll(".view");
    for (var i = 0; i < sections.length; i++) {
      sections[i].hidden = sections[i].getAttribute("data-view") !== view;
    }
    renderHeader(view);
    if (view === "landing") renderAmount();
    if (view === "purpose") setPressed($("purpose-tiles"), a.purpose);
    if (view === "income") {
      setPressed($("employment-toggles"), a.employment);
      $("income").value = a.income || "";
    }
    if (view === "credit") {
      setPressed($("credit-rows"), a.credit);
      $("state").value = a.state || "";
    }
    if (view === "options") renderOptions();
    if (view === "offers") renderOffers();
    syncButtons();

    current = view;
    state.view = view;
    save();

    window.scrollTo(0, 0);
    if (focus) {
      var h1 = $("view-" + view).querySelector("h1");
      if (h1) { try { h1.focus({ preventScroll: true }); } catch (e) { h1.focus(); } }
    }
    if (view === "options") trackOnce("result", "result_view");
  }

  function historyState(view) { return { v: view, i: VIEWS.indexOf(view) }; }

  function go(view) {
    view = resolve(view);
    try { history.pushState(historyState(view), ""); } catch (e) {}
    show(view, true);
  }

  function back() {
    var i = VIEWS.indexOf(current);
    if (i <= 0) return;
    var s = history.state;
    if (s && s.v === current && s.i > 0) {
      history.back();          // popstate does the rest
      return;
    }
    var prev = VIEWS[i - 1];
    try { history.replaceState(historyState(prev), ""); } catch (e) {}
    show(prev, true);
  }

  window.addEventListener("popstate", function (e) {
    var s = e.state;
    show(resolve(s && s.v ? s.v : "landing"), true);
  });

  // --- wiring --------------------------------------------------------------

  (function fillStates() {
    var select = $("state");
    STATES.forEach(function (pair) {
      var opt = document.createElement("option");
      opt.value = pair[0];
      opt.textContent = pair[1];
      select.appendChild(opt);
    });
  })();

  $("amount").addEventListener("input", function () {
    var n = parseInt(this.value, 10);
    if (validAmount(n)) { a.amount = n; save(); renderAmount(); }
  });

  $("go-compare").addEventListener("click", function () {
    trackOnce("s1", "swipe", 1);
    go("purpose");
  });

  $("purpose-tiles").addEventListener("click", function (e) {
    var tile = e.target.closest ? e.target.closest("button[data-value]") : null;
    if (!tile) return;
    a.purpose = tile.getAttribute("data-value");
    save();
    setPressed(this, a.purpose);
    trackOnce("s2", "swipe", 2);
    go("income");
  });

  function toggleGroup(id, key) {
    $(id).addEventListener("click", function (e) {
      var btn = e.target.closest ? e.target.closest("button[data-value]") : null;
      if (!btn) return;
      a[key] = btn.getAttribute("data-value");
      save();
      setPressed(this, a[key]);
      syncButtons();
    });
  }
  toggleGroup("employment-toggles", "employment");
  toggleGroup("credit-rows", "credit");

  $("income").addEventListener("change", function () {
    if (INCOMES.indexOf(this.value) >= 0) a.income = this.value; else delete a.income;
    save();
    syncButtons();
  });

  $("state").addEventListener("change", function () {
    if (stateName(this.value)) a.state = this.value; else delete a.state;
    save();
    syncButtons();
  });

  $("go-credit").addEventListener("click", function () {
    if (!ready("credit")) return;
    trackOnce("s3", "swipe", 3);
    go("credit");
  });

  $("go-options").addEventListener("click", function () {
    if (!ready("options")) return;
    trackOnce("s4", "swipe", 4);
    sendLead();                // fire and forget: the options show either way
    go("options");
  });

  $("go-offers").addEventListener("click", function () {
    track("offer_tap", null, { slot: "options_cta" });
    go("offers");
  });

  $("top-link").addEventListener("click", back);
  var backs = document.querySelectorAll("[data-back]");
  for (var k = 0; k < backs.length; k++) backs[k].addEventListener("click", back);

  // --- start ---------------------------------------------------------------

  (function start() {
    var s = history.state;
    var view;
    if (s && s.v && VIEWS.indexOf(s.v) >= 0) {
      // A reload, or the back button returning from another page: the stack
      // under this entry is already ours.
      view = resolve(s.v);
      if (view !== s.v) { try { history.replaceState(historyState(view), ""); } catch (e) {} }
    } else {
      // A fresh navigation. Resume where the session was, and lay the earlier
      // views under it so back still walks through them.
      view = resolve(state.view || "landing");
      var upto = VIEWS.indexOf(view);
      try {
        history.replaceState(historyState(VIEWS[0]), "");
        for (var i = 1; i <= upto; i++) history.pushState(historyState(VIEWS[i]), "");
      } catch (e) {}
    }
    show(view, false);
    trackOnce("start", "funnel_start");
  })();
})();
