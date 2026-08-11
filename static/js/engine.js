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
  var INTERSTITIAL_MS = 4000;   // a beat between steps, or a tap
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
  var GENERATING_MS = 3000;     // rotation of the in-report "still writing" card
  // The report can be rendered before the funnel config has loaded, so the
  // card needs copy of its own to open with. Config wins once it arrives.
  var GENERATING_FALLBACK = [
    "Comparing your choices against thousands of kitchens…",
    "Searching for the combinations that fit you…",
    "Almost there — writing your recommendations…"
  ];
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
  var chosen = [];          // image ids, in the order they were tapped
  var pair = [];            // current [imgA, imgB]
  var shownPairs = {};      // step index -> {id, images} drawn for this run
  var step = 0;             // pairs completed
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
  var analyzingTimer = null;    // free-result screen, between swipe and reveal
  var generatingTimer = null;   // the card under a report that is still filling
  var paywallTracked = false;
  var payMotionDone = false;    // the paywall's attention pull runs once
  var midOpen = false;          // an interstitial is on screen
  var midTimer = null;          // its auto-dismiss
  var midSeen = {};             // after_step -> already shown this run

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

  // --- Meta pixel ----------------------------------------------------------

  // Off unless the server hands back an id. The id is fetched rather than
  // written into the HTML because static/ is CDN-cached and shared by every
  // funnel — a pixel baked in here would follow the next brand onto its own
  // domain. With no id, nothing below runs and the page makes no request to
  // Meta at all.
  //
  // Purchase is deliberately absent. The browser is the wrong place for it:
  // a closed tab or a blocker loses it, and firing it here as well as on the
  // server double-counts the only number the ad spend is judged on.
  var pixelReady = false;
  var pixelQueue = [];

  function fbq() {
    return window.fbq;
  }

  function pixelTrack(name) {
    if (!pixelReady) { pixelQueue.push(name); return; }
    try {
      fbq()("track", name);
    } catch (e) { /* measurement must never break the funnel */ }
  }

  // Meta's own loader, verbatim in behaviour: define the stub queue, then
  // pull fbevents.js. Written out rather than pasted as a minified blob so
  // the next person can see what it does.
  function loadPixel(id) {
    if (window.fbq) return;
    var n = window.fbq = function () {
      n.callMethod ? n.callMethod.apply(n, arguments) : n.queue.push(arguments);
    };
    if (!window._fbq) window._fbq = n;
    n.push = n;
    n.loaded = true;
    n.version = "2.0";
    n.queue = [];
    var script = document.createElement("script");
    script.async = true;
    script.src = "https://connect.facebook.net/en_US/fbevents.js";
    document.head.appendChild(script);
    window.fbq("init", id);
  }

  function startPixel() {
    fetch("/api/pixel-config", { cache: "force-cache" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        var id = data && data.pixel_id;
        if (!id) return;
        loadPixel(String(id));
        pixelReady = true;
        pixelTrack("PageView");
        var queued = pixelQueue.slice();
        pixelQueue = [];
        queued.forEach(pixelTrack);
      })
      .catch(function () { /* no pixel, no funnel impact */ });
  }

  // What Meta needs to join this visit to the click that produced it. The
  // cookies are set by fbevents.js itself; fbclid is on the landing URL and
  // is the fallback for a first visit where the cookie does not exist yet.
  function cookie(name) {
    var hit = document.cookie.match(
      new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return hit ? decodeURIComponent(hit[1]) : "";
  }

  var META_ID_RE = /^[A-Za-z0-9._-]{1,255}$/;

  function metaIds() {
    var out = {};
    var fbp = cookie("_fbp");
    var fbc = cookie("_fbc");
    var fbclid = new URLSearchParams(location.search).get("fbclid") || "";
    if (META_ID_RE.test(fbp)) out.fbp = fbp;
    if (META_ID_RE.test(fbc)) out.fbc = fbc;
    if (META_ID_RE.test(fbclid)) out.fbclid = fbclid;
    return out;
  }

  // --- tracking ------------------------------------------------------------

  function track(event, stepNo, extra) {
    var body = { funnel: slug, session_id: sessionId, event: event };
    if (stepNo) body.step = stepNo;
    if (extra) body.extra = extra;
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

  // --- steps ---------------------------------------------------------------

  // The sequence is fixed and authored: each step is one question comparing a
  // single dimension, and both of its images are known up front. The previous
  // tag-following pairing chose the next pair from whatever the running scores
  // ranked highest, which put unrelated images against each other — a dark
  // render beside a bowl of fruit is not a choice about anything.
  function stepAt(index) {
    var steps = (cfg.swipe && cfg.swipe.steps) || [];
    return steps[index] || null;
  }

  // A step now owns several pairs asking the same question with different
  // photographs, and one of them is drawn per run. The step is still the unit
  // of meaning — what varies underneath it is which images made the argument,
  // which is the thing worth measuring.
  //
  // A step that still carries a bare `images` list is read as its own single
  // pair. engine.js and the funnel JSON are separate files behind a CDN, so
  // the two can be cached a version apart for a while after a deploy; the
  // fallback is what stops that window breaking the quiz.
  function pairsOf(st) {
    if (!st) return [];
    if (st.pairs && st.pairs.length) return st.pairs;
    if (st.images && st.images.length >= 2) {
      return [{ id: "p1", images: st.images }];
    }
    return [];
  }

  // A step shows two images side by side, four in a grid, or six in three
  // rows of two. All of them are one question and one tap; the format only
  // changes how many things are being compared at once.
  var GRID_SIZE = { grid4: 4, grid6: 6 };

  function stepFormat(st) {
    var f = st && st.format;
    return GRID_SIZE[f] ? f : "pair";
  }

  function stepSize(st) {
    return GRID_SIZE[stepFormat(st)] || 2;
  }

  // The two axes a step can adapt on. The config names the axis; what the
  // axis is made of lives here, because it is the same vocabulary the styles
  // are scored against and it should not be restatable per funnel.
  var TONE_AXIS = ["warm", "cool", "dark", "bright"];
  var TONE_OPPOSITE = {
    warm: "cool", cool: "warm", dark: "bright", bright: "dark"
  };
  var MATERIAL_AXIS = ["wood", "stone", "metal"];
  var AXES = { tone: TONE_AXIS, material: MATERIAL_AXIS };

  // The tag they have chosen most on one axis, or null when the axis has not
  // come up yet. Ties go to the first listed, so the same run always resolves
  // the same way.
  function leaderOf(axis) {
    var best = null;
    var bestScore = 0;
    (axis || []).forEach(function (tag) {
      var n = scores[tag] || 0;
      if (n > bestScore) { bestScore = n; best = tag; }
    });
    return best;
  }

  // Which pair an adaptive step wants, given what they have chosen so far.
  // Null means nothing matched and the draw falls back to random, which is
  // also what happens on a step with no rule at all.
  function adaptivePairId(st) {
    var rule = st && st.adaptive;
    if (!rule || !rule.variants) return null;
    var leader = leaderOf(AXES[rule.axis]);
    return (leader && rule.variants[leader]) || rule.variants["default"] || null;
  }

  function shuffled(list) {
    var out = list.slice();
    for (var i = out.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var swap = out[i]; out[i] = out[j]; out[j] = swap;
    }
    return out;
  }

  // One pair, order shuffled. Which image is on the left is not part of the
  // question, and leaving it fixed would let a habitual left-tapper score the
  // same way every run.
  function pickPair(index) {
    var st = stepAt(index);
    var pairs = pairsOf(st);
    if (!pairs.length) return null;

    var wanted = adaptivePairId(st);
    var pick = null;
    for (var i = 0; wanted && i < pairs.length; i++) {
      if (pairs[i].id === wanted) { pick = pairs[i]; break; }
    }
    if (!pick) pick = pairs[Math.floor(Math.random() * pairs.length)] || {};

    var size = stepSize(st);
    var images = (pick.images || []).slice(0, size);
    if (images.length < size) return null;
    return { id: pick.id || "p1", images: shuffled(images) };
  }

  // Drawn once per step and remembered. Preloading needs to know which images
  // are coming before the reader gets there, and the swipe event needs to name
  // the same pair afterwards — rolling the dice twice would warm one pair and
  // show another.
  function resolveStep(index) {
    if (!Object.prototype.hasOwnProperty.call(shownPairs, index)) {
      shownPairs[index] = pickPair(index);
    }
    return shownPairs[index];
  }

  function pairFor(index) {
    var picked = resolveStep(index);
    return picked ? picked.images : null;
  }

  function shownAt(index) {
    return Object.prototype.hasOwnProperty.call(shownPairs, index)
      ? shownPairs[index] : null;
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

  // The next step is the next step whatever the reader taps, so there is one
  // set of images to warm rather than a branch per card. Drawing the pair here
  // rather than at render time keeps that true now that a step has several:
  // two images are warmed, not every variant of the step.
  //
  // An adaptive step is the exception and has to stay one. Its answer depends
  // on the choice being made right now, so resolving it here would read the
  // scores one tap out of date and then remember the wrong pair. It warms
  // every variant instead and pays for that in bytes rather than in showing
  // the reader a pair the rule did not pick.
  function prepareNext() {
    var index = step + 1;
    var st = stepAt(index);
    if (!st) return;
    if (st.adaptive) {
      pairsOf(st).forEach(function (p) {
        (p.images || []).forEach(function (g) { preload(g.img); });
      });
      return;
    }
    var next = resolveStep(index);
    if (next) next.images.forEach(function (g) { preload(g.img); });
  }

  // --- swipe screen --------------------------------------------------------

  function cardNode(item, index) {
    var card = document.createElement("button");
    card.type = "button";
    card.className = "card";
    card.style.setProperty("--i", index);
    // The label is the only human name these images have — "Choose s1a" told
    // a screen reader nothing.
    card.setAttribute("aria-label", "Choose " + (item.label || item.id));

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

  function renderStep() {
    var st = stepAt(step);
    el.cards.innerHTML = "";
    el.cards.classList.remove("is-picking", "is-leaving");
    var fmt = stepFormat(st);
    el.cards.classList.toggle("is-grid4", fmt === "grid4");
    el.cards.classList.toggle("is-grid6", fmt === "grid6");
    pair.forEach(function (item, i) {
      el.cards.appendChild(cardNode(item, i));
    });
    setCaption((st && st.question) || "");
    renderProgress();
    prepareNext();
  }

  // The caption is the step's own question, so it changes on every pair.
  function setCaption(text) {
    if (text === el.caption.textContent) return;
    el.caption.textContent = text;
    el.caption.classList.remove("is-enter");
    void el.caption.offsetWidth;        // restart the animation
    el.caption.classList.add("is-enter");
  }

  function fillPips(host, total) {
    if (!host) return;
    if (host.childElementCount !== total) {
      host.innerHTML = "";
      for (var i = 0; i < total; i++) {
        var pip = document.createElement("span");
        pip.className = "pip";
        host.appendChild(pip);
      }
    }
    for (var j = 0; j < total; j++) {
      var node = host.children[j];
      // Adding is-done re-triggers its pop animation, so only completed pips
      // that were not already done will pop.
      node.classList.toggle("is-done", j < step);
      node.classList.toggle("is-current", j === step);
    }
  }

  // Two rows now — the swipe screen's and the interstitial's. An interstitial
  // sits between two steps rather than beside them, so the count carries
  // across it instead of disappearing and coming back.
  function renderProgress() {
    var total = cfg.swipe.pairs_count;
    var current = Math.min(step + 1, total);
    var label = current + " of " + total;

    fillPips(el.pips, total);
    fillPips(el.midPips, total);
    el.progressLabel.textContent = label;
    if (el.midProgressLabel) el.midProgressLabel.textContent = label;
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

  // Which pair was on screen and which side won. `shown` is in display order
  // rather than config order, because "the left one always wins" is a thing
  // worth being able to see in the readout. Nothing here is anyone's data —
  // it is which of our own photographs we put in front of them.
  function swipeExtra(index, item) {
    var st = stepAt(index);
    var picked = shownAt(index);
    if (!st || !picked || !st.id) return null;
    return {
      pair: st.id + ":" + picked.id,
      shown: picked.images.map(function (g) { return g.id; }),
      chosen: item.id
    };
  }

  function choose(item, card) {
    if (picking || !pair.length) return;   // one tap per pair
    picking = true;
    // Read before the counter moves: this describes the step just answered.
    var extra = swipeExtra(step, item);
    // A normal step asks what they want and scores the answer up. An inverse
    // step asks what they would never have, and the honest weight of "not
    // this" is smaller than the weight of "this" — a rejection narrows the
    // field, it does not choose. Half a point off, so a tag can end slightly
    // negative if the only thing anyone said about it was no.
    var weight = (stepAt(step) || {}).scoring === "inverse" ? -0.5 : 1;
    item.tags.forEach(function (t) { scores[t] = (scores[t] || 0) + weight; });
    chosen.push(item.id);
    step += 1;
    track("swipe", step, extra);
    pair = [];

    // Show the choice landing, and hold it, before anything moves. Tracking
    // already fired above at tap time — the hold must not shift analytics.
    if (card) {
      card.classList.add("is-chosen");
      el.cards.classList.add("is-picking");
      // The chip names what they just chose, in the words the step used for
      // it. A tag-derived reaction had to guess at meaning the label already
      // states.
      setTimeout(function () { showReaction(item.label || "", card); },
                 REACTION_DELAY_MS);
    }
    renderProgress();

    setTimeout(function () {
      el.cards.classList.add("is-leaving");
      setTimeout(function () {
        picking = false;
        var mid = interstitialAfter(step);
        if (mid) { openInterstitial(mid); return; }
        advance();
      }, SLIDE_OUT_MS + CARD_STAGGER_MS);
    }, prefersReducedMotion() ? HOLD_REDUCED_MS : HOLD_MS);
  }

  function advance() {
    var next = step >= cfg.swipe.pairs_count ? null : pairFor(step);
    if (!next) { startResult(); return; }
    pair = next;
    renderStep();
    show("screen-swipe");
  }

  // --- interstitials -------------------------------------------------------

  // A beat between steps that reads back what they have actually chosen. Every
  // number on it comes out of `scores`, which is the same object the result is
  // computed from — there is nothing here the run did not produce.

  function fillTokens(text) {
    if (!text) return "";
    var tone = leaderOf(TONE_AXIS);
    var material = leaderOf(MATERIAL_AXIS);
    var total = cfg.swipe.pairs_count || 1;
    return String(text)
      .replace(/\{leading_trait\}/g, tone || "")
      .replace(/\{opposite\}/g, (tone && TONE_OPPOSITE[tone]) || "")
      .replace(/\{leading_material\}/g, material || "")
      .replace(/\{n\}/g, String(tone ? (scores[tone] || 0) : 0))
      .replace(/\{total\}/g, String(step))
      .replace(/\{pct\}/g, String(Math.round(step / total * 100)));
  }

  // A template whose numbers cannot be derived yet is not shown at all. The
  // alternatives are a sentence with a hole in it or a figure we invented,
  // and this screen's entire claim is that it is reading what they chose.
  function canFill(entry) {
    var text = (entry.line || "") + " " + (entry.sub || "");
    if (/\{leading_trait\}|\{opposite\}/.test(text) && !leaderOf(TONE_AXIS)) {
      return false;
    }
    if (/\{leading_material\}/.test(text) && !leaderOf(MATERIAL_AXIS)) {
      return false;
    }
    return true;
  }

  function interstitialAfter(completed) {
    var list = (cfg && cfg.interstitials) || [];
    for (var i = 0; i < list.length; i++) {
      var entry = list[i];
      if (entry && entry.after_step === completed && !midSeen[completed]) {
        return canFill(entry) ? entry : null;
      }
    }
    return null;
  }

  function openInterstitial(entry) {
    midSeen[entry.after_step] = true;
    midOpen = true;
    el.midKicker.textContent = entry.kicker || "";
    el.midLine.textContent = fillTokens(entry.line || "");
    el.midSub.textContent = fillTokens(entry.sub || "");
    el.midSub.hidden = !entry.sub;
    el.midCta.textContent = entry.cta || "Continue analysis";
    renderProgress();
    show("screen-interstitial");
    track("interstitial", step);
    // Four seconds, or a tap — whichever comes first. A screen that only ever
    // waits is a screen somebody sits through.
    midTimer = setTimeout(closeInterstitial, INTERSTITIAL_MS);
  }

  function closeInterstitial() {
    if (!midOpen) return;               // the tap and the timer both land here
    midOpen = false;
    clearTimeout(midTimer);
    midTimer = null;
    advance();
  }

  // --- result --------------------------------------------------------------

  // The floor is -Infinity, not -1. With an inverse step in the sequence a
  // style's total can legitimately be negative, and a floor of -1 would have
  // quietly handed every one of those runs to whichever style happens to be
  // first in the config rather than to the one that scored highest.
  function computeWinner() {
    var best = cfg.styles[0];
    var bestScore = -Infinity;
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

  // The preview is the paid document with the copy taken out of it, not a
  // different object: same stacked sections, same titles and rules, same
  // swatch cards. What you are buying should be recognisable from what you
  // are looking at, so the only difference a reader can point to is that
  // most of the words are behind a blur.
  function renderLockedReport(style) {
    var sections = (cfg.report && cfg.report.sections) || [];
    var reveals = (style && style.reveals) || {};
    el.report.innerHTML = "";
    el.report.classList.add("report-preview");

    // Ranked once for the whole report, then dealt out two at a time: five
    // sections showing the same two frames reads as a bug, not as a teaser.
    var pool = styleShots(style);
    var taken = 0;

    sections.forEach(function (sec) {
      if (sec.enabled === false) return;
      var mode = (sec.reveal && sec.reveal.mode) || "locked";
      var reveal = reveals[sec.id];

      var block = elm("article", "section");
      block.setAttribute("data-mode", mode);
      block.appendChild(elm("h2", "section-title", sec.title || ""));

      if (mode === "visible" && reveal && reveal.colors) {
        block.appendChild(previewPalette(reveal));
      } else {
        block.appendChild(previewLocked(sec, reveal, pool, taken));
        taken += 2;
      }

      block.addEventListener("click", focusCta);
      el.report.appendChild(block);
    });

    layoutDissolves();
    // A font swap changes the metrics the mask was measured against.
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(layoutDissolves);
    }
  }

  // The one section delivered in full, and it is delivered in the paid shape:
  // real hex circles, the name and the code beside them. This is the sample,
  // so it has to be the actual product rather than a summary of it.
  function previewPalette(reveal) {
    var frag = document.createDocumentFragment();
    var list = elm("ul", "swatch-list");

    (reveal.colors || []).forEach(function (c) {
      var li = elm("li", "swatch-row");
      var dot = elm("span", "swatch-dot");
      dot.style.backgroundColor = c.hex;
      li.appendChild(dot);

      var text = elm("div", "swatch-text");
      var head = elm("p", "swatch-name", c.name);
      head.appendChild(elm("span", "swatch-hex", c.hex));
      text.appendChild(head);
      li.appendChild(text);
      list.appendChild(li);
    });

    frag.appendChild(list);
    if (reveal.line) frag.appendChild(elm("p", "callout", reveal.line));
    return frag;
  }

  // A blurred paragraph says the words are withheld. It says nothing about
  // whether there is anything to look at, and a report that is only prose is
  // a harder thing to want — so the strip under it carries the same withheld
  // treatment on images from the reader's own style.
  function previewLocked(sec, reveal, pool, from) {
    var body = elm("div", "locked-body");

    // One flowing paragraph: the setup reads clean, the trigger phrase lands
    // just inside the blur, and the rest is filler nobody can read.
    var setup = "", trigger = "";
    if (reveal && typeof reveal === "object") {
      setup = reveal.setup || "";
      trigger = reveal.trigger || "";
    } else if (typeof reveal === "string") {
      setup = reveal;
    }
    body.appendChild(dissolveNode(setup, trigger, runOn(fillerLines(sec, 2))));

    var strip = previewStrip(pool, from);
    if (strip) body.appendChild(strip);
    return body;
  }

  function previewStrip(pool, from) {
    if (!pool.length) return null;
    var shots = [pool[from % pool.length], pool[(from + 1) % pool.length]];

    var strip = elm("div", "preview-strip");
    strip.setAttribute("aria-hidden", "true");
    shots.forEach(function (item) {
      var frame = elm("span", "preview-thumb");
      var img = document.createElement("img");
      img.src = item.img;
      img.alt = "";
      img.loading = "lazy";
      img.draggable = false;
      frame.appendChild(img);
      strip.appendChild(frame);
    });
    strip.appendChild(lockNode());
    return strip;
  }

  // Gallery images sharing tags with the winning style, best match first, so
  // the strip under a Modern Rustic report is blurred wood rather than blurred
  // anything. Deterministic: the same style always deals the same order.
  function styleShots(style) {
    var tags = (style && style.tags) || [];
    var gallery = (cfg && cfg.preview_gallery) || [];
    if (!tags.length || !gallery.length) return [];

    return gallery
      .map(function (g, i) {
        var hits = (g.tags || []).filter(function (t) {
          return tags.indexOf(t) !== -1;
        }).length;
        return { item: g, hits: hits, i: i };
      })
      .filter(function (g) { return g.hits > 0; })
      .sort(function (a, b) { return b.hits - a.hits || a.i - b.i; })
      .map(function (g) { return g.item; });
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
    // The two share section classes, so the preview's must not survive into
    // the paid view — it would leave paid sections wired to the paywall.
    el.report.classList.remove("report-preview");
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
  // What the locked rows are worth, said once, between the sections and the
  // button. It sits here rather than on the paywall alone because this is the
  // screen where somebody decides whether to keep reading, and the number is
  // a market cost of getting a worktop or a cabinet colour wrong — not a
  // saving we have measured and cannot support.
  function renderValueBanner() {
    var copy = (cfg.result && cfg.result.value_banner) || "";
    if (!copy) return;
    var banner = el.valueBanner;
    if (!banner) {
      banner = document.createElement("p");
      banner.className = "value-banner";
      banner.id = "value-banner";
      el.cta.parentNode.insertBefore(banner, el.cta);
      el.valueBanner = banner;
    }
    banner.textContent = copy;
  }

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
    startAnalyzing();

    setTimeout(function () {
      var win = computeWinner();
      winnerStyleId = win.id;
      stopAnalyzing();
      el.analyzing.hidden = true;
      el.resultBody.hidden = false;
      el.resultName.textContent = win.name;
      el.resultBlurb.textContent = win.blurb || "";
      el.cta.textContent = cfg.pricing.cta;
      renderValueBanner();
      renderCtaNote();
      renderLockedReport(win);
      track("result_view");
      // A finished quiz with a result on screen is the qualified visitor Meta
      // should be optimising towards, so Lead sits exactly here and nowhere
      // earlier.
      pixelTrack("Lead");
      watchCta();
      celebrate();
    }, cfg.analyzing.duration_ms);
  }

  // The wait before the result is the one moment the reader has nothing to do,
  // and a row of dots says only "something is happening". Naming the steps —
  // their own choices, then the comparison, then the verdict — makes the same
  // wait read as work being done on their behalf. The messages divide the
  // configured duration between them, so the screen never cuts away mid-line.
  function startAnalyzing() {
    var lines = (cfg.analyzing && cfg.analyzing.messages) || [];
    var bar = el.analyzingBar;
    if (!bar) {
      bar = elm("div", "analyzing-bar");
      bar.setAttribute("aria-hidden", "true");
      bar.appendChild(elm("span", "analyzing-bar-fill"));
      el.analyzing.insertBefore(bar, el.analyzingDots);
      el.analyzingBar = bar;
    }
    bar.hidden = false;

    if (!lines.length) return;
    el.analyzingText.textContent = lines[0];
    if (lines.length < 2 || prefersReducedMotion()) return;

    var hold = Math.max(600, (cfg.analyzing.duration_ms || 2500) / lines.length);
    var i = 0;
    analyzingTimer = setInterval(function () {
      i += 1;
      if (i >= lines.length) { stopAnalyzing(); return; }
      el.analyzingText.textContent = lines[i];
    }, hold);
  }

  function stopAnalyzing() {
    if (analyzingTimer) clearInterval(analyzingTimer);
    analyzingTimer = null;
    if (el.analyzingBar) el.analyzingBar.hidden = true;
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
  function renderUnlocked(content, complete) {
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
    if (complete) stopGenerating();
    else startGenerating();
  }

  // Sections arrive one at a time, and a report that stops growing looks
  // finished. This sits under the last one that has landed and says, in as
  // many words, that more is still being written — then takes itself out of
  // the document the moment the report is whole.
  function startGenerating() {
    var card = el.generating;
    if (!card) {
      card = elm("div", "generating");
      card.id = "generating";
      card.setAttribute("aria-live", "polite");
      card.appendChild(elm("span", "generating-shimmer"));
      card.appendChild(elm("p", "generating-text", generatingLines()[0]));
      el.generating = card;
    }
    // Always re-append: sections are added above it, and the card belongs
    // under the last one.
    el.report.appendChild(card);

    if (generatingTimer || prefersReducedMotion()) return;
    var i = 0;
    generatingTimer = setInterval(function () {
      // Read the pool each tick: the report can arrive before the config does,
      // and the copy should improve the moment it lands.
      var lines = generatingLines();
      i = (i + 1) % lines.length;
      var text = card.querySelector(".generating-text");
      if (text) text.textContent = lines[i];
    }, GENERATING_MS);
  }

  function stopGenerating() {
    if (generatingTimer) clearInterval(generatingTimer);
    generatingTimer = null;
    if (el.generating && el.generating.parentNode) {
      el.generating.parentNode.removeChild(el.generating);
    }
    el.generating = null;
  }

  function generatingLines() {
    var lines = cfg && cfg.report && cfg.report.generating_messages;
    return (lines && lines.length) ? lines : GENERATING_FALLBACK;
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
        // The generating card does have to go: we have stopped looking, so it
        // would be promising work nobody is watching for.
        stopGenerating();
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
        var done = !!(data && data.complete && sections.length);
        if (sections.length) renderUnlocked(report, done);

        // The row exists and is still filling up, or it exists and is done.
        if (done) return;
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

  var SYMBOLS = { USD: "$", EUR: "€", GBP: "£" };

  // The same amount, short enough to sit inside a sentence. "3.00 USD" is
  // right on its own line and wrong in "This report costs ___", so copy that
  // names the price interpolates this instead of spelling a number out —
  // config never carries an amount, only the slot one goes in.
  function formatPriceShort() {
    var cents = cfg.pricing.amount_cents;
    var cur = (cfg.pricing.currency || "usd").toUpperCase();
    var amount = cents % 100 === 0 ? String(cents / 100)
                                   : (cents / 100).toFixed(2);
    return SYMBOLS[cur] ? SYMBOLS[cur] + amount : amount + " " + cur;
  }

  function withPrice(text) {
    return String(text || "").replace(/\{price\}/g, formatPriceShort());
  }

  function updatePayButton() {
    var ok = el.withdrawalCheck.checked && PAYMENTS_ENABLED;
    el.payButton.disabled = !ok;
    el.payButton.textContent = PAYMENTS_ENABLED
      ? withPrice(cfg.checkout.cta_label || cfg.pricing.cta || "Unlock")
      : "Payments coming in Phase 1b";
  }

  function startCheckout() {
    if (!PAYMENTS_ENABLED || !el.withdrawalCheck.checked) return;

    el.payError.hidden = true;
    el.payButton.disabled = true;
    el.payButton.textContent = "Redirecting...";

    var payload = {
      funnel: slug,
      session_id: sessionId,
      result_style: winnerStyleId,
      // Raw tag counts, so the report can be written around what this person
      // actually kept choosing. The server re-validates every key.
      tag_scores: scores,
      // The images themselves, in the order they were tapped. Tags say what
      // a choice meant; this says what they were looking at when they made
      // it, which is what the palette is built from. Re-validated server
      // side against the funnel's own step images.
      choices: chosen.slice()
    };

    // The click identifiers travel with the checkout because this is the last
    // moment the browser is involved. The purchase itself is reported by the
    // server after Stripe confirms it, long after this tab may be gone, and
    // without these it would arrive unattributed. The server re-validates
    // them and drops anything that is not a plain identifier.
    var ids = metaIds();
    for (var k in ids) payload[k] = ids[k];

    fetch("/api/checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
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

  var SVG_NS = "http://www.w3.org/2000/svg";

  // Icons are drawn rather than written: a glyph would arrive with whatever
  // the platform emoji font decided, at a colour and weight nobody chose.
  // These inherit currentColor and the accent, like everything else here.
  var ICONS = {
    check: "M4 10.5l4 4 8-9",
    lock: "M6 9V6.5a4 4 0 018 0V9M4.5 9h11v8h-11z",
    bolt: "M11 2L4.5 11.5H9.5L9 18l6.5-9.5H10.5z",
    mail: "M2.5 5h15v10h-15zM2.5 5.5l7.5 5.5 7.5-5.5"
  };

  function icon(name, cls) {
    var svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("class", cls);
    svg.setAttribute("viewBox", "0 0 20 20");
    svg.setAttribute("aria-hidden", "true");
    var path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", ICONS[name]);
    svg.appendChild(path);
    return svg;
  }

  // The three colours the result screen already showed them, repeated here at
  // dot size. The strip is a promise about the report, so it is drawn from the
  // same config the palette section is delivered from rather than from
  // decoration picked to look good — and a style with no palette shows
  // nothing instead of a row of empty circles.
  function renderProof(style) {
    var colors = (((style || {}).reveals || {}).palette || {}).colors || [];
    var line = cfg.checkout.proof_line || "";
    el.payDots.innerHTML = "";
    if (!colors.length || !line) {
      el.payProof.hidden = true;
      return;
    }
    colors.slice(0, 3).forEach(function (c) {
      var dot = elm("span", "pay-dot");
      dot.style.backgroundColor = c.hex;
      el.payDots.appendChild(dot);
    });
    el.payProofLine.textContent = line;
    el.payProof.hidden = false;
  }

  function renderManifest() {
    var rows = cfg.checkout.manifest || [];
    // `{n}` rather than a written-out six, for the same reason the price is a
    // slot: a number in copy that describes a list should come from the list.
    el.manifestHead.textContent =
      (cfg.checkout.manifest_head || "").replace("{n}", String(rows.length));
    el.manifestHead.hidden = !cfg.checkout.manifest_head;

    el.manifest.innerHTML = "";
    rows.forEach(function (row) {
      var li = elm("li", "manifest-row");
      li.appendChild(icon("check", "manifest-check"));
      li.appendChild(elm("span", "manifest-text", row));
      el.manifest.appendChild(li);
    });
  }

  var TRUST_ICONS = ["lock", "bolt", "mail"];

  function renderTrust() {
    el.trust.innerHTML = "";
    (cfg.checkout.trust || []).forEach(function (row, i) {
      var li = elm("li", "trust-row");
      li.appendChild(icon(TRUST_ICONS[i] || "check", "trust-icon"));
      li.appendChild(elm("span", null, row));
      el.trust.appendChild(li);
    });
  }

  // The three nodes 3e adds. funnel.html declares the containers this screen
  // has always had, and these go inside them — built once, on first render, so
  // a reader who goes back to the result and returns does not collect a second
  // set. Same construction as the manifest rows and the trust row above.
  function ensurePayNodes() {
    if (el.anchorHead) return;

    el.anchorHead = elm("span", "anchor-head");
    el.anchorLine = elm("span", "anchor-line");
    el.payAnchor.appendChild(el.anchorHead);
    el.payAnchor.appendChild(el.anchorLine);

    el.manifestHead = elm("p", "manifest-head");
    el.manifest.parentNode.insertBefore(el.manifestHead, el.manifest);

    el.reframe = elm("p", "pay-reframe");
    el.price.parentNode.insertBefore(el.reframe, el.price);
  }

  // A one-time scale-in when the anchor first comes into view, and two slow
  // shadow pulses under the button. Both are once per session and both are
  // off entirely under prefers-reduced-motion — the point is to catch an eye
  // that is already on the screen, not to keep moving.
  function playPayMotion() {
    if (prefersReducedMotion() || payMotionDone) return;
    payMotionDone = true;

    el.payButton.classList.add("is-breathing");

    if (!window.IntersectionObserver) {
      el.payAnchor.classList.add("is-flashed");
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        el.payAnchor.classList.add("is-flashed");
        io.disconnect();
      });
    }, { threshold: 0.5 });
    io.observe(el.payAnchor);
  }

  function renderPaywall() {
    var style = styleById(winnerStyleId);
    var name = (style && style.name) || "";
    ensurePayNodes();

    el.payKicker.textContent = cfg.checkout.kicker || "";
    // The winner is always computed before this screen can be reached, so the
    // name is always there — but "Your  Report" with a hole in it is the kind
    // of thing that only ever shows up in a screenshot from a real customer.
    el.paywallHeadline.textContent =
      (cfg.checkout.title || "Your {style} Report")
        .replace("{style}", name).replace(/\s{2,}/g, " ").trim();

    renderProof(style);
    renderManifest();

    el.anchorHead.textContent = withPrice(cfg.checkout.anchor_head || "");
    el.anchorHead.hidden = !cfg.checkout.anchor_head;
    el.anchorLine.textContent = withPrice(cfg.checkout.anchor || "");
    el.anchorLine.hidden = !cfg.checkout.anchor;
    el.payAnchor.hidden = !(cfg.checkout.anchor_head || cfg.checkout.anchor);

    el.reframe.textContent = withPrice(cfg.checkout.reframe || "");
    el.reframe.hidden = !cfg.checkout.reframe;

    var suffix = cfg.checkout.price_suffix;
    el.price.textContent = formatPrice() + (suffix ? " · " + suffix : "");
    renderTrust();

    el.withdrawalText.textContent = cfg.checkout.eu_withdrawal_text || "";
    // The short line is the whole of what the box says now; the full clause it
    // stands for is Terms section 6, which the footer links to from this
    // screen. The box itself is unchanged — tappable, uncheckable, and still
    // the only thing that enables the button.
    el.withdrawalCheck.checked = cfg.checkout.consent_prechecked === true;
    el.payError.hidden = true;
    updatePayButton();
    playPayMotion();
  }

  // --- boot ----------------------------------------------------------------

  function cache() {
    el.cards = $("cards");
    el.pips = $("pips");
    el.tapHint = $("tap-hint");
    el.midPips = $("mid-pips");
    el.midProgressLabel = $("mid-progress-label");
    el.midKicker = $("mid-kicker");
    el.midLine = $("mid-line");
    el.midSub = $("mid-sub");
    el.midCta = $("mid-cta");
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
    el.payKicker = $("pay-kicker");
    el.paywallHeadline = $("paywall-headline");
    el.payProof = $("pay-proof");
    el.payDots = $("pay-dots");
    el.payProofLine = $("pay-proof-line");
    el.manifest = $("manifest");
    el.payAnchor = $("pay-anchor");
    el.trust = $("trust");
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
      pixelTrack("InitiateCheckout");
      renderPaywall();
      show("screen-paywall");
    });
    el.withdrawalCheck.addEventListener("change", updatePayButton);
    el.payButton.addEventListener("click", startCheckout);
    el.paywallBack.addEventListener("click", function () { show("screen-result"); });
    el.midCta.addEventListener("click", closeInterstitial);

    // Rewrapped text moves the seam; re-measure when the box changes.
    var resizeTimer = null;
    window.addEventListener("resize", function () {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(layoutDissolves, 120);
    });
  }

  function startQuiz() {
    el.headline.textContent = cfg.swipe.headline;
    el.subtext.textContent = cfg.swipe.subtext || "";
    if (el.tapHint && cfg.swipe.hint) setHint(cfg.swipe.hint);

    var first = pairFor(0);
    if (!first) { startResult(); return; }
    pair = first;
    show("screen-swipe");
    track("funnel_start");
    preloadPair(pair, renderStep);
  }

  // The hint keeps its dot, which is markup rather than copy — replace only
  // the text node beside it.
  function setHint(text) {
    var node = el.tapHint;
    while (node.lastChild && node.lastChild.nodeType === 3) {
      node.removeChild(node.lastChild);
    }
    node.appendChild(document.createTextNode(text));
  }

  function boot() {
    cache();
    sessionId = getSessionId();

    var params = new URLSearchParams(location.search);
    attribution = readAttribution(params);
    startPixel();

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
