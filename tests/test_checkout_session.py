#!/usr/bin/env python3
"""What /api/checkout actually hands Stripe.

Drives the real Flask route with a stubbed `stripe.checkout.Session.create`,
so the assertions are against the payload the live code builds rather than
against a re-implementation of it. Nothing reaches Stripe and no database is
touched — the route reads config and posts, and the recorder answers.
"""
import copy
import json
import os
import sys

# The repo root, derived from this file rather than hardcoded: a suite
# that only runs from one absolute path is a suite that stops running the
# first time the checkout moves.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, REPO)

import config          # noqa: E402
import payments        # noqa: E402
import stripe          # noqa: E402
from app import app    # noqa: E402

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-56s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)) if not ok else ""))


class Recorder:
    """Stands in for stripe.checkout.Session.create and keeps the kwargs."""

    def __init__(self):
        self.kwargs = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs

        class Session:
            url = "https://checkout.stripe.test/c/pay/cs_test_123"
        return Session()


BASE_CFG = config.load_funnel("kitchen")
STEPS = BASE_CFG["swipe"]["steps"]
CHOICES = [s["pairs"][0]["images"][0]["id"] for s in STEPS]

BODY = {
    "funnel": "kitchen",
    "session_id": "11111111-2222-4333-8444-555555555555",
    "result_style": BASE_CFG["styles"][0]["id"],
    "tag_scores": {"warm": 8, "wood": 6},
    "choices": CHOICES,
}


def post(cfg_override=None, body=None):
    """One /api/checkout call, returning (response, recorded kwargs)."""
    rec = Recorder()
    real_create = stripe.checkout.Session.create
    # The key comes off config, not off `stripe.api_key`: a funnel names the
    # mode it transacts in and the route looks the matching secret up per call,
    # so module state is no longer what decides whether checkout is possible.
    real_key = config.STRIPE_SECRET_KEY
    real_test_key = config.STRIPE_TEST_SECRET_KEY
    real_load = config.load_funnel
    stripe.checkout.Session.create = rec
    config.STRIPE_SECRET_KEY = "sk_test_notreal"
    # Both key sets, because both funnels asked for here transact: kitchen on
    # the live set and zodiac on the sandbox one while it is being walked with
    # a 4242 card. Which set a mode reaches for is test_modes.py's subject;
    # this suite is about the session that gets built either way, and a funnel
    # refusing checkout for want of a key would test nothing it means to.
    config.STRIPE_TEST_SECRET_KEY = "sk_test_notreal_sandbox"
    if cfg_override is not None:
        config.load_funnel = lambda slug: cfg_override
        payments.config.load_funnel = config.load_funnel
    try:
        with app.test_client() as client:
            res = client.post("/api/checkout", json=body or BODY)
    finally:
        stripe.checkout.Session.create = real_create
        config.STRIPE_SECRET_KEY = real_key
        config.STRIPE_TEST_SECRET_KEY = real_test_key
        config.load_funnel = real_load
        payments.config.load_funnel = real_load
    return res, rec.kwargs


# A sentinel for "the body does not carry this key at all", which is a
# different case from carrying it empty.
_ABSENT = object()


def product(kwargs):
    return kwargs["line_items"][0]["price_data"]["product_data"]


def main():
    print("\n--- the session as the config now stands ---")
    res, kw = post()
    check("the route answers 200", res.status_code == 200, res.status_code)
    check("it returns the Stripe url",
          res.get_json().get("url", "").startswith("https://checkout.stripe"),
          res.get_json())
    pd = product(kw)
    print("    product_data: %s" % json.dumps(pd, ensure_ascii=False))

    check("name comes from the config",
          pd["name"] == "Your Kitchen Style Report — "
                        "the mistakes that cost $4,000+", pd["name"])
    check("exactly one image", pd.get("images") == [
        "https://mazzin.com/static/creative_src/stripe_tile.png"],
        pd.get("images"))
    check("the image is absolute",
          pd["images"][0].startswith("https://"), pd["images"])
    check("it is a png, not the webp Stripe renders unreliably",
          pd["images"][0].endswith(".png") and ".webp" not in pd["images"][0],
          pd["images"])
    # Stripe fetches this URL itself, so a path that 404s renders nothing at
    # all — the file has to be on disk under static/ for the deploy to publish.
    import os
    disk = REPO + pd["images"][0].split("mazzin.com", 1)[1]
    check("the file it points at exists on disk", os.path.isfile(disk), disk)
    from PIL import Image
    with Image.open(disk) as im:
        check("and it really is a PNG", im.format == "PNG", im.format)
        check("with sane thumbnail dimensions",
              0 < im.size[0] <= 640 and 0 < im.size[1] <= 1000, im.size)
    check("and is small enough to fetch on every session",
          os.path.getsize(disk) < 512 * 1024, os.path.getsize(disk))

    print("\n--- the rest of the session is untouched ---")
    li = kw["line_items"][0]
    check("quantity 1", li["quantity"] == 1)
    check("price still from the funnel",
          li["price_data"]["unit_amount"] == BASE_CFG["pricing"]["amount_cents"]
          and li["price_data"]["currency"] == BASE_CFG["pricing"]["currency"],
          li["price_data"])
    check("price is an integer number of cents",
          isinstance(li["price_data"]["unit_amount"], int),
          type(li["price_data"]["unit_amount"]).__name__)
    check("mode is payment", kw["mode"] == "payment")
    check("managed payments still off",
          kw["managed_payments"] == {"enabled": False}, kw.get("managed_payments"))
    check("success url still carries the session placeholder",
          kw["success_url"].endswith("?cs={CHECKOUT_SESSION_ID}"),
          kw["success_url"])
    check("cancel url unchanged",
          kw["cancel_url"].endswith("?canceled=1"), kw["cancel_url"])
    check("metadata still carries the funnel and the style",
          kw["metadata"].get("funnel") == "kitchen"
          and kw["metadata"].get("result_style") == BODY["result_style"],
          kw["metadata"])
    check("metadata still carries the choices",
          "choices" in kw["metadata"], sorted(kw["metadata"]))
    check("customer_creation unchanged",
          kw["customer_creation"] == "if_required")

    print("\n--- fallbacks ---")
    bare = copy.deepcopy(BASE_CFG)
    bare["checkout"].pop("product_name", None)
    bare["checkout"].pop("product_image", None)
    res, kw = post(cfg_override=bare)
    pd = product(kw)
    check("without the keys the old derived name comes back",
          pd["name"] == "%s — Full Style Report" % BASE_CFG["meta"]["title"],
          pd["name"])
    check("and no images key is sent at all", "images" not in pd, pd)
    check("the route still answers 200", res.status_code == 200)

    no_checkout = copy.deepcopy(BASE_CFG)
    no_checkout.pop("checkout", None)
    res, kw = post(cfg_override=no_checkout)
    check("a config with no checkout block still checks out",
          res.status_code == 200 and "images" not in product(kw),
          res.status_code)

    print("\n--- bad values are dropped, never sent ---")
    for value, why in [
        ("static/galleries/kitchen/mp1.webp", "relative without a leading slash"),
        ("javascript:alert(1)", "not a url"),
        ("ftp://example.com/x.webp", "wrong scheme"),
        ("", "empty"),
        (123, "not a string"),
        (None, "null"),
    ]:
        cfg = copy.deepcopy(BASE_CFG)
        cfg["checkout"]["product_image"] = value
        res, kw = post(cfg_override=cfg)
        pd = product(kw)
        ok = res.status_code == 200 and "images" not in pd
        check("  %-38s dropped" % why, ok,
              "%s -> %s" % (repr(value), pd.get("images")))

    absolute = copy.deepcopy(BASE_CFG)
    absolute["checkout"]["product_image"] = "https://cdn.example.com/a.webp"
    res, kw = post(cfg_override=absolute)
    check("an already-absolute url is passed through",
          product(kw).get("images") == ["https://cdn.example.com/a.webp"],
          product(kw).get("images"))

    long_name = copy.deepcopy(BASE_CFG)
    long_name["checkout"]["product_name"] = "x" * 400
    res, kw = post(cfg_override=long_name)
    check("an over-long name is capped rather than rejected by Stripe",
          len(product(kw)["name"]) == payments.PRODUCT_NAME_MAX,
          len(product(kw)["name"]))

    blank = copy.deepcopy(BASE_CFG)
    blank["checkout"]["product_name"] = "   "
    res, kw = post(cfg_override=blank)
    check("a blank name falls back rather than shipping whitespace",
          product(kw)["name"].endswith("Full Style Report"),
          product(kw)["name"])

    print("\n--- and the zodiac session, which is not a kitchen ---")
    # Stripe's own page is the one screen of this purchase we do not draw, and
    # until now every funnel handed it the same photograph of a kitchen. On a
    # funnel whose product is a birth-chart reading that is somebody else's
    # product on the page where the card is entered.
    zcfg = config.load_funnel("zodiac")
    zsteps = zcfg["swipe"]["steps"]
    zbody = {
        "funnel": "zodiac",
        "session_id": "11111111-2222-4333-8444-555555555555",
        "result_style": zcfg["styles"][0]["id"],
        "tag_scores": {"fire": 8, "sun": 6},
        "choices": [("sign_leo" if st["id"] == "sign"
                     else st["pairs"][0]["images"][0]["id"]) for st in zsteps],
    }
    res, kw = post(body=zbody)
    check("the route answers 200 for zodiac", res.status_code == 200,
          res.status_code)
    zpd = product(kw)
    print("    product_data: %s" % json.dumps(zpd, ensure_ascii=False))
    check("it is named as the profile, not a style report",
          "osmic" in zpd["name"] and "itchen" not in zpd["name"], zpd["name"])
    check("it carries the mazzin mark rather than a kitchen",
          zpd.get("images") == ["https://mazzin.com/static/brand/icon-512.png"],
          zpd.get("images"))
    check("  absolute, and a png Stripe will render",
          zpd["images"][0].startswith("https://")
          and zpd["images"][0].endswith(".png"), zpd["images"])
    zdisk = REPO + zpd["images"][0].split("mazzin.com", 1)[1]
    check("  and the file is on disk for the deploy to publish",
          os.path.isfile(zdisk), zdisk)
    with Image.open(zdisk) as mark:
        check("  square, and big enough for Stripe's tile",
              mark.size == (512, 512), str(mark.size))
    check("kitchen's image is untouched by any of it",
          product(post()[1]).get("images")
          == ["https://mazzin.com/static/creative_src/stripe_tile.png"],
          product(post()[1]).get("images"))

    print("\n--- the config copies agree ---")
    live = json.load(open(os.path.join(REPO, "funnels/kitchen.json")))
    served = json.load(open(os.path.join(REPO, "static/funnels/kitchen.json")))
    check("funnels/ and static/funnels/ are the same file", live == served)
    check("both carry the product name",
          live["checkout"]["product_name"]
          == served["checkout"]["product_name"]
          == "Your Kitchen Style Report — the mistakes that cost $4,000+")
    check("both carry the product image",
          live["checkout"]["product_image"]
          == served["checkout"]["product_image"]
          == "/static/creative_src/stripe_tile.png",
          (live["checkout"]["product_image"],
           served["checkout"]["product_image"]))

    print("\n--- the rounds a clock answered, on the way to the purchase ---")
    # The one field on this payload the server is not allowed to be relaxed
    # about. The tag scores and the tapped images steer copy, so a body that
    # sends nonsense there is dropped and the sale goes through; this list is
    # the difference between a report that tells somebody a round ran out on
    # them and one that tells them they answered it, and nothing on this side
    # can check it against the run — the card a clock picks is a card they
    # could have picked themselves. So the shape is checked, and a body whose
    # shape is wrong is refused rather than half-believed.
    brain = config.load_funnel("brain")
    brain_ids = [st["id"] for st in brain["swipe"]["steps"]]
    brain_body = {
        "funnel": "brain",
        "session_id": "11111111-2222-4333-8444-555555555556",
        "result_style": brain["styles"][0]["id"],
        "tag_scores": {"mem_hit": 3},
    }

    def brain_post(timed_out):
        body = dict(brain_body)
        if timed_out is not _ABSENT:
            body["timed_out"] = timed_out
        return post(body=body)

    res, kw = brain_post(["spa2", "ink"])
    check("a valid list is accepted", res.status_code == 200, res.status_code)
    check("  and rides Stripe's metadata as the ids themselves",
          kw["metadata"].get("timed_out") == "spa2,ink",
          kw["metadata"].get("timed_out"))
    check("  which the webhook reads back and re-checks from scratch",
          payments._read_timed_out(brain, kw["metadata"]["timed_out"])
          == ["spa2", "ink"],
          str(payments._read_timed_out(brain, kw["metadata"]["timed_out"])))
    check("a body naming none sends no key at all rather than an empty one",
          "timed_out" not in brain_post(_ABSENT)[1]["metadata"],
          sorted(brain_post(_ABSENT)[1]["metadata"]))
    check("an id this funnel does not have is a 400",
          brain_post(["spa2", "not_a_step"])[0].status_code == 400,
          brain_post(["spa2", "not_a_step"])[0].status_code)
    check("  and so is one that is not a string",
          brain_post(["spa2", 7])[0].status_code == 400,
          brain_post(["spa2", 7])[0].status_code)
    check("the same id twice is a 400",
          brain_post(["spa2", "spa2"])[0].status_code == 400,
          brain_post(["spa2", "spa2"])[0].status_code)
    check("something that is not a list at all is a 400",
          brain_post("spa2")[0].status_code == 400
          and brain_post({"spa2": True})[0].status_code == 400,
          brain_post("spa2")[0].status_code)
    check("  a list longer than the walk itself is a 400",
          brain_post(brain_ids + ["spa2"])[0].status_code == 400,
          brain_post(brain_ids + ["spa2"])[0].status_code)
    check("  and every id in the walk at once is not",
          brain_post(brain_ids)[0].status_code == 200,
          brain_post(brain_ids)[0].status_code)

    # And the far end: what the webhook hands `start_report` is what the
    # stored report draws its crosses from.
    import database
    real = (database.execute, database.query_all, database.query_one)
    database.execute = lambda *a, **kw: None
    database.query_all = lambda *a, **kw: []
    database.query_one = lambda *a, **kw: None
    try:
        import reports
        row = reports.start_report(
            9901, "brain", brain["styles"][0]["id"], {"mem_hit": 3},
            timed_out=payments._read_timed_out(brain, "spa2,ink"))
        check("and the report stores them where the page draws crosses from",
              (row.get("visuals") or {}).get("timed_out") == ["spa2", "ink"],
              str((row.get("visuals") or {}).get("timed_out")))
    finally:
        database.execute, database.query_all, database.query_one = real

    print("\n%d checks, %d failed" % (checks[0], len(fails)))
    for f in fails:
        print("  FAIL " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
