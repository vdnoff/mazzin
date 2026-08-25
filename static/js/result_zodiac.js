/* The zodiac funnel's pre-purchase result page.
 *
 * Loaded by engine.js when a config names it, handed the finished run, and
 * responsible for everything the reader sees between the analysing screen and
 * the money. It is not a second engine: it computes nothing about the quiz,
 * it renders what it is given, and the two things that must not be got wrong
 * — the withdrawal-right consent and the button that charges — are engine.js's
 * own live nodes, moved into this layout rather than rebuilt in it.
 *
 * The page, top to bottom: a kicker, the rich profile card, the strip of
 * frames they actually tapped, the one strength they get for nothing, and the
 * six questions the reading answers — each behind a lock — over the offer.
 *
 * The card is a named subtype rather than a crossing of two words: the run's
 * tallies resolve to an archetype, a runner-up element and an energy lean,
 * and `result_copy.profile` in the config turns those three into a name, a
 * measured rarity and a line about the reader's own sign. That table is
 * written into both zodiac configs by scripts/gen_profile_rarity.py, from one
 * source, so the two funnels cannot drift apart.
 *
 * A config with no `profile` block still renders: the old cosmic ID card and
 * the constellation path are kept below and drawn instead. This file and the
 * config it reads sit behind a CDN and can be a version apart, and a reader
 * who arrives in that window should get last week's page rather than none.
 */
(function () {
  "use strict";

  // This funnel's scoring axes. engine.js deliberately does not know these —
  // the vocabulary belongs to the funnel — so the grouping happens here and
  // the raw tallies come across.
  var ELEMENTS = ["fire", "earth", "air", "water"];
  var ENERGY = ["sun", "moon"];

  // The gallery's own families, so a bar and its frames are the same colour.
  var ELEMENT_COLOR = {
    fire: "#E08A3C", earth: "#7E9B5E", air: "#9CC3DF", water: "#4E8FA0"
  };
  var ELEMENT_NAME = {
    fire: "Fire", earth: "Earth", air: "Air", water: "Water"
  };
  var ENERGY_NAME = { sun: "Sun", moon: "Moon" };

  // The tone axis, as this funnel actually tags it. There is no `grounded`
  // tag and there never was one: `mystic` is the single tag the vocabulary
  // spends on the otherworldly, and `bold` and `calm` are what it spends on
  // everything else. So the mystic-to-grounded scale reads mystic against the
  // sum of the other two — a real measurement of the run rather than an
  // invented one, which is why most dots on it sit right of centre.
  var TONE = ["bold", "calm", "mystic"];

  // The reader's year runs from the month they are in, not from January, and
  // the Year card names both ends of it. reports.py builds the same twelve
  // server-side, stores them on the report and holds the generated section to
  // them; this is the free page's copy of the arithmetic, which is all it can
  // be — nothing has been bought yet, so there is no report to read them off.
  // A reader on the last night of a month can be a few hours out of step with
  // the server on the label; what neither of them ever shows is a year that
  // opens on a month already over.
  var MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  function yearLabels(from) {
    var day = from || new Date();
    var year = day.getFullYear();
    var month = day.getMonth();
    var out = [];
    for (var i = 0; i < 12; i++) {
      out.push(MONTH_ABBR[month] + " " + year);
      month += 1;
      if (month > 11) { month = 0; year += 1; }
    }
    return out;
  }

  // The stored twelve where there are any — a page reached after the money
  // shows the year the report was written for, not the year it is being read
  // in — and this month's otherwise.
  function yearOf(ctx) {
    var stored = (ctx.visuals && ctx.visuals.year) || null;
    return (stored && stored.length === 12) ? stored : yearLabels();
  }

  // The fewest frames worth calling a grid. Below this the run did not
  // happen, and a row of two squares under "read from your taps" reads as a
  // page that failed rather than as evidence.
  var TAPS_MIN = 4;

  function elm(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  // The strongest tag in a set. A tie goes to whichever one the winning style
  // is scored on, because the card says both — "Scorpio × Radiant Fire, 35%
  // Fire" — and a tie broken by array order can print an element the
  // archetype beside it does not carry.
  function lead(rows, prefer) {
    var own = prefer || [];
    return rows.reduce(function (best, row) {
      if (!best || row.score > best.score) return row;
      if (row.score === best.score
          && own.indexOf(row.tag) !== -1 && own.indexOf(best.tag) === -1) {
        return row;
      }
      return best;
    }, null);
  }

  function share(rows, row) {
    var total = rows.reduce(function (sum, r) {
      return sum + Math.max(0, r.score);
    }, 0);
    if (!total || !row) return 0;
    return Math.round(100 * Math.max(0, row.score) / total);
  }

  // --- the derived profile ---------------------------------------------------
  //
  // Everything the hero card says, computed from the tallies the run already
  // produced. Nothing here asks engine.js for anything new: the archetype,
  // the runner-up element and the energy lean are all in `ctx.tally`, and the
  // names, the rarity and the sign line are all in the config.
  //
  // reports.py computes the same block server-side and stores it on the
  // report, because the delivered page is opened from a link in an email in a
  // tab that never ran the quiz. The two must agree, so every tiebreak below
  // is stated rather than left to whichever order an array happened to be in.

  function profileBlock(ctx) {
    var table = ((ctx.cfg && ctx.cfg.result_copy) || {}).profile;
    return (table && typeof table === "object") ? table : null;
  }

  // A tally as a plain object, with anything the inverse step pushed below
  // zero read as zero. A negative score is a tap they told us to keep away
  // from; it is not a negative share of who they are.
  function positive(rows) {
    var out = {};
    rows.forEach(function (row) { out[row.tag] = Math.max(0, row.score); });
    return out;
  }

  // Where a dot sits between two poles, 0 hard left and 100 hard right.
  // Nothing measured on either side is dead centre rather than zero: a run
  // that scored neither has not leant left, it has not leant.
  function between(left, right) {
    var total = left + right;
    if (!total) return 50;
    return Math.round(100 * right / total);
  }

  // Four whole percents that add to a hundred. Rounding each share on its own
  // gives 33/33/17/16 as readily as not, and a caption whose numbers sum to
  // 99 is the one thing on this card a reader can check for themselves.
  function splitOf(elements) {
    var raw = elements.map(function (row) { return Math.max(0, row.score); });
    var total = raw.reduce(function (a, b) { return a + b; }, 0);
    var pcts;
    if (!total) {
      pcts = raw.map(function () { return Math.round(100 / raw.length); });
    } else {
      var exact = raw.map(function (value) { return 100 * value / total; });
      pcts = exact.map(function (value) { return Math.floor(value); });
      var owed = 100 - pcts.reduce(function (a, b) { return a + b; }, 0);
      exact
        .map(function (value, i) { return { i: i, frac: value % 1 }; })
        .sort(function (a, b) { return (b.frac - a.frac) || (a.i - b.i); })
        .slice(0, Math.max(0, owed))
        .forEach(function (row) { pcts[row.i] += 1; });
    }
    return elements.map(function (row, i) {
      return {
        tag: row.tag,
        name: ELEMENT_NAME[row.tag] || row.tag,
        pct: pcts[i],
        color: ELEMENT_COLOR[row.tag] || "#E8C878"
      };
    });
  }

  function fill(text, words) {
    if (!text) return "";
    return String(text).replace(/\{(\w+)\}/g, function (whole, key) {
      return Object.prototype.hasOwnProperty.call(words, key)
        ? words[key] : whole;
    });
  }

  // The whole card, or null when the config carries no table for it — which
  // is what sends `render` back to the page it drew before this existed.
  function profileOf(ctx, elements, top) {
    var table = profileBlock(ctx);
    if (!table || !table.subtypes) return null;

    var scores = positive(elements);
    var primary = top.tag;
    // The runner-up, never the archetype's own element. A tie falls to the
    // declared element order — the same rule the generator counts the rarity
    // by, because a name resolved on one rule and counted on another is a
    // number about nothing.
    var second = ELEMENTS
      .filter(function (tag) { return tag !== primary; })
      .reduce(function (best, tag) {
        return (best === null || scores[tag] > scores[best]) ? tag : best;
      }, null);

    var energyScores = positive(ctx.tally(ENERGY));
    var own = ctx.style.tags || [];
    var energy;
    if (energyScores.sun > energyScores.moon) {
      energy = "sun";
    } else if (energyScores.moon > energyScores.sun) {
      energy = "moon";
    } else {
      // Dead level. The archetype's own energy carries it, because the name
      // beside the number says both, and a tie broken by list order can print
      // an energy the archetype does not hold.
      energy = ENERGY.filter(function (tag) {
        return own.indexOf(tag) !== -1;
      })[0] || ENERGY[0];
    }

    var name = ((table.subtypes[ctx.style.id] || {})[second] || {})[energy];
    if (!name) return null;

    var pick = ctx.picks && ctx.picks.sign;
    var sign = (pick && pick.id !== "sign_cusp" && pick.label) || "";
    var crossKey = sign || ((pick && pick.id === "sign_cusp") ? "cusp" : "");

    var tone = positive(ctx.tally(TONE));
    var at = {
      energy: between(energyScores.sun, energyScores.moon),
      tone: between(tone.bold, tone.calm),
      depth: between(tone.mystic, tone.bold + tone.calm)
    };
    var split = splitOf(elements);
    var rarity = (((table.rarity || {})[ctx.style.id] || {})[second]
                  || {})[energy] || 0;

    var bare = name.replace(/^The\s+/, "");
    var year = yearOf(ctx);
    var words = {
      first: year[0],
      last: year[year.length - 1],
      sign: sign,
      subtype: name,
      subtype_bare: bare,
      subtype_article: /^[AEIOU]/.test(bare) ? "an" : "a",
      element: ELEMENT_NAME[primary] || primary,
      second: ELEMENT_NAME[second] || second,
      energy: ENERGY_NAME[energy] || energy,
      n: String(rarity)
    };
    split.forEach(function (cell) { words[cell.tag] = String(cell.pct); });

    return {
      archetype: ctx.style.id,
      primary: primary,
      second: second,
      energy: energy,
      sign: sign,
      subtype: name,
      subtype_bare: bare,
      rarity: rarity,
      words: words,
      // The formula loses its leading separator rather than printing one when
      // a run never reached the sign step.
      formula: fill(table.formula || "", words).replace(/^\s*·\s*/, ""),
      rarity_line: rarity ? fill(table.rarity_line || "", words) : "",
      cross_line: ((table.sign_cross || {})[crossKey] || {})[primary] || "",
      split: split,
      split_caption: fill(table.split_caption || "", words),
      scales: (table.scales || []).map(function (row) {
        return {
          id: row.id, left: row.left, right: row.right,
          at: (typeof at[row.id] === "number") ? at[row.id] : 50
        };
      })
    };
  }

  // --- a) the kicker ---------------------------------------------------------

  function kicker(copy) {
    return elm("p", "zr-kicker", copy.kicker || "YOUR COSMIC PROFILE");
  }

  // --- b) the cosmic ID ------------------------------------------------------

  // Their own sign frame, masked to a disc. The glyph is centred in the art,
  // so a centre crop is the glyph and nothing else needs drawing.
  function glyph(pick) {
    var badge = elm("span", "zr-glyph");
    if (!pick) return badge;
    var img = document.createElement("img");
    img.src = pick.img;
    img.alt = "";
    img.decoding = "async";
    badge.appendChild(img);
    return badge;
  }

  function hero(ctx, copy, elements, top) {
    var card = elm("section", "zr-hero");
    card.appendChild(glyph(ctx.picks.sign));

    var sign = (ctx.picks.sign && ctx.picks.sign.label) || ctx.style.name;
    card.appendChild(elm("h1", "zr-sign", sign));
    card.appendChild(elm("p", "zr-cross", "× " + ctx.style.name));

    var pct = share(elements, top);
    var bar = elm("div", "zr-bar");
    bar.setAttribute("role", "img");
    bar.setAttribute("aria-label",
                     pct + "% " + (ELEMENT_NAME[top.tag] || top.tag));
    var fill = elm("span", "zr-bar-fill");
    fill.style.width = pct + "%";
    fill.style.background = ELEMENT_COLOR[top.tag] || "#E8C878";
    bar.appendChild(fill);
    card.appendChild(bar);

    var led = lead(ctx.tally(ENERGY), ctx.style.tags);
    var parts = [pct + "% " + (ELEMENT_NAME[top.tag] || top.tag)];
    if (led && led.score > 0) {
      parts.push((ENERGY_NAME[led.tag] || led.tag) + "-led");
    }
    if (copy.blend_note) parts.push(copy.blend_note);
    card.appendChild(elm("p", "zr-sub", parts.join(" · ")));
    return card;
  }

  // --- b2) the rich profile card ---------------------------------------------
  //
  // The card the mockup asked for, and the one both halves of the funnel now
  // draw: glyph and name on one row, the gold rarity ribbon under it, three
  // spectrum scales, the four-element split, and the reader's own sign read
  // against the element they actually led with.
  //
  // It takes a finished block rather than a run, because the delivered page
  // has no run to give it — reports.py stores the same shape on the report
  // and `deliveredHero` hands it straight in.

  function scaleRow(row) {
    var wrap = elm("div", "zr-scale");
    wrap.appendChild(elm("span", "zr-scale-pole", row.left));
    var track = elm("span", "zr-scale-track");
    track.setAttribute("role", "img");
    track.setAttribute("aria-label",
                       row.left + " to " + row.right + " — " + row.at
                       + " out of 100 toward " + row.right);
    var dot = elm("i", "zr-scale-dot");
    dot.style.left = row.at + "%";
    track.appendChild(dot);
    wrap.appendChild(track);
    wrap.appendChild(elm("span", "zr-scale-pole is-right", row.right));
    return wrap;
  }

  function splitBar(data) {
    var wrap = elm("div", "zr-split");
    var bar = elm("div", "zr-split-bar");
    bar.setAttribute("role", "img");
    bar.setAttribute("aria-label", data.split_caption || "");
    (data.split || []).forEach(function (cell) {
      var seg = elm("span", "zr-split-seg");
      seg.style.width = cell.pct + "%";
      seg.style.background = cell.color || "#E8C878";
      bar.appendChild(seg);
    });
    wrap.appendChild(bar);
    if (data.split_caption) {
      wrap.appendChild(elm("p", "zr-split-caption", data.split_caption));
    }
    return wrap;
  }

  function richHero(badge, data) {
    var card = elm("section", "zr-hero is-rich");
    var head = elm("div", "zr-hero-top");
    head.appendChild(badge);
    var id = elm("div", "zr-hero-id");
    id.appendChild(elm("h1", "zr-subtype", data.subtype));
    if (data.formula) id.appendChild(elm("p", "zr-formula", data.formula));
    head.appendChild(id);
    card.appendChild(head);

    if (data.rarity_line) {
      card.appendChild(elm("p", "zr-ribbon", data.rarity_line));
    }
    if ((data.scales || []).length) {
      var scales = elm("div", "zr-scales");
      data.scales.forEach(function (row) {
        scales.appendChild(scaleRow(row));
      });
      card.appendChild(scales);
    }
    if ((data.split || []).length) card.appendChild(splitBar(data));
    if (data.cross_line) {
      card.appendChild(elm("hr", "zr-hairline"));
      card.appendChild(elm("p", "zr-crossline", data.cross_line));
    }
    return card;
  }

  // --- c) read from your taps ------------------------------------------------

  // Every frame of the run, six to a row, in the order they were tapped.
  //
  // It was five of them with their names under, chosen from a list of the
  // interesting steps. The whole claim of this block is "this reading was
  // read off these", and five out of eighteen is a sample rather than a
  // record — so it is all of them now, small and unlabelled, because the
  // point is the count and the fact that the reader recognises every square.
  // The names are gone with the size: at a sixth of the width a caption is
  // two clipped words.
  //
  // No new bytes on the wire. Every one of these files was decoded during the
  // quiz and is in the browser's cache; the grid is the same images again.

  function tapsGrid(picks) {
    var row = elm("ul", "zr-taps-grid");
    picks.forEach(function (pick) {
      var cell = elm("li", "zr-tap");
      var img = document.createElement("img");
      img.src = pick.img;
      img.alt = "";
      img.loading = "lazy";
      img.decoding = "async";
      cell.appendChild(img);
      row.appendChild(cell);
    });
    return row;
  }

  function tapsBlock(copy, picks) {
    if (picks.length < TAPS_MIN) return null;
    var block = elm("section", "zr-taps");
    block.appendChild(elm("p", "zr-taps-caption",
                          copy.taps_caption || "Read from your taps:"));
    block.appendChild(tapsGrid(picks));
    return block;
  }

  // Choice order is step order: the quiz walks its steps front to back, so
  // reading `picks` off the config's own step list puts the squares in the
  // order the reader put them there. A step they somehow did not answer is
  // absent rather than a gap.
  function taps(ctx, copy) {
    var steps = (ctx.cfg && ctx.cfg.swipe && ctx.cfg.swipe.steps) || [];
    var picks = steps
      .map(function (step) { return ctx.picks[step.id]; })
      .filter(function (pick) { return pick && pick.img; });
    return tapsBlock(copy, picks);
  }

  // The same grid after the money. The run is gone by now — this page is
  // opened from a link in a mail — so the ids travel on the report the way
  // the hero card and the section photographs do.
  function deliveredTaps(ctx, copy) {
    var want = (ctx.visuals && ctx.visuals.taps) || [];
    var picks = want
      .map(function (id) { return ctx.images[id]; })
      .filter(function (pick) { return pick && pick.img; });
    return tapsBlock(copy, picks);
  }

  // --- the reader's own reason for being here --------------------------------
  //
  // One step on this funnel asks what pulled them here, and the card they tap
  // carries a service tag — purpose_love and its three siblings — that no
  // archetype scores against. This is the whole of what reads it.
  //
  // Everything below is gated on `result_copy.purpose_map` being in the
  // config. zodiac v1 carries no such block, so `rule` is null for it on
  // every path and it renders exactly the page it always did.

  function purposeMap(ctx) {
    var map = ((ctx.cfg && ctx.cfg.result_copy) || {}).purpose_map;
    return (map && typeof map === "object") ? map : null;
  }

  // Found by tag rather than by step id: which question asks this is the
  // funnel's business, and a module that hardcoded "seeking" would quietly
  // stop working the day the step was renamed.
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

  // The tag this run carries, or "". After the money there is no run left to
  // read: the tag is stored on the report and handed back, which is why this
  // looks in two places.
  function purposeTagOf(ctx) {
    var map = purposeMap(ctx);
    if (!map) return "";
    var tag = (ctx && ctx.purpose) || purposeTag(ctx, map);
    return (tag && Object.prototype.hasOwnProperty.call(map, tag)) ? tag : "";
  }

  // The rule for this run, or null for no personalisation at all — which is
  // what an unknown tag, a missing step and a funnel with no map all get.
  function purposeRule(ctx) {
    var map = purposeMap(ctx);
    if (!map) return null;
    var rule = map[purposeTagOf(ctx)];
    return (rule && typeof rule === "object") ? rule : null;
  }

  function emphasised(rule) {
    return (rule && rule.emphasized_section) || "";
  }

  // The section they came for, first; everything else in the order the report
  // declares. Only the first match moves — a list that reshuffled twice would
  // stop reading as a document with an order at all — and a name that matches
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

  // --- d) the constellation path ---------------------------------------------

  var LOCK_PATH = "M5 8V5.5a3 3 0 0 1 6 0V8M4 8h8v6H4z";

  function node(kind, title) {
    var item = elm("li", "zr-node is-" + kind);
    var mark = elm("span", "zr-node-mark");
    mark.setAttribute("aria-hidden", "true");
    if (kind === "open") {
      mark.textContent = "✦";
    } else {
      var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("viewBox", "0 0 16 16");
      var shape = document.createElementNS("http://www.w3.org/2000/svg",
                                           "path");
      shape.setAttribute("d", LOCK_PATH);
      shape.setAttribute("stroke-linejoin", "round");
      svg.appendChild(shape);
      mark.appendChild(svg);
    }
    item.appendChild(mark);
    var body = elm("div", "zr-node-body");
    body.appendChild(elm("h2", "zr-node-title", title));
    item.appendChild(body);
    return item;
  }

  // All four elements at once, so the winning one is a claim with the other
  // three standing next to it rather than a number on its own.
  function balance(ctx, copy, elements) {
    var item = node("open", copy.balance_title || "Your element balance");
    var chart = elm("div", "zr-balance");
    var top = Math.max.apply(null, elements.map(function (row) {
      return Math.max(0, row.score);
    }).concat([1]));
    elements.forEach(function (row) {
      var col = elm("div", "zr-bal");
      var track = elm("span", "zr-bal-track");
      var fill = elm("span", "zr-bal-fill");
      // A floor, so an element the reader scored nothing on is still a
      // labelled column rather than a gap in the chart.
      fill.style.height =
        Math.max(4, Math.round(100 * Math.max(0, row.score) / top)) + "%";
      fill.style.background = ELEMENT_COLOR[row.tag] || "#E8C878";
      track.appendChild(fill);
      col.appendChild(track);
      col.appendChild(elm("span", "zr-bal-name",
                          ELEMENT_NAME[row.tag] || row.tag));
      col.appendChild(elm("span", "zr-bal-pct", share(elements, row) + "%"));
      chart.appendChild(col);
    });
    item.querySelector(".zr-node-body").appendChild(chart);
    return item;
  }

  function strength(ctx, copy) {
    var one = ctx.strength;
    if (!one || !one.title || !one.body) return null;
    var item = node("open", ctx.strengthCopy.title || "Hidden Strength #1");
    var body = item.querySelector(".zr-node-body");

    // The line that makes this theirs. Filled by engine.js's own hook
    // machinery, so every name in it is a card this reader tapped.
    var opener = ctx.fillHook(copy.strength_lead || "");
    if (opener && opener.indexOf("{") === -1) {
      body.appendChild(elm("p", "zr-lead", opener));
    }
    body.appendChild(elm("h3", "zr-strength-title", one.title));
    body.appendChild(elm("p", "zr-strength-body", one.body));
    if (one.fix) {
      body.appendChild(elm("p", "zr-strength-fix", "→ " + one.fix));
    }
    return item;
  }

  function locked(ctx, section, copy, lead) {
    var item = node("locked", section.title);
    if (lead) item.classList.add("is-lead");
    var body = item.querySelector(".zr-node-body");
    var line = ctx.fillHook(section.teaser_line || "");
    if (line) {
      var teaser = elm("p", "zr-teaser", line);
      // One step up the tier the readability pass set, and no further: the
      // muted grey the rest of this page already uses for a line that is not
      // body copy and not a whisper. Set from the tokens rather than from a
      // new rule, because a new rule would be a new visual language for one
      // line on one funnel.
      if (lead) {
        teaser.classList.add("is-lead");
        teaser.style.color = "var(--zr-muted)";
        teaser.style.fontSize = "15px";
      }
      body.appendChild(teaser);
    }
    var lock = elm("span", "zr-lock", copy.locked_note || "Locked");
    lock.setAttribute("aria-hidden", "true");
    item.insertBefore(lock, null);
    return item;
  }

  function path(ctx, copy, elements) {
    var list = elm("ol", "zr-path");
    list.appendChild(balance(ctx, copy, elements));
    var free = strength(ctx, copy);
    if (free) list.appendChild(free);
    // The two open nodes above are the free half and keep their places. The
    // reorder is inside what is still shut, so the section they came for is
    // the first locked thing they meet rather than the fourth.
    var want = emphasised(purposeRule(ctx));
    var shut = ctx.sections.filter(function (s) { return s.locked; });
    firstly(shut, want).forEach(function (section) {
      list.appendChild(locked(ctx, section, copy, section.id === want));
    });
    return list;
  }

  // --- d2) the free strength, standing on its own ----------------------------
  //
  // The same node the constellation drew, out of the list. It is the only
  // open thing on this page now — the element balance moved into the hero —
  // so a one-item ordered list with a gold thread running down the side of it
  // would be a path drawn between one point and itself.

  function freeStrength(ctx, copy) {
    var one = strength(ctx, copy);
    if (!one) return null;
    // A list of one rather than a section, because `node` builds an `li` and
    // a stray list item outside a list is still `display: list-item` — which
    // draws a second, smaller bullet beside the gold star.
    var block = elm("ul", "zr-free");
    block.appendChild(one);
    return block;
  }

  // --- d3) the six questions -------------------------------------------------
  //
  // What replaced the locked constellation nodes. A node said "Love &
  // Compatibility" and left the reader to work out what that was worth; a
  // card names the question the chapter answers, keyword first, and the
  // delivered page puts the same keyword back over the same section so what
  // they open is recognisably what they bought.

  var ICONS = {
    heart: ["M8 13.4C8 13.4 2.4 10 2.4 6.2A2.9 2.9 0 0 1 8 4.9"
            + "a2.9 2.9 0 0 1 5.6 1.3c0 3.8-5.6 7.2-5.6 7.2z"],
    eye: ["M1.4 8S4 3.6 8 3.6 14.6 8 14.6 8 12 12.4 8 12.4 1.4 8 1.4 8z",
          "M8 6.1A1.9 1.9 0 1 0 8 9.9a1.9 1.9 0 0 0 0-3.8z"],
    calendar: ["M2.6 4.4h10.8v9.1H2.6z", "M2.6 7.1h10.8",
               "M5.5 2.5v3.2", "M10.5 2.5v3.2"],
    coin: ["M8 2.4a5.6 5.6 0 1 0 0 11.2A5.6 5.6 0 0 0 8 2.4z",
           "M9.9 6.1C9.4 5.4 8.8 5.1 8 5.1c-1 0-1.8.5-1.8 1.3 0 1.9 3.6.9"
           + " 3.6 2.9 0 .9-.8 1.5-1.8 1.5-.9 0-1.6-.4-2-1.1",
           "M8 4v8"],
    palette: ["M8 2.4a5.6 5.6 0 0 0 0 11.2c.9 0 1.4-.6 1.4-1.2 0-.9-.7-1.2"
              + "-.7-1.8 0-.5.4-.9 1-.9h1.2a2.9 2.9 0 0 0 2.7-3.1C13.6 4.5"
              + " 11.1 2.4 8 2.4z",
              "M5.4 7.2h.01", "M7.4 5.1h.01", "M10.2 5.6h.01"],
    map: ["M2.5 4.2 6 2.7l4 1.6 3.5-1.5v9.5L10 13.8l-4-1.6-3.5 1.5z",
          "M6 2.7v9.5", "M10 4.3v9.5"]
  };

  function drawn(paths, cls) {
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 16 16");
    if (cls) svg.setAttribute("class", cls);
    (paths || []).forEach(function (d) {
      var shape = document.createElementNS("http://www.w3.org/2000/svg",
                                           "path");
      shape.setAttribute("d", d);
      shape.setAttribute("stroke-linejoin", "round");
      shape.setAttribute("stroke-linecap", "round");
      svg.appendChild(shape);
    });
    return svg;
  }

  // The promise, with every token answered. Three sources in order: the
  // profile's own words for {element} and {second}, engine.js's hook
  // machinery for {moonphase} — which already declares "moon" as its fallback
  // — and then a last sweep, because a brace is never a thing to show a
  // reader on the page that asks them for money.
  function promise(ctx, card, data, tag) {
    var text = (tag && card.upgrade && card.upgrade[tag]) || card.promise || "";
    text = fill(text, data.words || {});
    if (typeof ctx.fillHook === "function") text = ctx.fillHook(text);
    return text
      .replace(/\{moonphase\}/g, "moon")
      .replace(/\{\w+\}/g, "")
      .replace(/\s{2,}/g, " ")
      .trim();
  }

  function questionCard(ctx, card, data, tag, first) {
    var item = elm("li", "zr-card" + (first ? " is-lead" : ""));
    var icon = elm("span", "zr-card-icon");
    icon.setAttribute("aria-hidden", "true");
    icon.appendChild(drawn(ICONS[card.icon] || ICONS.map));
    item.appendChild(icon);

    var line = elm("p", "zr-card-line");
    line.appendChild(elm("strong", "zr-card-key", (card.key || "") + ":"));
    line.appendChild(document.createTextNode(
      " " + promise(ctx, card, data, tag)));
    item.appendChild(line);

    var lock = elm("span", "zr-card-lock");
    lock.setAttribute("aria-hidden", "true");
    lock.appendChild(drawn([LOCK_PATH]));
    item.appendChild(lock);
    return item;
  }

  function questions(ctx, data) {
    var table = profileBlock(ctx) || {};
    var want = emphasised(purposeRule(ctx));
    var tag = purposeTagOf(ctx);
    var list = elm("ul", "zr-cards");
    // Same reorder as the constellation had: the chapter they said they came
    // for is the first thing they meet, and it is the one card wearing the
    // stronger border. Only the first match moves.
    firstly((table.cards || []).slice(), want).forEach(function (card) {
      list.appendChild(questionCard(ctx, card, data, tag,
                                    !!want && card.id === want));
    });
    return list;
  }

  function bridge(ctx, data) {
    var table = profileBlock(ctx) || {};
    var line = fill(table.bridge || "", data.words || {});
    return line ? elm("p", "zr-bridge", line) : null;
  }

  // Which keyword stands over a section, for the delivered page.
  function keywordOf(ctx, section_id) {
    var cards = (profileBlock(ctx) || {}).cards || [];
    for (var i = 0; i < cards.length; i++) {
      if (cards[i].id === section_id) return cards[i].key || "";
    }
    return "";
  }

  // --- e) the offer ----------------------------------------------------------

  // engine.js has already built and wired all of this. What happens here is
  // placement: the consent box, the button, its error line and the legal
  // links are moved into this card, which is why the withdrawal waiver still
  // gates the same button it always did and no payment code lives in here.
  function offer(ctx, copy, data) {
    var card = elm("section", "zr-offer");
    var nodes = ctx.nodes;

    // The one new line on this card: what the six chapters add up to, named
    // as the thing the reader has just been told they are. Everything under
    // it — the anchor, the sub, the wallet, the button, the trust row, the
    // consent — is the stack it always was.
    if (data) {
      var head = ctx.withPrice(
        fill((profileBlock(ctx) || {}).offer_head || "", data.words || {}));
      if (head) card.appendChild(elm("p", "zr-offer-head", head));
    }

    // The price, and the order of the argument around it.
    //
    // It used to open on the comparison — "A $3 profile instead of a $75
    // session" — which makes the $75 the first number on the card and the
    // one the eye stops at. The reader's own price is the thing they are
    // deciding about, so it is the loudest text here by a distance; the
    // anchor is one muted line above it, doing the work of a footnote.
    var anchorText = ctx.withPrice(ctx.commerce.price_anchor
                                   || ctx.commerce.anchor_head
                                   || ctx.cfg.checkout.anchor_head || "");
    var accent = ctx.commerce.price_anchor_accent
      || ctx.commerce.anchor_head_accent || "";
    var anchor = elm("p", "zr-anchor");
    if (accent && anchorText.indexOf(accent) !== -1) {
      var cut = anchorText.split(accent);
      anchor.appendChild(document.createTextNode(cut[0]));
      anchor.appendChild(elm("span", "zr-gold", accent));
      anchor.appendChild(document.createTextNode(cut.slice(1).join(accent)));
    } else {
      anchor.textContent = anchorText;
    }
    card.appendChild(anchor);

    var price = elm("p", "zr-price");
    price.appendChild(elm("span", "zr-price-now", ctx.price));
    var note = ctx.commerce.price_note || "";
    if (note) price.appendChild(elm("span", "zr-price-note", note));
    card.appendChild(price);

    // The two questions a reader asks a $3 button, answered where they are
    // asked rather than in a run-on line at the bottom of the card.
    var badges = ctx.commerce.badges || [];
    if (badges.length) {
      var row = elm("ul", "zr-badges");
      badges.forEach(function (text) {
        row.appendChild(elm("li", "zr-badge", text));
      });
      card.appendChild(row);
    }
    // The one line under the anchor, in the reader's own terms when the run
    // said what they came for. Everything else on this card — the price, the
    // button, the trust row, the consent — is untouched by any of this.
    var rule = purposeRule(ctx);
    card.appendChild(elm("p", "zr-offer-sub",
                         (rule && rule.offer_sub) || copy.offer_sub || ""));

    // Live nodes, not copies of them. The consent box is placed only where a
    // funnel asks for one: `withdrawal_consent: false` takes it off the page
    // for everybody, which is a different thing from the country list
    // `consent_skip_countries` drives and deliberately not that.
    //
    // Taken off, it still has to be satisfied — it is what enables the pay
    // button — so it is ticked here rather than left to whatever
    // `consent_prechecked` happens to say. A hidden control that disables the
    // only button on the page is a page that looks broken.
    var wantsConsent = ctx.cfg.checkout.withdrawal_consent !== false;
    if (!wantsConsent && nodes.consent) {
      var box = nodes.consent.querySelector("input[type=checkbox]");
      if (box && !box.checked) {
        box.checked = true;
        box.dispatchEvent(new Event("change", { bubbles: true }));
      }
      nodes.consent.hidden = true;
    }
    // The wallet above the button it replaces, so the order a reader takes
    // the block in — what it costs, how to pay, what it is not — is the same
    // whether the fast path appeared or not.
    [wantsConsent ? nodes.consent : null, nodes.walletSummary, nodes.wallet,
     nodes.payButton, nodes.payError]
      .forEach(function (n) { if (n) card.appendChild(n); });

    var trust = (ctx.commerce.trust || ctx.cfg.checkout.trust || []);
    if (trust.length) {
      card.appendChild(elm("p", "zr-trust", trust.join(" · ")));
    }
    if (nodes.legal) card.appendChild(nodes.legal);

    // The rows this layout does not use. Hidden rather than removed: they are
    // the same elements the paid view and the two-screen flow still want.
    [nodes.manifest, nodes.anchor, nodes.price, nodes.trust]
      .forEach(function (n) { if (n) n.hidden = true; });

    // This card is the offer now. engine.js fires `paywall_view` and Meta's
    // InitiateCheckout when the offer reaches the reader, and it was watching
    // the container above — which this page hides the moment the rows are out
    // of it, so the event never fired for anybody. Naming the card is the
    // whole fix: what the event means, when it fires and what it carries all
    // stay engine.js's business.
    //
    // Guarded because this file and engine.js sit behind a CDN and can be a
    // version apart: an engine without the hook draws the same page and only
    // loses the event it was already losing.
    if (typeof ctx.watchOffer === "function") ctx.watchOffer(card);
    return card;
  }

  // --- render ----------------------------------------------------------------

  function render(root, ctx) {
    var copy = (ctx.cfg && ctx.cfg.result_copy) || {};
    var elements = ctx.tally(ELEMENTS);
    // The element the hero names is the archetype's own, not the highest
    // scorer. They are usually the same and they do not have to be: an
    // archetype is won on three tags, so a Deep Water reader can out-score
    // air and still be Deep Water. "Pisces × Deep Water" over "53% Air" reads
    // as a bug in a card whose whole subject is the archetype. The balance
    // chart below still shows all four honestly, which is where a reader who
    // wants the full picture goes.
    var own = elements.filter(function (row) {
      return ctx.style.tags.indexOf(row.tag) !== -1;
    });
    var top = own[0] || lead(elements, ctx.style.tags)
      || { tag: ELEMENTS[0], score: 0 };

    var data = profileOf(ctx, elements, top);

    root.innerHTML = "";
    root.appendChild(kicker(copy));
    // The rich card, or the one this page drew before there was a table to
    // draw it from. Below the hero the two pages differ entirely, which is
    // why the branch is the whole body rather than one node.
    root.appendChild(data
      ? richHero(glyph(ctx.picks.sign), data)
      : hero(ctx, copy, elements, top));
    var strip = taps(ctx, copy);
    if (strip) root.appendChild(strip);
    if (data) {
      var free = freeStrength(ctx, copy);
      if (free) root.appendChild(free);
      var line = bridge(ctx, data);
      if (line) root.appendChild(line);
      root.appendChild(questions(ctx, data));
    } else {
      root.appendChild(path(ctx, copy, elements));
    }
    root.appendChild(offer(ctx, copy, data));

    // The container engine.js moved the offer rows into is empty now and its
    // own border would draw a line under nothing.
    if (ctx.nodes.commerce) ctx.nodes.commerce.hidden = true;
    root.hidden = false;
  }

  // --- the delivered report --------------------------------------------------
  //
  // The same page after the money. The reader paid on a dark celestial page
  // and the thing they bought has to open as the same document — before this
  // it opened as the kitchen layout, whose kicker literally says "YOUR PERFECT
  // STYLE IS".
  //
  // Structurally it is the pre-purchase page with the locks off: the same
  // kicker, the same hero, the same path, and every node a gold star with its
  // section's real content inside it. What is new here is the content — six
  // shapes that only exist once somebody has bought them.

  function swatches(data) {
    var wrap = elm("div", "zr-swatches");
    (data.colors || []).forEach(function (colour) {
      var row = elm("div", "zr-swatch");
      var dot = elm("span", "zr-swatch-dot");
      dot.style.background = colour.hex || "#000";
      row.appendChild(dot);
      var text = elm("div", "zr-swatch-text");
      var head = elm("p", "zr-swatch-head");
      head.appendChild(elm("span", "zr-swatch-name", colour.name || ""));
      head.appendChild(elm("span", "zr-swatch-hex", colour.hex || ""));
      text.appendChild(head);
      // Role and when, on one line, the way the PDF sets them. `finish` is
      // this funnel's "when to reach for it" — the free page never showed it
      // and dropping it here would lose a line they paid for.
      var when = [colour.role, colour.finish].filter(Boolean).join(" \u00B7 ");
      if (when) text.appendChild(elm("p", "zr-swatch-role", when));
      if (colour.where) {
        text.appendChild(elm("p", "zr-swatch-where", colour.where));
      }
      row.appendChild(text);
      wrap.appendChild(row);
    });
    var frag = document.createDocumentFragment();
    if (data.intro) frag.appendChild(elm("p", "zr-body", data.intro));
    frag.appendChild(wrap);
    if (data.closing_rule) {
      frag.appendChild(elm("p", "zr-note", data.closing_rule));
    }
    return frag;
  }

  function strengths(data) {
    var list = elm("ol", "zr-list");
    (data.items || []).forEach(function (item, i) {
      var row = elm("li", "zr-item");
      row.appendChild(elm("span", "zr-item-num", String(i + 1)));
      var body = elm("div", "zr-item-body");
      body.appendChild(elm("h3", "zr-item-title", item.title || ""));
      if (item.body) body.appendChild(elm("p", "zr-body", item.body));
      if (item.fix) body.appendChild(elm("p", "zr-fix", "→ " + item.fix));
      row.appendChild(body);
      list.appendChild(row);
    });
    return list;
  }

  function compatibility(data) {
    var frag = document.createDocumentFragment();
    if (data.intro) frag.appendChild(elm("p", "zr-body", data.intro));
    var list = elm("ul", "zr-verdicts");
    (data.pairs || []).forEach(function (pair) {
      var row = elm("li", "zr-verdict");
      var head = elm("p", "zr-verdict-head");
      head.appendChild(elm("span", "zr-combo", pair.combo || ""));
      var tag = elm("span", "zr-tag is-" + (pair.verdict || "works"),
                    (pair.verdict || "").toUpperCase());
      head.appendChild(tag);
      row.appendChild(head);
      if (pair.why) row.appendChild(elm("p", "zr-body", pair.why));
      list.appendChild(row);
    });
    frag.appendChild(list);
    if (data.rule) frag.appendChild(elm("p", "zr-note", data.rule));
    return frag;
  }

  function blueprint(data) {
    var frag = document.createDocumentFragment();
    (data.narrative || []).forEach(function (para) {
      frag.appendChild(elm("p", "zr-body", para));
    });
    var list = elm("ul", "zr-implications");
    (data.implications || []).forEach(function (line) {
      list.appendChild(elm("li", null, line));
    });
    if (list.childNodes.length) frag.appendChild(list);
    return frag;
  }

  function career(data) {
    var frag = document.createDocumentFragment();
    var head = elm("div", "zr-splurge");
    head.appendChild(elm("p", "zr-splurge-head",
                         (data.splurge && data.splurge.item) || ""));
    if (data.splurge && data.splurge.why) {
      head.appendChild(elm("p", "zr-body", data.splurge.why));
    }
    frag.appendChild(head);
    var list = elm("ul", "zr-saves");
    (data.saves || []).forEach(function (row) {
      var item = elm("li", "zr-save");
      item.appendChild(elm("span", "zr-save-item", row.item || ""));
      if (row.why) item.appendChild(document.createTextNode(" " + row.why));
      list.appendChild(item);
    });
    if (list.childNodes.length) {
      frag.appendChild(elm("p", "zr-sub-head", "Where to stop spending it"));
      frag.appendChild(list);
    }
    if (data.split_note) {
      frag.appendChild(elm("p", "zr-note", data.split_note));
    }
    return frag;
  }

  function months(data) {
    var list = elm("ol", "zr-months");
    (data.items || []).forEach(function (item) {
      var row = elm("li", "zr-month");
      row.appendChild(elm("span", "zr-month-name", item.name || ""));
      row.appendChild(elm("span", "zr-month-note", item.priority_note || ""));
      list.appendChild(row);
    });
    var frag = document.createDocumentFragment();
    frag.appendChild(list);
    // `skip` is empty on this funnel by design — the quiet month is marked in
    // its own note rather than struck out — but a report written before that
    // was true can still carry one, and dropping it would lose a month.
    (data.skip || []).forEach(function (row) {
      var quiet = elm("p", "zr-note");
      quiet.appendChild(elm("span", "zr-month-name", row.name || ""));
      quiet.appendChild(document.createTextNode(" " + (row.why || "")));
      frag.appendChild(quiet);
    });
    return frag;
  }

  // Keyed on the id the section arrived under, which is the same id engine.js
  // and the PDF dispatch on. A section this does not know renders as its own
  // prose rather than not at all.
  var DELIVERED_BODY = {
    palette: swatches,
    mistakes: strengths,
    materials: compatibility,
    dna: blueprint,
    splurge: career,
    shopping: months
  };

  // A photograph out of this reader's own run, or nothing. Never a stock
  // frame: the page above this one says the reading was read off their taps,
  // and an image nobody chose is that sentence being untrue. The file is one
  // the browser already fetched during the quiz, so it costs a cache hit.
  function tapped(ctx, image_id) {
    var pick = image_id && ctx.images[image_id];
    if (!pick || !pick.img) return null;
    var frame = elm("figure", "zr-shot");
    var img = document.createElement("img");
    img.src = pick.img;
    img.alt = "";
    img.loading = "lazy";
    img.decoding = "async";
    frame.appendChild(img);
    if (pick.label) frame.appendChild(elm("figcaption", "zr-shot-cap",
                                          pick.label));
    return frame;
  }

  function sectionImage(ctx, section_id) {
    var map = (ctx.visuals && ctx.visuals.sections) || {};
    return tapped(ctx, map[section_id]);
  }

  function deliveredNode(ctx, section) {
    var item = node("open", section.title || "");
    var body = item.querySelector(".zr-node-body");
    // The keyword off the card that sold this chapter, over the title it was
    // sold under. "Love:" above "Love & Compatibility" is the promise and the
    // thing delivered, in that order, on one screen.
    var key = keywordOf(ctx, section.id);
    if (key) {
      body.insertBefore(elm("p", "zr-node-key", key + ":"), body.firstChild);
    }
    var shot = sectionImage(ctx, section.id);
    if (shot) body.appendChild(shot);
    var build = section.data && DELIVERED_BODY[section.id];
    if (build) {
      try {
        body.appendChild(build(section.data));
        return item;
      } catch (e) { /* fall through to prose */ }
    }
    if (section.body) body.appendChild(elm("p", "zr-body", section.body));
    return item;
  }

  // The hero, without a run behind it. The percentage and the balance chart
  // came from tallies this tab never had, so the delivered card carries the
  // identity and drops the arithmetic rather than inventing it.
  function deliveredHero(ctx, copy) {
    var card = elm("section", "zr-hero");
    var hero = (ctx.visuals && ctx.visuals.hero) || {};
    var pick = ctx.images[hero.glyph || signImageId(ctx)];
    // The same card as before the money, off the block reports.py measured
    // while the run still existed and stored on the report. Without one —
    // every report written before this shipped — the old delivered card is
    // drawn instead, which is the page those readers were sent to and still
    // have bookmarked.
    var data = (ctx.visuals && ctx.visuals.profile) || null;
    if (data && data.subtype) {
      var rich = richHero(glyph(pick), data);
      // The horizon they chose, which the paid card has always carried and
      // the free one never did. Appended here rather than inside `richHero`
      // for exactly that reason: there is no band before the money.
      var horizon = tapped(ctx, hero.band);
      if (horizon) {
        horizon.classList.add("zr-band");
        rich.appendChild(horizon);
      }
      return rich;
    }
    card.appendChild(glyph(pick));
    card.appendChild(elm("h1", "zr-sign", ctx.sign || ctx.style.name));
    if (ctx.sign) card.appendChild(elm("p", "zr-cross", "× " + ctx.style.name));
    if (ctx.style.blurb) {
      card.appendChild(elm("p", "zr-sub", ctx.style.blurb));
    }
    card.appendChild(deliveredElements(ctx));
    var band = tapped(ctx, hero.band);
    if (band) {
      band.classList.add("zr-band");
      card.appendChild(band);
    }
    return card;
  }

  // The element bar, after the money. The quiz tally is gone by now — someone
  // opening this from a link in their mail has no run left to count — so the
  // bar names the archetype's own element out of its tags rather than
  // inventing a percentage nobody measured. All four are drawn; one is lit.
  function deliveredElements(ctx) {
    var own = (ctx.style.tags || []).filter(function (tag) {
      return ELEMENTS.indexOf(tag) !== -1;
    })[0] || "";
    var row = elm("div", "zr-elements");
    ELEMENTS.forEach(function (tag) {
      var cell = elm("span", "zr-el" + (tag === own ? " is-own" : ""));
      var dot = elm("i", "zr-el-dot");
      dot.style.background = ELEMENT_COLOR[tag] || "#A8AECC";
      cell.appendChild(dot);
      cell.appendChild(elm("span", "zr-el-name", ELEMENT_NAME[tag] || tag));
      row.appendChild(cell);
    });
    return row;
  }

  // The sign's own frame, found by name. The stored report keeps the sign as
  // a label rather than an id, because that is what the mail and the PDF need.
  function signImageId(ctx) {
    var want = (ctx.sign || "").toLowerCase();
    if (!want) return "";
    var ids = Object.keys(ctx.images);
    for (var i = 0; i < ids.length; i++) {
      if (ids[i] === "sign_" + want) return ids[i];
    }
    return "";
  }

  // --- the delivery note -----------------------------------------------------
  //
  // The first thing a buyer sees on this page, above everything, on both ways
  // in: seconds after paying, and a week later from the link in the mail. The
  // past tense is what makes one line true on both — "was sent" is a fact
  // about something that has already happened, where "is on its way" is a
  // promise that expires.
  //
  // The address comes off the authenticated report payload and is never
  // touched again: it is not tracked, not stored by this page, and not put
  // anywhere a second request could read it. Without one the line still reads
  // as a sentence — a bar with a hole in it would be worse than no bar.

  var CHECK_PATH = "M3.5 8.6l3.1 3.1 5.9-6.4";

  function deliveryNote(ctx, copy) {
    if (!ctx.delivered) return null;
    var email = (((ctx.visuals || {}).delivery || {}).email || "").trim();
    var line = copy.delivery_line || "Your PDF was sent to {email}";
    var bare = copy.delivery_line_bare || "Your PDF was sent to your email";

    var bar = elm("p", "zr-sent");
    var mark = elm("span", "zr-sent-check");
    mark.setAttribute("aria-hidden", "true");
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 16 16");
    var tick = document.createElementNS("http://www.w3.org/2000/svg", "path");
    tick.setAttribute("d", CHECK_PATH);
    tick.setAttribute("stroke-linecap", "round");
    tick.setAttribute("stroke-linejoin", "round");
    svg.appendChild(tick);
    mark.appendChild(svg);
    bar.appendChild(mark);

    var text = elm("span", "zr-sent-text");
    if (!email || line.indexOf("{email}") === -1) {
      text.textContent = bare;
    } else {
      var cut = line.split("{email}");
      text.appendChild(document.createTextNode(cut[0]));
      text.appendChild(elm("span", "zr-sent-mail", email));
      text.appendChild(document.createTextNode(cut.slice(1).join("{email}")));
    }
    bar.appendChild(text);
    return bar;
  }

  function delivered(root, ctx) {
    var copy = (ctx.cfg && ctx.cfg.result_copy) || {};
    root.innerHTML = "";
    root.classList.add("is-delivered");
    var note = deliveryNote(ctx, copy);
    if (note) root.appendChild(note);
    root.appendChild(kicker(copy));
    root.appendChild(deliveredHero(ctx, copy));
    var strip = deliveredTaps(ctx, copy);
    if (strip) root.appendChild(strip);

    // Same reorder after the money as before it: the section they came for is
    // the first one they meet. `ctx.purpose` is the tag off the stored report
    // — this tab may never have run the quiz — and a report without one, which
    // is every zodiac v1 and kitchen report, renders in report order.
    var list = elm("ol", "zr-path");
    firstly(ctx.sections, emphasised(purposeRule(ctx)))
      .forEach(function (section) {
        list.appendChild(deliveredNode(ctx, section));
      });
    root.appendChild(list);

    // No offer here, obviously. What replaces it is the one line the reader
    // still needs: where else this document is.
    if (ctx.complete && copy.delivered_note) {
      root.appendChild(elm("p", "zr-footnote", copy.delivered_note));
    }
    root.hidden = false;
  }

  window.MazzinResult = { render: render, delivered: delivered };
}());
