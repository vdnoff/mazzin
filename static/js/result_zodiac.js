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

  function yearLabels(from, months) {
    var names = (months && months.length === 12) ? months : MONTH_ABBR;
    var day = from || new Date();
    var year = day.getFullYear();
    var month = day.getMonth();
    var out = [];
    for (var i = 0; i < 12; i++) {
      out.push(names[month] + " " + year);
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
    return (stored && stored.length === 12)
      ? stored : yearLabels(null, label(ctx, "months"));
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

  // The words this module prints that are not the model's and not the
  // config's copy: element names, energy names, month abbreviations, the
  // verdict badges and two headings. They were written in English because
  // there was one language; `result_copy.labels` is where a funnel that sells
  // in another one puts its own.
  //
  // Absent — which is every funnel but /zodiac-ro — every one of these falls
  // through to the string this file has always written, byte for byte.
  //
  // The server prints the same words on the PDF and in the mail out of
  // reports.py's RENDER_WORDS, and the two have to agree: a reader who saw
  // MERGE on the page and WORKS in the document has been shown two documents.
  // tests/test_zodiacro_check.py holds them to each other.
  var LABELS_FALLBACK = {
    elements: ELEMENT_NAME,
    energies: ENERGY_NAME,
    led_template: "{energy}-led",
    months: MONTH_ABBR,
    verdicts: null,               // null means "uppercase the tag", as before
    // Said as well as struck: the line through a number is a visual
    // convention, and a screen reader reads this instead.
    price_regular_aria: "Regular price {price}",
    saves_head: "Where to stop spending it",
    scale_aria: "{left} to {right} — {at} out of 100 toward {right}"
  };

  function labels(ctx) {
    var own = ((ctx && ctx.cfg && ctx.cfg.result_copy) || {}).labels;
    return (own && typeof own === "object") ? own : {};
  }

  function label(ctx, key) {
    var own = labels(ctx)[key];
    return (own === undefined || own === null) ? LABELS_FALLBACK[key] : own;
  }

  // One of a keyed set — an element, an energy, a verdict — in the funnel's
  // own words or in this file's. A key the config forgot falls back on its
  // own rather than taking the whole set down with it.
  function named(ctx, key, tag, fallback) {
    var set = labels(ctx)[key];
    if (set && typeof set === "object" && set[tag]) return set[tag];
    return fallback;
  }

  function elementName(ctx, tag) {
    return named(ctx, "elements", tag, ELEMENT_NAME[tag] || tag);
  }

  function energyName(ctx, tag) {
    return named(ctx, "energies", tag, ENERGY_NAME[tag] || tag);
  }

  function fillLabel(text, values) {
    return String(text || "").replace(/\{(\w+)\}/g, function (whole, k) {
      return Object.prototype.hasOwnProperty.call(values, k)
        ? String(values[k]) : whole;
    });
  }

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
  function splitOf(ctx, elements) {
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
        name: elementName(ctx, row.tag),
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
    var split = splitOf(ctx, elements);
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
      element: elementName(ctx, primary),
      second: elementName(ctx, second),
      energy: energyName(ctx, energy),
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

  function kicker(copy, lean) {
    var line = elm("p", "zr-kicker", copy.kicker || "YOUR COSMIC PROFILE");
    // The minimal arm frames it. Real nodes rather than pseudo-elements so
    // the ornament is something a test can find and a translation can drop,
    // and appended only for that arm — the control's kicker is one text node
    // and stays one.
    if (lean) {
      line.className = "zr-kicker is-framed";
      line.insertBefore(star(), line.firstChild);
      line.appendChild(star());
    }
    return line;
  }

  // The four-pointed mark this funnel already draws on its open nodes.
  function star() {
    var mark = elm("span", "zr-star", "\u2726");
    mark.setAttribute("aria-hidden", "true");
    return mark;
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
    bar.setAttribute("aria-label", pct + "% " + elementName(ctx, top.tag));
    var fill = elm("span", "zr-bar-fill");
    fill.style.width = pct + "%";
    fill.style.background = ELEMENT_COLOR[top.tag] || "#E8C878";
    bar.appendChild(fill);
    card.appendChild(bar);

    var led = lead(ctx.tally(ENERGY), ctx.style.tags);
    var parts = [pct + "% " + elementName(ctx, top.tag)];
    if (led && led.score > 0) {
      parts.push(fillLabel(label(ctx, "led_template"),
                           { energy: energyName(ctx, led.tag) }));
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

  function scaleRow(ctx, row, lean) {
    var wrap = elm("div", "zr-scale");
    // Which pole this row leans to. `at` counts toward the right one, so
    // under half is the left and over half the right; dead level is neither,
    // and neither is lit rather than one of them being lit by rounding.
    var active = row.at < 50 ? "left" : (row.at > 50 ? "right" : "");
    var left = elm("span", "zr-scale-pole"
                   + (lean && active === "left" ? " is-active" : ""), row.left);
    wrap.appendChild(left);
    var track = elm("span", "zr-scale-track");
    track.setAttribute("role", "img");
    track.setAttribute("aria-label", fillLabel(label(ctx, "scale_aria"), {
      left: row.left, right: row.right, at: row.at
    }));
    // The run from the lit pole to the dot, so the bar reads as a distance
    // travelled from a side rather than as a slider with a value on it.
    if (lean && active) {
      var run = elm("i", "zr-scale-run");
      if (active === "left") {
        run.style.left = "0";
        run.style.width = row.at + "%";
      } else {
        run.style.left = row.at + "%";
        run.style.width = (100 - row.at) + "%";
      }
      track.appendChild(run);
    }
    var dot = elm("i", "zr-scale-dot");
    dot.style.left = row.at + "%";
    track.appendChild(dot);
    wrap.appendChild(track);
    wrap.appendChild(elm("span", "zr-scale-pole is-right"
                         + (lean && active === "right" ? " is-active" : ""),
                         row.right));
    return wrap;
  }

  // A figure fits inside its own segment at about this share of the bar. Below
  // it "37%" is wider than the block it would sit in, so the number goes
  // unwritten rather than spilling over the segment beside it — the name
  // under the bar still says which element the block is.
  var SPLIT_LABEL_MIN_PCT = 12;

  function splitBar(data, lean) {
    var wrap = elm("div", "zr-split");
    var bar = elm("div", "zr-split-bar");
    bar.setAttribute("role", "img");
    bar.setAttribute("aria-label", data.split_caption || "");
    (data.split || []).forEach(function (cell) {
      var seg = elm("span", "zr-split-seg");
      seg.style.width = cell.pct + "%";
      seg.style.background = cell.color || "#E8C878";
      if (lean && cell.pct >= SPLIT_LABEL_MIN_PCT) {
        seg.appendChild(elm("b", "zr-split-pct", cell.pct + "%"));
      }
      bar.appendChild(seg);
    });
    wrap.appendChild(bar);
    if (lean) {
      // The names under the bar rather than in a sentence beside it, each one
      // the width of the block it names, so the word and the colour are the
      // same measurement twice.
      var names = elm("div", "zr-split-names");
      (data.split || []).forEach(function (cell) {
        var name = elm("span", "zr-split-name", cell.name || cell.tag);
        name.style.width = cell.pct + "%";
        name.style.color = cell.color || "#E8C878";
        names.appendChild(name);
      });
      wrap.appendChild(names);
      return wrap;
    }
    if (data.split_caption) {
      wrap.appendChild(elm("p", "zr-split-caption", data.split_caption));
    }
    return wrap;
  }

  // The formula as capsules, for the arm that draws them. Built from the words
  // the formula line is built from rather than by cutting that line up: it
  // carries "Fire-led, Earth undercurrent" as one segment and the mockup asks
  // for those as two chips, so a split on the separator gives three where
  // four are wanted. A chip whose words are missing — a run that never
  // reached the sign step — is dropped rather than drawn empty.
  function chipRow(ctx, data) {
    var want = (profileBlock(ctx) || {}).chips || [];
    if (!want.length) return null;
    var row = elm("ul", "zr-chips");
    want.forEach(function (shape) {
      var text = fill(shape, data.words || {}).replace(/\{\w+\}/g, "").trim();
      if (text) row.appendChild(elm("li", "zr-chip", text));
    });
    return row.childNodes.length ? row : null;
  }

  function richHero(ctx, badge, data, opts) {
    // The minimal arm pulls the rarity out of this card and gives it its own
    // weight further down the page, and draws the rest of it as the mockup
    // asks. Without the flag nothing here changes, which is the whole
    // contract: the control arm is this page as it was, node for node.
    var lean = !!(opts && opts.lean);
    var card = elm("section", "zr-hero is-rich" + (lean ? " is-lux" : ""));
    // Four marks, one to a corner. Decoration, and named as such: the card
    // is a keepsake on this arm and the frame is the whole of that idea.
    if (lean) {
      ["tl", "tr", "bl", "br"].forEach(function (corner) {
        var mark = star();
        mark.className = "zr-corner is-" + corner;
        card.appendChild(mark);
      });
    }
    var head = elm("div", "zr-hero-top");
    head.appendChild(badge);
    var id = elm("div", "zr-hero-id");
    id.appendChild(elm("h1", "zr-subtype", data.subtype));
    var chips = lean ? chipRow(ctx, data) : null;
    if (chips) {
      id.appendChild(chips);
    } else if (data.formula) {
      id.appendChild(elm("p", "zr-formula", data.formula));
    }
    head.appendChild(id);
    card.appendChild(head);

    if (!lean && data.rarity_line) {
      card.appendChild(elm("p", "zr-ribbon", data.rarity_line));
    }
    if ((data.scales || []).length) {
      var scales = elm("div", "zr-scales");
      data.scales.forEach(function (row) {
        scales.appendChild(scaleRow(ctx, row, lean));
      });
      card.appendChild(scales);
    }
    if ((data.split || []).length) card.appendChild(splitBar(data, lean));
    if (data.cross_line) {
      // The rule goes on the lux card: the reading is the loudest sentence
      // on it now, and a line above it makes it a footnote to the chart.
      if (!lean) card.appendChild(elm("hr", "zr-hairline"));
      var reading = elm("p", "zr-crossline" + (lean ? " is-bright" : ""));
      if (lean) reading.appendChild(star());
      reading.appendChild(document.createTextNode(data.cross_line));
      card.appendChild(reading);
    }
    return card;
  }

  // The rarity, at the size the claim deserves, for the arm that asks for it.
  // Same idea as the persona page's: the number is the argument, so it is set
  // apart from the sentence it sits in rather than left inside a pill.
  // How many readings do NOT land this blend, out of the same 1-in-N the
  // ribbon is built from. One number, one source: a blend that is 1 in 40 is
  // 98%, one that is 1 in 10 is 90%, and there is nothing here to keep in
  // step with anything else.
  // Two centred lines, broken at the em-dash rather than at whatever width
  // the box happens to be. The break is where the sentence turns, so it is
  // the same break in any column — and a translation that carries no dash
  // gets one line rather than a guess at where to cut it.
  function rarityNote(text) {
    var note = elm("p", "zr-rarity-note");
    var cut = String(text).split("\u2014");
    if (cut.length !== 2) {
      note.textContent = text;
      return note;
    }
    note.appendChild(elm("span", "zr-rarity-note-line",
                         cut[0].trim() + " \u2014"));
    note.appendChild(elm("span", "zr-rarity-note-line", cut[1].trim()));
    return note;
  }

  function differentPct(n) {
    return (typeof n === "number" && n >= 2)
      ? Math.round((1 - 1 / n) * 100) : 0;
  }

  function rarityBadge(data, table) {
    if (!data || !data.rarity_line) return null;
    // The arm that gives the rarity its own screen gives it a card: the frame
    // of the claim, the number at the size the claim deserves, and one line
    // about what it is worth. A funnel that declares no such copy — every one
    // but this — falls through to the single line below, unchanged.
    var own = (table || {}).rarity_card;
    var pct = differentPct(data.rarity);
    if (own && own.lead && pct) {
      var badge = elm("div", "zr-rarity is-card");
      badge.appendChild(elm("p", "zr-rarity-lead", own.lead));
      badge.appendChild(elm("p", "zr-rarity-figure", pct + "%"));
      if (own.tail) badge.appendChild(elm("p", "zr-rarity-tail", own.tail));
      if (own.note) badge.appendChild(rarityNote(own.note));
      return badge;
    }
    var wrap = elm("div", "zr-rarity");
    var line = data.rarity_line;
    var found = /(\d+(?:\.\d+)?%)/.exec(line);
    if (found) {
      var cut = line.split(found[1]);
      wrap.appendChild(elm("span", "zr-rarity-lead", cut[0].trim()));
      wrap.appendChild(elm("strong", "zr-rarity-figure", found[1]));
      var tail = cut.slice(1).join(found[1]).trim();
      if (tail) wrap.appendChild(elm("span", "zr-rarity-tail", tail));
    } else {
      wrap.appendChild(elm("span", "zr-rarity-lead", line));
    }
    return wrap;
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
      col.appendChild(elm("span", "zr-bal-name", elementName(ctx, row.tag)));
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
          "M6 2.7v9.5", "M10 4.3v9.5"],
    // The offer's checklist. A tick rather than a padlock: this list is what
    // is in the report, and a row of locks over the price is the page arguing
    // with the button under it.
    check: ["M3.2 8.4 6.4 11.6 12.8 4.8"],
    // The one place a padlock belongs: over the chapter the boxes arm shows
    // and does not open.
    lock: ["M4.6 7.2V5.4a3.4 3.4 0 0 1 6.8 0v1.8",
           "M3.4 7.2h9.2v6.4H3.4z"]
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

  // What is in the report, five short lines, above the price.
  //
  // Every line is a clause of a promise the funnel already makes: the keyword
  // is the question card's own `key` and the text is the config's short form
  // of that card's `promise`, so this list cannot promise a chapter something
  // the chapter does not say it contains. Reordered by what they said they
  // came for, exactly as the question cards are — a career purpose reads
  // Money first — and only the first match moves.
  function checklist(ctx, data) {
    var table = profileBlock(ctx) || {};
    var rows = table.unlock || [];
    if (!rows.length) return null;
    var keys = {};
    (table.cards || []).forEach(function (card) {
      keys[card.id] = card.key || "";
    });
    var block = elm("div", "zr-unlock");
    if (table.unlock_head) {
      block.appendChild(elm("p", "zr-unlock-head", table.unlock_head));
    }
    var list = elm("ul", "zr-checklist");
    firstly(rows.slice(), emphasised(purposeRule(ctx))).forEach(
      function (row) {
        list.appendChild(checkRow(keys[row.id] || "",
                                  fill(row.line || "", data.words || {})));
      });
    var tail = table.unlock_tail;
    if (tail && tail.key) {
      list.appendChild(checkRow(tail.key,
                                fill(tail.line || "", data.words || {})));
    }
    block.appendChild(list);
    return block;
  }

  function checkRow(key, text) {
    var item = elm("li", "zr-check");
    var mark = elm("span", "zr-check-mark");
    mark.setAttribute("aria-hidden", "true");
    mark.appendChild(drawn(ICONS.check));
    item.appendChild(mark);
    // The keyword and the description in one paragraph beside the tick, so a
    // row that runs to two lines wraps under its own text rather than under
    // the icon.
    var line = elm("p", "zr-check-line");
    if (key) {
      line.appendChild(elm("strong", "zr-check-key", key));
      line.appendChild(document.createTextNode(" \u2014 " + text));
    } else {
      line.appendChild(document.createTextNode(text));
    }
    item.appendChild(line);
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

  // --- d4) the boxes arm -----------------------------------------------------
  //
  // The second way of laying this page out. Where `minimal` argues from the
  // reading itself — the card, the taps it was read from, how rare it is —
  // this one argues from the table of contents: one locked chapter shown at
  // full size and the other four as tiles, then the same money block.
  //
  // Every string here ships as English and is overridden per funnel from
  // `result_copy.boxes`, exactly as `result_copy.labels` overrides the words
  // the page prints itself. A funnel that declares no block renders this
  // English — and nothing in this file knows which funnel does either, which
  // is the property that lets the next one adopt the arm with a config edit.
  var BOXES_FALLBACK = {
    // Which step's frame the locked card shows. Named in copy rather than in
    // code because it is a claim about one funnel's walk, not about the
    // layout: the card is the chapter the reader is closest to wanting.
    hero_step: "bond",
    locked: "Locked",
    hero_kicker: "LOVE & COMPATIBILITY",
    // The two verdicts are filled from `labels.verdicts`, so the page and the
    // document call a pairing the same thing.
    hero_line: "{works} or {avoid} — for every sign, on the first page.",
    boxes: [
      { id: "palette", icon: "palette",
        title: "Your power palette", sub: "Colours and talismans" },
      { id: "mistakes", icon: "eye",
        title: "5 hidden strengths", sub: "And 2 blind spots" },
      { id: "dna", icon: "map",
        title: "Your cosmic blueprint", sub: "Career and money" },
      { id: "shopping", icon: "calendar",
        title: "The next 12 months", sub: "{range}" }
    ]
  };

  function boxesCopy(ctx) {
    var own = ((ctx.cfg && ctx.cfg.result_copy) || {}).boxes;
    return (own && typeof own === "object") ? own : {};
  }

  function boxesText(ctx, key) {
    var own = boxesCopy(ctx)[key];
    return (own === undefined || own === null) ? BOXES_FALLBACK[key] : own;
  }

  // The twelve the rest of this page counts in, as one span. `yearOf` is the
  // same function the year map reads, so the tile can never name a window the
  // report does not open on: both start at this month and run twelve.
  function monthRange(ctx) {
    var year = yearOf(ctx);
    if (!year || year.length !== 12) return "";
    return year[0] + " \u2013 " + year[11];
  }

  // A verdict in the funnel's own word, or the tag upper-cased — which is
  // what every funnel that declares no `verdicts` has always printed.
  function verdictWord(ctx, tag) {
    var set = label(ctx, "verdicts");
    return (set && set[tag]) ? set[tag] : tag.toUpperCase();
  }

  // The frame they actually tapped on the step this card is about, or that
  // step's first frame when there is no run to read — which is every page
  // reached by reloading the URL directly. No new bytes either way: both are
  // images this browser decoded during the quiz.
  function bondPick(ctx) {
    var want = boxesText(ctx, "hero_step");
    var pick = ctx.picks && ctx.picks[want];
    if (pick && pick.img) return pick;
    var steps = (ctx.cfg && ctx.cfg.swipe && ctx.cfg.swipe.steps) || [];
    for (var i = 0; i < steps.length; i++) {
      if (steps[i].id !== want) continue;
      var pairs = steps[i].pairs || [];
      var first = pairs[0] && pairs[0].images && pairs[0].images[0];
      if (first && first.img) return first;
    }
    return null;
  }

  // The one accented element on the page: a chapter shown rather than
  // described, with the lock over the corner of it.
  function lockedHero(ctx) {
    var card = elm("section", "zr-boxes-hero");
    var shot = elm("div", "zr-boxes-shot");
    var pick = bondPick(ctx);
    if (pick) {
      var img = document.createElement("img");
      img.src = pick.img;
      img.alt = "";
      img.decoding = "async";
      shot.appendChild(img);
    }
    var pill = elm("span", "zr-boxes-lock");
    pill.appendChild(drawn(ICONS.lock, "zr-boxes-lock-icon"));
    pill.appendChild(elm("span", "zr-boxes-lock-text",
                         boxesText(ctx, "locked")));
    shot.appendChild(pill);
    card.appendChild(shot);
    var text = elm("div", "zr-boxes-hero-text");
    text.appendChild(elm("p", "zr-boxes-kicker",
                         boxesText(ctx, "hero_kicker")));
    text.appendChild(elm("p", "zr-boxes-line",
                         fillLabel(boxesText(ctx, "hero_line"), {
                           works: verdictWord(ctx, "works"),
                           avoid: verdictWord(ctx, "avoid")
                         })));
    card.appendChild(text);
    return card;
  }

  function boxGrid(ctx) {
    var want = boxesText(ctx, "boxes") || [];
    var grid = elm("ul", "zr-boxes-grid");
    want.forEach(function (box) {
      if (!box || !box.title) return;
      var cell = elm("li", "zr-box");
      var icon = elm("span", "zr-box-icon");
      icon.setAttribute("aria-hidden", "true");
      icon.appendChild(drawn(ICONS[box.icon] || ICONS.check));
      cell.appendChild(icon);
      cell.appendChild(elm("p", "zr-box-title", box.title));
      var sub = fillLabel(box.sub || "", { range: monthRange(ctx) })
        .replace(/\{\w+\}/g, "").trim();
      if (sub) cell.appendChild(elm("p", "zr-box-sub", sub));
      grid.appendChild(cell);
    });
    return grid.childNodes.length ? grid : null;
  }

  // The one block this arm swaps in, between the rarity card and the offer.
  //
  // No headline and no "you are X" line: the hero four blocks up already
  // carries the subtype, the sign and the chips, and repeating them here was
  // the page saying the same thing twice before asking for money.
  function boxesPitch(ctx) {
    var frag = document.createDocumentFragment();
    frag.appendChild(lockedHero(ctx));
    var grid = boxGrid(ctx);
    if (grid) frag.appendChild(grid);
    return frag;
  }

  // --- e) the offer ----------------------------------------------------------

  // engine.js has already built and wired all of this. What happens here is
  // placement: the consent box, the button, its error line and the legal
  // links are moved into this card, which is why the withdrawal waiver still
  // gates the same button it always did and no payment code lives in here.
  function offer(ctx, copy, data, template) {
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

    // Between the headline and the anchor, on the arm that took the question
    // cards off the page above. Those cards were the answer to "what am I
    // buying"; without them the offer has to carry it, and it carries it here
    // rather than as six blocks the reader scrolls past to reach the price.
    if (data && template === "minimal") {
      var list = checklist(ctx, data);
      if (list) card.appendChild(list);
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

    // The price. `ctx.price` is already whatever the checkout is about to
    // charge — engine.js resolves the sale before it fills a single {price}
    // — so the hero number needs no arithmetic here. What a sale adds is the
    // comparison beside it: the regular price, struck, and one line naming
    // the offer.
    //
    // `ctx.sale` is null unless a sale is genuinely running, and it is null
    // for a block whose claimed regular price is not this funnel's own. So
    // there is no state in which this draws a struck-through figure that is
    // not the price this product sells at the rest of the year.
    var price = elm("p", "zr-price");
    price.appendChild(elm("span", "zr-price-now", ctx.price));
    if (ctx.sale && ctx.priceRegular) {
      var was = elm("span", "zr-price-was", ctx.priceRegular);
      // Said as well as struck: a line through a number is a visual
      // convention a screen reader does not read out.
      was.setAttribute("aria-label", fillLabel(
        label(ctx, "price_regular_aria"), { price: ctx.priceRegular }));
      price.appendChild(was);
    }
    var note = ctx.commerce.price_note || "";
    if (note) price.appendChild(elm("span", "zr-price-note", note));
    card.appendChild(price);
    if (ctx.sale && ctx.sale.label) {
      // The offer's name, and nothing else at all. No clock counting down, no
      // number of copies left, and no closing date either — a date on a card
      // is a promise about a config value, and an offer that gets extended
      // twice has spent that promise. The block still ends on its own clock;
      // the page simply does not make a date part of the pitch.
      card.appendChild(elm("p", "zr-sale", ctx.sale.label));
    }

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

  // --- paywall variants ------------------------------------------------------
  //
  // The same mechanism result_persona.js carries, character for character.
  // It is a copy rather than an import because engine.js loads exactly one
  // module per funnel — `loadAsset(cfg.result_module)` — so there is nowhere
  // a shared file could be required from without changing the shell every
  // funnel loads, and this funnel takes real money. tests/test_variants.py
  // holds the two copies byte-identical, which is the price of not touching
  // engine.js to save a duplication.
  //
  // Nothing here knows what funnel it is in. A variant is
  // `{ id, enabled, weight, ... }` and a variant may also carry `template`,
  // which is what this funnel's second arm uses: same offer, same copy, a
  // different way of laying the page out.

  // engine.js's own session key. Read, never written: the id already exists
  // by the time a result page renders, it is the id every event on this
  // session carries, and assignment has to agree with what the events say.
  var SESSION_KEY = "mazzin_sid";

  function variantWeight(variant) {
    var weight = typeof variant.weight === "number" ? variant.weight : 1;
    return weight > 0 ? weight : 0;
  }

  // Enabled, and worth assigning. A variant left in the config with
  // `enabled: false` is excluded here and therefore cannot be assigned, drawn
  // or reported; so is one weighted to zero, which is the same intent
  // written differently.
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
      // that state lands on the same variant rather than on a random one:
      // a coin flipped per page load would show a reader one frame on the
      // free page and the other on the delivered one.
      return "";
    }
  }

  // FNV-1a, 32-bit. Any stable hash would do; what matters is that it reads
  // the session id and nothing else. Assignment must never depend on the URL
  // or on a campaign parameter — a variant that rotates with `subid` cannot
  // be added or retired without touching the ad account's final URLs, and
  // the whole point of the config list is that it can.
  function hashOf(text) {
    var hash = 0x811c9dc5;
    for (var i = 0; i < text.length; i++) {
      hash ^= text.charCodeAt(i);
      hash = (hash + ((hash << 1) + (hash << 4) + (hash << 7)
                      + (hash << 8) + (hash << 24))) >>> 0;
    }
    return hash >>> 0;
  }

  // The same session gets the same variant every time this is called — on
  // reload, and on the delivered page — because the only input is an id that
  // does not change. Weights renormalise by construction: the point is taken
  // over the live total, so disabling a variant hands its share to the
  // others without anybody restating the remaining weights.
  function assignedVariant(cfg) {
    var pool = variantPool(cfg);
    if (!pool.length) return null;
    // One enabled variant is not a test, and must not be treated as one: it
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
  // shown. Everything downstream — paywall_view, pay_tap, and the purchase
  // the webhook writes — already carries `session_id`, and both tables index
  // it, so conversion splits by variant on a join rather than on a column
  // added to every event. That is what keeps this a config change and not a
  // schema change.
  //
  // It is not fired on the delivered page. That page is past the money, its
  // assignment is recomputed from the same session id for display only, and
  // a second row would double-count the arm.
  var variantReported = false;

  function reportVariant(ctx, variant) {
    if (!variant || variantReported) return;
    variantReported = true;
    try {
      // The name is written out rather than held in a constant: the
      // suite pairs tracking.py's allowlist against the literals the client
      // actually emits, and an event that only exists as an identifier reads
      // there as a dead name in the allowlist.
      ctx.track("paywall_variant", { variant: variant.id });
    } catch (e) { /* an arm is not worth losing the page to */ }
  }

  // The one way to see a named arm on a real phone: ?arm=boxes.
  //
  // Outside `assignedVariant` on purpose, twice over. That block is held
  // byte-identical against the other module's copy of it — the whole subject
  // of tests/test_variants.py — so nothing may be added inside it; and
  // assignment reading the session id and nothing else is what makes the
  // split stable and honest, so nothing should be.
  //
  // It can only return an arm the pool already carries, so it cannot conjure
  // a layout the config does not name, and it is read once per load and
  // written nowhere: no cookie, no storage, nothing that could leak a forced
  // arm into a later session's numbers.
  //
  // A forced page still reports the arm it drew, because that is what the
  // reader saw. A QA walk therefore lands in the split like any other
  // session — a handful of loads against numbers read over thousands — and
  // an event naming an arm nobody was shown would be worse than that.
  function forcedVariant(pool) {
    var want = "";
    try {
      want = (new RegExp("[?&]arm=([^&#]+)").exec(
        window.location.search) || [])[1] || "";
      want = decodeURIComponent(want);
    } catch (e) {
      return null;
    }
    if (!want) return null;
    for (var i = 0; i < pool.length; i++) {
      if (pool[i].id === want) return pool[i];
    }
    return null;
  }

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

    // Which way this page is laid out. `null` on a funnel that declares no
    // variants, and the control arm carries no template — so both of those
    // take the branch below exactly as it has always been, node for node.
    // Only an arm that names a template takes the other one.
    var variant = forcedVariant(variantPool(ctx.cfg))
      || assignedVariant(ctx.cfg);
    // A funnel may also name a template outright, with no A/B behind it. That
    // is a layout decision already made rather than one being measured: no
    // variants block, nothing assigned, and `reportVariant` below is handed
    // null so no `paywall_variant` event is emitted for it.
    //
    // An assigned arm still wins, so a funnel running the experiment behaves
    // exactly as it did: a control arm carries no template and a funnel
    // running variants declares no `result_template`, so both halves of it
    // land on "" the way they always have.
    var template = (variant && variant.template)
      || (ctx.cfg && ctx.cfg.result_template) || "";
    // Reported here, before a single node is built.
    //
    // It used to be the last statement in this function, and that cost the
    // A/B its numbers: `renderCommerce` runs before any module does, so the
    // nodes engine.js watches for `paywall_view` exist whatever happens
    // next, and `mod.render` is called inside a try/catch that falls back to
    // engine's own page. A throw anywhere below — in the hero, the taps, the
    // arm's own builders, the offer — lost this event while `paywall_view`
    // went on firing, with `errors=0` in the browser because the catch
    // swallowed it.
    //
    // Worse, the arms run different builders, so a fault on one path lost
    // that arm disproportionately and biased the split without touching
    // assignment. Assignment is a pure function of the session id and needs
    // nothing that can throw, so the report goes with it.
    reportVariant(ctx, variant);

    root.innerHTML = "";
    // The arm, on the container rather than inside it. Every rule the
    // facelift adds hangs off this, and `#result-module`'s own class is not
    // part of the subtree the variants fixture compares — so the control arm
    // stays byte-identical while its stylesheet gains rules it never matches.
    // The two lean arms are one page with one block swapped, so they wear one
    // class and read the whole of this sheet: the framed kicker, the lux
    // hero, the taps strip and the rarity card are the same nodes with the
    // same rules on both. `is-boxes` is added on top and scopes nothing but
    // the two blocks that differ.
    var lean = template === "minimal" || template === "boxes";
    root.classList.toggle("is-minimal", lean);
    root.classList.toggle("is-boxes", template === "boxes");
    root.appendChild(kicker(copy, lean));
    // The rich card, or the one this page drew before there was a table to
    // draw it from. Below the hero the two pages differ entirely, which is
    // why the branch is the whole body rather than one node.
    root.appendChild(data
      ? richHero(ctx, glyph(ctx.picks.sign), data, { lean: lean })
      : hero(ctx, copy, elements, top));
    var strip = taps(ctx, copy);
    if (strip) root.appendChild(strip);
    if (data && lean) {
      // The short way down the page: the picture, the evidence it was read
      // from, how rare the reading is, and then the price. No locked bullets
      // doing the offer's job above the offer, and no bridge line.
      //
      // The four element tiles are gone too. They restated the hero's split
      // bar one for one — the same four numbers, in the same order, a screen
      // apart — and a page whose argument is brevity cannot afford to say a
      // thing twice. The bar keeps it; `balance` still draws for the funnels
      // that have no rich hero to put it in.
      var rare = rarityBadge(data, profileBlock(ctx) || {});
      if (rare) root.appendChild(rare);
      // And where the two lean arms part: minimal carries its pitch as a
      // checklist inside the offer card, boxes puts a locked chapter and four
      // tiles here instead. Everything above this line and everything below
      // it is the same page.
      if (template === "boxes") root.appendChild(boxesPitch(ctx));
    } else if (data) {
      var free = freeStrength(ctx, copy);
      if (free) root.appendChild(free);
      var line = bridge(ctx, data);
      if (line) root.appendChild(line);
      root.appendChild(questions(ctx, data));
    } else {
      root.appendChild(path(ctx, copy, elements));
    }
    root.appendChild(offer(ctx, copy, data, template));

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

  function compatibility(data, ctx) {
    var frag = document.createDocumentFragment();
    if (data.intro) frag.appendChild(elm("p", "zr-body", data.intro));
    var list = elm("ul", "zr-verdicts");
    (data.pairs || []).forEach(function (pair) {
      var row = elm("li", "zr-verdict");
      var head = elm("p", "zr-verdict-head");
      head.appendChild(elm("span", "zr-combo", pair.combo || ""));
      var mark = pair.verdict || "";
      var tag = elm("span", "zr-tag is-" + (mark || "works"),
                    named(ctx, "verdicts", mark, mark.toUpperCase()));
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

  function career(data, ctx) {
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
      frag.appendChild(elm("p", "zr-sub-head", label(ctx, "saves_head")));
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
        body.appendChild(build(section.data, ctx));
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
      var rich = richHero(ctx, glyph(pick), data);
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
      cell.appendChild(elm("span", "zr-el-name", elementName(ctx, tag)));
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
