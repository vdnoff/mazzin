#!/usr/bin/env python3
"""The single-page checkout, driven end to end in a browser.

Serves the funnel with a switchable config so both sides of
`checkout.single_page` can be walked, records every /api/track body in order,
and stands in for Stripe so the redirect can actually be followed.

    python3 single.py [scroll|mid|sticky|error|offflag|all]

  scroll   reach the offer by scrolling            -> paywall_view src=scroll
  mid      tap the mid-page CTA                    -> src=mid_cta
  sticky   arm the bar by scrolling, then tap it   -> src=sticky
  error    /api/checkout fails at the pay button   -> pay_tap, checkout_error
  offflag  single_page=false: the old two screens  -> paywall_open, no new events
"""
import copy
import http.server
import json
import os
import socketserver
import sys
import threading
# The repo root, derived from this file rather than hardcoded: a suite
# that only runs from one absolute path is a suite that stops running the
# first time the checkout moves.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


from playwright.sync_api import sync_playwright

ROOT = REPO
SHOTS = os.path.dirname(os.path.abspath(__file__))
PORT = 8751

BASE = json.load(open(os.path.join(ROOT, "funnels/kitchen.json")))
STEPS = BASE["swipe"]["steps"]
ANCHORS = {i["after_step"] for i in BASE["interstitials"]}
COM = BASE["checkout"]["commerce"]

events = []
single = [True]
checkout_ok = [True]
strip_commerce = [True]
fails = []


def check(label, ok, detail=""):
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("    %-56s %s%s" % (label, "ok" if ok else "FAIL",
                              ("  " + str(detail)) if not ok else ""))


def names():
    return [e.get("event") for e in events]


def extras(event):
    return [e.get("extra") for e in events if e.get("event") == event]


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/pixel-config":
            return self._json({})
        if path == "/static/funnels/kitchen.json":
            cfg = copy.deepcopy(BASE)
            cfg["checkout"]["single_page"] = single[0]
            if not single[0] and strip_commerce[0]:
                # One of the two flag-off runs also drops the copy block, which
                # is the config an older funnel would have: the engine has to
                # fall back on its own rather than lean on it being there.
                cfg["checkout"].pop("commerce", None)
            return self._json(cfg)
        if path == "/paid":
            body = b"<!doctype html><title>stripe</title>redirected"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/kitchen":
            self.path = "/static/funnel.html"
        return super().do_GET()

    def do_POST(self):
        path = self.path.split("?")[0]
        raw = self.rfile.read(int(self.headers.get("content-length") or 0))
        if path == "/api/track":
            try:
                events.append(json.loads(raw.decode("utf-8")))
            except Exception:
                events.append({"event": "<unparseable>"})
            self.send_response(204)
            self.end_headers()
            return
        if path == "/api/checkout":
            if not checkout_ok[0]:
                self.send_response(500)
                self.end_headers()
                return
            return self._json({"url": "http://127.0.0.1:%d/paid" % PORT})
        self._json({"ok": True})

    def _json(self, body):
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def quiz(page):
    page.wait_for_selector("#cards .card", timeout=10000)
    for i, step in enumerate(STEPS):
        page.query_selector_all("#cards .card")[0].click()
        done = i + 1
        if done in ANCHORS and done < len(STEPS):
            page.wait_for_selector("#screen-interstitial.is-active", timeout=12000)
            page.click("#mid-cta")
        if done < len(STEPS):
            page.wait_for_function(
                "q => document.getElementById('swipe-caption').textContent === q",
                arg=STEPS[done]["question"], timeout=12000)
    page.wait_for_selector("#result-body:not([hidden])", timeout=15000)
    page.wait_for_timeout(500)


def sticky_shown(page):
    return page.evaluate(
        """() => { const b = document.getElementById('sticky-cta');
             return !b.hidden && b.classList.contains('is-in'); }""")


def layout(page):
    """Document order of the pieces that must be in the specified sequence."""
    return page.evaluate("""() => {
      const ids = ['result-name', 'report', 'mid-offer', 'mistakes-teaser',
                   'commerce', 'manifest', 'pay-anchor', 'price',
                   'withdrawal', 'pay-button', 'pay-error', 'trust',
                   'legal-links'];
      const out = {};
      ids.forEach(id => {
        const n = document.getElementById(id);
        out[id] = n ? {top: Math.round(n.getBoundingClientRect().top
                                       + window.scrollY),
                       inCommerce: !!(document.getElementById('commerce')
                                      .contains(n)),
                       inReport: !!(document.getElementById('report')
                                    .contains(n))} : null;
      });
      return out;
    }""")


def run_single(mode):
    print("\n=== single-page: %s ===" % mode)
    single[0] = True
    checkout_ok[0] = (mode != "error")
    del events[:]

    with sync_playwright() as pw:
        b = pw.chromium.launch(
            executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
        page = b.new_page(viewport={"width": 390, "height": 844},
                          device_scale_factor=2)
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.goto("http://127.0.0.1:%d/kitchen" % PORT)
        quiz(page)

        # --- structure ---------------------------------------------------
        geo = layout(page)
        check("the old result CTA is gone",
              page.eval_on_selector("#cta", "n => n.hidden") is True)
        check("no duplicate value banner",
              page.query_selector("#value-banner") is None)
        check("the commerce block is on the result page",
              geo["commerce"] is not None
              and page.eval_on_selector("#commerce", "n => !n.hidden"))
        for row in ("manifest", "pay-anchor", "price", "withdrawal",
                    "pay-button", "pay-error", "trust", "legal-links"):
            check("  %s moved into the block" % row,
                  geo[row] and geo[row]["inCommerce"], row)
        block = page.eval_on_selector(
            "#commerce",
            """n => Array.from(n.children)
                 .filter(c => !c.hidden && c.offsetParent !== null)
                 .map(c => c.id || c.className)""")
        check("  headline, list, sample, price, consent, button, trust",
              block == ["pay-anchor", "manifest", "sample-link", "price",
                        "withdrawal", "pay-button", "trust", "legal-links"],
              block)
        check("the mid-CTA sits inside the report card",
              geo["mid-offer"] and geo["mid-offer"]["inReport"])
        check("the teaser sits inside the report card",
              geo["mistakes-teaser"] and geo["mistakes-teaser"]["inReport"])
        order = ["result-name", "mid-offer", "mistakes-teaser", "commerce"]
        tops = [geo[i]["top"] for i in order]
        check("order: header -> mid-CTA -> teaser -> commerce",
              tops == sorted(tops), list(zip(order, tops)))
        elements_top = page.evaluate(
            "() => Math.round(document.querySelector('.section-elements')"
            ".getBoundingClientRect().top + window.scrollY)")
        first_locked = page.evaluate(
            """() => { const s = [...document.querySelectorAll('#report .section')]
                 .find(n => n.getAttribute('data-mode') === 'locked');
                 return Math.round(s.getBoundingClientRect().top + window.scrollY); }""")
        check("the mid-CTA is between Style Elements and the locked sections",
              elements_top < geo["mid-offer"]["top"] < first_locked,
              (elements_top, geo["mid-offer"]["top"], first_locked))

        # --- copy ---------------------------------------------------------
        check("anchor headline names the saving in the accent",
              page.inner_text("#pay-anchor .anchor-head .money") == "$4,000+",
              page.inner_text("#pay-anchor"))
        check("anchor headline is priced from config",
              "$3 decision" in page.inner_text("#pay-anchor .anchor-head"),
              page.inner_text("#pay-anchor .anchor-head"))
        check("the support line is gone from the block",
              page.eval_on_selector("#pay-anchor .anchor-line",
                                    "n => n.hidden || !n.textContent"))
        check("and the headline is no longer a card",
              page.eval_on_selector(
                  "#pay-anchor",
                  "n => getComputedStyle(n).backgroundColor"
                  " === 'rgba(0, 0, 0, 0)'"),
              page.eval_on_selector("#pay-anchor",
                                    "n => getComputedStyle(n).backgroundColor"))
        check("price row", page.inner_text("#price")
              == "3.00 USD · one-time · no subscription",
              page.inner_text("#price"))
        check("the price sits directly above the consent row",
              page.eval_on_selector(
                  "#price", "n => n.nextElementSibling.id") == "withdrawal")
        check("consent row", page.inner_text("#withdrawal-text")
              == "One-time $3 — no subscription, ever. My report unlocks instantly.",
              page.inner_text("#withdrawal-text"))
        check("consent is pre-checked",
              page.eval_on_selector("#withdrawal-check", "n => n.checked"))
        check("the button names the price",
              page.inner_text("#pay-button") == "Get my report for $3",
              page.inner_text("#pay-button"))
        check("trust row", page.eval_on_selector_all(
              "#trust .trust-row", "ns => ns.map(n => n.textContent.trim())")
              == COM["trust"], page.eval_on_selector_all(
              "#trust .trust-row", "ns => ns.map(n => n.textContent.trim())"))
        check("six manifest rows",
              page.eval_on_selector_all("#manifest .manifest-row",
                                        "ns => ns.length") == 6)
        check("the mistakes row keeps its accent treatment",
              page.eval_on_selector_all(".manifest-row.is-hero",
                                        "ns => ns.length") == 1)
        check("the paywall's own kicker and title are hidden",
              page.eval_on_selector("#pay-kicker", "n => n.hidden")
              and page.eval_on_selector("#paywall-headline", "n => n.hidden"))
        check("mid-CTA copy",
              page.inner_text("#mid-offer .mid-offer-line")
              == COM["mid_line"]
              and page.inner_text("#mid-offer .mid-offer-cta")
              == COM["mid_button"],
              page.inner_text("#mid-offer"))
        check("mid-CTA accents the saving",
              page.inner_text("#mid-offer .money") == "$4,000+")
        check("sticky label", page.eval_on_selector(
              "#sticky-cta", "n => n.textContent") == "Unlock full report — $3",
              page.eval_on_selector("#sticky-cta", "n => n.textContent"))

        # --- tracking so far ----------------------------------------------
        seen = names()
        check("result_view fired", "result_view" in seen, seen)
        check("paywall_open never fires in single-page mode",
              "paywall_open" not in seen, seen)
        check("the offer has not been seen yet",
              "paywall_view" not in seen, seen)
        check("the sticky bar starts hidden", not sticky_shown(page))

        # --- reaching the offer -------------------------------------------
        if mode == "mid":
            page.click("#mid-offer .mid-offer-cta")
            page.wait_for_timeout(400)
            check("mid_cta fired", "mid_cta" in names(), names())
            check("the bar arms the moment the mid-CTA is tapped",
                  page.eval_on_selector("#sticky-cta", "n => !n.hidden")
                  or "commerce" in page.url, "bar stayed hidden")
            page.wait_for_timeout(1400)          # let the smooth scroll land
            want = "mid_cta"
        elif mode == "sticky":
            # Scroll just past the palette to arm the bar, but not to the offer.
            page.evaluate(
                """() => { const p = document.querySelector('#report .section');
                     window.scrollTo(0, p.getBoundingClientRect().bottom
                                        + window.scrollY + 40); }""")
            page.wait_for_timeout(500)
            check("scrolling past the palette shows the bar", sticky_shown(page))
            check("no mid_cta was claimed", "mid_cta" not in names(), names())

            # The bar asks for a scroll, not for money. It briefly took the
            # payment itself; that is reverted, so this mode rejoins the
            # shared tail below — the block arrives, and the button on it is
            # what gets pressed.
            page.click("#sticky-cta")
            page.wait_for_timeout(1600)          # let the smooth scroll land
            check("sticky_cta fired", "sticky_cta" in names(), names())
            check("no pay_tap from the bar itself",
                  "pay_tap" not in names(), names())
            want = "sticky"
        else:
            page.evaluate("() => document.getElementById('commerce')"
                          ".scrollIntoView()")
            page.wait_for_timeout(700)
            check("neither prompt was tapped",
                  "mid_cta" not in names() and "sticky_cta" not in names(),
                  names())
            want = "scroll"

        page.wait_for_timeout(400)
        seen = names()
        check("paywall_view fired", "paywall_view" in seen, seen)
        got = extras("paywall_view")
        check("it fired exactly once", len(got) == 1, got)
        check("src is %r" % want, got and got[0] == {"src": want}, got)
        check("paywall_view comes after result_view",
              seen.index("result_view") < seen.index("paywall_view"), seen)
        check("the bar hides while the offer is on screen",
              not sticky_shown(page))
        page.screenshot(path=os.path.join(SHOTS, "sp-%s.png" % mode))

        # --- paying --------------------------------------------------------
        page.click("#pay-button")
        if mode == "error":
            page.wait_for_selector("#pay-error:not([hidden])", timeout=10000)
            page.wait_for_timeout(400)
            seen = names()
            check("pay_tap fired", "pay_tap" in seen, seen)
            check("checkout_error fired", "checkout_error" in seen, seen)
            check("pay_tap precedes checkout_error",
                  seen.index("pay_tap") < seen.index("checkout_error"), seen)
            check("the reader is told", bool(page.inner_text("#pay-error")))
            check("the button is usable again",
                  page.eval_on_selector("#pay-button", "n => !n.disabled"))
        else:
            page.wait_for_url("**/paid", timeout=10000)
            page.wait_for_timeout(300)
            seen = names()
            check("pay_tap fired", "pay_tap" in seen, seen)
            check("no checkout_error", "checkout_error" not in seen, seen)
            check("reached Stripe", "/paid" in page.url, page.url)

        check("no page errors", not errs, errs[:3])
        print("    funnel: %s" % " -> ".join(
            [n for n in names() if n != "swipe" and n != "interstitial"]))
        b.close()


def run_offflag(strip=True):
    print("\n=== flag off%s: the two-screen regression ==="
          % (" (config complete)" if not strip else " (copy block absent too)"))
    single[0] = False
    strip_commerce[0] = strip
    checkout_ok[0] = True
    del events[:]

    with sync_playwright() as pw:
        b = pw.chromium.launch(
            executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
        page = b.new_page(viewport={"width": 390, "height": 844},
                          device_scale_factor=2)
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.goto("http://127.0.0.1:%d/kitchen" % PORT)
        quiz(page)

        check("the result CTA is back",
              page.eval_on_selector("#cta", "n => !n.hidden"))
        check("the commerce block stays empty and hidden",
              page.eval_on_selector("#commerce",
                                    "n => n.hidden && n.children.length === 0"))
        check("the value banner is back",
              page.query_selector("#value-banner") is not None)
        check("the cta note is back",
              page.query_selector("#cta-note") is not None)
        check("the teaser is above the report, as before",
              page.evaluate("""() => {
                const t = document.getElementById('mistakes-teaser');
                const r = document.getElementById('report');
                return !!t && !r.contains(t)
                  && (t.compareDocumentPosition(r)
                      & Node.DOCUMENT_POSITION_FOLLOWING) > 0; }"""))
        check("no mid-CTA on the page",
              page.query_selector("#mid-offer") is None)
        check("the sticky bar never appears", not sticky_shown(page))
        check("the pay button is still on the paywall screen",
              page.evaluate("""() => document.getElementById('screen-paywall')
                   .contains(document.getElementById('pay-button'))"""))

        page.click("#cta")
        page.wait_for_selector("#screen-paywall.is-active", timeout=5000)
        page.wait_for_timeout(500)
        seen = names()
        check("paywall_open fired, as before", "paywall_open" in seen, seen)
        check("no single-page events anywhere",
              not ({"mid_cta", "sticky_cta"} & set(seen)), seen)
        check("the paywall kicker and title are visible again",
              page.eval_on_selector("#pay-kicker", "n => !n.hidden")
              and bool(page.inner_text("#paywall-headline")))
        check("the old price row", page.inner_text("#price")
              == "3.00 USD · one-time", page.inner_text("#price"))
        check("the old consent line",
              "waive my 14-day withdrawal right" in
              page.inner_text("#withdrawal-text"),
              page.inner_text("#withdrawal-text"))
        check("the old trust rows", page.eval_on_selector_all(
              "#trust .trust-row", "ns => ns.map(n => n.textContent.trim())")
              == BASE["checkout"]["trust"])
        page.screenshot(path=os.path.join(SHOTS, "sp-offflag.png"))

        page.click("#pay-button")
        page.wait_for_url("**/paid", timeout=10000)
        seen = names()
        check("pay_tap still fires on the pay button", "pay_tap" in seen, seen)
        check("reached Stripe", "/paid" in page.url, page.url)
        check("no page errors", not errs, errs[:3])
        print("    funnel: %s" % " -> ".join(
            [n for n in names() if n not in ("swipe", "interstitial")]))
        b.close()


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        modes = (["scroll", "mid", "sticky", "error"] if which in ("all", "single")
                 else [] if which == "offflag" else [which])
        for m in modes:
            run_single(m)
        if which in ("all", "offflag"):
            run_offflag(strip=False)   # flag alone
            run_offflag(strip=True)    # flag plus an older config
    finally:
        httpd.shutdown()
    print("\n%d failed" % len(fails))
    for f in fails:
        print("  FAIL " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
