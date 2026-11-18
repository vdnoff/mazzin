/* The AI Navigator funnel's result page, before and after the money.
 *
 * Same contract as static/js/result_focus.js, which this file was cut from —
 * engine.js loads this when a config names it, hands it the finished run, and
 * the two things that must not be got wrong, the withdrawal-right consent and
 * the button that charges, are engine.js's own live nodes moved into this
 * layout rather than rebuilt in it. There is no payment path in this file and
 * no call that starts one.
 *
 * What differs from focus is the game. Focus is played against a clock and
 * its one number is a score out of a hundred; this is twelve questions with
 * one right answer each, no clock, and the number is simply how many were
 * right. So everything focus computes about time is gone from this file, not
 * switched off: no speed points, no reaction times, no time-up tiles. So are
 * the share button, the play-again line and the comparison with a last run.
 *
 * What it adds is the prediction. Before the test the reader says how many of
 * the twelve they expect to get right, and the page sets that against what
 * they scored — inside the band, above it or below it — in the reader's own
 * numbers and nobody else's.
 *
 * Nothing here holds a number of its own. How many questions there are, how
 * many per zone, what the zones are called, where the three levels start and
 * which band each prediction means all come off `brain_age` in the config —
 * the block keeps the key focus and brain use because the report machinery
 * reads it by that name — and every sentence comes off `result_copy`. The
 * tallies are the ones engine.js scored on the way through.
 *
 * The page never says which answer was right. The strip shows twelve marks,
 * right or missed, and the answers themselves are in the report.
 */
(function () {
  "use strict";

  // The four zones, in the order they are played, which is the order they
  // are drawn in. The tag stems are brain's — engine.js scores on `mem`,
  // `foc`, `chg` and `spa` and nothing else — and the reader never sees
  // them: the names are the config's, `brain_age.domains`.
  var DOMAINS = ["mem", "foc", "chg", "spa"];

  var ROUND_TAG = /^(mem|foc|chg|spa)_(hit|miss)$/;

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

  function glyph(d, cls) {
    var svg = svgEl("svg", { viewBox: "0 0 16 16", "aria-hidden": "true" });
    if (cls) svg.setAttribute("class", cls);
    svg.appendChild(svgEl("path", {
      d: d, "stroke-linecap": "round", "stroke-linejoin": "round"
    }));
    return svg;
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

  function profileCopy(ctx) {
    return (copyOf(ctx).profile) || {};
  }

  function numbers(ctx) {
    var block = ctx.cfg && ctx.cfg.brain_age;
    return (block && typeof block === "object") ? block : null;
  }

  function zoneName(ctx, key) {
    var names = (numbers(ctx) || {}).domains || {};
    return names[key] || key;
  }

  // --- the run ---------------------------------------------------------------

  // The scored steps, in walk order, each with the zone it belongs to. Found
  // by what the cards carry rather than by step id: a step is a question if
  // its cards are tagged hit and miss on one of the four stems, and a warm-up
  // is every step that is not.
  function rounds(cfg) {
    var out = [];
    ((cfg && cfg.swipe && cfg.swipe.steps) || []).forEach(function (step) {
      var cards = ((step.pairs || [])[0] || {}).images || [];
      for (var i = 0; i < cards.length; i++) {
        var tags = cards[i].tags || [];
        for (var j = 0; j < tags.length; j++) {
          var hit = ROUND_TAG.exec(tags[j]);
          if (hit) { out.push({ id: step.id, zone: hit[1] }); return; }
        }
      }
    });
    return out;
  }

  function isHit(pick, zone) {
    return !!(pick && (pick.tags || []).indexOf(zone + "_hit") !== -1);
  }

  // The first level whose ceiling the score is under, or the last one, which
  // carries no ceiling. Read off the config's table top to bottom.
  function levelOf(block, hits) {
    var rows = (block && block.levels) || [];
    for (var i = 0; i < rows.length; i++) {
      if (typeof rows[i].max !== "number" || hits <= rows[i].max) {
        return rows[i];
      }
    }
    return null;
  }

  // What the reader predicted, as the band the config says that card means.
  // Null when the step was never answered — a reload into the test, a config
  // without the step — and the page then shows the score alone.
  function predictionOf(ctx, block) {
    var rule = (block && block.predict) || null;
    if (!rule || !rule.bands) return null;
    var pick = (ctx.picks || {})[rule.step];
    var tags = (pick && pick.tags) || [];
    for (var i = 0; i < tags.length; i++) {
      var band = rule.bands[tags[i]];
      if (band && typeof band.min === "number"
          && typeof band.max === "number") {
        return band;
      }
    }
    return null;
  }

  // Inside the band, above it or below it. Three words for three cases, and
  // the wording for each is the config's.
  function calibrationOf(band, hits) {
    if (!band) return "";
    if (hits > band.max) return "under";
    if (hits < band.min) return "over";
    return "on";
  }

  // Everything the page says about the run, computed once.
  //
  // `hits` is counted off the hit tags engine.js tallied, so a question
  // nobody answered — a reader who reloaded mid-quiz — is a miss, and the
  // number shown is always out of the full twelve.
  function profileOf(ctx) {
    var block = numbers(ctx);
    if (!block) return null;
    var scores = ctx.scores || {};
    var per = typeof block.per_domain === "number" ? block.per_domain : 3;
    var counts = {};
    var hits = 0;
    DOMAINS.forEach(function (key) {
      var n = Math.max(0, Math.min(per, scores[key + "_hit"] || 0));
      counts[key] = n;
      hits += n;
    });
    var total = typeof block.scored === "number"
      ? block.scored : per * DOMAINS.length;

    // The zone with the most room: the lowest count, the earliest of them on
    // a tie. None at all when the four are level, because then no zone has
    // more room than another and naming one would be inventing a finding.
    var low = null;
    var level = true;
    DOMAINS.forEach(function (key) {
      if (counts[key] !== counts[DOMAINS[0]]) level = false;
      if (low === null || counts[key] < counts[low]) low = key;
    });

    var band = predictionOf(ctx, block);
    return {
      hits: hits, total: total, per: per, counts: counts,
      room: level ? "" : low,
      level: levelOf(block, hits),
      band: band,
      calibration: calibrationOf(band, hits)
    };
  }

  // --- 1) the score, and the prediction it is set against --------------------

  function kicker(copy) {
    return elm("p", "ai-kicker", copy.score_kicker || copy.kicker || "");
  }

  function hero(ctx, copy, data) {
    var card = elm("section", "ai-hero");
    if (copy.score_lead) card.appendChild(elm("p", "ai-hero-lead",
                                              copy.score_lead));
    var figure = elm("p", "ai-score");
    var text = fill(copy.score_of || "{n} / {total}",
                    { n: data.hits, total: data.total });
    // The first number is the loud one; " / 12" is its unit.
    var cut = text.indexOf(String(data.hits));
    if (cut === 0) {
      figure.appendChild(elm("span", "ai-score-n", String(data.hits)));
      figure.appendChild(elm("span", "ai-score-of",
                             text.slice(String(data.hits).length)));
    } else {
      figure.textContent = text;
    }
    card.appendChild(figure);

    if (data.band) {
      card.appendChild(elm("p", "ai-predict", fill(
        copy.calibration_line || "You predicted {band}. You scored {n}.",
        { band: data.band.label || (data.band.min + "–" + data.band.max),
          n: data.hits })));
      var word = (copy.calibration || {})[data.calibration] || "";
      if (word) {
        card.appendChild(elm("p", "ai-calibration is-" + data.calibration,
                             word));
      }
    }
    return card;
  }

  // --- 2) the level ----------------------------------------------------------

  function levelChip(ctx, copy, data) {
    if (!data.level || !data.level.label) return null;
    var wrap = elm("section", "ai-level");
    var chip = elm("p", "ai-level-chip");
    if (copy.level_lead) {
      chip.appendChild(elm("span", "ai-level-lead", copy.level_lead));
    }
    chip.appendChild(elm("span", "ai-level-name", data.level.label));
    wrap.appendChild(chip);

    // The whole scale, with this run's rung marked, so the chip is a place on
    // something rather than a bare word.
    var rows = (numbers(ctx) || {}).levels || [];
    var scale = elm("ol", "ai-level-scale");
    var from = 0;
    rows.forEach(function (row) {
      var to = typeof row.max === "number" ? row.max : data.total;
      var item = elm("li", "ai-level-step");
      if (row === data.level) {
        item.classList.add("is-here");
        item.setAttribute("aria-current", "true");
      }
      item.appendChild(elm("span", "ai-level-step-name", row.label || ""));
      item.appendChild(elm("span", "ai-level-step-range", from + "–" + to));
      scale.appendChild(item);
      from = to + 1;
    });
    wrap.appendChild(scale);
    return wrap;
  }

  // --- 3) the type -----------------------------------------------------------

  function typeCard(ctx) {
    var card = elm("section", "ai-type");
    if (ctx.style.id) card.setAttribute("data-type", ctx.style.id);
    card.appendChild(elm("h1", "ai-type-name", ctx.style.name || ""));
    var essence = (profileCopy(ctx).essence || {})[ctx.style.id] || "";
    if (essence) card.appendChild(elm("p", "ai-type-essence", essence));
    return card;
  }

  // --- 4) the four zones -----------------------------------------------------

  function bars(ctx, copy, data) {
    var card = elm("section", "ai-zones");
    if (copy.balance_title) {
      card.appendChild(elm("h2", "ai-h2", copy.balance_title));
    }
    var list = elm("ul", "ai-zone-list");
    DOMAINS.forEach(function (key) {
      var n = data.counts[key];
      var row = elm("li", "ai-zone is-" + key);
      var head = elm("p", "ai-zone-head");
      head.appendChild(elm("span", "ai-zone-name", zoneName(ctx, key)));
      head.appendChild(elm("span", "ai-zone-count", fill(
        copy.zone_of || "{n} of {total}", { n: n, total: data.per })));
      row.appendChild(head);
      var track = elm("span", "ai-zone-track");
      track.setAttribute("aria-hidden", "true");
      for (var i = 0; i < data.per; i++) {
        track.appendChild(elm("i", i < n ? "is-on" : ""));
      }
      row.appendChild(track);
      // Never a verdict: the lowest zone is where there is the most to gain,
      // and that is the only thing said about it.
      if (key === data.room && copy.zone_room) {
        row.classList.add("is-room");
        row.appendChild(elm("p", "ai-zone-room", copy.zone_room));
      }
      list.appendChild(row);
    });
    card.appendChild(list);
    if (copy.head_caption) {
      card.appendChild(elm("p", "ai-caption", copy.head_caption));
    }
    return card;
  }

  // --- 5) the twelve marks ---------------------------------------------------

  var MARK_CHECK = "M4.6 8.3 6.9 10.7 11.5 5.6";
  var MARK_CROSS = "M5.5 5.5 10.5 10.5M10.5 5.5 5.5 10.5";

  // One mark a question, right or missed, grouped by zone. Which of the four
  // answers was the right one is not on this page in any form — no label, no
  // id, no attribute — because that is what the Answer Key is.
  function strip(ctx, copy) {
    var list = rounds(ctx.cfg);
    if (!list.length) return null;
    var card = elm("section", "ai-strip");
    if (copy.strip_title) {
      card.appendChild(elm("h2", "ai-h2", copy.strip_title));
    }
    var row = elm("ol", "ai-marks");
    var picks = ctx.picks || {};
    list.forEach(function (round, index) {
      var ok = isHit(picks[round.id], round.zone);
      var item = elm("li", "ai-mark is-" + round.zone
                     + (ok ? " is-hit" : " is-miss"));
      item.setAttribute("aria-label", (index + 1) + ": "
                        + (ok ? (copy.strip_hit || "right")
                           : (copy.strip_miss || "missed")));
      item.appendChild(glyph(ok ? MARK_CHECK : MARK_CROSS));
      row.appendChild(item);
    });
    card.appendChild(row);
    if (copy.strip_note) {
      card.appendChild(elm("p", "ai-caption", copy.strip_note));
    }
    return card;
  }

  // --- 6) strength #1, free and in full --------------------------------------

  function strength(ctx, copy) {
    var one = ctx.strength;
    if (!one || !one.title) return null;
    var card = elm("section", "ai-strength");
    var title = (ctx.strengthCopy || {}).title || "";
    var lead = [copy.strength_lead, title].filter(Boolean).join(" ");
    if (lead) card.appendChild(elm("p", "ai-strength-lead", lead));
    card.appendChild(elm("h2", "ai-strength-title", one.title));
    if (one.body) card.appendChild(elm("p", "ai-body", one.body));
    if (one.fix) card.appendChild(elm("p", "ai-strength-fix", one.fix));
    var note = (ctx.strengthCopy || {}).locked_note || "";
    if (note) card.appendChild(elm("p", "ai-strength-note", note));
    return card;
  }

  // --- 7) what is locked -----------------------------------------------------

  var LOCK_PATH = "M5 8V5.5a3 3 0 0 1 6 0V8M4 8h8v6H4z";

  function node(kind, title) {
    var item = elm("li", "ai-node is-" + kind);
    var mark = elm("span", "ai-node-mark");
    mark.setAttribute("aria-hidden", "true");
    if (kind === "open") {
      mark.className = "ai-node-mark is-rule";
    } else {
      mark.appendChild(glyph(LOCK_PATH));
    }
    item.appendChild(mark);
    var body = elm("div", "ai-node-body");
    body.appendChild(elm("h3", "ai-node-title", title || ""));
    item.appendChild(body);
    return item;
  }

  function keywordOf(ctx, sectionId) {
    var cards = profileCopy(ctx).cards || [];
    for (var i = 0; i < cards.length; i++) {
      if (cards[i].id === sectionId) return cards[i].key || "";
    }
    return "";
  }

  function lockedNode(ctx, copy, title, key, line, lead) {
    var item = node("locked", title);
    if (lead) item.classList.add("is-lead");
    var body = item.querySelector(".ai-node-body");
    if (key) {
      body.insertBefore(elm("p", "ai-node-key", key + ":"), body.firstChild);
    }
    if (line) body.appendChild(elm("p", "ai-teaser", line));
    var lock = elm("span", "ai-lock", copy.locked_note || "Locked");
    lock.setAttribute("aria-hidden", "true");
    item.appendChild(lock);
    return item;
  }

  // The reason somebody gave for being here, as the config maps it: which
  // chapter leads, and one line for the offer. Found by tag, off whichever
  // step carried it. A config with no map changes nothing.
  function purposeRule(ctx) {
    var map = copyOf(ctx).purpose_map;
    if (!map || typeof map !== "object") return null;
    if (ctx.purpose && map[ctx.purpose]) return map[ctx.purpose];
    var picks = ctx.picks || {};
    for (var id in picks) {
      if (!Object.prototype.hasOwnProperty.call(picks, id)) continue;
      var tags = (picks[id] && picks[id].tags) || [];
      for (var i = 0; i < tags.length; i++) {
        if (map[tags[i]]) return map[tags[i]];
      }
    }
    return null;
  }

  function firstly(sections, want) {
    if (!want) return sections.slice();
    var head = sections.filter(function (s) { return s.id === want; });
    var rest = sections.filter(function (s) { return s.id !== want; });
    return head.concat(rest);
  }

  function path(ctx, copy) {
    var card = elm("section", "ai-path-card");
    if (copy.path_teaser) {
      card.appendChild(elm("p", "ai-path-teaser", copy.path_teaser));
    }
    if (copy.path_title) card.appendChild(elm("h2", "ai-h2", copy.path_title));
    var list = elm("ol", "ai-path");
    var want = (purposeRule(ctx) || {}).emphasized_section || "";
    var shut = (ctx.sections || []).filter(function (s) { return s.locked; });
    firstly(shut, want).forEach(function (section) {
      var line = typeof ctx.fillHook === "function"
        ? ctx.fillHook(section.teaser_line || "")
        : (section.teaser_line || "");
      list.appendChild(lockedNode(ctx, copy, section.title,
                                  keywordOf(ctx, section.id), line,
                                  section.id === want));
    });
    var key = profileCopy(ctx).answer_key;
    if (key && key.title) {
      list.appendChild(lockedNode(ctx, copy, key.title, key.key || "",
                                  key.hook || "", false));
    }
    card.appendChild(list);
    return card;
  }

  // --- 8) the offer ----------------------------------------------------------
  //
  // The card is this file's; everything on it that touches money is not. The
  // consent box, the wallet, the button, its error line and the legal links
  // are engine.js's own nodes, already wired, moved here.

  var OFFER_ID = "ai-offer";

  var OFFER_ICONS = {
    target: "M8 2.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11zM8 5.5a2.5 2.5 0 1 "
      + "0 0 5 2.5 2.5 0 0 0 0-5z",
    calendar: "M3 4.5h10v8.5H3zM3 7h10M5.5 3v2.5M10.5 3v2.5",
    bolt: "M9 2 4 9h3.5L7 14l5-7H8.5L9 2z",
    key: "M9.5 6.5a3 3 0 1 0-2.3 2.9L8.5 10.5H10V12h1.5v1.5H13V11l-3.6-3.6"
      + "c.1-.3.1-.6.1-.9z"
  };

  function offerBenefits(ctx) {
    var cards = profileCopy(ctx).offer_cards || [];
    if (!cards.length) return null;
    var grid = elm("ul", "ai-benefits");
    cards.forEach(function (row) {
      var item = elm("li", "ai-benefit");
      if (OFFER_ICONS[row.icon]) {
        var mark = elm("span", "ai-benefit-icon");
        mark.appendChild(glyph(OFFER_ICONS[row.icon]));
        item.appendChild(mark);
      }
      var text = elm("div", "ai-benefit-text");
      text.appendChild(elm("p", "ai-benefit-title", row.title || ""));
      if (row.sub) text.appendChild(elm("p", "ai-benefit-sub", row.sub));
      item.appendChild(text);
      grid.appendChild(item);
    });
    return grid;
  }

  function offerPersonal(ctx, data) {
    var table = profileCopy(ctx);
    if (!data) return "";
    if (data.room && table.offer_personal) {
      return fill(table.offer_personal, { zone: zoneName(ctx, data.room) });
    }
    return table.offer_personal_even || "";
  }

  function accented(text, accent, cls) {
    var line = elm("p", cls);
    if (accent && text.indexOf(accent) !== -1) {
      var cut = text.split(accent);
      line.appendChild(document.createTextNode(cut[0]));
      line.appendChild(elm("span", "ai-accent", accent));
      line.appendChild(document.createTextNode(cut.slice(1).join(accent)));
    } else {
      line.textContent = text;
    }
    return line;
  }

  function offer(ctx, copy, data) {
    var card = elm("section", "ai-offer");
    card.id = OFFER_ID;
    var nodes = ctx.nodes || {};
    var commerce = ctx.commerce || {};
    var checkout = (ctx.cfg && ctx.cfg.checkout) || {};

    var head = ctx.withPrice(profileCopy(ctx).offer_head || "");
    if (head) card.appendChild(elm("h2", "ai-offer-head", head));
    var personal = offerPersonal(ctx, data);
    if (personal) card.appendChild(elm("p", "ai-offer-personal", personal));
    var sub = (purposeRule(ctx) || {}).offer_sub || copy.offer_sub || "";
    if (sub) card.appendChild(elm("p", "ai-offer-sub", ctx.withPrice(sub)));
    var grid = offerBenefits(ctx);
    if (grid) card.appendChild(grid);

    // `ctx.price` is whatever the checkout is about to charge. Formatted by
    // engine.js off the config's own amount; no figure is written here.
    var price = elm("p", "ai-price");
    price.appendChild(elm("span", "ai-price-now", ctx.price));
    if (commerce.price_note) {
      price.appendChild(elm("span", "ai-price-note", commerce.price_note));
    }
    card.appendChild(price);

    // Live nodes, not copies of them. The consent box is placed only where a
    // funnel asks for one: `withdrawal_consent: false` takes it off the page
    // for everybody. Taken off, it still has to be satisfied — it is what
    // enables the pay button — so it is ticked here rather than left to
    // whatever `consent_prechecked` happens to say.
    var wantsConsent = checkout.withdrawal_consent !== false;
    if (!wantsConsent && nodes.consent) {
      var box = nodes.consent.querySelector("input[type=checkbox]");
      if (box && !box.checked) {
        box.checked = true;
        box.dispatchEvent(new Event("change", { bubbles: true }));
      }
      nodes.consent.hidden = true;
    }
    [wantsConsent ? nodes.consent : null, nodes.walletSummary, nodes.wallet,
     nodes.payButton, nodes.payError]
      .forEach(function (n) { if (n) card.appendChild(n); });

    // What this is and is not, straight under the button that buys it.
    var plain = checkout.disclaimer || copy.disclaimer || "";
    if (plain) card.appendChild(elm("p", "ai-disclaimer", plain));

    var chips = profileCopy(ctx).offer_chips || [];
    if (chips.length) {
      var row = elm("ul", "ai-chips");
      chips.forEach(function (text) {
        row.appendChild(elm("li", "ai-chip", text));
      });
      card.appendChild(row);
    }
    var trust = commerce.trust || checkout.trust || [];
    if (trust.length) {
      card.appendChild(elm("p", "ai-trust", trust.join(" · ")));
    }
    if (nodes.legal) card.appendChild(nodes.legal);
    // Last and quietest: what the thing is, in one line. Not a comparison
    // with what anything else costs.
    var anchor = ctx.withPrice(commerce.price_anchor || commerce.anchor_head
                               || checkout.anchor_head || "");
    if (anchor) {
      card.appendChild(accented(anchor, commerce.price_anchor_accent
                                || commerce.anchor_head_accent || "",
                                "ai-anchor"));
    }

    // The rows this layout does not use. Hidden rather than removed: they are
    // the same elements the paid view still wants.
    [nodes.manifest, nodes.anchor, nodes.price, nodes.trust]
      .forEach(function (n) { if (n) n.hidden = true; });

    // This card is the offer now; engine.js fires `paywall_view` when the
    // node it is told to watch reaches the reader. Guarded because this file
    // and engine.js sit behind a CDN and can be a version apart.
    if (typeof ctx.watchOffer === "function") ctx.watchOffer(card);
    return card;
  }

  function footer(copy) {
    if (!copy.disclaimer) return null;
    return elm("p", "ai-foot", copy.disclaimer);
  }

  // --- partner articles -------------------------------------------------------
  //
  // Up to two quiet links out to a partner's articles: one for the skill the
  // reader named, one for the zone with the most room. They stand under the
  // offer on the free page and at the end of the paid one, and nowhere else.
  //
  // Everything is the config's: which articles exist, their labels and links,
  // the lines around them, and which click identifiers ride along. Those
  // identifiers are held by engine.js and handed over as `ctx.passthrough`;
  // this writes them into the link's query, in the config's order, and adds
  // nothing else to it. A link that is not https, or that already carries a
  // query or a fragment, is not drawn. With nothing to draw there is no box.

  var RSOC_KEY = "mazzin_ai_rsoc";

  function rsocOf(ctx) {
    var block = ctx.cfg && ctx.cfg.rsoc;
    return block && typeof block === "object" && block.enabled === true
      ? block : null;
  }

  function articleOf(block, key) {
    var all = block.articles;
    if (!key || !all || !Object.prototype.hasOwnProperty.call(all, key)) {
      return null;
    }
    var item = all[key];
    if (!item || typeof item.label !== "string" || !item.label) return null;
    var link = item.link;
    if (typeof link !== "string" || link.indexOf("https://") !== 0) return null;
    if (link.indexOf("?") !== -1 || link.indexOf("#") !== -1) return null;
    return { key: key, label: item.label, link: link };
  }

  // The skill the reader named, as the tag of the card they tapped: whichever
  // tapped tag is also an article key that is not a zone.
  function skillKey(ctx, block) {
    var picks = ctx.picks || {};
    for (var id in picks) {
      if (!Object.prototype.hasOwnProperty.call(picks, id)) continue;
      var tags = (picks[id] && picks[id].tags) || [];
      for (var i = 0; i < tags.length; i++) {
        if (DOMAINS.indexOf(tags[i]) === -1 && articleOf(block, tags[i])) {
          return tags[i];
        }
      }
    }
    return "";
  }

  // The two keys of this run. The free page works them out and leaves them in
  // sessionStorage, because the paid page is opened after the run is gone and
  // has only what the report stored. Keys of the config, nothing of the
  // reader's beyond that.
  function rsocKeys(ctx, block, data) {
    var keys = { skill: "", zone: "" };
    if (!ctx.delivered) {
      keys.skill = skillKey(ctx, block);
      keys.zone = (data && data.room) || "";
      try { sessionStorage.setItem(RSOC_KEY, JSON.stringify(keys)); }
      catch (e) { /* private mode */ }
      return keys;
    }
    var stored = null;
    try { stored = JSON.parse(sessionStorage.getItem(RSOC_KEY) || "null"); }
    catch (e) { stored = null; }
    if (stored && typeof stored === "object") {
      if (typeof stored.skill === "string") keys.skill = stored.skill;
      if (typeof stored.zone === "string") keys.zone = stored.zone;
    }
    if (!keys.zone && data && data.room) keys.zone = data.room;
    return keys;
  }

  function rsocQuery(ctx, block) {
    var held = ctx.passthrough || {};
    var query = new URLSearchParams();
    (Array.isArray(block.passthrough) ? block.passthrough : [])
      .forEach(function (name) {
        if (typeof name === "string" && typeof held[name] === "string"
            && held[name] && !query.has(name)) {
          query.append(name, held[name]);
        }
      });
    return query;
  }

  function articles(ctx, data, slot) {
    var block = rsocOf(ctx);
    if (!block) return null;
    if ((Array.isArray(block.placement) ? block.placement : [])
        .indexOf(slot) === -1) return null;
    var query = rsocQuery(ctx, block);
    if (block.require_fbclid !== false && !query.has("fbclid")) return null;

    var keys = rsocKeys(ctx, block, data);
    var chosen = [];
    [keys.skill, DOMAINS.indexOf(keys.zone) !== -1 ? keys.zone : ""]
      .forEach(function (key) {
        var item = articleOf(block, key);
        if (!item) return;
        for (var i = 0; i < chosen.length; i++) {
          if (chosen[i].key === item.key || chosen[i].link === item.link) return;
        }
        chosen.push(item);
      });
    if (!chosen.length) return null;

    var tail = query.toString();
    var box = elm("section", "ai-rsoc");
    box.setAttribute("data-slot", slot);
    var head = slot === "delivered" ? block.head_delivered : block.head;
    if (head) box.appendChild(elm("p", "ai-rsoc-head", head));
    chosen.forEach(function (item) {
      var link = elm("a", "ai-rsoc-link", item.label);
      link.href = item.link + (tail ? "?" + tail : "");
      link.target = "_blank";
      link.rel = "noopener";
      link.setAttribute("data-article", item.key);
      link.addEventListener("click", function () {
        if (typeof ctx.track === "function") {
          ctx.track("article_tap", { article: item.key, slot: slot });
        }
      });
      box.appendChild(link);
    });
    if (block.note) box.appendChild(elm("p", "ai-rsoc-note", block.note));
    return box;
  }

  // --- render ----------------------------------------------------------------

  function render(root, ctx) {
    var copy = copyOf(ctx);
    var data = profileOf(ctx);

    root.innerHTML = "";
    root.classList.add("is-ai");
    root.classList.remove("is-delivered");
    root.appendChild(kicker(copy));
    // Top to bottom, the order somebody asks in: how did I do, against what I
    // thought; where does that put me; what kind of run was it; where exactly;
    // question by question; one thing I can use now; and what the rest is.
    // A config with no number block still draws the type and the offer.
    if (data) {
      root.appendChild(hero(ctx, copy, data));
      var chip = levelChip(ctx, copy, data);
      if (chip) root.appendChild(chip);
    }
    root.appendChild(typeCard(ctx));
    if (data) {
      root.appendChild(bars(ctx, copy, data));
      var marks = strip(ctx, copy);
      if (marks) root.appendChild(marks);
    }
    var one = strength(ctx, copy);
    if (one) root.appendChild(one);
    root.appendChild(path(ctx, copy));
    root.appendChild(offer(ctx, copy, data));
    // Under the offer, never in it: the pay button is the page's one loud ask.
    var guides = articles(ctx, data, "below_paywall");
    if (guides) root.appendChild(guides);
    var foot = footer(copy);
    if (foot) root.appendChild(foot);

    // The container engine.js moved the offer rows into is empty now and its
    // own border would draw a line under nothing.
    if (ctx.nodes && ctx.nodes.commerce) ctx.nodes.commerce.hidden = true;
    root.hidden = false;
  }

  // --- the delivered report --------------------------------------------------
  //
  // The same page after the money, opened in a tab that never ran the quiz.
  // The run is gone by then, so the head is rebuilt from whatever the report
  // stored under `visuals.brain` — the block the report machinery writes for
  // a game. Until this funnel has a report profile of its own nothing writes
  // one, and the page is the type card over the sections as they arrive: the
  // stub content a report without a profile is made of renders as prose.

  function storedProfile(ctx) {
    var stored = (ctx.visuals && ctx.visuals.brain) || null;
    var block = numbers(ctx);
    if (!stored || !block || typeof stored.hits !== "number") return null;
    var per = typeof block.per_domain === "number" ? block.per_domain : 3;
    var counts = {};
    var low = null;
    var level = true;
    DOMAINS.forEach(function (key) {
      var n = (stored.counts || {})[key];
      counts[key] = typeof n === "number" ? Math.max(0, Math.min(per, n)) : 0;
      if (counts[key] !== counts[DOMAINS[0]]) level = false;
      if (low === null || counts[key] < counts[low]) low = key;
    });
    var total = typeof block.scored === "number"
      ? block.scored : per * DOMAINS.length;
    var hits = Math.max(0, Math.min(total, stored.hits));
    var band = null;
    var bands = ((block.predict || {}).bands) || {};
    if (stored.predict && bands[stored.predict]) band = bands[stored.predict];
    return {
      hits: hits, total: total, per: per, counts: counts,
      room: level ? "" : low,
      level: levelOf(block, hits),
      band: band,
      calibration: calibrationOf(band, hits)
    };
  }

  var CHECK_PATH = "M3.5 8.6l3.1 3.1 5.9-6.4";

  // The first thing a buyer sees, on both ways in: seconds after paying, and
  // a week later from the link in the mail. The address comes off the
  // authenticated report payload and is never touched again.
  function deliveryNote(ctx, copy) {
    if (!ctx.delivered) return null;
    var email = (((ctx.visuals || {}).delivery || {}).email || "").trim();
    var line = copy.delivery_line || "Your PDF was sent to {email}";
    var bare = copy.delivery_line_bare || "Your PDF was sent to your email";
    var bar = elm("p", "ai-sent");
    var mark = elm("span", "ai-sent-check");
    mark.appendChild(glyph(CHECK_PATH));
    bar.appendChild(mark);
    var text = elm("span", "ai-sent-text");
    if (!email || line.indexOf("{email}") === -1) {
      text.textContent = bare;
    } else {
      var cut = line.split("{email}");
      text.appendChild(document.createTextNode(cut[0]));
      text.appendChild(elm("span", "ai-sent-mail", email));
      text.appendChild(document.createTextNode(cut.slice(1).join("{email}")));
    }
    bar.appendChild(text);
    return bar;
  }

  function itemNode(item, index) {
    var row = elm("li", "ai-item");
    if (typeof item === "string") {
      row.textContent = item;
      return row;
    }
    var title = item.title || item.name || "";
    if (title) {
      var head = elm("p", "ai-item-title");
      head.appendChild(elm("span", "ai-item-n", String(index + 1)));
      head.appendChild(document.createTextNode(title));
      row.appendChild(head);
    }
    [item.body, item.priority_note, item.why].forEach(function (text) {
      if (text) row.appendChild(elm("p", "ai-body", text));
    });
    if (item.fix) row.appendChild(elm("p", "ai-item-fix", item.fix));
    return row;
  }

  // A section body, in whatever shape the report wrote it: a string, or the
  // typed block the report machinery uses — paragraphs, an opening, a list
  // of items, a closing rule. Anything this does not recognise is skipped
  // rather than guessed at, and a section with no data at all falls back to
  // its prose.
  function sectionBody(data) {
    var frag = document.createDocumentFragment();
    if (typeof data === "string") {
      frag.appendChild(elm("p", "ai-body", data));
      return frag;
    }
    (data.narrative || []).forEach(function (para) {
      if (typeof para === "string") frag.appendChild(elm("p", "ai-body", para));
    });
    if (data.intro) frag.appendChild(elm("p", "ai-body", data.intro));
    (data.pairs || []).forEach(function (pair) {
      var row = elm("div", "ai-pair");
      if (pair.combo) row.appendChild(elm("p", "ai-item-title", pair.combo));
      if (pair.why) row.appendChild(elm("p", "ai-body", pair.why));
      frag.appendChild(row);
    });
    var items = data.items || data.implications || [];
    if (items.length) {
      var list = elm("ul", "ai-list");
      items.forEach(function (item, index) {
        if (item) list.appendChild(itemNode(item, index));
      });
      frag.appendChild(list);
    }
    if (data.rule) frag.appendChild(elm("p", "ai-note", data.rule));
    (data.skip || []).forEach(function (row) {
      frag.appendChild(elm("p", "ai-note",
                           [row.name, row.why].filter(Boolean).join(" — ")));
    });
    if (data.closing_rule) {
      frag.appendChild(elm("p", "ai-note", data.closing_rule));
    }
    return frag;
  }

  function deliveredNode(ctx, section) {
    var item = node("open", section.title || "");
    var body = item.querySelector(".ai-node-body");
    var key = keywordOf(ctx, section.id);
    if (key) {
      body.insertBefore(elm("p", "ai-node-key", key + ":"), body.firstChild);
    }
    if (section.data) {
      try {
        var built = sectionBody(section.data);
        if (built.childNodes.length) {
          body.appendChild(built);
          return item;
        }
      } catch (e) { /* fall through to prose */ }
    }
    if (section.body) body.appendChild(elm("p", "ai-body", section.body));
    return item;
  }

  function delivered(root, ctx) {
    var copy = copyOf(ctx);
    var data = storedProfile(ctx);
    root.innerHTML = "";
    root.classList.add("is-ai", "is-delivered");
    var note = deliveryNote(ctx, copy);
    if (note) root.appendChild(note);
    if (data) {
      root.appendChild(hero(ctx, copy, data));
      var chip = levelChip(ctx, copy, data);
      if (chip) root.appendChild(chip);
    }
    root.appendChild(typeCard(ctx));
    if (data) root.appendChild(bars(ctx, copy, data));

    var list = elm("ol", "ai-path is-open");
    var want = (purposeRule(ctx) || {}).emphasized_section || "";
    firstly(ctx.sections || [], want).forEach(function (section) {
      list.appendChild(deliveredNode(ctx, section));
    });
    root.appendChild(list);

    // No offer here. What replaces it is the one line the reader still
    // needs — where else this document is — and what it is not.
    if (ctx.complete && copy.delivered_note) {
      root.appendChild(elm("p", "ai-footnote", copy.delivered_note));
    }
    var guides = articles(ctx, data, "delivered");
    if (guides) root.appendChild(guides);
    var foot = footer(copy);
    if (foot) root.appendChild(foot);
    root.hidden = false;
  }

  window.MazzinResult = { render: render, delivered: delivered };
}());
