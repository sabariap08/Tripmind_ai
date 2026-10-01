"""Guards for services/place_images._score.

These cases are the ones that actually occurred in this project's seed data,
plus the false-positive classes the scorer was extended to reject. They need no
network access and no database, so they can run in CI.

    python scripts/test_place_images.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.place_images import _score, _foreign_proper_nouns  # noqa: E402

# (title, name, city, district, kind, should_accept, why)
CASES = (
    # --- spots: real matches, must be kept ---------------------------------
    ("File:Chennai Marina Beach in 2022, October 01.jpg", "Marina Beach",
     "Chennai", "Chennai", "spot", True, "verbatim name in title"),
    ("File:Chennai-Fort St. George-St. Mary's Church-WUS01478.jpg", "Fort St. George",
     "Chennai", "Chennai", "spot", True, "verbatim name in title"),
    ("File:Chennai Kapaleeshwarar Temple.jpg", "Kapaleeshwarar Temple",
     "Chennai", "Chennai", "spot", True, "verbatim name in title"),
    ("File:Mahabalipuram-Shore Temple-WUS01811.jpg", "Mahabalipuram (Shore Temple)",
     "Mahabalipuram", "Chennai", "spot", True, "verbatim name in title"),
    ("File:Marudhamalai Murugan Temple Coimbatore.jpg", "Marudhamalai Murugan Temple",
     "Coimbatore", "Coimbatore", "spot", True, "verbatim + city"),
    ("File:Boating, Ooty Lake 01.jpg", "Ooty Lake",
     "Ooty", "Nilgiris", "spot", True, "verbatim name"),

    # --- the reported bug: unrelated landmark photos ------------------------
    ("File:Taj Mahal, Agra, India.jpg", "Kapaleeshwarar Temple",
     "Chennai", "Chennai", "spot", False, "Taj Mahal is not this temple"),
    ("File:Amber Fort Jaipur Rajasthan.jpg", "Fort St. George",
     "Chennai", "Chennai", "spot", False, "Rajasthan fort is not Fort St. George"),
    ("File:Palolem Beach Goa.jpg", "Kovai Kondattam Amusement Park",
     "Coimbatore", "Coimbatore", "spot", False, "beach is not an amusement park"),

    # --- wrong city behind a shared category word ---------------------------
    # This is the class that motivated geographic corroboration.
    ("File:Gateway Bridge and CityCat Marina Murarrie Mumbai.jpg", "Marina Gateway",
     "Chennai", "Chennai", "hotel", False, "Mumbai bridge, not a Chennai hotel"),
    ("File:Colva Residency Hotel Of GTDC Goa - panoramio.jpg", "Hotel Residency",
     "Chennai", "Chennai", "hotel", False, "Goa hotel, name is far too generic"),
    ("File:Marina Bay Sands Singapore from the sky.jpg", "Marina Deck",
     "Chennai", "Chennai", "restaurant", False, "Singapore landmark, not Chennai"),
    ("File:Cloud Forest - Gardens by the Bay.jpg", "Marina Deck",
     "Chennai", "Chennai", "restaurant", False, "Singapore landmark, not Chennai"),

    # --- right city, wrong business -----------------------------------------
    ("File:Grand Padappai Residency Chennai.jpg", "Grand Chennai Residency",
     "Chennai", "Chennai", "hotel", False, "a different hotel in the same city"),
    ("File:MS Marina Deck at Night.JPG", "Marina Deck",
     "Chennai", "Chennai", "restaurant", True, "name is distinctive and matches"),
    ("File:ITC Grand Chola Chennai.jpg", "Grand Chennai Residency",
     "Chennai", "Chennai", "hotel", False, "ITC Grand Chola is a different hotel"),

    # --- generic-only names need the city -----------------------------------
    ("File:City Park Chennai.jpg", "City Park", "Chennai", "Chennai",
     "spot", True, "generic name, but city corroborates"),
    ("File:City Park Kolkata.jpg", "City Park", "Chennai", "Chennai",
     "spot", False, "generic name, wrong city"),
)


def main():
    failures = []
    for title, name, city, district, kind, expect, why in CASES:
        score, ok = _score(title, name, city, district, kind=kind)
        status = "PASS" if ok is expect else "FAIL"
        if ok is not expect:
            failures.append((title, name, kind, expect, ok, why))
        print("  [%s] %-6s score=%-4.1f %s" % (status, kind, score, why))
        print("         %s" % title)

    print("\n-- _foreign_proper_nouns (business kinds only) --")
    # This check is deliberately not applied to spots: "Fort St. George-St.
    # Mary's Church" is a correct photo of Fort St. George even though the
    # filename mentions a building inside the fort. Its behaviour on spots is
    # covered by the _score cases above.
    foreign_cases = (
        ("File:Grand Padappai Residency Chennai.jpg", "Grand Chennai Residency",
         ["Padappai"]),
        ("File:Chennai Marina Beach.jpg", "Marina Beach", []),
        ("File:MS Marina Deck at Night.JPG", "Marina Deck", []),
        ("File:ITC Grand Chola Chennai.jpg", "Grand Chennai Residency",
         ["Chola"]),
    )
    for title, name, expect in foreign_cases:
        got = _foreign_proper_nouns(title, name)
        status = "PASS" if got == expect else "FAIL"
        if got != expect:
            failures.append((title, name, "foreign", expect, got, ""))
        print("  [%s] %-52s -> %s" % (status, title[:52], got))

    total = len(CASES) + len(foreign_cases)
    if failures:
        print("\n%d/%d FAILED" % (len(failures), total))
        for f in failures:
            print("  %s / %s (%s): expected %s, got %s  [%s]" % f)
        return 1
    print("\nAll %d provenance guards pass." % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
