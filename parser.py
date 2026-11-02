"""Extracts traveler name, travel dates, and route from flight itinerary PDFs.

Handles three known formats (MakeMyTrip Biz emails, direct IndiGo bookings,
GDS/eTicket receipts) with a generic fallback for anything else. When a field
can't be extracted confidently, the trip is flagged `needs_review` so the UI
can prompt the uploader to fill it in via the edit form.
"""
import re
from datetime import date

import pdfplumber

MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
MONTH_NUM = {m: i + 1 for i, m in enumerate(MONTHS.split("|"))}

DATE4_RE = re.compile(rf"\b(\d{{1,2}}) ({MONTHS}) (\d{{4}})\b")
DATE2_RE = re.compile(rf"\b(\d{{1,2}}) ({MONTHS}) (\d{{2}})\b")

IATA_CITY = {
    "BOM": "Mumbai", "DEL": "New Delhi", "BLR": "Bengaluru", "MAA": "Chennai",
    "CCU": "Kolkata", "HYD": "Hyderabad", "PNQ": "Pune", "AMD": "Ahmedabad",
    "COK": "Kochi", "GOI": "Goa", "GOX": "Goa", "JAI": "Jaipur", "LKO": "Lucknow",
    "IXC": "Chandigarh", "PAT": "Patna", "GAU": "Guwahati", "IXR": "Ranchi",
    "TRV": "Thiruvananthapuram", "VNS": "Varanasi", "IDR": "Indore",
    "BBI": "Bhubaneswar", "IXZ": "Port Blair", "STV": "Surat", "NAG": "Nagpur",
    "VGA": "Vijayawada", "VTZ": "Visakhapatnam", "IXM": "Madurai", "IXE": "Mangalore",
    "RPR": "Raipur", "IXA": "Agartala", "IXB": "Bagdogra", "SXR": "Srinagar",
    "IXJ": "Jammu", "ATQ": "Amritsar", "UDR": "Udaipur", "BHO": "Bhopal", "IXL": "Leh",
    "BKK": "Bangkok", "DMK": "Bangkok", "SIN": "Singapore", "DXB": "Dubai",
    "AUH": "Abu Dhabi", "DOH": "Doha", "KUL": "Kuala Lumpur", "CGK": "Jakarta",
    "LHR": "London", "LGW": "London", "JFK": "New York", "EWR": "New York",
    "IAD": "Washington", "ORD": "Chicago", "SFO": "San Francisco", "LAX": "Los Angeles",
    "YYZ": "Toronto", "HKG": "Hong Kong", "ICN": "Seoul", "NRT": "Tokyo", "HND": "Tokyo",
    "CDG": "Paris", "AMS": "Amsterdam", "FRA": "Frankfurt", "IST": "Istanbul",
    "CMB": "Colombo", "KTM": "Kathmandu", "MLE": "Male", "MNL": "Manila",
    "SYD": "Sydney", "MEL": "Melbourne", "AKL": "Auckland", "ZRH": "Zurich",
    "MUC": "Munich", "BRU": "Brussels", "MXP": "Milan", "BOS": "Boston",
    "SEA": "Seattle", "ATL": "Atlanta", "DFW": "Dallas", "IAH": "Houston",
    "MIA": "Miami", "YVR": "Vancouver", "JNB": "Johannesburg", "CAI": "Cairo",
    "RUH": "Riyadh", "JED": "Jeddah", "KWI": "Kuwait City", "MCT": "Muscat", "BAH": "Manama",
}

KNOWN_AIRLINES = [
    "IndiGo", "Air India", "Akasa Air", "SpiceJet", "Vistara", "GoAir", "Go First",
    "AirAsia", "Etihad Airways", "Emirates", "Qatar Airways", "Singapore Airlines",
    "Lufthansa", "British Airways", "United Airlines", "Delta Air Lines",
    "American Airlines", "Cathay Pacific", "Thai Airways", "Malaysia Airlines",
    "Air France", "KLM", "Turkish Airlines", "Alliance Air",
]


def titlecase_name(s):
    return " ".join(w.capitalize() for w in s.strip().split())


def name_from_filename(filename):
    stem = re.sub(r"\.pdf$", "", filename, flags=re.IGNORECASE)
    m = re.match(r"Mr\.?\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)", stem.strip())
    if m:
        return titlecase_name(m.group(1))
    return None


def find_airline(text):
    for al in KNOWN_AIRLINES:
        if re.search(re.escape(al), text, re.IGNORECASE):
            return al
    return None


PRICE_RE = re.compile(
    r"(?:Total\s*Amount|Grand\s*Total|Total\s*Fare|Amount\s*Paid|Total\s*Price|"
    r"Total\s*Charge|Fare\s*Amount|Total\s*Payable|Net\s*Amount|Total\s*Paid)"
    r"\s*[:\-]?\s*"
    r"(₹|Rs\.?|INR|USD|\$|EUR|€|GBP|£)?\s*([\d,]+(?:\.\d{1,2})?)",
    re.IGNORECASE,
)


def find_price(text):
    m = PRICE_RE.search(text)
    if not m:
        return None
    currency, amount = m.group(1), m.group(2)
    return f"{currency} {amount}".strip() if currency else amount


def parse_dates_4(text):
    out = []
    for d, mon, y in DATE4_RE.findall(text):
        try:
            out.append(date(int(y), MONTH_NUM[mon], int(d)))
        except ValueError:
            pass
    return out


def parse_dates_2(text):
    out = []
    for d, mon, y in DATE2_RE.findall(text):
        yy = int(y)
        year = 2000 + yy if yy < 70 else 1900 + yy
        try:
            out.append(date(year, MONTH_NUM[mon], int(d)))
        except ValueError:
            pass
    return out


def build_trip(name, origin, destination, dates, airline, pnr, fmt, needs_review=False,
                start_time=None, end_time=None, start_arrival_time=None,
                end_departure_time=None, price=None, booking_source=None):
    dates = sorted(set(dates))
    start_date = dates[0].isoformat() if dates else None
    end_date = dates[-1].isoformat() if dates else start_date
    if not name or not dates:
        needs_review = True
    return {
        "traveler_name": name or "Unknown Traveler",
        "origin": origin,
        "destination": destination,
        "start_date": start_date,
        "end_date": end_date,
        "start_time": start_time,
        "end_time": end_time,
        "start_arrival_time": start_arrival_time,
        "end_departure_time": end_departure_time,
        "airline": airline,
        "pnr": pnr,
        "price": price,
        "booking_source": booking_source,
        "source_format": fmt,
        "needs_review": needs_review,
    }


def detect_format(text):
    if "thank you for booking with us" in text:
        return "makemytrip"
    if "Passenger Information" in text and re.search(r"PNR/Booking Reference", text):
        return "indigo_direct"
    if "eTicket Receipt" in text and "Itinerary Details" in text:
        return "gds_eticket"
    return "generic"


LEG_TIME_RE = re.compile(
    rf"(\d{{1,2}}) ({MONTHS}) (\d{{4}})[^\n]*\n"   # date line, e.g. "Wed, 12 Aug 2026 ..."
    r"[^\n]*\n"                                      # airline + city-pair line
    r"[^\n]*?(\d{1,2}:\d{2})\s*hrs[^\n]*?(\d{1,2}:\d{2})\s*hrs"  # flight/time line
)


def _times_from_legs(leg_matches):
    """leg_matches: list of (day, month, year, dep_time, arr_time).

    Returns (start_time, start_arrival_time, end_departure_time, end_time):
    the outer pair is the trip's first departure and final arrival (as before);
    the inner pair is the same-day arrival on the first leg and same-day
    departure on the last leg, populated only when there's more than one leg
    so a single-leg trip doesn't just duplicate start_time/end_time.
    """
    leg_tuples = []
    for d, mon, y, dep, arr in leg_matches:
        try:
            leg_tuples.append((date(int(y), MONTH_NUM[mon], int(d)), dep, arr))
        except ValueError:
            pass
    if not leg_tuples:
        return None, None, None, None
    leg_tuples.sort(key=lambda t: t[0])
    start_time = leg_tuples[0][1]
    end_time = leg_tuples[-1][2]
    start_arrival_time = leg_tuples[0][2] if len(leg_tuples) > 1 else None
    end_departure_time = leg_tuples[-1][1] if len(leg_tuples) > 1 else None
    return start_time, start_arrival_time, end_departure_time, end_time


def parse_makemytrip(text):
    name = None
    m = re.search(r"Hi\s+([A-Za-z][A-Za-z .]+?),\s*thank you for booking", text)
    if m:
        name = titlecase_name(m.group(1))

    origin = destination = None
    m = re.search(r"([A-Za-z][A-Za-z ]+?)\s+-\s+([A-Za-z][A-Za-z ]+?)\s*\n\s*(?:Round Trip|One Way)", text)
    if m:
        origin, destination = m.group(1).strip(), m.group(2).strip()

    text_for_dates = re.sub(r"Booked on \d{1,2} \w{3} \d{4}", "", text)
    dates = parse_dates_4(text_for_dates)
    start_time, start_arrival_time, end_departure_time, end_time = _times_from_legs(
        LEG_TIME_RE.findall(text_for_dates)
    )
    pnrs = list(dict.fromkeys(re.findall(r"PNR:\s*([A-Z0-9]{5,8})", text)))  # dedupe, keep leg order
    pnr = " / ".join(pnrs) if pnrs else None

    price = find_price(text)
    if price and not re.match(r"^(₹|Rs\.?|INR|\$|USD|€|EUR|£|GBP)", price, re.IGNORECASE):
        # MakeMyTrip Biz totals are often printed without a symbol, but the payment
        # breakdown lines just below always carry ₹ - safe to inherit it here.
        price = f"₹{price}"

    return build_trip(
        name=name, origin=origin, destination=destination, dates=dates,
        airline=find_airline(text), pnr=pnr, price=price,
        fmt="makemytrip", start_time=start_time, end_time=end_time,
        start_arrival_time=start_arrival_time, end_departure_time=end_departure_time,
        booking_source="MyBiz",
    )


def parse_indigo_direct(text):
    name = None
    m = re.search(
        r"Passenger Information\s*\n\s*(?:Mr|Ms|Mrs)\.?\s+([A-Za-z][A-Za-z ]+?)\s+(?:Adult|Child)\s*\|",
        text,
    )
    if m:
        name = titlecase_name(m.group(1))

    sectors = re.findall(r"^([A-Z]{3})-([A-Z]{3})\b", text, re.MULTILINE)
    cities = []
    for a, b in sectors:
        for code in (a, b):
            city = IATA_CITY.get(code, code)
            if not cities or cities[-1] != city:
                cities.append(city)
    origin = cities[0] if cities else None
    dest_list = list(dict.fromkeys(cities[1:]))
    destination = " -> ".join(dest_list) if dest_list else None

    dt_matches = re.findall(rf"(\d{{1,2}}:\d{{2}}) hrs,\s*(\d{{1,2}}) ({MONTHS}) (\d{{4}})", text)
    date_time_pairs = []
    for t, d, mon, y in dt_matches:
        try:
            date_time_pairs.append((date(int(y), MONTH_NUM[mon], int(d)), t))
        except ValueError:
            pass
    dates = [dt for dt, _ in date_time_pairs]
    start_time = end_time = None
    if date_time_pairs:
        date_time_pairs.sort(key=lambda x: (x[0], x[1]))
        start_time = date_time_pairs[0][1]
        end_time = date_time_pairs[-1][1]
    if not dates:
        dates = parse_dates_4(text)

    pnr_m = re.search(r"PNR/Booking Reference\s+([A-Z0-9]{5,8})", text)

    return build_trip(
        name=name, origin=origin, destination=destination, dates=dates,
        airline=find_airline(text) or "IndiGo", pnr=(pnr_m.group(1) if pnr_m else None),
        price=find_price(text), fmt="indigo_direct", start_time=start_time, end_time=end_time,
        booking_source="IndiGo (Direct)",
    )


def parse_gds_eticket(text):
    name = None
    m = re.search(r"Prepared For\s*\n([A-Z]+)/([A-Z]+)", text)
    if m:
        last, first = m.group(1), m.group(2)
        name = f"{first.title()} {last.title()}"

    airline_m = re.search(r"ISSUING AIRLINE\s+([A-Za-z ]+?)\n", text)
    airline = airline_m.group(1).strip() if airline_m else find_airline(text)

    pnr_m = re.search(r"RESERVATION CODE\s+([A-Z0-9]{5,8})", text)

    row_dates = re.findall(rf"(?:^|\n)(\d{{1,2}} (?:{MONTHS}) \d{{2}})\s+[A-Z]", text)
    dep_arr = re.findall(
        rf"Departure:\s*(\d{{1,2}} (?:{MONTHS}) \d{{2}})\s+Arrival:\s*(\d{{1,2}} (?:{MONTHS}) \d{{2}})",
        text,
    )
    date_strs = list(row_dates) + [d for pair in dep_arr for d in pair]
    dates = []
    for ds in date_strs:
        dd, mon, yy = ds.split()
        yy = int(yy)
        year = 2000 + yy if yy < 70 else 1900 + yy
        try:
            dates.append(date(year, MONTH_NUM[mon], int(dd)))
        except ValueError:
            pass
    if not dates:
        dates = parse_dates_2(text)

    return build_trip(
        name=name, origin=None, destination=None, dates=dates,
        airline=airline, pnr=(pnr_m.group(1) if pnr_m else None), price=find_price(text),
        fmt="gds_eticket", needs_review=True, booking_source="Travel Agency (GDS)",
    )


def parse_generic(text, filename=None):
    name = None
    m = re.search(r"Hi\s+([A-Za-z][A-Za-z .]+?),\s*thank you for booking", text)
    if m:
        name = titlecase_name(m.group(1))
    if not name:
        m = re.search(r"(?:Mr|Ms|Mrs)\.?\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)+)", text)
        if m:
            name = titlecase_name(m.group(1))
    if not name and filename:
        name = name_from_filename(filename)

    dates = parse_dates_4(text) or parse_dates_2(text)

    return build_trip(
        name=name, origin=None, destination=None, dates=dates,
        airline=find_airline(text), pnr=None, price=find_price(text), fmt="generic", needs_review=True,
    )


def extract_pdf_text(path):
    parts = []
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                t = page.extract_text(x_tolerance=1.5, y_tolerance=3) or ""
                parts.append(t)
    except Exception:
        pass
    return "\n".join(parts)


def parse_itinerary_text(text, filename=None):
    fmt = detect_format(text)
    if fmt == "makemytrip":
        result = parse_makemytrip(text)
    elif fmt == "indigo_direct":
        result = parse_indigo_direct(text)
    elif fmt == "gds_eticket":
        result = parse_gds_eticket(text)
    else:
        result = parse_generic(text, filename=filename)

    if (not result.get("traveler_name") or result["traveler_name"] == "Unknown Traveler") and filename:
        fallback_name = name_from_filename(filename)
        if fallback_name:
            result["traveler_name"] = fallback_name

    return result


def _trip_from_llm_result(llm_result, source_format="llm"):
    needs_review = not llm_result.get("confident", False)
    if not llm_result.get("traveler_name") or not llm_result.get("start_date"):
        needs_review = True
    return {
        "traveler_name": llm_result.get("traveler_name") or "Unknown Traveler",
        "origin": llm_result.get("origin"),
        "destination": llm_result.get("destination"),
        "start_date": llm_result.get("start_date"),
        "end_date": llm_result.get("end_date") or llm_result.get("start_date"),
        "start_time": llm_result.get("departure_time"),
        "end_time": llm_result.get("arrival_time"),
        "start_arrival_time": llm_result.get("start_arrival_time"),
        "end_departure_time": llm_result.get("end_departure_time"),
        "airline": llm_result.get("airline"),
        "pnr": llm_result.get("pnr"),
        "price": llm_result.get("price"),
        "booking_source": llm_result.get("booking_source"),
        "source_format": source_format,
        "needs_review": needs_review,
    }


def parse_itinerary_pdf(path, filename=None, use_llm=True):
    text = extract_pdf_text(path)
    filename = filename or path

    if use_llm and text.strip():
        try:
            from llm_extractor import extract_with_llm
            llm_result = extract_with_llm(text, filename=filename)
        except ImportError:
            llm_result = None
        if llm_result is not None:
            return _trip_from_llm_result(llm_result)

    # No embedded text layer at all (e.g. a browser print-to-PDF with nothing
    # extractable) - try reading it as an image before giving up on AI entirely.
    if use_llm and not text.strip():
        try:
            from vision_ocr import extract_text_via_vision
            recovered_text = extract_text_via_vision(path)
        except ImportError:
            recovered_text = None
        if recovered_text:
            try:
                from llm_extractor import extract_with_llm
                llm_result = extract_with_llm(recovered_text, filename=filename)
            except ImportError:
                llm_result = None
            if llm_result is not None:
                return _trip_from_llm_result(llm_result, source_format="llm_vision")

    return parse_itinerary_text(text, filename=filename)
