/* Mazzin swipe engine — vanilla, no deps, one IIFE.
 * Boot -> swipe pairs -> analyzing -> result + locked report -> Stripe.
 * Returning from Stripe with ?cs=<checkout_session> skips the quiz and
 * renders the unlocked report once the webhook has landed. */
(function () {
  "use strict";

  var PAYMENTS_ENABLED = true;
  var SLIDE_OUT_MS = 160;       // outgoing pair
  var CARD_STAGGER_MS = 40;     // left card leads
  var REPORT_POLL_MS = 1200;
  var PRELOAD_TIMEOUT_MS = 800;
  var HOLD_MS = 1650;           // ring -> badge -> reaction, then the pair goes
  var HOLD_REDUCED_MS = 500;    // same beats, no animation, for reduced motion
  var REACTION_DELAY_MS = 200;  // lands just after the check badge
  // The blur curve is anchored to the trigger phrase's own line boxes: one
  // line of softening leads into it, the trigger itself lands in the
  // barely-readable band, and one line later nothing is legible. The opacity
  // each stop carries lives in the CSS gradient; these are only the offsets.
  //
  // Stops sit on line CENTRES, not line boundaries. A stop on a boundary is
  // the average of the two lines it divides, so every line ends up reading
  // half the value it was meant to.
  var HALF = 0.5;
  var CONFETTI_COUNT = 24;
  var CONFETTI_LIFE_MS = 2200;  // longest particle plus its delay, then cleared
  // 100 tries at 1200ms is two minutes of polling, which has to outlast the
  // server's whole window — the per-call budget plus the late-upgrade grace —
  // or the last sections would never arrive without a reload.
  var REPORT_MAX_TRIES = 100;
  var CS_RE = /^cs_[A-Za-z0-9_]{1,250}$/;   // Stripe checkout session id
  var REVEAL_THRESHOLD = 0.15;  // how much of a section must be in view to play
  var STATUS_MS = 2500;         // how long each loading line holds
  var STATUS_LINES = [
    "Confirming your payment\u2026",
    "Reading your choices\u2026",
    "Writing your color palette\u2026"
  ];

  var cfg = null;
  var slug = location.pathname.split("/")[1] || "";
  var sessionId = null;
  var attribution = {};

  var scores = {};          // tag -> count
  var seen = {};            // image id -> true (shown, never reshown)
  var pair = [];            // current [imgA, imgB]
  var step = 0;             // pairs completed
  var byId = {};
  var pending = {};          // tapped image id -> the pair that follows it
  var preloaded = {};        // img src -> already requested
  var winnerStyleId = null; // set when the result is computed
  var picking = false;      // true through the selection hold; taps ignored
  var confettiDone = false; // the burst fires once per session, never again
  var unlockedContent = null;   // report shown after returning from Stripe
  var unlockedStarted = false;  // the loading state is shown once, as early as possible
  var unlockedShown = false;    // the report has replaced the loading state
  var rendered = {};            // section id -> its node, so polls only append
  var sectionIO = null;         // one observer, outliving any single render
  var statusTimer = null;
  var lastReaction = null;  // never show the same line twice running
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

  function rankTags(map) {
    return Object.keys(map).sort(function (a, b) {
      return map[b] - map[a] || (a < b ? -1 : 1);
    });
  }

  // Scores as they would stand if `item` were the next tap.
  function scoresWith(item) {
    var m = {}, k;
    for (k in scores) m[k] = scores[k];
    item.tags.forEach(function (t) { m[t] = (m[t] || 0) + 1; });
    return m;
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

  function nextPairFrom(map) {
    var pool = unseen();
    if (pool.length < 2) return null;

    var ranked = rankTags(map);
    var a = pickByTag(pool, ranked[0]) || pickRandom(pool);
    var rest = pool.filter(function (g) { return g.id !== a.id; });
    var b = pickByTag(rest, ranked[1]) || pickRandom(rest);
    return [a, b];
  }

  // --- preloading ----------------------------------------------------------

  function preload(src) {
    if (!src || preloaded[src]) return;
    preloaded[src] = true;
    var img = new Image();
    img.src = src;
  }

  // Wait for both images, or PRELOAD_TIMEOUT_MS, whichever comes first — a
  // slow image must never hold the quiz hostage.
  function preloadPair(items, done) {
    var remaining = items.length;
    var fired = false;
    function finish() {
      if (fired) return;
      fired = true;
      clearTimeout(timer);
      done();
    }
    var timer = setTimeout(finish, PRELOAD_TIMEOUT_MS);
    items.forEach(function (item) {
      preloaded[item.img] = true;
      var img = new Image();
      img.onload = img.onerror = function () {
        remaining -= 1;
        if (remaining <= 0) finish();
      };
      img.src = item.img;
    });
  }

  // The pair that follows depends on which card is tapped, so resolve both
  // branches now and warm their images while the current pair is on screen.
  // Whichever the user picks, its images are already in cache.
  function prepareNext() {
    pending = {};
    if (step + 1 >= cfg.swipe.pairs_count) return;
    pair.forEach(function (item) {
      var next = nextPairFrom(scoresWith(item));
      pending[item.id] = next;
      if (next) next.forEach(function (g) { preload(g.img); });
    });
  }

  // --- swipe screen --------------------------------------------------------

  function cardNode(item, index) {
    var card = document.createElement("button");
    card.type = "button";
    card.className = "card";
    card.style.setProperty("--i", index);
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

    var check = document.createElement("span");
    check.className = "check";
    check.setAttribute("aria-hidden", "true");
    check.textContent = "\u2713";
    card.appendChild(check);

    card.addEventListener("click", function () { choose(item, card); });
    return card;
  }

  // Captions are keyed by image-id prefix (k1/k2/k3) — one per gallery layer.
  function captionFor(items) {
    var captions = (cfg.swipe && cfg.swipe.captions) || {};
    for (var i = 0; i < items.length; i++) {
      var key = String(items[i].id).slice(0, 2);
      if (captions[key]) return captions[key];
    }
    return "";
  }

  function renderPair() {
    el.cards.innerHTML = "";
    el.cards.classList.remove("is-picking", "is-leaving");
    pair.forEach(function (item, i) {
      seen[item.id] = true;
      el.cards.appendChild(cardNode(item, i));
    });
    setCaption(captionFor(pair));
    renderProgress();
    prepareNext();
  }

  // The caption only moves when it actually changes — a new layer of the
  // gallery — so the motion means something.
  function setCaption(text) {
    if (text === el.caption.textContent) return;
    el.caption.textContent = text;
    el.caption.classList.remove("is-enter");
    void el.caption.offsetWidth;        // restart the animation
    el.caption.classList.add("is-enter");
  }

  function renderProgress() {
    var total = cfg.swipe.pairs_count;
    var current = Math.min(step + 1, total);

    if (el.pips.childElementCount !== total) {
      el.pips.innerHTML = "";
      for (var i = 0; i < total; i++) {
        var pip = document.createElement("span");
        pip.className = "pip";
        el.pips.appendChild(pip);
      }
    }
    for (var j = 0; j < total; j++) {
      var node = el.pips.children[j];
      // Adding is-done re-triggers its pop animation, so only completed pips
      // that were not already done will pop.
      node.classList.toggle("is-done", j < step);
      node.classList.toggle("is-current", j === step);
    }

    el.progressLabel.textContent = current + " of " + total;
  }

  // The tag the chosen card has and the rejected one does not is what the tap
  // actually revealed — a shared tag would have been picked either way.
  function reactionFor(chosen, rejected) {
    var map = (cfg.swipe && cfg.swipe.reactions) || {};
    var rejectedTags = (rejected && rejected.tags) || [];
    var known = chosen.tags.filter(function (t) { return map[t]; });
    var differentiating = known.filter(function (t) {
      return rejectedTags.indexOf(t) === -1;
    });
    var pool = differentiating.length ? differentiating : known;
    if (!pool.length) return "";

    // Rotate by step so a repeated tag pairing does not always read the same.
    var texts = pool.map(function (t) { return map[t]; });
    var pick = texts[(step - 1) % texts.length];
    if (pick === lastReaction) {
      for (var i = 0; i < texts.length; i++) {
        if (texts[i] !== lastReaction) { pick = texts[i]; break; }
      }
    }
    lastReaction = pick;
    return pick;
  }

  function showReaction(text, card) {
    if (!text) return;
    var chip = document.createElement("div");
    chip.className = "reaction " +
      (el.cards.firstChild === card ? "is-left" : "is-right");
    chip.setAttribute("role", "status");

    // The pill is a separate box so its width is measured against one card,
    // independent of where the outer element sits in the row.
    var pill = document.createElement("div");
    pill.className = "reaction-pill";
    pill.appendChild(document.createTextNode(text));
    var tick = document.createElement("span");
    tick.className = "tick";
    tick.setAttribute("aria-hidden", "true");
    tick.textContent = "\u2713";
    pill.appendChild(tick);
    chip.appendChild(pill);
    el.cards.appendChild(chip);
    // next frame, so the entry animation actually runs
    requestAnimationFrame(function () { chip.classList.add("is-in"); });
  }

  function prefersReducedMotion() {
    return !!(window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  function choose(item, card) {
    if (picking || !pair.length) return;   // one tap per pair
    picking = true;
    var next = pending[item.id] || null;   // resolved and preloaded already
    var rejected = pair[0] === item ? pair[1] : pair[0];
    item.tags.forEach(function (t) { scores[t] = (scores[t] || 0) + 1; });
    step += 1;
    track("swipe", step);
    pair = [];

    // Show the choice landing, and hold it, before anything moves. Tracking
    // already fired above at tap time — the hold must not shift analytics.
    if (card) {
      card.classList.add("is-chosen");
      el.cards.classList.add("is-picking");
      var reaction = reactionFor(item, rejected);
      setTimeout(function () { showReaction(reaction, card); }, REACTION_DELAY_MS);
    }
    renderProgress();

    setTimeout(function () {
      el.cards.classList.add("is-leaving");
      setTimeout(function () {
        picking = false;
        if (step >= cfg.swipe.pairs_count) { startResult(); return; }
        if (!next) { startResult(); return; }
        pair = next;
        renderPair();
      }, SLIDE_OUT_MS + CARD_STAGGER_MS);
    }, prefersReducedMotion() ? HOLD_REDUCED_MS : HOLD_MS);
  }

  // --- result --------------------------------------------------------------

  function computeWinner() {
    var best = cfg.styles[0];
    var bestScore = -1;
    cfg.styles.forEach(function (s) {
      var sc = 0;
      s.tags.forEach(function (t) { sc += scores[t] || 0; });
      if (sc > bestScore) { bestScore = sc; best = s; }
    });
    return best;
  }

  function styleById(id) {
    for (var i = 0; cfg && i < cfg.styles.length; i++) {
      if (cfg.styles[i].id === id) return cfg.styles[i];
    }
    return null;
  }

  // Every report row is the same two-column shape: title on the left, whatever
  // the reveal ladder allows on the right.
  function rowNode(title, mode) {
    var row = document.createElement("div");
    row.className = "row";
    if (mode) row.setAttribute("data-mode", mode);

    var head = document.createElement("h2");
    head.className = "row-title";
    head.textContent = title;
    row.appendChild(head);

    var body = document.createElement("div");
    body.className = "row-body";
    row.appendChild(body);
    return row;
  }

  function para(text, className) {
    var p = document.createElement("p");
    if (className) p.className = className;
    p.textContent = text;
    return p;
  }

  // Filler for the blurred parts. Real copy never reaches these, so the
  // section's own preview lines stand in.
  function fillerLines(sec, count) {
    var lines = (sec.preview || []).slice(0, count);
    while (lines.length < count) lines.push(lines[0] || "");
    return lines;
  }

  function renderLockedReport(style) {
    var sections = (cfg.report && cfg.report.sections) || [];
    var reveals = (style && style.reveals) || {};
    el.report.innerHTML = "";

    sections.forEach(function (sec) {
      if (sec.enabled === false) return;
      var mode = (sec.reveal && sec.reveal.mode) || "locked";
      var reveal = reveals[sec.id];
      var row = rowNode(sec.title, mode);
      var body = row.lastChild;

      if (mode === "visible" && reveal && reveal.colors) {
        body.appendChild(swatchList(reveal.colors));
        body.appendChild(para(reveal.line || "", "palette-line"));
      } else {
        // One flowing paragraph: the setup reads clean, the trigger phrase
        // lands just inside the blur, and the rest is filler nobody can read.
        var setup = "", trigger = "";
        if (reveal && typeof reveal === "object") {
          setup = reveal.setup || "";
          trigger = reveal.trigger || "";
        } else if (typeof reveal === "string") {
          setup = reveal;
        }
        body.appendChild(dissolveNode(setup, trigger, runOn(fillerLines(sec, 2))));
      }

      row.addEventListener("click", focusCta);
      el.report.appendChild(row);
    });

    layoutDissolves();
    // A font swap changes the metrics the mask was measured against.
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(layoutDissolves);
    }
  }

  function swatchList(colors) {
    var list = document.createElement("ul");
    list.className = "swatches";
    colors.forEach(function (c) {
      var li = document.createElement("li");
      var dot = document.createElement("span");
      dot.className = "swatch";
      dot.style.backgroundColor = c.hex;
      li.appendChild(dot);
      li.appendChild(document.createTextNode(c.name));
      list.appendChild(li);
    });
    return list;
  }

  // Filler sentences read as filler the moment you see a capital letter start
  // a new one, even through a blur. Dropping the first one's capital lets the
  // whole block keep running on out of the trigger phrase.
  function runOn(lines) {
    var joined = lines.join(" ");
    if (/^[A-Z][a-z]/.test(joined)) {
      joined = joined.charAt(0).toLowerCase() + joined.slice(1);
    }
    return joined;
  }

  // Two identical text layers stacked pixel for pixel: a blurred one in flow
  // that sets the height, and a crisp one on top. Opposed gradient masks
  // cross-fade between them, so the same sentence appears to lose focus part
  // way down instead of stopping at a visible seam.
  //
  // Everything past the setup is filler on BOTH layers — the real section copy
  // is never in the document, so there is nothing to lift out of devtools or a
  // selection. The trigger is written to be the payoff the reader wants, and
  // it is placed where it is legible only if you work at it.
  function dissolveNode(setup, trigger, rest) {
    var wrap = document.createElement("div");
    wrap.className = "dissolve";
    wrap.appendChild(dissolveLayer("dissolve-blur", setup, trigger, rest, true));
    wrap.appendChild(dissolveLayer("dissolve-crisp", setup, trigger, rest, false));
    wrap.appendChild(lockNode());
    return wrap;
  }

  function dissolveLayer(cls, setup, trigger, rest, hidden) {
    var p = document.createElement("p");
    p.className = "dissolve-layer " + cls;
    if (hidden) p.setAttribute("aria-hidden", "true");
    appendPart(p, "setup", setup);
    appendPart(p, "trigger", trigger);
    appendPart(p, null, rest);
    return p;
  }

  // Parts are separated by a single space and empty ones contribute nothing,
  // so the two layers can never drift apart on whitespace alone.
  function appendPart(p, cls, text) {
    if (!text) return;
    if (p.firstChild) p.appendChild(document.createTextNode(" "));
    if (!cls) {
      p.appendChild(document.createTextNode(text));
      return;
    }
    var span = document.createElement("span");
    span.className = cls;
    span.textContent = text;
    p.appendChild(span);
  }

  // Where the curve sits, measured rather than guessed. Writing T for the line
  // the trigger phrase STARTS on, the four stops sit one line apart, centred
  // on T:
  //
  //   f0  centre of T-2   crisp
  //   f1  centre of T-1   ~40% gone  (the run-up line softens)
  //   f2  centre of T     ~75% gone  (barely readable — the hook)
  //   f3  centre of T+1   nothing left
  //
  // Anchoring to where the trigger starts rather than to the whole phrase is
  // what makes the reading identical across widths: a trigger that fits one
  // line on a 390 and wraps to two on a 360 still puts its opening at exactly
  // 75%, instead of the wrap quietly deciding how much of the payoff shows.
  function layoutDissolve(wrap) {
    var crisp = wrap.querySelector(".dissolve-crisp");
    if (!crisp) return;
    var lineH = parseFloat(getComputedStyle(crisp).lineHeight) || 21;
    var top = crisp.getBoundingClientRect().top;
    var trigger = spanTop(crisp.querySelector(".trigger"), top);

    // A section with no trigger phrase still has to dissolve somewhere: fall
    // back to starting at the line after the setup.
    if (trigger === null) {
      var setup = spanBottom(crisp.querySelector(".setup"), top);
      trigger = setup === null ? lineH : setup;
    }

    // Stops are left unclamped on purpose. When a reflow puts the trigger near
    // the top of the block the leading stops go negative, and a negative stop
    // is exactly right: the gradient starts partway along its ramp instead of
    // restarting at full crisp and steepening.
    var centre = trigger + lineH * HALF;
    for (var i = 0; i < 4; i++) {
      wrap.style.setProperty("--f" + i, Math.round(centre + (i - 2) * lineH) + "px");
    }
  }

  // Top of a span's first line box / bottom of its last, relative to the
  // paragraph. Null when the span is absent or has not been laid out.
  function spanTop(span, top) {
    var rects = span ? span.getClientRects() : [];
    return rects.length ? rects[0].top - top : null;
  }

  function spanBottom(span, top) {
    var rects = span ? span.getClientRects() : [];
    return rects.length ? rects[rects.length - 1].bottom - top : null;
  }

  function layoutDissolves() {
    if (!el.report) return;
    var all = el.report.querySelectorAll(".dissolve");
    for (var i = 0; i < all.length; i++) layoutDissolve(all[i]);
  }

  function lockNode() {
    var lock = document.createElement("span");
    lock.className = "row-lock";
    lock.setAttribute("role", "img");
    lock.setAttribute("aria-label", "Locked");
    return lock;
  }

  function focusCta() {
    if (!el.cta || el.cta.hidden) return;
    if (el.cta.scrollIntoView) {
      el.cta.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    el.cta.classList.remove("is-nudged");
    void el.cta.offsetWidth;
    el.cta.classList.add("is-nudged");
  }

  function elm(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  // Items inside a section stagger off their index; the section's own reveal
  // drives the delay, so nothing animates until it is actually on screen.
  function item(tag, cls, index) {
    var node = elm(tag, cls + " reveal-item");
    node.style.setProperty("--i", index);
    return node;
  }

  // --- typed section bodies (schema 2) -------------------------------------

  function paletteBody(d) {
    var frag = document.createDocumentFragment();
    frag.appendChild(elm("p", "section-intro", d.intro));

    var list = elm("ul", "swatch-list");
    (d.colors || []).forEach(function (c, i) {
      var li = item("li", "swatch-row", i);
      var dot = elm("span", "swatch-dot");
      // Validated to #rrggbb server-side before it was ever stored.
      dot.style.backgroundColor = c.hex;
      li.appendChild(dot);

      var text = elm("div", "swatch-text");
      var head = elm("p", "swatch-name", c.name);
      head.appendChild(elm("span", "swatch-hex", c.hex));
      text.appendChild(head);
      text.appendChild(elm("p", "swatch-role", c.role + " \u00B7 " + c.finish));
      text.appendChild(elm("p", "swatch-where", c.where));
      li.appendChild(text);
      list.appendChild(li);
    });
    frag.appendChild(list);
    frag.appendChild(elm("p", "callout", d.closing_rule));
    return frag;
  }

  function mistakesBody(d) {
    var list = elm("ol", "mistake-list");
    (d.items || []).forEach(function (m, i) {
      var li = item("li", "mistake", i);
      li.appendChild(elm("span", "mistake-num", String(i + 1)));
      var box = elm("div", "mistake-text");
      box.appendChild(elm("h3", "mistake-title", m.title));
      box.appendChild(elm("p", "mistake-body", m.body));
      box.appendChild(elm("p", "mistake-fix", "\u2192 Fix: " + m.fix));
      li.appendChild(box);
      list.appendChild(li);
    });
    return list;
  }

  function materialsBody(d) {
    var frag = document.createDocumentFragment();
    frag.appendChild(elm("p", "section-intro", d.intro));

    var list = elm("ul", "verdict-list");
    (d.pairs || []).forEach(function (p, i) {
      var li = item("li", "verdict", i);
      var head = elm("p", "verdict-head");
      head.appendChild(elm("span", "verdict-combo", p.combo));
      head.appendChild(elm("span", "badge badge-" + p.verdict, p.verdict));
      li.appendChild(head);
      li.appendChild(elm("p", "verdict-why", p.why));
      list.appendChild(li);
    });
    frag.appendChild(list);
    frag.appendChild(elm("p", "callout", d.rule));
    return frag;
  }

  function shoppingBody(d) {
    var frag = document.createDocumentFragment();
    var list = elm("ol", "buy-list");
    (d.items || []).forEach(function (buy, i) {
      var li = item("li", "buy", i);
      li.appendChild(elm("span", "buy-num", String(i + 1)));
      var box = elm("div", "buy-text");
      box.appendChild(elm("p", "buy-name", buy.name));
      box.appendChild(elm("p", "buy-note", buy.priority_note));
      li.appendChild(box);
      list.appendChild(li);
    });
    frag.appendChild(list);

    if ((d.skip || []).length) {
      var skip = elm("div", "skip-block");
      skip.appendChild(elm("p", "skip-label", "Skip"));
      d.skip.forEach(function (s) {
        var row = elm("p", "skip-row");
        row.appendChild(elm("span", "skip-name", s.name));
        row.appendChild(document.createTextNode(" " + s.why));
        skip.appendChild(row);
      });
      frag.appendChild(skip);
    }
    return frag;
  }

  function dnaBody(d) {
    var frag = document.createDocumentFragment();
    (d.narrative || []).forEach(function (para_) {
      frag.appendChild(elm("p", "section-body", para_));
    });
    var list = elm("ul", "implications");
    (d.implications || []).forEach(function (line, i) {
      var li = item("li", "implication", i);
      li.textContent = line;
      list.appendChild(li);
    });
    frag.appendChild(list);
    return frag;
  }

  function splurgeBody(d) {
    var frag = document.createDocumentFragment();
    var split = elm("div", "split");

    var up = item("div", "splurge-card", 0);
    up.appendChild(elm("p", "split-label", "Splurge"));
    up.appendChild(elm("p", "splurge-item", d.splurge.item));
    up.appendChild(elm("p", "splurge-why", d.splurge.why));
    split.appendChild(up);

    var down = item("div", "save-card", 1);
    down.appendChild(elm("p", "split-label", "Save"));
    var saves = elm("ul", "save-list");
    (d.saves || []).forEach(function (s) {
      var li = elm("li", "save");
      li.appendChild(elm("span", "save-item", s.item));
      li.appendChild(document.createTextNode(" " + s.why));
      saves.appendChild(li);
    });
    down.appendChild(saves);
    split.appendChild(down);

    frag.appendChild(split);
    frag.appendChild(elm("p", "split-note", d.split_note));
    return frag;
  }

  var SECTION_BODY = {
    palette: paletteBody,
    mistakes: mistakesBody,
    materials: materialsBody,
    shopping: shoppingBody,
    dna: dnaBody,
    splurge: splurgeBody
  };

  function isTyped(version) {
    return /(^|-)2(-partial)?$/.test(version || "");
  }

  function buildSection(sec, typed) {
    var block = elm("article", "section");
    block.appendChild(elm("h2", "section-title", sec.title || ""));

    var build = typed && SECTION_BODY[sec.id];
    if (build && sec.data) {
      try {
        block.appendChild(build(sec.data));
        return block;
      } catch (e) { /* fall through to prose */ }
    }
    block.appendChild(para(sec.body || "", "section-body"));
    return block;
  }

  // Paid view. The two-column table is a teaser device — a short title beside
  // a truncated reveal is what makes a locked row read as withheld. Once it is
  // bought it is a document, so each section gets a heading with its own rule
  // and a body shaped like its content: swatches, numbered cards, verdicts.
  //
  // Sections arrive across several polls, so this only ever appends what is
  // new. One that resolves late still lands in the right place: the payload is
  // always in report order, so a newcomer goes immediately before the first
  // already-rendered section that follows it.
  //
  // Schema 1 reports predate the typed data and still exist in the database,
  // so they fall through to the prose renderer they were written for.
  function renderUnlockedReport(content) {
    el.report.classList.add("report-unlocked");
    var typed = isTyped(content.version);
    var list = content.sections || [];

    list.forEach(function (sec, index) {
      if (!sec || !sec.id || rendered[sec.id]) return;

      var block = buildSection(sec, typed);
      rendered[sec.id] = block;

      var before = null;
      for (var j = index + 1; j < list.length; j++) {
        if (rendered[list[j].id]) { before = rendered[list[j].id]; break; }
      }
      if (before) el.report.insertBefore(block, before);
      else el.report.appendChild(block);

      observeSection(block);
    });

    markHero();
  }

  // The opening section carries the choreography, and which section that is
  // can change: a palette that resolves after another section still takes the
  // top, and the sequence belongs to whatever is first.
  function markHero() {
    var sections = el.report.children;
    for (var i = 0; i < sections.length; i++) {
      sections[i].classList.toggle("is-hero", i === 0);
    }
  }

  // --- reveals -------------------------------------------------------------

  // The title lands first, then each section as it comes into view. Sections
  // arrive over several polls, so the observer outlives any single render and
  // newcomers are handed to it as they are built.
  //
  // Only transform and opacity animate, and each section is unobserved the
  // moment it has played — once per section, not on every scroll.
  function instantReveal() {
    return !window.IntersectionObserver || prefersReducedMotion();
  }

  function revealHead() {
    var heads = [el.resultKicker, el.resultName, el.resultBlurb];
    heads.forEach(function (node, i) {
      if (!node) return;
      node.classList.add("reveal-head");
      node.style.setProperty("--i", i);
    });
    if (instantReveal()) {
      heads.forEach(function (n) { if (n) n.classList.add("is-revealed"); });
      return;
    }
    // Next frame, so the starting state is painted before the transition.
    requestAnimationFrame(function () {
      heads.forEach(function (n) { if (n) n.classList.add("is-revealed"); });
    });
  }

  function observeSection(block) {
    if (instantReveal()) {
      block.classList.add("is-revealed");
      return;
    }
    if (!sectionIO) sectionIO = makeObserver();
    sectionIO.observe(block);
  }

  function makeObserver() {
    function reveal(node) {
      if (node.classList.contains("is-revealed")) return;
      node.classList.add("is-revealed");
      io.unobserve(node);
    }

    var io = new IntersectionObserver(function (entries) {
      // A jump — a restored scroll position, an anchor, a hard flick — can
      // carry a section from below the fold to above it without ever
      // intersecting, and an unrevealed section is invisible. Anything now
      // scrolled past has to play too, or someone has paid for a blank gap.
      // Measure first, then write, so nothing is read back mid-mutation.
      var waiting = el.report.querySelectorAll(".section:not(.is-revealed)");
      var passed = [];
      for (var p = 0; p < waiting.length; p++) {
        if (waiting[p].getBoundingClientRect().bottom < 0) passed.push(waiting[p]);
      }
      entries.forEach(function (entry) {
        if (entry.isIntersecting) reveal(entry.target);
      });
      passed.forEach(reveal);
    }, { threshold: REVEAL_THRESHOLD });

    return io;
  }

  // --- free (pre-Stripe) result -------------------------------------------

  // One line of context immediately above the button, built here so the shell
  // markup stays a plain container.
  function renderCtaNote() {
    var sections = ((cfg.report && cfg.report.sections) || [])
      .filter(function (sec) { return sec.enabled !== false; });
    var note = el.ctaNote;
    if (!note) {
      note = document.createElement("p");
      note.className = "cta-note";
      note.id = "cta-note";
      el.cta.parentNode.insertBefore(note, el.cta);
      el.ctaNote = note;
    }
    note.textContent = "Unlock all " + numberWord(sections.length) + " sections \u00B7 " +
      formatPrice();
  }

  function numberWord(n) {
    var words = ["zero", "one", "two", "three", "four", "five", "six",
                 "seven", "eight", "nine", "ten"];
    return words[n] || String(n);
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
      winnerStyleId = win.id;
      el.analyzing.hidden = true;
      el.resultBody.hidden = false;
      el.resultName.textContent = win.name;
      el.resultBlurb.textContent = win.blurb || "";
      el.cta.textContent = cfg.pricing.cta;
      renderCtaNote();
      renderLockedReport(win);
      track("result_view");
      watchCta();
      celebrate();
    }, cfg.analyzing.duration_ms);
  }

  // A single small burst when the result lands. Purely decorative, never
  // repeated, and skipped outright when motion is unwelcome.
  function celebrate() {
    if (confettiDone || prefersReducedMotion()) return;
    confettiDone = true;

    var host = el.resultBody;
    if (!host) return;
    var field = document.createElement("div");
    field.className = "confetti";
    field.setAttribute("aria-hidden", "true");

    var colors = ["#C05621", "#FDF1E7", "#D4A853"];
    for (var i = 0; i < CONFETTI_COUNT; i++) {
      var bit = document.createElement("i");
      var size = 4 + Math.round(Math.random() * 2);          // 4-6px
      bit.style.left = (Math.random() * 100).toFixed(2) + "%";
      bit.style.width = size + "px";
      bit.style.height = size + "px";
      bit.style.backgroundColor = colors[i % colors.length];
      bit.style.setProperty("--drift", (Math.random() * 48 - 24).toFixed(1) + "px");
      bit.style.setProperty("--spin", Math.round(Math.random() * 360 - 180) + "deg");
      bit.style.animationDuration = (1.2 + Math.random() * 0.4).toFixed(2) + "s";
      bit.style.animationDelay = (Math.random() * 0.25).toFixed(2) + "s";
      field.appendChild(bit);
    }

    host.appendChild(field);
    setTimeout(function () {
      if (field.parentNode) field.parentNode.removeChild(field);
    }, CONFETTI_LIFE_MS);
  }

  // --- unlocked (post-Stripe) view ----------------------------------------

  function showReportMessage(text) {
    el.analyzing.hidden = false;
    el.analyzingText.textContent = text;
    el.analyzingDots.hidden = true;
    stopStatusRotation();
    if (el.analyzingStatus) el.analyzingStatus.hidden = true;
    // We gave up polling, so stop promising mail we cannot see the state of.
    if (el.analyzingNote) el.analyzingNote.hidden = true;
  }

  // Called on every poll that carries sections. The first one swaps the
  // loading state for the report; the rest only append what is new.
  function renderUnlocked(content) {
    unlockedContent = content;

    if (!unlockedShown) {
      unlockedShown = true;
      stopStatusRotation();
      el.analyzing.hidden = true;
      el.resultBody.hidden = false;
      el.cta.hidden = true;
      if (el.ctaNote) el.ctaNote.hidden = true;
      el.resultName.textContent = content.style_name || "";
      revealHead();
    }

    applyStyleCopy();
    renderUnlockedReport(content);
  }

  // The report can land before the funnel config does, and the blurb only
  // exists in the config — so fill it in whenever either side arrives.
  function applyStyleCopy() {
    if (!unlockedContent) return;
    var style = styleById(unlockedContent.style_id);
    if (!style) return;
    if (!el.resultName.textContent) el.resultName.textContent = style.name || "";
    el.resultBlurb.textContent = style.blurb || "";
  }

  // Second line of the loading state, built here so the shell markup stays a
  // plain container. It starts generic and gains the address once /api/report
  // tells us which inbox the PDF is going to.
  function setEmailNote(masked) {
    var note = el.analyzingNote;
    if (!note) {
      note = document.createElement("p");
      note.className = "analyzing-note";
      note.id = "analyzing-note";
      el.analyzing.insertBefore(note, el.analyzingDots);
      el.analyzingNote = note;
    }
    note.hidden = false;
    note.textContent = masked
      ? "We’re also emailing you a PDF copy to " + masked + "."
      : "We’re also emailing you a PDF copy.";
  }

  // A third line, under the dots. The headline above stays the fixed promise
  // and this carries the step, because the gap between the Stripe redirect and
  // the first section is long enough that a spinner alone reads as stuck.
  function setStatus(text) {
    var node = el.analyzingStatus;
    if (!node) {
      node = elm("p", "analyzing-status");
      node.id = "analyzing-status";
      el.analyzing.appendChild(node);
      el.analyzingStatus = node;
    }
    node.hidden = false;
    node.textContent = text;
  }

  function startStatusRotation() {
    if (statusTimer) return;
    var i = 0;
    setStatus(STATUS_LINES[0]);
    if (prefersReducedMotion()) return;      // no churn for anyone opted out
    statusTimer = setInterval(function () {
      i += 1;
      if (i >= STATUS_LINES.length) {        // hold on the last line
        stopStatusRotation();
        return;
      }
      setStatus(STATUS_LINES[i]);
    }, STATUS_MS);
  }

  function stopStatusRotation() {
    if (statusTimer) clearInterval(statusTimer);
    statusTimer = null;
  }

  function pollReport(cs, tries) {
    function retry() {
      if (tries + 1 >= REPORT_MAX_TRIES) {
        // Once sections are on screen the report is readable and giving up is
        // silent — replacing it with a "come back later" would be a downgrade.
        if (!unlockedShown) {
          showReportMessage("Your report is being prepared — check back in a minute.");
        }
        return;
      }
      setTimeout(function () { pollReport(cs, tries + 1); }, REPORT_POLL_MS);
    }

    fetch("/api/report?cs=" + encodeURIComponent(cs), { cache: "no-store" })
      // 202 carries the pending body, and the masked address with it.
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (data && data.email_masked) setEmailNote(data.email_masked);

        var report = data && data.report;
        var sections = (report && report.sections) || [];
        if (sections.length) renderUnlocked(report);

        // The row exists and is still filling up, or it exists and is done.
        if (data && data.complete && sections.length) return;
        retry();
      })
      .catch(retry);
  }

  function startUnlocked(cs) {
    if (unlockedStarted) return;
    unlockedStarted = true;
    show("screen-result");
    el.resultBody.hidden = true;
    el.cta.hidden = true;
    if (el.ctaNote) el.ctaNote.hidden = true;
    el.analyzing.hidden = false;
    el.analyzingDots.hidden = false;
    el.analyzingText.textContent = "Preparing your personalized report…";
    setEmailNote(null);
    startStatusRotation();
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
        result_style: winnerStyleId,
        // Raw tag counts, so the report can be written around what this person
        // actually kept choosing. The server re-validates every key.
        tag_scores: scores
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
    el.pips = $("pips");
    el.tapHint = $("tap-hint");
    el.progressLabel = $("progress-label");
    el.headline = $("swipe-headline");
    el.subtext = $("swipe-subtext");
    el.caption = $("swipe-caption");
    el.analyzing = $("analyzing");
    el.analyzingText = $("analyzing-text");
    el.analyzingDots = $("analyzing-dots");
    el.resultBody = $("result-body");
    // The kicker carries no id in the shell markup; it is only ever needed
    // here, to join the title block's reveal.
    el.resultKicker = document.querySelector(".result-kicker");
    el.resultName = $("result-name");
    // The match percent was retired in 2c.2; the shell markup still declares
    // the node, so take it out of the document rather than leave it hanging.
    var stale = $("result-match");
    if (stale && stale.parentNode) stale.parentNode.removeChild(stale);
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

    // Rewrapped text moves the seam; re-measure when the box changes.
    var resizeTimer = null;
    window.addEventListener("resize", function () {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(layoutDissolves, 120);
    });
  }

  function startQuiz() {
    byId = {};
    cfg.swipe.gallery.forEach(function (g) { byId[g.id] = g; });

    el.headline.textContent = cfg.swipe.headline;
    el.subtext.textContent = cfg.swipe.subtext || "";

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
    track("funnel_start");
    preloadPair(pair, renderPair);
  }

  function boot() {
    cache();
    sessionId = getSessionId();

    var params = new URLSearchParams(location.search);
    attribution = readAttribution(params);

    // After the Stripe redirect sessionStorage may be empty (new tab on some
    // devices), so the cs param alone has to be enough to render the report.
    var cs = params.get("cs");
    var unlocked = !!(cs && CS_RE.test(cs));

    if (unlocked) startUnlocked(cs);   // no-op when the early path got there first

    if (!/^[a-z0-9_-]{1,32}$/.test(slug)) return;

    fetch("/static/funnels/" + slug + ".json", { cache: "no-cache" })
      .then(function (r) { if (!r.ok) throw new Error("config"); return r.json(); })
      .then(function (data) {
        cfg = data;
        document.title = (cfg.meta && cfg.meta.title) || document.title;
        wire();
        if (unlocked) applyStyleCopy();
        else startQuiz();
      })
      .catch(function () {
        if (!unlocked) el.headline.textContent = "This quiz is unavailable right now.";
      });
  }

  // Someone coming back from Stripe has already paid; the first thing they see
  // must be their report loading, not a flash of the quiz they finished. This
  // runs at script execution — the shell above it is parsed, DOMContentLoaded
  // has not fired and the config fetch has not been issued. The copy renders in
  // the system fallback of the font stack, so it does not wait on the webfonts
  // either.
  try {
    var early = new URLSearchParams(location.search).get("cs");
    if (early && CS_RE.test(early)) {
      cache();
      startUnlocked(early);
    }
  } catch (e) {
    // Any surprise here is not worth losing the quiz over; boot() re-checks.
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
