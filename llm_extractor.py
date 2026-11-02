"""Universal itinerary extraction via the OpenAI API, strict JSON schema.

Primary extraction path for parser.parse_itinerary_pdf. Falls back to the regex
parsers in parser.py whenever this returns None: missing API key, network/API
error, or a malformed response. Never raises out of extract_with_llm — the
caller always gets either a valid dict or None.
"""
import json
import os
from datetime import date

import truststore
truststore.inject_into_ssl()  # trust the Windows cert store (corporate proxy TLS)

from openai import OpenAI

DEFAULT_MODEL = "gpt-5-mini"
REQUEST_TIMEOUT_SECONDS = 12

TRIP_SCHEMA = {
    "type": "object",
    "properties": {
        "traveler_name": {"type": ["string", "null"]},
        "origin": {"type": ["string", "null"]},
        "destination": {"type": ["string", "null"]},
        "start_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
        "end_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
        "departure_time": {"type": ["string", "null"], "description": "HH:MM, 24-hour, local time of the first departure, on start_date"},
        "arrival_time": {"type": ["string", "null"], "description": "HH:MM, 24-hour, local time of the final arrival, on end_date"},
        "start_arrival_time": {"type": ["string", "null"], "description": "HH:MM, 24-hour. Only for multi-leg/round trips: the arrival time of the outbound leg (its landing time, whether that's the same calendar day as start_date or the next day on an overnight flight). Null for single-leg trips where start_date == end_date."},
        "end_departure_time": {"type": ["string", "null"], "description": "HH:MM, 24-hour. Only for multi-leg/round trips: the departure time of the final/return leg (when it takes off, whether that's the same calendar day as end_date or the day before on an overnight flight). Null for single-leg trips where start_date == end_date."},
        "airline": {"type": ["string", "null"]},
        "pnr": {"type": ["string", "null"], "description": "e.g. 'ABC123' or, if the outbound and return legs have different PNRs, 'ABC123 / XYZ789'"},
        "price": {"type": ["string", "null"], "description": "The total fare/amount paid, with its currency symbol or code, e.g. '₹8,450' or 'INR 8,450' or 'USD 210.00'"},
        "booking_source": {"type": ["string", "null"], "description": "The booking platform/agency/app used to book this, based on branding or mentions in the text, e.g. 'MyBiz', 'MakeMyTrip', 'Yatra', 'Cleartrip', 'EaseMyTrip', 'Booking.com', or '<Airline> (Direct)' if booked straight from the airline with no third-party agency involved. Null if it can't be determined."},
        "confident": {
            "type": "boolean",
            "description": "false if traveler_name or the dates could not be found with confidence",
        },
    },
    "required": [
        "traveler_name", "origin", "destination", "start_date", "end_date",
        "departure_time", "arrival_time", "start_arrival_time", "end_departure_time",
        "airline", "pnr", "price", "booking_source", "confident",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = f"""You extract structured trip data from airline/travel-agent itinerary \
or e-ticket text (emails, PDFs converted to text, GDS receipts, etc). Today's date is \
{date.today().isoformat()}.

Rules:
- Only report fields you can actually find in the text. Use null for anything absent \
or ambiguous — never invent a name, date, city, or PNR.
- traveler_name: the passenger's full name in normal "First Last" form (fix ALL-CAPS \
or "LAST/FIRST" formatting).
- origin/destination: the trip's overall route in plain city names. For a round trip \
just the two cities (e.g. origin "Mumbai", destination "Bengaluru"). For a multi-city \
trip, destination may list the other cities visited joined with " -> " in order.
- start_date/end_date: the trip's earliest and latest travel dates found, as YYYY-MM-DD. \
Ignore unrelated dates like "booked on" / issue date / ticketing date.
- departure_time: the clock time (HH:MM, 24-hour) of the very first departure, on start_date.
- arrival_time: the clock time (HH:MM, 24-hour) of the very final arrival, on end_date.
- start_arrival_time: for round trips/multi-leg tickets where start_date != end_date, the \
clock time the outbound leg actually lands - report it even if it lands the next calendar \
day (an overnight/red-eye flight). Only null for single-leg trips (start_date == end_date).
- end_departure_time: for round trips/multi-leg tickets where start_date != end_date, the \
clock time the return/final leg actually takes off - report it even if that's the day \
*before* end_date (an overnight flight that lands after midnight). Only null for \
single-leg trips (start_date == end_date). Don't withhold this just because the takeoff \
date differs from end_date; that's expected for overnight flights, not a reason for null.
- airline: the operating airline name, if present.
- pnr: a booking reference / PNR code, if present. Round trips and multi-leg tickets \
often show a *different* PNR per leg — when you see more than one distinct PNR, report \
ALL of them in leg order (outbound first, then return/next legs), joined by " / ", e.g. \
"EAQ3RH / EALREX". If every leg shares the same single PNR, just report that one value. \
Only use null if no PNR appears anywhere in the text.
- price: the total fare or amount paid for the booking, including its currency symbol or \
code (e.g. "₹8,450", "INR 8,450", "USD 210.00"). Prefer a grand/total amount over a \
per-passenger or per-leg breakdown if both are present. Null if no amount appears.
- booking_source: the booking platform/travel agency/app itself - e.g. "MyBiz", "MakeMyTrip", \
"Yatra", "Cleartrip", "EaseMyTrip", "Booking.com", "Expedia". Look for that brand name in \
logos-as-text, letterheads, footers, contact info (e.g. a "MakeMy Trip" support line), or \
booking-ID patterns. This is NEVER the traveler's employer or the corporate account name \
that owns the booking (a company name like "Netcore Private Limited" next to the booking \
details is the corporate account holder, not the booking platform - ignore it for this \
field). If the ticket is a plain airline e-ticket/GDS receipt with no third-party agency \
branding at all, use "<Airline> (Direct)", e.g. "IndiGo (Direct)". Null if you genuinely \
can't tell - don't guess a company name just because one appears in the text.
- confident: false if traveler_name is missing OR both dates are missing; true otherwise.
"""


def extract_with_llm(text, filename=None):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or not text.strip():
        return None

    model = os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)
    client = OpenAI(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS)

    user_content = f"Filename: {filename or 'unknown'}\n\n{text[:12000]}"

    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "trip_extraction",
                        "strict": True,
                        "schema": TRIP_SCHEMA,
                    },
                },
                # gpt-5-mini is a reasoning model - it doesn't reliably accept a
                # custom temperature, so we don't set one (the strict schema
                # above is what actually keeps output well-formed and stable).
                reasoning_effort="low",  # a strict-schema extraction task doesn't need deep reasoning
            )
            data = json.loads(response.choices[0].message.content)
            return _normalize(data)
        except Exception:
            if attempt == 0:
                continue
            return None
    return None


def _normalize(data):
    return {
        "traveler_name": data.get("traveler_name") or None,
        "origin": data.get("origin") or None,
        "destination": data.get("destination") or None,
        "start_date": data.get("start_date") or None,
        "end_date": data.get("end_date") or data.get("start_date") or None,
        "departure_time": data.get("departure_time") or None,
        "arrival_time": data.get("arrival_time") or None,
        "start_arrival_time": data.get("start_arrival_time") or None,
        "end_departure_time": data.get("end_departure_time") or None,
        "airline": data.get("airline") or None,
        "pnr": data.get("pnr") or None,
        "price": data.get("price") or None,
        "booking_source": data.get("booking_source") or None,
        "confident": bool(data.get("confident", False)),
    }
