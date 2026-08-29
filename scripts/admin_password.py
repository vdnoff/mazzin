#!/usr/bin/env python3
"""Turn an admin password into the line that goes in .env.

    cd ~/mazzin && python3 scripts/admin_password.py

It asks twice, prints the hash, and stores nothing anywhere. Paste the two
lines it prints into .env and reload the app:

    ADMIN_USER=...
    ADMIN_PASSWORD_HASH=pbkdf2_sha256$240000$...$...

The hashing itself lives in admin.py, imported here rather than reimplemented:
a generator and a verifier that are two pieces of code are two pieces of code
that can disagree, and the day they do is the day nobody can log in.

The password is read with `getpass`, so it is not echoed and does not reach
the shell history. Passing it as an argument is deliberately not supported —
that is a password in `ps` and in `~/.bash_history`.
"""
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import admin          # noqa: E402

MIN_LENGTH = 12


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if argv:
        print("usage: python3 scripts/admin_password.py    (no arguments)")
        print("A password on the command line is a password in your shell "
              "history.")
        return 2

    user = input("admin username: ").strip()
    if not user:
        print("no username, nothing written")
        return 1

    password = getpass.getpass("password: ")
    if len(password) < MIN_LENGTH:
        print("too short — %d characters minimum" % MIN_LENGTH)
        return 1
    if password != getpass.getpass("again: "):
        print("they do not match")
        return 1

    print()
    print("# paste into .env, then reload the app")
    print("ADMIN_USER=%s" % user)
    print("ADMIN_PASSWORD_HASH=%s" % admin.hash_password(password))
    return 0


if __name__ == "__main__":
    sys.exit(main())
