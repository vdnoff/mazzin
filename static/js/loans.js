/* Loan Options funnel (/loans). One IIFE, no framework, no build step.
 *
 * Not the swipe engine: this page does not load engine.js and has no funnel
 * config. It asks six closed questions, posts the answers once, and links to
 * a partner's articles, labelled as a partner site that shows ads. It holds
 * no name, contact detail or free text, and a network call that fails is
 * never shown and never blocks a tap.
 */
(function () {
  "use strict";

  // The partner's articles (Campaign Links). The summary view shows four: the
  // one for the loan purpose, the one for the credit range, and the two
  // general ones. A link is stored bare, with no query string; the click
  // identifiers held below are the only thing ever added to it.
  var ARTICLES = {
    "purpose_emergency": {
      label: "Covering an unexpected expense",
      link: "https://openresourcelist.com/AsTm9Loi4hUFQfGXTBPbhLzQ690-EuCOvXUZSznAKRbjb9AhKrJCCfgwdDxTCoBFq_yxr4Tfx9_CbwPnw1ZqO9CE8_N74n4fjbvkNYU7Gy_CAqk9Wz8AzyToPiqpzVHO5Op2WYC6Y3mYigtpjomIN7QEUDYVEcS4gXsSZJIL1IVatpuHC4t8W622YRyNRg0K6PV1nf3jR0L2yAGVx2Zh57CtwZbcNEyzeQDYqskuw5KCX85XMVX0KtJ093NlaNJALlJuAM0jYn9-QTfA"
    },
    "purpose_debt": {
      label: "How debt consolidation loans work",
      link: "https://basicsitecatalog.com/AoN_2NvrLJdndkLBEjLS5oxsCyhaysmabsNida28jQzfns5W343mjhYDK3uZFC9TilHiv1YGI5MpPTyed66bwj0CgotWHKXa6SmL33vXD6UY-ypLwbR7v4uMyNuPpnqbDy_6bAFX9aqnEUpotSWQXGOcQEIA7F_UWXbNXG5kHlpYRCn5OnAMWJMACDbiL0CkblUb-hEwcoKLl2ef5AWrELiT7ulLJQ0FXfwhwbWzGAGovtPcTYM"
    },
    "purpose_car": {
      label: "Paying for a car repair",
      link: "https://basicwebregister.com/AqMxslxaBo5A2-FtLJd6eoUD3kYuKG24uSm6vkInpP74sYNzFUcJdd6_rDfnedCfU_IfzqNOyEBSqMf4wWLvj6hu7UyHjef9TbVm4WCAErYWquSlTqGIHggygBG-uZM-EEs38fvE3zF6y3ZN-NgrdWObTBt4vju-e5vxg_x3kjgocN-w_cMOMIwriiXeY-TvtwVqeMEpLT9O0FK3hRE6_KFucWADm4yUrdd2ewMqHVmTVkTpfQ"
    },
    "purpose_home": {
      label: "Home improvement loans: what to compare",
      link: "https://topicregister.com/AlazqAPb1H0_NbTR8i_sxdjMyFOCIPQ8HoJLdfIy2UilNX_cRBT7ZmxKl258GtWBuBuS1uziKD-GsS8j1paULNNWFUlvSaAgjZbUFXB0MqCHqveAuJuChbRMJvLwKvK54J2X_26n0_Aa2Mf9O0QDGkr1w4c-bpHyS5VIDqbKbiPSBi41UdPDqKhJHfaP5zEWS0ZenvmbL7J92M-1BKbbvUgcwo2bSCrBVd2R0g0Slk01gw"
    },
    "purpose_medical": {
      label: "Medical bills: plans, help and loans",
      link: "https://browserreference.com/Ag61mGNyCYbKRJWtQdw474-q6xYlVMF4__D6DpxK2eZa6IK4wr-oY9wCZnrLTca8EntIQR3isbiVjz6VDIpEs5dFAyWtYNuxA4TZPnF_i_rBWMSYR_efAmbd4rSMLFDzwUkiKb3BcirGdhcCgnc-7y3NlMetnf3yRDUafTlJ7bqdTgsZvNiRNzM0TVVhEEJdgtLnFe_woSdYG8pyQ0crA7Spixsniy3ELLP-IrqAH9sD4IPsQ-Wr5UI"
    },
    "purpose_other": {
      label: "How personal loans work",
      link: "https://browserreference.com/AtoHmw03FDNwu_xiOzJDItfQNOFSqChO5V3gCUzYHwCiJeu1t7ZD1hdUlw7R-nTYkdCjyxFRuz1Fi_OTII3OOHEwyERnUnhdFxJbFmNgCJYRWUdBjBTx7nk6SOfalFm7aagqX8aByil4GhsgdFmZLj803eoQTzcFUbPXsY-OEYOLl7KZT5VLkPKjSrpu-EJ66dqxE2WBif0ylXXYpkOIJiVsnFcTjSfYFMShlELcRyZYbWC_SPhMUw"
    },
    "credit_excellent": {
      label: "Getting the lowest rate with strong credit",
      link: "https://generalentrypage.com/AoMm9dGPeVkm4oYwLfKNvejnMD0EJteD89wCr2v27kDm4g2iSGilnoTsqiDohLHMIcp72gG0q22M5U0lEPaAlWXEIrocWDLhAXwdGl4PEao-lB07rHyKUzeaFEDDKXt_b7eRLjM2nIYMMZ7i-x8AM57wZLbW9qlnCRXqG2-WP11VNPVd82lLBfXGDdnPSkVzDJJUaJooRKLC5RQDCuvSLNRMyHNuJJSCEDVGxCgxcNKtD3XsTOoPkQ"
    },
    "credit_good": {
      label: "Comparing offers with good credit",
      link: "https://topiclisting.com/Atb9pM40PGeRJa5RTZvvjCuVOI2wrA4S0zQ7G6JowBwR9ysm009h1aSJwSskn_c1Du7zzg6TgmVZ4J2e5kzbdKK263eXoPbgEN-BqqUlQulgdJQN27b5A-qIhYSJkA--Wf3eGNfE-9mggEn3NvgqolN-maA9q297LKgkgmtaPLxxAXE5JZlbtLaTYZqlze4AUTsEHp7nLCK2TlU1lsb7AS8tvskd8fCjuxJixDpdpShWQD_oqD7Xc1blkUrPvKMkklwufHnEzA65-Cjy"
    },
    "credit_fair": {
      label: "Personal loans for fair credit",
      link: "https://topiclisting.com/AoIIaqhTcpPf3gqLuhLWqdBDJbcLV9UzoUmRcsswu_xPXl4PnvAJixOrnCmAIHPSc8Rs8iribg_XvXacd8J5H8JalOkDv5876By09mhLZHETstgPkop8UBiJ23hrA5qDdQBp6l53aJ2JHx3caW8UcStGX_PDb-2RERJ3-hKZJIchFFQj_LM76t08LNHXaXo0LnwvFeRyJ_YNawomxSpEXeUnnWeE6g6GAaeiaL0jpkX8GR9e_X6GKZ3l"
    },
    "credit_building": {
      label: "Borrowing with low or thin credit",
      link: "https://browseroverview.com/AjN2kqdWFs_u4gir7AgI3rApZ3-gxHGS6KMYHU7iJto7TPIh1-c3qWOo6BlsSzgmppSg8idVTurZUA2SETCJu5VlPc_uLVOtEQ3bxHeRNVMQiEG3-YfXwNTD8xgrx2DEg-2cGXbYBvILS_qA0Ye0n72lKdbfbK4Mb1knSewewFf-7kybCeL3GjGbtu2UfwmXpQpgleg8jBEuFdgKlRbrS54rJc9lLEdjnGmrnPqF8gKPtUP_DXep6zJr6okmPb4O3NjDLa_3RV1_Sw"
    },
    "general_small": {
      label: "Small personal loans: costs and options",
      link: "https://topiclisting.com/AkBkm3gpDHDLnx3SkWJ9_eTmTBJT0waawtlcmiga-X5vD7cb53Vp5L8tOPJKK-HJz7wiEzDuBzDLYPTD1zbQtIk2MYuukvN4mzHsuVrNUI87muMcKAO5TJ-H8kIxYi2_8oE-bJgEzfHlrfvE8fq4PMZo7htZw-GVR6BIbeNMRooMg2hnXuLy_0Qkupu7GlJhztgzHWN-uMbz00j24hyU3S8zYBS09zEx5JAW90my7oI-nJE"
    },
    "general_apr": {
      label: "How to read a loan offer",
      link: "https://topicregister.com/AsvAFZVmmbNgk20XqJQo9SVb9LvCIErHGXvAv6Lm6a3kxATLEr1WFv0svEtys-CJzLKMGqiRMakhB4BG437NW-ZSs8d5745_8uUmiyl_GXWk8b-EAKBGvms275vnTB1KcWwmjlxwawvw8_J60sC6O78DYA_Ly0PzUrJ_Km-rFZmCjSQWYfY-pPmIs03NyAwRwu-U9QDI8Cl9c65nfCtsMBZ6"
    }
  };
  var GENERAL = ["general_small", "general_apr"];

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
  var VIEWS = ["landing", "purpose", "income", "credit", "options"];
  // Views this page once had. A tab that was left on one resumes on the view
  // that took its place, never on a blank page.
  var RETIRED = { guides: "options", offers: "options" };
  var STEP_OF = { purpose: 1, income: 2, credit: 3 };
  var ATTRIBUTION = ["subid", "utm_source", "utm_campaign", "utm_content", "utm_term"];
  var STORE_KEY = "mazzin_loans";
  var PASS_KEY = "mazzin_pass_loans";
  // The click identifiers the partner needs, in the order they are written
  // into a link, each with the rule a value must pass to be kept. An empty
  // value and an unresolved ad-platform macro ("{{ad.id}}") both fail.
  var PASS_ORDER = ["fbclid", "ad_id", "asid"];
  var PASS_RULES = {
    fbclid: /^[A-Za-z0-9_-]{1,512}$/,
    ad_id: /^[0-9]{1,32}$/,
    asid: /^[0-9]{1,32}$/
  };
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
  if (RETIRED.hasOwnProperty(state.view)) state.view = RETIRED[state.view];
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

  // --- click identifiers passed on to the partner ---------------------------
  //
  // Read off the URL on every load and kept in sessionStorage for this tab,
  // so they outlive all five views, a reload, back and forward, and a second
  // arrival on a bare /loans URL. A load without them clears nothing. Their
  // only reader is articleHref(): they are never posted to /api/loans/* and
  // never put on an event.
  var passMemory = {};

  function passValid(source) {
    var out = {};
    PASS_ORDER.forEach(function (k) {
      var v = source ? source[k] : null;
      if (typeof v === "string" && v.indexOf("{{") < 0 && v.indexOf("}}") < 0 &&
          PASS_RULES[k].test(v)) out[k] = v;
    });
    return out;
  }

  function heldPass() {
    var stored = null;
    try { stored = JSON.parse(sessionStorage.getItem(PASS_KEY) || "null"); }
    catch (e) { stored = null; }
    return passValid(stored && typeof stored === "object" ? stored : passMemory);
  }

  (function keepPass() {
    var held = heldPass(), seen = {};
    try {
      var params = new URLSearchParams(window.location.search);
      PASS_ORDER.forEach(function (k) {
        var v = params.get(k);
        if (v !== null) seen[k] = v;
      });
    } catch (e) { /* no URLSearchParams: nothing new to keep */ }
    var fresh = passValid(seen);
    for (var k in fresh) held[k] = fresh[k];
    passMemory = held;
    try { sessionStorage.setItem(PASS_KEY, JSON.stringify(held)); }
    catch (e) { /* private mode: held for this page load only */ }
  })();

  function hasClick() { return !!heldPass().fbclid; }

  // The article's link plus the held identifiers and nothing else. No link at
  // all without an fbclid, or for a link that is not a bare https URL.
  function articleHref(key) {
    var article = ARTICLES.hasOwnProperty(key) ? ARTICLES[key] : null;
    var held = heldPass();
    if (!article || !held.fbclid) return "";
    var link = article.link;
    if (typeof link !== "string" || link.indexOf("https://") !== 0 ||
        link.indexOf("?") >= 0 || link.indexOf("#") >= 0) return "";
    var query = new URLSearchParams();
    PASS_ORDER.forEach(function (k) {
      if (held[k]) query.append(k, held[k]);
    });
    return link + "?" + query.toString();
  }

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
      link.textContent = "Edit answers";
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
    // No click to pass on means no guides: no block and no anchor at all.
    var on = hasClick() && renderGuides() > 0;
    $("guides-block").hidden = !on;
    $("guides-none").hidden = on;
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

  function renderGuides() {
    var list = $("guides");
    list.textContent = "";
    if (!hasClick()) return 0;
    ["purpose_" + a.purpose, "credit_" + a.credit].concat(GENERAL)
      .forEach(function (key) {
        var href = articleHref(key);
        if (!href) return;         // refused: no row is better than a dead one
        var li = document.createElement("li");
        var row = document.createElement("a");
        row.className = "guide";
        row.href = href;
        row.target = "_blank";
        row.rel = "noopener";
        row.setAttribute("data-article", key);
        var text = document.createElement("span");
        text.textContent = ARTICLES[key].label;
        row.appendChild(text);
        row.appendChild(chevron());
        // Reported on the way out and never waited for: the tab opens
        // whatever becomes of the request.
        row.addEventListener("click", function () {
          track("offer_tap", null, { slot: key });
        });
        li.appendChild(row);
        list.appendChild(li);
      });
    return list.children.length;
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

  $("top-link").addEventListener("click", back);
  var backs = document.querySelectorAll("[data-back]");
  for (var k = 0; k < backs.length; k++) backs[k].addEventListener("click", back);

  // --- start ---------------------------------------------------------------

  (function start() {
    var s = history.state;
    var view;
    if (s && RETIRED.hasOwnProperty(s.v)) {
      s = historyState(RETIRED[s.v]);
      try { history.replaceState(s, ""); } catch (e) {}
    }
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
