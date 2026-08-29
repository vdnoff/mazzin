#!/usr/bin/env python3
"""Record the control arm's page as tests/fixtures/variants_control.html.

Run this ONLY when the control arm is meant to change.

That file is the A/B's reference. test_variants.py walks the control arm with
a pinned Math.random — so the same eighteen taps deal the same cards every run
— and compares the whole rendered subtree against it. A copy edit that leaves
the node shape untouched fails there and nowhere else, which is the reason it
exists: the experiment is only worth reading if the arm it is measured against
did not move under it.

    python3 tests/record_variants_control.py

Regenerating this to turn a red suite green is how an A/B quietly loses its
control. If the baseline has to move, the commit that moves it should say what
changed on the control arm and why it was meant to.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

env = dict(os.environ, MAZZIN_RECORD_CONTROL="1")
sys.exit(subprocess.call([sys.executable,
                          os.path.join(HERE, "test_variants.py")], env=env))
