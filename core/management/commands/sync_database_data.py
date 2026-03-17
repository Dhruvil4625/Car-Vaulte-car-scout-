import random
import re
from decimal import Decimal
from html import escape
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db.models import Count, Q

from core.models import Car, CarCon, CarListing, CarListingImage, CarPro


LUXURY_BRANDS = {"BMW", "Mercedes-Benz", "Audi", "Volkswagen", "Skoda", "Porsche", "Volvo", "Jaguar", "Land Rover"}


def _to_decimal(v, default=Decimal("0.00")):
    try:
        if v is None:
            return default
        return Decimal(str(v))
    except Exception:
        return default


def _infer_market_fields(listing):
    price = _to_decimal(getattr(listing, "price", None), Decimal("0.00"))
    if price <= 0:
        price = Decimal("100000")

    tax_pct = Decimal("0.10") if price < Decimal("2000000") else (Decimal("0.12") if price < Decimal("4000000") else Decimal("0.15"))
    ins_pct = Decimal("0.025")
    duty_pct = Decimal("0.15") if (getattr(getattr(listing, "car", None), "make", "") in LUXURY_BRANDS) else Decimal("0.00")

    market = (price * Decimal(str(random.uniform(0.94, 1.04)))).quantize(Decimal("0.01"))
    tax = (market * tax_pct).quantize(Decimal("0.01"))
    ins = (market * ins_pct).quantize(Decimal("0.01"))
    duty = (market * duty_pct).quantize(Decimal("0.01"))
    on_road = (market + tax + ins + duty).quantize(Decimal("0.01"))

    diff = ((price - market) / market) if market else Decimal("0")
    if abs(diff) <= Decimal("0.05"):
        label = "Fair Price"
    elif diff < Decimal("-0.10"):
        label = "Good Deal"
    elif diff > Decimal("0.10"):
        label = "Expensive"
    else:
        label = "Slightly Off"

    return {
        "market_price": market,
        "tax_amount": tax,
        "insurance_amount": ins,
        "import_duty": duty,
        "on_road_price": on_road,
        "deal_label": label,
    }


def _sanitize_filename(s):
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", (s or "car").strip()).strip("-")[:90] or "car"


def _svg_placeholder_bytes(make, model, year):
        title = f"{(make or 'Brand').strip()} {(model or 'Model').strip()}"
        subtitle = f"{year or ''} Vehicle Vault".strip()
        title = escape(title)
        subtitle = escape(subtitle)
        svg = f"""<svg xmlns='http://www.w3.org/2000/svg' width='1200' height='800' viewBox='0 0 1200 800'>
    <defs>
        <linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>
            <stop offset='0%' stop-color='#0f172a'/>
            <stop offset='100%' stop-color='#334155'/>
        </linearGradient>
    </defs>
    <rect width='1200' height='800' fill='url(#g)'/>
    <rect x='40' y='40' width='1120' height='720' rx='24' fill='none' stroke='#e2e8f0' stroke-width='2' opacity='0.6'/>
    <text x='600' y='360' text-anchor='middle' fill='#ffffff' font-family='Segoe UI, Arial, sans-serif' font-size='64' font-weight='700'>{title}</text>
    <text x='600' y='430' text-anchor='middle' fill='#cbd5e1' font-family='Segoe UI, Arial, sans-serif' font-size='34'>{subtitle}</text>
    <text x='600' y='730' text-anchor='middle' fill='#94a3b8' font-family='Segoe UI, Arial, sans-serif' font-size='24'>Model-aligned placeholder image</text>
</svg>"""
        return svg.encode("utf-8")


class Command(BaseCommand):
    help = "Synchronize DB details: market fields, pros/cons, and model-wise listing images for pgAdmin completeness."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0, help="Optional listing limit for image backfill")
        parser.add_argument("--dry-run", action="store_true", help="Preview updates without writing")
        parser.add_argument(
            "--skip-remote-images",
            action="store_true",
            help="Do not fetch remote photos; create model-aligned SVG placeholders immediately.",
        )

    def _fetch_image_bytes(self, make, model):
        queries = [
            f"{make} {model} car",
            f"{make} {model} automobile",
            f"{make} car",
            "car vehicle",
        ]
        for q in queries:
            try:
                url = f"https://source.unsplash.com/1200x800/?{quote_plus(q)}"
                req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urlopen(req, timeout=8) as res:
                    ctype = (res.headers.get("Content-Type") or "").lower()
                    if "image" not in ctype:
                        continue
                    body = res.read()
                    if body and len(body) > 2000:
                        return body
            except (HTTPError, URLError, TimeoutError, ValueError):
                continue
            except Exception:
                continue
        return None

    def handle(self, *args, **options):
        dry_run = bool(options["dry_run"])
        limit = int(options["limit"] or 0)
        skip_remote_images = bool(options.get("skip_remote_images"))

        # 1) Fill missing expert fields + pros/cons minimally
        cars = Car.objects.all()
        cars_fixed = 0
        pros_added = 0
        cons_added = 0

        for car in cars:
            changed = False
            if not car.expert_overview:
                car.expert_overview = f"{car.make} {car.model} offers a balanced package for Indian roads with comfort, safety and value."
                changed = True
            if not car.expert_exterior:
                car.expert_exterior = "Contemporary design, balanced proportions, and road presence suitable for urban and highway use."
                changed = True
            if not car.expert_interior:
                car.expert_interior = "Practical cabin with user-friendly controls, comfort-focused seating, and modern infotainment."
                changed = True
            if not car.expert_performance:
                car.expert_performance = "Refined performance with predictable drivability, efficiency, and confidence at cruising speeds."
                changed = True
            if not car.expert_verdict:
                car.expert_verdict = "A strong choice in its class for buyers prioritizing reliability, value, and overall ownership experience."
                changed = True
            if car.engine_cc is None and (car.fuel_type or "").lower() != "electric":
                car.engine_cc = random.choice([1197, 1498, 1998, 2998])
                changed = True

            if changed and not dry_run:
                car.save(update_fields=[
                    "expert_overview",
                    "expert_exterior",
                    "expert_interior",
                    "expert_performance",
                    "expert_verdict",
                    "engine_cc",
                ])
            if changed:
                cars_fixed += 1

            if car.pros.count() == 0:
                pros = [
                    "Practical and comfortable for daily use",
                    "Competitive features and safety package",
                    "Wide service support and ownership confidence",
                ]
                if not dry_run:
                    CarPro.objects.bulk_create([CarPro(car=car, text=t) for t in pros])
                pros_added += len(pros)
            if car.cons.count() == 0:
                cons = [
                    "Top variants can be expensive",
                    "Real-world mileage varies by traffic conditions",
                    "Delivery waiting period may apply in some cities",
                ]
                if not dry_run:
                    CarCon.objects.bulk_create([CarCon(car=car, text=t) for t in cons])
                cons_added += len(cons)

        # 2) Fill missing market-price fields + description market block
        listings = CarListing.objects.select_related("car").all()
        market_fixed = 0
        desc_fixed = 0

        for lst in listings:
            needs_market = any(
                getattr(lst, f) in (None, "")
                for f in ["market_price", "tax_amount", "insurance_amount", "import_duty", "on_road_price", "deal_label"]
            )
            changed_fields = []

            if needs_market:
                vals = _infer_market_fields(lst)
                for k, v in vals.items():
                    setattr(lst, k, v)
                    changed_fields.append(k)
                market_fixed += 1

            desc = (lst.description or "").strip()
            has_market_block = "Market Snapshot" in desc and "On-road Breakdown" in desc
            if not has_market_block:
                vals = {
                    "market": getattr(lst, "market_price", None) or _infer_market_fields(lst)["market_price"],
                    "tax": getattr(lst, "tax_amount", None) or Decimal("0"),
                    "ins": getattr(lst, "insurance_amount", None) or Decimal("0"),
                    "duty": getattr(lst, "import_duty", None) or Decimal("0"),
                    "on_road": getattr(lst, "on_road_price", None) or Decimal("0"),
                    "label": getattr(lst, "deal_label", None) or "Fair Price",
                }
                lst.description = (
                    f"<p><strong>Market Snapshot:</strong> Estimated current market price for this "
                    f"{lst.car.year} {lst.car.make} {lst.car.model} is ₹{vals['market']:,.0f}. "
                    f"AI fairness label: <strong>{vals['label']}</strong>.</p>"
                    f"<p><strong>On-road Breakdown:</strong> Tax ₹{vals['tax']:,.0f}, "
                    f"Insurance ₹{vals['ins']:,.0f}, Import Duty ₹{vals['duty']:,.0f}; "
                    f"Expected total on-road cost ₹{vals['on_road']:,.0f}.</p>"
                    f"<p>Verified listing with practical features and pricing aligned to current market trends.</p>"
                )
                changed_fields.append("description")
                desc_fixed += 1

            if changed_fields and not dry_run:
                lst.save(update_fields=list(dict.fromkeys(changed_fields)))

        # 3) Add listing images where missing (brand/model-wise)
        missing_qs = CarListing.objects.select_related("car").annotate(ic=Count("images")).filter(ic=0).order_by("-created_at")
        if limit > 0:
            missing_qs = missing_qs[:limit]

        image_cache = {}
        img_added = 0
        img_failed = 0

        for lst in missing_qs:
            key = (lst.car.make or "", lst.car.model or "")
            raw = image_cache.get(key)
            if raw is None:
                raw = None if skip_remote_images else self._fetch_image_bytes(lst.car.make, lst.car.model)
                image_cache[key] = raw

            safe = _sanitize_filename(f"{lst.car.make}-{lst.car.model}-{lst.car.year}")
            if raw:
                payload = raw
                fname = f"seed_{safe}.jpg"
            else:
                payload = _svg_placeholder_bytes(lst.car.make, lst.car.model, lst.car.year)
                fname = f"seed_{safe}.svg"
                img_failed += 1

            if not dry_run:
                CarListingImage.objects.create(
                    listing=lst,
                    image=ContentFile(payload, name=fname),
                    alt=f"{lst.car.make} {lst.car.model}",
                )
            img_added += 1

        # 4) Summary for pgAdmin readiness
        final_missing = CarListing.objects.annotate(ic=Count("images")).filter(ic=0).count()
        missing_market = CarListing.objects.filter(
            Q(market_price__isnull=True)
            | Q(tax_amount__isnull=True)
            | Q(insurance_amount__isnull=True)
            | Q(import_duty__isnull=True)
            | Q(on_road_price__isnull=True)
            | Q(deal_label__isnull=True)
        ).count()

        self.stdout.write(self.style.SUCCESS("Database sync completed."))
        self.stdout.write(f"Cars fixed: {cars_fixed}")
        self.stdout.write(f"Pros added: {pros_added}, Cons added: {cons_added}")
        self.stdout.write(f"Listings market fields fixed: {market_fixed}")
        self.stdout.write(f"Listings description market blocks fixed: {desc_fixed}")
        self.stdout.write(f"Listing images added: {img_added}, image fetch failed: {img_failed}")
        self.stdout.write(self.style.WARNING(f"Remaining listings without images: {final_missing}"))
        self.stdout.write(self.style.WARNING(f"Remaining listings missing market columns: {missing_market}"))
