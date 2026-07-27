import json
import tempfile
import unittest
from pathlib import Path

from refresh_flights import (
    DESTINATIONS,
    has_unpriced_qualifying_itinerary,
    load_run_results,
    qualifying_records,
)


def record(
    price: int = 10000,
    outbound_minutes: int = 1020,
    inbound_minutes: int = 1020,
    outbound_stops: int = 1,
    inbound_stops: int = 1,
) -> dict:
    return {
        "price": price,
        "currency": "CNY",
        "cabin_class": "economy",
        "duration_minutes": outbound_minutes,
        "return_duration_minutes": inbound_minutes,
        "stops": outbound_stops,
        "return_stops": inbound_stops,
    }


class QualifyingRecordsTest(unittest.TestCase):
    def test_accepts_exact_duration_boundary(self) -> None:
        self.assertEqual(len(qualifying_records([record()])), 1)

    def test_rejects_duration_above_boundary(self) -> None:
        self.assertEqual(
            qualifying_records([record(outbound_minutes=1021)]),
            [],
        )

    def test_rejects_two_stops_in_either_direction(self) -> None:
        self.assertEqual(
            qualifying_records([record(inbound_stops=2)]),
            [],
        )

    def test_sorts_by_price_before_duration(self) -> None:
        records = [
            record(price=12000, outbound_minutes=900),
            record(price=10000, outbound_minutes=1020),
        ]
        self.assertEqual(qualifying_records(records)[0]["price"], 10000)

    def test_identifies_qualifying_route_without_price(self) -> None:
        value = record()
        value["price"] = None
        value["currency"] = None
        self.assertTrue(has_unpriced_qualifying_itinerary([value]))

    def test_cached_results_require_every_destination(self) -> None:
        run_dir = Path(tempfile.mkdtemp(prefix="flight-run-test-"))
        destination = next(iter(DESTINATIONS))
        path = run_dir / "missing.json"
        path.write_text(
            json.dumps({"destination": destination}),
            encoding="utf-8",
        )
        with self.assertRaises(RuntimeError):
            load_run_results(run_dir)


if __name__ == "__main__":
    unittest.main()
