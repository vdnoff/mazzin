/* The AI Navigator funnel's result page, before and after the money.
 *
 * engine.js loads this when a config names it and hands it the finished run.
 * The two things that must not be got wrong, the withdrawal-right consent and
 * the button that charges, are engine.js's own live nodes moved into this
 * layout rather than rebuilt in it. There is no payment path in this file and
 * no call that starts one.
 *
 * The free page is three blocks: who the reader is (the type and one line),
 * how they scored against their own prediction (a ring and a sentence), and
 * the offer, with engine.js's pay button inside it. Under those, what the
 * report unlocks, the partner guides where the visit carries a click to pass
 * on, and the disclaimer. The page never names a strategy and never says
 * which answer was right: the rows in the offer card are labels and empty
 * bars, and nothing of the report's text is in the DOM before it is bought.
 *
 * The paid page adds the zone bars, the strategies card, the four sections
 * and the eight scenarios with the reader's move, the right move and why.
 *
 * Nothing here holds a number of its own. How many scenarios there are, how
 * many per zone, what the zones are called, where the levels start and which
 * band each prediction means all come off `brain_age` in the config — the
 * block keeps the key focus and brain use because the report machinery reads
 * it by that name — and every sentence comes off `result_copy`.
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
  // number shown is always out of the full eight.
  function profileOf(ctx) {
    var block = numbers(ctx);
    if (!block) return null;
    var scores = ctx.scores || {};
    var per = typeof block.per_domain === "number" ? block.per_domain : 2;
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

  // --- 1) who they are -------------------------------------------------------

  function profileBlock(ctx, copy) {
    var card = elm("section", "ai-profile");
    if (ctx.style.id) card.setAttribute("data-type", ctx.style.id);
    if (copy.kicker) card.appendChild(elm("p", "ai-kicker", copy.kicker));
    card.appendChild(elm("h1", "ai-type-name", ctx.style.name || ""));
    var essence = (profileCopy(ctx).essence || {})[ctx.style.id] || "";
    if (essence) card.appendChild(elm("p", "ai-type-essence", essence));
    return card;
  }

  // --- 2) the score, against their own prediction ----------------------------

  var RING_R = 34;

  function ring(data, copy) {
    var size = 2 * RING_R + 16;
    var mid = size / 2;
    var around = 2 * Math.PI * RING_R;
    var share = data.total ? Math.max(0, Math.min(1, data.hits / data.total))
      : 0;
    var box = elm("div", "ai-ring");
    var svg = svgEl("svg", { viewBox: "0 0 " + size + " " + size,
                             "aria-hidden": "true" });
    svg.appendChild(svgEl("circle", { cx: mid, cy: mid, r: RING_R,
                                      "class": "ai-ring-track" }));
    var arc = svgEl("circle", { cx: mid, cy: mid, r: RING_R,
                                "class": "ai-ring-arc",
                                transform: "rotate(-90 " + mid + " " + mid + ")" });
    arc.setAttribute("stroke-dasharray",
                     (around * share).toFixed(2) + " " + around.toFixed(2));
    if (share > 0) svg.appendChild(arc);
    box.appendChild(svg);
    box.appendChild(elm("p", "ai-ring-n", fill(copy.score_of || "{n}/{total}",
                                               { n: data.hits,
                                                 total: data.total })));
    return box;
  }

  function scoreCard(ctx, copy, data) {
    var card = elm("section", "ai-scorecard");
    card.appendChild(ring(data, copy));
    var text = elm("div", "ai-score-text");
    if (data.band) {
      text.appendChild(elm("p", "ai-predict", fill(
        copy.calibration_line || "You predicted {band}. You scored {n}.",
        { band: data.band.label || (data.band.min + "–" + data.band.max),
          n: data.hits })));
      var word = (copy.calibration || {})[data.calibration] || "";
      if (word) {
        text.appendChild(elm("p", "ai-calibration is-" + data.calibration,
                             word));
      }
    } else {
      text.appendChild(elm("p", "ai-predict", fill(
        copy.score_only || "You scored {n} of {total}.",
        { n: data.hits, total: data.total })));
    }
    card.appendChild(text);
    return card;
  }

  // --- the four zones (the paid page only) -----------------------------------

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

  // --- 3) the offer ----------------------------------------------------------
  //
  // Labels and empty bars. The strategy's name and everything about it are
  // in the report and nowhere on this page: a bar is a decorative span with
  // no text in it, so there is nothing for a reader, a screen reader or a
  // scraper to lift.

  var OFFER_ID = "ai-offer";

  function bar(cls) {
    var node = elm("span", "ai-bar" + (cls ? " " + cls : ""));
    node.setAttribute("aria-hidden", "true");
    return node;
  }

  // "your 3–7 hours a week", from the card they tapped. Empty when the step
  // was never answered, and the line then says "your hours".
  function hoursOf(ctx, words) {
    var table = words.hours || {};
    var picks = ctx.picks || {};
    for (var id in picks) {
      if (!Object.prototype.hasOwnProperty.call(picks, id)) continue;
      var tags = (picks[id] && picks[id].tags) || [];
      for (var i = 0; i < tags.length; i++) {
        if (typeof table[tags[i]] === "string") return table[tags[i]];
      }
    }
    return "";
  }

  function offer(ctx, copy) {
    var words = copy.offer || {};
    var card = elm("section", "ai-offer");
    card.id = OFFER_ID;
    var nodes = ctx.nodes || {};
    var checkout = (ctx.cfg && ctx.cfg.checkout) || {};
    var priced = typeof ctx.withPrice === "function"
      ? ctx.withPrice : function (text) { return text; };

    // What it is, in the words the reader came for, and the one thing the
    // page will not show: a bar where the strategy's name will be.
    var top = elm("div", "ai-offer-top");
    var label = elm("p", "ai-offer-label");
    label.appendChild(elm("span", "", words.label || ""));
    label.appendChild(glyph(LOCK_PATH, "ai-lock-icon"));
    top.appendChild(label);
    if (words.head) top.appendChild(elm("h2", "ai-offer-head", words.head));
    top.appendChild(bar("is-name"));
    if (words.line) top.appendChild(elm("p", "ai-offer-line", words.line));
    card.appendChild(top);

    var list = words.unlock || [];
    if (list.length) {
      var rule = elm("hr", "ai-offer-rule");
      rule.setAttribute("aria-hidden", "true");
      card.appendChild(rule);
      var group = elm("div", "ai-offer-list");
      if (words.unlock_title) {
        group.appendChild(elm("p", "ai-offer-sublabel", words.unlock_title));
      }
      var hours = hoursOf(ctx, words) || words.hours_bare || "";
      var rows = elm("ul", "ai-checks");
      list.forEach(function (text) {
        var row = elm("li", "ai-check");
        row.appendChild(glyph(CHECK_PATH, "ai-check-icon"));
        row.appendChild(elm("span", "", fill(text, { hours: hours })));
        rows.appendChild(row);
      });
      group.appendChild(rows);
      card.appendChild(group);
    }

    // A funnel that asks for no consent tick still has the box: engine.js
    // gates the pay button on it. Ticked here, announced the way a real tick
    // is, and kept out of sight. Where the funnel does ask, the row is the
    // engine's own and goes above the button.
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

    if (words.under) {
      card.appendChild(elm("p", "ai-offer-under", priced(words.under)));
    }

    // The paywall's own rows have nothing left to say on this page.
    [nodes.manifest, nodes.anchor, nodes.price, nodes.trust]
      .forEach(function (n) { if (n) n.hidden = true; });

    if (typeof ctx.watchOffer === "function") ctx.watchOffer(card);
    return card;
  }

  var CHECK_PATH = "M3.5 8.6l3.1 3.1 5.9-6.4";

  function footer(ctx, copy) {
    var foot = elm("footer", "ai-foot");
    if (copy.disclaimer) foot.appendChild(elm("p", "", copy.disclaimer));
    var legal = ctx.nodes && ctx.nodes.legal;
    if (legal && !ctx.delivered) foot.appendChild(legal);
    return foot.childNodes.length ? foot : null;
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
  var ARROW_PATH = "M3.5 8h9M8.5 4l4 4-4 4";
  // The one article that is the same for every reader. Drawn first, and
  // only when the config carries an article under this key.
  var FEATURED = "start";

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
  // The zone the second guide is picked for. Where the run has a zone with
  // the most room it is that one, the same one the score card and the report
  // name. A level run has none, and a guides card with one button reads as
  // half a card, so for this block only the tie is broken in a fixed order:
  // business sense first, since that is the question a reader who is not
  // buying yet is most likely asking.
  var GUIDE_TIE = ["spa", "foc", "chg", "mem"];

  function guideZone(data) {
    if (!data) return "";
    if (data.room) return data.room;
    var counts = data.counts || {};
    var low = null;
    DOMAINS.forEach(function (key) {
      if (low === null || counts[key] < low) low = counts[key];
    });
    for (var i = 0; i < GUIDE_TIE.length; i++) {
      if (counts[GUIDE_TIE[i]] === low) return GUIDE_TIE[i];
    }
    return "";
  }

  // The words on the skill card they tapped, for the tag over its guide.
  function skillLabel(ctx, tag) {
    var steps = (ctx.cfg && ctx.cfg.swipe && ctx.cfg.swipe.steps) || [];
    for (var i = 0; i < steps.length; i++) {
      var cards = ((steps[i].pairs || [])[0] || {}).images || [];
      for (var j = 0; j < cards.length; j++) {
        if ((cards[j].tags || []).indexOf(tag) !== -1) {
          return cards[j].label || "";
        }
      }
    }
    return "";
  }

  function rsocKeys(ctx, block, data) {
    var keys = { skill: "", zone: "" };
    if (!ctx.delivered) {
      keys.skill = skillKey(ctx, block);
      keys.zone = guideZone(data);
      try { sessionStorage.setItem(RSOC_KEY, JSON.stringify(keys)); }
      catch (e) { /* private mode */ }
      return keys;
    }
    // The report first: it stores the skill the reader named and the four
    // counts the zone is read off, and it is the same on every device this
    // page is opened on. Session storage is what is left for a report
    // written before it stored them.
    var run = (ctx.visuals && ctx.visuals.brain) || {};
    if (typeof run.skill === "string") keys.skill = run.skill;
    if (data) keys.zone = guideZone(data);
    var stored = null;
    try { stored = JSON.parse(sessionStorage.getItem(RSOC_KEY) || "null"); }
    catch (e) { stored = null; }
    if (stored && typeof stored === "object") {
      if (!keys.skill && typeof stored.skill === "string") {
        keys.skill = stored.skill;
      }
      if (!data && typeof stored.zone === "string") keys.zone = stored.zone;
    }
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
    // The featured guide first, where the config has one; then the skill's;
    // then the zone's. Never the same article twice.
    [FEATURED, keys.skill, DOMAINS.indexOf(keys.zone) !== -1 ? keys.zone : ""]
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
    var late = slot === "delivered";
    var box = elm("section", "ai-rsoc");
    box.setAttribute("data-slot", slot);
    var kicker = late ? block.kicker_delivered : block.kicker;
    if (kicker) box.appendChild(elm("p", "ai-rsoc-kicker", kicker));
    var head = late ? block.head_delivered : block.head;
    if (head) box.appendChild(elm("h2", "ai-rsoc-head", head));
    if (block.sub) {
      box.appendChild(elm("p", "ai-rsoc-sub",
                          fill(block.sub, { n: chosen.length })));
    }
    var list = elm("div", "ai-rsoc-list");
    chosen.forEach(function (item) {
      var first = item.key === FEATURED;
      var link = elm("a", "ai-rsoc-link" + (first ? " is-featured" : ""));
      var words = elm("span", "ai-rsoc-words");
      var tag = first ? (block.tag_start || "")
        : item.key === keys.skill
          ? fill(block.tag_skill || "", { skill: skillLabel(ctx, item.key) })
          : fill(block.tag_zone || "", { zone: zoneName(ctx, item.key) });
      if (tag) words.appendChild(elm("span", "ai-rsoc-tag", tag));
      words.appendChild(elm("span", "ai-rsoc-text", item.label));
      link.appendChild(words);
      link.appendChild(glyph(ARROW_PATH, "ai-rsoc-arrow"));
      link.href = item.link + (tail ? "?" + tail : "");
      link.target = "_blank";
      link.rel = "noopener";
      link.setAttribute("data-article", item.key);
      link.addEventListener("click", function () {
        // The funnel's own pixel hears of a guide once per tab; the id it
        // fired under rides on the tap's own event. Neither is waited for:
        // the link opens as it always did.
        var cart = typeof ctx.pixelOnce === "function"
          ? ctx.pixelOnce("AddToCart",
                          { content_name: item.key, content_category: slot },
                          item.key)
          : null;
        if (typeof ctx.track === "function") {
          if (cart) ctx.track("article_tap", { article: item.key, slot: slot }, cart);
          else ctx.track("article_tap", { article: item.key, slot: slot });
        }
      });
      list.appendChild(link);
    });
    box.appendChild(list);
    if (block.note) box.appendChild(elm("p", "ai-rsoc-note", block.note));
    return box;
  }

  // --- the free page ---------------------------------------------------------

  function render(root, ctx) {
    var copy = copyOf(ctx);
    var data = profileOf(ctx);

    root.innerHTML = "";
    root.classList.add("is-ai");
    root.classList.remove("is-delivered");
    root.appendChild(profileBlock(ctx, copy));
    if (data) root.appendChild(scoreCard(ctx, copy, data));
    root.appendChild(offer(ctx, copy));
    // The second way out, and for most readers the one they take: directly
    // under the offer, so still after the pay button, and above the list.
    var guides = articles(ctx, data, "below_paywall");
    if (guides) root.appendChild(guides);
    var foot = footer(ctx, copy);
    if (foot) root.appendChild(foot);

    // The engine's commerce block is replaced by the offer card above.
    if (ctx.nodes && ctx.nodes.commerce) ctx.nodes.commerce.hidden = true;
    root.hidden = false;
  }

  // --- the paid page ---------------------------------------------------------

  function storedProfile(ctx) {
    var stored = (ctx.visuals && ctx.visuals.brain) || null;
    var block = numbers(ctx);
    if (!stored || !block || typeof stored.hits !== "number") return null;
    var per = typeof block.per_domain === "number" ? block.per_domain : 2;
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
  // The two badges a path wears, set once per render from the config.
  var BADGES = {};

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
      if (pair.combo) {
        var name = elm("p", "ai-item-title", pair.combo);
        var word = BADGES[pair.verdict];
        if (word) {
          name.appendChild(document.createTextNode(" "));
          name.appendChild(elm("span", "ai-badge is-" + pair.verdict, word));
        }
        row.appendChild(name);
      }
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

  // --- the paths card ---------------------------------------------------------
  //
  // The reader's three paths with the facts about each, and the two to skip
  // for now. Which five, and every sentence under them, is what the server
  // worked out from the config's table and stored with the report: nothing
  // here chooses a path and nothing here is the model's.

  var FACTS = ["sells", "buyer", "first_client", "startup", "risk"];

  function pathCard(card, words, first, only) {
    var box = elm("div", "ai-pathcard" + (first ? " is-first" : ""));
    box.appendChild(elm("p", "ai-pathcard-name", card.name || ""));
    var list = elm("dl", "ai-facts");
    FACTS.forEach(function (field) {
      if (!card[field] || (only && only.indexOf(field) === -1)) return;
      list.appendChild(elm("dt", "", (words.facts || {})[field] || field));
      list.appendChild(elm("dd", "", card[field]));
    });
    box.appendChild(list);
    return box;
  }

  function pathsCard(ctx, copy) {
    var paths = (ctx.visuals && ctx.visuals.paths) || null;
    if (!paths || !Array.isArray(paths.works) || !paths.works.length) {
      return null;
    }
    var words = copy.paths_card || {};
    var card = elm("section", "ai-paths");
    if (words.title) card.appendChild(elm("h2", "ai-h2", words.title));
    if (words.lead) card.appendChild(elm("p", "ai-caption", words.lead));
    if (paths.format && words.format) {
      var line = elm("p", "ai-paths-format", words.format + " ");
      line.appendChild(elm("b", "", paths.format));
      card.appendChild(line);
    }
    paths.works.forEach(function (row, index) {
      card.appendChild(pathCard(row, words, index === 0, null));
    });
    var skip = Array.isArray(paths.avoid) ? paths.avoid : [];
    if (skip.length) {
      if (words.skip_title) {
        card.appendChild(elm("p", "ai-paths-sub", words.skip_title));
      }
      skip.forEach(function (row) {
        card.appendChild(pathCard(row, words, false, ["sells", "risk"]));
      });
    }
    return card;
  }

  // The eight scenarios: the question, their move, the right move and what it
  // means. Stored with the report; nothing here is recomputed on the page.
  function scenarios(ctx, copy) {
    var rows = (ctx.visuals && ctx.visuals.answer_key) || null;
    if (!Array.isArray(rows) || !rows.length) return null;
    var words = copy.key_card || {};
    var card = elm("section", "ai-key");
    if (words.title) card.appendChild(elm("h2", "ai-h2", words.title));
    if (words.lead) card.appendChild(elm("p", "ai-caption", words.lead));
    var list = elm("ol", "ai-key-list");
    rows.forEach(function (row) {
      var item = elm("li", "ai-key-row is-" + (row.hit ? "hit" : "miss"));
      item.appendChild(elm("span", "ai-badge is-" + (row.hit ? "hit" : "miss"),
                           (row.hit ? words.hit : words.miss) || ""));
      item.appendChild(elm("p", "ai-key-q", row.question || ""));
      var mine = elm("p", "ai-key-line");
      mine.appendChild(elm("span", "ai-key-lab", (words.yours || "") + " "));
      mine.appendChild(document.createTextNode(
        row.yours || words.none || ""));
      item.appendChild(mine);
      var right = elm("p", "ai-key-line");
      right.appendChild(elm("span", "ai-key-lab", (words.right || "") + " "));
      right.appendChild(document.createTextNode(row.right || ""));
      item.appendChild(right);
      if (row.why) item.appendChild(elm("p", "ai-key-why", row.why));
      list.appendChild(item);
    });
    card.appendChild(list);
    return card;
  }

  function delivered(root, ctx) {
    var copy = copyOf(ctx);
    var data = storedProfile(ctx);
    var badge = copy.paths_card || {};
    BADGES = { works: badge.badge_works || "", avoid: badge.badge_avoid || "" };
    root.innerHTML = "";
    root.classList.add("is-ai", "is-delivered");
    var note = deliveryNote(ctx, copy);
    if (note) root.appendChild(note);
    root.appendChild(profileBlock(ctx, copy));
    if (data) {
      root.appendChild(scoreCard(ctx, copy, data));
      root.appendChild(bars(ctx, copy, data));
    }
    var fits = pathsCard(ctx, copy);
    if (fits) root.appendChild(fits);

    var list = elm("ol", "ai-path is-open");
    var want = (purposeRule(ctx) || {}).emphasized_section || "";
    firstly(ctx.sections || [], want).forEach(function (section) {
      list.appendChild(deliveredNode(ctx, section));
    });
    root.appendChild(list);
    var key = scenarios(ctx, copy);
    if (key) root.appendChild(key);

    if (ctx.complete && copy.delivered_note) {
      root.appendChild(elm("p", "ai-footnote", copy.delivered_note));
    }
    var guides = articles(ctx, data, "delivered");
    if (guides) root.appendChild(guides);
    var foot = footer(ctx, copy);
    if (foot) root.appendChild(foot);
    root.hidden = false;
  }

  window.MazzinResult = { render: render, delivered: delivered };
}());
