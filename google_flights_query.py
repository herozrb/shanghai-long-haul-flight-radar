from __future__ import annotations

import argparse
import json
from typing import Any

from fli.models import SeatType, TripType
from fli.models.google_flights.base import Airport, MaxStops, SortBy
from fli.models.google_flights.flights import (
    FlightSearchFilters,
    FlightSegment,
    PassengerInfo,
)
from fli.search import SearchFlights


def airport_groups(value: str) -> list[list[Any]]:
    groups = []
    for code in value.split(","):
        code = code.strip().upper()
        if not code:
            continue
        groups.append([Airport[code], 0])
    if not groups:
        raise ValueError("At least one airport is required")
    return groups


def airline_name(result: Any) -> str:
    if result.primary_airline_name:
        return str(result.primary_airline_name)
    names = []
    for leg in result.legs:
        name = str(leg.airline.value) if leg.airline else ""
        if name and name not in names:
            names.append(name)
    return "、".join(names)


def flight_number(leg: Any) -> str:
    code = str(leg.airline.name).removeprefix("_") if leg.airline else ""
    return f"{code}{leg.flight_number}" if leg.flight_number else ""


def segments(result: Any) -> list[dict]:
    output = []
    for leg in result.legs:
        output.append(
            {
                "flight_number": flight_number(leg),
                "origin_iata": str(leg.departure_airport.name),
                "destination_iata": str(leg.arrival_airport.name),
                "departure": leg.departure_datetime.isoformat(timespec="minutes"),
                "arrival": leg.arrival_datetime.isoformat(timespec="minutes"),
                "duration_minutes": int(leg.duration),
            }
        )
    return output


def layovers(result: Any) -> tuple[list[str], list[int]]:
    codes = []
    minutes = []
    for layover in result.layovers or []:
        codes.append(str(layover.airport.name))
        minutes.append(int(layover.duration))
    return codes, minutes


def normalize(outbound: Any, inbound: Any) -> dict:
    outbound_layovers, outbound_layover_minutes = layovers(outbound)
    inbound_layovers, inbound_layover_minutes = layovers(inbound)
    price = outbound.price if outbound.price is not None else inbound.price
    currency = outbound.currency if outbound.currency else inbound.currency
    return {
        "flight_number": flight_number(outbound.legs[0]),
        "airline": airline_name(outbound),
        "origin_iata": str(outbound.legs[0].departure_airport.name),
        "destination_iata": str(outbound.legs[-1].arrival_airport.name),
        "scheduled_departure": outbound.legs[0].departure_datetime.isoformat(),
        "scheduled_arrival": outbound.legs[-1].arrival_datetime.isoformat(),
        "price": float(price) if price is not None else None,
        "currency": str(currency) if currency else None,
        "stops": int(outbound.stops),
        "duration_minutes": int(outbound.duration),
        "source": "google_flights",
        "segments": segments(outbound),
        "layover_cities": outbound_layovers,
        "layover_minutes": outbound_layover_minutes,
        "max_layover_minutes": max(outbound_layover_minutes, default=0),
        "trip_type": "round_trip",
        "cabin_class": "economy",
        "return_flight_number": flight_number(inbound.legs[0]),
        "return_airline": airline_name(inbound),
        "return_departure": inbound.legs[0].departure_datetime.isoformat(),
        "return_arrival": inbound.legs[-1].arrival_datetime.isoformat(),
        "return_stops": int(inbound.stops),
        "return_duration_minutes": int(inbound.duration),
        "return_segments": segments(inbound),
        "return_layover_cities": inbound_layovers,
        "return_layover_minutes": inbound_layover_minutes,
        "return_max_layover_minutes": max(inbound_layover_minutes, default=0),
    }


def search(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str,
    max_duration_minutes: int,
    max_stops: int,
    top_n: int,
) -> list[dict]:
    stops = {
        0: MaxStops.NON_STOP,
        1: MaxStops.ONE_STOP_OR_FEWER,
        2: MaxStops.TWO_OR_FEWER_STOPS,
    }[max_stops]
    flight_segments = [
        FlightSegment(
            departure_airport=airport_groups(origin),
            arrival_airport=airport_groups(destination),
            travel_date=departure_date,
        ),
        FlightSegment(
            departure_airport=airport_groups(destination),
            arrival_airport=airport_groups(origin),
            travel_date=return_date,
        ),
    ]
    filters = FlightSearchFilters(
        passenger_info=PassengerInfo(adults=1),
        flight_segments=flight_segments,
        seat_type=SeatType.ECONOMY,
        stops=stops,
        sort_by=SortBy.CHEAPEST,
        trip_type=TripType.ROUND_TRIP,
        max_duration=max_duration_minutes,
    )
    raw_results = SearchFlights().search(
        filters,
        top_n=top_n,
        currency="CNY",
    )
    if raw_results is None:
        raise RuntimeError("Google Flights returned no response")
    if not raw_results:
        return []
    records = []
    for item in raw_results:
        if not isinstance(item, tuple) or len(item) != 2:
            continue
        records.append(normalize(item[0], item[1]))
    return records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-airports", required=True)
    parser.add_argument("--to-airports", required=True)
    parser.add_argument("--departure-date", required=True)
    parser.add_argument("--return-date", required=True)
    parser.add_argument("--max-duration-minutes", type=int, required=True)
    parser.add_argument("--max-stops", type=int, required=True)
    parser.add_argument("--top-n", type=int, default=8)
    args = parser.parse_args()
    records = search(
        args.from_airports,
        args.to_airports,
        args.departure_date,
        args.return_date,
        args.max_duration_minutes,
        args.max_stops,
        args.top_n,
    )
    print(json.dumps(records, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
