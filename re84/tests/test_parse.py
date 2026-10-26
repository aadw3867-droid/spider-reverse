"""Offline regression tests for main.py (no network, no secrets).

    python -m unittest discover -s tests -v
    python tests/test_parse.py
"""

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import main as M

SAMPLE = os.path.join(ROOT, "js_reverse_cache", "airbounds_sample.json")


class TestParseOffers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(SAMPLE, encoding="utf-8") as fh:
            cls.doc = json.load(fh)
        cls.offers = M.parse_offers(cls.doc)

    def test_offers_non_empty(self):
        self.assertGreater(len(self.offers), 0)

    def test_required_fields(self):
        for o in self.offers:
            self.assertIn("fareFamily", o)
            self.assertIn("total", o)
            self.assertIn("currency", o)
            self.assertIn("segments", o)
            self.assertIsInstance(o["segments"], list)
            self.assertGreater(len(o["segments"]), 0)

    def test_sorted_by_total(self):
        totals = [o["total"] for o in self.offers if o.get("total") is not None]
        self.assertEqual(totals, sorted(totals))

    def test_cheapest_flag_present(self):
        self.assertTrue(any(o.get("cheapest") for o in self.offers))

    def test_currency_thb(self):
        self.assertEqual(self.offers[0]["currency"], "THB")

    def test_segment_enrichment(self):
        seg = self.offers[0]["segments"][0]
        for key in ("flightId", "flightNumber", "from", "to", "departure", "arrival"):
            self.assertIn(key, seg)
        self.assertTrue(seg["flightNumber"].startswith("PG"))
        self.assertEqual(len(seg["from"]), 3)
        self.assertEqual(len(seg["to"]), 3)

    def test_known_sample_values(self):
        cheapest = self.offers[0]
        self.assertEqual(cheapest["total"], 2830)
        self.assertEqual(cheapest["base"], 2600)
        self.assertEqual(cheapest["taxes"], 130)
        self.assertEqual(cheapest["bookingClass"], "Q")
        self.assertEqual(cheapest["seatsLeft"], 2)

    def test_groups_and_bounds_counts(self):
        groups = self.doc["data"]["airBoundGroups"]
        self.assertEqual(len(groups), 20)
        self.assertEqual(len(groups[0]["airBounds"]), 3)

    def test_baggage_parsed(self):
        self.assertTrue(any(o.get("baggage") for o in self.offers))

    def test_empty_doc(self):
        self.assertEqual(M.parse_offers({}), [])
        self.assertEqual(M.parse_offers({"data": {}}), [])


class TestFormatting(unittest.TestCase):
    def test_fmt_duration(self):
        self.assertEqual(M.fmt_duration(0), "?")
        self.assertEqual(M.fmt_duration(None), "?")
        self.assertEqual(M.fmt_duration(5700), "1h35m")
        self.assertEqual(M.fmt_duration(1800), "30m")


class TestFilterOffers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows = [
            {"fareFamily": "PGPROMO", "cabin": "eco", "total": 100},
            {"fareFamily": "PGSAVER", "cabin": "eco", "total": 200},
            {"fareFamily": "PGPROMO", "cabin": "business", "total": 300},
            {"fareFamily": "PGBLUE", "cabin": "business", "total": 400},
        ]
        cls.rows = rows

    def test_no_filter(self):
        self.assertEqual(len(M.filter_offers(self.rows)), 4)

    def test_fare_code_case_insensitive(self):
        got = M.filter_offers(self.rows, fare_code="pgsaver")
        self.assertEqual([o["total"] for o in got], [200])

    def test_cabin(self):
        got = M.filter_offers(self.rows, cabin="BUSINESS")
        self.assertEqual([o["total"] for o in got], [300, 400])

    def test_both(self):
        got = M.filter_offers(self.rows, fare_code="PGBLUE", cabin="business")
        self.assertEqual([o["total"] for o in got], [400])

    def test_no_match(self):
        self.assertEqual(M.filter_offers(self.rows, fare_code="PGNOPE"), [])


class TestFareFamilyConstants(unittest.TestCase):
    def test_commercial_families_are_the_two_valid_ones(self):
        self.assertEqual(set(M.FARE_FAMILIES), {"PGPROMO", "PGFLEX"})

    def test_fare_codes_are_sub_families(self):
        self.assertEqual(set(M.FARE_CODES),
                         {"PGPROMO", "PGSAVER", "PGFREEDOM", "PGBLUE"})

    def test_no_overlap_between_wrongly_used_codes(self):
        for bad in ("PGSAVER", "PGFREEDOM", "PGBLUE"):
            self.assertNotIn(bad, M.FARE_FAMILIES)

    def test_pgblue_is_business_only(self):
        self.assertEqual(M.cabin_for_code("PGBLUE"), "business")
        self.assertEqual(M.cabin_for_code("pgblue"), "business")

    def test_eco_codes(self):
        for code in ("PGPROMO", "PGSAVER", "PGFREEDOM"):
            self.assertEqual(M.cabin_for_code(code), "eco")

    def test_unknown_code_has_no_cabin(self):
        self.assertIsNone(M.cabin_for_code("PGBOGUS"))
        self.assertIsNone(M.cabin_for_code(None))


class TestTokenGuards(unittest.TestCase):
    def test_empty_seed_rejected(self):
        with self.assertRaises(M.Reese84Error):
            M.renew_token("")

    def test_cli_without_seed(self):
        # disable the on-disk seed cache so this exercises the no-seed path
        old_cache = os.environ.get("RE84_SEED_CACHE")
        old_seed = os.environ.get("RE84_SEED")
        os.environ["RE84_SEED_CACHE"] = ""
        os.environ.pop("RE84_SEED", None)
        try:
            import importlib
            importlib.reload(M)
            rc = M.main(["--check-token"])
        finally:
            if old_cache is None:
                os.environ.pop("RE84_SEED_CACHE", None)
            else:
                os.environ["RE84_SEED_CACHE"] = old_cache
            if old_seed is not None:
                os.environ["RE84_SEED"] = old_seed
            importlib.reload(M)
        self.assertEqual(rc, 2)

    def test_cli_rejects_return_before_departure(self):
        rc = M.main(["--date", "2026-11-20", "--return-date", "2026-11-15"])
        self.assertEqual(rc, 2)

    def test_install_cookie_domain(self):
        s = M._session()
        try:
            M.install_cookie(s, "3:abc:", "bangkokair.com")
            names = {c.name: c for c in s.cookies.jar}
            self.assertIn("reese84", names)
            self.assertTrue(names["reese84"].domain.lstrip(".").endswith("bangkokair.com"))
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
