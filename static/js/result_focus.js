/* The focus funnel's result page, before and after the money.
 *
 * Same contract as static/js/result_brain.js, which this file was cut from —
 * engine.js loads this when a config names it, hands it the finished run, and
 * the two things that must not be got wrong, the withdrawal-right consent and
 * the button that charges, are engine.js's own live nodes moved into this
 * layout rather than rebuilt in it. The paywall variants are the same
 * mechanism, unchanged, down to the one event it fires and the one field
 * engine.js reads back.
 *
 * What differs from brain is the number. Brain gives the score away and sells
 * the age behind it; this funnel has one number, the Focus Score, and it is
 * the headline on both pages: "82/100" under the words FOCUS SCORE. There is
 * no second figure to hold back, no age group to set it against, and nothing
 * on either page compares the reader with anybody — the benchmark line brain
 * drew under its number is gone from this file, not hidden.
 *
 * The score is not a verdict about anybody. It is sixteen rounds, a base, a
 * per-miss and — v3 — a point a step for answering the twelve timed rounds
 * fast, all stated in `brain_age` in the config; the block keeps brain's key
 * because the report machinery reads it by that name. Nothing in this file
 * holds a constant of its own: the base, the cost of a miss, the clamp, the
 * half-clock a full point needs and the three speed words all come off that
 * table. The reaction times come off the run — engine.js hands them over on
 * the funnels that record them — and after the money there is no run left in
 * the tab, so what the report stored travels back as `visuals.brain`.
 *
 * A config with no `brain_age` block still renders: the type card and the
 * offer are drawn without the number, which is the page a reader gets in the
 * window where this file and the config it reads are a version apart behind
 * the CDN.
 */
(function () {
  "use strict";

  // The four zones, in the order they were played, which is also the order
  // they are drawn in. The tag stems are brain's — engine.js scores on `mem`,
  // `foc`, `chg` and `spa` and nothing else — and the names are the config's,
  // `brain_age.domains`, so the chips and the report cannot end up calling
  // the same zone two things.
  var DOMAINS = ["mem", "foc", "chg", "spa"];

  var DOMAIN_COLOR = {
    mem: "#3B7DD8", foc: "#8E6FD8", chg: "#F2B33D", spa: "#4CAF7D"
  };

  // How many of each round there are. Four apiece, sixteen in all, which is
  // also what `brain_age.scored` says — read from the run rather than from
  // the config so a bar can never claim a denominator the quiz did not draw.
  var PER_DOMAIN = 4;

  // The fewest frames worth calling a grid, borrowed from the persona page
  // for the same reason: a row of two squares under "read from your rounds"
  // reads as a page that failed rather than as evidence.
  var TAPS_MIN = 4;

  function elm(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  var SVG_NS = "http://www.w3.org/2000/svg";

  function svgEl(name, attrs) {
    var node = document.createElementNS(SVG_NS, name);
    for (var key in attrs) {
      if (Object.prototype.hasOwnProperty.call(attrs, key)) {
        node.setAttribute(key, String(attrs[key]));
      }
    }
    return node;
  }

  // `{token}` against a plain object. Anything unanswered is left standing,
  // the way engine.js's own `fillHook` leaves it: a brace on the page is a
  // copy bug somebody can see, where a silent gap is one nobody reports.
  function fill(text, words) {
    if (!text) return "";
    return String(text).replace(/\{(\w+)\}/g, function (whole, key) {
      return Object.prototype.hasOwnProperty.call(words || {}, key)
        ? String(words[key]) : whole;
    });
  }

  function copyOf(ctx) {
    return (ctx.cfg && ctx.cfg.result_copy) || {};
  }

  // Which layout this funnel asked for. Named in the config rather than
  // assigned to a session: this page is not running a test, and a reader who
  // paid on one layout has to come back to the same one.
  function template(ctx) {
    return (ctx.cfg && ctx.cfg.result_template) || "";
  }

  function profileCopy(ctx) {
    return (copyOf(ctx).profile) || {};
  }

  function ageBlock(ctx) {
    var block = ctx.cfg && ctx.cfg.brain_age;
    return (block && typeof block === "object") ? block : null;
  }

  // --- the score -------------------------------------------------------------

  // Everything the page says about the run, computed once.
  //
  // `misses` is counted off the hits rather than off a miss tally, and that is
  // deliberate: a round nobody answered — a reader who reloaded mid-quiz, a
  // step that failed to draw — is a miss, and counting `*_miss` tags would
  // quietly score it as neither. The number a reader is shown must always be
  // out of sixteen.
  //
  // `age` is the block's own formula and it is kept under that name because
  // the report stores it under that name; on this funnel the table makes it
  // the same figure as the score. What is NOT here is brain's age group:
  // the age-group table maps every work tag to nothing, nothing is compared,
  // and no line on either page sets the reader against anybody.
  function profileOf(ctx) {
    var cfg = ctx.cfg;
    var scores = ctx.scores || {};
    var block = (cfg && cfg.brain_age) || null;
    if (!block) return null;
    var counts = {};
    var hits = 0;
    DOMAINS.forEach(function (key) {
      var n = Math.max(0, scores[key + "_hit"] || 0);
      counts[key] = n;
      hits += n;
    });
    var scored = typeof block.scored === "number" ? block.scored : 16;
    var misses = Math.max(0, scored - hits);
    var raw = (block.base || 0) + (block.per_miss || 0) * misses;
    var age = Math.round(raw);
    if (typeof block.min === "number") age = Math.max(block.min, age);
    if (typeof block.max === "number") age = Math.min(block.max, age);

    var out = {
      age: age,
      hits: hits,
      misses: misses,
      scored: scored,
      counts: counts
    };
    return scoreOf(out, block, speedOf(ctx, block));
  }

  // --- speed -----------------------------------------------------------------
  //
  // v3: the timed rounds pay for being answered fast as well as right. Every
  // step with a clock on it is worth `point_per_step` for a correct answer
  // inside `full_frac` of its own clock, and less than that, straight down to
  // nothing, for a correct answer that used the rest of it. A miss earns
  // nothing whatever the time; a step the clock answered earns nothing and is
  // not counted as answered at all.
  //
  // Everything is read off the run and the config. The clock is the step's
  // own `timer_ms`, the fractions are the block's, and the times are the ones
  // engine.js recorded on the way through — a funnel that records none, or a
  // run that reached this page from a reload with none, scores its accuracy
  // and nothing else.

  function timedSteps(cfg) {
    var steps = (cfg && cfg.swipe && cfg.swipe.steps) || [];
    return steps.filter(function (step) {
      return typeof step.timer_ms === "number" && step.timer_ms > 0;
    });
  }

  function isHit(pick) {
    var tags = (pick && pick.tags) || [];
    for (var i = 0; i < tags.length; i++) {
      if (/_hit$/.test(String(tags[i]))) return true;
    }
    return false;
  }

  // One step's bonus, as a fraction of a point: full inside `full_frac` of
  // the clock, then linear to nothing at the clock's end.
  function bonusOf(frac, rule) {
    var full = rule.full_frac;
    if (frac <= full) return 1;
    if (full >= 1) return 0;
    return Math.max(0, Math.min(1, (1 - frac) / (1 - full)));
  }

  function speedOf(ctx, block) {
    var rule = (block && block.speed) || null;
    // No table, or a table missing either number, is no speed rule at all:
    // the run scores its accuracy and the page draws no reaction line.
    if (!rule || typeof rule.point_per_step !== "number"
        || typeof rule.full_frac !== "number") return null;
    var times = (ctx && ctx.elapsed) || {};
    var late = (ctx && ctx.timed_out) || [];
    var picks = (ctx && ctx.picks) || {};
    var answered = 0;
    var sumMs = 0;
    var sumFrac = 0;
    var bonus = 0;
    timedSteps(ctx.cfg).forEach(function (step) {
      var ms = times[step.id];
      if (typeof ms !== "number" || late.indexOf(step.id) !== -1) return;
      var frac = ms / step.timer_ms;
      answered += 1;
      sumMs += ms;
      sumFrac += frac;
      if (isHit(picks[step.id])) bonus += bonusOf(frac, rule) * rule.point_per_step;
    });
    // Never more than the table says the timed rounds are worth together,
    // so a config that lists more clocks than it counts cannot pay past
    // its own ceiling.
    var most = (typeof rule.steps === "number" ? rule.steps : answered)
      * rule.point_per_step;
    return {
      bonus: Math.min(most, bonus),
      answered: answered,
      avg_ms: answered ? sumMs / answered : null,
      avg_frac: answered ? sumFrac / answered : null,
      label: answered ? speedLabel(sumFrac / answered, rule) : ""
    };
  }

  // The word for an average, off the table's own thresholds: the first row
  // whose ceiling the average sits under, and the row with no ceiling for
  // everything past the last one. No row means no word.
  function speedLabel(frac, rule) {
    var rows = rule.labels || [];
    for (var i = 0; i < rows.length; i++) {
      var top = rows[i].max_frac;
      if (typeof top !== "number" || frac <= top) return rows[i].label || "";
    }
    return "";
  }

  // The score, out of a hundred, off the same misses the age is off. It is
  // the number the free page shows and the age is the number the report
  // reveals, so the two have to be the same arithmetic on the same run —
  // which is why this takes the profile the age was computed into rather
  // than counting anything again.
  //
  // Every constant is the config's. Nothing here invents a threshold, and
  // nothing anywhere on this page compares the reader to anybody else: there
  // is no population behind this number, and a page that implied one would be
  // making it up.
  function scoreOf(data, block, speed) {
    var rule = (block && block.score) || null;
    if (!rule) return data;
    var raw = (rule.base || 0) + (rule.per_miss || 0) * data.misses
      + (speed ? speed.bonus : 0);
    var floor = typeof rule.floor === "number" ? rule.floor : 0;
    var top = topOf(block);
    data.speed = speed;
    data.score = Math.max(floor, Math.min(top, Math.round(raw)));
    // A round "has room" when it is one the reader dropped points in. The
    // line under the score counts them; it does not rank them.
    var cap = typeof rule.room_round_max_hits === "number"
      ? rule.room_round_max_hits : 2;
    var room = 0;
    DOMAINS.forEach(function (key) {
      if ((data.counts[key] || 0) <= cap) room += 1;
    });
    data.room_rounds = room;
    data.elite = typeof rule.elite_min === "number"
      && data.score >= rule.elite_min;
    return data;
  }

  // What a clean, fast run is worth, and the number the score is drawn out
  // of: the block's own ceiling, falling back to the score table's base on a
  // block that names none.
  function topOf(block) {
    if (block && typeof block.max === "number") return block.max;
    var rule = (block && block.score) || {};
    return typeof rule.base === "number" ? rule.base : 100;
  }

  // --- a) the kicker ---------------------------------------------------------

  function kicker(copy, lean, words) {
    var line = elm("p", "br-kicker", words || copy.kicker || "Your Focus Score");
    // The minimal arm frames it. Real nodes rather than pseudo-elements so
    // the ornament is something a check can find and a translation can drop,
    // and appended only for that arm — the plain kicker is one text node and
    // stays one.
    if (lean) {
      line.className = "br-kicker is-framed";
      line.insertBefore(mark(), line.firstChild);
      line.appendChild(mark());
    }
    return line;
  }

  // The diamond this page already draws on an open node. Reused rather than a
  // second ornament: one funnel, one mark.
  function mark() {
    var node = elm("span", "br-mark", "\u25C6");
    node.setAttribute("aria-hidden", "true");
    return node;
  }

  // Four of them, one to a corner, on the cards the minimal arm treats as
  // keepsakes rather than as panels.
  function corners(card) {
    ["tl", "tr", "bl", "br"].forEach(function (corner) {
      var node = mark();
      node.className = "br-corner is-" + corner;
      card.appendChild(node);
    });
  }

  // The four rounds as capsules, which is what the minimal arm shows instead
  // of four bars — the same four numbers, in the place the eye goes after the
  // headline figure. Each chip is a template in the config filled from the
  // run; one whose token is unanswered is dropped rather than drawn empty.
  function chipWords(ctx, data) {
    var names = (ageBlock(ctx) || {}).domains || {};
    var words = {};
    DOMAINS.forEach(function (key) {
      words[key] = (names[key] || key) + " "
        + Math.min(PER_DOMAIN, data.counts[key] || 0) + "/" + PER_DOMAIN;
    });
    return words;
  }

  function chipRow(ctx, data) {
    var want = profileCopy(ctx).chips || [];
    if (!want.length) return null;
    var words = chipWords(ctx, data);
    var row = elm("ul", "br-chips");
    want.forEach(function (shape) {
      var text = fill(shape, words).replace(/\{\w+\}/g, "").trim();
      if (text) row.appendChild(elm("li", "br-chip", text));
    });
    return row.childNodes.length ? row : null;
  }

  // --- b) the number ---------------------------------------------------------

  // The reaction, in one line: the average over the timed rounds the reader
  // actually answered, and the table's word for it. Nothing about anybody
  // else, and no line at all on a run that answered no timed round.
  function speedLine(data, cls) {
    var speed = data && data.speed;
    if (!speed || !speed.answered || typeof speed.avg_ms !== "number") {
      return null;
    }
    var seconds = (speed.avg_ms / 1000).toFixed(1);
    var text = "Avg reaction: " + seconds + "s";
    if (speed.label) text += " \u2014 " + speed.label;
    return elm("p", (cls || "br-age-note") + " br-speed", text);
  }

  // What the score says about the run, in one line. Two sentences and no
  // third: a run with room in it is told how many rounds have room, and a run
  // without is told it was close. Neither is told where it sits against
  // anybody else, because nobody else has taken this.
  function scoreLine(copy, data) {
    if (data.elite) return copy.score_elite || "";
    if (!data.room_rounds) return copy.score_room_none || "";
    return fill(copy.score_room || "Clear room in {k} of your 4 rounds.",
                { k: data.room_rounds });
  }

  // The hero, on both pages: the Focus Score, out of what the table says a
  // clean run is worth, under the words the config puts over it. The lead is
  // `score_lead`, which this funnel sets to the label FOCUS SCORE.
  function scoreCard(ctx, copy, data, lean) {
    if (typeof data.score !== "number") return null;
    var card = elm("section", "br-score" + (lean ? " is-lux" : ""));
    if (lean) corners(card);
    var lead = copy.score_lead || "";
    if (lead) card.appendChild(elm("p", "br-score-lead", lead));
    var big = elm("p", "br-age br-points");
    big.appendChild(elm("span", "br-age-number", String(data.score)));
    // Out of what the table says a clean, fast run is worth, not out of a
    // hundred this file decided on: the score is the config's arithmetic and
    // so is the number it is out of.
    big.appendChild(elm("span", "br-points-of", "/" + topOf(ageBlock(ctx))));
    card.appendChild(big);
    var line = scoreLine(copy, data);
    if (line) card.appendChild(elm("p", "br-age-note", line));
    var pace = speedLine(data);
    if (pace) card.appendChild(pace);
    var chips = lean ? chipRow(ctx, data) : null;
    if (chips) card.appendChild(chips);
    return card;
  }

  // The fallback for a config with no score table: the block's own formula,
  // drawn the same way, out of the table's ceiling. No word in front of the
  // number and no line under it about anybody else.
  function score(ctx, copy, data, lean) {
    var card = elm("section", "br-score" + (lean ? " is-lux" : ""));
    if (lean) corners(card);
    var lead = copy.score_lead || copy.kicker || "";
    if (lead) card.appendChild(elm("p", "br-score-lead", lead));
    var big = elm("p", "br-age br-points");
    big.appendChild(elm("span", "br-age-number", String(data.age)));
    big.appendChild(elm("span", "br-points-of", "/" + topOf(ageBlock(ctx))));
    card.appendChild(big);
    return card;
  }

  // --- c) the four rounds ----------------------------------------------------

  // Every round at once, so the strongest one is a claim with the other three
  // standing next to it. Out of four rather than as a share of the total: a
  // reader who hit two of four on every round is not "twenty-five percent
  // Memory", they are a reader who hit two of four on every round.
  function bars(ctx, copy, data) {
    var block = ageBlock(ctx) || {};
    var names = block.domains || {};
    var wrap = elm("section", "br-rounds");
    wrap.appendChild(elm("p", "br-rounds-head",
                         copy.balance_title || "Your four rounds"));
    var chart = elm("ul", "br-bars");
    DOMAINS.forEach(function (key) {
      var got = Math.min(PER_DOMAIN, data.counts[key] || 0);
      var row = elm("li", "br-bar");
      row.appendChild(elm("span", "br-bar-name", names[key] || key));
      var track = elm("span", "br-bar-track");
      var fillBar = elm("span", "br-bar-fill");
      // A floor, so a round they scored nothing on is still a labelled row
      // rather than a gap in the chart.
      fillBar.style.width =
        Math.max(4, Math.round(100 * got / PER_DOMAIN)) + "%";
      fillBar.style.background = DOMAIN_COLOR[key] || "#3B7DD8";
      track.appendChild(fillBar);
      row.appendChild(track);
      row.appendChild(elm("span", "br-bar-count", got + "/" + PER_DOMAIN));
      chart.appendChild(row);
    });
    wrap.appendChild(chart);
    return wrap;
  }

  // --- d) the productivity profile -------------------------------------------

  function typeCard(ctx, copy, lean) {
    var essence = (profileCopy(ctx).essence || {})[ctx.style.id] || "";
    var own = profileCopy(ctx).rarity_card || {};
    // The arm that gives the type its own screen gives it a card: the frame
    // of the claim, the name at the size the claim deserves, and one line
    // about what it is worth. A config that declares no such copy falls
    // through to the plain block below, unchanged.
    if (lean && own.lead) {
      var big = elm("section", "br-type is-card");
      corners(big);
      big.appendChild(elm("p", "br-type-lead", own.lead));
      big.appendChild(elm("p", "br-type-figure", ctx.style.name || ""));
      if (own.tail) big.appendChild(elm("p", "br-type-tail", own.tail));
      if (essence) big.appendChild(elm("p", "br-type-essence", essence));
      if (ctx.style.blurb) {
        big.appendChild(elm("p", "br-type-blurb", ctx.style.blurb));
      }
      if (own.note) big.appendChild(noteLines(own.note));
      return big;
    }
    var card = elm("section", "br-type");
    card.appendChild(elm("p", "br-type-label", copy.head_caption
                         || "Four rounds, scored off your own taps."));
    card.appendChild(elm("h1", "br-type-name", ctx.style.name || ""));
    if (essence) card.appendChild(elm("p", "br-type-essence", essence));
    if (ctx.style.blurb) {
      card.appendChild(elm("p", "br-type-blurb", ctx.style.blurb));
    }
    return card;
  }

  // Two centred lines, broken at the em-dash rather than at whatever width
  // the box happens to be. The break is where the sentence turns, so it is
  // the same break in any column — and copy carrying no dash gets one line
  // rather than a guess at where to cut it.
  function noteLines(text) {
    var note = elm("p", "br-type-note");
    var cut = String(text).split("\u2014");
    if (cut.length !== 2) {
      note.textContent = text;
      return note;
    }
    note.appendChild(elm("span", "br-type-note-line", cut[0].trim() + " \u2014"));
    note.appendChild(elm("span", "br-type-note-line", cut[1].trim()));
    return note;
  }

  // --- d2) the reason to keep reading ----------------------------------------
  //
  // The number on its own is a fact. This is the sentence that makes it a
  // thing somebody can do something about, and the control under it is the
  // only other place on the page that goes to the price.
  //
  // It says the same thing three ways because there are three readers: one
  // ahead of their group, one on it, and one behind. None of the three is
  // told anything is wrong with them — the one furthest behind is told they
  // have the most to gain, which is both kinder and true.

  // The offer card, by id, at the moment the button is pressed rather than
  // when it is built: the card is drawn after this block and holding a
  // reference to a node that does not exist yet is how a page ends up with a
  // button that does nothing on the one render where an earlier section threw.
  var OFFER_ID = "br-offer";

  // No line opens this block. Brain once printed a sentence here setting the
  // reader against their age group, and this funnel has no such group: the
  // line under the score has already said what the run left on the table,
  // and this block is the way to act on it.
  function urge(ctx, copy) {
    if (!copy.improve_cta) return null;
    var block = elm("section", "br-urge");
    var button = elm("button", "br-urge-cta",
                     copy.improve_cta || "Improve now");
    button.type = "button";
    // Not a payment control, and it must never be mistaken for one: it moves
    // the page. The button that takes money is engine.js's own, it lives in
    // the offer card, and nothing here touches it.
    button.addEventListener("click", function () {
      var card = document.getElementById(OFFER_ID);
      if (!card) return;
      try {
        card.scrollIntoView({ behavior: "smooth", block: "start" });
      } catch (e) {
        // Older engines take no options object. The reader still gets there.
        card.scrollIntoView();
      }
    });
    block.appendChild(button);
    // One line under the button. It is the answer to the question the button
    // raises — improve how? — and it is the whole promise of the plan in a
    // sentence, with no number in it that nobody has measured.
    if (copy.improve_foot) {
      block.appendChild(elm("p", "br-urge-foot", copy.improve_foot));
    }
    return block;
  }

  // --- d3) handing it to somebody else ----------------------------------------
  //
  // The number is the one thing on this page a reader would say out loud, so
  // the page gives them a way to. It sits under the hero and above the reason
  // to buy, and it is deliberately the quieter of the two controls: outlined
  // where IMPROVE NOW is solid, because what it is competing with is the
  // offer and it must not win.
  //
  // Every word of it is in the config. What gets shared, what the button
  // says, and what it says once the text is on the clipboard are copy, and
  // copy on this platform lives in the funnel.

  // How long the label stays swapped after a copy. Long enough to be read,
  // short enough that a reader who taps twice is not looking at a stale word.
  var COPIED_MS = 2000;

  // Where the challenge points. The origin plus the funnel's own slug rather
  // than this tab's URL: a paid reader is sitting on `/focus?cs=...`, and a
  // friend handed that link would land on somebody else's report.
  function shareUrl(ctx) {
    var slug = (ctx.cfg && ctx.cfg.slug) || "";
    if (!slug) return "";
    try {
      return window.location.origin + "/" + slug;
    } catch (e) {
      return "/" + slug;
    }
  }

  function share(ctx, data) {
    var table = profileCopy(ctx);
    if (!table.share_cta || !table.share_line || !data) return null;
    // The score, not the age. This is the free page's control and the free
    // page does not know the age out loud — and a number out of a hundred is
    // the one a friend can be beaten on, which is what the line asks for.
    if (typeof data.score !== "number") return null;
    var text = fill(table.share_line, { n: data.score });
    var url = shareUrl(ctx);

    var block = elm("section", "br-share");
    var button = elm("button", "br-share-cta", table.share_cta);
    button.type = "button";
    var timer = null;

    function said(word) {
      button.textContent = word;
      clearTimeout(timer);
      timer = setTimeout(function () {
        button.textContent = table.share_cta;
      }, COPIED_MS);
    }

    button.addEventListener("click", function () {
      // One event, on the tap, whichever way the handing-over goes. It says
      // somebody pressed it and nothing else: no number, no session, nothing
      // about the reader. What they shared is on their own phone.
      try {
        ctx.track("share_tap");
      } catch (e) { /* an event is not worth losing the page to */ }
      var payload = { text: text, url: url };
      if (navigator.share) {
        // The sheet is the phone's, and a reader who backs out of it has not
        // done anything wrong — the rejection is swallowed rather than shown.
        try {
          navigator.share(payload).catch(function () {});
          return;
        } catch (e) { /* fall through to the clipboard */ }
      }
      var full = url ? (text + " " + url) : text;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(full).then(function () {
          said(table.share_copied || table.share_cta);
        }, function () { said(table.share_copied || table.share_cta); });
        return;
      }
      said(table.share_copied || table.share_cta);
    });

    block.appendChild(button);
    return block;
  }

  // --- e) the frames they tapped ---------------------------------------------
  //
  // Eighteen squares, one per round, in the order they were played. The strip
  // is a record of the walk rather than a contact sheet of the art, and a
  // round the clock answered is not a round anybody played: it gets a cross
  // rather than a picture of a card nobody chose.

  // Which tile stands for a round is the engine's rule, not this page's. It
  // draws the same tiles between rounds and on the analysing screen, and two
  // copies of "what does this round show" would be two answers the moment one
  // of them was edited. `ctx.tile` is that rule; this reads it. On this funnel
  // every round is answered on the card that was tapped, so the rule is the
  // plain one — but it is still read rather than assumed.
  //
  // The fallback is for an engine.js cached from before it shipped: a tile of
  // the card that was tapped, which is what this strip drew before the
  // stand-ins were added and is never wrong, only less interesting.
  function tileOf(ctx, index, stepId, item, late) {
    if (typeof ctx.tile === "function") {
      return ctx.tile(index, stepId, item, late);
    }
    return { img: (item && item.img) || null };
  }

  function tapsGrid(cells) {
    var row = elm("ul", "br-taps-grid");
    cells.forEach(function (cell) {
      var item = elm("li", "br-tap");
      if (!cell.img) {
        // The cross, drawn as two bars the stylesheet crosses — the same
        // mark, in the same red, that covered the cards when the clock ran
        // out. One idea, twice.
        item.className = "br-tap is-out";
        var mark = elm("span", "br-tap-out");
        mark.setAttribute("aria-hidden", "true");
        mark.appendChild(elm("i"));
        mark.appendChild(elm("i"));
        item.appendChild(mark);
        row.appendChild(item);
        return;
      }
      var img = document.createElement("img");
      img.src = cell.img;
      img.alt = "";
      img.loading = "lazy";
      img.decoding = "async";
      item.appendChild(img);
      row.appendChild(item);
    });
    return row;
  }

  function tapsBlock(copy, cells) {
    if (cells.length < TAPS_MIN) return null;
    var block = elm("section", "br-taps");
    block.appendChild(elm("p", "br-taps-caption",
                          copy.taps_caption || "Read from your rounds:"));
    block.appendChild(tapsGrid(cells));
    return block;
  }

  // Step order, because that is the order the reader put them there. A step
  // they somehow did not answer is absent rather than drawn as a gap; a step
  // the clock answered is present, and crossed.
  function taps(ctx, copy) {
    var steps = (ctx.cfg && ctx.cfg.swipe && ctx.cfg.swipe.steps) || [];
    var out = [];
    var late = ctx.timed_out || [];
    steps.forEach(function (step, index) {
      var pick = ctx.picks[step.id];
      if (!pick || !pick.img) return;
      out.push(tileOf(ctx, index, step.id, pick, late));
    });
    return tapsBlock(copy, out);
  }

  // The same strip after the money, off the ids the report carries. The two
  // substitutions are the same two: a stand-in where the config names one,
  // and a cross where the report says the clock answered.
  function deliveredTaps(ctx, copy) {
    var want = (ctx.visuals && ctx.visuals.taps) || [];
    var late = (ctx.visuals && ctx.visuals.timed_out) || [];
    var steps = (ctx.cfg && ctx.cfg.swipe && ctx.cfg.swipe.steps) || [];
    var out = [];
    want.forEach(function (id, index) {
      var pick = ctx.images[id];
      if (!pick || !pick.img) return;
      var step = steps[index];
      out.push(tileOf(ctx, index, step && step.id, pick, late));
    });
    return tapsBlock(copy, out);
  }

  // --- f) what the report answers --------------------------------------------
  //
  // The same node path the persona page draws, in this funnel's own words: one
  // row per section, each shut, each with the line the config wrote for it.
  // The row the reader is most likely to have come for goes first — which
  // round they said they were on before they played is the only thing this
  // page knows about their reason for being here.

  var LOCK_PATH = "M5 8V5.5a3 3 0 0 1 6 0V8M4 8h8v6H4z";

  function node(kind, title) {
    var item = elm("li", "br-node is-" + kind);
    var mark = elm("span", "br-node-mark");
    mark.setAttribute("aria-hidden", "true");
    if (kind === "open") {
      // A rule in the accent, the same mark the printed chapter opens on. It
      // was a filled lozenge, which is a bullet, and a bullet in front of a
      // chapter heading says the heading is one item in a list.
      mark.className = "br-node-mark is-rule";
    } else {
      var svg = svgEl("svg", { viewBox: "0 0 16 16" });
      svg.appendChild(svgEl("path", {
        d: LOCK_PATH, "stroke-linejoin": "round"
      }));
      mark.appendChild(svg);
    }
    item.appendChild(mark);
    var body = elm("div", "br-node-body");
    body.appendChild(elm("h2", "br-node-title", title || ""));
    item.appendChild(body);
    return item;
  }

  // Gated on `result_copy.purpose_map` being in the config, so a funnel
  // carrying no such block renders with no personalisation at all rather than
  // differently. Found by tag rather than by step id: which question asks how
  // sharp somebody feels is the funnel's business, and a module naming the
  // step would stop working the day the step was renamed.
  function purposeMap(ctx) {
    var map = copyOf(ctx).purpose_map;
    return (map && typeof map === "object") ? map : null;
  }

  function purposeTag(ctx, map) {
    var picks = (ctx && ctx.picks) || {};
    var ids = Object.keys(picks);
    for (var i = 0; i < ids.length; i++) {
      var tags = (picks[ids[i]] && picks[ids[i]].tags) || [];
      for (var j = 0; j < tags.length; j++) {
        if (Object.prototype.hasOwnProperty.call(map, tags[j])) return tags[j];
      }
    }
    return "";
  }

  // After the money there is no run left to read: the tag is stored on the
  // report and handed back, which is why this looks in two places.
  function purposeRule(ctx) {
    var map = purposeMap(ctx);
    if (!map) return null;
    var tag = (ctx && ctx.purpose) || purposeTag(ctx, map);
    var rule = tag && map[tag];
    return (rule && typeof rule === "object") ? rule : null;
  }

  function emphasised(rule) {
    return (rule && rule.emphasized_section) || "";
  }

  // Only the first match moves — a list that reshuffled twice would stop
  // reading as a document with an order at all — and a name that matches
  // nothing leaves the list exactly as it was.
  function firstly(sections, want) {
    if (!want) return sections;
    var hit = null;
    var rest = [];
    sections.forEach(function (section) {
      if (!hit && section.id === want) hit = section;
      else rest.push(section);
    });
    return hit ? [hit].concat(rest) : sections;
  }

  function keywordOf(ctx, section_id) {
    var cards = profileCopy(ctx).cards || [];
    for (var i = 0; i < cards.length; i++) {
      if (cards[i].id === section_id) return cards[i].key || "";
    }
    return "";
  }

  function locked(ctx, section, copy, isLead) {
    var item = node("locked", section.title);
    if (isLead) item.classList.add("is-lead");
    var body = item.querySelector(".br-node-body");
    var key = keywordOf(ctx, section.id);
    if (key) {
      body.insertBefore(elm("p", "br-node-key", key + ":"), body.firstChild);
    }
    var line = typeof ctx.fillHook === "function"
      ? ctx.fillHook(section.teaser_line || "") : (section.teaser_line || "");
    if (line) body.appendChild(elm("p", "br-teaser", line));
    var lock = elm("span", "br-lock", copy.locked_note || "Locked");
    lock.setAttribute("aria-hidden", "true");
    item.appendChild(lock);
    return item;
  }

  function path(ctx, copy) {
    var list = elm("ol", "br-path");
    var want = emphasised(purposeRule(ctx));
    var shut = ctx.sections.filter(function (s) { return s.locked; });
    firstly(shut, want).forEach(function (section) {
      list.appendChild(locked(ctx, section, copy, section.id === want));
    });
    return list;
  }

  // --- paywall variants ------------------------------------------------------
  //
  // The persona funnel's mechanism, carried across without a persona word in
  // it, which is what it was built to allow. A variant is
  // `{ id, enabled, weight, name, frame, benefits, cta_text }` and the config
  // is a list of them; adding one, or turning one off, is an edit to that list
  // and nothing else.

  // engine.js's own session key. Read, never written: the id already exists by
  // the time a result page renders, it is the id every event on this session
  // carries, and assignment has to agree with what the events say.
  var SESSION_KEY = "mazzin_sid";

  function variantWeight(variant) {
    var weight = typeof variant.weight === "number" ? variant.weight : 1;
    return weight > 0 ? weight : 0;
  }

  function variantPool(cfg) {
    return ((cfg && cfg.paywall_variants) || []).filter(function (variant) {
      return variant && variant.id
        && variant.enabled !== false && variantWeight(variant) > 0;
    });
  }

  function sessionKey() {
    try {
      return window.sessionStorage.getItem(SESSION_KEY) || "";
    } catch (e) {
      // Private mode, or storage the browser will not hand over. Everyone in
      // that state lands on the same variant rather than on a random one: a
      // coin flipped per page load would show a reader one frame on the free
      // page and the other on the delivered one.
      return "";
    }
  }

  // FNV-1a, 32-bit. Any stable hash would do; what matters is that it reads
  // the session id and nothing else, so a variant cannot rotate with a
  // campaign parameter and the list stays the only thing that decides.
  function hashOf(text) {
    var hash = 0x811c9dc5;
    for (var i = 0; i < text.length; i++) {
      hash ^= text.charCodeAt(i);
      hash = (hash + ((hash << 1) + (hash << 4) + (hash << 7)
                      + (hash << 8) + (hash << 24))) >>> 0;
    }
    return hash >>> 0;
  }

  function assignedVariant(cfg) {
    var pool = variantPool(cfg);
    if (!pool.length) return null;
    // One enabled variant is not a test and must not be treated as one: it
    // renders unconditionally, whatever it weighs and whatever the hash says.
    if (pool.length === 1) return pool[0];
    var total = 0;
    var i;
    for (i = 0; i < pool.length; i++) total += variantWeight(pool[i]);
    if (total <= 0) return pool[0];
    var point = (hashOf(sessionKey()) % 100000) / 100000 * total;
    var seen = 0;
    for (i = 0; i < pool.length; i++) {
      seen += variantWeight(pool[i]);
      if (point < seen) return pool[i];
    }
    return pool[pool.length - 1];
  }

  // One event, once, when the offer is drawn: which variant this session was
  // shown. Everything downstream already carries `session_id`, so conversion
  // splits by variant on a join rather than on a column added to every event.
  // Not fired on the delivered page: that page is past the money and a second
  // row would double-count the arm.
  var variantReported = false;

  function reportVariant(ctx, variant) {
    if (!variant || variantReported) return;
    variantReported = true;
    try {
      // The name is written out rather than held in a constant: the suite
      // pairs tracking.py's allowlist against the literals the client actually
      // emits, and an event that only exists as an identifier reads there as a
      // dead name in the allowlist.
      ctx.track("paywall_variant", { variant: variant.id });
    } catch (e) { /* an arm is not worth losing the page to */ }
  }

  function variantBlock(variant) {
    if (!variant) return null;
    var block = elm("section", "br-variant");
    block.setAttribute("data-variant", variant.id);
    if (variant.name) {
      block.appendChild(elm("h2", "br-variant-name", variant.name));
    }
    if (variant.frame) {
      block.appendChild(elm("p", "br-variant-frame", variant.frame));
    }
    var lines = variant.benefits || [];
    if (lines.length) {
      var list = elm("ul", "br-variant-benefits");
      lines.forEach(function (line) {
        list.appendChild(elm("li", "br-variant-benefit", line));
      });
      block.appendChild(list);
    }
    return block;
  }

  // The button's label belongs to engine.js: it writes `payButton.textContent`
  // from `cfg.checkout.cta_label` and rewrites it every time the consent box
  // changes. So the variant does not write the button — it writes what
  // engine.js reads, and then asks engine.js to read it. This is the one place
  // in this file that writes anything back into the config.
  function applyVariantCta(ctx, variant) {
    if (!variant || !variant.cta_text) return;
    ctx.cfg.checkout.cta_label = variant.cta_text;
    var consent = ctx.nodes && ctx.nodes.consent;
    var box = consent && consent.querySelector("input[type=checkbox]");
    if (box) box.dispatchEvent(new Event("change", { bubbles: true }));
  }


  // --- e) the offer ----------------------------------------------------------
  //
  // v11 rebuilt it. It used to be a list of five ticked rows on the card and
  // the same five again as a manifest under the button — the same promise in
  // two voices, in two places, neither of which said which round THIS reader
  // dropped points in.
  //
  // Now it argues in one order: what the plan is, what this run left on the
  // table, the number it is holding back, the four things it contains, the
  // price, the button, what it is not, and one comparison at the very bottom.

  // The four things the plan is, as four marks. Inline paths rather than
  // files: they are four shapes at one weight in one colour, and a request
  // per icon on the screen that decides a sale is a request too many.
  // Stroked in `currentColor`, so the card's own colour reaches them.
  var OFFER_ICONS = {
    // a ring with its own centre: the round with the most room in it
    target: ["M12 4.2a7.8 7.8 0 1 0 0 15.6 7.8 7.8 0 0 0 0-15.6z",
             "M12 8.6a3.4 3.4 0 1 0 0 6.8 3.4 3.4 0 0 0 0-6.8z"],
    // seven days with a bar across the top
    calendar: ["M4.6 6.8h14.8v12.4H4.6z", "M4.6 10.6h14.8",
               "M8.6 4.4v3.2", "M15.4 4.4v3.2"],
    // the bolt this funnel already draws on its sharpest mood card
    bolt: ["M13.4 3.6 6.8 13.2h4.3l-.9 7.2 6.8-9.8h-4.3z"],
    // a plate seen from above: the rim, the well inside it, and a leaf
    plate: ["M12 4.2a7.8 7.8 0 1 0 0 15.6 7.8 7.8 0 0 0 0-15.6z",
            "M12 7.4a4.6 4.6 0 1 0 0 9.2 4.6 4.6 0 0 0 0-9.2z",
            "M9.9 14.1c-.5-2.3.9-4.2 3.6-4.6.5 2.4-.9 4.3-3.6 4.6z",
            "M9.9 14.1 13.9 9.9"]
  };

  function offerIcon(name) {
    var chip = elm("span", "br-benefit-icon");
    chip.setAttribute("aria-hidden", "true");
    var svg = svgEl("svg", { viewBox: "0 0 24 24" });
    (OFFER_ICONS[name] || OFFER_ICONS.bolt).forEach(function (d) {
      svg.appendChild(svgEl("path", {
        d: d, "stroke-linecap": "round", "stroke-linejoin": "round"
      }));
    });
    chip.appendChild(svg);
    return chip;
  }

  // The round this reader dropped the most points in, by name. Fewest hits
  // wins, and a tie goes to the earliest of the four — so the same run always
  // names the same round, here and in the report.
  function weakestRound(ctx, data) {
    var names = (ageBlock(ctx) || {}).domains || {};
    var worst = null;
    DOMAINS.forEach(function (key) {
      var got = (data.counts || {})[key] || 0;
      if (worst === null || got < worst.got) worst = { key: key, got: got };
    });
    return worst ? (names[worst.key] || worst.key) : "";
  }

  // The line under the head. A run with room in it is told where the room is;
  // a run without is told it was close. Neither is told anything about
  // anybody else — there is nobody else.
  function offerPersonal(ctx, data) {
    var table = profileCopy(ctx);
    if (!data) return null;
    if (data.elite || !data.room_rounds) {
      var close = table.offer_personal_elite || "";
      return close ? elm("p", "br-offer-personal", close) : null;
    }
    var text = table.offer_personal || "";
    if (!text) return null;
    var round = weakestRound(ctx, data);
    var line = elm("p", "br-offer-personal");
    var cut = text.split("{round}");
    line.appendChild(document.createTextNode(cut[0]));
    line.appendChild(elm("strong", "br-offer-round", round));
    line.appendChild(document.createTextNode(cut.slice(1).join(round)));
    return line;
  }

  // The thing being sold, as a tile of what it is not showing. The number is
  // two hashes and never a computed age: this page does not know the age out
  // loud, and a placeholder that happened to be the real figure would be the
  // reveal given away on the card selling it.
  function offerHero(ctx) {
    var table = profileCopy(ctx);
    if (!table.offer_hero_line) return null;
    var block = elm("div", "br-hero");
    var tile = elm("div", "br-hero-tile");
    tile.setAttribute("aria-hidden", "true");
    tile.appendChild(elm("span", "br-hero-hash", "##"));
    tile.appendChild(elm("span", "br-hero-lock", "LOCKED"));
    block.appendChild(tile);
    var words = elm("div", "br-hero-words");
    if (table.offer_hero_kicker) {
      words.appendChild(elm("p", "br-hero-kicker", table.offer_hero_kicker));
    }
    words.appendChild(elm("p", "br-hero-line", table.offer_hero_line));
    block.appendChild(words);
    return block;
  }

  // What the plan is, in four. Each one a mark, a name and a line — the same
  // four the report's own chapters are, said in the fewest words that still
  // say what a reader gets to DO.
  function offerBenefits(ctx) {
    var rows = profileCopy(ctx).offer_cards || [];
    if (!rows.length) return null;
    var grid = elm("ul", "br-benefits");
    rows.forEach(function (row) {
      var cell = elm("li", "br-benefit");
      cell.appendChild(offerIcon(row.icon));
      cell.appendChild(elm("p", "br-benefit-title", row.title || ""));
      cell.appendChild(elm("p", "br-benefit-sub", row.sub || ""));
      grid.appendChild(cell);
    });
    return grid;
  }

  function offerChips(ctx) {
    var rows = profileCopy(ctx).offer_chips || [];
    if (!rows.length) return null;
    var row = elm("ul", "br-offer-chips");
    rows.forEach(function (text) {
      row.appendChild(elm("li", "br-offer-chip", text));
    });
    return row;
  }


  // --- g) the offer ----------------------------------------------------------
  //
  // engine.js has already built and wired all of this. What happens here is
  // placement: the consent box, the button, its error line and the legal links
  // are moved into this card, which is why the withdrawal waiver still gates
  // the same button it always did and no payment code lives in here.

  function offer(ctx, copy, data, variant, lean) {
    var card = elm("section", "br-offer");
    card.id = OFFER_ID;
    var nodes = ctx.nodes;

    var head = ctx.withPrice(fill(profileCopy(ctx).offer_head || "",
                                  { type: ctx.style.name || "" }));
    if (head) card.appendChild(elm("p", "br-offer-head", head));

    // v11: the card argues in one order, top to bottom. The head says what
    // the plan is; one line says what THIS run left on the table; the hero
    // tile says what is being held back; four marks say what the plan
    // contains; then the price, the button, what it is not, and the anchor.
    //
    // It replaces a list of ticked rows and a manifest that said the same
    // five things twice, in two places, in two voices.
    var personal = offerPersonal(ctx, data);
    if (personal) card.appendChild(personal);
    var hero = offerHero(ctx);
    if (hero) card.appendChild(hero);
    var grid = offerBenefits(ctx);
    if (grid) card.appendChild(grid);

    // The price, and the order of the argument around it. The reader's own
    // price is the thing they are deciding about, so it is the loudest text
    // here by a distance; the anchor is one muted line above it, doing the
    // work of a footnote.
    var anchorText = ctx.withPrice(ctx.commerce.price_anchor
                                   || ctx.commerce.anchor_head
                                   || ctx.cfg.checkout.anchor_head || "");
    var accent = ctx.commerce.price_anchor_accent
      || ctx.commerce.anchor_head_accent || "";
    var anchor = elm("p", "br-anchor");
    if (accent && anchorText.indexOf(accent) !== -1) {
      var cut = anchorText.split(accent);
      anchor.appendChild(document.createTextNode(cut[0]));
      anchor.appendChild(elm("span", "br-accent", accent));
      anchor.appendChild(document.createTextNode(cut.slice(1).join(accent)));
    } else {
      anchor.textContent = anchorText;
    }

    // `ctx.price` is already whatever the checkout is about to charge —
    // engine.js resolves the sale before it fills a single {price} — so the
    // figure needs no arithmetic here. What a sale adds is the comparison
    // beside it: the regular price, struck, and one line naming the offer.
    //
    // `ctx.sale` is null unless a sale is genuinely running, and it is null
    // for a block whose claimed regular price is not this funnel's own. So
    // there is no state in which this draws a struck figure that is not the
    // price this product sells at the rest of the year.
    var price = elm("p", "br-price");
    price.appendChild(elm("span", "br-price-now", ctx.price));
    if (ctx.sale && ctx.priceRegular) {
      var was = elm("span", "br-price-was", ctx.priceRegular);
      // Said as well as struck: a line through a number is a visual
      // convention a screen reader does not read out.
      was.setAttribute("aria-label",
                       fill(copy.price_regular_aria || "Regular price {price}",
                            { price: ctx.priceRegular }));
      price.appendChild(was);
    }
    var note = ctx.commerce.price_note || "";
    if (note) price.appendChild(elm("span", "br-price-note", note));
    card.appendChild(price);
    if (ctx.sale && ctx.sale.label) {
      // The offer's name, and nothing else at all. No clock counting down and
      // no closing date: a date on a card is a promise about a config value,
      // and an offer that gets extended twice has spent that promise. The
      // block still ends on its own clock; the page does not make a date part
      // of the pitch.
      card.appendChild(elm("p", "br-sale", ctx.sale.label));
    }


    // The one line under the anchor, in the reader's own terms when the run
    // said which round they thought they were on. Everything else on this card
    // — the price, the button, the trust row, the consent — is untouched by it.

    var frame = variantBlock(variant);
    if (frame) card.appendChild(frame);

    // Live nodes, not copies of them. The consent box is placed only where a
    // funnel asks for one: `withdrawal_consent: false` takes it off the page
    // for everybody. Taken off, it still has to be satisfied — it is what
    // enables the pay button — so it is ticked here rather than left to
    // whatever `consent_prechecked` happens to say. A hidden control that
    // disables the only button on the page is a page that looks broken.
    var wantsConsent = ctx.cfg.checkout.withdrawal_consent !== false;
    if (!wantsConsent && nodes.consent) {
      var box = nodes.consent.querySelector("input[type=checkbox]");
      if (box && !box.checked) {
        box.checked = true;
        box.dispatchEvent(new Event("change", { bubbles: true }));
      }
      nodes.consent.hidden = true;
    }
    // The wallet above the button it replaces, so the order a reader takes the
    // block in — what it costs, how to pay, what it is not — is the same
    // whether the fast path appeared or not.
    [wantsConsent ? nodes.consent : null, nodes.walletSummary, nodes.wallet,
     nodes.payButton, nodes.payError]
      .forEach(function (n) { if (n) card.appendChild(n); });

    var chips = offerChips(ctx);
    if (chips) card.appendChild(chips);
    var trust = (ctx.commerce.trust || ctx.cfg.checkout.trust || []);
    if (trust.length) {
      card.appendChild(elm("p", "br-trust", trust.join(" · ")));
    }
    if (nodes.legal) card.appendChild(nodes.legal);
    // Last, and quietest: the one comparison on the card, and the only line
    // on it about anything other than this reader's own run.
    card.appendChild(anchor);

    // The rows this layout does not use. Hidden rather than removed: they are
    // the same elements the paid view and the two-screen flow still want.
    [nodes.manifest, nodes.anchor, nodes.price, nodes.trust]
      .forEach(function (n) { if (n) n.hidden = true; });

    // This card is the offer now. engine.js fires `paywall_view` and Meta's
    // InitiateCheckout when the offer reaches the reader and watches whichever
    // node it is told to; naming the card is the whole of it. Guarded because
    // this file and engine.js sit behind a CDN and can be a version apart: an
    // engine without the hook draws the same page and only loses the event.
    if (typeof ctx.watchOffer === "function") ctx.watchOffer(card);
    return card;
  }

  // --- render ----------------------------------------------------------------

  function render(root, ctx) {
    var copy = copyOf(ctx);
    var data = profileOf(ctx);

    // Chosen before the offer is drawn, so the card and the button it contains
    // argue the same offer, and reported here, before a single node is built:
    // `mod.render` runs inside a try/catch that falls back to engine's own
    // page, so a throw anywhere below would otherwise lose this event while
    // `paywall_view` went on firing. Assignment is a pure function of the
    // session id and needs nothing that can throw, so the report goes with it.
    var variant = assignedVariant(ctx.cfg);
    reportVariant(ctx, variant);

    // The layout, named by the config outright rather than assigned. A
    // funnel that names none draws the page this file has always drawn.
    var lean = template(ctx) === "minimal";

    root.innerHTML = "";
    // The arm goes on the container rather than inside it, so every rule the
    // minimal layout adds hangs off one class and the plain page keeps its
    // stylesheet without matching any of them.
    root.classList.toggle("is-minimal", lean);
    root.appendChild(kicker(copy, lean, copy.score_kicker));
    // The order this page argues in: the score, what it says about the run,
    // which rounds produced it, the frames they tapped, and then the price —
    // where the age is the first thing named.
    //
    // On the minimal arm the four bars are gone — the chips inside the hero
    // are the same four numbers, and a page whose argument is brevity cannot
    // afford to say a thing twice — and so are the locked rows, which were
    // doing the offer's job above the offer. What the report contains is said
    // once, on the offer card, next to the price.
    if (data) {
      // The Focus Score, which is the one number this funnel has. A config
      // with no score table falls back to the block's own formula, drawn the
      // same way.
      var head = scoreCard(ctx, copy, data, lean)
        || score(ctx, copy, data, lean);
      root.appendChild(head);
      if (!lean) root.appendChild(bars(ctx, copy, data));
      // The one thing on this page somebody would say out loud, and the way
      // to say it. Above the reason to buy, because a reader who has just
      // been given a number is at their most likely to hand it on, and
      // quieter than that reason, because it must not win against it.
      var hand = share(ctx, data);
      if (hand) root.appendChild(hand);
      // What the number is worth doing something about, and the way down to
      // the offer. Straight under the figure, because everything between a
      // number and the reason to act on it is a reason to stop reading.
      var push = urge(ctx, copy);
      if (push) root.appendChild(push);
    }
    // The profile card is not drawn on this page. It is still computed — the
    // report is written for it and the delivered page still draws it — but
    // before the money it was a second identity card under the first, and
    // what it said about the reader is what the report is for.
    var strip = taps(ctx, copy);
    if (strip) root.appendChild(strip);
    if (!lean) root.appendChild(path(ctx, copy));
    root.appendChild(offer(ctx, copy, data, variant, lean));
    applyVariantCta(ctx, variant);

    // The container engine.js moved the offer rows into is empty now and its
    // own border would draw a line under nothing.
    if (ctx.nodes.commerce) ctx.nodes.commerce.hidden = true;
    root.hidden = false;
  }

  // --- the delivered report --------------------------------------------------
  //
  // The same page after the money, opened in a tab that never ran the quiz.
  // Everything the free page computed off the run is gone by then, so the head
  // is rebuilt from what the report stored: `visuals.brain` is this file's own
  // block, written server-side while the run still existed. A report without
  // one — every report written before that shipped — gets the type card and no
  // arithmetic, which is honest rather than invented.

  function storedProfile(ctx) {
    var stored = (ctx.visuals && ctx.visuals.brain) || null;
    if (!stored || typeof stored.age !== "number") return null;
    var counts = {};
    DOMAINS.forEach(function (key) {
      counts[key] = Math.max(0, (stored.counts || {})[key] || 0);
    });
    return {
      age: stored.age,
      hits: stored.hits || 0,
      misses: stored.misses || 0,
      scored: stored.scored || 16,
      counts: counts,
      // Off the report, never recomputed here: the stored row is the single
      // record of what this run scored, and a page that worked it out again
      // would be a second opinion about a number somebody paid for.
      score: typeof stored.score === "number" ? stored.score : null,
      room_rounds: typeof stored.room_rounds === "number"
        ? stored.room_rounds : 0,
      elite: !!stored.elite,
      // The reaction, as the report stored it: the average and the word
      // were measured on the server from the times the order carried, and
      // this page draws them back rather than working anything out — the
      // tab it opens in never played a round. A report without one, or a
      // purchase whose order carried no times, draws no line.
      speed: (stored.speed && typeof stored.speed.avg_ms === "number"
              && stored.speed.answered) ? stored.speed : null
    };
  }

  var CHECK_PATH = "M3.5 8.6l3.1 3.1 5.9-6.4";

  // The first thing a buyer sees, on both ways in: seconds after paying, and a
  // week later from the link in the mail. The past tense is what makes one
  // line true on both. The address comes off the authenticated report payload
  // and is never touched again — not tracked, not stored by this page.
  function deliveryNote(ctx, copy) {
    if (!ctx.delivered) return null;
    var email = (((ctx.visuals || {}).delivery || {}).email || "").trim();
    var line = copy.delivery_line || "Your PDF was sent to {email}";
    var bare = copy.delivery_line_bare || "Your PDF was sent to your email";

    var bar = elm("p", "br-sent");
    var mark = elm("span", "br-sent-check");
    mark.setAttribute("aria-hidden", "true");
    var svg = svgEl("svg", { viewBox: "0 0 16 16" });
    svg.appendChild(svgEl("path", {
      d: CHECK_PATH, "stroke-linecap": "round", "stroke-linejoin": "round"
    }));
    mark.appendChild(svg);
    bar.appendChild(mark);

    var text = elm("span", "br-sent-text");
    if (!email || line.indexOf("{email}") === -1) {
      text.textContent = bare;
    } else {
      var cut = line.split("{email}");
      text.appendChild(document.createTextNode(cut[0]));
      text.appendChild(elm("span", "br-sent-mail", email));
      text.appendChild(document.createTextNode(cut.slice(1).join("{email}")));
    }
    bar.appendChild(text);
    return bar;
  }

  // A section body, in whatever shape the report wrote it.
  //
  // Four shapes reach this page, because BRAIN_PROFILE writes four: the
  // profile chapter is paragraphs and arrow lines, the weakest-round chapter
  // is an opening, a badged table of the four rounds and a closing drill, the
  // strengths are numbered items, and the plan is eight named days.
  //
  // It used to render two of them. `items` was read as `{title, body, fix}`
  // only, so the plan's `{name, priority_note}` rows came out as eight empty
  // numbers, and `pairs` was not read at all — which took the round table off
  // the one chapter whose whole argument is that table. Both are the paid
  // half of the document, and both were missing from it.
  function sectionBody(data) {
    var frag = document.createDocumentFragment();
    if (typeof data === "string") {
      frag.appendChild(elm("p", "br-body", data));
      return frag;
    }
    (data.narrative || []).forEach(function (para) {
      frag.appendChild(elm("p", "br-body", para));
    });
    if (data.intro) frag.appendChild(elm("p", "br-body", data.intro));

    // The four rounds, badged. The word inside the badge is the profile's —
    // "AVOID" over the round somebody is being told to practise is the
    // document arguing with its own plan — so it is read off the config the
    // same way the offer's copy is, and falls back to the schema's own word.
    (data.pairs || []).forEach(function (pair) {
      var row = elm("div", "br-verdict");
      var head = elm("p", "br-verdict-head");
      head.appendChild(elm("span", "br-combo", pair.combo || ""));
      head.appendChild(elm("span", "br-badge-verdict is-" + (pair.verdict
                                                             || "works"),
                           verdictWord(pair.verdict)));
      row.appendChild(head);
      if (pair.why) row.appendChild(elm("p", "br-body", pair.why));
      frag.appendChild(row);
    });

    var items = data.items || data.implications || [];
    if (items.length) frag.appendChild(itemList(items));
    // The drill the weakest-round chapter closes on, and the one paragraph on
    // it that the reader is meant to act on tomorrow morning. A card with a
    // clock on it: under a shared left rule it read as one more closing line,
    // and it is the thing the whole plan is built on.
    if (data.rule) frag.appendChild(drillCard(data.rule));
    (data.skip || []).forEach(function (row) {
      frag.appendChild(elm("p", "br-note",
                           [row.name, row.why].filter(Boolean).join(" — ")));
    });
    if (data.closing_rule) {
      frag.appendChild(elm("p", "br-note", data.closing_rule));
    }
    return frag;
  }

  function drillCard(text) {
    var card = elm("div", "br-drill");
    var head = elm("p", "br-drill-head");
    var mark = elm("span", "br-drill-glyph");
    mark.setAttribute("aria-hidden", "true");
    var svg = svgEl("svg", { viewBox: "0 0 16 16" });
    svg.appendChild(svgEl("circle", { cx: "8", cy: "8", r: "6.3" }));
    svg.appendChild(svgEl("path", {
      d: GLYPH_CLOCK, "stroke-linecap": "round"
    }));
    mark.appendChild(svg);
    head.appendChild(mark);
    head.appendChild(document.createTextNode("The two-minute drill"));
    card.appendChild(head);
    card.appendChild(elm("p", "br-drill-body", text));
    return card;
  }

  // The words a day about food is written in, and the same two-hit rule the
  // document uses: one is a coincidence, and a memory drill about a shopping
  // list says "list" and "shop" and never says anybody ate anything.
  var FUEL_WORDS = ["eat", "eating", "ate", "breakfast", "lunch", "dinner",
                    "snack", "plate", "meal", "food", "supermarket", "toast",
                    "fish", "sardines", "walnuts", "nuts", "eggs", "yoghurt",
                    "yogurt", "fruit", "cheese", "porridge", "oats", "beans",
                    "supper"];

  function isFuel(text) {
    var words = String(text || "").toLowerCase().match(/[a-z]+/g) || [];
    var seen = {};
    var hits = 0;
    words.forEach(function (word) {
      if (FUEL_WORDS.indexOf(word) === -1 || seen[word]) return;
      seen[word] = true;
      hits += 1;
    });
    return hits >= 2;
  }

  var DAY_NAME = /^\s*Day\s+(\d+)\s*[-\u2013\u2014:]\s*(.+)$/;

  // A day, as a card. Eight numbered paragraphs is a wall of text, and the
  // day is the unit somebody reads a week in.
  function dayCard(item, index, last) {
    var got = DAY_NAME.exec(item.name || "");
    var fuel = isFuel((item.name || "") + " " + (item.priority_note || ""));
    var card = elm("li", "br-day"
                   + (index === last ? " is-last" : (fuel ? " is-fuel" : "")));
    var head = elm("p", "br-day-head");
    head.appendChild(elm("span", "br-day-n",
                         got ? got[1] : String(index + 1)));
    head.appendChild(elm("span", "br-day-name", got ? got[2] : item.name));
    if (fuel) head.appendChild(plateGlyph());
    card.appendChild(head);
    if (item.priority_note) {
      card.appendChild(elm("p", "br-body", item.priority_note));
    }
    return card;
  }

  function plateGlyph() {
    var mark = elm("span", "br-day-glyph");
    mark.setAttribute("aria-hidden", "true");
    var svg = svgEl("svg", { viewBox: "0 0 20 16" });
    svg.appendChild(svgEl("circle", { cx: "12.4", cy: "8", r: "5.6" }));
    svg.appendChild(svgEl("circle", { cx: "12.4", cy: "8", r: "2.5" }));
    svg.appendChild(svgEl("path", {
      d: GLYPH_PLATE, "stroke-linecap": "round"
    }));
    svg.appendChild(svgEl("path", {
      d: "M3 2.4v2.4M6 2.4v2.4", "stroke-linecap": "round"
    }));
    mark.appendChild(svg);
    return mark;
  }

  // A strength, or one of the two habits. They arrive as one list of seven
  // and they rendered as one list of seven, which reads as seven faults with
  // the first five miscounted. The split is the chapter's own.
  function traitCard(item, index, habit) {
    var card = elm("li", "br-trait" + (habit ? " is-habit" : ""));
    var head = elm("p", "br-trait-head");
    if (!habit) head.appendChild(elm("span", "br-trait-n", String(index + 1)));
    head.appendChild(elm("span", "br-trait-title", item.title || ""));
    if (habit) head.appendChild(elm("span", "br-swap", "SWAP THIS"));
    card.appendChild(head);
    if (item.body) card.appendChild(elm("p", "br-body", item.body));
    if (item.fix) {
      card.appendChild(elm("p", "br-do",
                           (habit ? "Swap: " : "Spend it: ") + item.fix));
    }
    return card;
  }

  // One list, three row shapes: an arrow line, a day, a strength or a habit.
  // Which one a row is, is which one it carries — none of the three is a
  // fallback for another.
  function itemList(items) {
    var traits = items.length === 7 && items[0] && items[0].title;
    var list = elm("ul", "br-list");
    var last = items.length - 1;
    items.forEach(function (item, index) {
      if (typeof item === "string") {
        list.appendChild(elm("li", "br-item", item));
        return;
      }
      if (item.name || item.priority_note) {
        list.appendChild(dayCard(item, index, last));
        return;
      }
      if (traits && index === 5) {
        list.appendChild(elm("li", "br-habits-head", "Two habits to swap"));
      }
      list.appendChild(traitCard(item, index, traits && index >= 5));
    });
    return list;
  }

  // What a verdict is called on this page. The schema's word is `works` or
  // `avoid`; what the reader sees is the funnel's, because one of the two
  // marks a round they are being told to practise.
  var VERDICT_WORDS = { works: "STRENGTH", avoid: "ROOM TO GROW" };

  function verdictWord(verdict) {
    return VERDICT_WORDS[verdict] || String(verdict || "").toUpperCase();
  }

  // --- the delivered page, as four blocks ------------------------------------
  //
  // What the reader bought is a document, and it was rendering as a column of
  // paragraphs with the number they paid for four screens down it. These are
  // the four blocks it is now: the two numbers, the run, the sixteen rounds,
  // and the chapters. The free page is not one of them and does not change.

  // The three marks a round wears. The same three shapes the PDF draws, from
  // the same paths — drawn rather than typed, because a report opened in a
  // browser with one font and printed from another cannot rely on a glyph.
  var MARK_CHECK = "M4.6 8.3 6.9 10.7 11.5 5.6";
  var MARK_CROSS = "M5.5 5.5 10.5 10.5M10.5 5.5 5.5 10.5";
  var GLYPH_CLOCK = "M8 4.3V8l2.5 1.5";
  var GLYPH_PLATE = "M3 2.4v3.2a1.5 1.5 0 0 0 3 0V2.4M4.5 5.6V13.6";

  function markFor(status) {
    if (!status) return null;
    var mark = elm("span", "br-mark is-" + status);
    mark.setAttribute("aria-hidden", "true");
    var svg = svgEl("svg", { viewBox: "0 0 16 16" });
    if (status === "miss") {
      svg.appendChild(svgEl("circle", { cx: "8", cy: "8", r: "3.4" }));
    } else {
      svg.appendChild(svgEl("path", {
        d: status === "hit" ? MARK_CHECK : MARK_CROSS,
        "stroke-linecap": "round", "stroke-linejoin": "round"
      }));
    }
    mark.appendChild(svg);
    return mark;
  }

  // The record of the run, off the report rather than off the tab: this page
  // is opened from a link in a mail, in a browser that never played a round.
  function stored(ctx) {
    return (ctx.visuals && ctx.visuals.brain) || {};
  }

  // Block 1. The one number the whole funnel was asking for, drawn the size
  // brain draws its age, and the four zones it was read off. No second cell
  // and no line under it: the score is the answer, and there is no age group
  // to set it against.
  function heroBlock(ctx, copy, data) {
    var wrap = elm("section", "br-dhero");
    wrap.appendChild(elm("p", "br-dhero-lead",
                         copy.head_title || "Your productivity profile"));
    wrap.appendChild(elm("h1", "br-dhero-name", ctx.style.name || ""));
    // The type's one line, and then the type's paragraph. They were on a card
    // of their own between the numbers and the run, which put a paragraph
    // between the reader and the thing they had just paid to see; they belong
    // to the name, so they sit under it.
    var essence = (profileCopy(ctx).essence || {})[ctx.style.id] || "";
    if (essence) wrap.appendChild(elm("p", "br-dhero-essence", essence));
    var nums = elm("div", "br-dhero-nums");
    var cell = elm("div", "br-dhero-cell is-score");
    cell.appendChild(elm("span", "br-dhero-cap",
                         copy.score_lead || "Focus score"));
    var points = elm("p", "br-dhero-figure");
    // The score where the report stored one; the block's own formula where
    // it did not, which on this table is the same figure.
    var figure = typeof data.score === "number" ? data.score : data.age;
    points.appendChild(elm("span", "br-dhero-n is-big", String(figure)));
    points.appendChild(elm("span", "br-dhero-of", "/" + topOf(ageBlock(ctx))));
    cell.appendChild(points);
    nums.appendChild(cell);
    wrap.appendChild(nums);
    // The reaction line, off the stored block, where the report carried one.
    var pace = speedLine(data, "br-dhero-pace");
    if (pace) wrap.appendChild(pace);
    wrap.appendChild(heroBars(ctx, data));
    if (ctx.style.blurb) {
      wrap.appendChild(elm("p", "br-dhero-blurb", ctx.style.blurb));
    }
    return wrap;
  }

  // The four rounds, filled. The fill is scaled rather than widened, so the
  // growth is one CSS animation on first paint and nothing in here has to
  // watch the viewport to start it.
  function heroBars(ctx, data) {
    var names = (ageBlock(ctx) || {}).domains || {};
    var totals = roundTotals(ctx);
    var chart = elm("ul", "br-dbars");
    DOMAINS.forEach(function (key) {
      var total = totals[key] || PER_DOMAIN;
      var got = Math.min(total, (data.counts || {})[key] || 0);
      var row = elm("li", "br-dbar");
      row.appendChild(elm("span", "br-dbar-name", names[key] || key));
      var track = elm("span", "br-dbar-track");
      var bar = elm("span", "br-dbar-fill");
      bar.style.width = Math.max(4, Math.round(100 * got / total)) + "%";
      track.appendChild(bar);
      row.appendChild(track);
      row.appendChild(elm("span", "br-dbar-count", got + "/" + total));
      chart.appendChild(row);
    });
    return chart;
  }

  // How many rounds each of the four is out of, counted off the record where
  // there is one so a funnel that adds a round is not drawn out of four.
  function roundTotals(ctx) {
    var out = {};
    (stored(ctx).rounds || []).forEach(function (row) {
      if (row.domain) out[row.domain] = (out[row.domain] || 0) + 1;
    });
    return out;
  }

  // Block 2. The whole run, six across, every scored round marked. The two
  // warm-up rounds carry no mark: there was nothing to get right on them.
  function runStrip(ctx, copy) {
    var strip = stored(ctx).strip || [];
    if (strip.length < TAPS_MIN) return deliveredTaps(ctx, copy);
    var block = elm("section", "br-strip");
    block.appendChild(elm("p", "br-strip-cap",
                          (copy.taps_caption || "Your run")
                            .replace(/:\s*$/, "")));
    var grid = elm("ul", "br-strip-grid");
    strip.forEach(function (entry) {
      var cell = elm("li", "br-strip-cell"
                     + (entry.status ? " is-" + entry.status : ""));
      if (entry.img) {
        var img = document.createElement("img");
        img.src = entry.img;
        img.alt = "";
        img.loading = "lazy";
        img.decoding = "async";
        cell.appendChild(img);
      }
      var mark = markFor(entry.status);
      if (mark) cell.appendChild(mark);
      grid.appendChild(cell);
    });
    block.appendChild(grid);
    return block;
  }

  // Block 3. Every scored round, grouped by which of the four it belongs to.
  // A list rather than a table element: this is read on a phone 390 points
  // wide, and a table with four columns on it is a table you scroll sideways.
  function roundsTable(ctx) {
    var rows = stored(ctx).rounds || [];
    if (!rows.length) return null;
    var names = (ageBlock(ctx) || {}).domains || {};
    var totals = roundTotals(ctx);
    var counts = storedProfile(ctx) || { counts: {} };
    var block = elm("section", "br-rounds-table");
    block.appendChild(elm("h2", "br-rt-title",
                          "Your " + rows.length + " scored rounds"));
    block.appendChild(elm("p", "br-rt-lead",
                          "Every round you played, what it asked of you, "
                          + "and how it went."));
    DOMAINS.forEach(function (key) {
      var mine = rows.filter(function (row) { return row.domain === key; });
      if (!mine.length) return;
      var head = elm("p", "br-rt-group");
      head.appendChild(elm("span", "br-rt-group-name", names[key] || key));
      head.appendChild(elm("span", "br-rt-group-score",
                           ((counts.counts || {})[key] || 0) + "/"
                           + (totals[key] || mine.length)));
      block.appendChild(head);
      var list = elm("ul", "br-rt-list");
      mine.forEach(function (row) {
        list.appendChild(roundRow(row));
      });
      block.appendChild(list);
    });
    return block;
  }

  var CHIP_WORDS = { hit: "HIT", miss: "MISS", out: "TIME'S UP" };

  function roundRow(row) {
    var item = elm("li", "br-rt-row");
    var shot = elm("span", "br-rt-shot"
                   + (row.img ? "" : " is-out"));
    if (row.img) {
      var img = document.createElement("img");
      img.src = row.img;
      img.alt = "";
      img.loading = "lazy";
      img.decoding = "async";
      shot.appendChild(img);
    } else {
      var mark = markFor("out");
      if (mark) shot.appendChild(mark);
    }
    item.appendChild(shot);
    var text = elm("span", "br-rt-text");
    text.appendChild(elm("span", "br-rt-task", row.task || ""));
    text.appendChild(elm("span", "br-rt-asks", row.asks || ""));
    item.appendChild(text);
    item.appendChild(elm("span", "br-rt-chip is-" + (row.status || "miss"),
                         CHIP_WORDS[row.status] || ""));
    return item;
  }

  function deliveredNode(ctx, section) {
    var item = node("open", section.title || "");
    var body = item.querySelector(".br-node-body");
    var key = keywordOf(ctx, section.id);
    if (key) {
      body.insertBefore(elm("p", "br-node-key", key + ":"), body.firstChild);
    }
    if (section.data) {
      try {
        body.appendChild(sectionBody(section.data));
        return item;
      } catch (e) { /* fall through to prose */ }
    }
    if (section.body) body.appendChild(elm("p", "br-body", section.body));
    return item;
  }

  function delivered(root, ctx) {
    var copy = copyOf(ctx);
    var data = storedProfile(ctx);
    var lean = template(ctx) === "minimal";
    root.innerHTML = "";
    root.classList.add("is-delivered");
    root.classList.toggle("is-minimal", lean);
    var note = deliveryNote(ctx, copy);
    if (note) root.appendChild(note);
    // Four blocks, in this order, and the reason for the order is that it is
    // the order somebody asks in: what did I get, what did I play, how did
    // each round go, and what do I do about it.
    //
    // What was here instead was the free page's three cards stacked, then the
    // strip, then a column of prose — so the number the reader had just paid
    // to be told was the third card down and the sixteen rounds behind it
    // were not on the page at all.
    if (data) {
      root.appendChild(heroBlock(ctx, copy, data));
    } else {
      root.appendChild(typeCard(ctx, copy, lean));
    }
    var strip = runStrip(ctx, copy);
    if (strip) root.appendChild(strip);
    var table = roundsTable(ctx);
    if (table) root.appendChild(table);
    // Same reorder after the money as before it: the section they came for is
    // the first one they meet. `ctx.purpose` is the tag off the stored report
    // — this tab may never have run the quiz — and a report without one
    // renders in report order.
    var list = elm("ol", "br-path");
    firstly(ctx.sections, emphasised(purposeRule(ctx)))
      .forEach(function (section) {
        list.appendChild(deliveredNode(ctx, section));
      });
    root.appendChild(list);

    // No offer here, obviously. What replaces it is the one line the reader
    // still needs: where else this document is.
    if (ctx.complete && copy.delivered_note) {
      root.appendChild(elm("p", "br-footnote", copy.delivered_note));
    }
    // And the last thing the plan asks for, which is the thing that makes it
    // a plan rather than a document: come back and play it again. A plain
    // link to the funnel's own path, because the reader is sitting on that
    // path with a token on the end of it and the token is what would hand
    // them their old report instead of a new run.
    var again = retest(ctx);
    if (again) root.appendChild(again);
    root.hidden = false;
  }

  function retest(ctx) {
    var table = profileCopy(ctx);
    var slug = (ctx.cfg && ctx.cfg.slug) || "";
    if (!table.retest_line || !slug) return null;
    var line = elm("p", "br-retest");
    var link = elm("a", "br-retest-link", table.retest_line);
    link.href = "/" + slug;
    line.appendChild(link);
    return line;
  }

  window.MazzinResult = { render: render, delivered: delivered };
}());
