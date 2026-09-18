"""Generate TripMind_AI_Test_Credentials.pdf in the project root.

Renders the seed account table (scripts/seed_tripmind_cbe_chn_data.ACCOUNTS)
plus the preserved system Main Admin so every test credential lives in one
document. Run AFTER `python backend/scripts/seed_tripmind_cbe_chn_data.py`
so the accounts actually exist in the DB.

Output: <project root>/TripMind_AI_Test_Credentials.pdf
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from scripts.seed_tripmind_cbe_chn_data import ACCOUNTS

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "TripMind_AI_Test_Credentials.pdf")

ROLE_LABEL = {
    "USER": "Passenger",
    "RAILWAY_ADMIN": "Railway Admin",
    "TRANSPORT_ADMIN": "Transport Admin",
    "HOTEL_ADMIN": "Hotel Admin",
    "RESTAURANT_ADMIN": "Restaurant Admin",
    "TOURIST_SPOT_ADMIN": "Travel Spot Admin",
    "GUIDE": "Guide",
}


def build_rows():
    rows = [["Role", "Name", "Company", "Email", "Password"]]
    for a in sorted(ACCOUNTS, key=lambda x: (x["role"], x["name"])):
        rows.append([
            ROLE_LABEL.get(a["role"], a["role"]),
            a["name"], a["company"], a["email"], "password",
        ])
    rows.append(["System Admin", "Main Admin", "TripMind AI Platform",
                 "admin@tripmind.com", "admin@123"])
    return rows


def main():
    rows = build_rows()
    title_style = ParagraphStyle("title", fontName="Helvetica-Bold",
                                 fontSize=18, leading=22, spaceAfter=4)
    sub_style = ParagraphStyle("sub", fontName="Helvetica", fontSize=10,
                               leading=14, textColor=colors.grey, spaceAfter=10)
    cell = ParagraphStyle("cell", fontName="Helvetica", fontSize=9, leading=12)
    cell_bold = ParagraphStyle("cellb", fontName="Helvetica-Bold", fontSize=9,
                               leading=12)

    doc = SimpleDocTemplate(OUT, pagesize=landscape(A4),
                            leftMargin=1.2 * cm, rightMargin=1.2 * cm,
                            topMargin=1.2 * cm, bottomMargin=1.2 * cm,
                            title="TripMind AI Test Credentials",
                            author="TripMind AI")

    story = [
        Paragraph("TripMind AI - Test Credentials", title_style),
        Paragraph("%d seeded corridor accounts + system admin. "
                  % len(ACCOUNTS)
                  + "Every seeded account uses the password "
                  "<b>password</b>; the admin password is <b>admin@123</b>. "
                  "Generated %s." % datetime.now().strftime("%d %b %Y, %H:%M %Z"),
                  sub_style),
    ]

    data = [[]]
    header = ["Role", "Name", "Company", "Email", "Password"]
    body = [Paragraph(h, cell_bold) for h in header]
    grid = [body]
    for role, name, company, email, password in rows[1:]:
        grid.append([
            Paragraph(role, cell), Paragraph(name, cell),
            Paragraph(company, cell), Paragraph(email, cell),
            Paragraph(password, cell),
        ])

    t = Table(grid, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#232D3F")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C7C9CE")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#F2F4F8")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(Spacer(1, 0.4 * cm))
    story.append(t)
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph(
        "All accounts are active and approved in the <b>tripmind</b> database "
        "(MongoDB Atlas). The Railway admin has registered trains and lounges; "
        "transport operators have registered buses/flights/cabs with fares; "
        "hotels have room inventory; restaurants have food items; travel spots "
        "have images, slots and tours; guides have pricing and locked weekly "
        "availability.", sub_style))

    doc.build(story)
    print("PDF written to:", OUT)
    return OUT


if __name__ == "__main__":
    main()