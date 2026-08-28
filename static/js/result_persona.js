/* The persona funnel's pre-purchase result page.
 *
 * A conscious fork of static/js/result_zodiac.js. Same contract — engine.js
 * loads it when a config names it, hands it the finished run, and the two
 * things that must not be got wrong, the withdrawal-right consent and the
 * button that charges, are engine.js's own live nodes moved into this layout
 * rather than rebuilt in it. What differs is everything the fork exists for:
 * the vocabulary is drive/anchor/wave/prism rather than the four elements,
 * the ground is a deep warm umbra with clay slabs on it rather than gold on
 * indigo, every class carries a `pr-` prefix so the two stylesheets cannot
 * reach each other's pages, and this page draws a head.
 *
 * It is a fork rather than a shared file on purpose. The two funnels are two
 * products in two voices, and a single module parameterised over both would
 * be a file where every third line asks which one it is running for.
 *
 * The page, top to bottom: a kicker, the rich profile card — totem on a lit
 * pedestal, persona name and essence, rarity, a sentence woven from their own
 * picks, four trait bars and the clay head — the strip of frames they
 * actually tapped, the six questions the profile answers — each behind a
 * lock — and the offer.
 *
 * The free strength that used to sit between the strip and the questions is
 * gone. It was the one thing given away that the paywall was also selling,
 * and reading it answered enough of the question to stop being a reason to
 * pay. The locked teasers stay: they are the offer.
 *
 * The card is one of eight personas: the run's tallies resolve to an
 * archetype and an energy lean, and `result_copy.profile` in the config turns
 * those two into a name, a one-line essence, a measured rarity and a totem.
 * The runner-up axis survives as an undercurrent in the formula line — real,
 * and a detail rather than an identity.
 *
 * A config with no `profile` block still renders: the plain ID card and the
 * node path are kept below and drawn instead. This file and the config it
 * reads sit behind a CDN and can be a version apart, and a reader who arrives
 * in that window should get last week's page rather than none.
 */
(function () {
  "use strict";

  // This funnel's scoring axes. engine.js deliberately does not know these —
  // the vocabulary belongs to the funnel — so the grouping happens here and
  // the raw tallies come across.
  var AXES = ["drive", "anchor", "wave", "prism"];
  var ENERGY = ["outer", "inner"];

  // The gallery's own families, so a bar and its frames are the same colour.
  var AXIS_COLOR = {
    drive: "#F0845A", anchor: "#9BB08A", wave: "#4EDDC4", prism: "#A98CE8"
  };
  var AXIS_NAME = {
    drive: "Drive", anchor: "Anchor", wave: "Wave", prism: "Prism"
  };
  var ENERGY_NAME = { outer: "Outer", inner: "Inner" };

  // The tone axis, as this funnel actually tags it. There is no `light` tag
  // and there never was one: `deep` is the single word the vocabulary spends
  // on what sits under the surface, and `bold` and `calm` are what it spends
  // on everything above it. So the light-to-deep scale reads deep against the
  // sum of the other two — a real measurement of the run rather than an
  // invented one, which is why most dots on it sit left of centre.
  var TONE = ["bold", "calm", "deep"];

  // The reader's year runs from the month they are in, not from January, and
  // the Year card names both ends of it. reports.py builds the same twelve
  // server-side and holds the generated section to them; this is the free
  // page's copy of the arithmetic, which is all it can be — nothing has been
  // bought yet, so there is no report to read them off.
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

  var SVG_NS = "http://www.w3.org/2000/svg";

  // One SVG node with its attributes set. Presentation attributes rather than
  // classes throughout the head below: the same drawing has to be reproducible
  // server-side for the PDF, where there is no stylesheet of this page's to
  // read, and markup that carries its own paint ports across as a string.
  function svgEl(name, attrs) {
    var node = document.createElementNS(SVG_NS, name);
    for (var key in attrs) {
      if (Object.prototype.hasOwnProperty.call(attrs, key)) {
        node.setAttribute(key, String(attrs[key]));
      }
    }
    return node;
  }

  // The strongest tag in a set. A tie goes to whichever one the winning style
  // is scored on, because the card says both — "Owl × The Feeler, 35% Wave" —
  // and a tie broken by array order can print an axis the archetype beside it
  // does not carry.
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
  // Everything the hero card and the head say, computed from the tallies the
  // run already produced. Nothing here asks engine.js for anything new: the
  // archetype, the runner-up axis and the energy lean are all in `ctx.tally`,
  // and the names, the essence lines and the rarity are all in the config.
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
  function splitOf(axes) {
    var raw = axes.map(function (row) { return Math.max(0, row.score); });
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
    return axes.map(function (row, i) {
      return {
        tag: row.tag,
        name: AXIS_NAME[row.tag] || row.tag,
        pct: pcts[i],
        color: AXIS_COLOR[row.tag] || "#4EDDC4"
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

  // Where the eight persona totems live. One image per archetype and energy,
  // placeholders until v3-B renders them; the path is built rather than
  // configured because the naming is the persona and there is nothing to
  // choose.
  var TOTEM_DIR = "/static/galleries/persona/totem_";

  // The four traits, in human words. The tags are the funnel's own vocabulary
  // and stay in the data; these are what a reader is shown, and they come off
  // the config so the page and the report cannot disagree about them.
  function traitsOf(table, split) {
    var names = {};
    (table.traits || []).forEach(function (row) {
      if (row && row.tag) names[row.tag] = row.name || row.tag;
    });
    return split.map(function (cell) {
      return {
        tag: cell.tag,
        name: names[cell.tag] || AXIS_NAME[cell.tag] || cell.tag,
        pct: cell.pct
      };
    });
  }

  // The paragraph, woven from what they actually picked.
  //
  // The claim the whole funnel makes is that the shapes unlock something, so
  // the reading has to quote them back — not "you are curious" but "you
  // reached for *lit up*". Three picks carry it: the shape they opened on,
  // the chapter they said they are in, and the fork they follow. Those are
  // the three the interstitials already echoed, so the page finishes a
  // sentence the quiz started.
  //
  // Returns a list of parts rather than a string: a label is set in italics
  // and a string would have to be parsed back apart to do it. Each part is
  // {text} or {em} and the renderer turns them into text and <em>.
  var NARRATIVE_STEPS = ["now", "chapter", "forks"];

  function narrativeOf(ctx, name) {
    var picks = (ctx && ctx.picks) || {};
    var got = NARRATIVE_STEPS
      .map(function (id) { return picks[id]; })
      .filter(function (pick) { return pick && pick.label; });
    if (!got.length) return null;

    var parts = [{ text: "You opened on " },
                 { em: got[0].label.toLowerCase() }];
    if (got.length > 1) {
      parts.push({ text: ", said the chapter you are in is " });
      parts.push({ em: got[1].label.toLowerCase() });
    }
    if (got.length > 2) {
      parts.push({ text: ", and when it forks you follow " });
      parts.push({ em: got[2].label.toLowerCase() });
    }
    parts.push({ text: ". That is " + name + ", and the rest of this page "
                       + "is what those three unlock." });
    return parts;
  }

  // The whole card, or null when the config carries no table for it — which
  // is what sends `render` back to the plain page below.
  function profileOf(ctx, axes, top) {
    var table = profileBlock(ctx);
    if (!table || !table.subtypes) return null;

    var scores = positive(axes);
    var primary = top.tag;
    // The runner-up, never the archetype's own axis. A tie falls to the
    // declared axis order — the same rule the rarity is counted by, because a
    // name resolved on one rule and counted on another is a number about
    // nothing.
    var second = AXES
      .filter(function (tag) { return tag !== primary; })
      .reduce(function (best, tag) {
        return (best === null || scores[tag] > scores[best]) ? tag : best;
      }, null);

    var energyScores = positive(ctx.tally(ENERGY));
    var own = ctx.style.tags || [];
    var energy;
    if (energyScores.outer > energyScores.inner) {
      energy = "outer";
    } else if (energyScores.inner > energyScores.outer) {
      energy = "inner";
    } else {
      // Dead level. The archetype's own energy carries it, because the name
      // beside the number says both, and a tie broken by list order can print
      // an energy the archetype does not hold.
      energy = ENERGY.filter(function (tag) {
        return own.indexOf(tag) !== -1;
      })[0] || ENERGY[0];
    }

    // v3: eight personas, one per archetype and energy. The 24-name table was
    // archetype x runner-up x energy, which named a blend nobody could hold in
    // their head and split the audience so fine that four of the cells were
    // unreachable. The runner-up survives as an undercurrent in the formula
    // line — it is real, and it is a detail rather than an identity.
    var name = (table.subtypes[ctx.style.id] || {})[energy];
    if (!name) return null;

    var essence = ((table.essence || {})[ctx.style.id] || {})[energy] || "";

    var tone = positive(ctx.tally(TONE));
    var at = {
      energy: between(energyScores.outer, energyScores.inner),
      tone: between(tone.bold, tone.calm),
      depth: between(tone.bold + tone.calm, tone.deep)
    };
    var split = splitOf(axes);
    var rarity = ((table.rarity || {})[ctx.style.id] || {})[energy] || 0;
    var rarer = ((table.rarer_than || {})[ctx.style.id] || {})[energy] || 0;

    var bare = name.replace(/^The\s+/, "");
    var year = yearOf(ctx);
    var words = {
      first: year[0],
      last: year[year.length - 1],
      subtype: name,
      subtype_bare: bare,
      subtype_article: /^[AEIOU]/.test(bare) ? "an" : "a",
      axis: AXIS_NAME[primary] || primary,
      second: AXIS_NAME[second] || second,
      energy: ENERGY_NAME[energy] || energy,
      n: String(rarity),
      rarer: String(rarer)
    };
    split.forEach(function (cell) { words[cell.tag] = String(cell.pct); });

    return {
      archetype: ctx.style.id,
      primary: primary,
      second: second,
      energy: energy,
      subtype: name,
      subtype_bare: bare,
      essence: essence,
      rarity: rarity,
      rarer: rarer,
      totem: TOTEM_DIR + ctx.style.id + "_" + energy + ".webp",
      // The persona as one string, which is what the share card, the share
      // page and the share event are all keyed by. Built once here so the
      // three cannot spell it differently.
      persona_slug: ctx.style.id + "_" + energy,
      narrative: narrativeOf(ctx, name),
      traits: traitsOf(table, split),
      words: words,
      // The formula loses its leading separator rather than printing one when
      // a run never reached the opening step.
      formula: fill(table.formula || "", words).replace(/^\s*·\s*/, ""),
      rarity_line: rarer ? fill(table.rarity_line || "", words) : "",
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
    return elm("p", "pr-kicker", copy.kicker || "YOUR MIND PROFILE");
  }

  // --- b) the ID card --------------------------------------------------------

  // The frame they opened the quiz on, masked to a disc. The form is centred
  // in the art, so a centre crop is the shape and nothing else needs drawing.
  function glyph(pick) {
    var badge = elm("span", "pr-glyph");
    if (!pick) return badge;
    var img = document.createElement("img");
    img.src = pick.img;
    img.alt = "";
    img.decoding = "async";
    badge.appendChild(img);
    return badge;
  }

  // The totem on its pedestal, under a spotlight. The persona's own form,
  // lit the way the sculptures in the quiz were lit, so the reading opens on
  // the same gallery the quiz was walked through — at dusk rather than in
  // daylight, which is what the analysing fade has just done to the page.
  //
  // The image is a slot: a placeholder until v3-B renders the eight. It is
  // built from the persona rather than chosen, so a missing file is a missing
  // render and never a missing branch.
  function pedestal(data) {
    var stand = elm("figure", "pr-totem");
    var light = elm("span", "pr-totem-light");
    light.setAttribute("aria-hidden", "true");
    stand.appendChild(light);
    if (data && data.totem) {
      var img = document.createElement("img");
      img.className = "pr-totem-art";
      img.src = data.totem;
      img.alt = "";
      img.decoding = "async";
      stand.appendChild(img);
    }
    var plinth = elm("span", "pr-totem-plinth");
    plinth.setAttribute("aria-hidden", "true");
    stand.appendChild(plinth);
    return stand;
  }

  // The narrative, with the reader's own picks set in italics.
  function narrativeBlock(parts) {
    if (!parts || !parts.length) return null;
    var para = elm("p", "pr-narrative");
    parts.forEach(function (part) {
      if (part.em) {
        para.appendChild(elm("em", "pr-quote", part.em));
      } else {
        para.appendChild(document.createTextNode(part.text || ""));
      }
    });
    return para;
  }

  // The share control, and the only thing on this page that hands something
  // out rather than taking something in.
  //
  // Free page only. After the money the reader has a report to read and a
  // link that is theirs — offering to broadcast the persona at that moment is
  // the wrong ask on the wrong page, and `deliveredHero` does not pass the
  // option that draws this.
  //
  // Two paths, because the Web Share API is a phone feature and this page has
  // desktop readers. Where it exists the sheet is the whole interaction; where
  // it does not the link goes to the clipboard and a small toast says so. A
  // reader who dismisses the native sheet is not a failure and gets nothing:
  // `AbortError` is the ordinary way that dialog closes.
  function shareBlock(ctx, data, copy) {
    var share = (copy && copy.share) || {};
    if (!data || !data.persona_slug) return null;

    var base = share.url_base || "/persona/s/";
    var url = location.origin + base + data.persona_slug;
    var wrap = elm("div", "pr-share");
    var button = elm("button", "pr-share-btn",
                     share.button || "Share your shape");
    button.type = "button";
    var toast = elm("span", "pr-share-toast", "");
    toast.setAttribute("role", "status");

    function say(text) {
      toast.textContent = text;
      toast.classList.add("is-on");
    }

    button.addEventListener("click", function () {
      // Fired before either path runs, and once. What the reader does with
      // the sheet after that is theirs; the event is the intent, and the
      // return leg is counted separately as `subid=share-<id>` on whoever
      // arrives.
      try {
        ctx.track("share_tap", { persona: data.persona_slug });
      } catch (e) { /* a tap is not worth losing to a blocked beacon */ }

      var payload = {
        title: fill(share.title || "", data.words || {}),
        text: share.text || "",
        url: url
      };
      if (navigator.share) {
        navigator.share(payload).catch(function (err) {
          if (err && err.name === "AbortError") return;
          say(share.failed || "Could not share");
        });
        return;
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(function () {
          say(share.copied || "Link copied");
        }, function () {
          say(share.failed || "Could not share");
        });
        return;
      }
      say(share.failed || "Could not share");
    });

    wrap.appendChild(button);
    wrap.appendChild(toast);
    return wrap;
  }

  // Four bars, one per trait: a clay track with a teal fill and the human
  // word beside it. The stacked split bar this replaces put the four traits
  // in one rule, which reads as a budget being divided rather than as four
  // things the reader has different amounts of.
  function traitBars(data) {
    var rows = (data && data.traits) || [];
    if (!rows.length) return null;
    var wrap = elm("div", "pr-traits");
    rows.forEach(function (row) {
      var line = elm("div", "pr-trait");
      line.appendChild(elm("span", "pr-trait-name", row.name));
      var track = elm("span", "pr-trait-track");
      track.setAttribute("role", "img");
      track.setAttribute("aria-label",
                         row.name + " " + row.pct + " out of 100");
      var fillBar = elm("i", "pr-trait-fill");
      fillBar.style.width = row.pct + "%";
      track.appendChild(fillBar);
      line.appendChild(track);
      line.appendChild(elm("span", "pr-trait-value", row.pct + "%"));
      wrap.appendChild(line);
    });
    return wrap;
  }

  function hero(ctx, copy, axes, top) {
    var card = elm("section", "pr-hero");
    card.appendChild(glyph(ctx.picks.now));

    var opener = (ctx.picks.now && ctx.picks.now.label) || ctx.style.name;
    card.appendChild(elm("h1", "pr-animal", opener));
    card.appendChild(elm("p", "pr-cross", "× " + ctx.style.name));

    var pct = share(axes, top);
    var bar = elm("div", "pr-bar");
    bar.setAttribute("role", "img");
    bar.setAttribute("aria-label",
                     pct + "% " + (AXIS_NAME[top.tag] || top.tag));
    var fillBar = elm("span", "pr-bar-fill");
    fillBar.style.width = pct + "%";
    fillBar.style.background = AXIS_COLOR[top.tag] || "#4EDDC4";
    bar.appendChild(fillBar);
    card.appendChild(bar);

    var led = lead(ctx.tally(ENERGY), ctx.style.tags);
    var parts = [pct + "% " + (AXIS_NAME[top.tag] || top.tag)];
    if (led && led.score > 0) {
      parts.push((ENERGY_NAME[led.tag] || led.tag) + "-led");
    }
    if (copy.blend_note) parts.push(copy.blend_note);
    card.appendChild(elm("p", "pr-sub", parts.join(" · ")));
    return card;
  }

  // --- b2) the rich profile card ---------------------------------------------
  //
  // The card both halves of the funnel draw, top to bottom: the persona's
  // totem on a lit pedestal, the name and its one-line essence, the rarity
  // ribbon, the sentence woven from the reader's own picks, four trait bars,
  // and the clay head.
  //
  // The three spectrum scales and the stacked split bar this replaced are
  // gone. The split said the same thing as the trait bars in a form that read
  // as a budget being divided, and two of the three scales were measuring the
  // tone tags, which v3 keeps as scoring flavour and report material rather
  // than as something the result page has to explain. The energy scale
  // survives in the data, unrendered, because the head reads its lean off it.
  //
  // It takes a finished block rather than a run, because the delivered page
  // has no run to give it — reports.py stores the same shape on the report
  // and `deliveredHero` hands it straight in.

  function richHero(badge, data, copy, opts) {
    var card = elm("section", "pr-hero is-rich");
    // v3 order: the totem first and large, then who that makes them, then the
    // measure, then the sentence built from their own picks. The badge the
    // callers still pass is the frame they opened the quiz on; it rides in
    // the identity row rather than leading the card, because the totem is now
    // the picture of them and the pick is the evidence for it.
    card.appendChild(pedestal(data));

    var id = elm("div", "pr-hero-id");
    id.appendChild(elm("h1", "pr-subtype", data.subtype));
    if (data.essence) {
      id.appendChild(elm("p", "pr-essence", data.essence));
    }
    if (data.formula) id.appendChild(elm("p", "pr-formula", data.formula));
    card.appendChild(id);

    if (data.rarity_line) {
      card.appendChild(elm("p", "pr-ribbon", data.rarity_line));
    }
    var story = narrativeBlock(data.narrative);
    if (story) card.appendChild(story);
    if (opts && opts.share && opts.ctx) {
      var handout = shareBlock(opts.ctx, data, copy || {});
      if (handout) card.appendChild(handout);
    }
    var bars = traitBars(data);
    if (bars) card.appendChild(bars);
    // The drawing, directly under the name and the rarity and above the three
    // scales. It was the last thing on the page, below six locked cards, and
    // it is the one part of the card that is a picture of the reader rather
    // than a row of numbers — so it opens the card and the scales read as its
    // detail. Inside `richHero` rather than at either call site because both
    // the free page and the delivered one draw this card, and a reposition
    // applied in one place is a reposition that drifts.
    var drawing = headBlock(copy || {}, data);
    if (drawing) card.appendChild(drawing);
    return card;
  }

  // --- b3) the clay head -----------------------------------------------------
  //
  // The one drawing on this page, and the only thing on it that is not a bar.
  //
  // v1 drew the whole thing in SVG: a profile outline in stroke, with the
  // radar inside its skull. v3 splits it in two. The head is a rendered clay
  // profile — the same material as every card in the quiz, with a smooth
  // empty cranium left in it on purpose — and the radar is inlaid on that
  // empty field: grooves pressed into the clay, a teal glaze poured in the
  // shape of the reader, beads set at the points.
  //
  // The split is what makes it belong to the funnel. A stroked outline is a
  // diagram of a head; a photographed clay head with a mark pressed into it
  // is an object from the same gallery as the shapes they just picked, which
  // is the whole claim the product makes.
  //
  // What did not change is where the numbers come from. Everything drawn
  // here comes off the same block the hero card is built from — `split` for
  // the four traits, the `energy` scale for the lean — so the delivered page
  // and the PDF can draw it from a stored block with no run in the tab.

  // The rendered base. A placeholder until v3-B, and referenced by path for
  // the same reason the totems are: there is nothing to choose.
  var HEAD_BASE = "/static/galleries/persona/head_base.webp";

  // The overlay's own box. It is square and self-contained — the cranial
  // field it sits on is positioned by the stylesheet against the image, and
  // the SVG knows only its own centre. v1's geometry was measured against a
  // silhouette this file drew itself and could not survive the image
  // replacing it.
  var INLAY_SIZE = 240;
  var HEAD_CX = 120;
  var HEAD_CY = 120;
  var HEAD_R = 96;
  var LEAN_ARC = "M 24 44 Q 120 -6 216 44";

  // The clay the grooves are pressed into, and the glaze poured in them.
  var GROOVE = "#7A5334";
  var GROOVE_SOFT = "#8E6742";
  var GLAZE = "#4EDDC4";

  // Which way each trait points out of the centre, and the glyph the legend
  // gives it. Up is the trait that starts things and down is the one that
  // holds ground, which is the only arrangement of these four a reader does
  // not have to be told.
  var HEAD_AXES = [
    { tag: "drive", dx: 0, dy: -1, arrow: "↑" },
    { tag: "prism", dx: 1, dy: 0, arrow: "→" },
    { tag: "anchor", dx: 0, dy: 1, arrow: "↓" },
    { tag: "wave", dx: -1, dy: 0, arrow: "←" }
  ];

  // The four traits as 0-100, scaled so the reader's strongest reaches the
  // outer ring. Shares of a hundred would put every polygon inside the middle
  // circle and every reader's shape would look like everybody else's; the
  // shape is the subject here, and the numbers are printed underneath it
  // either way.
  function headValues(data) {
    var by = {};
    (data.split || []).forEach(function (cell) {
      by[cell.tag] = Math.max(0, cell.pct || 0);
    });
    var top = AXES.reduce(function (best, tag) {
      return Math.max(best, by[tag] || 0);
    }, 0);
    var out = {};
    AXES.forEach(function (tag) {
      out[tag] = top ? Math.round(100 * (by[tag] || 0) / top) : 0;
    });
    return out;
  }

  // Where the bead on the arc sits, 0 hard outer and 100 hard inner. Read off
  // the block by id rather than by position so a config that reorders its
  // scales does not silently move it.
  function leanAt(data) {
    var rows = data.scales || [];
    for (var i = 0; i < rows.length; i++) {
      if (rows[i] && rows[i].id === "energy") {
        return Math.max(0, Math.min(100, rows[i].at));
      }
    }
    return 50;
  }

  function leanPoint(t) {
    var u = 1 - t;
    return {
      x: u * u * 24 + 2 * u * t * 120 + t * t * 216,
      y: u * u * 44 + 2 * u * t * -6 + t * t * 44
    };
  }

  // The inlay. No head in it: the head is the photograph underneath.
  function headSvg(data) {
    var values = headValues(data);
    var svg = svgEl("svg", {
      viewBox: "0 0 " + INLAY_SIZE + " " + INLAY_SIZE,
      class: "pr-head-svg", role: "img",
      "aria-label": HEAD_AXES.map(function (row) {
        return (AXIS_NAME[row.tag] || row.tag) + " " + values[row.tag];
      }).join(", ") + " out of 100"
    });

    // The grid, as grooves pressed into the clay. Warm and darker than the
    // surface rather than a lighter ruled line: a groove in clay reads as a
    // shadow, and a light stroke would sit on top of the head like ink.
    [HEAD_R / 3, HEAD_R * 2 / 3, HEAD_R].forEach(function (r) {
      svg.appendChild(svgEl("circle", {
        cx: HEAD_CX, cy: HEAD_CY, r: r.toFixed(1),
        fill: "none", stroke: GROOVE, "stroke-width": 1.5,
        "stroke-opacity": 0.55
      }));
    });
    [[HEAD_CX, HEAD_CY - HEAD_R, HEAD_CX, HEAD_CY + HEAD_R],
     [HEAD_CX - HEAD_R, HEAD_CY, HEAD_CX + HEAD_R, HEAD_CY]]
      .forEach(function (line) {
        svg.appendChild(svgEl("line", {
          x1: line[0], y1: line[1], x2: line[2], y2: line[3],
          stroke: GROOVE, "stroke-width": 1.5, "stroke-opacity": 0.55
        }));
      });

    // The reader's own shape, as glaze poured into the field. Heavier fill
    // than v1's outline-on-ink: on clay the colour is the mark, and a thin
    // stroke would read as drawn on rather than run in.
    var points = HEAD_AXES.map(function (row) {
      var r = HEAD_R * (values[row.tag] || 0) / 100;
      return { x: HEAD_CX + row.dx * r, y: HEAD_CY + row.dy * r };
    });
    svg.appendChild(svgEl("polygon", {
      points: points.map(function (p) {
        return p.x.toFixed(1) + "," + p.y.toFixed(1);
      }).join(" "),
      fill: GLAZE, "fill-opacity": 0.42,
      stroke: GLAZE, "stroke-width": 2.5, "stroke-linejoin": "round"
    }));
    points.forEach(function (p) {
      svg.appendChild(svgEl("circle", {
        cx: p.x.toFixed(1), cy: p.y.toFixed(1), r: 4, fill: GLAZE
      }));
    });

    // The lean, over the crown. One dashed groove with a lit bead on it:
    // which way the reader's charge runs is a single number and deserves a
    // single mark, not a fifth bar.
    svg.appendChild(svgEl("path", {
      d: LEAN_ARC, fill: "none", stroke: GROOVE_SOFT, "stroke-width": 1.2,
      "stroke-dasharray": "3 5"
    }));
    var bead = leanPoint(leanAt(data) / 100);
    svg.appendChild(svgEl("circle", {
      cx: bead.x.toFixed(1), cy: bead.y.toFixed(1), r: 5, fill: GLAZE
    }));
    return svg;
  }

  function headLegend(data) {
    var values = headValues(data);
    var names = {};
    (data.traits || []).forEach(function (row) { names[row.tag] = row.name; });
    var list = elm("ul", "pr-head-legend");
    HEAD_AXES.forEach(function (row) {
      var cell = elm("li", "pr-head-key");
      var mark = elm("span", "pr-head-arrow", row.arrow);
      mark.setAttribute("aria-hidden", "true");
      cell.appendChild(mark);
      cell.appendChild(elm("span", "pr-head-name",
                           names[row.tag] || AXIS_NAME[row.tag] || row.tag));
      cell.appendChild(elm("span", "pr-head-value",
                           String(values[row.tag] || 0)));
      list.appendChild(cell);
    });
    return list;
  }

  function headBlock(copy, data) {
    if (!data || !(data.split || []).length) return null;
    var block = elm("section", "pr-head");
    if (copy.head_title) {
      block.appendChild(elm("p", "pr-head-title", copy.head_title));
    }
    // The base and the inlay in one positioned box. The image carries the
    // head; the stylesheet puts the overlay on the cranium; neither knows
    // anything about the other beyond the box they share.
    var plate = elm("div", "pr-head-plate");
    var base = document.createElement("img");
    base.className = "pr-head-base";
    base.src = HEAD_BASE;
    base.alt = "";
    base.decoding = "async";
    plate.appendChild(base);
    var field = elm("div", "pr-head-inlay");
    field.appendChild(headSvg(data));
    plate.appendChild(field);
    block.appendChild(plate);
    block.appendChild(headLegend(data));
    if (copy.head_caption) {
      block.appendChild(elm("p", "pr-head-caption", copy.head_caption));
    }
    return block;
  }

  // --- c) read from your taps ------------------------------------------------
  //
  // Every frame of the run, six to a row, in the order they were tapped. The
  // whole claim of this block is "this profile was read off these", so it is
  // all eighteen rather than a chosen five, small and unlabelled: the point is
  // the count and the fact that the reader recognises every square.
  //
  // No new bytes on the wire. Every one of these files was decoded during the
  // quiz and is in the browser's cache; the grid is the same images again.

  function tapsGrid(picks) {
    var row = elm("ul", "pr-taps-grid");
    picks.forEach(function (pick) {
      var cell = elm("li", "pr-tap");
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
    var block = elm("section", "pr-taps");
    block.appendChild(elm("p", "pr-taps-caption",
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
  // config, so a funnel that carries no such block renders with no
  // personalisation at all rather than differently.

  function purposeMap(ctx) {
    var map = ((ctx.cfg && ctx.cfg.result_copy) || {}).purpose_map;
    return (map && typeof map === "object") ? map : null;
  }

  // Found by tag rather than by step id: which question asks this is the
  // funnel's business, and a module that hardcoded the step's name would
  // quietly stop working the day the step was renamed.
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

  // --- d) the node path ------------------------------------------------------

  var LOCK_PATH = "M5 8V5.5a3 3 0 0 1 6 0V8M4 8h8v6H4z";

  function node(kind, title) {
    var item = elm("li", "pr-node is-" + kind);
    var mark = elm("span", "pr-node-mark");
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
    var body = elm("div", "pr-node-body");
    body.appendChild(elm("h2", "pr-node-title", title));
    item.appendChild(body);
    return item;
  }

  // All four axes at once, so the winning one is a claim with the other three
  // standing next to it rather than a number on its own.
  function balance(ctx, copy, axes) {
    var item = node("open", copy.balance_title || "Your axis balance");
    var chart = elm("div", "pr-balance");
    var top = Math.max.apply(null, axes.map(function (row) {
      return Math.max(0, row.score);
    }).concat([1]));
    axes.forEach(function (row) {
      var col = elm("div", "pr-bal");
      var track = elm("span", "pr-bal-track");
      var bar = elm("span", "pr-bal-fill");
      // A floor, so an axis the reader scored nothing on is still a labelled
      // column rather than a gap in the chart.
      bar.style.height =
        Math.max(4, Math.round(100 * Math.max(0, row.score) / top)) + "%";
      bar.style.background = AXIS_COLOR[row.tag] || "#4EDDC4";
      track.appendChild(bar);
      col.appendChild(track);
      col.appendChild(elm("span", "pr-bal-name",
                          AXIS_NAME[row.tag] || row.tag));
      col.appendChild(elm("span", "pr-bal-pct", share(axes, row) + "%"));
      chart.appendChild(col);
    });
    item.querySelector(".pr-node-body").appendChild(chart);
    return item;
  }

  function locked(ctx, section, copy, isLead) {
    var item = node("locked", section.title);
    if (isLead) item.classList.add("is-lead");
    var body = item.querySelector(".pr-node-body");
    var line = ctx.fillHook(section.teaser_line || "");
    if (line) {
      var teaser = elm("p", "pr-teaser", line);
      // One step up the tier the rest of this page uses for a line that is
      // not body copy and not a whisper. Set from the tokens rather than from
      // a new rule, because a new rule would be a new visual language for one
      // line on one funnel.
      if (isLead) {
        teaser.classList.add("is-lead");
        teaser.style.color = "var(--pr-muted)";
        teaser.style.fontSize = "15px";
      }
      body.appendChild(teaser);
    }
    var lock = elm("span", "pr-lock", copy.locked_note || "Locked");
    lock.setAttribute("aria-hidden", "true");
    item.insertBefore(lock, null);
    return item;
  }

  function path(ctx, copy, axes) {
    var list = elm("ol", "pr-path");
    list.appendChild(balance(ctx, copy, axes));
    // The balance chart above is the free half now and keeps its place. The
    // reorder is inside what is still shut, so the section they came for is
    // the first locked thing they meet rather than the fourth.
    var want = emphasised(purposeRule(ctx));
    var shut = ctx.sections.filter(function (s) { return s.locked; });
    firstly(shut, want).forEach(function (section) {
      list.appendChild(locked(ctx, section, copy, section.id === want));
    });
    return list;
  }

  // --- d3) the six questions -------------------------------------------------

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
    var svg = svgEl("svg", { viewBox: "0 0 16 16" });
    if (cls) svg.setAttribute("class", cls);
    (paths || []).forEach(function (d) {
      svg.appendChild(svgEl("path", {
        d: d, "stroke-linejoin": "round", "stroke-linecap": "round"
      }));
    });
    return svg;
  }

  // The promise, with every token answered. Three sources in order: the
  // profile's own words for {axis} and {second}, engine.js's hook machinery
  // for {weather} — which already declares "weather" as its fallback — and
  // then a last sweep, because a brace is never a thing to show a reader on
  // the page that asks them for money.
  function promise(ctx, card, data, tag) {
    var text = (tag && card.upgrade && card.upgrade[tag]) || card.promise || "";
    text = fill(text, data.words || {});
    if (typeof ctx.fillHook === "function") text = ctx.fillHook(text);
    return text
      .replace(/\{weather\}/g, "weather")
      .replace(/\{\w+\}/g, "")
      .replace(/\s{2,}/g, " ")
      .trim();
  }

  function questionCard(ctx, card, data, tag, first) {
    var item = elm("li", "pr-card" + (first ? " is-lead" : ""));
    var icon = elm("span", "pr-card-icon");
    icon.setAttribute("aria-hidden", "true");
    icon.appendChild(drawn(ICONS[card.icon] || ICONS.map));
    item.appendChild(icon);

    var line = elm("p", "pr-card-line");
    line.appendChild(elm("strong", "pr-card-key", (card.key || "") + ":"));
    line.appendChild(document.createTextNode(
      " " + promise(ctx, card, data, tag)));
    item.appendChild(line);

    var lock = elm("span", "pr-card-lock");
    lock.setAttribute("aria-hidden", "true");
    lock.appendChild(drawn([LOCK_PATH]));
    item.appendChild(lock);
    return item;
  }

  function questions(ctx, data) {
    var table = profileBlock(ctx) || {};
    var want = emphasised(purposeRule(ctx));
    var tag = purposeTagOf(ctx);
    var list = elm("ul", "pr-cards");
    // The chapter they said they came for is the first thing they meet, and
    // it is the one card wearing the stronger border. Only the first match
    // moves.
    firstly((table.cards || []).slice(), want).forEach(function (card) {
      list.appendChild(questionCard(ctx, card, data, tag,
                                    !!want && card.id === want));
    });
    return list;
  }

  function bridge(ctx, data) {
    var table = profileBlock(ctx) || {};
    var line = fill(table.bridge || "", data.words || {});
    return line ? elm("p", "pr-bridge", line) : null;
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
  //
  // engine.js has already built and wired all of this. What happens here is
  // placement: the consent box, the button, its error line and the legal
  // links are moved into this card, which is why the withdrawal waiver still
  // gates the same button it always did and no payment code lives in here.

  function offer(ctx, copy, data) {
    var card = elm("section", "pr-offer");
    var nodes = ctx.nodes;

    if (data) {
      var head = ctx.withPrice(
        fill((profileBlock(ctx) || {}).offer_head || "", data.words || {}));
      if (head) card.appendChild(elm("p", "pr-offer-head", head));
    }

    // The price, and the order of the argument around it. The reader's own
    // price is the thing they are deciding about, so it is the loudest text
    // here by a distance; the anchor is one muted line above it, doing the
    // work of a footnote.
    var anchorText = ctx.withPrice(ctx.commerce.price_anchor
                                   || ctx.commerce.anchor_head
                                   || ctx.cfg.checkout.anchor_head || "");
    var accent = ctx.commerce.price_anchor_accent
      || ctx.commerce.anchor_head_accent || "";
    var anchor = elm("p", "pr-anchor");
    if (accent && anchorText.indexOf(accent) !== -1) {
      var cut = anchorText.split(accent);
      anchor.appendChild(document.createTextNode(cut[0]));
      anchor.appendChild(elm("span", "pr-teal", accent));
      anchor.appendChild(document.createTextNode(cut.slice(1).join(accent)));
    } else {
      anchor.textContent = anchorText;
    }
    card.appendChild(anchor);

    var price = elm("p", "pr-price");
    price.appendChild(elm("span", "pr-price-now", ctx.price));
    var note = ctx.commerce.price_note || "";
    if (note) price.appendChild(elm("span", "pr-price-note", note));
    card.appendChild(price);

    // The two questions a reader asks a small button, answered where they are
    // asked rather than in a run-on line at the bottom of the card.
    var badges = ctx.commerce.badges || [];
    if (badges.length) {
      var row = elm("ul", "pr-badges");
      badges.forEach(function (text) {
        row.appendChild(elm("li", "pr-badge", text));
      });
      card.appendChild(row);
    }
    // The one line under the anchor, in the reader's own terms when the run
    // said what they came for. Everything else on this card — the price, the
    // button, the trust row, the consent — is untouched by any of this.
    var rule = purposeRule(ctx);
    card.appendChild(elm("p", "pr-offer-sub",
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
      card.appendChild(elm("p", "pr-trust", trust.join(" · ")));
    }
    if (nodes.legal) card.appendChild(nodes.legal);

    // The rows this layout does not use. Hidden rather than removed: they are
    // the same elements the paid view and the two-screen flow still want.
    [nodes.manifest, nodes.anchor, nodes.price, nodes.trust]
      .forEach(function (n) { if (n) n.hidden = true; });

    // This card is the offer now. engine.js fires `paywall_view` and Meta's
    // InitiateCheckout when the offer reaches the reader, and it watches
    // whichever node it is told to; naming the card is the whole of it. What
    // the event means, when it fires and what it carries all stay engine.js's
    // business.
    //
    // Guarded because this file and engine.js sit behind a CDN and can be a
    // version apart: an engine without the hook draws the same page and only
    // loses the event.
    if (typeof ctx.watchOffer === "function") ctx.watchOffer(card);
    return card;
  }

  // --- render ----------------------------------------------------------------

  function render(root, ctx) {
    var copy = (ctx.cfg && ctx.cfg.result_copy) || {};
    var axes = ctx.tally(AXES);
    // The axis the hero names is the archetype's own, not the highest scorer.
    // They are usually the same and they do not have to be: an archetype is
    // won on three tags, so a Feeler reader can out-score prism and still be
    // a Feeler. "Owl × The Feeler" over "53% Prism" reads as a bug in a card
    // whose whole subject is the archetype. The balance chart below still
    // shows all four honestly, which is where a reader who wants the full
    // picture goes.
    var own = axes.filter(function (row) {
      return ctx.style.tags.indexOf(row.tag) !== -1;
    });
    var top = own[0] || lead(axes, ctx.style.tags)
      || { tag: AXES[0], score: 0 };

    var data = profileOf(ctx, axes, top);

    root.innerHTML = "";
    root.appendChild(kicker(copy));
    // The rich card, or the plain one, when a config carries no table to draw
    // it from. Below the hero the two pages differ entirely, which is why the
    // branch is the whole body rather than one node.
    root.appendChild(data
      ? richHero(glyph(ctx.picks.now), data, copy,
                 { share: true, ctx: ctx })
      : hero(ctx, copy, axes, top));
    var strip = taps(ctx, copy);
    if (strip) root.appendChild(strip);
    if (data) {
      var line = bridge(ctx, data);
      if (line) root.appendChild(line);
      root.appendChild(questions(ctx, data));
    } else {
      root.appendChild(path(ctx, copy, axes));
    }
    root.appendChild(offer(ctx, copy, data));

    // The container engine.js moved the offer rows into is empty now and its
    // own border would draw a line under nothing.
    if (ctx.nodes.commerce) ctx.nodes.commerce.hidden = true;
    root.hidden = false;
  }

  // --- the delivered report --------------------------------------------------
  //
  // The same page after the money. The reader paid on a dark page and the
  // thing they bought has to open as the same document: the same kicker, the
  // same hero, the same head, and every node open with its section's real
  // content inside it.

  function swatches(data) {
    var wrap = elm("div", "pr-swatches");
    (data.colors || []).forEach(function (colour) {
      var row = elm("div", "pr-swatch");
      var dot = elm("span", "pr-swatch-dot");
      dot.style.background = colour.hex || "#000";
      row.appendChild(dot);
      var text = elm("div", "pr-swatch-text");
      var head = elm("p", "pr-swatch-head");
      head.appendChild(elm("span", "pr-swatch-name", colour.name || ""));
      head.appendChild(elm("span", "pr-swatch-hex", colour.hex || ""));
      text.appendChild(head);
      // Role and when, on one line, the way the PDF sets them.
      var when = [colour.role, colour.finish].filter(Boolean).join(" · ");
      if (when) text.appendChild(elm("p", "pr-swatch-role", when));
      if (colour.where) {
        text.appendChild(elm("p", "pr-swatch-where", colour.where));
      }
      row.appendChild(text);
      wrap.appendChild(row);
    });
    var frag = document.createDocumentFragment();
    if (data.intro) frag.appendChild(elm("p", "pr-body", data.intro));
    frag.appendChild(wrap);
    if (data.closing_rule) {
      frag.appendChild(elm("p", "pr-note", data.closing_rule));
    }
    return frag;
  }

  function strengths(data) {
    var list = elm("ol", "pr-list");
    (data.items || []).forEach(function (item, i) {
      var row = elm("li", "pr-item");
      row.appendChild(elm("span", "pr-item-num", String(i + 1)));
      var body = elm("div", "pr-item-body");
      body.appendChild(elm("h3", "pr-item-title", item.title || ""));
      if (item.body) body.appendChild(elm("p", "pr-body", item.body));
      if (item.fix) body.appendChild(elm("p", "pr-fix", "→ " + item.fix));
      row.appendChild(body);
      list.appendChild(row);
    });
    return list;
  }

  function connection(data) {
    var frag = document.createDocumentFragment();
    if (data.intro) frag.appendChild(elm("p", "pr-body", data.intro));
    var list = elm("ul", "pr-verdicts");
    (data.pairs || []).forEach(function (pair) {
      var row = elm("li", "pr-verdict");
      var head = elm("p", "pr-verdict-head");
      head.appendChild(elm("span", "pr-combo", pair.combo || ""));
      head.appendChild(elm("span", "pr-tag is-" + (pair.verdict || "works"),
                           (pair.verdict || "").toUpperCase()));
      row.appendChild(head);
      if (pair.why) row.appendChild(elm("p", "pr-body", pair.why));
      list.appendChild(row);
    });
    frag.appendChild(list);
    if (data.rule) frag.appendChild(elm("p", "pr-note", data.rule));
    return frag;
  }

  function blueprint(data) {
    var frag = document.createDocumentFragment();
    (data.narrative || []).forEach(function (para) {
      frag.appendChild(elm("p", "pr-body", para));
    });
    var list = elm("ul", "pr-implications");
    (data.implications || []).forEach(function (line) {
      list.appendChild(elm("li", null, line));
    });
    if (list.childNodes.length) frag.appendChild(list);
    return frag;
  }

  function work(data) {
    var frag = document.createDocumentFragment();
    var head = elm("div", "pr-splurge");
    head.appendChild(elm("p", "pr-splurge-head",
                         (data.splurge && data.splurge.item) || ""));
    if (data.splurge && data.splurge.why) {
      head.appendChild(elm("p", "pr-body", data.splurge.why));
    }
    frag.appendChild(head);
    var list = elm("ul", "pr-saves");
    (data.saves || []).forEach(function (row) {
      var item = elm("li", "pr-save");
      item.appendChild(elm("span", "pr-save-item", row.item || ""));
      if (row.why) item.appendChild(document.createTextNode(" " + row.why));
      list.appendChild(item);
    });
    if (list.childNodes.length) {
      frag.appendChild(elm("p", "pr-sub-head", "Where to stop spending it"));
      frag.appendChild(list);
    }
    if (data.split_note) {
      frag.appendChild(elm("p", "pr-note", data.split_note));
    }
    return frag;
  }

  function months(data) {
    var list = elm("ol", "pr-months");
    (data.items || []).forEach(function (item) {
      var row = elm("li", "pr-month");
      row.appendChild(elm("span", "pr-month-name", item.name || ""));
      row.appendChild(elm("span", "pr-month-note", item.priority_note || ""));
      list.appendChild(row);
    });
    var frag = document.createDocumentFragment();
    frag.appendChild(list);
    (data.skip || []).forEach(function (row) {
      var quiet = elm("p", "pr-note");
      quiet.appendChild(elm("span", "pr-month-name", row.name || ""));
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
    materials: connection,
    dna: blueprint,
    splurge: work,
    shopping: months
  };

  // A photograph out of this reader's own run, or nothing. Never a stock
  // frame: the page above this one says the profile was read off their taps,
  // and an image nobody chose is that sentence being untrue. The file is one
  // the browser already fetched during the quiz, so it costs a cache hit.
  function tapped(ctx, image_id) {
    var pick = image_id && ctx.images[image_id];
    if (!pick || !pick.img) return null;
    var frame = elm("figure", "pr-shot");
    var img = document.createElement("img");
    img.src = pick.img;
    img.alt = "";
    img.loading = "lazy";
    img.decoding = "async";
    frame.appendChild(img);
    if (pick.label) {
      frame.appendChild(elm("figcaption", "pr-shot-cap", pick.label));
    }
    return frame;
  }

  function sectionImage(ctx, section_id) {
    var map = (ctx.visuals && ctx.visuals.sections) || {};
    return tapped(ctx, map[section_id]);
  }

  function deliveredNode(ctx, section) {
    var item = node("open", section.title || "");
    var body = item.querySelector(".pr-node-body");
    // The keyword off the card that sold this chapter, over the title it was
    // sold under.
    var key = keywordOf(ctx, section.id);
    if (key) {
      body.insertBefore(elm("p", "pr-node-key", key + ":"), body.firstChild);
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
    if (section.body) body.appendChild(elm("p", "pr-body", section.body));
    return item;
  }

  // The hero, without a run behind it. The percentage and the balance chart
  // came from tallies this tab never had, so the plain delivered card carries
  // the identity and drops the arithmetic rather than inventing it.
  function deliveredHero(ctx, copy) {
    var card = elm("section", "pr-hero");
    var hero_visuals = (ctx.visuals && ctx.visuals.hero) || {};
    var pick = ctx.images[hero_visuals.glyph || shapeImageId(ctx)];
    // The same card as before the money, off the block reports.py measured
    // while the run still existed and stored on the report. Without one the
    // plain delivered card is drawn instead, which is the page those readers
    // were sent to and still have bookmarked.
    var data = (ctx.visuals && ctx.visuals.profile) || null;
    if (data && data.subtype) {
      var rich = richHero(glyph(pick), data, copy);
      // The place they chose, which the paid card has always carried and the
      // free one never did. Appended here rather than inside `richHero` for
      // exactly that reason: there is no band before the money.
      var horizon = tapped(ctx, hero_visuals.band);
      if (horizon) {
        horizon.classList.add("pr-band");
        rich.appendChild(horizon);
      }
      return rich;
    }
    var shape = shapeOf(ctx);
    card.appendChild(glyph(pick));
    card.appendChild(elm("h1", "pr-animal", shape || ctx.style.name));
    if (shape) {
      card.appendChild(elm("p", "pr-cross", "× " + ctx.style.name));
    }
    if (ctx.style.blurb) {
      card.appendChild(elm("p", "pr-sub", ctx.style.blurb));
    }
    card.appendChild(deliveredAxes(ctx));
    var band = tapped(ctx, hero_visuals.band);
    if (band) {
      band.classList.add("pr-band");
      card.appendChild(band);
    }
    return card;
  }

  // The axis row, after the money. The quiz tally is gone by now — someone
  // opening this from a link in their mail has no run left to count — so the
  // row names the archetype's own axis out of its tags rather than inventing
  // a percentage nobody measured. All four are drawn; one is lit.
  function deliveredAxes(ctx) {
    var own = (ctx.style.tags || []).filter(function (tag) {
      return AXES.indexOf(tag) !== -1;
    })[0] || "";
    var row = elm("div", "pr-axes");
    AXES.forEach(function (tag) {
      var cell = elm("span", "pr-ax" + (tag === own ? " is-own" : ""));
      var dot = elm("i", "pr-ax-dot");
      dot.style.background = AXIS_COLOR[tag] || "#8A97A0";
      cell.appendChild(dot);
      cell.appendChild(elm("span", "pr-ax-name", AXIS_NAME[tag] || tag));
      row.appendChild(cell);
    });
    return row;
  }

  // What the stored report calls the shape the reader opened on.
  //
  // engine.js's delivered context carries the slot under the name the first
  // funnel to need it gave it, `sign`, and that name is engine.js's business
  // rather than this funnel's: the word on this page is the shape, and all
  // three spellings are read here so the module works against the contract as
  // it stands, against the animal-shaped report v1 wrote, and against the day
  // engine.js grows the clearer name.
  function shapeOf(ctx) {
    return (ctx && (ctx.shape || ctx.animal || ctx.sign)) || "";
  }

  // That shape's own frame, found by label. The stored report keeps it as a
  // label rather than an id, because that is what the mail and the PDF need,
  // so the label is matched against the step's own images instead of being
  // pasted into an id — v3's ids are `now_<slug>` and a label like "Lit up"
  // does not spell one.
  function shapeImageId(ctx) {
    var want = shapeOf(ctx).toLowerCase();
    if (!want) return "";
    var ids = Object.keys(ctx.images);
    for (var i = 0; i < ids.length; i++) {
      var image = ctx.images[ids[i]];
      if (ids[i].indexOf("now_") === 0
          && image && String(image.label || "").toLowerCase() === want) {
        return ids[i];
      }
    }
    return "";
  }

  // --- the delivery note -----------------------------------------------------
  //
  // The first thing a buyer sees on this page, above everything, on both ways
  // in: seconds after paying, and a week later from the link in the mail. The
  // past tense is what makes one line true on both.
  //
  // The address comes off the authenticated report payload and is never
  // touched again: it is not tracked, not stored by this page, and not put
  // anywhere a second request could read it.

  var CHECK_PATH = "M3.5 8.6l3.1 3.1 5.9-6.4";

  function deliveryNote(ctx, copy) {
    if (!ctx.delivered) return null;
    var email = (((ctx.visuals || {}).delivery || {}).email || "").trim();
    var line = copy.delivery_line || "Your PDF was sent to {email}";
    var bare = copy.delivery_line_bare || "Your PDF was sent to your email";

    var bar = elm("p", "pr-sent");
    var mark = elm("span", "pr-sent-check");
    mark.setAttribute("aria-hidden", "true");
    var svg = svgEl("svg", { viewBox: "0 0 16 16" });
    svg.appendChild(svgEl("path", {
      d: CHECK_PATH, "stroke-linecap": "round", "stroke-linejoin": "round"
    }));
    mark.appendChild(svg);
    bar.appendChild(mark);

    var text = elm("span", "pr-sent-text");
    if (!email || line.indexOf("{email}") === -1) {
      text.textContent = bare;
    } else {
      var cut = line.split("{email}");
      text.appendChild(document.createTextNode(cut[0]));
      text.appendChild(elm("span", "pr-sent-mail", email));
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
    // — this tab may never have run the quiz — and a report without one
    // renders in report order.
    var list = elm("ol", "pr-path");
    firstly(ctx.sections, emphasised(purposeRule(ctx)))
      .forEach(function (section) {
        list.appendChild(deliveredNode(ctx, section));
      });
    root.appendChild(list);

    // No offer here, obviously. What replaces it is the one line the reader
    // still needs: where else this document is.
    if (ctx.complete && copy.delivered_note) {
      root.appendChild(elm("p", "pr-footnote", copy.delivered_note));
    }
    root.hidden = false;
  }

  window.MazzinResult = { render: render, delivered: delivered };
}());
