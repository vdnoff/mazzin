/* Mazzin swipe engine — vanilla, no deps, one IIFE.
 * Boot -> swipe pairs -> analyzing -> result + locked report -> Stripe.
 * Returning from Stripe with ?cs=<checkout_session> skips the quiz and
 * renders the unlocked report once the webhook has landed. */
(function () {
  "use strict";

  var PAYMENTS_ENABLED = true;
  var SLIDE_OUT_MS = 160;       // outgoing pair
  var CARD_STAGGER_MS = 40;     // left card leads
  var REPORT_POLL_MS = 2000;
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
  var pending = {};          // tapped image id -> the pair that follows it
  var preloaded = {};        // img src -> already requested
  var winnerStyleId = null; // set when the result is computed
  var picking = false;      // true through the selection hold; taps ignored
  var confettiDone = false; // the burst fires once per session, never again
  var unlockedContent = null;   // report shown after returning from Stripe
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

  function renderUnlockedReport(content) {
    el.report.innerHTML = "";
    (content.sections || []).forEach(function (sec) {
      var row = rowNode(sec.title, "visible");
      row.lastChild.appendChild(para(sec.body || "", "crisp section-body"));
      el.report.appendChild(row);
    });
  }

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
  }

  function renderUnlocked(content) {
    el.analyzing.hidden = true;
    el.resultBody.hidden = false;
    el.cta.hidden = true;
    if (el.ctaNote) el.ctaNote.hidden = true;

    unlockedContent = content;
    el.resultName.textContent = content.style_name || "";
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
    if (el.ctaNote) el.ctaNote.hidden = true;
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
    var unlocked = !!(cs && /^cs_[A-Za-z0-9_]{1,250}$/.test(cs));

    if (unlocked) startUnlocked(cs);

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

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
