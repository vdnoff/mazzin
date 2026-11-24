/* RSOC quiz engine. One IIFE, no framework, no build step.
 *
 * Serves every quiz under funnels/rsoc/: the page names its slug, this file
 * fetches /static/funnels/rsoc/<slug>.json and draws everything from it —
 * the questions, the answers, the article rows, the rules that pick them,
 * every word on the page. Nothing a reader sees is written here.
 *
 * It asks closed tap questions and ends on three partner article links. It
 * posts no answers, takes no contact detail and makes no payment. What the
 * server hears is an event; the click identifiers the partner needs are held
 * in this tab and written into the links, and nowhere else.
 *
 * Tracking, identifier passthrough and the partner pixel behave as /loans
 * does. This file is a reimplementation, not a reuse: it shares no code with
 * loans.js and /loans is untouched by it.
 *
 * The two pure parts — the row resolver and the link builder — are exported
 * when this file is loaded by Node, so the tests exercise this code and not
 * a copy of it.
 */
(function () {
  "use strict";

  // --- pure: which rows ------------------------------------------------------
  //
  // `rules.rows` is an ordered list. Each entry picks one article key:
  //   { "always": key }
  //   { "by": stepId, "map": { answer: key, ... },
  //     "else": <entry>, "default": key, "fallback": [key, ...] }
  // `map` is read first; an answer it does not name goes to `else` (another
  // entry, read the same way) and then to `default`. A key an earlier row
  // already took is replaced by the first unused key in `fallback`. A row
  // that ends with nothing, or only with a taken key, is left out.

  function pick(rule, answers) {
    if (!rule || typeof rule !== "object") return "";
    if (typeof rule.always === "string") return rule.always;
    var value = answers ? answers[rule.by] : undefined;
    var map = rule.map || {};
    if (typeof value === "string" && Object.prototype.hasOwnProperty.call(map, value)) {
      return map[value];
    }
    if (rule["else"]) {
      var inner = pick(rule["else"], answers);
      if (inner) return inner;
    }
    return typeof rule["default"] === "string" ? rule["default"] : "";
  }

  function resolveRows(cfg, answers) {
    var rows = (cfg && cfg.rules && cfg.rules.rows) || [];
    var articles = (cfg && cfg.articles) || {};
    var out = [];
    rows.forEach(function (rule) {
      var key = pick(rule, answers);
      if (!key || out.indexOf(key) !== -1) {
        key = "";
        var chain = (rule && rule.fallback) || [];
        for (var i = 0; i < chain.length; i++) {
          if (out.indexOf(chain[i]) === -1) { key = chain[i]; break; }
        }
      }
      if (key && Object.prototype.hasOwnProperty.call(articles, key) &&
          out.indexOf(key) === -1) out.push(key);
    });
    return out;
  }

  // --- pure: the identifiers and the link ------------------------------------
  //
  // The three the partner needs, in the order they are written into a link,
  // each with the rule a value must pass. An empty value and an unresolved
  // ad-platform macro ("{{ad.id}}") both fail.
  var PASS_ORDER = ["fbclid", "ad_id", "asid"];
  var PASS_RULES = {
    fbclid: /^[A-Za-z0-9_-]{1,512}$/,
    ad_id: /^[0-9]{1,32}$/,
    asid: /^[0-9]{1,32}$/
  };

  function passValid(source) {
    var out = {};
    PASS_ORDER.forEach(function (k) {
      var v = source ? source[k] : null;
      if (typeof v === "string" && v.indexOf("{{") < 0 && v.indexOf("}}") < 0 &&
          PASS_RULES[k].test(v)) out[k] = v;
    });
    return out;
  }

  // The link plus the held identifiers and nothing else. No link without an
  // fbclid, and none for a link that is not a bare https URL.
  function hrefFor(link, held) {
    held = passValid(held);
    if (!held.fbclid) return "";
    if (typeof link !== "string" || link.indexOf("https://") !== 0 ||
        link.indexOf("?") >= 0 || link.indexOf("#") >= 0) return "";
    var query = new URLSearchParams();
    PASS_ORDER.forEach(function (k) {
      if (held[k]) query.append(k, held[k]);
    });
    return link + "?" + query.toString();
  }

  var api = { resolveRows: resolveRows, hrefFor: hrefFor, passValid: passValid };
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
    return;
  }
  if (typeof document === "undefined") return;

  // --- the page --------------------------------------------------------------

  var SLUG_RE = /^[a-z0-9_-]{1,32}$/;
  var ATTRIBUTION = ["subid", "utm_source", "utm_campaign", "utm_content", "utm_term"];
  var ICON_RE = /^[MmLlHhVvCcSsQqTtAaZz0-9 .,\-]{1,400}$/;
  var PIXEL_RE = /^[0-9]{5,20}$/;
  var EVENT_NAME_RE = /^[A-Za-z]{1,40}$/;
  var SVG_NS = "http://www.w3.org/2000/svg";

  var slug = document.body.getAttribute("data-rsoc") || "";
  if (!SLUG_RE.test(slug)) return;

  var STORE_KEY = "mazzin_rsoc_" + slug;
  var PASS_KEY = "mazzin_pass_" + slug;
  var EVENT_URL = "/api/rsoc/" + slug + "/event";

  function $(id) { return document.getElementById(id); }

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

  // --- state: this tab's session ---------------------------------------------

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
    return { sid: uuid(), answers: {}, sent: {}, attr: {}, view: "" };
  }

  function save() {
    try { sessionStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch (e) {}
  }

  var state = load();

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

  // --- the click identifiers -------------------------------------------------
  //
  // Read off the URL on every load and kept in sessionStorage for this tab, so
  // they outlive every view, a reload, back and forward, and a second arrival
  // on a bare URL. A load without them clears nothing. Their only reader is
  // hrefFor(): never posted, never put on an event.
  var passMemory = {};

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
    } catch (e) { /* nothing new to keep */ }
    var fresh = passValid(seen);
    for (var k in fresh) held[k] = fresh[k];
    passMemory = held;
    try { sessionStorage.setItem(PASS_KEY, JSON.stringify(held)); }
    catch (e) { /* private mode: held for this page load only */ }
  })();

  function hasClick() { return !!heldPass().fbclid; }

  // --- our events: fire and forget -------------------------------------------

  function track(event, step, extra) {
    var payload = { event: event, session_id: state.sid };
    if (step != null) payload.step = step;
    if (extra) payload.extra = extra;
    ATTRIBUTION.forEach(function (k) {
      if (state.attr[k]) payload[k] = state.attr[k];
    });
    var body = JSON.stringify(payload);
    try {
      if (navigator.sendBeacon && navigator.sendBeacon(EVENT_URL, body)) return;
    } catch (e) { /* fall through to fetch */ }
    try {
      fetch(EVENT_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body,
        keepalive: true,
        credentials: "omit"
      }).catch(function () {});
    } catch (e) { /* never the visitor's problem */ }
  }

  // Once per session, so a reload or an edited answer does not count twice.
  function trackOnce(key, event, step, extra) {
    if (state.sent[key]) return;
    state.sent[key] = 1;
    save();
    track(event, step, extra);
  }

  // --- the partner's pixel -----------------------------------------------------
  //
  // The article partner's pixel, named by the config. Three events: a page
  // view on load, the result event once a session, and the tap event on
  // every row tap. The result and tap events are named by the config too,
  // with whether each is a custom event; the partner's article page sends its
  // own events on the same pixel and those are never sent from here.
  //
  // Every call names the pixel (`trackSingle`, `trackSingleCustom`). No
  // advanced matching and no user data. Meta's script is fetched async after
  // the first view is on screen; blocked or offline, the calls sit in a queue
  // nobody reads and the page is what it was.
  var pixelId = "";

  function pixel() {
    try {
      if (typeof window.fbq === "function") window.fbq.apply(window, arguments);
    } catch (e) { /* measurement never breaks the page */ }
  }

  function pixelSend(spec, params) {
    if (!pixelId || !spec || !EVENT_NAME_RE.test(spec.name || "")) return;
    var method = spec.custom ? "trackSingleCustom" : "trackSingle";
    if (params) pixel(method, pixelId, spec.name, params);
    else pixel(method, pixelId, spec.name);
  }

  function pixelStart(id) {
    if (!PIXEL_RE.test(id || "")) return;
    try {
      if (!window.fbq) {
        var n = window.fbq = function () {
          if (n.callMethod) n.callMethod.apply(n, arguments);
          else n.queue.push(arguments);
        };
        if (!window._fbq) window._fbq = n;
        n.push = n;
        n.loaded = true;
        n.version = "2.0";
        n.queue = [];
      }
    } catch (e) { return; }
    pixelId = id;
    pixel("init", pixelId);
    pixelSend({ name: "PageView", custom: false });
  }

  function pixelLoad() {
    if (!pixelId) return;
    try {
      var tag = document.createElement("script");
      tag.async = true;
      tag.src = "https://connect.facebook.net/en_US/fbevents.js";
      document.head.appendChild(tag);
    } catch (e) { /* blocked or offline: nothing depends on it */ }
  }

  // --- building blocks -------------------------------------------------------

  function elm(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function icon(d, cls) {
    var svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("class", cls || "ico");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    var path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", d);
    svg.appendChild(path);
    return svg;
  }

  var CHEVRON = "m9 6 6 6-6 6";
  var CARET = "m6 9 6 6 6-6";

  // A sentence made of strings and {label, href} links, built node by node.
  function sentence(cls, parts) {
    var p = elm("p", cls);
    (parts || []).forEach(function (part) {
      if (typeof part === "string") p.appendChild(document.createTextNode(part));
      else if (part && typeof part.href === "string" && part.href.charAt(0) === "/") {
        var a = elm("a", "", part.label || "");
        a.href = part.href;
        p.appendChild(a);
      }
    });
    return p;
  }

  // --- the quiz --------------------------------------------------------------

  var cfg = null;
  var steps = [];
  var VIEWS = [];
  var current = null;
  var a = state.answers;
  var stateStep = "";

  function stepById(id) {
    for (var i = 0; i < steps.length; i++) if (steps[i].id === id) return steps[i];
    return null;
  }

  function optionLabel(stepId, value) {
    var step = stepById(stepId);
    var opts = (step && step.options) || [];
    for (var i = 0; i < opts.length; i++) if (opts[i].id === value) return opts[i].label;
    return "";
  }

  function stateName(code) {
    var list = (cfg.state_select && cfg.state_select.options) || [];
    for (var i = 0; i < list.length; i++) if (list[i][0] === code) return list[i][1];
    return "";
  }

  function cleanAnswers() {
    steps.forEach(function (step) {
      if (a[step.id] != null && !optionLabel(step.id, a[step.id])) delete a[step.id];
    });
    if (a.state != null && !stateName(a.state)) delete a.state;
  }

  // A step is reachable once every step before it is answered; the result
  // once every step is, and the state where the config asks for one.
  function ready(view) {
    var i = VIEWS.indexOf(view);
    if (i < 0) return false;
    for (var j = 0; j < Math.min(i, steps.length); j++) {
      if (!a[steps[j].id]) return false;
    }
    if (view === "result" && stateStep && !a.state) return false;
    return true;
  }

  function resolve(view) {
    var target = VIEWS.indexOf(view);
    if (target < 0) return VIEWS[0];
    for (var i = 1; i <= target; i++) {
      if (!ready(VIEWS[i])) return VIEWS[i - 1];
    }
    return view;
  }

  function setPressed(container, value) {
    var buttons = container.querySelectorAll("button[data-value]");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].setAttribute("aria-pressed",
        buttons[i].getAttribute("data-value") === value ? "true" : "false");
    }
  }

  function syncButton() {
    var btn = $("go-result");
    if (btn) btn.disabled = !(a[stateStep] && a.state);
  }

  function choose(step, index, value) {
    a[step.id] = value;
    save();
    setPressed($("choices-" + step.id), value);
    trackOnce("start", "quiz_start");
    if (step.id === stateStep) { syncButton(); return; }
    trackOnce("s_" + step.id, "step", index + 1, { step: step.id });
    go(VIEWS[index + 1]);
  }

  function buildStep(step, index) {
    var section = elm("section", "view");
    section.id = "view-" + step.id;
    section.setAttribute("data-view", step.id);
    section.hidden = true;
    if (step.eyebrow) section.appendChild(elm("p", "eyebrow", step.eyebrow));

    var h1;
    if (index === 0) {
      h1 = elm("h1", "h1 h1-lg", cfg.headline || step.question);
      section.appendChild(h1);
      if (cfg.sub) section.appendChild(elm("p", "lede", cfg.sub));
      if (cfg.headline) section.appendChild(elm("h2", "question", step.question));
    } else {
      h1 = elm("h1", "h1 h1-md", step.question);
      section.appendChild(h1);
    }
    h1.tabIndex = -1;

    var opts = step.options || [];
    var withIcons = opts.length && opts.every(function (o) {
      return typeof o.icon === "string" && ICON_RE.test(o.icon);
    });
    var list = elm("div", withIcons ? "tiles" : "rows");
    list.id = "choices-" + step.id;
    list.setAttribute("role", "group");
    list.setAttribute("aria-label", step.question);
    opts.forEach(function (o) {
      var btn = elm("button", withIcons ? "tile" : "row-toggle");
      btn.type = "button";
      btn.setAttribute("data-value", o.id);
      btn.setAttribute("aria-pressed", "false");
      if (withIcons) btn.appendChild(icon(o.icon));
      btn.appendChild(elm("span", "", o.label));
      btn.addEventListener("click", function () { choose(step, index, o.id); });
      list.appendChild(btn);
    });
    section.appendChild(list);
    if (step.helper) section.appendChild(elm("p", "helper", step.helper));

    if (step.id === stateStep) {
      var ss = cfg.state_select;
      var label = elm("label", "field-label", ss.label || "");
      label.setAttribute("for", "state");
      section.appendChild(label);
      var wrap = elm("div", "select");
      var select = elm("select");
      select.id = "state";
      var first = elm("option", "", ss.placeholder || "");
      first.value = "";
      select.appendChild(first);
      (ss.options || []).forEach(function (pair) {
        var opt = elm("option", "", pair[1]);
        opt.value = pair[0];
        select.appendChild(opt);
      });
      select.addEventListener("change", function () {
        if (stateName(this.value)) a.state = this.value; else delete a.state;
        save();
        syncButton();
      });
      wrap.appendChild(select);
      wrap.appendChild(icon(CARET, "ico select-ico"));
      section.appendChild(wrap);

      var go_ = elm("button", "btn", ss.button || "");
      go_.id = "go-result";
      go_.type = "button";
      go_.disabled = true;
      go_.addEventListener("click", function () {
        if (!ready("result")) return;
        trackOnce("s_" + step.id, "step", index + 1, { step: step.id });
        go("result");
      });
      section.appendChild(go_);
      if (ss.consent) section.appendChild(sentence("consent", ss.consent));
    }

    if (index > 0 && cfg.labels && cfg.labels.back) {
      var back_ = elm("button", "back", cfg.labels.back);
      back_.type = "button";
      back_.addEventListener("click", back);
      section.appendChild(back_);
    }
    return section;
  }

  function buildResult() {
    var r = cfg.result || {};
    var section = elm("section", "view");
    section.id = "view-result";
    section.setAttribute("data-view", "result");
    section.hidden = true;
    if (r.eyebrow) section.appendChild(elm("p", "eyebrow", r.eyebrow));
    var h1 = elm("h1", "h1 h1-lg", r.headline || "");
    h1.tabIndex = -1;
    section.appendChild(h1);
    var chips = elm("ul", "chips");
    chips.id = "result-chips";
    if (r.chips_label) chips.setAttribute("aria-label", r.chips_label);
    section.appendChild(chips);
    if (r.line) section.appendChild(elm("p", "lede", r.line));
    var rows = elm("div", "guides-block");
    rows.id = "result-rows";
    section.appendChild(rows);
    if (r.disclaimer) section.appendChild(elm("p", "note disclaimer", r.disclaimer));
    var foot = elm("footer", "foot");
    var nav = elm("nav", "foot-links");
    (cfg.footer || []).forEach(function (link) {
      if (!link || typeof link.href !== "string" || link.href.charAt(0) !== "/") return;
      var x = elm("a", "", link.label || "");
      x.href = link.href;
      nav.appendChild(x);
    });
    foot.appendChild(nav);
    section.appendChild(foot);
    return section;
  }

  function rowTap(key) {
    // Reported on the way out and never waited for: a live row's tab opens
    // whatever becomes of either call.
    track("offer_tap", null, { slot: key });
    pixelSend(cfg.pixel_events && cfg.pixel_events.tap,
              { content_name: key, content_category: slug });
  }

  function renderResult() {
    var r = cfg.result || {};
    var chips = $("result-chips");
    chips.textContent = "";
    (r.chips || []).forEach(function (id) {
      var text = id === "state" ? stateName(a.state) : optionLabel(id, a[id]);
      if (text) chips.appendChild(elm("li", "", text));
    });

    var box = $("result-rows");
    box.textContent = "";
    // No click to pass on means no rows at all: no anchor, no placeholder.
    if (!hasClick()) {
      box.appendChild(elm("p", "guides-none", r.no_id_line || ""));
      return;
    }
    var list = elm("ul", "card guides");
    var waiting = false;
    resolveRows(cfg, a).forEach(function (key) {
      var article = cfg.articles[key];
      var li = elm("li");
      var row;
      if (article.link === "") {
        // Not live yet: a muted row that is no link, still counted on a tap.
        waiting = true;
        row = elm("span", "guide is-off");
        row.setAttribute("aria-disabled", "true");
      } else {
        var href = hrefFor(article.link, heldPass());
        if (!href) return;          // refused: no row is better than a dead one
        row = elm("a", "guide");
        row.href = href;
        row.target = "_blank";
        row.rel = "noopener";
      }
      row.setAttribute("data-article", key);
      row.appendChild(elm("span", "", article.label));
      row.appendChild(icon(CHEVRON));
      row.addEventListener("click", function () { rowTap(key); });
      li.appendChild(row);
      list.appendChild(li);
    });
    if (!list.children.length) {
      box.appendChild(elm("p", "guides-none", r.no_id_line || ""));
      return;
    }
    box.appendChild(list);
    if (r.pill) {
      var tag = elm("p", "guides-tag");
      tag.appendChild(elm("span", "pill", r.pill));
      box.appendChild(tag);
    }
    if (waiting && r.prefeed_line) box.appendChild(elm("p", "guides-none", r.prefeed_line));
  }

  function renderHeader(view) {
    var link = $("top-link"), bar = $("progress");
    var i = steps.length ? VIEWS.indexOf(view) : -1;
    var onStep = i >= 0 && i < steps.length;
    link.hidden = view !== "result";
    bar.hidden = !onStep;
    if (onStep) {
      var label = steps[i].eyebrow || "";
      bar.setAttribute("aria-label", label);
      for (var k = 0; k < bar.children.length; k++) {
        bar.children[k].className = k <= i ? "is-on" : "";
      }
    }
  }

  function show(view, focus) {
    var sections = document.querySelectorAll(".view");
    for (var i = 0; i < sections.length; i++) {
      sections[i].hidden = sections[i].getAttribute("data-view") !== view;
    }
    renderHeader(view);
    var step = stepById(view);
    if (step) setPressed($("choices-" + step.id), a[step.id]);
    if (view === stateStep) {
      $("state").value = a.state || "";
      syncButton();
    }
    if (view === "result") renderResult();

    current = view;
    state.view = view;
    save();

    window.scrollTo(0, 0);
    if (focus) {
      var h1 = $("view-" + view).querySelector("h1");
      if (h1) { try { h1.focus({ preventScroll: true }); } catch (e) { h1.focus(); } }
    }
    if (view === "result") {
      trackOnce("result", "result_view");
      if (!state.sent.px_result) {
        state.sent.px_result = 1;
        save();
        pixelSend(cfg.pixel_events && cfg.pixel_events.result);
      }
    }
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

  function build() {
    steps = (cfg.steps || []).filter(function (s) {
      return s && typeof s.id === "string" && Array.isArray(s.options);
    });
    VIEWS = steps.map(function (s) { return s.id; }).concat(["result"]);
    stateStep = (cfg.state_select && cfg.state_select.step) || "";
    if (!stepById(stateStep)) stateStep = "";
    cleanAnswers();

    if (cfg.title) document.title = cfg.title;
    var logo = $("logo");
    if (logo && cfg.labels && cfg.labels.logo) logo.setAttribute("aria-label", cfg.labels.logo);
    var link = $("top-link");
    link.textContent = (cfg.labels && cfg.labels.edit) || "";
    link.addEventListener("click", back);
    var bar = $("progress");
    steps.forEach(function () { bar.appendChild(elm("span")); });

    var app = $("app");
    steps.forEach(function (step, i) { app.appendChild(buildStep(step, i)); });
    app.appendChild(buildResult());

    window.addEventListener("popstate", function (e) {
      var s = e.state;
      show(resolve(s && s.v ? s.v : VIEWS[0]), true);
    });
  }

  function start() {
    var s = history.state;
    var view;
    if (s && s.v && VIEWS.indexOf(s.v) >= 0) {
      // A reload, or back from another page: the stack under this entry is
      // already ours.
      view = resolve(s.v);
      if (view !== s.v) { try { history.replaceState(historyState(view), ""); } catch (e) {} }
    } else {
      // A fresh navigation. Resume where the session was, and lay the earlier
      // views under it so back still walks through them.
      view = resolve(state.view || VIEWS[0]);
      var upto = VIEWS.indexOf(view);
      try {
        history.replaceState(historyState(VIEWS[0]), "");
        for (var i = 1; i <= upto; i++) history.pushState(historyState(VIEWS[i]), "");
      } catch (e) {}
    }
    pixelStart(cfg.pixel_id);
    show(view, false);
    pixelLoad();
  }

  function unavailable() {
    var note = $("unavailable");
    if (note) note.hidden = false;
  }

  fetch("/static/funnels/rsoc/" + slug + ".json", { cache: "no-cache" })
    .then(function (r) { if (!r.ok) throw new Error("config"); return r.json(); })
    .then(function (data) {
      if (!data || data.slug !== slug) throw new Error("config");
      cfg = data;
      build();
      start();
    })
    .catch(unavailable);
})();
