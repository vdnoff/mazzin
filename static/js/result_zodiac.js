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
      if (colour.role) text.appendChild(elm("p", "zr-swatch-role", colour.role));
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

  function deliveredNode(section) {
    var item = node("open", section.title || "");
    var body = item.querySelector(".zr-node-body");
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
    var pick = ctx.images[signImageId(ctx)];
    card.appendChild(glyph(pick));
    card.appendChild(elm("h1", "zr-sign", ctx.sign || ctx.style.name));
    if (ctx.sign) card.appendChild(elm("p", "zr-cross", "× " + ctx.style.name));
    if (ctx.style.blurb) {
      card.appendChild(elm("p", "zr-sub", ctx.style.blurb));
    }
    return card;
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

  function delivered(root, ctx) {
    var copy = (ctx.cfg && ctx.cfg.result_copy) || {};
    root.innerHTML = "";
    root.classList.add("is-delivered");
    root.appendChild(kicker(copy));
    root.appendChild(deliveredHero(ctx, copy));

    var list = elm("ol", "zr-path");
    ctx.sections.forEach(function (section) {
      list.appendChild(deliveredNode(section));
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
