"""End-to-end stability harness for the Bangkok Airways Reese84 pipeline.

Mints ONE seed, then drives the full chain repeatedly across a matrix of
cases (one-way / round-trip, multiple routes, fare families, sub fare codes,
cabins, passenger counts) using a SINGLE renewal chain.

A case only counts as passed when the API returns real offers AND no
`errors` envelope was produced.

Usage:
    python stability.py [--cases 24] [--headful] [--seed <token>] [--json]
"""

import argparse
import datetime
import json
import os
import random
import sys
import time

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import main as m


ROUTES = [
    ("BKK", "HKT"), ("BKK", "CNX"), ("BKK", "USM"),
    ("BKK", "TDX"), ("BKK", "KBV"), ("HKT", "CNX"),
]
BIZ_ROUTES = [("BKK", "USM")]
FAMILIES = ["PGPROMO", "PGFLEX"]
FARE_CODES = [None, "PGPROMO", "PGSAVER", "PGFREEDOM", "PGBLUE"]
PAX = [1, 2, 3]


def _cabin_pair(rng):
    """Pick a (fareCode, cabin) pair that can actually co-exist.

    PGBLUE is business-only and only sold on the ATR routes, so we only pair
    it with those routes; eco codes are the opposite.
    """
    code = rng.choice(FARE_CODES)
    if code == "PGBLUE":
        return code, "business"
    if code:
        cabin = m.cabin_for_code(code)
        if rng.random() < 0.12:
            cabin = None
        return code, cabin
    return None, rng.choice([None, None, "eco"])


def build_cases(n):
    rng = random.Random(20261025)
    base = datetime.date.today() + datetime.timedelta(days=21)
    cases = []
    for i in range(n):
        code, cabin = _cabin_pair(rng)
        pool = BIZ_ROUTES if code == "PGBLUE" else ROUTES
        origin, dest = rng.choice(pool)
        rt = rng.random() < 0.35
        date = (base + datetime.timedelta(days=rng.randint(-7, 28))).isoformat()
        ret_date = None
        if rt:
            ret_date = (base + datetime.timedelta(days=rng.randint(1, 30))).isoformat()
            if ret_date < date:
                ret_date = date
        cases.append({
            "name": "case-%02d" % (i + 1),
            "origin": origin, "dest": dest, "date": date, "returnDate": ret_date,
            "fare": rng.choice(FAMILIES),
            "fareCode": code,
            "cabin": cabin,
            "pax": rng.choice(PAX),
            "roundTrip": rt,
        })
    return cases


def run_case(sess, access_token, token, c):
    doc = m.search_air_bounds(
        sess, access_token, token, c["origin"], c["dest"], c["date"],
        fare_family=c["fare"], passengers=c["pax"], return_date=c["returnDate"])
    raw = m.parse_offers(doc)
    rt = doc.get("_roundTrip")
    if rt:
        rt["outbound"] = m.filter_offers(rt["outbound"], c["fareCode"], c["cabin"])
    return doc, m.filter_offers(raw, c["fareCode"], c["cabin"]), len(raw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=int, default=24)
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--seed", default=None)
    ap.add_argument("--seed-file", default="_seed_tmp.txt")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    seed = args.seed or os.environ.get("RE84_SEED", "").strip()
    if not seed and args.seed_file and os.path.exists(args.seed_file):
        seed = open(args.seed_file, encoding="utf-8").read().strip()
    if not seed:
        print("no seed; minting one with Camoufox ...", file=sys.stderr)
        from mint_seed import mint
        seed = mint(headless=not args.headful)
        if not seed:
            print("fatal: mint produced no seed", file=sys.stderr)
            return 2
    print("seed: len=%d" % len(seed), file=sys.stderr)

    sess = m._session()
    token = seed
    secs = 0
    results = []
    t_start = time.time()
    renew_n = 0
    renew_rejections = 0
    try:
        for attempt in (1, 2):
            token, secs, domain = m.renew_token(token, sess)
            renew_n += 1
            print("[renew #%d] len=%d renewInSec=%d domain=%s"
                  % (renew_n, len(token), secs, domain), file=sys.stderr)
            m.install_cookie(sess, token, domain)
            ok, status, size = m.verify_token(sess)
            print("[verify] ok=%s status=%d size=%d" % (ok, status, size), file=sys.stderr)
            if ok:
                break
            renew_rejections += 1
            if attempt == 2:
                print("fatal: renewal chain broken", file=sys.stderr)
                return 3

        at, exp = m.get_access_token(sess, token)
        print("[oauth] len=%d expires_in=%d" % (len(at), exp), file=sys.stderr)

        for c in build_cases(args.cases):
            st = time.time()
            rec = {k: c[k] for k in ("name", "origin", "dest", "date", "returnDate",
                                     "fare", "fareCode", "cabin", "pax", "roundTrip")}
            attempts = 0
            ok = False
            last_err = ""
            filtered = 0
            rawn = 0
            while attempts < 3 and not ok:
                attempts += 1
                try:
                    doc, rows, raw_total = run_case(sess, at, token, c)
                    raw = doc.get("_roundTrip")
                    filtered = len(rows)
                    rawn = raw_total
                    if raw:
                        rec["offers_outbound"] = len(raw.get("outbound") or [])
                        rec["selectedBoundId"] = raw.get("selectedBoundId")
                    rec["offers"] = filtered
                    rec["raw_offers"] = raw_total
                    ok = True
                except Exception as e:
                    last_err = "%s" % e
                    time.sleep(2 * attempts)
            rec["ok"] = ok
            rec["attempts"] = attempts
            rec["latency"] = round(time.time() - st, 2)
            rec["error"] = last_err if not ok else None
            results.append(rec)

            tag = "%s->%s %s %s%s pax=%d" % (
                c["origin"], c["dest"], c["date"], c["fare"],
                " RT" if c["roundTrip"] else "", c["pax"])
            flt = "+".join(x for x in (c["fareCode"], c["cabin"]) if x) or "-"
            if ok:
                print("[%s] %-46s flt=%-16s offers=%d/%d %.1fs"
                      % (c["name"], tag, flt, filtered, rawn, rec["latency"]),
                      file=sys.stderr)
            else:
                print("[%s] %-46s flt=%-16s FAILED(%d): %s"
                      % (c["name"], tag, flt, attempts, last_err[:120]), file=sys.stderr)
    except m.Reese84Error as e:
        print("fatal (renew/oauth): %s" % e, file=sys.stderr)
        return 4
    finally:
        sess.close()

    total = len(results)
    passed = sum(1 for r in results if r["ok"])
    failed = total - passed
    empty = sum(1 for r in results if r["ok"] and r.get("raw_offers", 0) == 0)
    avg_lat = sum(r["latency"] for r in results) / max(1, total)
    retries = sum(r["attempts"] - 1 for r in results)

    summary = {
        "total_cases": total, "passed": passed, "failed": failed,
        "empty_result_cases": empty,
        "avg_latency_s": round(avg_lat, 2), "retries": retries,
        "renew_calls": renew_n, "renew_rejections": renew_rejections,
        "seed_len": len(seed), "final_renew_in_sec": secs,
        "elapsed_s": round(time.time() - t_start, 1),
        "results": results,
    }

    print("=" * 66, file=sys.stderr)
    print("SUMMARY: %d/%d passed | %d empty | avg %.1fs | %d retries | "
          "%d renew | %d rejections"
          % (passed, total, empty, avg_lat, retries, renew_n, renew_rejections),
          file=sys.stderr)
    print("elapsed %.1fs | final renewInSec=%d" % (summary["elapsed_s"], secs),
          file=sys.stderr)
    if failed:
        print("FAILED:", file=sys.stderr)
        for r in results:
            if not r["ok"]:
                print("  %s %s->%s %s: %s" % (r["name"], r["origin"], r["dest"],
                                              r["date"], r["error"]), file=sys.stderr)

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
