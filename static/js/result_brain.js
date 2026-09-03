/* The brain funnel's result page, before and after the money.
 *
 * Same contract as static/js/result_persona.js — engine.js loads this when a
 * config names it, hands it the finished run, and the two things that must
 * not be got wrong, the withdrawal-right consent and the button that charges,
 * are engine.js's own live nodes moved into this layout rather than rebuilt
 * in it. The paywall variants are the same mechanism, unchanged, down to the
 * one event it fires and the one field engine.js reads back.
 *
 * What differs is everything else, because the product is different. Persona
 * sells a reading of somebody's shape; this sells a reading of how they just
 * played. So the page opens on a number the reader earned in the last two
 * minutes — "Your brain is 34" — and everything under it is the arithmetic
 * behind that number, in the order somebody actually asks for it: how it
 * compares with their own age group, which of the four rounds carried it, and
 * which brain type that adds up to.
 *
 * The number is not a verdict about anybody. It is sixteen rounds, a base and
 * a per-miss, stated in `brain_age` in the config so the page, the report and
 * anybody reading the config all get the same figure from the same table.
 * This file computes it from the run; after the money there is no run left in
 * the tab, so the same block travels on the report as `visuals.brain` and is
 * read back rather than recomputed.
 *
 * A config with no `brain_age` block still renders: the type card and the
 * offer are drawn without the number, which is the page a reader gets in the
 * window where this file and the config it reads are a version apart behind
 * the CDN.
 */
(function () {
  "use strict";

  // The four rounds, in the order they were played, which is also the order
  // they are drawn in. The names are the config's — `brain_age.domains` — so
  // the bar and the report cannot end up calling the same round two things.
  var DOMAINS = ["mem", "spa", "chg", "foc"];

  var DOMAIN_COLOR = {
    mem: "#3B7DD8", spa: "#4CAF7D", chg: "#F2B33D", foc: "#8E6FD8"
  };

  // How many of each round there are. Four apiece, sixteen in all, which is
  // also what `brain_age.scored` says — read from the run rather than from
  // the config so a bar can never claim a denominator the quiz did not draw.
  var PER_DOMAIN = 4;

  // Inside this many years of their own age group is "level". Three rather
  // than one, because the score moves in steps of `per_miss` and a single
  // round either way should not flip the sentence.
  var LEVEL_BAND = 3;

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
  function profileOf(scores, cfg) {
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

    // Their own age group, off the service tag the first step carries. No tag
    // — a run that skipped it, or a report written before the step existed —
    // means no comparison, which is a line this page simply does not draw.
    var mid = null;
    var table = block.age_mid || {};
    for (var tag in table) {
      if (Object.prototype.hasOwnProperty.call(table, tag)
          && (scores[tag] || 0) > 0) {
        mid = table[tag];
        break;
      }
    }

    var out = {
      age: age,
      hits: hits,
      misses: misses,
      scored: scored,
      counts: counts,
      age_mid: mid,
      delta: mid === null ? null : age - mid
    };
    return scoreOf(out, block);
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
  function scoreOf(data, block) {
    var rule = (block && block.score) || null;
    if (!rule) return data;
    var raw = (rule.base || 0) + (rule.per_miss || 0) * data.misses;
    var floor = typeof rule.floor === "number" ? rule.floor : 0;
    var top = typeof rule.base === "number" ? rule.base : 100;
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

  // --- a) the kicker ---------------------------------------------------------

  function kicker(copy, lean, words) {
    var line = elm("p", "br-kicker", words || copy.kicker || "Your brain age");
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

  // The one line the reader came for, and the one under it that gives it a
  // meaning. Three sentences, chosen on how far the score sits from the middle
  // of their own age group; a run that never said which group that is gets the
  // bare line instead of an invented comparison.
  function ageLine(copy, data) {
    if (!data || data.delta === null) {
      return copy.age_line_bare || "";
    }
    var years = Math.abs(data.delta);
    if (data.delta <= -LEVEL_BAND) {
      return fill(copy.younger_line || "{n} years younger than your age group",
                  { n: years });
    }
    if (data.delta >= LEVEL_BAND) {
      return fill(copy.older_line || "{n} years older — let's fix that",
                  { n: years });
    }
    return copy.level_line || "right where your age group sits";
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

  // The free page's hero. The same lux treatment the age had, on the number
  // this page is allowed to give away — the age is the thing the report opens
  // on, and a page that has already said it has nothing left to sell.
  function scoreCard(ctx, copy, data, lean) {
    if (typeof data.score !== "number") return null;
    var card = elm("section", "br-score" + (lean ? " is-lux" : ""));
    if (lean) corners(card);
    var lead = copy.score_lead || "";
    if (lead) card.appendChild(elm("p", "br-score-lead", lead));
    var big = elm("p", "br-age br-points");
    big.appendChild(elm("span", "br-age-number", String(data.score)));
    // Out of what the table says a clean run is worth, not out of a hundred
    // this file decided on: the score is the config's arithmetic and so is
    // the number it is out of.
    var top = ((ageBlock(ctx) || {}).score || {}).base;
    big.appendChild(elm("span", "br-points-of",
                        "/" + (typeof top === "number" ? top : 100)));
    card.appendChild(big);
    var line = scoreLine(copy, data);
    if (line) card.appendChild(elm("p", "br-age-note", line));
    var chips = lean ? chipRow(ctx, data) : null;
    if (chips) card.appendChild(chips);
    return card;
  }

  function score(ctx, copy, data, lean) {
    var card = elm("section", "br-score" + (lean ? " is-lux" : ""));
    if (lean) corners(card);
    // Its own label, not the type card's. The kicker above already says what
    // the number is; this says when it was measured, which is the part that
    // makes it feel earned rather than looked up.
    var lead = copy.kicker || "";
    if (lead) card.appendChild(elm("p", "br-score-lead", lead));
    var big = elm("p", "br-age");
    big.appendChild(elm("span", "br-age-word", "Your brain is"));
    big.appendChild(elm("span", "br-age-number", String(data.age)));
    card.appendChild(big);
    var line = ageLine(copy, data);
    if (line) card.appendChild(elm("p", "br-age-note", line));
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

  // --- d) the brain type -----------------------------------------------------

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

  // v10 dropped the line this block used to open with. It said the same thing
  // three ways — for a reader ahead of, on, or behind their age group — which
  // meant printing the age delta on the page whose whole job is now to make
  // the age worth paying for. Those three sentences are the report's, under
  // the number they are about; here the line under the score has already said
  // what the run left on the table, and this block is the way to act on it.
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
  // than this tab's URL: a paid reader is sitting on `/brain?cs=...`, and a
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
  // Eighteen squares, one per round, in the order they were played. Two of
  // them are not the card that was tapped, and both for the same reason: the
  // strip is a record of the walk rather than a contact sheet of the art.
  //
  // A spatial round was answered on six identical closed boxes, so the tapped
  // card is a shut lid — the same shut lid six times, four rounds running. The
  // strip draws the box that was OPEN on that round's flash instead, which is
  // the thing the round was actually about and the only frame of it the reader
  // would recognise.
  //
  // And a round the clock answered is not a round anybody played. It gets a
  // cross rather than a picture of a card nobody chose.

  // Both of those substitutions are the engine's rule, not this page's. It
  // draws the same tiles between rounds and on the analysing screen, and two
  // copies of "what does this round show" would be two answers the moment one
  // of them was edited. `ctx.tile` is that rule; this reads it.
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
      mark.textContent = "◆";
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
    var data = profileOf(ctx.scores || {}, ctx.cfg);

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
      // v10: the score, not the age. The age is what the report opens on, and
      // a free page that has already printed it has nothing left to reveal.
      // Nothing on this page draws it — not the hero, not the closing line,
      // not the share text.
      //
      // A config with no score table has no score to show, and gets the page
      // it had before this: the funnel this file was written for has one.
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
    // The type card is gone from this page. It is still computed — the report
    // is written for it and the delivered page still draws it — but before
    // the money it was a second identity card under the first, and what it
    // said about the reader is what the report is for.
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
      age_mid: typeof stored.age_mid === "number" ? stored.age_mid : null,
      delta: typeof stored.delta === "number" ? stored.delta : null,
      // Off the report, never recomputed here: the stored row is the single
      // record of what this run scored, and a page that worked it out again
      // would be a second opinion about a number somebody paid for.
      score: typeof stored.score === "number" ? stored.score : null,
      room_rounds: typeof stored.room_rounds === "number"
        ? stored.room_rounds : 0,
      elite: !!stored.elite
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
    if (items.length) {
      var list = elm("ol", "br-list");
      items.forEach(function (item) {
        var row = elm("li", "br-item");
        if (typeof item === "string") {
          row.appendChild(elm("p", "br-body", item));
        } else {
          // Two row shapes, one list: a strength is a title, a body and a
          // fix; a day is a name and what to do on it. Neither is the other's
          // fallback — a row is whichever of the two it carries.
          var title = item.title || item.name;
          if (title) row.appendChild(elm("h3", "br-item-title", title));
          var body = item.body || item.priority_note;
          if (body) row.appendChild(elm("p", "br-body", body));
          if (item.fix) row.appendChild(elm("p", "br-fix", "→ " + item.fix));
        }
        list.appendChild(row);
      });
      frag.appendChild(list);
    }
    // The drill the weakest-round chapter closes on, and the one paragraph on
    // it that the reader is meant to act on tomorrow morning.
    if (data.rule) frag.appendChild(elm("p", "br-callout", data.rule));
    (data.skip || []).forEach(function (row) {
      frag.appendChild(elm("p", "br-note",
                           [row.name, row.why].filter(Boolean).join(" — ")));
    });
    if (data.closing_rule) {
      frag.appendChild(elm("p", "br-note", data.closing_rule));
    }
    return frag;
  }

  // What a verdict is called on this page. The schema's word is `works` or
  // `avoid`; what the reader sees is the funnel's, because one of the two
  // marks a round they are being told to practise.
  var VERDICT_WORDS = { works: "STRENGTH", avoid: "ROOM TO GROW" };

  function verdictWord(verdict) {
    return VERDICT_WORDS[verdict] || String(verdict || "").toUpperCase();
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
    // The score's kicker here too, because the score is the first card under
    // it. The age has its own lead on its own card, one card further down,
    // which is where the reveal belongs.
    root.appendChild(kicker(copy, lean, copy.score_kicker));
    // The same head as before the money, off the block the report carries.
    // The reader paid on this page and the thing they bought has to open as
    // the same document, so the arm travels with it.
    if (data) {
      // The page the reader last saw, and then the thing they bought. The
      // score first because it is what they were looking at when they paid,
      // and the age straight under it because it is the answer to the
      // question the whole funnel asked.
      var top = scoreCard(ctx, copy, data, lean);
      if (top) root.appendChild(top);
      root.appendChild(score(ctx, copy, data, lean));
      if (!lean) root.appendChild(bars(ctx, copy, data));
    }
    root.appendChild(typeCard(ctx, copy, lean));
    var strip = deliveredTaps(ctx, copy);
    if (strip) root.appendChild(strip);
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
