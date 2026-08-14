/* Mazzin swipe engine — vanilla, no deps, one IIFE.
 * Boot -> swipe pairs -> analyzing -> result + locked report -> Stripe.
 * Returning from Stripe with ?cs=<checkout_session> skips the quiz and
 * renders the unlocked report once the webhook has landed. */
(function () {
  "use strict";

  var PAYMENTS_ENABLED = true;
  // One step change is three beats: the selection dims everything that was not
  // tapped, the whole set leaves to the left, and the next set arrives from the
  // right. Nothing overlaps, so the reader never sees two sets at once.
  //
  // Only the exit is timed here, because only the exit is something the engine
  // waits on: the 240ms enter runs in the stylesheet over cards that are
  // already in the document, and nothing is sequenced behind it.
  var EXIT_MS = 220;            // the set slides left and fades
  var EXIT_CHOSEN_MS = 40;      // ...with the card they chose leaving last
  var ENTER_STAGGER_MS = 50;    // per card, left to right
  var ENTER_STAGGER_CAP_MS = 150;  // a six-up would otherwise take 250ms to land
  var SWAP_REDUCED_MS = 200;    // reduced motion: the old instant swap, unchanged
  // The enter animation must not start over cards with nothing in them. These
  // bytes were warmed a step ago by prepareNext(), so this normally resolves on
  // the next microtask; the cap is for the case where the warm did not land, and
  // is small enough that the whole step change stays inside its latency budget.
  var DECODE_TIMEOUT_MS = 300;
  var REPORT_POLL_MS = 1200;
  var PRELOAD_TIMEOUT_MS = 800;
  var HOLD_MS = 1650;           // ring -> badge -> reaction, then the pair goes
  var HOLD_REDUCED_MS = 500;    // same beats, no animation, for reduced motion
  var REACTION_DELAY_MS = 200;  // lands just after the check badge
  var INTERSTITIAL_MS = 4000;   // a beat between steps, or a tap
  var WORKING_MS = 2000;        // the interstitial's micro-copy rotation
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
  var unlockedComplete = false; // whether that report is finished
  var configLost = false;       // the funnel config fetch failed for good
  var unlockedStarted = false;  // the loading state is shown once, as early as possible
  var unlockedShown = false;    // the report has replaced the loading state
  var rendered = {};            // section id -> its node, so polls only append
  var paidElements = false;     // the elements strip is placed once, paid side
  var sectionIO = null;         // one observer, outliving any single render
  var statusTimer = null;
  var analyzingTimer = null;    // free-result screen, between swipe and reveal
  var generatingTimer = null;   // the card under a report that is still filling
  var paywallTracked = false;
  var payMotionDone = false;    // the paywall's attention pull runs once
  var singlePage = false;       // the commerce block lives on the result page
  var commerceMoved = false;    // the paywall rows have been relocated once
  var stickyArmed = false;      // the mid-CTA has been tapped
  var stickyOn = false;         // the bar is currently showing
  var commerceInView = false;   // the block is on screen right now
  // Which deliberate act most recently preceded the commerce block coming into
  // view. Plain scrolling is the default because it is the answer when nobody
  // pressed anything.
  var payIntent = "scroll";
  var midOpen = false;          // an interstitial is on screen
  var midTimer = null;          // its auto-dismiss
  var midSeen = {};             // after_step -> already shown this run
  var workingTimer = null;      // the interstitial's rotating micro-copy

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
    // Decoded here, not at the swap. It is the same work either way, but a
    // whole step early it happens inside the selection hold where nothing else
    // is going on, and whenDecoded() below then resolves on the first tick
    // instead of holding a six-up grid for a sixth of a second. The promise
    // keeps `img` alive; a failure is the placeholder's problem, not ours.
    if (img.decode) img.decode().catch(function () {});
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

  // Decoded, not merely fetched. `preload` and `preloadPair` above stop at the
  // bytes being in the cache, which is enough when the cards fade up from grey
  // but not when they slide in — a card that decodes two frames into its own
  // entrance animates an empty rectangle and then pops. `img.decode()` is the
  // only hook that answers "this will paint on the next frame"; where it is
  // missing, `onload` is the closest thing and is what the old path used.
  //
  // The images are already warm, so this is a microtask in the normal case.
  // The timeout is the guarantee: a step change is never held longer than
  // DECODE_TIMEOUT_MS by an image, whatever the network is doing.
  function whenDecoded(items, done) {
    var remaining = items.length;
    var fired = false;
    function finish() {
      if (fired) return;
      fired = true;
      clearTimeout(timer);
      done();
    }
    function one() {
      remaining -= 1;
      if (remaining <= 0) finish();
    }
    if (!remaining) { finish(); return; }
    var timer = setTimeout(finish, DECODE_TIMEOUT_MS);
    items.forEach(function (item) {
      var img = new Image();
      preloaded[item.img] = true;
      img.src = item.img;
      // Failures resolve too: a broken image gets its placeholder from
      // cardNode, and holding the quiz for a 404 helps nobody.
      if (img.decode) { img.decode().then(one, one); return; }
      img.onload = img.onerror = one;
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

  // How far apart the cards land. Left to right at ENTER_STAGGER_MS each, but
  // the last card must still arrive promptly: six of them at 50ms would put the
  // bottom-right board a quarter of a second behind the top-left one, which
  // stops reading as one set arriving and starts reading as a list loading.
  // The whole set is inside ENTER_STAGGER_CAP_MS however many there are.
  function enterStagger(count) {
    if (count < 2) return ENTER_STAGGER_MS;
    return Math.min(ENTER_STAGGER_MS, ENTER_STAGGER_CAP_MS / (count - 1));
  }

  function renderStep() {
    var st = stepAt(step);
    el.cards.innerHTML = "";
    el.cards.classList.remove("is-picking", "is-leaving");
    var fmt = stepFormat(st);
    el.cards.classList.toggle("is-grid4", fmt === "grid4");
    el.cards.classList.toggle("is-grid6", fmt === "grid6");
    // Read by the per-card animation-delay. An engine.js that predates this
    // sets nothing and the CSS falls back to its own default, which is the
    // uncapped per-card figure — later, never broken.
    el.cards.style.setProperty("--stagger", enterStagger(pair.length) + "ms");
    pair.forEach(function (item, i) {
      el.cards.appendChild(cardNode(item, i));
    });
    setCaption((st && st.question) || "");
    renderProgress();
    prepareNext();
  }

  // The caption is the step's own question, so it changes on every pair.
  //
  // It fades out with the outgoing set and back in with the incoming one, so it
  // is restarted unconditionally — two steps that happen to ask the same
  // question still need the second half of that crossfade, and an early return
  // on matching text would leave the line faded out and never bring it back.
  function setCaption(text) {
    el.caption.textContent = text;
    el.caption.classList.remove("is-enter", "is-exit");
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

  // The label lands in the middle of the card that was tapped, over a wash
  // that dims the photograph under it.
  //
  // It used to straddle the card's top edge, anchored to the row and offset
  // left or right by half its width. That worked for a pair and for nothing
  // else: on a four-up it sat over the card above, and on a six-up over two of
  // them. Putting it inside the card removes the arithmetic \u2014 the chip is a
  // centred box in the only element it was ever about, at any grid size.
  function showReaction(text, card) {
    if (!text || !card) return;
    var chip = document.createElement("div");
    chip.className = "reaction";
    chip.setAttribute("role", "status");

    var pill = document.createElement("div");
    pill.className = "reaction-pill";
    pill.appendChild(document.createTextNode(text));
    var tick = document.createElement("span");
    tick.className = "tick";
    tick.setAttribute("aria-hidden", "true");
    tick.textContent = "\u2713";
    pill.appendChild(tick);
    chip.appendChild(pill);
    card.appendChild(chip);
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

    var reduced = prefersReducedMotion();
    setTimeout(function () {
      // The pip fills as the set leaves, not as the card is tapped. It used to
      // pop a second and a half before anything else moved, which read as a
      // fourth event in a step that only has three; on the exit it is the same
      // gesture as the cards, one row up.
      renderProgress();
      el.caption.classList.remove("is-enter");
      el.caption.classList.add("is-exit");
      el.cards.classList.add("is-leaving");
      setTimeout(function () {
        var mid = interstitialAfter(step);
        if (mid) { picking = false; openInterstitial(mid); return; }
        // `picking` stays set across the decode gate below: the outgoing cards
        // are still in the DOM and still buttons, and a tap landing on an
        // invisible one must not advance the quiz twice.
        advance();
      }, reduced ? SWAP_REDUCED_MS : EXIT_MS + EXIT_CHOSEN_MS);
    }, reduced ? HOLD_REDUCED_MS : HOLD_MS);
  }

  function advance() {
    var next = step >= cfg.swipe.pairs_count ? null : pairFor(step);
    if (!next) { picking = false; startResult(); return; }
    whenDecoded(next, function () {
      pair = next;
      renderStep();
      show("screen-swipe");
      picking = false;
    });
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
    startWorking();
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
    stopWorking();
    advance();
  }

  // A spinner and a line that changes under the read-back. The screen was
  // already claiming to be adjusting what comes next; this is the only part of
  // it that looks like something is happening while it says so. It is
  // decoration over a real pause — the dismiss timing above is untouched by
  // it, and it stops the moment the screen goes.
  function workingLines() {
    var lines = cfg && cfg.interstitial_working;
    return (lines && lines.length) ? lines : [];
  }

  function startWorking() {
    var lines = workingLines();
    var row = el.midWorking;
    if (!lines.length) {
      if (row) row.hidden = true;
      return;
    }
    if (!row) {
      row = elm("p", "mid-working");
      row.id = "mid-working";
      row.setAttribute("aria-live", "polite");
      var spin = elm("span", "mid-spinner");
      spin.setAttribute("aria-hidden", "true");
      row.appendChild(spin);
      row.appendChild(elm("span", "mid-working-text"));
      // Under the subline, inside the read-back block. Anchored to the button
      // it read as a state of the button — something you were waiting on
      // before you were allowed to continue — when what it is actually saying
      // is that the sentence above it is being acted on.
      el.midSub.parentNode.insertBefore(row, el.midSub.nextSibling);
      el.midWorking = row;
    }
    row.hidden = false;
    var text = row.querySelector(".mid-working-text");
    var i = 0;
    text.textContent = lines[0];
    if (workingTimer || prefersReducedMotion() || lines.length < 2) return;
    workingTimer = setInterval(function () {
      i = (i + 1) % lines.length;
      text.textContent = lines[i];
    }, WORKING_MS);
  }

  function stopWorking() {
    if (workingTimer) clearInterval(workingTimer);
    workingTimer = null;
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

  // Which locked sections have given up their own block to the compact card
  // at the bottom. A row naming a section that this config does not have is
  // ignored on both sides, so a stale funnel JSON can neither collapse a
  // section that is not there nor lose one that is.
  function collapsedIds() {
    var rows = ((cfg.report && cfg.report.also) || {}).rows || [];
    var ids = {};
    rows.forEach(function (row) {
      if (row && row.section) ids[row.section] = true;
    });
    return ids;
  }

  // The preview is the paid document with most of the copy taken out of it,
  // not a different object: same stacked sections, same titles and rules, same
  // swatch cards. What you are buying should be recognisable from what you are
  // looking at.
  //
  // What changed is where the line falls and how often it is drawn. The reader
  // now gets a whole page of the report for nothing — the palette, one entire
  // mistake — and the withheld part is two teasers and a list rather than five
  // identical blurs, because five of them in a row is not five arguments, it is
  // one argument made five times until it stops landing.
  function renderLockedReport(style) {
    var sections = (cfg.report && cfg.report.sections) || [];
    var reveals = (style && style.reveals) || {};
    el.report.innerHTML = "";
    el.report.classList.add("report-preview");

    // Ranked once for the whole report, then dealt out two at a time: two
    // sections showing the same two frames reads as a bug, not as a teaser.
    var pool = styleShots(style);
    var taken = 0;
    var elementsPlaced = false;
    var collapsed = collapsedIds();

    sections.forEach(function (sec) {
      if (sec.enabled === false) return;
      var mode = (sec.reveal && sec.reveal.mode) || "locked";
      var reveal = reveals[sec.id];

      // The elements block goes in at the line between what they have been
      // given and what is being sold: under the palette and the free mistake,
      // above the first section with its words held back.
      if (mode !== "visible" && !elementsPlaced) {
        elementsPlaced = true;
        addElements();
        if (singlePage) addOffer(style);
      }

      // Collapsed sections have a row in the card below instead of a block of
      // their own. Five blurred blocks in a row taught the reader to scroll
      // past blurred blocks, which is the opposite of what they are for.
      if (mode !== "visible" && collapsed[sec.id]) return;

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

      // Straight after the palette, before anything is asked for: one whole
      // mistake, numbered, in the shape the paid section uses.
      if (mode === "visible" && reveal && reveal.colors) {
        var free = mistakeOneSection(style);
        if (free) el.report.appendChild(free);
      }
    });

    // A report with nothing locked in it would never have hit the line above.
    if (!elementsPlaced) {
      addElements();
      if (singlePage) addOffer(style);
    }

    var also = alsoSection(sections);
    if (also) el.report.appendChild(also);

    layoutDissolves();
    // A font swap changes the metrics the mask was measured against.
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(layoutDissolves);
    }
  }

  // --- the free mistake ------------------------------------------------------

  // One of the five, whole, before anything is asked for — and it is the one
  // the locked section's teaser used to be written about, so the reader who
  // buys on "the other four" gets the other four rather than five strangers.
  //
  // Built out of the same classes the paid section uses, deliberately: the
  // strongest argument for what a report page looks like is a report page.
  function mistakeOneSection(style) {
    var one = ((style && style.reveals) || {}).mistake_one;
    var copy = (cfg.report && cfg.report.mistake_one) || {};
    if (!one || !one.title || !one.body || !one.fix) return null;

    var node = elm("article", "section section-mistake-one");
    node.setAttribute("data-mode", "visible");
    node.appendChild(elm("h2", "section-title", copy.title || "Mistake #1"));

    var list = elm("ol", "mistake-list");
    var li = elm("li", "mistake");
    li.appendChild(elm("span", "mistake-num", "1"));
    var box = elm("div", "mistake-text");
    box.appendChild(elm("h3", "mistake-title", one.title));
    box.appendChild(elm("p", "mistake-body", one.body));
    box.appendChild(elm("p", "mistake-fix", "→ Fix: " + one.fix));
    li.appendChild(box);
    list.appendChild(li);
    node.appendChild(list);

    if (copy.locked_note) {
      var foot = elm("p", "mistake-locked");
      foot.appendChild(padlockNode("is-sm"));
      foot.appendChild(elm("span", null, copy.locked_note));
      node.appendChild(foot);
      node.addEventListener("click", focusCta);
    }
    return node;
  }

  // --- what is left, in one card ---------------------------------------------

  // The four sections that no longer get a blurred block each. One row apiece:
  // a lock, the title the report will use, and a line about what the section
  // decides. It is shorter than any one of the blocks it replaces and it says
  // more, because four different sentences carry further than four identical
  // treatments.
  function alsoSection(sections) {
    var block = (cfg.report && cfg.report.also) || {};
    var rows = block.rows || [];
    if (!rows.length) return null;

    var titles = {};
    (sections || []).forEach(function (sec) {
      if (sec && sec.id && sec.enabled !== false) titles[sec.id] = sec.title;
    });

    var list = elm("ul", "also-list");
    rows.forEach(function (row) {
      if (!row) return;
      // A row naming a section takes that section's own title. A row with a
      // title of its own is something the report contains that is not a
      // section — the paint codes live inside the palette.
      var title = row.section ? titles[row.section] : row.title;
      if (!title) return;
      var li = elm("li", "also-row");
      li.appendChild(padlockNode("is-sm"));
      var text = elm("div", "also-text");
      text.appendChild(elm("p", "also-title", title));
      if (row.hook) text.appendChild(elm("p", "also-hook", row.hook));
      li.appendChild(text);
      list.appendChild(li);
    });
    if (!list.childElementCount) return null;

    var node = elm("article", "section section-also");
    node.setAttribute("data-mode", "locked");
    node.appendChild(elm("h2", "section-title",
                         block.title || "Also in your report"));
    node.appendChild(list);
    node.addEventListener("click", focusCta);
    return node;
  }

  // --- style elements (free) ------------------------------------------------

  // Six things the report will specify, named and pictured, given away before
  // anything is asked for. The palette above proves we read their colours; this
  // proves we read their fittings, which is the harder claim and the one the
  // locked sections are trading on.
  var ELEMENT_COUNT = 6;

  function elementItems() {
    var block = cfg && cfg.style_elements;
    return (block && block.items) || [];
  }

  // What one element is worth against the run so far. Same `scores` object the
  // result is computed from, so an element cannot rank on a tag nobody chose.
  function elementWeight(item) {
    var sum = 0;
    (item.tags || []).forEach(function (t) { sum += scores[t] || 0; });
    return sum;
  }

  // An image they actually tapped is the strongest claim available — they
  // pointed at it — so those fill the grid first, in config order. The rest go
  // to whichever elements carry most of what they kept choosing, with config
  // order breaking ties so one run always shows one set.
  //
  // The chosen pass alone cannot fill six: the mapped images live on five
  // steps and only one image per step is ever tapped.
  function pickElements() {
    var items = elementItems();
    if (!items.length) return [];

    var picked = [];
    var seen = {};
    items.forEach(function (item) {
      if (picked.length >= ELEMENT_COUNT) return;
      if (item.image && chosen.indexOf(item.image) !== -1) {
        seen[item.id] = true;
        picked.push(item);
      }
    });

    if (picked.length < ELEMENT_COUNT) {
      items
        .map(function (item, i) {
          return { item: item, weight: elementWeight(item), i: i };
        })
        .filter(function (row) { return !seen[row.item.id]; })
        .sort(function (a, b) { return b.weight - a.weight || a.i - b.i; })
        .slice(0, ELEMENT_COUNT - picked.length)
        .forEach(function (row) { picked.push(row.item); });
    }
    return picked;
  }

  // The paid view shows the six the free view showed, and the server is what
  // remembers which six: it stored them with the report. Somebody returning
  // from Stripe can land in a new tab with no `chosen` and no `scores` left to
  // recompute from, and six elements picked out of an empty run would be a
  // different set from the one they were promised.
  function elementsFor(ids) {
    if (!ids || !ids.length) return pickElements();
    var items = elementItems();
    var byId = {};
    items.forEach(function (item) { byId[item.id] = item; });
    var out = [];
    ids.forEach(function (id) {
      if (byId[id]) out.push(byId[id]);
    });
    return out.length ? out : pickElements();
  }

  function addElements() {
    var node = elementsSection();
    if (node) el.report.appendChild(node);
  }

  // Same article shell as every other section, so it inherits the rule under
  // the title and the spacing between blocks. The thumbnails are square
  // centre-crops rather than the tall quiz frames: at this size the crop is
  // the material, and the room around it is noise.
  //
  // `detail` is the paid view: the same strip, one to a row, each chip
  // carrying the specification the report was promising to give them. Before
  // the money it is a list of things we know about you; after it, it is the
  // beginning of the document.
  function elementsSection(detail, ids) {
    var block = cfg && cfg.style_elements;
    var items = detail ? elementsFor(ids) : pickElements();
    if (!block || !items.length) return null;

    var node = elm("article", "section section-elements");
    node.setAttribute("data-mode", "visible");
    node.appendChild(elm("h2", "section-title",
                         block.title || "Your Style Elements"));
    if (!detail && block.subline) {
      node.appendChild(elm("p", "elements-sub", block.subline));
    }

    var grid = elm("ul", "element-grid" + (detail ? " is-detailed" : ""));
    items.forEach(function (item) {
      var chip = elm("li", "element-chip");
      var frame = elm("span", "element-thumb");
      var img = document.createElement("img");
      img.src = item.img;
      img.alt = "";
      img.loading = "lazy";
      img.draggable = false;
      frame.appendChild(img);
      chip.appendChild(frame);
      if (detail) {
        var text = elm("span", "element-text");
        text.appendChild(elm("span", "element-label", item.label || ""));
        if (item.spec) text.appendChild(elm("span", "element-spec", item.spec));
        chip.appendChild(text);
      } else {
        chip.appendChild(elm("span", "element-label", item.label || ""));
      }
      grid.appendChild(chip);
    });
    node.appendChild(grid);

    // Only the preview is one big tap target for the button. In the paid view
    // there is no button, and a section that scrolled somewhere when touched
    // would be a document fighting the reader.
    if (!detail) node.addEventListener("click", focusCta);
    return node;
  }

  // The colour to paint a config swatch with. The config carries an rgb
  // triple rather than a hex string, so that nothing the free page is sent is
  // a paint code — see maskedCode below. `hex` is still read, because an
  // engine.js this new can be handed a funnel JSON cached from before the
  // change and a row of empty circles would be worse than an old code.
  function swatchColor(c) {
    var t = c && c.rgb;
    if (t && t.length === 3) return "rgb(" + t[0] + "," + t[1] + "," + t[2] + ")";
    return (c && c.hex) || "";
  }

  // What stands where the code goes. Not the real value under a blur — the
  // value is not in the document at all, and a placeholder of the right shape
  // says "there is a code here and you have not got it" more honestly than a
  // hex somebody can read out of devtools.
  function maskedCode() {
    var span = elm("span", "swatch-hex is-masked");
    span.setAttribute("aria-label", "Paint code locked");
    span.appendChild(elm("span", "code-mask", "#■■■■■"));
    span.appendChild(padlockNode("is-sm"));
    return span;
  }

  // The free palette: the three colours, drawn and named, with a one-line
  // reason. What it does not carry is the codes — that is the line the report
  // is being bought across, and it is drawn in the payload rather than in CSS
  // so that view-source is the same answer as the screen.
  function previewPalette(reveal) {
    var frag = document.createDocumentFragment();
    var list = elm("ul", "swatch-list is-gated");

    (reveal.colors || []).forEach(function (c) {
      var li = elm("li", "swatch-row");
      var dot = elm("span", "swatch-dot");
      dot.style.backgroundColor = swatchColor(c);
      li.appendChild(dot);

      var text = elm("div", "swatch-text");
      var head = elm("p", "swatch-name", c.name);
      head.appendChild(maskedCode());
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

    // One padlock over the whole withheld block — the prose and the pictures
    // together — rather than a small one tucked into the strip. There is one
    // thing being withheld here, so there is one marker for it, and at 48px it
    // is the element the eye lands on when the section comes into view instead
    // of something noticed on the way past.
    //
    // It does not take the tap: `pointer-events: none` lets it fall through to
    // the section, which has carried the listener all along.
    var mark = elm("span", "locked-lock");
    mark.setAttribute("aria-hidden", "true");
    mark.appendChild(padlockNode("is-lg"));
    body.appendChild(mark);
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

  // One padlock, drawn once, used at every size the report needs: 15px beside
  // a row in the "also" card and 48px over a locked section.
  //
  // It replaces a lock built out of a box and two pseudo-elements. That shape
  // survived at 28px over a photograph and fell apart everywhere else — at
  // text size the shackle was a hairline sitting above a filled rectangle,
  // which reads as a bullet that has come apart rather than as a lock. A
  // filled body with a stroked shackle holds together at both ends of the
  // range, which is the whole reason for having one drawing.
  function padlockNode(cls) {
    var svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("class", "padlock" + (cls ? " " + cls : ""));
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Locked");

    var shackle = document.createElementNS(SVG_NS, "path");
    shackle.setAttribute("class", "padlock-shackle");
    shackle.setAttribute("d", "M7.9 10.2V7.4a4.1 4.1 0 018.2 0v2.8");
    svg.appendChild(shackle);

    var body = document.createElementNS(SVG_NS, "rect");
    body.setAttribute("class", "padlock-body");
    body.setAttribute("x", "4.6");
    body.setAttribute("y", "10.2");
    body.setAttribute("width", "14.8");
    body.setAttribute("height", "10.4");
    body.setAttribute("rx", "2.6");
    svg.appendChild(body);

    // Only legible on the large one; the small variant hides it in CSS rather
    // than rendering a smudge in the middle of the body.
    var hole = document.createElementNS(SVG_NS, "circle");
    hole.setAttribute("class", "padlock-hole");
    hole.setAttribute("cx", "12");
    hole.setAttribute("cy", "15.4");
    hole.setAttribute("r", "1.6");
    svg.appendChild(hole);
    return svg;
  }

  function focusCta() {
    // Single-page has no button of its own to scroll to — the whole offer is
    // further down the same page, and that is what a tap on a locked row is
    // asking to see.
    if (singlePage) {
      scrollToCommerce();
      return;
    }
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

  // --- the report's own photographs -----------------------------------------

  // Set once the paid content lands, read by the section builders below. A
  // module-level handle rather than a parameter threaded through buildSection,
  // because two of the six builders want it and the other four do not.
  var reportVisuals = null;

  function imageById(id) {
    var steps = (cfg && cfg.swipe && cfg.swipe.steps) || [];
    for (var i = 0; i < steps.length; i++) {
      var pairs = steps[i].pairs || [];
      for (var j = 0; j < pairs.length; j++) {
        var images = pairs[j].images || [];
        for (var k = 0; k < images.length; k++) {
          if (images[k].id === id) return images[k];
        }
      }
    }
    return null;
  }

  // Which image they tapped on one named step, or null. Reads `chosen`, so it
  // only answers in the tab that took the quiz.
  function chosenOnStep(stepId) {
    if (!stepId || !chosen.length) return null;
    var steps = (cfg && cfg.swipe && cfg.swipe.steps) || [];
    for (var i = 0; i < steps.length; i++) {
      if (steps[i].id !== stepId) continue;
      var here = {};
      (steps[i].pairs || []).forEach(function (p) {
        (p.images || []).forEach(function (g) { here[g.id] = true; });
      });
      for (var c = 0; c < chosen.length; c++) {
        if (here[chosen[c]]) return chosen[c];
      }
    }
    return null;
  }

  // The palette board they chose and the two surfaces they picked, as image
  // records. Three sources, in falling order of how much they know about this
  // particular reader:
  //
  //   1. what the server stored with the report — the only one that survives
  //      the Stripe redirect, which is how nearly everybody arrives here;
  //   2. the run in this tab, for a report opened without leaving;
  //   3. the config's per-style defaults, for a report written before this
  //      shipped or a run whose choices did not reach the server.
  //
  // A report illustrated with somebody else's kitchen is worse than one with
  // no pictures, so every branch ends in an image this reader could actually
  // have been shown for their style.
  function visualsFor(content) {
    var block = (cfg && cfg.report && cfg.report.visuals) || {};
    var stored = (content && content.visuals) || {};
    var byStyle = (block.defaults || {})[(content || {}).style_id] || {};
    var steps = block.material_steps || [];

    var board = stored.moodboard
      || chosenOnStep(block.moodboard_step)
      || byStyle.moodboard;

    var mats = [];
    var storedMats = stored.materials || [];
    for (var i = 0; i < steps.length; i++) {
      var one = storedMats[i] || chosenOnStep(steps[i])
        || (byStyle.materials || [])[i];
      var rec = one && imageById(one);
      if (rec) mats.push(rec);
    }
    return { moodboard: board && imageById(board), materials: mats };
  }

  function figureNode(cls, item, caption) {
    var fig = elm("figure", cls);
    var img = document.createElement("img");
    img.src = item.img;
    img.alt = "";
    img.loading = "lazy";
    img.draggable = false;
    fig.appendChild(img);
    if (caption && item.label) {
      fig.appendChild(elm("figcaption", null, item.label));
    }
    return fig;
  }

  // --- typed section bodies (schema 2) -------------------------------------

  function paletteBody(d) {
    var frag = document.createDocumentFragment();

    // The board they chose at the colour step, at the head of the section the
    // colours came out of. It is the one picture in the report that says "this
    // is yours" without a sentence having to say it.
    var board = (reportVisuals || {}).moodboard;
    if (board) frag.appendChild(figureNode("palette-board", board, true));

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

    // The worktop and the backsplash they picked, side by side above the
    // verdicts. This section is a set of judgements about surfaces; showing
    // the two surfaces it is judging is the difference between reading advice
    // and reading advice about your own kitchen.
    var mats = (reportVisuals || {}).materials || [];
    if (mats.length) {
      var strip = elm("div", "material-strip");
      mats.forEach(function (m) {
        strip.appendChild(figureNode("material-shot", m, true));
      });
      frag.appendChild(strip);
    }

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
  // The order the document is read in belongs to the config, not to whichever
  // model call happened to finish first. Enabled sections, in the order they
  // are configured.
  function reportOrder(content) {
    var configured = ((cfg && cfg.report && cfg.report.sections) || [])
      .filter(function (sec) { return sec.enabled !== false; })
      .map(function (sec) { return sec.id; });
    if (configured.length) return configured;
    // The report can arrive before the config does. The payload is built in
    // report order too, so it is the same answer rather than a different one.
    return (content.sections || []).map(function (sec) {
      return sec && sec.id;
    });
  }

  // The seam the elements sit on, read out of the config rather than by naming
  // "palette" here: the last section the reader is given for nothing. Same rule
  // the preview uses, so the two views cannot drift apart.
  function elementsAnchor() {
    var sections = ((cfg && cfg.report && cfg.report.sections) || [])
      .filter(function (sec) { return sec.enabled !== false; });
    var anchor = null;
    for (var i = 0; i < sections.length; i++) {
      var mode = (sections[i].reveal && sections[i].reveal.mode) || "locked";
      if (mode !== "visible") break;
      anchor = sections[i].id;
    }
    return anchor || (sections[0] && sections[0].id) || null;
  }

  function placeElements(content) {
    if (paidElements) return;
    paidElements = true;
    var node = elementsSection(true, content.elements);
    if (!node) return;
    el.report.appendChild(node);
    observeSection(node);
  }

  // Strictly in order, and only ever a prefix of it. A section is rendered
  // once every section above it is already on screen, so the reader never
  // watches "Materials" appear over the hole where "The 5 Mistakes" is still
  // being written and then get pushed down when it lands. Nothing shows at all
  // until the palette is in — the generating card covers that wait, and a
  // report that opens on its fourth section is not the document that was sold.
  function renderUnlockedReport(content) {
    // The two share section classes, so the preview's must not survive into
    // the paid view — it would leave paid sections wired to the paywall.
    el.report.classList.remove("report-preview");
    el.report.classList.add("report-unlocked");
    var typed = isTyped(content.version);
    // Resolved on every poll: the first one may arrive before the config has,
    // and the section builders below read it as they run.
    reportVisuals = visualsFor(content);

    var arrived = {};
    (content.sections || []).forEach(function (sec) {
      if (sec && sec.id) arrived[sec.id] = sec;
    });

    var order = reportOrder(content);
    var anchor = elementsAnchor();
    for (var i = 0; i < order.length; i++) {
      var id = order[i];
      if (!rendered[id]) {
        var sec = arrived[id];
        if (!sec) break;                  // the first gap ends the run
        var block = buildSection(sec, typed);
        rendered[id] = block;
        el.report.appendChild(block);     // always in order, so never inserted
        observeSection(block);
      }
      if (id === anchor) placeElements(content);
    }

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

  // The one locked section worth naming before anyone scrolls. Five of the six
  // are things a reader can imagine wanting; the mistakes section is the one
  // that costs money not to have, so it gets a line of its own directly under
  // the blurb, above the report rather than inside it. Templated in config so
  // the number and the wording stay copy rather than code.
  function buildMistakesTeaser(style) {
    var copy = (cfg.result && cfg.result.mistakes_teaser) || "";
    if (!copy) return null;
    var node = elm("p", "mistakes-teaser");
    node.id = "mistakes-teaser";
    node.textContent = copy.replace(/\{style\}/g, (style && style.name) || "");
    node.addEventListener("click", focusCta);
    return node;
  }

  // Two-screen placement: above the report card, where it has always been.
  // Single-page puts it inside the card instead, under the offer, which is the
  // seam `addOffer` owns.
  function renderMistakesTeaser(style) {
    var node = buildMistakesTeaser(style);
    if (!node) return;
    el.report.parentNode.insertBefore(node, el.report);
    el.mistakesTeaser = node;
  }

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
      singlePage = wantsSinglePage();

      if (singlePage) {
        // No result CTA and no value banner: the button is the one at the
        // bottom of the page now, and the anchor card carries what the banner
        // used to say — once, where the decision is actually made.
        el.cta.hidden = true;
        renderLockedReport(win);
        renderCommerce();
      } else {
        el.cta.textContent = cfg.pricing.cta;
        renderMistakesTeaser(win);
        renderValueBanner();
        renderCtaNote();
        renderLockedReport(win);
      }

      track("result_view");
      // A finished quiz with a result on screen is the qualified visitor Meta
      // should be optimising towards, so Lead sits exactly here and nowhere
      // earlier.
      pixelTrack("Lead");
      if (singlePage) {
        watchCommerce();
        watchScroll();
      } else {
        watchCta();
      }
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

  // Called on every poll that carries sections. The first one that can open
  // the document swaps the loading state for it; the rest only append.
  function renderUnlocked(content, complete) {
    unlockedContent = content;
    unlockedComplete = complete;

    // The section the report opens with has to be here before any of it goes
    // up. A poll can carry section four on its own — the model calls resolve
    // in whatever order they resolve — and swapping the loading state for a
    // report whose first heading is "Get the Look" is a worse wait than the
    // wait itself. The status card stays until the opening is real.
    if (!unlockedShown && !hasOpening(content)) return;

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

  // Whether the section the document opens with is here.
  //
  // Without the config there is no such thing as "the section it opens with":
  // the payload's own order is the order things resolved in, which is how a
  // report ends up opening on its third heading. So the answer is no until the
  // config lands — the status card is already covering that wait — and
  // `configLost` releases the hold if it never does, because a paid report
  // withheld over a CDN hiccup is far worse than one in the wrong order.
  function hasOpening(content) {
    if (!configLost && !(cfg && cfg.report && cfg.report.sections)) return false;
    var order = reportOrder(content);
    if (!order.length) return false;
    var first = order[0];
    return (content.sections || []).some(function (sec) {
      return sec && sec.id === first;
    });
  }

  // The config and the report race each other, and either can win. Whichever
  // arrives second re-runs the render, so content held back for want of an
  // order goes up the moment the order is known rather than on the next poll.
  function reflowUnlocked() {
    if (unlockedContent) renderUnlocked(unlockedContent, unlockedComplete);
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

  // The payment attempt itself, and the only place that name belongs. Fired
  // before the guard rather than after it: what this counts is somebody
  // pressing the button that takes their money, and a run that then bails on
  // an unchecked box is a tap that happened. The guard is unreachable from
  // the UI anyway — the button is disabled while the box is clear, and a
  // disabled button dispatches no click.
  function startCheckout() {
    track("pay_tap");
    // Meta's name for the same moment. InitiateCheckout already fires when the
    // offer reaches somebody; this is the narrower signal Meta optimises
    // against — the tap that starts paying. Both ways in go through here, the
    // pay button and the sticky bar's shortcut, so one call covers both and
    // neither can drift from the other.
    pixelTrack("AddPaymentInfo");
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
        // Everything that can go wrong between the tap and Stripe lands here:
        // a dead network, a 500, a response with no url in it. Until now all
        // of it was silent — the reader saw one sentence and the funnel report
        // saw a tap that simply never became a purchase, which is the same
        // shape as somebody changing their mind. No payload: the event is the
        // fact, and anything more would be describing our own failure into a
        // table that holds one row per visitor action.
        track("checkout_error");
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
      dot.style.backgroundColor = swatchColor(c);
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

    // One row is the reason most people are on this screen, and six identical
    // ticks say the opposite — that everything in the list weighs the same.
    // The config names the row by a fragment of its own copy rather than by
    // an index, so re-ordering the manifest cannot silently promote the wrong
    // line. First match only: a treatment applied twice is not a treatment.
    var needle = (cfg.checkout.manifest_hero || "").toLowerCase();
    var promoted = false;

    el.manifest.innerHTML = "";
    rows.forEach(function (row) {
      var li = elm("li", "manifest-row");
      if (needle && !promoted && String(row).toLowerCase().indexOf(needle) !== -1) {
        promoted = true;
        li.classList.add("is-hero");
      }
      li.appendChild(icon("check", "manifest-check"));
      li.appendChild(elm("span", "manifest-text", row));
      el.manifest.appendChild(li);
    });
  }

  var TRUST_ICONS = ["lock", "bolt", "mail"];

  function renderTrust(rows) {
    el.trust.innerHTML = "";
    (rows || cfg.checkout.trust || []).forEach(function (row, i) {
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


  // --- single-page checkout -------------------------------------------------

  // The paywall as a block on the result page rather than a screen after it.
  // Config decides, but only when the config also carries the copy the block
  // is made of: engine.js and the funnel JSON sit behind a CDN and can be
  // cached a version apart, and an engine that switched to single-page against
  // a config with no `commerce` in it would render a half-empty page with a
  // pay button on the end. Falling back to the two-screen flow that older
  // config can fill completely is the only safe way to be wrong here.
  function wantsSinglePage() {
    var co = (cfg && cfg.checkout) || {};
    return co.single_page !== false && !!co.commerce;
  }

  function commerceCopy() {
    return ((cfg && cfg.checkout) || {}).commerce || {};
  }

  // Relocation, not duplication. Every row in the block below is the node the
  // two-screen paywall uses, moved: the pay button keeps the listener wire()
  // gave it, `startCheckout` keeps the element it already knew about, and
  // `updatePayButton` keeps working on both paths. Two buttons that can both
  // charge somebody is exactly the kind of thing that ends up with one of them
  // never being updated again.
  // Headline, then what you get, then what it costs, then the button. The
  // manifest used to come first and the headline second, which put the list
  // in front of the reason to read it; and the price used to sit two rows
  // above the button with the consent between them, so the number and the tap
  // were never in the eye at once. Everything below the anchor is now one
  // descent: six rows, a price, a checkbox, the button.
  function moveCommerce() {
    if (commerceMoved) return;
    commerceMoved = true;
    // Before the move: it inserts relative to nodes that are about to travel.
    ensurePayNodes();

    [el.payAnchor, el.manifest, buildSampleLink(), el.price, el.withdrawal,
     el.payButton, el.payError, el.trust, el.legal].forEach(function (node) {
      if (node) el.commerce.appendChild(node);
    });

    // Left behind, with the screen nobody now travels to: its kicker and title
    // were introducing that screen, the colour proof repeats the palette the
    // reader has already scrolled past, the manifest head and the reframe line
    // are not in the merged layout, and the back link has nothing to go back
    // to. Hidden rather than deleted so the flag can put them back.
    [el.payKicker, el.paywallHeadline, el.payProof, el.paywallBack,
     el.manifestHead, el.reframe].forEach(function (node) {
      if (node) node.hidden = true;
    });
  }

  function renderCommerce() {
    var copy = commerceCopy();
    moveCommerce();

    renderManifest();

    fillAccent(el.anchorHead, withPrice(copy.anchor_head || ""),
               copy.anchor_head_accent || "");
    el.anchorHead.hidden = !copy.anchor_head;
    el.anchorLine.textContent = withPrice(copy.anchor || "");
    el.anchorLine.hidden = !copy.anchor;
    el.payAnchor.hidden = !(copy.anchor_head || copy.anchor);

    var suffix = copy.price_suffix;
    el.price.textContent = formatPrice() + (suffix ? " \u00B7 " + suffix : "");

    el.withdrawalText.textContent = withPrice(copy.consent || "");
    el.withdrawalCheck.checked = cfg.checkout.consent_prechecked === true;

    renderTrust(copy.trust);
    el.payError.hidden = true;
    updatePayButton();

    el.commerce.hidden = false;
    if (el.sticky) el.sticky.textContent = withPrice(copy.sticky_label || "");
    playPayMotion();
  }

  // --- the sample page --------------------------------------------------------

  var SAMPLE_SRC = "/static/img/sample_page.png";

  // Under the manifest, because that is where somebody stops believing the
  // list: six lines describing a document is not a document. The link opens
  // one real page of one, with its lower half behind a blur — the same
  // boundary the report itself draws, drawn once more where the decision is.
  function buildSampleLink() {
    var copy = commerceCopy();
    if (!copy.sample_link) return null;
    var link = elm("button", "sample-link", copy.sample_link);
    link.type = "button";
    link.id = "sample-link";
    link.addEventListener("click", function (e) {
      e.stopPropagation();
      openSample();
    });
    return link;
  }

  function openSample() {
    if (el.sample) { showSample(); return; }
    var copy = commerceCopy();

    var box = elm("div", "lightbox");
    box.id = "sample-box";
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-modal", "true");
    box.setAttribute("aria-label", copy.sample_link || "Sample page");

    var shell = elm("div", "lightbox-shell");
    var figure = elm("div", "sample-figure");
    var img = document.createElement("img");
    img.className = "sample-img";
    img.src = SAMPLE_SRC;
    img.alt = "";
    figure.appendChild(img);
    // The blur is an overlay rather than a filter on the image, so the top of
    // the page stays exactly as sharp as it is in the report.
    figure.appendChild(elm("span", "sample-veil"));
    shell.appendChild(figure);
    if (copy.sample_caption) {
      shell.appendChild(elm("p", "sample-caption", copy.sample_caption));
    }

    var close = elm("button", "sample-close", "×");
    close.type = "button";
    close.id = "sample-close";
    close.setAttribute("aria-label", "Close");
    close.addEventListener("click", closeSample);
    shell.appendChild(close);

    box.appendChild(shell);
    // Anywhere off the page closes it; the page itself does not.
    box.addEventListener("click", function (e) {
      if (e.target === box) closeSample();
    });
    document.body.appendChild(box);
    el.sample = box;
    showSample();
  }

  function showSample() {
    el.sample.hidden = false;
    document.body.classList.add("is-locked");
    document.addEventListener("keydown", sampleKeys);
    var close = el.sample.querySelector(".sample-close");
    if (close && close.focus) close.focus();
  }

  function closeSample() {
    if (!el.sample) return;
    el.sample.hidden = true;
    document.body.classList.remove("is-locked");
    document.removeEventListener("keydown", sampleKeys);
  }

  function sampleKeys(e) {
    if (e.key === "Escape" || e.keyCode === 27) closeSample();
  }

  // The card between the elements strip and the first locked section. It is
  // the only thing on the way down that asks for anything, and what it asks
  // for is a scroll rather than a payment.
  function buildMidCta() {
    var copy = commerceCopy();
    if (!copy.mid_button) return null;

    var card = elm("div", "mid-offer");
    card.id = "mid-offer";
    var line = elm("p", "mid-offer-line");
    fillAccent(line, withPrice(copy.mid_line || ""), copy.mid_line_accent || "");
    card.appendChild(line);

    var button = elm("button", "mid-offer-cta", withPrice(copy.mid_button));
    button.type = "button";
    button.addEventListener("click", function (e) {
      e.stopPropagation();          // the report card scrolls on tap too
      track("mid_cta");
      payIntent = "mid_cta";
      stickyArmed = true;
      updateSticky();
      scrollToCommerce();
    });
    card.appendChild(button);
    el.midOffer = card;
    return card;
  }

  // Both single-page insertions, at the seam the elements strip already owns:
  // elements, then the offer card, then the teaser, then everything withheld.
  function addOffer(style) {
    var mid = buildMidCta();
    if (mid) el.report.appendChild(mid);
    var teaser = buildMistakesTeaser(style);
    if (teaser) {
      el.report.appendChild(teaser);
      el.mistakesTeaser = teaser;
    }
  }

  // Whether the bar can charge somebody without showing them the block first.
  // Both halves matter: the config has to say the consent is given by default,
  // AND the box has to actually be ticked — a reader who scrolled down and
  // unticked it has said something, and a bar that ignored that would be
  // taking the money on a consent that had been withdrawn.
  function stickyCanCheckout() {
    return !!(cfg && cfg.checkout
              && cfg.checkout.consent_prechecked === true
              && el.withdrawalCheck && el.withdrawalCheck.checked
              && el.payButton && !el.payButton.disabled
              && el.commerce && !el.commerce.hidden);
  }

  // The bar is the offer, not a signpost to it. Sending somebody to a button
  // they had already found is a scroll and a second decision between the tap
  // and Stripe, and both of those are places to lose them.
  //
  // The event trail is the same one the scroll produces, in the same order:
  // sticky_cta for the tap, then paywall_view attributed to it — the offer
  // reached this reader here, on the bar, which is exactly what that event is
  // for — then pay_tap out of startCheckout. Firing paywall_view by hand is
  // what stops the shortcut from putting a hole in the funnel, because the
  // observer that usually fires it never sees the block scroll past.
  function stickyTap() {
    track("sticky_cta");
    payIntent = "sticky";
    if (stickyCanCheckout()) {
      firePaywallView();
      startCheckout();
      return;
    }
    stickyArmed = true;
    updateSticky();
    scrollToCommerce();
  }

  function scrollToCommerce() {
    if (!el.commerce || el.commerce.hidden) return;
    if (el.commerce.scrollIntoView) {
      el.commerce.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    nudgePay();
  }

  function nudgePay() {
    if (!el.payButton) return;
    el.payButton.classList.remove("is-nudged");
    void el.payButton.offsetWidth;
    el.payButton.classList.add("is-nudged");
  }

  // --- the sticky bar -------------------------------------------------------

  // Shown once somebody is past the free part or has asked to see the offer,
  // and taken away again whenever the real block is on screen — a bar telling
  // you to go to the thing you are already looking at is just something
  // covering it.
  function updateSticky() {
    var bar = el.sticky;
    if (!bar || !singlePage) return;
    var want = (stickyArmed || pastPalette()) && !commerceInView;
    if (want === stickyOn) return;
    stickyOn = want;
    bar.hidden = !want;
    // Next frame, so the slide has a starting position to animate from.
    if (want) {
      requestAnimationFrame(function () { bar.classList.add("is-in"); });
    } else {
      bar.classList.remove("is-in");
    }
  }

  // "Past the free palette" is its bottom edge leaving the top of the screen.
  // The palette is the first section in the report by construction — it is the
  // one the config marks visible, and the ordering gate puts it first.
  function pastPalette() {
    var first = el.report && el.report.querySelector(".section");
    if (!first) return false;
    return first.getBoundingClientRect().bottom < 0;
  }

  function watchScroll() {
    var pending = false;
    function onScroll() {
      if (pending) return;
      pending = true;
      requestAnimationFrame(function () {
        pending = false;
        updateSticky();
      });
    }
    // Passive: this only reads geometry and must never hold up a scroll.
    try {
      window.addEventListener("scroll", onScroll, { passive: true });
    } catch (e) {
      window.addEventListener("scroll", onScroll);
    }
    window.addEventListener("resize", onScroll);
    onScroll();
  }

  // --- reaching the offer ---------------------------------------------------

  // `paywall_view` means the commerce block reached the reader, once per
  // session, and it carries how they got there — whichever deliberate act most
  // recently preceded it, or plain scrolling when there was none. The pixel's
  // InitiateCheckout fires at the same moment for the same reason: this is
  // where the offer is actually seen.
  function watchCommerce() {
    if (!window.IntersectionObserver) {
      firePaywallView();
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        commerceInView = e.isIntersecting;
        if (e.isIntersecting) firePaywallView();
      });
      updateSticky();
    }, {
      // Any part of it entering counts, except the strip the sticky bar
      // covers. A threshold fraction would be unreachable on a block taller
      // than the viewport, which this one can be.
      threshold: 0,
      rootMargin: "0px 0px -80px 0px"
    });
    io.observe(el.commerce);
  }

  function firePaywallView() {
    if (paywallTracked) return;
    paywallTracked = true;
    track("paywall_view", null, { src: payIntent });
    pixelTrack("InitiateCheckout");
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
    el.withdrawal = $("withdrawal");
    el.legal = $("legal-links");
    el.commerce = $("commerce");
    el.sticky = $("sticky-cta");
  }

  function wire() {
    // This button opens the paywall. It does not start a payment, and calling
    // it `pay_tap` made every funnel report count the two as the same act —
    // the ratio between deciding to look at the price and deciding to pay it
    // was invisible, and the drop-off between them read as no drop-off at all.
    //
    // The pixel event stays here on purpose. InitiateCheckout is Meta's name
    // for the intent step, and intent is exactly what this tap is.
    el.cta.addEventListener("click", function () {
      track("paywall_open");
      pixelTrack("InitiateCheckout");
      renderPaywall();
      show("screen-paywall");
    });
    if (el.sticky) el.sticky.addEventListener("click", stickyTap);
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
    setMoneyLine(cfg.swipe.subtext || "", cfg.swipe.subtext_accent || "");
    if (el.tapHint && cfg.swipe.hint) setHint(cfg.swipe.hint);

    var first = pairFor(0);
    if (!first) { startResult(); return; }
    pair = first;
    show("screen-swipe");
    track("funnel_start");
    preloadPair(pair, renderStep);
  }

  // The header line, with the part that names the saving lifted into the
  // accent. The fragment to lift is named in the config rather than marked up
  // in it: config carries copy, and copy with tags in it is copy that has to
  // be trusted with innerHTML. Everything here is a text node, so the worst a
  // bad config can do is fail to match and leave the line plain.
  function setMoneyLine(text, accent) {
    fillAccent(el.subtext, text, accent);
  }

  // One line with one fragment of it lifted into the accent. Shared by the
  // swipe header, the mid-page card and the commerce anchor, so the three
  // places that shout a number all shout it the same way. Everything appended
  // is a text node: config carries copy, never markup.
  function fillAccent(node, text, accent) {
    if (!node) return;
    node.textContent = "";
    text = String(text || "");
    var at = accent ? text.indexOf(accent) : -1;
    if (at === -1) {
      node.textContent = text;
      return;
    }
    node.appendChild(document.createTextNode(text.slice(0, at)));
    node.appendChild(elm("span", "money", accent));
    node.appendChild(document.createTextNode(text.slice(at + accent.length)));
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
        if (unlocked) { applyStyleCopy(); reflowUnlocked(); }
        else startQuiz();
      })
      .catch(function () {
        // Nothing is coming. Whatever the report says its own order is, is now
        // the best order there is.
        configLost = true;
        if (unlocked) reflowUnlocked();
        // The kicker this used to write into is gone; the caption is the
        // loudest slot on an otherwise empty screen, so the failure goes there.
        if (!unlocked) el.caption.textContent = "This quiz is unavailable right now.";
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
