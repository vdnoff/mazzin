/* The zodiac funnel's pre-purchase result page.
 *
 * Loaded by engine.js when a config names it, handed the finished run, and
 * responsible for everything the reader sees between the analysing screen and
 * the money. It is not a second engine: it computes nothing about the quiz,
 * it renders what it is given, and the two things that must not be got wrong
 * — the withdrawal-right consent and the button that charges — are engine.js's
 * own live nodes, moved into this layout rather than rebuilt in it.
 *
 * The page, top to bottom: a kicker, the cosmic ID card, the strip of frames
 * they actually tapped, a constellation path of what is open and what is not,
 * and the offer.
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

  // The steps whose frames are worth showing back, in the order they read.
  // Only ones they tapped are drawn — a strip that shows a card somebody did
  // not choose is the opposite of proof.
  var TAP_STEPS = ["landscape", "palette", "moonphase", "symbol", "sanctuary"];
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

  // --- c) read from your taps ------------------------------------------------

  function taps(ctx, copy) {
    var picks = TAP_STEPS
      .map(function (id) { return ctx.picks[id]; })
      .filter(Boolean);
    if (picks.length < TAPS_MIN) return null;

    var block = elm("section", "zr-taps");
    block.appendChild(elm("p", "zr-taps-caption",
                          copy.taps_caption || "Read from your taps:"));
    var row = elm("ul", "zr-taps-row");
    picks.slice(0, 5).forEach(function (pick) {
      var cell = elm("li", "zr-tap");
      var img = document.createElement("img");
      img.src = pick.img;
      img.alt = "";
      img.loading = "lazy";
      img.decoding = "async";
      cell.appendChild(img);
      cell.appendChild(elm("span", "zr-tap-name", pick.label || ""));
      row.appendChild(cell);
    });
    block.appendChild(row);
    return block;
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

  function locked(ctx, section, copy) {
    var item = node("locked", section.title);
    var body = item.querySelector(".zr-node-body");
    var line = ctx.fillHook(section.teaser_line || "");
    if (line) body.appendChild(elm("p", "zr-teaser", line));
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
    ctx.sections.forEach(function (section) {
      if (!section.locked) return;
      list.appendChild(locked(ctx, section, copy));
    });
    return list;
  }

  // --- e) the offer ----------------------------------------------------------

  // engine.js has already built and wired all of this. What happens here is
  // placement: the consent box, the button, its error line and the legal
  // links are moved into this card, which is why the withdrawal waiver still
  // gates the same button it always did and no payment code lives in here.
  function offer(ctx, copy) {
    var card = elm("section", "zr-offer");
    var nodes = ctx.nodes;

    var anchorText = ctx.withPrice(ctx.commerce.anchor_head
                                   || ctx.cfg.checkout.anchor_head || "");
    var accent = ctx.commerce.anchor_head_accent || "";
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
    card.appendChild(elm("p", "zr-offer-sub", copy.offer_sub || ""));

    // Live nodes, not copies of them.
    [nodes.consent, nodes.payButton, nodes.payError].forEach(function (n) {
      if (n) card.appendChild(n);
    });

    var trust = (ctx.commerce.trust || ctx.cfg.checkout.trust || []);
    if (trust.length) {
      card.appendChild(elm("p", "zr-trust", trust.join(" · ")));
    }
    if (nodes.legal) card.appendChild(nodes.legal);

    // The rows this layout does not use. Hidden rather than removed: they are
    // the same elements the paid view and the two-screen flow still want.
    [nodes.manifest, nodes.anchor, nodes.price, nodes.trust]
      .forEach(function (n) { if (n) n.hidden = true; });
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

    root.innerHTML = "";
    root.appendChild(kicker(copy));
    root.appendChild(hero(ctx, copy, elements, top));
    var strip = taps(ctx, copy);
    if (strip) root.appendChild(strip);
    root.appendChild(path(ctx, copy, elements));
    root.appendChild(offer(ctx, copy));

    // The container engine.js moved the offer rows into is empty now and its
    // own border would draw a line under nothing.
    if (ctx.nodes.commerce) ctx.nodes.commerce.hidden = true;
    root.hidden = false;
  }

  window.MazzinResult = { render: render };
}());
