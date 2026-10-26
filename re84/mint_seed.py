"""Mint ONE genuine reese84 seed token with a real (anti-detection) browser.

This is only needed once per seed lifetime. After that, `main.py` renews the token
with plain HTTP and never touches a browser again.

    python mint_seed.py                 # print token to stdout
    python mint_seed.py --out seed.txt  # also write it to a file

Requires: camoufox (python) + the Camoufox browser binary.
Set CAMOUFOX_EXECUTABLE_PATH if the binary is not auto-detected.
"""

import argparse
import json
import os
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

WEB = "https://digital.bangkokair.com"
PAGE = WEB + "/booking/availability/0"

DEFAULT_BIN = r"D:\develop_software\Camoufox\camoufox.exe"
DEFAULT_PROFILE = r"D:\develop_software\Camoufox\Profiles\default"


def _executable_path():
    env = os.environ.get("CAMOUFOX_EXECUTABLE_PATH")
    if env and os.path.exists(env):
        return env
    if os.path.exists(DEFAULT_BIN):
        return DEFAULT_BIN
    return None


def mint(headless=True, timeout_ms=45000, profile_dir=None, verbose=False):
    from camoufox.sync_api import Camoufox

    kwargs = {
        "headless": headless,
        "os": "windows",
        "locale": "en-US",
        "humanize": True,
        "geoip": False,
        "block_webrtc": False,
    }
    exe = _executable_path()
    if exe:
        kwargs["executable_path"] = exe
    if profile_dir:
        kwargs["persistent_context"] = True
        kwargs["user_data_dir"] = profile_dir

    if verbose:
        print("camoufox kwargs:", {k: v for k, v in kwargs.items() if k != "user_data_dir"},
              file=sys.stderr)

    with Camoufox(**kwargs) as browser:
        page = browser.new_page()
        page.goto(PAGE, wait_until="domcontentloaded", timeout=timeout_ms)
        # the interrogation runs after load; poll for the cookie
        deadline = 30
        token = None
        for _ in range(deadline):
            page.wait_for_timeout(1000)
            for c in page.context.cookies():
                if c.get("name") == "reese84" and "bangkokair" in (c.get("domain") or ""):
                    token = c.get("value")
                    break
            if token:
                break
        if not token and verbose:
            print("page title:", page.title(), file=sys.stderr)
            print("url:", page.url, file=sys.stderr)
        try:
            page.close()
        except Exception:
            pass
        return token


def validate(token, verbose=False):
    """Confirm the token is genuine: renewal must return renewInSec > 0."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from main import Reese84Error, renew_token
    try:
        new_tok, secs, dom = renew_token(token)
    except Reese84Error as e:
        if verbose:
            print("validate failed: %s" % e, file=sys.stderr)
        return None, 0, None
    return new_tok, secs, dom


def main(argv=None):
    ap = argparse.ArgumentParser(description="Mint a reese84 seed token with Camoufox")
    ap.add_argument("--out", default=None, help="write token to this file")
    ap.add_argument("--headful", action="store_true", help="show the browser window")
    ap.add_argument("--profile-dir", default=None)
    ap.add_argument("--no-validate", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    tok = mint(headless=not args.headful, profile_dir=args.profile_dir, verbose=args.verbose)
    if not tok:
        print("error: no reese84 cookie appeared", file=sys.stderr)
        return 1

    print("minted token: len=%d" % len(tok), file=sys.stderr)

    if not args.no_validate:
        new_tok, secs, dom = validate(tok, verbose=args.verbose)
        if not new_tok:
            print("error: minted token failed validation (renewInSec=0)", file=sys.stderr)
            return 2
        print("validated: renewInSec=%d domain=%s (using renewed token)" % (secs, dom),
              file=sys.stderr)
        tok = new_tok

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(tok)
        print("written to %s" % args.out, file=sys.stderr)
    else:
        print(tok)
    return 0


if __name__ == "__main__":
    sys.exit(main())
