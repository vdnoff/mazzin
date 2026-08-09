/* Mazzin swipe engine — vanilla, no deps, one IIFE.
 * Boot -> swipe pairs -> analyzing -> result + locked report -> paywall.
 * Payments are Phase 1b; the pay button stays disabled behind a flag. */
(function () {
  "use strict";

  var PAYMENTS_ENABLED = false; // flip in Phase 1b
  var SLIDE_MS = 160;

  var cfg = null;
  var slug = location.pathname.split("/")[1] || "";
  var sessionId = null;
  var attribution = {};

  var scores = {};          // tag -> count
  var seen = {};            // image id -> true (shown, never reshown)
  var pair = [];            // current [imgA, imgB]
  var step = 0;             // pairs completed
  var byId = {};
  var paywallTracked = false;

  var el = {};

  // --- utils ---------------------------------------------------------------

  function $(id) { return document.getElementById(id); }

  function uuid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    // Fallback for older mobile Safari.
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
      var r = (Math.random() * 16) | 0;
      return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  function getSessionId() {
    var key = "mazzin_sid";
    var v;
    try { v = sessionStorage.getItem(key); } catch (e) { v = null; }
    if (!v) {
      v = uuid();
      try { sessionStorage.setItem(key, v); } catch (e) { /* private mode */ }
    }
    return v;
  }

  function readAttribution() {
    var p = new URLSearchParams(location.search);
    var out = {};
    ["subid", "utm_source", "utm_campaign", "utm_content", "utm_term"].forEach(function (k) {
      var v = p.get(k);
      if (v) out[k] = v;
    });
    return out;
  }

  // --- tracking ------------------------------------------------------------

  function track(event, stepNo) {
    var body = { funnel: slug, session_id: sessionId, event: event };
    if (stepNo) body.step = stepNo;
    for (var k in attribution) body[k] = attribution[k];

    var json = JSON.stringify(body);
    try {
      if (navigator.sendBeacon) {
        var blob = new Blob([json], { type: "application/json" });
        if (navigator.sendBeacon("/api/track", blob)) return;
      }
    } catch (e) { /* fall through */ }
    try {
      fetch("/api/track", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: json,
        keepalive: true
      });
    } catch (e) { /* tracking must never break the funnel */ }
  }

  // --- screens -------------------------------------------------------------

  function show(id) {
    var screens = document.querySelectorAll(".screen");
    for (var i = 0; i < screens.length; i++) {
      screens[i].classList.toggle("is-active", screens[i].id === id);
    }
    window.scrollTo(0, 0);
  }

  // --- pairing -------------------------------------------------------------

  function topTags() {
    return Object.keys(scores).sort(function (a, b) {
      return scores[b] - scores[a] || (a < b ? -1 : 1);
    });
  }

  function unseen() {
    return cfg.swipe.gallery.filter(function (g) { return !seen[g.id]; });
  }

  function pickByTag(pool, tag) {
    if (!tag) return null;
    var hits = pool.filter(function (g) { return g.tags.indexOf(tag) !== -1; });
    if (!hits.length) return null;
    return hits[Math.floor(Math.random() * hits.length)];
  }

  function pickRandom(pool) {
    if (!pool.length) return null;
    return pool[Math.floor(Math.random() * pool.length)];
  }

  function nextPair() {
    var pool = unseen();
    if (pool.length < 2) return null;

    var ranked = topTags();
    var a = pickByTag(pool, ranked[0]) || pickRandom(pool);
    var rest = pool.filter(function (g) { return g.id !== a.id; });
    var b = pickByTag(rest, ranked[1]) || pickRandom(rest);
    return [a, b];
  }

  // --- swipe screen --------------------------------------------------------

  function cardNode(item) {
    var card = document.createElement("button");
    card.type = "button";
    card.className = "card";
    card.setAttribute("aria-label", "Choose " + item.id);

    var img = document.createElement("img");
    img.className = "card-img";
    img.alt = "";
    img.decoding = "async";
    img.loading = "eager";
    img.onerror = function () {
      var ph = document.createElement("div");
      ph.className = "card-img card-placeholder";
      ph.textContent = item.id;
      if (img.parentNode) img.parentNode.replaceChild(ph, img);
    };
    img.src = item.img;

    card.appendChild(img);
    card.addEventListener("click", function () { choose(item); });
    return card;
  }

  function renderPair() {
    el.cards.innerHTML = "";
    pair.forEach(function (item) {
      seen[item.id] = true;
      el.cards.appendChild(cardNode(item));
    });
    el.cards.classList.remove("slide-out");
    el.cards.classList.add("slide-in");
    setTimeout(function () { el.cards.classList.remove("slide-in"); }, SLIDE_MS);
    renderProgress();
  }

  function renderProgress() {
    var total = cfg.swipe.pairs_count;
    var current = Math.min(step + 1, total);
    el.progressBar.style.width = ((step / total) * 100).toFixed(1) + "%";
    el.progressLabel.textContent = current + " of " + total;
  }

  function choose(item) {
    if (!pair.length) return;
    item.tags.forEach(function (t) { scores[t] = (scores[t] || 0) + 1; });
    step += 1;
    track("swipe", step);
    pair = [];

    el.cards.classList.add("slide-out");
    setTimeout(function () {
      if (step >= cfg.swipe.pairs_count) {
        el.progressBar.style.width = "100%";
        startResult();
        return;
      }
      var next = nextPair();
      if (!next) { startResult(); return; }
      pair = next;
      renderPair();
    }, SLIDE_MS);
  }

  // --- result --------------------------------------------------------------

  function computeWinner() {
    var total = 0;
    for (var t in scores) total += scores[t];

    var best = cfg.styles[0];
    var bestScore = -1;
    cfg.styles.forEach(function (s) {
      var sc = 0;
      s.tags.forEach(function (t) { sc += scores[t] || 0; });
      if (sc > bestScore) { bestScore = sc; best = s; }
    });

    var pct = total > 0 ? Math.round((100 * bestScore) / total) : 55;
    pct = Math.max(55, Math.min(95, pct));
    return { style: best, percent: pct };
  }

  function renderReport() {
    var sections = (cfg.report && cfg.report.sections) || [];
    el.report.innerHTML = "";
    sections.forEach(function (sec) {
      if (sec.enabled === false) return;

      var wrap = document.createElement("div");
      wrap.className = "section";

      var h = document.createElement("h2");
      h.className = "section-title";
      h.textContent = sec.title;
      wrap.appendChild(h);

      var locked = document.createElement("div");
      locked.className = "locked";

      var lines = document.createElement("div");
      lines.className = "blurred";
      (sec.preview || ["", "", ""]).slice(0, 3).forEach(function (line) {
        var p = document.createElement("p");
        p.textContent = line;
        lines.appendChild(p);
      });
      locked.appendChild(lines);

      var lock = document.createElement("div");
      lock.className = "lock";
      lock.textContent = "🔒";
      lock.setAttribute("aria-label", "Locked");
      locked.appendChild(lock);

      wrap.appendChild(locked);
      el.report.appendChild(wrap);
    });
  }

  function watchCta() {
    if (!window.IntersectionObserver) { track("paywall_view"); paywallTracked = true; return; }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting && !paywallTracked) {
          paywallTracked = true;
          track("paywall_view");
          io.disconnect();
        }
      });
    }, { threshold: 0.5 });
    io.observe(el.cta);
  }

  function startResult() {
    show("screen-result");
    el.analyzingText.textContent = cfg.analyzing.text;
    el.analyzing.hidden = false;
    el.resultBody.hidden = true;

    setTimeout(function () {
      var win = computeWinner();
      el.analyzing.hidden = true;
      el.resultBody.hidden = false;
      el.resultName.textContent = win.style.name;
      el.resultMatch.textContent = win.percent + "% match";
      el.resultBlurb.textContent = win.style.blurb || "";
      el.cta.textContent = cfg.pricing.cta;
      renderReport();
      track("result_view");
      watchCta();
    }, cfg.analyzing.duration_ms);
  }

  // --- paywall -------------------------------------------------------------

  function formatPrice() {
    var cents = cfg.pricing.amount_cents;
    var cur = (cfg.pricing.currency || "usd").toUpperCase();
    return (cents / 100).toFixed(2) + " " + cur;
  }

  function updatePayButton() {
    var ok = el.withdrawalCheck.checked && PAYMENTS_ENABLED;
    el.payButton.disabled = !ok;
    el.payButton.textContent = PAYMENTS_ENABLED
      ? "Pay " + formatPrice()
      : "Payments coming in Phase 1b";
  }

  function renderPaywall() {
    el.benefits.innerHTML = "";
    (cfg.checkout.benefits || []).forEach(function (b) {
      var li = document.createElement("li");
      li.textContent = b;
      el.benefits.appendChild(li);
    });
    el.price.textContent = formatPrice();
    el.withdrawalText.textContent = cfg.checkout.eu_withdrawal_text || "";
    el.withdrawalCheck.checked = false;
    updatePayButton();
  }

  // --- boot ----------------------------------------------------------------

  function cache() {
    el.cards = $("cards");
    el.progressBar = $("progress-bar");
    el.progressLabel = $("progress-label");
    el.headline = $("swipe-headline");
    el.analyzing = $("analyzing");
    el.analyzingText = $("analyzing-text");
    el.resultBody = $("result-body");
    el.resultName = $("result-name");
    el.resultMatch = $("result-match");
    el.resultBlurb = $("result-blurb");
    el.report = $("report");
    el.cta = $("cta");
    el.benefits = $("benefits");
    el.price = $("price");
    el.withdrawalCheck = $("withdrawal-check");
    el.withdrawalText = $("withdrawal-text");
    el.payButton = $("pay-button");
    el.paywallBack = $("paywall-back");
  }

  function wire() {
    el.cta.addEventListener("click", function () {
      track("pay_tap");
      renderPaywall();
      show("screen-paywall");
    });
    el.withdrawalCheck.addEventListener("change", updatePayButton);
    el.paywallBack.addEventListener("click", function () { show("screen-result"); });
  }

  function start() {
    byId = {};
    cfg.swipe.gallery.forEach(function (g) { byId[g.id] = g; });

    document.title = (cfg.meta && cfg.meta.title) || document.title;
    el.headline.textContent = cfg.swipe.headline;

    var first = (cfg.swipe.pairing && cfg.swipe.pairing.first_pair) || [];
    var a = byId[first[0]];
    var b = byId[first[1]];
    if (!a || !b || a === b) {
      var pool = cfg.swipe.gallery.slice();
      a = pool[0];
      b = pool[1];
    }
    pair = [a, b];
    renderPair();
    track("funnel_start");
  }

  function boot() {
    cache();
    sessionId = getSessionId();
    attribution = readAttribution();

    if (!/^[a-z0-9_-]{1,32}$/.test(slug)) return;

    fetch("/static/funnels/" + slug + ".json", { cache: "no-cache" })
      .then(function (r) { if (!r.ok) throw new Error("config"); return r.json(); })
      .then(function (data) { cfg = data; wire(); start(); })
      .catch(function () {
        el.headline.textContent = "This quiz is unavailable right now.";
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
