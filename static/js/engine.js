/* Mazzin swipe engine — vanilla, no deps, one IIFE.
 * Boot -> swipe pairs -> analyzing -> result + locked report -> Stripe.
 * Returning from Stripe with ?cs=<checkout_session> skips the quiz and
 * renders the unlocked report once the webhook has landed. */
(function () {
  "use strict";

  var PAYMENTS_ENABLED = true;
  var SLIDE_MS = 160;
  var REPORT_POLL_MS = 2000;
  var REPORT_MAX_TRIES = 30;

  var cfg = null;
  var slug = location.pathname.split("/")[1] || "";
  var sessionId = null;
  var attribution = {};

  var scores = {};          // tag -> count
  var seen = {};            // image id -> true (shown, never reshown)
  var pair = [];            // current [imgA, imgB]
  var step = 0;             // pairs completed
  var byId = {};
  var winnerStyleId = null; // set when the result is computed
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

  function readAttribution(params) {
    var out = {};
    ["subid", "utm_source", "utm_campaign", "utm_content", "utm_term"].forEach(function (k) {
      var v = params.get(k);
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
    // The winner's raw share of the summed style scores never reaches the
    // bottom of the clamp — tags are shared between styles, so a four-style
    // funnel floors that share near 1/4. Normalize against that floor first,
    // then scale into 55..95.
    var best = cfg.styles[0];
    var bestScore = -1;
    var total = 0;

    cfg.styles.forEach(function (s) {
      var sc = 0;
      s.tags.forEach(function (t) { sc += scores[t] || 0; });
      total += sc;
      if (sc > bestScore) { bestScore = sc; best = s; }
    });

    var floor = 1 / cfg.styles.length;
    var pct = 55;
    if (total > 0 && floor < 1) {
      pct = Math.round(55 + 40 * ((bestScore / total) - floor) / (1 - floor));
    }
    pct = Math.max(55, Math.min(95, pct));
    return { style: best, percent: pct };
  }

  function styleById(id) {
    for (var i = 0; cfg && i < cfg.styles.length; i++) {
      if (cfg.styles[i].id === id) return cfg.styles[i];
    }
    return null;
  }

  function sectionNode(title) {
    var wrap = document.createElement("div");
    wrap.className = "section";
    var h = document.createElement("h2");
    h.className = "section-title";
    h.textContent = title;
    wrap.appendChild(h);
    return wrap;
  }

  function renderLockedReport() {
    var sections = (cfg.report && cfg.report.sections) || [];
    el.report.innerHTML = "";
    sections.forEach(function (sec) {
      if (sec.enabled === false) return;

      var wrap = sectionNode(sec.title);

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

  function renderUnlockedReport(content) {
    el.report.innerHTML = "";
    (content.sections || []).forEach(function (sec) {
      var wrap = sectionNode(sec.title);
      var p = document.createElement("p");
      p.className = "section-body";
      p.textContent = sec.body || "";
      wrap.appendChild(p);
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
      winnerStyleId = win.style.id;
      el.analyzing.hidden = true;
      el.resultBody.hidden = false;
      el.resultName.textContent = win.style.name;
      el.resultMatch.textContent = win.percent + "% match";
      el.resultMatch.hidden = false;
      el.resultBlurb.textContent = win.style.blurb || "";
      el.cta.textContent = cfg.pricing.cta;
      renderLockedReport();
      track("result_view");
      watchCta();
    }, cfg.analyzing.duration_ms);
  }

  // --- unlocked (post-Stripe) view ----------------------------------------

  function showReportMessage(text) {
    el.analyzing.hidden = false;
    el.analyzingText.textContent = text;
    el.analyzingDots.hidden = true;
  }

  function renderUnlocked(content) {
    el.analyzing.hidden = true;
    el.resultBody.hidden = false;
    el.cta.hidden = true;

    var style = styleById(content.style_id);
    el.resultName.textContent = content.style_name || (style && style.name) || "";
    el.resultMatch.hidden = true;   // the match percent is not part of the purchase record
    el.resultBlurb.textContent = (style && style.blurb) || "";
    renderUnlockedReport(content);
  }

  function pollReport(cs, tries) {
    function retry() {
      if (tries + 1 >= REPORT_MAX_TRIES) {
        showReportMessage("Your report is being prepared — check back in a minute.");
        return;
      }
      setTimeout(function () { pollReport(cs, tries + 1); }, REPORT_POLL_MS);
    }

    fetch("/api/report?cs=" + encodeURIComponent(cs), { cache: "no-store" })
      .then(function (r) { return r.status === 200 ? r.json() : null; })
      .then(function (data) {
        if (data && data.status === "ready" && data.report) {
          renderUnlocked(data.report);
          return;
        }
        retry();
      })
      .catch(retry);
  }

  function startUnlocked(cs) {
    show("screen-result");
    el.resultBody.hidden = true;
    el.cta.hidden = true;
    el.analyzing.hidden = false;
    el.analyzingDots.hidden = false;
    el.analyzingText.textContent = "Preparing your report...";
    pollReport(cs, 0);
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

  function startCheckout() {
    if (!PAYMENTS_ENABLED || !el.withdrawalCheck.checked) return;

    el.payError.hidden = true;
    el.payButton.disabled = true;
    el.payButton.textContent = "Redirecting...";

    fetch("/api/checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        funnel: slug,
        session_id: sessionId,
        result_style: winnerStyleId
      })
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (data && data.url) {
          location.href = data.url;
          return;
        }
        throw new Error("no url");
      })
      .catch(function () {
        el.payError.textContent = "Could not start checkout. Please try again.";
        el.payError.hidden = false;
        updatePayButton();
      });
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
    el.payError.hidden = true;
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
    el.analyzingDots = $("analyzing-dots");
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
    el.payError = $("pay-error");
    el.paywallBack = $("paywall-back");
  }

  function wire() {
    el.cta.addEventListener("click", function () {
      track("pay_tap");
      renderPaywall();
      show("screen-paywall");
    });
    el.withdrawalCheck.addEventListener("change", updatePayButton);
    el.payButton.addEventListener("click", startCheckout);
    el.paywallBack.addEventListener("click", function () { show("screen-result"); });
  }

  function startQuiz() {
    byId = {};
    cfg.swipe.gallery.forEach(function (g) { byId[g.id] = g; });

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
    show("screen-swipe");
    renderPair();
    track("funnel_start");
  }

  function boot() {
    cache();
    sessionId = getSessionId();

    var params = new URLSearchParams(location.search);
    attribution = readAttribution(params);

    // After the Stripe redirect sessionStorage may be empty (new tab on some
    // devices), so the cs param alone has to be enough to render the report.
    var cs = params.get("cs");
    var unlocked = !!(cs && /^cs_[A-Za-z0-9_]{1,250}$/.test(cs));

    if (unlocked) startUnlocked(cs);

    if (!/^[a-z0-9_-]{1,32}$/.test(slug)) return;

    fetch("/static/funnels/" + slug + ".json", { cache: "no-cache" })
      .then(function (r) { if (!r.ok) throw new Error("config"); return r.json(); })
      .then(function (data) {
        cfg = data;
        document.title = (cfg.meta && cfg.meta.title) || document.title;
        wire();
        if (!unlocked) startQuiz();
      })
      .catch(function () {
        if (!unlocked) el.headline.textContent = "This quiz is unavailable right now.";
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
