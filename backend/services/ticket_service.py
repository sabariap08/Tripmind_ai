"""Ticket PDF generation and QR verification for bookings.

- Every confirmed booking can be downloaded as a printable PDF ticket.
- The ticket carries a QR code whose payload is an opaque, HMAC-signed
  token (see issue_token) — it contains NO personal data (no passenger
  name, phone, identity numbers). It only encodes a server-side booking
  identifier, its public reference, its status and a signature.
- Verification endpoint recovers the booking from the token and asserts
  the live status still matches what the ticket was issued for, so a
  cancelled/rejected ticket verifies as invalid.

The status is bound into the signature on purpose: a ticket printed for a
CONFIRMED booking becomes unverifiable the moment it is cancelled.
"""
import base64
import hashlib
import hmac
import io
from datetime import datetime

import qrcode
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, A5
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

from config import SECRET_KEY
from services.mongodb import get_collection


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s):
    try:
        pad = "=" * (-len(s) % 4)
        return base64.urlsafe_b64decode(s + pad)
    except (ValueError, TypeError):
        return None


def issue_token(booking):
    """Opaque signed token for a booking (no personal data)."""
    payload = f"{booking['_id']}|{booking['reference']}|{booking['status']}"
    sig = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).digest()[:24]
    return ".".join([
        _b64(booking["_id"].encode()),
        _b64(booking["reference"].encode()),
        _b64(booking["status"].encode()),
        _b64(sig),
    ])


def verify_token(token):
    """Verify a ticket token against the live booking.

    Returns (booking, None) on success, (None, reason) otherwise. No PII is
    exposed in the returned reason.
    """
    try:
        b64id, b64ref, b64status, b64sig = (token or "").split(".")
    except ValueError:
        return None, "Malformed ticket."
    _id = _unb64(b64id)
    _ref = _unb64(b64ref)
    _status = _unb64(b64status)
    sig = _unb64(b64sig)
    if None in (_id, _ref, _status, sig):
        return None, "Malformed ticket."
    booking_id = _id.decode()
    expected = f"{booking_id}|{_ref.decode()}|{_status.decode()}"
    want = hmac.new(SECRET_KEY.encode(), expected.encode(), hashlib.sha256).digest()[:24]
    if not hmac.compare_digest(sig, want):
        return None, "Invalid ticket signature."
    booking = get_collection("bookings").find_one({"_id": booking_id})
    if not booking:
        return None, "Ticket no longer exists."
    if (booking.get("reference") != _ref.decode()
            or booking.get("status") != _status.decode()):
        return None, "Ticket is no longer in the issued state."
    return booking, None


def _esc(v):
    return None if v is None else str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _money(v):
    try:
        return "Rs. %.2f" % float(v or 0)
    except (TypeError, ValueError):
        return "-"


def _service_rows(booking):
    """Human-readable service detail rows for the PDF."""
    btype = booking.get("type")
    details = booking.get("details") or {}
    rows = []
    if btype == "TRANSPORT":
        t = get_collection("transports").find_one({"_id": str(booking.get("transportId") or "")}) or {}
        rows += [
            ("Service", (t.get("serviceName") or "Transport") + " (" + (t.get("type") or "TRANSPORT") + ")"),
            ("Journey", " -> ".join(x or "-" for x in
                                    [t.get("boardingPoint"), t.get("droppingPoint")])),
            ("Vehicle", t.get("busNumber") or t.get("flightNumber") or t.get("vehicleNumber") or t.get("registrationNumber") or "-"),
            ("Departure", (t.get("boardingTime") or t.get("departureTime") or "-")
                          + (" (Day +%s)" % t.get("boardingDay") if t.get("boardingDay") else "")),
            ("Arrival", t.get("droppingTime") or t.get("arrivalTime") or "-"),
            ("Class / Seats", (booking.get("seatType") or details.get("seatClass") or "-")
                              + " x " + str(booking.get("qty") or 1)),
        ]
        if details.get("distanceKm"):
            rows.append(("Distance", "%.0f km" % float(details["distanceKm"])))
    elif btype == "HOTEL":
        h = get_collection("hotels").find_one({"_id": str(booking.get("hotelId") or "")}) or {}
        rt = next((r for r in (h.get("roomTypes") or [])
                   if r.get("id") == str(booking.get("roomTypeId") or "")), {})
        rows += [
            ("Hotel", h.get("name") or "-"),
            ("Location", h.get("city") or h.get("address") or h.get("location") or "-"),
            ("Room type", (rt.get("name") or "-") + " x " + str(booking.get("qty") or 1)),
        ]
    elif btype == "TOUR":
        t = get_collection("tours").find_one({"_id": str(booking.get("tourId") or "")}) or {}
        rows.append(("Tour", t.get("title") or t.get("name") or "-"))
        if t.get("duration"):
            rows.append(("Duration", str(t.get("duration"))))
    elif btype == "SPOT":
        s = get_collection("tourist_spots").find_one({"_id": str(booking.get("spotId") or "")}) or {}
        rows.append(("Spot", s.get("name") or "-"))
        loc = s.get("location") or {}
        if isinstance(loc, dict) and loc.get("district"):
            rows.append(("District", str(loc["district"])))
    elif btype == "GUIDE":
        g = get_collection("users").find_one({"_id": str(booking.get("guideId") or "")}) or {}
        rows += [
            ("Guide", g.get("name") or "-"),
            ("Slot", " - ".join([(details.get("startTime") or "-"), (details.get("endTime") or "-")])),
            ("Location", details.get("location") or "-"),
        ]
    elif btype == "RESTAURANT":
        r = get_collection("restaurants").find_one({"_id": str(booking.get("restaurantId") or "")}) or {}
        rows += [
            ("Restaurant", r.get("name") or booking.get("foodName") or "-"),
            ("City", r.get("city") or "-"),
            ("Item", booking.get("foodName") or "-"),
            ("Qty", str(booking.get("qty") or 1)),
        ]
    return rows


def build_ticket_pdf(booking):
    """Render a printable PDF ticket (with QR) for a booking. Returns bytes."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A5,
                            leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=10 * mm, bottomMargin=10 * mm,
                            title="TripMind AI Ticket %s" % booking.get("reference"),
                            author="TripMind AI")

    ss = getSampleStyleSheet()
    title = ParagraphStyle("TitleX", parent=ss["Title"], fontSize=16,
                           textColor=colors.HexColor("#1e3a8a"))
    h2 = ParagraphStyle("H2X", parent=ss["Heading2"], fontSize=11,
                        textColor=colors.HexColor("#1e293b"))
    small = ParagraphStyle("SmallX", parent=ss["BodyText"], fontSize=8.5,
                           leading=11, textColor=colors.HexColor("#334155"))
    bold = ParagraphStyle("BoldX", parent=small, fontName="Helvetica-Bold")

    badge_col = {"CONFIRMED": colors.HexColor("#059669"),
                 "PENDING": colors.HexColor("#b45309"),
                 "CANCELLED": colors.HexColor("#b91c1c"),
                 "REJECTED": colors.HexColor("#b91c1c"),
                 "COMPLETED": colors.HexColor("#2563eb")}.get(
                     booking.get("status"), colors.grey)

    story = []
    story.append(Paragraph("TripMind AI", title))
    story.append(Paragraph("Travel Ticket", ParagraphStyle(
        "SubX", parent=title, fontSize=11, textColor=colors.grey)))
    story.append(Spacer(1, 4 * mm))

    story.append(_kv_table([
        ("Ticket Reference", booking.get("reference") or "-", bold),
        ("Status", booking.get("status") or "-", ParagraphStyle(
            "Stat", parent=bold, textColor=badge_col)),
        ("Travel date", booking.get("date") or "-", small),
        ("Booked on", (booking.get("createdAt") or "-").replace("T", " ")[:16], small),
    ], spans=1))
    story.append(Spacer(1, 3 * mm))

    service = _service_rows(booking)
    if service:
        story.append(Paragraph("Service details", h2))
        story.append(_kv_table([(k, v, small) for k, v in service]))
        story.append(Spacer(1, 3 * mm))

    story.append(Paragraph("Payment summary", h2))
    story.append(_kv_table([
        ("Unit price", _money(booking.get("unitPrice")), small),
        ("Quantity", str(booking.get("qty") or 1), small),
        ("Total", _money(booking.get("total")), bold),
        ("Payment status", booking.get("paymentStatus") or "PENDING", small),
        ("Paid from wallet", _money(booking.get("walletPaid")), small),
    ]))
    if booking.get("walletTxnId"):
        story.append(Paragraph("Wallet txn: %s" % _esc(booking["walletTxnId"]), small))
    story.append(Spacer(1, 6 * mm))

    token = issue_token(booking)
    try:
        img = qrcode.make("verify?token=" + token)
        qbuf = io.BytesIO()
        img.save(qbuf, format="PNG")
        qbuf.seek(0)
        story.append(Table([[Image(qbuf, 52 * mm, 52 * mm)],
                            [Paragraph("Scan to verify this ticket", ParagraphStyle(
                                "Scan", parent=small, alignment=TA_CENTER))]],
                           colWidths=[52 * mm]))
    except Exception:
        story.append(Paragraph("Verification token unavailable.", small))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("Verification code: %s" % _esc(token), small))

    doc.build(story)
    return buf.getvalue()


def _kv_table(rows, spans=None):
    cells = []
    for i, (k, v, style) in enumerate(rows):
        cells.append([Paragraph(k, ParagraphStyle("K%d" % i, parent=style,
                                                  fontName="Helvetica-Bold",
                                                  textColor=colors.HexColor("#64748b"))),
                      Paragraph(_esc(v), style)])
    t = Table(cells, colWidths=[42 * mm, 82 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


# ---------------------------------------------------------------------------
# Whole-trip tickets (ONE ticket, ONE QR per trip).
#
# The token encodes only a 'TRIP' tag, the trip id and its public reference —
# there is no personal data and (unlike a single booking) the status is NOT
# bound into the signature, so a completed trip ticket still verifies.
# ---------------------------------------------------------------------------

def issue_trip_token(trip):
    ref = trip.get("reference") or ""
    payload = "TRIP:%s:%s" % (trip["_id"], ref)
    sig = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).digest()[:24]
    return ".".join([
        _b64(b"TRIP"),
        _b64(trip["_id"].encode()),
        _b64(ref.encode()),
        _b64(sig),
    ])


def is_trip_token(token):
    """True when the token is a whole-trip token (starts with the TRIP tag)."""
    try:
        first = (token or "").split(".")[0]
        pad = "=" * (-len(first) % 4)
        return (base64.urlsafe_b64decode(first + pad) or b"").decode() == "TRIP"
    except (ValueError, TypeError):
        return False


def verify_trip_token(token):
    """Verify a whole-trip token against the live trip document.

    Returns (trip, None) on success, (None, reason) otherwise. No PII is
    exposed in the returned reason.
    """
    try:
        b64tag, b64id, b64ref, b64sig = (token or "").split(".")
    except ValueError:
        return None, "Malformed ticket."
    tag = _unb64(b64tag)
    trip_id = _unb64(b64id)
    b64ref = _unb64(b64ref)
    sig = _unb64(b64sig)
    if None in (tag, trip_id, b64ref, sig):
        return None, "Malformed ticket."
    if tag.decode() != "TRIP":
        return None, "Not a trip ticket."
    trip_id = trip_id.decode()
    ref = b64ref.decode()
    expected = "TRIP:%s:%s" % (trip_id, ref)
    want = hmac.new(SECRET_KEY.encode(), expected.encode(), hashlib.sha256).digest()[:24]
    if not hmac.compare_digest(sig, want):
        return None, "Invalid ticket signature."
    trip = get_collection("trips").find_one({"_id": trip_id})
    if not trip:
        return None, "Ticket no longer exists."
    if (trip.get("reference") or "") != ref:
        return None, "Ticket is no longer in the issued state."
    return trip, None


def build_trip_ticket_pdf(trip):
    """Render a printable PDF ticket (ONE QR) for a whole trip. Returns bytes."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm,
                            title="TripMind AI Trip Ticket %s" % (trip.get("reference") or trip["_id"]),
                            author="TripMind AI")

    ss = getSampleStyleSheet()
    title = ParagraphStyle("TripTitle", parent=ss["Title"], fontSize=18,
                           textColor=colors.HexColor("#1e3a8a"))
    h2 = ParagraphStyle("TripH2", parent=ss["Heading2"], fontSize=12,
                        textColor=colors.HexColor("#1e293b"))
    small = ParagraphStyle("TripSmall", parent=ss["BodyText"], fontSize=9,
                           leading=12, textColor=colors.HexColor("#334155"))
    bold = ParagraphStyle("TripBold", parent=small, fontName="Helvetica-Bold")

    status_col = {"BOOKED": colors.HexColor("#059669"),
                  "COMPLETED": colors.HexColor("#2563eb"),
                  "PLANNED": colors.HexColor("#b45309")}.get(
                      trip.get("status"), colors.grey)

    selected = None
    for itin in trip.get("itineraries", []):
        if itin.get("status") == "SELECTED":
            selected = itin
            break

    story = []
    story.append(Paragraph("TripMind AI", title))
    story.append(Paragraph("Trip Ticket", ParagraphStyle(
        "SubX", parent=title, fontSize=12, textColor=colors.grey)))
    story.append(Spacer(1, 4 * mm))

    story.append(_kv_table([
        ("Trip reference", trip.get("reference") or trip["_id"], bold),
        ("Status", trip.get("status") or "-", ParagraphStyle(
            "Stat", parent=bold, textColor=status_col)),
        ("Route", " -> ".join([(trip.get("origin") or "-"), (trip.get("destination") or "-")]), small),
        ("Dates", "%s to %s" % (trip.get("startDate") or "-", trip.get("endDate") or "-"), small),
        ("Travelers", str(trip.get("travelers") or 1), small),
        ("Issued on", datetime.utcnow().strftime("%b %d, %Y"), small),
    ], spans=1))
    story.append(Spacer(1, 4 * mm))

    if selected:
        story.append(Paragraph("Itinerary (%s)" % (selected.get("planType") or "Plan"), h2))
        header = [Paragraph("Day", bold), Paragraph("Time", bold),
                  Paragraph("Item", bold), Paragraph("Provider", bold),
                  Paragraph("Cost", bold)]
        cells = [header]
        for item in (selected.get("items") or []):
            st = (item.get("startTime") or "")
            st = st[11:16] if len(st or "") > 10 else (st or "-")
            cells.append([
                Paragraph(str(item.get("day", 1)), small),
                Paragraph(st, small),
                Paragraph(_esc(item.get("title") or "-"), small),
                Paragraph(_esc(item.get("provider") or "-"), small),
                Paragraph(_money(item.get("cost") or 0), small),
            ])
        table = Table(cells, repeatRows=1)
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(table)
        story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("Payment summary", h2))
    est = trip.get("totalEstimatedCost")
    payment = trip.get("paymentStatus") or "PENDING"
    paid_col = colors.HexColor("#059669") if payment in ("PAID", "COMPLETED", "WALLET") else colors.grey
    story.append(_kv_table([
        ("Total planned cost", _money(est) if est is not None else "-", bold),
        ("Payment", payment, ParagraphStyle("PStat", parent=small, textColor=paid_col)),
    ]))
    story.append(Spacer(1, 7 * mm))

    token = issue_trip_token(trip)
    try:
        img = qrcode.make("verify?token=" + token)
        qbuf = io.BytesIO()
        img.save(qbuf, format="PNG")
        qbuf.seek(0)
        story.append(Table([[Image(qbuf, 50 * mm, 50 * mm)],
                            [Paragraph("Scan to verify this trip ticket", ParagraphStyle(
                                "Scan", parent=small, alignment=TA_CENTER))]],
                           colWidths=[50 * mm]))
    except Exception:
        story.append(Paragraph("Verification token unavailable.", small))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("Verification code: %s" % _esc(token), small))

    doc.build(story)
    return buf.getvalue()