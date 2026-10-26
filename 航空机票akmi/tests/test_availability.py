from __future__ import annotations

import unittest

from main import _parse_availability


HTML = """
<ul><li class="price_list section_list_item">
  <button class="bul_air_info" data-dispflightnumber="TW303"></button>
  <div class="segmentInfo" data-aircraftprovider="B737-8" data-flightdate="2030-06-18"
       data-departureairportcode="ICN" data-departuretime="10:50"
       data-arrivalairportcode="KIX" data-arrivaltime="13:00" data-journeytime="02:10" data-stops="0"></div>
  <div class="rate_box"><input class="tripInfo" data-faretype="SmartFare">
    <div class="segmentInfo" data-bookingclass="W"></div><div class="rate_price">KRW 302,400 3석</div>
    <div>무료 위탁수하물 : 15KG</div>
  </div>
  <div class="rate_box soldout"><input class="tripInfo" data-faretype="EventFare">
    <div class="segmentInfo" data-bookingclass="D"></div><div class="rate_price">매진</div>
    <div>무료 위탁수하물 : 없음</div>
  </div>
</li></ul>
"""


class AvailabilityParserTests(unittest.TestCase):
    def test_parses_flight_and_fare_rows(self):
        flights = _parse_availability(HTML)
        self.assertEqual(len(flights), 1)
        self.assertEqual(flights[0]["flight_number"], "TW303")
        self.assertEqual(flights[0]["departure"], {"airport": "ICN", "time": "10:50"})
        self.assertEqual(flights[0]["arrival"], {"airport": "KIX", "time": "13:00"})
        self.assertEqual(flights[0]["fares"][0]["price"], 302400)
        self.assertEqual(flights[0]["fares"][0]["seats"], 3)
        self.assertFalse(flights[0]["fares"][0]["sold_out"])
        self.assertTrue(flights[0]["fares"][1]["sold_out"])

    def test_empty_inventory_is_not_invented(self):
        self.assertEqual(_parse_availability("<div>조회된 여정이 없습니다.</div>"), [])


if __name__ == "__main__":
    unittest.main()
