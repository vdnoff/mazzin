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
  // The token a paid reader comes back with. Two shapes, because there are two
  // ways to pay: `cs_` from the hosted redirect, `pi_` from a payment confirmed
  // in the page. The parameter is called `cs` for both — it is the name that is
  // already in the wild, on links people have and on the server route that
  // reads it, and renaming it would strand every one of them.
  //
  // This mirrors payments.RESULT_TOKEN_RE, which is what actually decides
  // whether a token finds a purchase. A `pi_` reaching here and being turned
  // away would have dropped somebody who had just paid onto the quiz.
  var CS_RE = /^(?:cs|pi)_[A-Za-z0-9_]{1,250}$/;
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
  var unlockedCs = null;        // the token this report was opened with
  var vizNode = null;           // the visualizer section, placed once
  var vizDead = false;          // the server said not for this reader, ever
  var vizTeaserSeen = false;    // the locked panel has been counted once
  var vizState = null;          // the last status body the server sent
  var vizTimer = null;          // the poll, running only while it generates
  var vizBusy = false;          // a request of ours is in flight
  var vizUploading = false;     // the in-flight request is an upload
  var vizUploadPath = null;     // how it was shrunk: bitmap|canvas|raw
  var vizSeen = {};             // status -> already counted, so events fire once
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
  // Which of the three steps the reader is standing in: 0 while they are
  // choosing, 1 once the offer and the upload box are what is in front of
  // them, 2 once their kitchen has actually been drawn.
  var journeyStage = 0;
  var gateSeen = false;         // viz_gate_view is once a session, not a scroll
  var gateIO = null;            // its observer, dropped the moment it fires
  var gateUp = false;           // no photograph yet, so the gate is showing
  var payHeld = false;          // no pay control on screen, for any reason
  var pixelCartFired = false;   // AddToCart: the first photo, once
  var payReadyFired = false;    // which control was shown, counted once
  var readerCountry = null;     // two letters off the edge, or null for unknown
  var pixelPayFired = false;    // AddPaymentInfo: once, on either path
  // --- express checkout -----------------------------------------------------
  var xpState = "off";          // off | reserved | wallet | redirect
  var xpStarted = false;        // the whole attempt runs once per page
  var xpSlot = null;            // the placeholder and the element, stacked
  var xpMountNode = null;       // the layer the element itself mounts into
  var xpBlock = null;           // the grid holding the slot and the pay button
  var xpIntent = null;          // {client_secret, publishable_key} from the API
  var xpElements = null;        // the Stripe Elements group
  var xpTimer = null;           // the deadline; a dead paywall costs more

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

  // A step shows two images side by side, four in a grid, six in three rows
  // of two, or twelve in four rows of three. All of them are one question and
  // one tap; the format only changes how many things are being compared at
  // once. Everything downstream reads this table rather than naming a format,
  // so a new one is an entry here plus the CSS that lays it out.
  var GRID_SIZE = { grid4: 4, grid6: 6, grid12: 12 };
  var GRID_NAMES = Object.keys(GRID_SIZE);

  function stepFormat(st) {
    var f = st && st.format;
    return GRID_SIZE[f] ? f : "pair";
  }

  function stepSize(st) {
    return GRID_SIZE[stepFormat(st)] || 2;
  }

  // Whether card labels are on screen all the time or only in the chip after
  // a tap. Absent is the tap-reveal behaviour every funnel has had.
  function labelMode() {
    return (cfg && cfg.swipe && cfg.swipe.label_mode) || "";
  }

  // The axes a step can adapt on. The config names the axis; what the
  // axis is made of lives here, because it is the same vocabulary the styles
  // are scored against and it should not be restatable per funnel.
  //
  // Season is the odd one: it is answered outright by a step that asks which
  // one somebody was born in, rather than accumulated over several taps, and
  // no style is scored against it. It is here for the same reason the other
  // two are — an axis this file has never heard of resolves to no leader at
  // all, which collapses every variant onto `default` silently.
  var TONE_AXIS = ["warm", "cool", "dark", "bright"];
  var TONE_OPPOSITE = {
    warm: "cool", cool: "warm", dark: "bright", bright: "dark"
  };
  var MATERIAL_AXIS = ["wood", "stone", "metal"];
  var SEASON_AXIS = ["spring", "summer", "autumn", "winter"];
  var AXES = {
    tone: TONE_AXIS, material: MATERIAL_AXIS, season: SEASON_AXIS
  };

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
  //
  // A step may opt out with `"shuffle": false`, and one kind of step has to.
  // Shuffling assumes the cards are alternatives being weighed, so their order
  // carries no meaning and randomising it only removes a bias. That stops
  // being true when the set has an order of its own: a reader scanning twelve
  // zodiac signs is looking for the one that is already theirs, and Aries to
  // Pisces is where they expect to find it. Dealing that shuffled does not
  // remove a bias, it just makes them read all twelve. Absent, every step
  // shuffles exactly as it always has.
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
    if (st && st.shuffle === false) {
      return { id: pick.id || "p1", images: images };
    }
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

    // Some funnels name every card on screen, permanently, rather than only
    // in the chip that lands after a tap. A zodiac grid of twelve glyphs is
    // unreadable without it — the reader is looking for their own sign, not
    // comparing pictures — where a kitchen pair is a photograph that would
    // only be covered up by a word. So it is a funnel-level flag, and a
    // config without it renders exactly what it always did.
    //
    // `badge` is the only mode. The first attempt at this put the name across
    // the middle of the card over a scrim, and on a phone the scrim muddied
    // every frame and sat on top of the sign glyph — the art is the product,
    // and a label that dims it is a label that costs more than it earns. The
    // pill sits under the picture instead and touches nothing.
    if (labelMode() === "badge" && item.label) {
      var name = document.createElement("span");
      name.className = "card-name";
      name.setAttribute("aria-hidden", "true");   // the button already says it
      name.textContent = item.label;
      card.appendChild(name);
    }

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
    // One class per known grid, off the table above. A pair carries none of
    // them, which is what it carried before, and a format added to the table
    // gets its class without this line being touched again.
    GRID_NAMES.forEach(function (name) {
      el.cards.classList.toggle("is-" + name, fmt === name);
    });
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
    setHandoff(entry.next || "");
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

  // What happens after the last one of these. Per-entry copy, so only the
  // interstitial that is actually the last one carries it — a "next: your
  // result" on the first of three would be a lie about how much is left.
  //
  // Below the working row and above the button, because it is the one line
  // here that is about after rather than about now. Set on every open, so an
  // entry without it clears one left by an entry that had it.
  function setHandoff(text) {
    var node = el.midNext;
    if (!text) {
      if (node) node.hidden = true;
      return;
    }
    if (!node) {
      node = elm("p", "mid-next");
      node.id = "mid-next";
      el.midSub.parentNode.appendChild(node);
      el.midNext = node;
    }
    node.hidden = false;
    node.textContent = fillTokens(text);
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
    // Resolved once for the whole zone: three places write hooks and all three
    // must name the same worktop.
    hookWords = hookWordsFor(style);
    el.report.innerHTML = "";
    el.report.classList.add("report-preview");

    // One block, and it is the thing being sold. Everything the loop below
    // would build — the palette section, the free mistake, the elements strip,
    // the mid card, the mistakes teaser, the two remaining blurred teasers and
    // the also-list — is off this funnel's page. `placeVisualizer` puts their
    // own palette, their own materials and the two panels in, and
    // `renderCommerce` puts the offer under it.
    if (focusResult()) {
      el.report.classList.add("report-focus");
      placeVisualizer();
      return;
    }

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

    // Last, so it lands at the top of a report that has just been rebuilt from
    // nothing. On the funnel that takes the photo early this is the first
    // thing under the style name — their kitchen, and the transformation they
    // have not bought yet — and on every other funnel it does not exist.
    placeVisualizer();

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
      if (row.hook) {
        text.appendChild(elm("p", "also-hook", fillHook(row.hook, hookWords)));
      }
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

    // A line under the strip for a funnel that sells something the strip does
    // not describe. It is config copy and nothing else — a funnel without it
    // renders exactly what it rendered before — and it sits under the chips
    // because that is where the reader has just been shown what the report
    // knows about their kitchen, which is the thing being transformed.
    if (!detail && block.promo) {
      node.appendChild(elm("p", "elements-promo", block.promo));
    }

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
    body.appendChild(dissolveNode(fillHook(setup, hookWords),
                                  fillHook(trigger, hookWords),
                                  runOn(fillerLines(sec, 2))));

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

  // The same shape on the free side: the words the locked zone's hooks are
  // written around, resolved once per render and read by all three of the
  // places that write one.
  var hookWords = {};

  // --- the words a hook is written around -----------------------------------

  // What goes where a hook says {worktop}. Every one of them is read out of
  // the run: which image was tapped on which step, and the label the quiz put
  // under it. The step each placeholder reads lives in the config, because
  // step ids belong to a funnel and this engine serves any of them.
  //
  // A curiosity gap about your own worktop is a different thing from one about
  // worktops. Nothing here makes a claim the generic copy did not — the same
  // sections, described in the reader's own nouns.
  function hookWordsFor(style) {
    var slots = (cfg && cfg.report && cfg.report.hook_slots) || {};
    var out = { style: (style && style.name) || "" };
    for (var key in slots) {
      if (!Object.prototype.hasOwnProperty.call(slots, key)) continue;
      var rule = slots[key] || {};
      var picked = imageById(chosenOnStep(rule.step));
      var label = picked && picked.label;
      // The fallback is the bare noun rather than a phrase, because every
      // sentence is written around "your {slot}" and has to survive as
      // English without one: "one involves your worktop" reads, where an
      // empty string leaves a hole and "the worktop you chose" leaves two
      // articles. Only reachable on a config whose steps have been renamed —
      // the locked zone is rendered off a finished run — but a hook with
      // braces in it on a live page would be worse than a generic one.
      out[key] = label ? lowerLabel(label) : (rule.fallback || key);
    }
    return out;
  }

  // "Aged brass" is a proper noun that is not one, and it lands mid-sentence.
  // First character only: "Moss & earth" must not come back as "moss & Earth".
  function lowerLabel(text) {
    return String(text).charAt(0).toLowerCase() + String(text).slice(1);
  }

  // A placeholder nothing answers is left as it was written. That way a copy
  // change that invents `{splashback}` shows up as `{splashback}` on the page
  // rather than as a silent gap in a sentence.
  function fillHook(text, words) {
    if (!text) return "";
    return String(text).replace(/\{(\w+)\}/g, function (whole, key) {
      return Object.prototype.hasOwnProperty.call(words || {}, key)
        ? words[key] : whole;
    });
  }

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
    placeVisualizer();
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
    node.textContent = fillHook(copy, hookWordsFor(style));
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

  // --- a funnel's own result page --------------------------------------------
  //
  // One funnel now wants a result page that is not this one's. Rather than a
  // second design growing inside these five thousand lines behind flags, a
  // config may name a script and a stylesheet and take the page over: this
  // file computes the run — the winner, the tallies, what was tapped, what is
  // locked — hands it across, and stops drawing.
  //
  // The seam is deliberately narrow and one-directional. A module renders the
  // pre-purchase page and nothing else: the paid report is drawn by
  // `buildSection` off SECTION_BODY for every funnel, unconditionally, and
  // payment is never handed over — the module is given the consent box and the
  // pay button this file already built and wired, to place where it wants
  // them. It cannot make a payment; it can only put ours somewhere.
  //
  // A funnel with no `result_module` never reaches any of this.

  var moduleAssets = {};

  function resultModule() {
    return (cfg && cfg.result_module) || "";
  }

  // Script and stylesheet, once each, in that order — the module's own render
  // measures nothing, but a page that paints unstyled and then restyles is a
  // flash the reader sees.
  function loadAsset(url, done) {
    if (!url) return done();
    if (moduleAssets[url] === "done") return done();
    if (moduleAssets[url]) return moduleAssets[url].push(done);
    var waiting = moduleAssets[url] = [done];
    function settle() {
      moduleAssets[url] = "done";
      waiting.forEach(function (fn) { fn(); });
    }
    var node;
    if (/\.css($|\?)/.test(url)) {
      node = document.createElement("link");
      node.rel = "stylesheet";
      node.href = url;
    } else {
      node = document.createElement("script");
      node.src = url;
      node.async = false;
    }
    node.onload = settle;
    // A module that will not load must not leave the reader on a blank page,
    // so a failure settles too and `renderModuleResult` falls back to this
    // file's own result.
    node.onerror = settle;
    document.head.appendChild(node);
  }

  // The run's tallies for a named set of tags, in the order asked for.
  //
  // Which tags are elements and which are energy is not something this file
  // can know — the vocabulary belongs to the funnel, and this one has three
  // axes where kitchen has two. So the raw scores go across and the module,
  // which does know, asks for the groups it wants.
  function tallyOf(names) {
    return (names || []).map(function (tag) {
      return { tag: tag, score: scores[tag] || 0 };
    });
  }

  // What the module is given. Everything in here is the finished run — nothing
  // it is handed can be recomputed by a page that was reached through a
  // redirect, which is the same reason the paid view stores its elements.
  function resultContext(win) {
    var picks = {};
    ((cfg.swipe && cfg.swipe.steps) || []).forEach(function (step) {
      var id = chosenOnStep(step.id);
      var item = id && imageById(id);
      if (item) picks[step.id] = item;
    });

    var collapsed = collapsedIds();
    var sections = ((cfg.report && cfg.report.sections) || [])
      .filter(function (sec) { return sec.enabled !== false; })
      .map(function (sec) {
        return {
          id: sec.id,
          title: sec.title,
          teaser_line: sec.teaser_line || "",
          locked: ((sec.reveal || {}).mode || "locked") !== "visible",
          collapsed: !!collapsed[sec.id],
          reveal: (win.reveals || {})[sec.id] || null
        };
      });

    return {
      cfg: cfg,
      style: {
        id: win.id, name: win.name, blurb: win.blurb || "",
        tags: (win.tags || []).slice(),
        reveals: win.reveals || {}
      },
      tally: tallyOf,
      picks: picks,
      chosen: chosen.slice(),
      scores: JSON.parse(JSON.stringify(scores)),
      hookWords: hookWordsFor(win),
      fillHook: function (text) { return fillHook(text, hookWordsFor(win)); },
      strength: (win.reveals || {}).mistake_one || null,
      strengthCopy: (cfg.report && cfg.report.mistake_one) || {},
      sections: sections,
      price: formatPriceShort(),
      withPrice: withPrice,
      // The offer, as this file built it. `nodes` are real, live and already
      // listening — the consent box gates the button, the button takes the
      // money — and a module places them rather than making its own.
      commerce: commerceCopy(),
      nodes: {
        commerce: el.commerce, consent: el.withdrawal, payButton: el.payButton,
        payError: el.payError, trust: el.trust, price: el.price,
        manifest: el.manifest, anchor: el.payAnchor, legal: el.legal,
        // The wallet's own block, when a funnel offers one. `xpReserve` puts
        // it beside the pay button while that button is still in the commerce
        // container, so a module that moves the button has to move this with
        // it or leave the wallet behind in a box it just hid.
        //
        // `walletSummary` is the price row the wallet path shows in place of
        // the ordinary one, and it travels for the same reason: `xpReserve`
        // files it next to `el.price`, which a module is free to leave behind.
        wallet: xpBlock, walletSummary: el.xpSummary
      },
      checkout: startCheckout,
      track: function (name, extra) { track(name, null, extra); }
    };
  }

  function renderModuleResult(win) {
    var css = (cfg && cfg.result_css) || "";
    var root = el.moduleRoot;
    if (!root) {
      root = elm("div", "result-module");
      root.id = "result-module";
      el.report.parentNode.insertBefore(root, el.report);
      el.moduleRoot = root;
    }
    // This file's own result furniture stays out of the way rather than being
    // deleted: the paid view rebuilds on these same nodes after a purchase.
    el.report.hidden = true;
    el.cta.hidden = true;
    [el.resultKicker, el.resultName, el.resultBlurb].forEach(function (node) {
      if (node) node.hidden = true;
    });
    // Built and wired here, placed by the module. Everything the offer needs
    // to be legal and to work exists before the module has drawn anything.
    renderCommerce();

    loadAsset(css, function () {
      loadAsset(cfg.result_module, function () {
        var mod = window.MazzinResult;
        if (!mod || typeof mod.render !== "function") {
          // The module did not arrive. Put this file's own page back rather
          // than leaving a finished quiz on an empty screen.
          root.hidden = true;
          el.report.hidden = false;
          el.cta.hidden = true;
          [el.resultKicker, el.resultName, el.resultBlurb]
            .forEach(function (node) { if (node) node.hidden = false; });
          renderLockedReport(win);
          return;
        }
        try {
          mod.render(root, resultContext(win));
        } catch (e) {
          root.hidden = true;
          el.report.hidden = false;
          renderLockedReport(win);
        }
      });
    });
  }

  function startResult() {
    show("screen-result");
    el.analyzingText.textContent = cfg.analyzing.text;
    el.analyzing.hidden = false;
    el.resultBody.hidden = true;
    startFade();
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

      if (resultModule()) {
        // The delegation. A funnel that names a module draws its own
        // pre-purchase page; everything after it here — the tracking, the
        // pixel, the scroll watchers — is the same for both.
        renderModuleResult(win);
      } else if (singlePage) {
        // No result CTA and no value banner: the button is the one at the
        // bottom of the page now, and the anchor card carries what the banner
        // used to say — once, where the decision is actually made.
        el.cta.hidden = true;
        homeJourney();
        renderLockedReport(win);
        renderCommerce();
        // The offer is on screen: the choosing is done and the photo is what
        // is being asked for.
        markJourney(1);
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
  // A funnel may name a theme, which is one class on the body and nothing
  // else — the stylesheet decides what it means. A config without one leaves
  // the page exactly as it was.
  function applyTheme() {
    var theme = (cfg && cfg.theme) || "";
    if (/^[a-z0-9-]{1,24}$/.test(theme)) {
      document.body.classList.add("theme-" + theme);
    }
  }

  // The quiz is a light page and the reading is a dark one. Without this the
  // change lands in a single frame with the result, which reads as a
  // different site rather than as an arrival — so the page darkens across the
  // wait it already has, and the result is where it was going.
  //
  // Config, not inference: absent, nothing here runs and the body keeps the
  // background it always had.
  function startFade() {
    var to = (cfg && cfg.swipe && cfg.swipe.analyzing_fade_to) || "";
    if (!/^#[0-9a-fA-F]{3,8}$/.test(to)) return;
    var ms = Math.max(400, (cfg.analyzing && cfg.analyzing.duration_ms) || 2500);
    var body = document.body;
    body.style.setProperty("--fade-to", to);
    body.style.setProperty("--fade-ms", ms + "ms");
    // The copy switches once the ground behind it is already dark rather than
    // easing alongside it, which would spend the middle of the wait as grey
    // type on a grey field.
    body.style.setProperty("--fade-swap", Math.round(ms * 0.45) + "ms");
    // Next frame, so the starting colour is painted before the transition.
    requestAnimationFrame(function () { body.classList.add("is-fading"); });
  }

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

  // --- the visualizer -------------------------------------------------------

  // A photograph of the reader's own kitchen, redrawn in the style the report
  // just described. It is the headline of the funnel that sells it, so it sits
  // above the palette rather than under the document — and it exists at all
  // only where the config says so, which is what keeps every other funnel's
  // unlocked report byte-for-byte what it was.
  //
  // The whole thing is one small state machine over what the server says:
  //   none -> uploaded -> generating -> ready
  // with `failed` reachable from generating and returning to uploaded. The
  // server owns every transition; this only ever draws the state it is told
  // and asks for the next one. That is deliberate — a page that decided for
  // itself that a render was running would keep saying so after a reload, and
  // one that counted its own credits would disagree with the thing being
  // billed.

  var VIZ_POLL_MS = 2500;
  var VIZ_ROTATE_MS = 4000;

  // Refusals that mean "not for this purchase, ever" rather than "not now".
  // Every one of them is decided before any work is done and none of them can
  // change while the page is open, so the section retires instead of retrying.
  var DEAD = ["no_visualizer", "no_funnel", "no_purchase", "not_paid"];

  function vizConfig() {
    var block = cfg && cfg.visualizer;
    if (!block || block.enabled !== true) return null;
    return block;
  }

  // On the paid page it needs the purchase token. On the free one it needs a
  // funnel that has opted into taking the photo early, and the session id the
  // quiz has been sending with every event since boot.
  function vizOn() {
    var block = vizConfig();
    if (!block) return false;
    if (unlockedCs) return true;
    return block.pre_purchase === true && !!sessionId;
  }

  // The credential this page has, as the query string every call appends.
  // Which one it is decides almost nothing below — the server draws the same
  // line in one place and the client does not need a second copy of it.
  function vizAuth() {
    if (unlockedCs) return "cs=" + encodeURIComponent(unlockedCs);
    return "session_id=" + encodeURIComponent(sessionId)
      + "&funnel=" + encodeURIComponent(slug);
  }

  // Before the money. The section is the same article in the same place either
  // way; what changes is that there is no generating and no result, because
  // the thing that costs money has not been bought yet.
  function vizPre() {
    return !unlockedCs;
  }

  // What the reader already owns, shown back to them: the three colours their
  // choices produced and the fittings those choices ranked highest.
  //
  // Nothing here crosses the paid line, and the line is worth restating
  // because this is a new place to cross it. The dots are painted from the
  // `rgb` triple the funnel JSON carries — the free payload has no `hex` in it
  // at all — and the paint CODE is what the report is bought for, so no code
  // is written, no `swatch-hex` node is built, and the element chips carry
  // their label without the `spec` subline that belongs to the paid detail
  // view. What is on screen here is exactly what the free result page below
  // already shows.
  function yoursStrip(block) {
    var style = styleById(winnerStyleId);
    var colors = (((style || {}).reveals || {}).palette || {}).colors || [];
    // Five blocks and four thumbs. `pickElements` is the same picker the
    // Style Elements strip used, so the four are still the four this run
    // actually ranked highest — the strip is gone, the picker is not.
    colors = colors.slice(0, 5);
    var items = pickElements().slice(0, 4);
    if (!colors.length && !items.length) return null;

    var node = elm("div", "viz-yours");

    if (colors.length) {
      node.appendChild(elm("p", "viz-yours__label",
                           block.palette_label || "YOUR PALETTE"));
      var swatches = elm("ul", "viz-yours__colors");
      colors.forEach(function (c) {
        var li = elm("li", "viz-yours__color");
        li.style.backgroundColor = swatchColor(c);
        li.setAttribute("title", c.name || "");
        swatches.appendChild(li);
      });
      node.appendChild(swatches);
    }

    // Four materials, named and pictured, in the free form: the picture and
    // its label, never the `spec` subline that belongs to the paid detail view.
    //
    // The picture is a flat close-up of the surface — a `swatch` — and not the
    // room shot the quiz used. The quiz frames are whole kitchens, and a whole
    // kitchen shrunk to a 64px square is four or five materials, a window and
    // a worktop all at once, which at that size is mud. A close-up of the same
    // material is one thing at one scale, which is what the reader is being
    // shown: this is your brass, this is your concrete.
    //
    // `img` is still the fallback, so a funnel whose items carry no `swatch` —
    // /kitchen, or this one served from a JSON cached before the key existed —
    // renders exactly what it rendered before rather than four broken frames.
    if (items.length) {
      node.appendChild(elm("p", "viz-yours__label",
                           block.materials_label || "YOUR MATERIALS"));
      var grid = elm("ul", "viz-yours__items");
      items.forEach(function (item) {
        var li = elm("li", "viz-yours__item");
        var frame = elm("span", "viz-yours__thumb");
        var img = document.createElement("img");
        img.src = item.swatch || item.img;
        img.alt = "";
        // Lazy, the same as the elements strip these came from. The row is
        // below the fold on every phone the page is built for, and four
        // textures fetched before the style name has painted are four requests
        // competing with the thing the reader is waiting to read.
        img.loading = "lazy";
        img.draggable = false;
        frame.appendChild(img);
        li.appendChild(frame);
        li.appendChild(elm("span", "viz-yours__name", item.label || ""));
        grid.appendChild(li);
      });
      node.appendChild(grid);
    }

    if (block.yours_note) {
      node.appendChild(elm("p", "viz-yours__note", block.yours_note));
    }
    return node;
  }

  function placeVisualizer() {
    // `vizDead` and not `vizNode`: the free page rebuilds its report from
    // scratch, so a node that is no longer in the document is a node to
    // replace rather than a reason to stop.
    if (vizDead || !vizOn()) return;
    if (vizNode && vizNode.parentNode === el.report) return;
    var block = vizConfig();

    vizNode = elm("article", "section section-visualizer");
    vizNode.id = "visualizer";

    // The focused free page names nothing here. Directly above this are the
    // style name and its one-line description, and directly below is a strip
    // headed YOUR PALETTE over a row of the reader's own colours — a heading
    // saying "Your Kitchen, Transformed" and a paragraph explaining that a
    // photo becomes a picture sit between the reader and the two things that
    // make the same point by being true. A rule instead, which is the whole of
    // what the join needs. The paid report still opens with both: there it is
    // a document, and a document has a title.
    if (focusResult() && vizPre()) {
      vizNode.appendChild(ruleNode());
    } else {
      vizNode.appendChild(elm("h2", "section-title",
                              block.title || "Your Kitchen, Transformed"));
      if (block.intro) vizNode.appendChild(elm("p", "viz-intro", block.intro));
    }

    // What it costs, said before a photograph is asked for rather than after
    // one has been handed over. The upload moving ahead of the payment is only
    // fair if the price moved ahead of the upload.
    if (vizPre() && block.price_note) {
      // Held on `el` so the gate can take it down: "no price until a photo"
      // has to mean every price on the page, and this is one of them.
      el.vizPrice = elm("p", "viz-price", withPrice(block.price_note));
      vizNode.appendChild(el.vizPrice);
    }

    // Their own palette and their own fittings, directly above the box that
    // asks for a photograph. It is the answer to "what will it look like":
    // not a promise about the render, but the actual colours and materials
    // that go into it, which they picked themselves thirteen taps ago.
    if (vizPre()) {
      var yours = yoursStrip(block);
      if (yours) vizNode.appendChild(yours);
    }

    vizNode.appendChild(elm("div", "viz-body"));

    // First in the document, whatever else has already landed. Sections arrive
    // across several polls and this one is not one of them.
    el.report.insertBefore(vizNode, el.report.firstChild);
    observeSection(vizNode);

    // What state this reader is already in. Somebody who left mid-render and
    // came back through the link in their email must find the render, and
    // somebody who uploaded a photo yesterday must find the photo — not an
    // empty box offering to start again.
    if (!vizState) vizFetch("/api/visualizer/status?" + vizAuth());
    vizRender();
  }

  function vizBody() {
    return vizNode && vizNode.querySelector(".viz-body");
  }

  function vizRemove() {
    vizStopPoll();
    if (vizNode && vizNode.parentNode) vizNode.parentNode.removeChild(vizNode);
    // Retired for the life of the page. The free report re-renders and would
    // otherwise put back a section the server has just said is not on offer.
    vizDead = true;
    vizNode = null;
    vizState = null;
  }

  // Every server answer lands here. Draw, count, and keep polling only while
  // there is something to wait for.
  function vizApply(data) {
    vizState = data || null;
    var status = (data && data.status) || "none";
    // Held separately as well: `vizState` is rebuilt on every poll and the
    // consent control is rendered from other places too.
    if (data && data.country) readerCountry = data.country;
    renderConsent();

    if (vizUploading) {
      vizUploading = false;
      // Which side of the money it happened on. The same act before and after
      // a purchase is two different events, and one name for both would make
      // the whole point of moving the upload earlier unmeasurable.
      // `path` says how the photograph got here — the memory-safe bitmap
      // resize, the ordinary canvas, or raw off the camera. It is the only way
      // to see which of the three real devices actually take, which is the
      // question that started this.
      var phase = vizPre() ? "pre" : "post";
      track("viz_upload", null, {
        phase: phase,
        path: vizUploadPath || "raw"
      });

      // The signal the campaign is actually optimised against. At three
      // dollars the Purchase volume will not leave Meta's learning phase for
      // weeks, and a photograph of your own kitchen handed over before paying
      // is the highest-intent thing that happens here in any volume.
      //
      // Pre-purchase only. The same act after the money is somebody who has
      // already converted, and feeding those into the same event would teach
      // the campaign to find people who have already bought — worse than
      // sending nothing. Once a session, so replacing the photo does not
      // count twice.
      if (phase === "pre" && !pixelCartFired) {
        pixelCartFired = true;
        pixelTrack("AddToCart");
      }
    }
    if (status === "ready" && !vizSeen.ready) {
      vizSeen.ready = true;
      track("viz_ready");
    }
    if (status === "failed" && !vizSeen.failed) {
      vizSeen.failed = true;
      track("viz_failed");
    }
    // Armed again for the next round, so a regenerate that fails is counted.
    if (status === "generating") vizSeen = {};

    vizRender();
    // The paid render, and the one that happens before the money. Both are a
    // picture being made while somebody watches, and both stop the poll the
    // moment there is nothing left to wait for.
    if (status === "generating" || vizTeaserWorking()) vizPoll();
    else vizStopPoll();
  }

  // Whether the locked panel is a render in progress rather than a picture.
  // Absent on a funnel with the flag off, and absent from an engine.js reading
  // a server that has not been deployed yet, so both fall through to the blur.
  function vizTeaserWorking() {
    return !!vizState && vizState.teaser === "working";
  }

  function vizTeaserReady() {
    return !!vizState && vizState.teaser === "ready" && !!vizState.teaser_url;
  }

  function vizPoll() {
    if (vizTimer) return;
    vizTimer = setInterval(function () {
      if (vizBusy) return;
      vizFetch("/api/visualizer/status?" + vizAuth());
    }, VIZ_POLL_MS);
  }

  function vizStopPoll() {
    if (vizTimer) clearInterval(vizTimer);
    vizTimer = null;
    vizStopRotate();
  }

  // One request at a time. `body` is a FormData for the two POSTs and absent
  // for a poll.
  function vizFetch(url, body, onError) {
    if (vizBusy) return;
    vizBusy = true;
    fetch(url, body ? { method: "POST", body: body } : { cache: "no-store" })
      .then(function (r) {
        return r.json().then(function (data) {
          return { ok: r.ok, data: data };
        });
      })
      .then(function (res) {
        vizBusy = false;
        if (res.ok) { vizApply(res.data); return; }
        var code = (res.data && res.data.error) || "";

        // The server does not have this feature here — which, with the config
        // on a CDN and the code on the server, is exactly what the window
        // between a static deploy and a code deploy looks like. Take the
        // section out rather than offer a picker that would 404.
        //
        // Only on a poll, though. A section that vanishes the instant somebody
        // taps a photograph is worse than one that says what went wrong, so a
        // call with its own error handler gets routed to copy instead.
        if (!onError && DEAD.indexOf(code) !== -1) {
          vizRemove();
          return;
        }

        // Any other refusal carries its own sentence. Show it rather than a
        // generic failure: "you've used both" and "that isn't a photo" are
        // different things and the reader can act on exactly one of them.
        if (onError) onError((res.data && res.data.message) || "", code,
                             res.data);
        else vizApply(res.data && res.data.status ? res.data : vizState);
      })
      .catch(function () {
        vizBusy = false;
        // Nothing came back, or what came back was not JSON. Either way this
        // is the network class and emphatically not a reason to reach for
        // whatever copy happens to be the default.
        if (onError) onError("", "network");
      });
  }

  // --- what to say when an upload does not go through -----------------------

  // The four ways a photograph fails to arrive, in the reader's terms rather
  // than the server's. This exists because there was one fallback string for
  // every failure in the section, and it belonged to generation — so a photo
  // that was merely too big was answered with "Nothing was used up — try
  // again", which is true of a render and meaningless about an upload.
  //
  // Config wins if it carries the same keys, so this can move into the funnel
  // without a deploy; these are the defaults, not the only copy.
  // `{limit}` is filled from whatever the server actually refused it for, so
  // raising the cap is a config change rather than a copy edit — and so the
  // sentence can never name a number the server disagrees with.
  var UPLOAD_COPY = {
    size: "That photo is over {limit}MB — most phones can export a smaller "
      + "version, or try a different shot",
    format: "We couldn't read that photo — JPEG, PNG or HEIC please",
    session: "This link needs your own quiz first — take it in 2 minutes and "
      + "your photo slot will be ready",
    network: "Upload didn't go through — check your connection and try again"
  };

  var UPLOAD_LIMIT_FALLBACK = 20;

  // Which class a server code belongs to. Anything unrecognised is network,
  // because the honest thing to tell somebody about a failure we cannot name
  // is to try again — not to guess at a cause.
  var UPLOAD_CLASS = {
    too_large: "size",
    not_an_image: "format",
    wrong_format: "format",
    unreadable: "format",
    unavailable: "format",
    empty: "format",
    no_file: "format",
    unknown_session: "session",
    bad_token: "session",
    no_purchase: "session",
    not_paid: "session",
    no_visualizer: "session",
    no_funnel: "session"
  };

  function uploadCopy(code, data) {
    var block = vizConfig() || {};
    var set = block.upload_errors || {};
    var kind = UPLOAD_CLASS[code] || "network";
    var text = set[kind] || UPLOAD_COPY[kind];
    var bytes = data && data.limit_bytes;
    var mb = bytes ? Math.round(bytes / 1048576) : UPLOAD_LIMIT_FALLBACK;
    return String(text).replace(/\{limit\}/g, String(mb));
  }

  function vizRender() {
    var host = vizBody();
    if (!host) return;
    var block = vizConfig();
    var status = (vizState && vizState.status) || "none";

    host.textContent = "";

    // Whatever went wrong is said once, at the top, above whichever state the
    // reader is being put back into. A failure with no photo behind it — an
    // upload that was refused — leaves them at the picker with the reason
    // above it rather than at a picker that looks like it was never used.
    if (status === "failed" && vizState.message) {
      host.appendChild(elm("p", "viz-error", vizState.message));
    }

    var have = status === "uploaded" || (vizState && vizState.has_source);

    // Before the money there are two states and no more. Generating and ready
    // are not reachable here — the endpoint behind them takes a purchase token
    // and nothing else — so the pre-purchase branch is written as the two
    // states it actually has rather than as the paid machine with parts
    // switched off.
    if (vizPre()) {
      host.appendChild(have ? vizTeaser(block) : vizDrop(block));
      renderManifestRows();
      // The photo can arrive long after the offer rendered, and the bottom of
      // the page has to hear about it: this is what takes the gate down and
      // starts the wallet element.
      renderGate();
      return;
    }

    if (status === "generating") host.appendChild(vizWorking(block));
    else if (status === "ready") host.appendChild(vizResult(block));
    else if (have) host.appendChild(vizReady(block));
    else host.appendChild(vizDrop(block));

    if (status !== "generating") vizStopRotate();
  }

  // Their kitchen, and beside it the same photograph behind a lock.
  //
  // The blurred panel is their own picture rather than a stock frame or a grey
  // box, and that is the entire idea: what is being withheld is visibly theirs.
  // A placeholder anybody could have been shown withholds nothing.
  function vizTeaser(block) {
    var frag = document.createDocumentFragment();

    var pair = elm("div", "viz-pair viz-pair-teaser");

    // One shape for both halves, and it is the reader's own photograph's.
    //
    // The render comes back in one of three sizes the model will produce and
    // is cropped server-side to this ratio, so the two files agree — but the
    // box is set here regardless and before either picture has loaded, which
    // is what makes the wait, the teaser and the fallback blur all occupy
    // exactly the same rectangle. Nothing on this page moves when the render
    // lands.
    var before = elm("figure", "viz-half");
    var shot = vizImg(vizSourceUrl());
    shot.addEventListener("load", function () {
      if (shot.naturalWidth && shot.naturalHeight) {
        pair.style.setProperty(
          "--viz-ratio",
          String(Math.round(shot.naturalWidth / shot.naturalHeight * 1000)
                 / 1000));
      }
    });
    // The same wrapper the locked half uses, so the two media boxes are the
    // same element under the same rule rather than two things kept in step by
    // hand. The wash and the lock belong to the locked one and are turned off
    // here by the modifier.
    var frame = elm("div", "viz-shade is-plain");
    frame.appendChild(shot);
    before.appendChild(frame);
    before.appendChild(elm("figcaption", "viz-caption",
                           block.before_label_pre || block.before_label
                           || "Your kitchen"));
    pair.appendChild(before);

    var after = elm("figure", "viz-half is-locked");
    after.appendChild(vizLockedBody(block));
    after.appendChild(elm("figcaption", "viz-caption",
                          fillHook(block.locked_label
                                   || "Your {style} transformation",
                                   hookWordsFor(styleById(winnerStyleId)))));
    // The whole panel asks the same question the offer answers, so touching
    // any of it goes there. `focusCta` and not `scrollToCommerce`: on a funnel
    // whose offer is still on its own screen the commerce block is hidden and
    // scrolling to it does nothing, which would make the lock a dead end.
    after.addEventListener("click", focusCta);
    pair.appendChild(after);

    frag.appendChild(pair);

    // The bridge from the locked panel to the offer.
    //
    // This is the one moment on the page where the reader can see what they do
    // not have: their own kitchen beside their own kitchen behind a lock. The
    // block that sells it is a screen and a half further down, and asking
    // somebody at the peak of wanting a thing to go and find the button is
    // asking them to cool off on the way. It takes no money and starts no
    // checkout — it scrolls, exactly as the panel's own tap does.
    //
    // Only ever when there is a photograph. `vizTeaser` is already the
    // photo-present branch, but the check is written out rather than inferred:
    // with nothing uploaded there is nothing to unlock, and the foot of the
    // page is already asking for the photograph in its own words. Read from
    // `vizState` and not from `gateUp`, because `vizRender` builds this before
    // it calls `renderGate` and the flag is one render stale here.
    // What unlocking actually sends, between the pictures and the button.
    //
    // It was a paragraph under the CTA, which is the wrong side of it: the
    // reader decides at the button, and the answer to "what am I paying for"
    // has to arrive before the question does. Two rows rather than a sentence
    // because there are two things and a reader scanning sees two.
    frag.appendChild(vizDeliver(block));

    var teaserCta = ((cfg && cfg.checkout) || {}).teaser_cta;
    if (teaserCta && vizHasPhoto()) {
      frag.appendChild(vizButton("viz-go viz-go--teaser", teaserCta,
                                 teaserTap));
    } else if (block.locked_cta) {
      // The older key, for a funnel that still carries it. Never both: two
      // full-width accent buttons under one pair of panels is two offers.
      frag.appendChild(vizButton("viz-go", block.locked_cta, focusCta));
    }

    vizWatchTeaser(pair);
    return frag;
  }

  // The two rows, and the reason they are built even when they are not shown.
  //
  // "This image, unblurred" refers to a picture. While the render is still
  // running there is no picture, and if it failed what is on screen is the
  // reader's own photograph behind a blur — in both cases the rows would be
  // pointing at nothing. So they are hidden in both.
  //
  // Hidden, not absent. The block is in the document from the first render
  // with its height reserved, and `visibility` is what turns it on: the pay
  // button underneath must be in the same place before and after a render that
  // lands twenty to thirty seconds after the reader started reading, because
  // the one thing worse than a slow picture is a button that moves under a
  // thumb already travelling towards it.
  function vizDeliver(block) {
    var box = elm("div", "viz-deliver");
    var rows = block.deliver_rows || [];
    if (block.deliver_label) {
      box.appendChild(elm("p", "viz-deliver__label", block.deliver_label));
    }
    var list = elm("ul", "viz-deliver__list");
    rows.forEach(function (row, i) {
      if (!row || !row.text) return;
      var li = elm("li", "viz-deliver__row");
      li.appendChild(icon(i === 0 ? "image" : "doc", "viz-deliver__icon"));
      var text = elm("span", "viz-deliver__text");
      // The accent lands on the half that is the promise. Bolding the whole
      // line emphasises nothing; bolding "unblurred, full resolution" is the
      // reason the line is there.
      fillAccent(text, row.text, row.accent || "");
      li.appendChild(text);
      list.appendChild(li);
    });
    box.appendChild(list);
    box.classList.toggle("is-on", vizTeaserReady());
    el.vizDeliver = box;
    return box;
  }

  // What the teaser button does, and the whole of it.
  //
  // `payIntent` is the point. `paywall_view` carries how the reader got to the
  // offer, and the observer that fires it cannot tell a scroll from a scroll
  // somebody asked for — so whichever deliberate act preceded it names itself
  // first. Filed under `scroll`, or under `mid_cta` because that is the nearest
  // existing word, this button's entire contribution would be invisible: the
  // question it exists to answer is how many people the panels send down, and
  // that number cannot be read out of a bucket it shares.
  //
  // No event of its own. `mid_cta` has one because it was the only prompt on a
  // page of blurred sections and its tap rate was the thing being measured;
  // here the tap and the arrival are the same act a second apart, and
  // `paywall_view` with this src already counts it.
  function teaserTap() {
    payIntent = "teaser_cta";
    scrollToCommerce();
  }

  // What stands in the right-hand panel before the money, in the three states
  // it can be in.
  //
  // The one that is new is the middle one: a real render of their kitchen with
  // half of it blurred. It is a file the server built and downscaled, not a
  // CSS filter over the real image — a filter is a decoration over bytes the
  // browser already has, and anybody who opens the network tab has the picture
  // unblurred. Here the blur is in the pixels and the pixels are a seventh of
  // the render, so holding the file is not holding the product.
  //
  // The other two are the wait, and the blur the page has always shown when
  // there is no render to show. Every one of them is the same box, because the
  // reader must not have the page move under their thumb when the picture
  // lands.
  function vizLockedBody(block) {
    var shade = elm("div", "viz-shade");

    if (vizTeaserReady()) {
      var real = vizImg(vizState.teaser_url);
      real.className = "viz-img viz-img--teaser";
      // A courtesy and nothing more, and worth saying so plainly: neither of
      // these stops anybody who wants the file, and neither is meant to. What
      // protects the render is that this is not the render.
      real.draggable = false;
      real.setAttribute("oncontextmenu", "return false");
      shade.classList.add("is-real");
      shade.appendChild(real);
      shade.addEventListener("click", focusCta);
      return shade;
    }

    if (vizTeaserWorking()) {
      shade.classList.add("is-working");
      var box = elm("div", "viz-wait");
      box.appendChild(elm("span", "viz-wait__spin"));
      box.appendChild(elm("p", "viz-wait__title",
                          block.preparing_title || "Preparing your kitchen"));
      box.appendChild(elm("p", "viz-wait__note",
                          block.preparing_note || ""));
      shade.appendChild(box);
      return shade;
    }

    // The fallback, unchanged: their own photograph behind a blur and a lock.
    // Reached when the funnel does not render early, when the render failed,
    // and when this engine.js is talking to a server that predates any of it.
    var blurred = vizImg(vizSourceUrl());
    blurred.className = "viz-img is-blurred";
    shade.appendChild(blurred);
    shade.appendChild(icon("lock", "viz-lock"));
    return shade;
  }

  function vizImg(src) {
    var img = document.createElement("img");
    img.className = "viz-img";
    img.src = src;
    img.alt = "";
    return img;
  }

  // The offer reaching the reader, counted once. It is the visualizer's
  // `paywall_view`: without it, "uploaded a photo" and "was actually shown
  // what they would get" are the same number, and they are not.
  function vizWatchTeaser(node) {
    if (vizTeaserSeen) return;
    var fire = function () {
      if (vizTeaserSeen) return;
      vizTeaserSeen = true;
      track("viz_teaser_view");
    };
    if (!window.IntersectionObserver) { fire(); return; }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        io.disconnect();
        fire();
      });
    }, { threshold: 0.4 });
    io.observe(node);
  }

  // The line the reader is told before they take the photograph. Almost every
  // disappointing render is a photograph problem — too close, lights off, half
  // the room out of frame — so it is shown next to the button on every state
  // that can still lead to a generation, not once at the start.
  function vizGuide(block) {
    return elm("p", "viz-guide", block.guidance || "");
  }

  function vizButton(cls, label, onTap) {
    var btn = elm("button", cls, label);
    btn.type = "button";
    btn.addEventListener("click", onTap);
    return btn;
  }

  function vizFileInput(block) {
    var input = document.createElement("input");
    input.type = "file";
    // Everything the OS is willing to call an image, and no narrower.
    //
    // This used to name jpeg and png, which quietly greyed out most of the
    // camera roll on an iPhone: the camera writes HEIC and a portrait or
    // burst shot is an MPO, and neither matches either type. A phone's own
    // idea of what it took is more reliable than a list maintained here, and
    // the server decodes the bytes anyway — the accept attribute is a filter
    // on a picker, never a check.
    //
    // Still `image/*` and not omitted: on Android an unrestricted input
    // offers every file on the device.
    input.accept = "image/*";
    input.className = "viz-file";
    input.addEventListener("change", function () {
      var file = input.files && input.files[0];
      if (file) vizUpload(file);
    });
    return input;
  }

  function vizDrop(block) {
    var zone = elm("label", "viz-drop");
    zone.appendChild(elm("span", "viz-drop-mark", "＋"));
    zone.appendChild(elm("span", "viz-drop-cta",
                         block.upload_cta || "Choose a photo"));
    zone.appendChild(vizGuide(block));
    zone.appendChild(vizFileInput(block));

    // What happens to the photograph, answered before it is asked. It is the
    // first thing anybody sensible wonders before handing over a picture of
    // the inside of their house, and it belongs inside the tap target so it
    // cannot be scrolled past on the way to the picker.
    if (block.privacy_note) {
      zone.appendChild(elm("p", "viz-privacy", block.privacy_note));
    }
    return zone;
  }

  function vizReady(block) {
    var frag = document.createDocumentFragment();

    var figure = elm("figure", "viz-shot");
    var img = document.createElement("img");
    img.className = "viz-img";
    img.src = vizSourceUrl();
    img.alt = "";
    figure.appendChild(img);
    frag.appendChild(figure);

    // Two different reasons the button does not come back: every credit is
    // spent, or the server has stopped accepting attempts for this purchase.
    // Both end the same way, and in both cases offering a button the server
    // would refuse is worse than not offering one.
    var spent = (vizState && vizState.remaining) === 0;
    var retriable = !(vizState && vizState.retriable === false);
    if (spent || !retriable) {
      frag.appendChild(elm("p", "viz-spent",
                           (vizState && vizState.message)
                           || block.spent_note || ""));
    } else {
      frag.appendChild(vizButton("viz-go",
                                 block.generate_cta || "Transform my kitchen",
                                 vizGenerate));
      frag.appendChild(vizGuide(block));
    }

    var swap = elm("label", "viz-replace",
                   block.replace_cta || "Use a different photo");
    swap.appendChild(vizFileInput(block));
    frag.appendChild(swap);
    return frag;
  }

  function vizWorking(block) {
    var card = elm("div", "viz-working");
    card.setAttribute("aria-live", "polite");
    card.appendChild(elm("span", "viz-shimmer"));
    card.appendChild(elm("p", "viz-working-title",
                         block.generating_title || "Redrawing your kitchen…"));
    card.appendChild(elm("p", "viz-working-text", vizLines(block)[0]));
    if (block.generating_note) {
      card.appendChild(elm("p", "viz-note", block.generating_note));
    }
    vizStartRotate(card, block);
    return card;
  }

  function vizLines(block) {
    var lines = block && block.generating_messages;
    return (lines && lines.length) ? lines : ["Working…"];
  }

  var vizRotateTimer = null;

  function vizStartRotate(card, block) {
    vizStopRotate();
    if (prefersReducedMotion()) return;
    var lines = vizLines(block);
    var i = 0;
    vizRotateTimer = setInterval(function () {
      i = (i + 1) % lines.length;
      var text = card.querySelector(".viz-working-text");
      if (text) text.textContent = lines[i];
    }, VIZ_ROTATE_MS);
  }

  function vizStopRotate() {
    if (vizRotateTimer) clearInterval(vizRotateTimer);
    vizRotateTimer = null;
  }

  function vizSourceUrl() {
    return "/api/visualizer/image?which=source&" + vizAuth();
  }

  function vizResult(block) {
    // Their kitchen has been drawn. Third step, and the only place it is
    // reached — the teaser and the working state are still the second.
    markJourney(2);
    var frag = document.createDocumentFragment();

    var pair = elm("div", "viz-pair");
    pair.appendChild(vizFigure(vizSourceUrl(),
                               block.before_label || "Your kitchen", false));
    pair.appendChild(vizFigure(vizState.url,
                               block.after_label || "In your style", true));
    frag.appendChild(pair);

    if (block.enlarge_hint) {
      frag.appendChild(elm("p", "viz-hint", block.enlarge_hint));
    }

    var actions = elm("div", "viz-actions");
    // A real link rather than a scripted save: the file is same-origin and the
    // route sets the disposition, so the browser's own download does the work.
    var save = elm("a", "viz-download", block.download_cta || "Download");
    save.href = vizState.url + "&download=1";
    save.setAttribute("download", "my-kitchen-transformed.jpg");
    actions.appendChild(save);

    if ((vizState.remaining || 0) > 0) {
      actions.appendChild(vizButton("viz-again",
                                    block.regenerate_cta || "Regenerate once",
                                    vizGenerate));
    }
    frag.appendChild(actions);

    if (!(vizState.remaining > 0) && block.spent_note) {
      frag.appendChild(elm("p", "viz-spent", block.spent_note));
    }
    return frag;
  }

  function vizFigure(src, caption, after) {
    var figure = elm("figure", "viz-half" + (after ? " is-after" : ""));
    var img = document.createElement("img");
    img.className = "viz-img";
    img.src = src;
    img.alt = "";
    figure.appendChild(img);
    figure.appendChild(elm("figcaption", "viz-caption", caption));
    figure.addEventListener("click", function () { vizEnlarge(src, caption); });
    return figure;
  }

  function vizEnlarge(src, caption) {
    if (el.vizBox && el.vizBox.parentNode) {
      el.vizBox.parentNode.removeChild(el.vizBox);
    }
    var box = boxShell("vizBox", "viz-box", caption || "");
    var shell = elm("div", "lightbox-shell");
    var figure = elm("div", "sample-figure");
    var img = document.createElement("img");
    img.className = "sample-img";
    img.src = src;
    img.alt = "";
    figure.appendChild(img);
    shell.appendChild(figure);
    if (caption) shell.appendChild(elm("p", "sample-caption", caption));
    shell.appendChild(boxClose("vizBox"));
    box.appendChild(shell);
    document.body.appendChild(box);
    el.vizBox = box;
    showBox("vizBox");
  }

  // --- shrinking the photograph before it goes anywhere ---------------------

  // The longest side we send. The model reads about a megapixel and the server
  // keeps 1536, so 2048 is already more than anything downstream wants — it is
  // the point where sending more stops buying anything.
  var VIZ_UPLOAD_EDGE = 2048;
  var VIZ_UPLOAD_QUALITY = 0.85;

  // Draw it, then send what was drawn.
  //
  // This is the fix for a whole class of failure rather than a saving. A 48MP
  // Pro sensor writes HEICs past any sane request ceiling, and it writes
  // container variants a server-side decoder may not know yet — but the phone
  // that took the photograph can always display it, and anything the browser
  // can display it can draw. What leaves the device is therefore an ordinary
  // JPEG of a few hundred kilobytes, whatever exotic thing came off the
  // sensor, and it goes over mobile data in a fraction of the time.
  //
  // Three ways down, in order of how much they can be trusted with a very
  // large file:
  //
  //   bitmap — createImageBitmap with resize options. The decoder scales
  //            while decoding, so a 108MP JPEG never exists full-size in
  //            memory. This is the one that matters in an in-app WebView on
  //            a mid-range Android, where the other path runs out of memory.
  //   canvas — Image plus drawImage. Correct everywhere, allocates the whole
  //            source bitmap first.
  //   raw    — send the file exactly as the camera wrote it, and let the
  //            server decode it. The path that worked before any of this.
  //
  // Which one a device actually took is reported with the upload, because the
  // whole reason this exists is that we could not see what real phones were
  // doing.

  function vizLog(message) {
    // Console as well as telemetry: the telemetry says which path, the console
    // says why, and only one of them is available while somebody is holding
    // the phone that is failing.
    try {
      if (window.console && console.log) console.log("[viz] " + message);
    } catch (e) { /* a console that throws is not worth an upload */ }
  }

  // A canvas to a JPEG blob. `toBlob` is the right call and some older Android
  // WebViews either lack it or hand back null, so `toDataURL` is kept as the
  // way out — it is synchronous and wasteful and it works.
  function vizCanvasBlob(canvas, done) {
    function fromDataUrl() {
      try {
        var url = canvas.toDataURL("image/jpeg", VIZ_UPLOAD_QUALITY);
        var comma = url.indexOf(",");
        if (comma < 0 || url.indexOf("image/jpeg") < 0) { done(null); return; }
        var binary = atob(url.slice(comma + 1));
        var bytes = new Uint8Array(binary.length);
        for (var i = 0; i < binary.length; i++) {
          bytes[i] = binary.charCodeAt(i);
        }
        done(new Blob([bytes], { type: "image/jpeg" }));
      } catch (e) {
        done(null);
      }
    }

    if (!canvas.toBlob) {
      vizLog("toBlob missing — using toDataURL");
      fromDataUrl();
      return;
    }
    try {
      canvas.toBlob(function (blob) {
        if (blob) { done(blob); return; }
        // Documented WebView behaviour, not a theoretical branch.
        vizLog("toBlob returned null — using toDataURL");
        fromDataUrl();
      }, "image/jpeg", VIZ_UPLOAD_QUALITY);
    } catch (e) {
      vizLog("toBlob threw — using toDataURL");
      fromDataUrl();
    }
  }

  // Paint a decoded source onto a canvas at the target size and encode it.
  function vizEncode(source, w, h, how, finish) {
    var scale = Math.min(1, VIZ_UPLOAD_EDGE / Math.max(w, h));
    var canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(w * scale));
    canvas.height = Math.max(1, Math.round(h * scale));

    var ctx = canvas.getContext && canvas.getContext("2d");
    if (!ctx) { finish(null, "raw", "no 2d context"); return; }
    ctx.drawImage(source, 0, 0, canvas.width, canvas.height);

    vizCanvasBlob(canvas, function (blob) {
      if (!blob) { finish(null, "raw", "no blob from canvas"); return; }
      finish(blob, how);
    });
  }

  // The memory-safe one. `resizeWidth` alone preserves the aspect ratio, so a
  // landscape photo is done in a single decode; a portrait one comes back
  // taller than the cap and is decoded again bounded on the other axis. Both
  // decodes are scaled, so neither holds the full-size image.
  //
  // One known cost: a photograph already narrower than the cap is resampled
  // *up* to it, because there is no way to learn the source size without
  // decoding something. It costs a slightly larger upload on small images and
  // nothing on the phone photographs this is for, all of which are wider.
  function vizBitmap(file, finish) {
    if (!window.createImageBitmap || !window.Promise) {
      finish(null, "canvas", "no createImageBitmap");
      return;
    }
    var opts = { resizeWidth: VIZ_UPLOAD_EDGE, resizeQuality: "high" };
    var first = null;
    try {
      createImageBitmap(file, opts).then(function (bmp) {
        first = bmp;
        if (bmp.height <= VIZ_UPLOAD_EDGE) return bmp;
        var narrow = Math.max(
          1, Math.round(VIZ_UPLOAD_EDGE * bmp.width / bmp.height));
        return createImageBitmap(file, {
          resizeWidth: narrow, resizeHeight: VIZ_UPLOAD_EDGE,
          resizeQuality: "high"
        });
      }).then(function (bmp) {
        if (first && first !== bmp && first.close) first.close();
        vizEncode(bmp, bmp.width, bmp.height, "bitmap",
                  function (blob, how, why) {
                    if (bmp.close) bmp.close();
                    finish(blob, how, why);
                  });
      })["catch"](function (err) {
        if (first && first.close) first.close();
        finish(null, "canvas", "createImageBitmap failed: " + err);
      });
    } catch (e) {
      finish(null, "canvas", "createImageBitmap threw");
    }
  }

  // The everywhere-else one.
  function vizCanvas(file, finish) {
    if (!window.URL || !URL.createObjectURL) {
      finish(null, "raw", "no object URLs");
      return;
    }
    var url;
    var img = new Image();
    // A photograph that will not decode in a reasonable time is one we stop
    // waiting on rather than one that leaves the reader with a dead picker.
    var timer = setTimeout(function () {
      finish(null, "raw", "decode timed out");
    }, 15000);

    function cleanup() {
      clearTimeout(timer);
      if (url) { try { URL.revokeObjectURL(url); } catch (e) { /* fine */ } }
    }

    img.onload = function () {
      cleanup();
      var w = img.naturalWidth || img.width;
      var h = img.naturalHeight || img.height;
      if (!w || !h) { finish(null, "raw", "no dimensions"); return; }
      try {
        vizEncode(img, w, h, "canvas", finish);
      } catch (e) {
        finish(null, "raw", "draw failed");
      }
    };
    img.onerror = function () {
      cleanup();
      finish(null, "raw", "the browser could not decode it");
    };

    try {
      url = URL.createObjectURL(file);
      img.src = url;
    } catch (e) {
      cleanup();
      finish(null, "raw", "could not make an object URL");
    }
  }

  function vizShrink(file, done) {
    var settled = false;

    function land(out, how) {
      if (settled) return;
      settled = true;
      vizLog("upload path: " + how
             + (out && out.size ? " (" + Math.round(out.size / 1024) + "KB)"
                                : ""));
      done(out || file, how);
    }

    vizBitmap(file, function (blob, how, why) {
      if (blob) { land(blob, how); return; }
      if (why) vizLog("bitmap path unavailable — " + why);
      if (how === "raw") { land(null, "raw"); return; }

      vizCanvas(file, function (blob2, how2, why2) {
        if (blob2) { land(blob2, how2); return; }
        if (why2) vizLog("canvas path unavailable — " + why2);
        land(null, "raw");
      });
    });
  }

  function vizUpload(file) {
    if (vizBusy) return;
    var host = vizBody();
    if (host) {
      host.textContent = "";
      host.appendChild(elm("p", "viz-note", "Uploading…"));
    }
    // Held so the picker cannot fire twice while the canvas is working — the
    // request itself has not started yet, so `vizBusy` is not set for it.
    vizBusy = true;
    vizShrink(file, function (payload, how) {
      vizBusy = false;
      var body = new FormData();
      // A filename is required for the part to arrive as a file rather than a
      // field. Ours, not theirs: what the photograph was called on their phone
      // is not something this server needs to be told.
      body.append("photo", payload, "upload.jpg");

      // Which result these thirteen taps produced, and which four fittings the
      // reader was shown for it.
      //
      // The server cannot work either out. A session has no row and no report
      // — that is deliberate, a table of people who did not buy is a table we
      // decided not to keep — so the winner exists only here, and without it
      // `_pre_purchase_content` finds no style and every pre-purchase render
      // fails `no_prompt` before an image is ever asked for. Which is exactly
      // what was happening.
      //
      // `winnerStyleId` and not a name or a label: it is the same expression
      // `orderPayload` sends as `result_style` at checkout, from the same
      // variable, so the render and the purchase cannot come to disagree about
      // which style this reader got. Both are re-validated server-side against
      // the funnel's own list — the browser makes a claim, the server decides.
      //
      // Only when there is one. On a paid page opened from an emailed link
      // there was no quiz run in this tab, `winnerStyleId` is null, and
      // appending it would send the string "null" for the server to reject.
      if (winnerStyleId) body.append("style", winnerStyleId);
      // The same four, and the same slice, that `yoursStrip` draws under YOUR
      // MATERIALS — `pickElements` returns six and the row shows four, so
      // sending six would render surfaces the reader was never shown.
      var shown = pickElements().slice(0, 4).map(function (item) {
        return item.id;
      });
      if (shown.length) body.append("elements", shown.join(","));
      // Counted when the server has it, not when the picker closed. A photo
      // the server refused is a `viz_failed`, and counting it as both would
      // make the upload-to-generate rate read better than it is.
      vizUploading = true;
      vizUploadPath = how;
      vizFetch("/api/visualizer/upload?" + vizAuth(), body, vizUploadFailed);
    });
  }

  function vizGenerate() {
    if (vizBusy) return;
    track("viz_generate");
    // Straight into the working state rather than waiting for the answer: the
    // request takes a moment and a button that stays idle gets pressed twice.
    // The server would refuse the second one, but the reader would not know
    // that.
    vizState = { status: "generating",
                 remaining: (vizState && vizState.remaining) || 0 };
    vizRender();
    vizFetch("/api/visualizer/generate?" + vizAuth(), new FormData(), vizFailed);
  }

  // A refusal the server explained, or a network failure it could not. Either
  // way the section goes back to a state the reader can act from — with the
  // photo still on the server, so nothing has to be chosen twice.
  // A generation that did not produce an image. `error_text` is this one's
  // copy and only this one's — it is the sentence that says the credit was not
  // spent, which is a fact about renders and nothing at all about uploads.
  function vizFailed(message) {
    vizShowFailure(message
                   || (vizConfig() || {}).error_text
                   || "That didn't work. Try again.");
  }

  // A photograph that did not arrive. Its own copy set, keyed on what the
  // server actually said, because the four ways this fails need four different
  // things from the reader: a smaller file, a different file, a quiz, or
  // another try in a minute.
  function vizUploadFailed(message, code, data) {
    // The server's own sentence wins where it has one worth showing — it knows
    // things the class does not, like which of two ceilings was hit — but a
    // code we can name beats a generic message, and beats silence outright.
    var mapped = uploadCopy(code, data);
    vizShowFailure(UPLOAD_CLASS[code] ? mapped : (message || mapped));
  }

  function vizShowFailure(message) {
    vizUploading = false;
    vizState = {
      status: "failed",
      message: message,
      remaining: (vizState && vizState.remaining) || 1,
      has_source: !!(vizState && vizState.has_source),
      retriable: true
    };
    if (!vizSeen.failed) { vizSeen.failed = true; track("viz_failed"); }
    vizRender();
    vizStopPoll();
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
      // A funnel with its own result page hid this container and put its own
      // page in front of it. The paid report is drawn into it by every funnel
      // — that path is never delegated — so it comes back, and the module's
      // page goes. Unreachable today, because both ways of paying navigate
      // and the reader returns on a fresh load: it is here so that the day
      // one of them confirms in place, the report is not written into a
      // hidden div.
      el.report.hidden = false;
      if (el.moduleRoot) el.moduleRoot.hidden = true;
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
    // Held for the visualizer, which needs the same token on every call it
    // makes. Nothing else on the unlocked path keeps it: the report poller is
    // handed it as an argument and recurses with it.
    unlockedCs = cs;
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

  // Whether the withdrawal-right waiver has to be shown to this reader.
  //
  // It is a legal control, so the interesting case is the one where we do not
  // know: an absent country header, a proxy, a reader Cloudflare files as XX.
  // Every one of those SHOWS the box. The only way it comes off the page is a
  // country the config names explicitly, which makes turning it off somewhere
  // a deliberate edit by somebody who has decided that country does not
  // require it — never something that happens because a header went missing.
  //
  // In the UK the Consumer Contracts Regulations 2013 need the waiver before
  // instant delivery. In Canada nothing equivalent applies. The list is config
  // for that reason: it is a legal judgement, not a technical one.
  function consentRequired() {
    var country = (vizState && vizState.country) || readerCountry;
    if (!country) return true;
    var skip = ((cfg && cfg.checkout) || {}).consent_skip_countries;
    if (!Array.isArray(skip)) return true;
    for (var i = 0; i < skip.length; i++) {
      if (String(skip[i]).toUpperCase() === country) return false;
    }
    return true;
  }

  // Shown, or taken off the page and treated as satisfied. Never left on the
  // page disabled, and never hidden while still gating the button — a control
  // somebody cannot see and cannot pass is a page that looks broken.
  function renderConsent() {
    if (!el.withdrawal) return;
    var need = consentRequired();
    el.withdrawal.classList.toggle("is-off", !need);
    if (!need) el.withdrawalCheck.checked = true;
    updatePayButton();
  }

  function updatePayButton() {
    var ok = el.withdrawalCheck.checked && PAYMENTS_ENABLED;
    el.payButton.disabled = !ok;
    el.payButton.textContent = PAYMENTS_ENABLED
      ? withPrice(cfg.checkout.cta_label || cfg.pricing.cta || "Unlock")
      : "Payments coming in Phase 1b";
    // The other button the same box gates, when there is one. A no-op on every
    // funnel without the express flag, and on this one until the element says
    // it has a wallet to offer.
    xpConsent();
  }

  // Everything a payment needs, and the same body for both ways of starting
  // one: `/api/checkout` and `/api/payment-intent` validate through the same
  // function server-side, so there is one shape here rather than two that
  // agree today. No amount in it — the price is read from the funnel on the
  // server, and the client has never been able to say what anything costs.
  function orderPayload() {
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

    // The click identifiers travel with the order because this is the last
    // moment the browser is involved. The purchase itself is reported by the
    // server after Stripe confirms it, long after this tab may be gone, and
    // without these it would arrive unattributed. The server re-validates
    // them and drops anything that is not a plain identifier.
    var ids = metaIds();
    for (var k in ids) payload[k] = ids[k];
    return payload;
  }

  // The payment attempt itself, and the only place that name belongs. Fired
  // before the guard rather than after it: what this counts is somebody
  // pressing the button that takes their money, and a run that then bails on
  // an unchecked box is a tap that happened. The guard is unreachable from
  // the UI anyway — the button is disabled while the box is clear, and a
  // disabled button dispatches no click.
  function startCheckout() {
    track("pay_tap", null, { method: "redirect" });
    // Meta's name for the same moment. InitiateCheckout already fires when the
    // offer reaches somebody; this is the narrower signal Meta optimises
    // against — the tap that starts paying. The wallet button fires it too,
    // from its own click handler: they are two buttons now, and the one the
    // reader was given is not a thing Meta should be able to tell apart.
    firePayPixel();
    if (!PAYMENTS_ENABLED || !el.withdrawalCheck.checked) return;

    el.payError.hidden = true;
    el.payButton.disabled = true;
    el.payButton.textContent = "Redirecting...";

    fetch("/api/checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(orderPayload())
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

  // --- express checkout -----------------------------------------------------

  // A wallet button on the paywall — Apple Pay, Google Pay, Link — instead of
  // a trip to Stripe's hosted page. The sheet opens over this page, the reader
  // authorises with a thumb, and nobody types a card number.
  //
  // Everything below is written around one fact: this can fail in more ways
  // than the redirect can. Stripe.js is a third-party script on a network we
  // do not control, the intent is a round trip, the element decides for itself
  // whether this device has a wallet at all, and any of the three can simply
  // not answer. A dead paywall costs more than a lost wallet, so every one of
  // those endings is the same ending — today's button, calling /api/checkout,
  // exactly as it always has.
  var XP_SRC = "https://js.stripe.com/v3/";

  // The whole budget, from the first byte requested to the element saying it
  // is ready. Not per-step: the reader is looking at a placeholder for the
  // duration, and what they are owed is a button inside three seconds, not a
  // fair share of the wait for each thing that has to happen.
  var XP_DEADLINE_MS = 3000;

  // Stripe's own ceiling for the wallet button is 55px. The block reserves the
  // pay button's full height regardless, and centres whatever it gets inside
  // it, so this number changes what the button looks like and never what the
  // page measures.
  var XP_BUTTON_HEIGHT = 55;

  // What the sheet has to ask the wallet for, handed to `resolve` when the
  // button is tapped.
  //
  // `emailRequired` is the whole of this fix. Apple Pay and Google Pay do NOT
  // share the buyer's email address unless asked — the sheet simply never
  // shows the field — so a purchase went through, the charge was read, the
  // charge carried no email, and the report was generated for somebody who
  // then received nothing. The hosted Checkout page always collected an email;
  // the wallet only collects it on request, and nobody made the request.
  //
  // `billingAddressRequired` is stated rather than left to its default. The
  // default is true today, but only while no shipping option is passed — it
  // flips to false the moment one is — and `purchases.country` is fed from
  // this address. A column that empties itself because an unrelated option was
  // added later is not a thing to leave to a default.
  //
  // Nothing else is asked for. No phone: nothing stores one. No shipping:
  // there is nothing to ship.
  var XP_COLLECT = { emailRequired: true, billingAddressRequired: true };

  // The fields Stripe accepts on `billing_details`, and the only ones that
  // travel. An allowlist rather than a pass-through: whatever a future wallet
  // decides to put in that object, what leaves this page is these keys or
  // nothing.
  var XP_BILLING_KEYS = ["name", "email", "phone"];
  var XP_ADDRESS_KEYS = ["line1", "line2", "city", "state", "postal_code",
                         "country"];

  function expressOn() {
    return ((cfg && cfg.checkout) || {}).express === true;
  }

  // Config, not inference. The flag being absent — an older funnel JSON behind
  // the CDN, or /kitchen, which never gets this — means none of it runs and
  // no script is fetched from Stripe at all.
  function xpStart() {
    if (xpStarted || !expressOn() || !PAYMENTS_ENABLED) return;
    if (!el.payButton || !el.payButton.parentNode) return;
    xpStarted = true;

    xpReserve();

    // One deadline for the whole attempt, armed before anything is asked for.
    xpTimer = setTimeout(function () { xpFallback(); }, XP_DEADLINE_MS);

    // Both in flight at once. The script is the long pole and the intent is a
    // round trip to our own server; running them in sequence would spend the
    // budget twice for no reason.
    var stripeReady = false;
    var maker = null;

    function ready() {
      if (xpState !== "reserved") return;          // the deadline got here first
      if (!stripeReady || !xpIntent) return;
      if (!maker) { xpFallback(); return; }
      xpMount(maker);
    }

    xpLoadStripe(function (factory) {
      stripeReady = true;
      maker = factory;
      ready();
    });

    xpFetchIntent(function (intent) {
      if (!intent) { xpFallback(); return; }
      xpIntent = intent;
      ready();
    });
  }

  // The reserved state. The slot and the pay button are two children of one
  // grid cell, so the block is always as tall as the taller of them and
  // nothing below it can move when the choice is finally made. That is
  // structural rather than two numbers kept in step by hand: whichever way
  // this ends, the button under the reader's thumb is where it already was.
  //
  // Called twice on the focused page and once anywhere else. The offer block
  // builds the slot as soon as it has a shape to build it in, so the space the
  // wallet will occupy is in the layout from the first paint; `xpStart` calls
  // it again when the render is done and there is finally something to sell,
  // and finds it already standing. Reserving is DOM and nothing else — no
  // script fetched, no intent created — which is the whole reason it can
  // happen before the attempt is allowed to.
  function xpReserve() {
    if (xpBlock) return;
    if (!expressOn() || !PAYMENTS_ENABLED) return;
    if (!el.payButton || !el.payButton.parentNode) return;

    var summary = xpSummary();

    xpBlock = elm("div", "xp");
    xpBlock.id = "xp";

    // Two layers, stacked the same way the block itself is. The element
    // mounts into the lower one and paints as soon as it is mounted — before
    // it has said whether it has a wallet to offer — so it stays invisible and
    // untouchable until it does, with the placeholder over it. Otherwise there
    // is a moment, however short, with two buttons on screen and the choice
    // between them not yet made.
    xpSlot = elm("div", "xp__slot");
    xpSlot.id = "xp-slot";
    xpMountNode = elm("div", "xp__mount xp__off");
    xpSlot.appendChild(xpMountNode);
    xpSlot.appendChild(elm("div", "xp__ghost"));

    var parent = el.payButton.parentNode;
    parent.insertBefore(xpBlock, el.payButton);
    if (summary) {
      // Into the price row's slot, not up against the button. It IS the price
      // block on the wallet path, and the order the block is read in — what
      // you get, what it costs, what it is not, the consent, the button — does
      // not change because the button turned out to be a wallet.
      if (el.price && el.price.parentNode) {
        el.price.parentNode.insertBefore(summary, el.price);
      } else {
        parent.insertBefore(summary, xpBlock);
      }
      el.xpSummary = summary;
      // Hidden until the element reports a wallet. `xpSet` owns which of the
      // two price blocks is showing from here on.
      summary.hidden = true;
    }

    // The button first, the slot over it: in one grid cell the later child
    // paints on top, and the wallet button has to be the one a thumb reaches.
    xpBlock.appendChild(el.payButton);
    xpBlock.appendChild(xpSlot);

    xpSet("reserved");
  }

  // Which of the two is live. Never both: the one that is not is invisible and
  // untouchable, and it stays in the grid so the block keeps its height.
  function xpSet(state) {
    xpState = state;
    var wallet = state === "reserved" || state === "wallet";
    xpSlot.classList.toggle("xp__off", !wallet);
    el.payButton.classList.toggle("xp__off", wallet);
    showSummary(state === "wallet");
    // "reserved" is the placeholder, which is not a control — it is the space
    // one will occupy while the question is still open. The answer is the
    // other two, and both of them arrive through here: `xpMount` sets wallet
    // when the element reports one, and `xpFallback` sets redirect on every
    // way the attempt can end without one — no wallet, no intent, Stripe.js
    // refusing to load, or the deadline.
    if (state === "wallet" || state === "redirect") payReady(state);
  }

  // What the reader was actually shown, once a session.
  //
  // `pay_tap` says which button took a payment, which is only ever answered by
  // somebody who pressed one — and the sessions that cost money are the ones
  // that did not. Twelve of them reached this block, spent minutes on it, and
  // left one tap between them; whether they were looking at an Apple Pay sheet
  // or a trip to a hosted page is the first thing worth knowing and nothing
  // recorded it.
  //
  // Deliberately not derived from the device. A phone can be an iPhone and
  // still have no card in the wallet, and an in-app browser can suppress the
  // button on hardware that would otherwise show it. What was shown and what
  // it was shown on are two facts, and this is only the first.
  function payReady(control) {
    // Nothing is showable while the block is held: what stands there is a
    // button asking for a photograph, or a line saying the picture is being
    // prepared, and counting either as a pay control would put a reader who
    // never reached the offer in the denominator of a rate about people who
    // did.
    if (payReadyFired || payHeld) return;
    payReadyFired = true;
    track("pay_ready", null, { control: control });
  }

  // Exactly one price block, whichever way the wallet check goes.
  //
  // The summary card belongs to the wallet path and only to it: a sheet opens
  // over this page showing an amount and nothing about what it is for, so the
  // naming has to happen here. The redirect path does not need it — Stripe's
  // own page names the product before anything is authorised — and running
  // both left "$7 $3 LAUNCH PRICE" printed twice, a hundred pixels apart.
  function showSummary(on) {
    if (el.xpSummary) el.xpSummary.hidden = !on;
    // The price row yields to the summary card and to nothing else. Without a
    // card there is no other price block, so hiding the row on a wallet answer
    // would leave a page selling something at no stated price.
    if (el.price) el.price.hidden = (on && !!el.xpSummary) || priceGated();
  }

  // Whether the price is being withheld until a photograph exists.
  function priceGated() {
    return gateUp && ((cfg && cfg.checkout) || {}).price_after_upload === true;
  }

  // Every ending that is not a wallet. Called from the deadline, from a script
  // that would not load, from an intent that did not come back, from an
  // element that errored, and from an element that reported no wallet on this
  // device — because to the reader they are one thing, which is that the
  // ordinary button is what they get.
  function xpFallback() {
    if (xpState === "redirect") return;
    if (xpTimer) { clearTimeout(xpTimer); xpTimer = null; }
    xpSet("redirect");
    updatePayButton();
  }

  function xpLoadStripe(done) {
    if (window.Stripe) { done(window.Stripe); return; }
    var tag = document.createElement("script");
    tag.src = XP_SRC;
    tag.async = true;
    tag.onload = function () { done(window.Stripe || null); };
    tag.onerror = function () { done(null); };
    try {
      document.head.appendChild(tag);
    } catch (e) {
      done(null);
    }
  }

  // The publishable key comes back with the intent it belongs to. It is the
  // only place it comes from: a key in the funnel JSON would be a second
  // source of truth for which Stripe account this funnel sells on, and the two
  // would eventually disagree about a live funnel.
  function xpFetchIntent(done) {
    fetch("/api/payment-intent", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(orderPayload())
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        done(data && data.client_secret && data.publishable_key ? data : null);
      })
      .catch(function () { done(null); });
  }

  function xpMount(maker) {
    var stripe;
    try {
      stripe = maker(xpIntent.publishable_key);
      xpElements = stripe.elements({ clientSecret: xpIntent.client_secret });
      var element = xpElements.create("expressCheckout", {
        buttonHeight: XP_BUTTON_HEIGHT
      });

      // The only place the choice is made, and it is made on what the element
      // reports rather than on anything guessed about the device beforehand.
      element.on("ready", function (ev) {
        var have = ev && ev.availablePaymentMethods;
        var any = false;
        for (var k in have) { if (have[k]) { any = true; break; } }
        if (!any) { xpFallback(); return; }
        xpShowWallet();
      });
      element.on("loaderror", function () { xpFallback(); });
      element.on("click", function (ev) { xpClick(ev); });
      element.on("cancel", function () { xpCancel(); });
      element.on("confirm", function (ev) { xpConfirm(stripe, ev); });

      element.mount(xpMountNode);
    } catch (e) {
      xpFallback();
    }
  }

  function xpShowWallet() {
    if (xpState !== "reserved") return;
    if (xpTimer) { clearTimeout(xpTimer); xpTimer = null; }
    var ghost = xpSlot.querySelector(".xp__ghost");
    if (ghost) ghost.parentNode.removeChild(ghost);
    xpMountNode.classList.remove("xp__off");
    xpSet("wallet");
    xpConsent();
  }

  // The tap that asks for the sheet. Counted here rather than after the
  // consent check, for the same reason the redirect button counts before its
  // own guard: what this measures is somebody pressing the thing that takes
  // their money.
  function xpClick(ev) {
    track("pay_tap", null, { method: "wallet" });
    firePayPixel();

    // The withdrawal consent has to be given before the sheet opens, not
    // inside it — there is nothing in a wallet sheet that could carry it, and
    // it is the same box gating the same purchase on the same page. Not
    // resolving is how the element is told not to open.
    if (!el.withdrawalCheck.checked) {
      xpNudgeConsent();
      return;
    }
    el.payError.hidden = true;
    ev.resolve(XP_COLLECT);
  }

  // Somebody looked at the sheet and closed it. That is not a failure and it
  // is not a state to recover from: the button stays live, the box stays
  // ticked, the page has not moved, and nothing red appears. There is
  // deliberately no flag being cleared here — a "busy" state that only the
  // sheet can clear is a dead button waiting to happen, and the sheet is
  // modal, so there is no second tap to defend against anyway.
  function xpCancel() { }

  // What the wallet handed over, in the shape Stripe's `billing_details`
  // takes, or null when it gave nothing usable.
  //
  // Rebuilt key by key rather than forwarded, the same way every payload this
  // codebase sends is rebuilt: the object comes from a sheet we do not
  // control, and an empty string is worse than an absent field because it
  // would be stored as one.
  function xpBillingDetails(details) {
    if (!details) return null;
    var out = {};
    var any = false;

    XP_BILLING_KEYS.forEach(function (key) {
      var value = details[key];
      if (typeof value === "string" && value) { out[key] = value; any = true; }
    });

    var from = details.address;
    if (from) {
      var address = {};
      var found = false;
      XP_ADDRESS_KEYS.forEach(function (key) {
        var value = from[key];
        if (typeof value === "string" && value) {
          address[key] = value;
          found = true;
        }
      });
      if (found) { out.address = address; any = true; }
    }
    return any ? out : null;
  }

  function xpConfirm(stripe, ev) {
    var back = location.origin + "/" + slug + "?cs="
      + encodeURIComponent(xpIntentId());

    var params = { return_url: back };

    // The email's whole journey, and the reason it is spelled out here: the
    // wallet gives it to the element, the element gives it to us on this
    // event, and this hands it to Stripe as part of confirming the payment.
    // It becomes the PaymentMethod's billing details, which become the
    // charge's, which is where the webhook reads it — from Stripe, on the
    // server, exactly as it reads the hosted page's. It never travels to our
    // own API as a field of ours, because a client that can name the buyer's
    // email is a client that can name somebody else's.
    //
    // Stripe's own wallet values win over anything passed here, so this cannot
    // overwrite what Apple Pay actually said. It is the belt to that braces:
    // asking for the email is what makes it exist, and this is what makes sure
    // it is attached to the payment rather than only seen in this callback.
    var billing = xpBillingDetails(ev && ev.billingDetails);
    if (billing) params.payment_method_data = { billing_details: billing };

    stripe.confirmPayment({
      elements: xpElements,
      confirmParams: params,
      redirect: "if_required"
    })
      .then(function (res) {
        if (res && res.error) { xpFailed(); return; }
        // Not a claim that the money arrived — the webhook is the only thing
        // that decides that. This hands the token to the page the same way the
        // hosted redirect does, and the report appears when, and only when,
        // the poll finds one written for it.
        location.href = "/" + slug + "?cs=" + encodeURIComponent(xpIntentId());
      })
      .catch(function () { xpFailed(); });
  }

  // `pi_x_secret_y` — the intent's own id is the part before the separator,
  // and it is what the server stores and looks a purchase up by. The secret
  // half never leaves this function.
  function xpIntentId() {
    return String(xpIntent.client_secret).split("_secret_")[0];
  }

  // A payment that really did fail. One short line, and the ordinary button
  // put back within reach — whatever went wrong with the wallet, the redirect
  // is a way through that does not depend on any of it.
  function xpFailed() {
    el.payError.textContent = "That payment didn't go through. Please try again.";
    el.payError.hidden = false;
    xpFallback();
  }

  function xpNudgeConsent() {
    el.payError.textContent = "Please tick the box above to continue.";
    el.payError.hidden = false;
    if (el.withdrawal) {
      el.withdrawal.classList.remove("is-nudged");
      void el.withdrawal.offsetWidth;
      el.withdrawal.classList.add("is-nudged");
    }
  }

  // The wallet button greys out with the box, the way the pay button does.
  // Stripe's element has no disabled state, so this is appearance only — what
  // actually stops the sheet is `xpClick` declining to resolve.
  function xpConsent() {
    if (xpState !== "wallet") return;
    xpSlot.classList.toggle("is-locked", !el.withdrawalCheck.checked);
    if (el.withdrawalCheck.checked) el.payError.hidden = true;
  }

  // What a wallet buyer would otherwise never see. The hosted page names the
  // product and the amount before anything is authorised; a sheet that opens
  // in place shows the amount and nothing about what it is for, so the naming
  // has to happen here, above the button, before the thumb.
  //
  // Every word of it is config that already exists, and it is rendered with
  // the same trust row the block below uses rather than a second set of
  // styles saying the same thing.
  function xpSummary() {
    var co = (cfg && cfg.checkout) || {};
    var copy = commerceCopy();
    var name = co.product_name || "";
    if (!name) return null;

    // Not on the focused page. There the price is a row of the page — under
    // three value cards, over the consent box — and it is there whichever way
    // the wallet check goes, so a card that appears when a wallet answers and
    // takes the row's place is a second price block and, worse, a block that
    // arrives late: everything below it moves the moment Stripe replies, which
    // is the moment a thumb is already on its way to the button.
    if (focusResult()) return null;

    var card = elm("div", "xp-summary");
    card.appendChild(elm("p", "xp-summary__name", name));

    // The same was/now/launch presentation the block above it uses. A wallet
    // buyer sees the price here and nowhere else, so it cannot be the one
    // place the offer looks different.
    var price = elm("p", "xp-summary__price");
    renderPrice(price, copy.price_suffix || co.price_suffix || "");
    card.appendChild(price);

    // No trust row here. There is one on the page, directly under the pay
    // control, and this was a second copy of its first line sitting a
    // hundred pixels above it — the same reassurance twice reads as neither.
    return card;
  }

  var SVG_NS = "http://www.w3.org/2000/svg";

  // Icons are drawn rather than written: a glyph would arrive with whatever
  // the platform emoji font decided, at a colour and weight nobody chose.
  // These inherit currentColor and the accent, like everything else here.
  var ICONS = {
    check: "M4 10.5l4 4 8-9",
    lock: "M6 9V6.5a4 4 0 018 0V9M4.5 9h11v8h-11z",
    bolt: "M11 2L4.5 11.5H9.5L9 18l6.5-9.5H10.5z",
    mail: "M2.5 5h15v10h-15zM2.5 5.5l7.5 5.5 7.5-5.5",
    // The two things unlocking sends: a picture and a document.
    image: "M2.5 4h15v12h-15zM2.5 13l4.5-4 3.5 3 3-2.5 4 3.5",
    doc: "M4.5 2h7l4 4v12h-11zM11.5 2v4.5h4M7 10h6M7 13h6",
    // The three offer cards. The star is filled and the other two are drawn in
    // line, which is the whole hierarchy in one property: a solid shape reads
    // before an outline does, and the first card is the one being bought.
    star: "M10 1.6l2.4 5.3 5.8.6-4.3 3.9 1.2 5.7L10 14.2l-5.1 2.9 1.2-5.7L1.8"
          + " 7.5l5.8-.6z",
    shield: "M10 2.2l6 2.2v5c0 3.9-2.5 6.8-6 8.4-3.5-1.6-6-4.5-6-8.4v-5z"
            + "M7.1 9.9l2.2 2.2 3.7-3.9"
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

  // Once the photo is on the server, the row that promises a visualization
  // stops describing something they will hand over and starts describing
  // something already waiting. Config copy, and only on the funnel that has
  // both the key and a photo — everywhere else the manifest is what it was.
  function manifestRows() {
    var rows = (cfg.checkout.manifest || []).slice();
    var block = vizConfig();
    var have = vizState && vizState.has_source && !vizState.paid;
    if (rows.length && have && block && block.manifest_uploaded) {
      rows[0] = block.manifest_uploaded;
    }
    return rows;
  }

  // The manifest is built once when the offer is rendered, and the photo can
  // arrive after that. Re-running it is cheap and keeps the two in step
  // without the upload path needing to know how a manifest row is built.
  //
  // Guarded on `manifestHead` rather than on `manifest`: the head is created
  // by the same setup pass that first renders the rows, so its absence means
  // the offer has not been built yet — and re-rendering into a half-built one
  // empties the list and throws on the way out, leaving no manifest at all.
  // The first real render picks the photo up anyway.
  function renderManifestRows() {
    if (el.manifest && el.manifestHead && cfg && cfg.checkout) {
      renderManifest();
    }
  }

  function renderManifest() {
    var rows = manifestRows();
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

    renderPrice(el.price, cfg.checkout.price_suffix);
    renderExpectation();
    renderTrust();
    renderGate();

    el.withdrawalText.textContent = cfg.checkout.eu_withdrawal_text || "";
    // The short line is the whole of what the box says now; the full clause it
    // stands for is Terms section 6, which the footer links to from this
    // screen. The box itself is unchanged — tappable, uncheckable, and still
    // the only thing that enables the button.
    el.withdrawalCheck.checked = cfg.checkout.consent_prechecked === true;
    el.payError.hidden = true;
    updatePayButton();
    xpStart();
    // Same reasoning as the single-page block: if no express attempt started,
    // the button on this screen is the control and nothing else will say so.
    if (!xpStarted) payReady("redirect");
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

  // The free result page as one argument instead of eleven.
  //
  // On a funnel that sells a picture of the reader's own kitchen, the page they
  // land on had accumulated every section the report funnel needs and then the
  // offer underneath it: a palette section, a whole free mistake, a strip of
  // style elements, a card asking them to scroll, a teaser about the other four
  // mistakes, two more blurred teasers, a list of what else is inside, a sample
  // link, two lead lines. Each of those earns its place on /kitchen, where the
  // report IS the product. Here the product is above all of it and every one of
  // them is another reason to stop before reaching it.
  //
  // So this funnel renders a fixed page: what they chose, the two panels, and
  // what unlocking costs. It is a layout switch and not a feature flag — the
  // config either names this layout or it does not, and a funnel JSON cached
  // from before the key existed renders exactly what it rendered yesterday.
  // /kitchen never names it.
  function focusResult() {
    return ((cfg && cfg.report) || {}).free_layout === "visualizer";
  }

  // The hairlines the focused page is divided by. It has no section stack to
  // inherit rules from any more, so the two rules it does want are drawn.
  function ruleNode() {
    return elm("div", "result-rule");
  }

  // Two lines where a seven-row list used to be. The first names the thing
  // being bought — their own kitchen, redrawn — and the second names the
  // report as what makes that image usable rather than as a second product.
  // A funnel with neither key renders neither node, so the older config
  // behind the CDN, and /kitchen, are unchanged.
  function renderLeads(copy) {
    ensureLeadNodes();
    if (!el.leadMain) return;
    fillAccent(el.leadMain, withPrice(copy.lead || ""), copy.lead_accent || "");
    el.leadMain.hidden = !copy.lead;
    el.leadReport.textContent = withPrice(copy.lead_report || "");
    el.leadReport.hidden = !copy.lead_report;
  }

  // What each card carries beside its title. Positional, not configured: there
  // are three cards and the comment above says why there is no fourth, the
  // order is the order of what is being sold, and a per-row icon key would be
  // one more name a copywriter has to keep in step with that order.
  //
  // The hero's is overridden to the star wherever it sits, so a config that
  // moves the hero moves its mark with it rather than leaving the star behind
  // on a card that is no longer the one being bought.
  var VALUE_ICONS = ["star", "doc", "shield"];

  // Three things, in the order they matter, and the first one carries the
  // weight because it is the one being bought. No fourth item, and nothing
  // about other customers: there are none yet, and a number nobody can stand
  // behind is the one line on a paywall that costs more than it earns.
  function renderValue(copy) {
    var rows = copy.value || [];
    if (!el.valueList) {
      if (!rows.length || !el.price || !el.price.parentNode) return;
      el.valueHead = elm("h3", "offer-value__head", copy.value_head || "");
      el.valueHead.hidden = !copy.value_head;
      el.valueList = elm("ul", "offer-value");
      // Heading then cards then price, with nothing allowed between them:
      // both are inserted immediately before the row that holds the price, in
      // that order. On the focused page that row is the hold container and not
      // the price itself — inserted before the price, the heading and the
      // cards would be inside the block that goes invisible while the render
      // runs, and the reader would be left waiting at a blank page instead of
      // reading what they are waiting for.
      var anchor = valueAnchor();
      anchor.parentNode.insertBefore(el.valueHead, anchor);
      anchor.parentNode.insertBefore(el.valueList, anchor);
    }
    el.valueList.textContent = "";
    el.valueList.hidden = !rows.length;

    rows.forEach(function (row, i) {
      if (!row || !row.text) return;
      var li = elm("li", "offer-value__row" + (row.hero ? " is-hero" : ""));

      // The badge is a circle with a mark in it, and it is the same shape on
      // every card: what separates the hero is the tint behind it, the fill of
      // the mark and the border around the card, not a different geometry.
      var badge = elm("span", "offer-value__badge");
      var name = row.hero ? "star" : (VALUE_ICONS[i] || "doc");
      var mark = icon(name, "offer-value__icon"
                            + (name === "star" ? " is-filled" : ""));
      badge.appendChild(mark);
      li.appendChild(badge);

      var body = elm("div", "offer-value__body");
      if (row.title) {
        body.appendChild(elm("p", "offer-value__title", row.title));
      }
      var text = elm("p", "offer-value__text");
      // The accent lands on the figure alone. Bolding the whole sentence
      // emphasises nothing; bolding "$4,000+" is the point of the sentence.
      fillAccent(text, withPrice(row.text), row.accent || "");
      body.appendChild(text);
      li.appendChild(body);
      el.valueList.appendChild(li);
    });
  }

  function valueAnchor() {
    return el.hold && el.hold.parentNode ? el.hold : el.price;
  }

  // Whether this reader has actually handed over a kitchen. The whole bottom
  // block turns on it.
  function vizHasPhoto() {
    return !!(vizState && vizState.has_source);
  }

  // No photograph, no payment — on either path.
  //
  // The redirect button was gated on the consent box and nothing else, and the
  // wallet was gated on even less: `xpStart` ran the moment the offer
  // rendered, so the Express Element mounted, a wallet button appeared, and
  // `xpClick` only ever asked about the checkbox. Somebody with Apple Pay
  // could therefore buy a transformation of a photograph they had not sent —
  // and the intent was created before the photo existed too. That is what this
  // gate closes, and it closes it in one place so neither path can be the one
  // that was forgotten.
  //
  // That one place is now three states rather than two, and the reason the
  // second one is here rather than somewhere of its own is the same reason the
  // first one is: every route to a pay control has to pass through a single
  // function, or one of them is eventually the route somebody forgets.
  //
  // Three states below the panels, and which one is live is read from the
  // server's own status body rather than from anything the page remembers.
  //
  //   no photo                  gate     "Add your photo first"
  //   photo, render running     wait     one muted line, no price, no control
  //   render finished or failed open     price, pay control, trust row
  //
  // `has_source` is what the upload wrote and separates the first from the
  // other two; `teaser` — "working", then "ready" or absent — separates the
  // second from the third. Both come off `/api/visualizer/status`, which is
  // also what the poll refreshes, so the block changes state on the same
  // answer that changes the panel above it.
  //
  // A funnel that does not render before the money never reports a teaser at
  // all, and neither does an engine.js talking to a server that predates it:
  // `vizTeaserWorking()` is false, and the block is open the moment there is a
  // photograph, exactly as it was.
  function offerState() {
    if (!vizOn() || !vizPre()) return "open";
    if (!vizHasPhoto()) return "gate";
    // The note is the state. Withholding the price and the button while saying
    // nothing about why is worse than not withholding them, so a funnel with
    // no waiting copy configured — an older JSON off the CDN — keeps the two
    // states it already had.
    if (vizTeaserWorking() && waitNote()) return "wait";
    return "open";
  }

  function waitNote() {
    return ((cfg && cfg.checkout) || {}).wait_note || "";
  }

  function renderGate() {
    // Keyed on the price row rather than on the commerce block, so the gate
    // covers the two-screen paywall too if that flag is ever turned back on.
    if (!el.price) return;
    showOffer(offerState());
  }

  function showOffer(state) {
    ensureGateNodes();
    if (!el.gate) return;

    var on = state === "gate";
    var wait = state === "wait";

    // The wallet's geometry, up front. Without this the block would be one
    // bare button tall while the render ran and one grid cell tall after it,
    // and the no-shift promise below would be a promise about a page that had
    // not finished being built yet.
    if (el.hold) xpReserve();

    gateUp = on;
    // What no pay control is on screen means, whatever the reason for it.
    // Two events read this rather than the gate flag: neither `pay_ready` nor
    // `paywall_view` is true of a block showing a line about a picture being
    // prepared.
    payHeld = on || wait;

    el.gate.hidden = !on;
    // Held, not hidden. Every row below stays in the layout at its own height
    // and goes invisible, which is what makes the block the same number of
    // pixels tall in both states — so the legal line under it, and the whole
    // of the page below that, cannot move when the render lands.
    if (el.hold) el.hold.classList.toggle("is-held", wait);
    if (el.wait) el.wait.textContent = waitNote();

    if (el.withdrawal) el.withdrawal.hidden = on;
    if (el.trust) el.trust.hidden = on;
    if (el.expectation) el.expectation.hidden = on || !expectationText();

    // Two ways to treat the price before there is a photograph, and which one
    // is live is a config value because it is going to be tested against the
    // upload rate rather than argued about. Shown-and-dimmed is the default
    // and today's behaviour; hidden is the other arm.
    //
    // Either way the price is on screen in full before any pay control is,
    // because `showOffer("open")` runs this before it starts the wallet. A
    // price that first appears after the money has been asked for is the one
    // ordering this must never produce.
    //
    // The waiting state is deliberately not in here. Its price is withheld by
    // the hold going invisible, which keeps the row's height; hiding it would
    // take the height with it and move the button when it came back.
    var hide = priceGated();
    if (el.price) {
      // `xpSet` owns this too once a wallet answer is in, so ask it rather
      // than assuming: the summary card may be the price block right now.
      el.price.hidden = hide || (el.xpSummary && !el.xpSummary.hidden);
      el.price.classList.toggle("is-dimmed", on && !hide);
    }
    if (el.xpSummary && hide) el.xpSummary.hidden = true;

    // Every other place a price is printed. "No price until a photo" has to
    // mean the page, not one row of it: the visualizer card names the price
    // above the upload box, and the sticky bar carries it down the whole
    // scroll. Both were still saying it while the block below said nothing.
    if (el.vizPrice) el.vizPrice.hidden = hide;
    if (el.sticky) {
      var copy = commerceCopy();
      // The bar goes quiet for the wait as well. It is the same price the
      // block below is withholding, carried down the whole scroll — a bar
      // still shouting the number while the block says the picture is being
      // prepared is the page contradicting itself on the reader's screen.
      el.sticky.textContent = (hide || wait)
        ? (copy.sticky_label_gated || copy.sticky_label || "")
        : withPrice(copy.sticky_label || "");
    }

    // Both, every time, and not one or the other.
    //
    // The gate goes up before the offer block has been assembled — the
    // visualizer section renders first and asks for it — so the button is
    // hidden directly, on its own, while there is no express slot to hide it
    // through. The slot is built later, and a run that then cleared only the
    // slot left the button carrying a `hidden` nobody was going to take off
    // again: a block with a price, a consent box and no way to pay.
    if (xpBlock) xpBlock.hidden = on;
    if (el.payButton) el.payButton.hidden = on && !xpBlock;

    if (on) watchGate();
    else if (gateIO) { gateIO.disconnect(); gateIO = null; }

    // The block just became something that can be paid. If the reader is
    // already looking at it there will be no new intersection to wait for, so
    // the postponed view is fired here; otherwise the observer still has it.
    if (!payHeld && commerceInView) firePaywallView();

    // The element is never mounted while the gate is up, so there is no wallet
    // button to press and no intent created for a purchase that cannot be
    // fulfilled. Taken down, this is what lets it start.
    //
    // The waiting state holds it for the second reason as much as the first.
    // A PaymentIntent is created against an order this session might never be
    // able to fulfil — the render can still fail — and a wallet button under a
    // panel that has no picture in it yet is a charge offered for something
    // nobody has been shown.
    if (!payHeld) xpStart();

    // A gated funnel with no express attempt: the gate has just come down and
    // the redirect button is what is standing behind it. `xpStart` has already
    // run and declined by this line, so `xpStarted` is asking whether an
    // attempt is under way — if none is, what is on screen is the final answer.
    if (!payHeld && !xpStarted) payReady("redirect");
  }

  function ensureGateNodes() {
    if (el.gate) { homeGate(); return; }
    if (!el.commerce) return;
    var co = (cfg && cfg.checkout) || {};
    if (!co.gate_cta) return;

    el.gate = elm("div", "offer-gate");
    var button = elm("button", "offer-gate__cta");
    button.type = "button";
    button.appendChild(elm("span", "offer-gate__arrow", "↑"));
    button.appendChild(elm("span", null, co.gate_cta));
    button.addEventListener("click", function () {
      track("viz_gate_tap");
      scrollToUpload();
    });
    el.gate.appendChild(button);
    if (co.gate_note) {
      el.gate.appendChild(elm("p", "offer-gate__note", co.gate_note));
    }
    homeGate();
  }

  // Directly under the price, where the pay control would be — and re-homed
  // every time, because the price row does not stay put.
  //
  // The visualizer section renders before `moveCommerce` relocates the price
  // into the commerce block, and the first thing it does is ask for the gate.
  // Built once at that moment, the gate was inserted beside a price row that
  // was still on the two-screen paywall, and stayed there: present, correct
  // by every class and hidden flag, and nought pixels tall inside a screen
  // nobody was looking at. A reader with no photo therefore got a dimmed
  // price, no button and no sentence explaining why — the protection worked
  // and the explanation for it did not.
  function homeGate() {
    if (!el.gate || !el.price || !el.price.parentNode) return;
    if (el.gate.parentNode === el.price.parentNode) return;
    el.price.parentNode.insertBefore(el.gate, el.price.nextSibling);
  }

  // The gate reaching the reader, counted once. It is put up before the offer
  // is scrolled to and can be scrolled past repeatedly, so the count is of
  // people who saw it and not of times it crossed the fold — a scroll-counted
  // view would make the upload rate look worse the longer somebody deliberated.
  function watchGate() {
    if (gateSeen || gateIO || !el.gate) return;

    if (!window.IntersectionObserver) {
      // Nothing to observe with. Counting it as it goes up overstates it
      // slightly; not counting it at all loses the denominator entirely, and
      // of the two only one of them can be corrected later.
      gateSeen = true;
      track("viz_gate_view");
      return;
    }

    gateIO = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting || gateSeen) return;
        gateSeen = true;
        track("viz_gate_view");
        if (gateIO) { gateIO.disconnect(); gateIO = null; }
      });
    }, { threshold: 0.4 });
    gateIO.observe(el.gate);
  }

  function scrollToUpload() {
    var zone = document.querySelector(".viz-drop");
    if (!zone) return;
    if (zone.scrollIntoView) {
      zone.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    zone.classList.remove("is-nudged");
    void zone.offsetWidth;
    zone.classList.add("is-nudged");
  }

  function expectationText() {
    return ((cfg && cfg.checkout) || {}).expectation || "";
  }

  function ensureLeadNodes() {
    if (el.leadMain || !el.manifest || !el.manifest.parentNode) return;
    el.leadMain = elm("p", "offer-lead");
    el.leadReport = elm("p", "offer-lead offer-lead--report");
    el.manifest.parentNode.insertBefore(el.leadMain, el.manifest);
    el.manifest.parentNode.insertBefore(el.leadReport, el.manifest);
  }

  // The price, everywhere it is shown as a price rather than mentioned inside
  // a sentence: what it was, struck; what it is, loud; and what that is called.
  //
  // The struck figure is config copy, never arithmetic. A number this code
  // worked out would be a claim about what something used to cost that nothing
  // here can stand behind, and the one place a made-up "was" price is worth
  // real money is exactly the place it must not be invented.
  function renderPrice(node, suffix) {
    if (!node) return;
    var co = (cfg && cfg.checkout) || {};

    // No struck figure configured, no new presentation: this is the one line
    // every funnel without a launch price still renders, and it renders it
    // exactly as it always did, down to the separator. A funnel that did not
    // ask for this change does not get it.
    if (!co.price_was_display) {
      node.classList.remove("has-was");
      node.textContent = formatPrice() + (suffix ? " · " + suffix : "");
      return;
    }

    node.textContent = "";
    node.classList.add("has-was");
    node.appendChild(elm("span", "price-was", co.price_was_display));
    // The short form: "$3" beside a struck "$7" is the comparison. "3.00 USD"
    // beside it is an invoice.
    node.appendChild(elm("span", "price-now", formatPriceShort()));
    if (co.price_launch_label) {
      node.appendChild(elm("span", "price-launch", co.price_launch_label));
    }
    if (suffix) node.appendChild(elm("span", "price-note", suffix));

    // Beside the number rather than in the list above it: this is a term of
    // the sale, not one of the things being sold.
    if (co.price_terms) {
      node.appendChild(elm("span", "price-terms", co.price_terms));
    }
  }

  // The quiet line by the button. It is what stops somebody expecting a
  // drawing they could hand a builder, which is the refund this prevents, so
  // it is always rendered when the config carries it and never made loud.
  function renderExpectation() {
    var text = ((cfg && cfg.checkout) || {}).expectation || "";
    if (!el.expectation) {
      // Above the value list on the focused page, over the consent box
      // everywhere else.
      //
      // It has now been under the price and under the button, and both were
      // wrong for the same reason: a sentence naming what the thing is NOT,
      // read in the second before a tap, is a doubt planted at the moment of
      // decision. Above the list it is a frame for what follows — here is what
      // this is, and here is what you get — which is the job it was written
      // for. `renderValue` inserts the heading and the cards before the price,
      // so anchoring on the heading keeps this first of all of them.
      var anchor = focusResult() ? (el.valueHead || el.price) : el.withdrawal;
      if (!text || !anchor || !anchor.parentNode) return;
      el.expectation = elm("p", "offer-expectation");
      anchor.parentNode.insertBefore(el.expectation, anchor);
    }
    el.expectation.textContent = text;
    el.expectation.hidden = !text;
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

    // The focused page takes fewer rows, and the ones it leaves out are the
    // ones that describe the offer instead of making it: the anchor line, the
    // six-row manifest and the sample-page link, all of which are answered
    // above by three value cards and by the reader's own kitchen. The rule is
    // the join to what is above.
    //
    // The expectation line is not in either list. It is placed by
    // `renderExpectation`, which puts it under the pay control here and over
    // the consent box on /kitchen.
    var rows = focusResult()
      ? [ruleNode(),
         holdNode([el.price, el.withdrawal, el.payButton, el.payError,
                   el.trust]),
         el.legal]
      : [el.payAnchor, el.manifest, buildSampleLink(), el.price, el.withdrawal,
         el.payButton, el.payError, el.trust, el.legal];
    rows.forEach(function (node) {
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

    // Same treatment for the three the focused layout drops. They stay on the
    // paywall screen nobody travels to, which is already display:none — hidden
    // as well so that flipping `single_page` off cannot surface an anchor line
    // this funnel has no copy for.
    if (focusResult()) {
      [el.payAnchor, el.manifest].forEach(function (node) {
        if (node) node.hidden = true;
      });
      // One page, not a page and then a card with the offer in it. The report
      // above has already dropped its own card for the same reason: the two
      // hairlines are what divide this page, and a box edge beside a hairline
      // is the same division drawn twice in two different languages.
      el.commerce.classList.add("commerce--focus");
    }
  }

  // Everything that is withheld while the render runs, in one box, plus the
  // line that stands in for it.
  //
  // The box is what makes the promise keepable. Its height comes entirely from
  // the rows inside it — the price, the consent, the pay control, the trust
  // row — and those rows are in the document from the first paint whichever
  // state the block is in. The waiting line is taken out of flow and laid over
  // them, so it contributes nothing. There is therefore no arithmetic keeping
  // the two states the same height: they are the same height because they are
  // the same boxes.
  //
  // The legal line is deliberately outside. It is the fine print of the page
  // rather than a term of this sale, and it is the thing directly underneath —
  // the first thing that would visibly jump if any of this were wrong.
  function holdNode(rows) {
    el.hold = elm("div", "offer-hold");
    el.wait = elm("p", "offer-wait", waitNote());
    el.hold.appendChild(el.wait);
    rows.forEach(function (node) {
      if (node) el.hold.appendChild(node);
    });
    return el.hold;
  }

  function renderCommerce() {
    var copy = commerceCopy();
    var focus = focusResult();
    moveCommerce();

    // Three renders the focused layout has no nodes on the page for. Calling
    // them anyway would build a lead paragraph and a manifest head into a
    // container sitting on a screen nobody reaches, which is not harmful and is
    // not honest either — the page does not have these, so nothing renders them.
    if (!focus) {
      renderManifest();
      renderLeads(copy);
    }
    renderValue(copy);

    if (!focus) {
      fillAccent(el.anchorHead, withPrice(copy.anchor_head || ""),
                 copy.anchor_head_accent || "");
      el.anchorHead.hidden = !copy.anchor_head;
      el.anchorLine.textContent = withPrice(copy.anchor || "");
      el.anchorLine.hidden = !copy.anchor;
      el.payAnchor.hidden = !(copy.anchor_head || copy.anchor);
    }

    renderPrice(el.price, copy.price_suffix);
    renderExpectation();

    el.withdrawalText.textContent = withPrice(copy.consent || "");
    el.withdrawalCheck.checked = cfg.checkout.consent_prechecked === true;
    renderConsent();

    renderTrust(copy.trust);
    el.payError.hidden = true;
    updatePayButton();

    el.commerce.hidden = false;
    // The bar's default label, before the gate has had a look at it. A funnel
    // with no gate keeps exactly this; a gated one has it replaced a line
    // below, which is why this is written first and not last.
    if (el.sticky) el.sticky.textContent = withPrice(copy.sticky_label || "");
    // After the block is on screen: the slot is measured against the pay
    // button, and a button inside a hidden container has no height to match.
    // `renderGate` is what calls `xpStart` now — it only starts once there is
    // a photograph to sell a transformation of.
    renderGate();
    // A funnel with no gate never reaches the `xpStart` inside `showOffer` —
    // that call sits below an early return for the missing gate node, which
    // was right while the only funnel offering a wallet was the gated one.
    // /zodiac offers one and has no photograph to gate on, so nothing was
    // holding the wallet back and nothing was starting it either.
    //
    // Inert for the funnels that were here first: `xpStart` returns at its
    // own first line unless `checkout.express` is true, so /kitchen fetches
    // nothing from Stripe and behaves exactly as before, and a gated funnel
    // still starts express from `showOffer` when its gate comes down.
    if (!el.gate) xpStart();
    // And the ungated case, which is most funnels. `showGate` gives up at its
    // first line when there is no gate node to hide — /kitchen has no
    // `gate_cta` and therefore no gate — so the call inside it never runs
    // there, and the redirect button standing on this block from the moment it
    // renders would have gone uncounted. `payReady` still refuses while the
    // gate is up, so a gated funnel reaching here early is not miscounted.
    if (!xpStarted) payReady("redirect");
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

  // --- modals ---------------------------------------------------------------

  // Two things on this page open a sheet over a locked document: the sample
  // page on the offer, and the transformed kitchen after it. They look nothing
  // alike inside and behave identically outside — backdrop closes, Escape
  // closes, the page underneath must not scroll — so the outside is written
  // once here and each of them fills in its own middle.
  //
  // `slot` is the key on `el` the box is kept under, because both are built
  // once and then re-shown rather than rebuilt on every open.
  function boxShell(slot, id, label) {
    var box = elm("div", "lightbox");
    box.id = id;
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-modal", "true");
    box.setAttribute("aria-label", label || "");
    // Anywhere off the content closes it; the content itself does not.
    box.addEventListener("click", function (e) {
      if (e.target === box) closeBox(slot);
    });
    return box;
  }

  function boxClose(slot) {
    var close = elm("button", "sample-close", "×");
    close.type = "button";
    close.setAttribute("aria-label", "Close");
    close.addEventListener("click", function () { closeBox(slot); });
    return close;
  }

  // One handler per slot, held so it can be removed again. A listener left on
  // the document after close would keep answering Escape for a dialog that is
  // no longer on screen.
  var boxKeys = {};

  function showBox(slot) {
    var box = el[slot];
    if (!box) return;
    box.hidden = false;
    document.body.classList.add("is-locked");
    if (!boxKeys[slot]) {
      boxKeys[slot] = function (e) {
        if (e.key === "Escape" || e.keyCode === 27) closeBox(slot);
      };
    }
    document.addEventListener("keydown", boxKeys[slot]);
    var close = box.querySelector(".sample-close");
    if (close && close.focus) close.focus();
  }

  function closeBox(slot) {
    var box = el[slot];
    if (!box) return;
    box.hidden = true;
    document.body.classList.remove("is-locked");
    if (boxKeys[slot]) document.removeEventListener("keydown", boxKeys[slot]);
  }

  function openSample() {
    if (el.sample) { showSample(); return; }
    var copy = commerceCopy();

    var box = boxShell("sample", "sample-box",
                       copy.sample_link || "Sample page");

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

    var close = boxClose("sample");
    close.id = "sample-close";
    shell.appendChild(close);

    box.appendChild(shell);
    document.body.appendChild(box);
    el.sample = box;
    showSample();
  }

  function showSample() { showBox("sample"); }

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

  // The bar asks for a scroll, not for money. It briefly took the payment
  // itself — one tap from the bar to Stripe — and that is reverted: the block
  // it scrolls to is where the price, the consent and the button are, and
  // somebody who has not seen those has not been shown what they are agreeing
  // to. A bar that charges is a bar that has to carry all three.
  //
  // The two paths that used to exist here are one path now. There is no
  // consent_prechecked branch left to take: the checkbox is on the block, so
  // whether it starts ticked changes what the reader finds when they arrive
  // rather than what this function does. `pay_tap` belongs to the button they
  // find there and to nothing else.
  //
  // `payIntent` is still set, and is still the whole point of tapping it: the
  // block coming into view fires `paywall_view`, and this is what makes that
  // event say the bar sent them rather than a scroll.
  function stickyTap() {
    track("sticky_cta");
    payIntent = "sticky";
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
    // Reaching a block that cannot take money is not reaching checkout. With
    // the upload gate up, what is on screen is a dimmed price and a button
    // asking for a photograph — telling Meta somebody arrived at checkout
    // there would pollute the exact signal the upload event exists to be.
    //
    // Deliberately without setting the flag: this is a postponement, not a
    // suppression. The next intersection after the block opens fires it, and
    // `showOffer` fires it directly if the block is already on screen. The
    // waiting state is held for the same reason — a block whose price and
    // button are not on it yet is not a checkout anybody has reached.
    if (payHeld) return;
    paywallTracked = true;
    track("paywall_view", null, { src: payIntent });
    pixelTrack("InitiateCheckout");
  }

  // AddPaymentInfo, once a session and on both paths.
  //
  // It was once per tap, which the redirect made look like once per session
  // because the page is gone a moment later. The wallet is not: a dismissed
  // sheet leaves the reader on the page and free to press again, so the same
  // person would have sent two, three, four. Meta would then have been told
  // that wallet readers reach payment more often than redirect readers, which
  // is not true and is not something it should be able to tell apart at all.
  //
  // `pay_tap` is deliberately left counting every tap: how often a wallet
  // sheet is opened and abandoned is a real thing to know, and our own table
  // is the right place to know it. The pixel is the one that has to mean the
  // same thing on both paths.
  function firePayPixel() {
    if (pixelPayFired) return;
    pixelPayFired = true;
    pixelTrack("AddPaymentInfo");
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
    setJourneySteps(cfg.swipe.journey_steps);
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
  // A funnel with no `subtext` gets no line, and no space where one would
  // have been. The node is in the shell markup rather than built here, so
  // leaving it empty would leave a 14px top margin on nothing — which on a
  // header with no slack in it is 14px taken from the cards to show a blank.
  // `hidden` and not an empty string, because [hidden] wins over the margin.
  function setMoneyLine(text, accent) {
    if (!el.subtext) return;
    if (!text) {
      el.subtext.textContent = "";
      el.subtext.hidden = true;
      return;
    }
    el.subtext.hidden = false;
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

  // Where this is going, as three numbered steps across the top.
  //
  // Somebody thirteen taps into a quiz has been told what they will get and
  // not that the last step is a photograph of their own kitchen. On the funnel
  // that ends in one this is the only place before the result that says so,
  // and it replaces the money line rather than sitting under it — two claims
  // stacked above the question were two headlines arguing.
  //
  // Built once and left in the header, which persists across steps: the cards
  // and the caption are what change between taps, so the strip is on screen
  // for every one of the thirteen without being rebuilt for any of them.
  //
  // A funnel with no `journey_steps` gets nothing at all — no node, no grid,
  // no margin — which is the whole of what keeps /kitchen as it was.
  function setJourneySteps(steps) {
    var node = el.journeySteps;
    if (!steps || !steps.length) {
      if (node) node.hidden = true;
      return;
    }
    if (!node) {
      node = elm("div", "m-steps");
      node.id = "swipe-steps";
      // Inside `.lead`, in the slot the money line occupies. `.lead` is
      // display:contents, so this becomes a flex item of the screen like its
      // sibling and takes its own space rather than borrowing the caption's.
      el.subtext.parentNode.insertBefore(node, el.subtext.nextSibling);
      el.journeySteps = node;
    }
    node.hidden = false;
    node.textContent = "";

    steps.forEach(function (step) {
      if (!step) return;
      var cell = elm("div", "m-steps__c");
      cell.appendChild(elm("div", "m-steps__n", String(step.n == null
                                                       ? "" : step.n)));
      cell.appendChild(labelWithBreaks("div", "m-steps__l",
                                       String(step.label || "")));
      node.appendChild(cell);
    });
    markJourney(journeyStage);
  }

  // The strip onto the result page, moved rather than copied.
  //
  // It was built into the swipe screen's header, which is exactly right for the
  // thirteen taps and wrong the moment they are over: that screen is
  // display:none from the result onwards, so `markJourney(1)` was setting the
  // active class on a strip nobody could see. Step 2 of three — "your kitchen"
  // — is the step the reader is standing in for the whole of this page, and a
  // position they cannot see is not a position.
  //
  // Moved, so there is one strip: two would be two things to keep in step, and
  // the one that got forgotten would be the one on screen.
  function homeJourney() {
    if (!focusResult()) return;
    var node = el.journeySteps;
    if (!node || !el.resultBody) return;
    if (node.parentNode === el.resultBody) return;
    node.classList.add("m-steps--result");
    el.resultBody.insertBefore(node, el.resultBody.firstChild);
  }

  // Which of the three the reader is actually in. A strip that looks the same
  // on every screen is decoration; one that moves is a position.
  //
  // Class only, never geometry: the active and inactive circles are the same
  // size and the labels the same weight, so the strip cannot change height
  // when the stage does and nothing below it moves.
  function markJourney(stage) {
    journeyStage = stage;
    var node = el.journeySteps;
    if (!node) return;
    var cells = node.querySelectorAll(".m-steps__c");
    for (var i = 0; i < cells.length; i++) {
      cells[i].classList.toggle("is-active", i === stage);
    }
  }

  // Copy with an explicit line break in it, as text nodes and real <br>
  // elements. The break is explicit rather than left to wrapping because the
  // three columns have to be the same height, and where a phrase wraps
  // naturally depends on the screen — three columns that each break somewhere
  // different is a strip with a ragged bottom edge.
  //
  // Built rather than assigned: config carries copy, and copy that reaches
  // innerHTML is copy that has to be trusted. A label with a tag in it lands
  // on the page as the literal characters of that tag.
  function labelWithBreaks(tag, cls, text) {
    var node = elm(tag, cls);
    text.split("\n").forEach(function (line, index) {
      if (index) node.appendChild(document.createElement("br"));
      node.appendChild(document.createTextNode(line));
    });
    return node;
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
        applyTheme();
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
