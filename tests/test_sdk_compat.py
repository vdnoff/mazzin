#!/usr/bin/env python3
"""The one model call the report module makes, against two SDK generations.

anthropic 1.x dropped `temperature`, `top_p` and `top_k` from
`messages.create`; the live venv may be on 0.x or 1.x. So `reports._ask`
passes the temperature only where the signature has a slot for it — decided
once per process by inspecting the signature, with the TypeError as the
backstop for a wrapper the inspection cannot see through — and the funnel
generator never sends a sampling parameter at all.

No network, no key: three fake clients with three signatures.
"""
import importlib.util
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
ROOT = REPO

import reports                                  # noqa: E402

fails = []
checks = [0]


def check(label, ok, detail=""):
    checks[0] += 1
    if not ok:
        fails.append("%s %s" % (label, detail))
    print("  %-62s %s%s" % (label, "ok" if ok else "FAIL",
                            ("  " + str(detail)[:200]) if detail and not ok
                            else ""))


class Message:
    def __init__(self):
        self.content = [type("B", (), {"type": "text", "text": "hi"})()]
        self.stop_reason = "end_turn"


class OldSdk:
    """0.x: temperature is a named parameter."""

    def __init__(self):
        self.calls = []

    @property
    def messages(self):
        return self

    def create(self, *, model, max_tokens, messages, system=None,
               temperature=None, top_p=None, top_k=None, output_config=None):
        self.calls.append({"model": model, "temperature": temperature})
        return Message()


class NewSdk:
    """1.x: no sampling parameters, and no **kwargs to swallow one."""

    def __init__(self):
        self.calls = []

    @property
    def messages(self):
        return self

    def create(self, *, model, max_tokens, messages, system=None,
               output_config=None):
        self.calls.append({"model": model})
        return Message()


class Wrapped:
    """A **kwargs wrapper over a 1.x SDK: the signature says anything goes,
    the call underneath says no."""

    def __init__(self):
        self.calls = []

    @property
    def messages(self):
        return self

    def create(self, **kwargs):
        self.calls.append(dict(kwargs))
        if "temperature" in kwargs:
            raise TypeError("Messages.create() got an unexpected keyword "
                            "argument 'temperature'")
        return Message()


def reset():
    reports._SAMPLING["temperature"] = None


print("\n--- the decision is read off the signature, once ---")
reset()
old = OldSdk()
text, stop = reports._ask(old, "p", 100)
check("a 0.x SDK is handed the temperature",
      old.calls[0]["temperature"] == reports.TEMPERATURE
      and text == "hi" and stop == "end_turn", str(old.calls))
check("  and the decision is remembered as yes",
      reports._SAMPLING["temperature"] is True)
reset()
new = NewSdk()
text, stop = reports._ask(new, "p", 100)
check("a 1.x SDK is not — the call goes through with no TypeError",
      new.calls == [{"model": reports.config.ANTHROPIC_MODEL}]
      and text == "hi", str(new.calls))
check("  and the decision is remembered as no",
      reports._SAMPLING["temperature"] is False)
reports._ask(new, "p", 100)
check("  a second call does not ask again", len(new.calls) == 2)

print("\n--- the TypeError backstop ---")
reset()
wrapped = Wrapped()
text, stop = reports._ask(wrapped, "p", 100)
check("a **kwargs wrapper is tried with the temperature first",
      "temperature" in wrapped.calls[0])
check("  refused, and retried without it in the same call",
      len(wrapped.calls) == 2 and "temperature" not in wrapped.calls[1]
      and text == "hi", str(wrapped.calls))
check("  after which the process never sends it again",
      reports._SAMPLING["temperature"] is False
      and (reports._ask(wrapped, "p", 100), len(wrapped.calls))[1] == 3)


class Broken(Wrapped):
    def create(self, **kwargs):
        self.calls.append(dict(kwargs))
        raise TypeError("something else entirely")


reset()
broken = Broken()
try:
    reports._ask(broken, "p", 100)
    raised = False
except TypeError:
    raised = True
check("any other TypeError still goes straight up, once",
      raised and len(broken.calls) == 1)

print("\n--- the real SDK, whichever is installed ---")
reset()
try:
    import anthropic
    client = anthropic.Anthropic(api_key="not-a-key")
    accepts = reports._accepts_temperature(client)
    major = int(anthropic.__version__.split(".")[0])
    check("anthropic %s: temperature %s, as its signature says"
          % (anthropic.__version__, "passed" if accepts else "omitted"),
          accepts == (major < 1), "major=%d accepts=%s" % (major, accepts))
except ImportError:
    check("anthropic SDK not installed here — signature check skipped", True)
reset()

print("\n--- the generator sends no sampling parameter ---")
spec = importlib.util.spec_from_file_location(
    "make_funnel_t", os.path.join(ROOT, "scripts", "make_funnel.py"))
mf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mf)
SRC = open(os.path.join(ROOT, "scripts", "make_funnel.py"),
           encoding="utf-8").read()
check("make_funnel.py names no temperature, top_p, top_k or extra_body",
      not any(("%s=" % k) in SRC for k in ("temperature", "top_p", "top_k",
                                          "extra_body")))
gen = NewSdk()
mf._STRUCTURED["on"] = True
# A 1.x-shaped client must accept the generator's exact call: model,
# max_tokens, system, messages, output_config — and nothing else.
try:
    mf._ask(gen, "m", "German", '{"s0": "Hi"}', {"s0": "Hi"})
    accepted = True
except TypeError as exc:
    accepted = False
check("  and its call fits a 1.x signature exactly", accepted
      and gen.calls == [{"model": "m"}])
check("reports.py passes temperature in exactly one place, guarded",
      open(os.path.join(ROOT, "reports.py"), encoding="utf-8").read()
      .count("temperature=") == 0
      and open(os.path.join(ROOT, "reports.py"), encoding="utf-8").read()
      .count('kwargs["temperature"] = TEMPERATURE') == 1)

print("\n%d checks, %d failed" % (checks[0], len(fails)))
for f in fails:
    print("  FAIL " + f)
sys.exit(1 if fails else 0)
