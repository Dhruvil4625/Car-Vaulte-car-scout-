from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.utils import ImageReader
import os

DEEP_NAVY = colors.HexColor("#0A1F44")
TEAL = colors.HexColor("#00D4FF")
GOLD = colors.HexColor("#FFD700")
WHITE = colors.white
TEXT = colors.HexColor("#0f172a")
MUTED = colors.HexColor("#475569")

def _rounded_rect(c, x, y, w, h, r=6*mm, fill_color=WHITE, stroke_color=colors.HexColor("#e2e8f0"), stroke=1, fill=1):
    c.setFillColor(fill_color)
    c.setStrokeColor(stroke_color)
    c.setLineWidth(0.6)
    c.roundRect(x, y, w, h, r, stroke=stroke, fill=fill)

def build_brochure_pdf(user=None, base_dir=None):
    """
    Returns brochure PDF bytes for the Vehicle Vault one-page flyer (A4 portrait).
    """
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4  # 595 x 842 pt

    # Header background ~45% of page height
    header_h = H * 0.45
    c.setFillColor(DEEP_NAVY)
    c.rect(0, H - header_h, W, header_h, stroke=0, fill=1)

    # Title and subtitle
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 34)
    c.drawCentredString(W/2, H - header_h + 0.75*header_h, "VEHICLE VAULT")
    c.setFont("Helvetica-Bold", 18)
    c.setFillColor(TEAL)
    c.drawCentredString(W/2, H - header_h + 0.63*header_h, "India's Smartest Way to Buy & Sell Cars")

    # Hero image with soft overlay
    img_path = None
    if base_dir:
        hero_candidate = os.path.join(base_dir, "static", "img", "bmw-m4-hero.jpg")
        if os.path.exists(hero_candidate):
            img_path = hero_candidate
    if img_path:
        try:
            img = ImageReader(img_path)
            # Fit image width with aspect ratio
            img_w = W - 40
            img_h = header_h * 0.55
            c.drawImage(img, 20, H - header_h + (header_h*0.06), width=img_w, height=img_h, mask='auto')
            c.setFillColor(colors.Color(0,0,0,0.15))
            c.rect(20, H - header_h + (header_h*0.06), img_w, img_h, fill=1, stroke=0)
        except Exception:
            pass

    # Tagline + subtext
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(W/2, H - header_h + 18, "Discover • Negotiate • Own — With Intelligence & Trust")
    c.setFont("Helvetica", 10.5)
    c.setFillColor(colors.HexColor("#cbd5e1"))
    c.drawCentredString(W/2, H - header_h + 4, "AI‑Powered • Secure • Made in India")

    # Features grid (3x2)
    grid_top = H - header_h - 10*mm
    card_w = (W - 40*mm) / 3.0
    card_h = 28*mm
    xs = [15*mm, 15*mm + card_w + 5*mm, 15*mm + 2*(card_w + 5*mm)]
    ys = [grid_top - card_h, grid_top - 2*(card_h + 6*mm)]

    features = [
        ("Immersive 360° & 3D", "Turntable spins, panoramas & 3D models for clarity."),
        ("Secure Chat & Deals", "In‑app messaging and guided negotiation flow."),
        ("AI Recommendations", "Smart matches & real‑time price fairness info."),
        ("Sentiment Intelligence", "Message tone & safety signals for trust."),
        ("AI Condition Scoring", "Insightful scoring from uploaded car photos."),
        ("Razorpay Payments", "UPI, cards & EMI with fast, secure checkout."),
    ]

    c.setFont("Helvetica-Bold", 11.5)
    idx = 0
    for row in range(2):
        for col in range(3):
            if idx >= len(features): break
            x = xs[col]
            y = ys[row]
            _rounded_rect(c, x, y, card_w, card_h, r=4*mm, fill_color=WHITE, stroke_color=colors.HexColor("#e2e8f0"))
            # teal glow line on top
            c.setFillColor(TEAL); c.rect(x, y + card_h - 2, card_w, 2, stroke=0, fill=1)
            c.setFillColor(TEXT)
            c.drawString(x + 6*mm, y + card_h - 8*mm, features[idx][0])
            c.setFillColor(MUTED)
            c.setFont("Helvetica", 9.5)
            c.drawString(x + 6*mm, y + card_h - 13*mm, features[idx][1][:65])
            c.drawString(x + 6*mm, y + card_h - 18*mm, features[idx][1][65:130])
            idx += 1
        if idx >= len(features): break

    # How it works (bottom-left)
    c.setFillColor(TEXT)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(15*mm, 35*mm, "Simple. Smart. Secure.")
    c.setFont("Helvetica", 10.5)
    steps = [
        "1) Search & Discover with AI Guidance",
        "2) Explore Details & Get AI Insights",
        "3) Chat, Negotiate & Schedule Test Drive",
        "4) Pay Securely & Drive Home with Confidence",
    ]
    yy = 30*mm
    for s in steps:
        c.setFillColor(TEAL); c.circle(16*mm, yy+2.5*mm, 1.5*mm, stroke=0, fill=1)
        c.setFillColor(TEXT); c.drawString(20*mm, yy, s)
        yy -= 7*mm

    # Tech stack strip (bottom-right)
    c.setFillColor(colors.HexColor("#00b5e2"))
    strip_h = 14*mm
    c.rect(W - 95*mm, 15*mm, 80*mm, strip_h, stroke=0, fill=1)
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 9.8)
    c.drawCentredString(W - 55*mm, 22*mm, "Django • PostgreSQL • Razorpay • Google Maps • Hugging Face • Python")

    # Footer credits & QR placeholder
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 9)
    c.drawString(15*mm, 12*mm, "Developed by Dhruvil as Internship Project")
    c.drawString(15*mm, 8*mm, "Vadodara, Gujarat • 2025–2026")
    # QR placeholder
    _rounded_rect(c, W - 30*mm, 10*mm, 20*mm, 20*mm, r=2*mm, fill_color=WHITE)
    c.setFillColor(MUTED); c.setFont("Helvetica", 7.5)
    c.drawCentredString(W - 20*mm, 8*mm, "QR: Live Demo / GitHub")

    # Gold accent bar
    c.setFillColor(GOLD); c.rect(0, H - header_h, W, 3, stroke=0, fill=1)
    c.showPage()
    c.save()
    return buf.getvalue()
