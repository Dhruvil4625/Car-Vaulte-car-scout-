import random
import string
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Car, CarCon, CarListing, CarPro, Seller, Showroom, User


BRAND_CATALOG = {
    "Maruti Suzuki": {
        "city": "Ahmedabad",
        "state": "Gujarat",
        "models": [("Swift", 850000), ("Baleno", 980000), ("Brezza", 1250000), ("Grand Vitara", 1650000)],
    },
    "Hyundai": {
        "city": "Mumbai",
        "state": "Maharashtra",
        "models": [("i20", 980000), ("Verna", 1550000), ("Creta", 1850000), ("Alcazar", 2250000)],
    },
    "Tata": {
        "city": "Pune",
        "state": "Maharashtra",
        "models": [("Altroz", 980000), ("Nexon", 1450000), ("Harrier", 2450000), ("Safari", 2750000)],
    },
    "Mahindra": {
        "city": "Delhi",
        "state": "Delhi",
        "models": [("XUV300", 1350000), ("Scorpio-N", 2050000), ("XUV700", 2650000), ("Thar", 1850000)],
    },
    "Toyota": {
        "city": "Bengaluru",
        "state": "Karnataka",
        "models": [("Glanza", 980000), ("Urban Cruiser Hyryder", 2050000), ("Innova Hycross", 3250000), ("Fortuner", 4650000)],
    },
    "Kia": {
        "city": "Chennai",
        "state": "Tamil Nadu",
        "models": [("Sonet", 1350000), ("Seltos", 2050000), ("Carens", 1950000), ("EV6", 6500000)],
    },
    "Honda": {
        "city": "Hyderabad",
        "state": "Telangana",
        "models": [("Amaze", 980000), ("City", 1650000), ("Elevate", 1850000), ("City e:HEV", 2350000)],
    },
    "Skoda": {
        "city": "Jaipur",
        "state": "Rajasthan",
        "models": [("Slavia", 1650000), ("Kushaq", 1850000), ("Octavia", 3550000), ("Kodiaq", 4550000)],
    },
    "Volkswagen": {
        "city": "Kolkata",
        "state": "West Bengal",
        "models": [("Virtus", 1650000), ("Taigun", 1850000), ("Tiguan", 4050000), ("Polo GT", 1450000)],
    },
    "MG": {
        "city": "Lucknow",
        "state": "Uttar Pradesh",
        "models": [("Astor", 1650000), ("Hector", 2350000), ("ZS EV", 2850000), ("Comet EV", 950000)],
    },
    "Audi": {
        "city": "Ahmedabad",
        "state": "Gujarat",
        "models": [("A4", 5400000), ("Q3", 5200000), ("Q5", 7000000), ("e-tron", 11500000)],
    },
    "BMW": {
        "city": "Mumbai",
        "state": "Maharashtra",
        "models": [("3 Series", 6500000), ("5 Series", 7800000), ("X1", 5500000), ("iX1", 7000000)],
    },
    "Mercedes-Benz": {
        "city": "Delhi",
        "state": "Delhi",
        "models": [("A-Class", 5200000), ("C-Class", 6600000), ("GLA", 5700000), ("GLE", 10800000)],
    },
    "Volvo": {
        "city": "Pune",
        "state": "Maharashtra",
        "models": [("XC40", 5600000), ("XC60", 7000000), ("S90", 7400000), ("C40 Recharge", 6400000)],
    },
    "Land Rover": {
        "city": "Bengaluru",
        "state": "Karnataka",
        "models": [("Range Rover Evoque", 8200000), ("Discovery Sport", 7800000), ("Defender", 11000000), ("Range Rover Velar", 9200000)],
    },
}


BODY_TYPES = ["Hatchback", "Sedan", "SUV", "Coupe", "MPV"]
COLORS = ["White", "Black", "Silver", "Blue", "Grey", "Red"]
TRANSMISSIONS = ["Manual", "Automatic", "CVT", "DCT", "AMT"]


class Command(BaseCommand):
    help = "Seed at least N car listings for each brand with realistic market pricing details."

    def add_arguments(self, parser):
        parser.add_argument("--per-brand", type=int, default=25, help="Minimum listings to ensure per brand")
        parser.add_argument(
            "--brands",
            type=str,
            default="",
            help="Comma-separated brand names. If omitted, uses known catalog + existing DB brands.",
        )
        parser.add_argument("--seed", type=int, default=20260317, help="Random seed for reproducible generation")
        parser.add_argument("--dry-run", action="store_true", help="Show planned inserts without saving")
        parser.add_argument("--use-groq", action="store_true", help="Use Groq to enrich expert overview fields")

    def _brand_info(self, brand):
        if brand in BRAND_CATALOG:
            return BRAND_CATALOG[brand]
        return {
            "city": "Ahmedabad",
            "state": "Gujarat",
            "models": [
                (f"{brand} Prime", 1500000),
                (f"{brand} Sport", 2200000),
                (f"{brand} X", 2800000),
                (f"{brand} EV", 3200000),
            ],
        }

    def _is_luxury(self, brand):
        return brand in {"Audi", "BMW", "Mercedes-Benz", "Volvo", "Land Rover", "Porsche", "Jaguar"}

    def _new_vin(self, make):
        prefix = "".join(ch for ch in (make or "CAR").upper() if ch.isalnum())[:3].ljust(3, "X")
        chars = string.ascii_uppercase + string.digits
        while True:
            vin = prefix + "".join(random.choice(chars) for _ in range(14))
            if not Car.objects.filter(vin=vin).exists():
                return vin

    def _ensure_seller(self, brand):
        slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in brand).strip("-")
        email = f"seed-{slug}@vehiclevault.local"
        user = User.objects.filter(email=email).first()
        if not user:
            user = User.objects.create_user(
                email=email,
                password="SeedPass@123",
                name=f"{brand} Verified Seller",
                role=User.Role.SELLER,
                status=User.Status.ACTIVE,
            )
        else:
            changed = False
            if user.role != User.Role.SELLER:
                user.role = User.Role.SELLER
                changed = True
            if user.status != User.Status.ACTIVE:
                user.status = User.Status.ACTIVE
                changed = True
            if changed:
                user.save(update_fields=["role", "status", "updated_at"])

        Seller.objects.get_or_create(
            user=user,
            defaults={
                "dealership_name": f"{brand} Auto Hub",
                "location": self._brand_info(brand)["city"],
                "rating": Decimal("4.50"),
            },
        )
        return user

    def _ensure_showroom(self, brand, seller):
        info = self._brand_info(brand)
        city = info["city"]
        state = info["state"]
        name = f"{brand} Prime Showroom"
        showroom, _ = Showroom.objects.get_or_create(
            name=name,
            city=city,
            defaults={
                "state": state,
                "address": f"Main Auto Market, {city}",
                "map_query": f"{name} {city}",
                "seller": seller,
            },
        )
        if not showroom.seller:
            showroom.seller = seller
            showroom.save(update_fields=["seller", "updated_at"])
        return showroom

    def _price_bundle(self, base_price, year, is_luxury):
        age = max(0, 2026 - int(year))
        depreciation = 0.06 * age
        volatility = random.uniform(-0.08, 0.10)
        market = max(base_price * (1 - depreciation) * (1 + volatility), base_price * 0.45)

        rto_pct = 0.10 if market < 2000000 else (0.12 if market < 4000000 else 0.15)
        ins_pct = 0.025
        duty_pct = 0.15 if is_luxury else 0.0

        tax = market * rto_pct
        ins = market * ins_pct
        duty = market * duty_pct
        on_road = market + tax + ins + duty

        listing_price = market * random.uniform(0.93, 1.08)
        diff_pct = (listing_price - market) / market if market else 0
        if abs(diff_pct) <= 0.05:
            label = "Fair Price"
        elif diff_pct < -0.10:
            label = "Good Deal"
        elif diff_pct > 0.10:
            label = "Expensive"
        else:
            label = "Slightly Off"

        return {
            "market": round(market, 0),
            "tax": round(tax, 0),
            "insurance": round(ins, 0),
            "duty": round(duty, 0),
            "on_road": round(on_road, 0),
            "listing": round(listing_price, 0),
            "deal_label": label,
        }

    def _listing_description(self, car, pb):
        return (
            f"<p><strong>Market Snapshot:</strong> Estimated current market price for this "
            f"{car.year} {car.make} {car.model} is ₹{pb['market']:,.0f}. "
            f"AI fairness label: <strong>{pb['deal_label']}</strong>.</p>"
            f"<p><strong>On-road Breakdown:</strong> Tax ₹{pb['tax']:,.0f}, "
            f"Insurance ₹{pb['insurance']:,.0f}, Import Duty ₹{pb['duty']:,.0f}; "
            f"Expected total on-road cost ₹{pb['on_road']:,.0f}.</p>"
            f"<p>Well maintained vehicle with verified seller history, "
            f"clean ownership trail, and competitive pricing for its segment.</p>"
        )

    def _enrich_with_groq(self, use_groq, car):
        if not use_groq:
            return
        api_key = (getattr(settings, "GROQ_API_KEY", "") or "").strip()
        if not api_key:
            return
        if car.expert_overview and car.expert_exterior and car.expert_interior and car.expert_performance and car.expert_verdict:
            return

        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
            prompt = (
                "Return strict JSON with keys overview, exterior, interior, performance, verdict, pros, cons "
                f"for {car.year} {car.make} {car.model}. "
                "Keep each text concise and practical for Indian buyers."
            )
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": "You are a JSON-only automotive assistant."},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            import json

            data = json.loads(resp.choices[0].message.content)
            car.expert_overview = data.get("overview") or car.expert_overview
            car.expert_exterior = data.get("exterior") or car.expert_exterior
            car.expert_interior = data.get("interior") or car.expert_interior
            car.expert_performance = data.get("performance") or car.expert_performance
            car.expert_verdict = data.get("verdict") or car.expert_verdict
            car.save(
                update_fields=[
                    "expert_overview",
                    "expert_exterior",
                    "expert_interior",
                    "expert_performance",
                    "expert_verdict",
                ]
            )

            if data.get("pros"):
                CarPro.objects.filter(car=car).delete()
                for t in data.get("pros", [])[:3]:
                    CarPro.objects.create(car=car, text=str(t)[:200])
            if data.get("cons"):
                CarCon.objects.filter(car=car).delete()
                for t in data.get("cons", [])[:3]:
                    CarCon.objects.create(car=car, text=str(t)[:200])
        except Exception:
            return

    @transaction.atomic
    def handle(self, *args, **options):
        target = max(1, int(options["per_brand"]))
        dry_run = bool(options["dry_run"])
        use_groq = bool(options["use_groq"])
        random.seed(int(options["seed"]))

        explicit_brands = [b.strip() for b in (options.get("brands") or "").split(",") if b.strip()]
        existing_brands = list(Car.objects.values_list("make", flat=True).distinct())
        brands = explicit_brands or sorted(set(list(BRAND_CATALOG.keys()) + existing_brands))

        self.stdout.write(self.style.WARNING(f"Ensuring >= {target} listings per brand across {len(brands)} brand(s)..."))

        added_total = 0
        touched = 0

        for brand in brands:
            current = CarListing.objects.filter(car__make__iexact=brand).count()
            missing = max(0, target - current)
            if missing == 0:
                self.stdout.write(self.style.SUCCESS(f"{brand}: already has {current} listing(s)."))
                continue

            touched += 1
            self.stdout.write(self.style.WARNING(f"{brand}: has {current}, adding {missing}."))

            if dry_run:
                added_total += missing
                continue

            seller = self._ensure_seller(brand)
            showroom = self._ensure_showroom(brand, seller)
            info = self._brand_info(brand)
            models = info["models"]
            is_luxury = self._is_luxury(brand)

            for i in range(missing):
                model_name, base_price = models[i % len(models)]
                year = random.choice([2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026])
                fuel = random.choice(["Petrol", "Diesel", "Hybrid", "Electric"])
                body = random.choice(BODY_TYPES)
                transmission = random.choice(TRANSMISSIONS)
                mileage = random.randint(1500, 95000)
                if year >= 2025:
                    mileage = random.randint(50, 12000)
                if fuel == "Electric":
                    mileage = random.randint(100, 60000)

                pb = self._price_bundle(base_price=base_price, year=year, is_luxury=is_luxury)

                car = Car.objects.create(
                    vin=self._new_vin(brand),
                    make=brand,
                    model=model_name,
                    year=year,
                    color=random.choice(COLORS),
                    fuel_type=fuel,
                    transmission=transmission,
                    mileage=mileage,
                    body_type=body,
                    engine_cc=(0 if fuel == "Electric" else random.choice([1197, 1498, 1997, 2998])),
                    power_bhp=(Decimal(str(random.choice([88.0, 115.0, 150.0, 190.0, 258.0, 375.0])))),
                    torque_nm=(Decimal(str(random.choice([113.0, 200.0, 250.0, 320.0, 450.0, 650.0])))),
                    gncap_rating=random.choice([3, 4, 5]),
                    expert_overview=f"{brand} {model_name} balances comfort, features, and ownership value.",
                    expert_exterior="Modern styling with practical dimensions for city and highway driving.",
                    expert_interior="Cabin offers usable space, infotainment features, and daily comfort.",
                    expert_performance="Refined power delivery and stable highway dynamics for Indian roads.",
                    expert_verdict="A strong segment option when value, safety, and reliability are priorities.",
                )

                CarPro.objects.bulk_create(
                    [
                        CarPro(car=car, text="Balanced performance for daily and highway use"),
                        CarPro(car=car, text="Competitive feature list with safety equipment"),
                        CarPro(car=car, text="Good resale and service support in major cities"),
                    ]
                )
                CarCon.objects.bulk_create(
                    [
                        CarCon(car=car, text="Top variants can feel expensive"),
                        CarCon(car=car, text="Real-world mileage varies by traffic conditions"),
                        CarCon(car=car, text="Waiting periods may apply in popular colors"),
                    ]
                )

                CarListing.objects.create(
                    car=car,
                    seller=seller,
                    price=Decimal(str(pb["listing"])),
                    market_price=Decimal(str(pb["market"])),
                    tax_amount=Decimal(str(pb["tax"])),
                    insurance_amount=Decimal(str(pb["insurance"])),
                    import_duty=Decimal(str(pb["duty"])),
                    on_road_price=Decimal(str(pb["on_road"])),
                    deal_label=pb["deal_label"],
                    mileage=mileage,
                    description=self._listing_description(car, pb),
                    status=CarListing.Status.ACTIVE,
                    showroom=showroom,
                )

                self._enrich_with_groq(use_groq=use_groq, car=car)
                added_total += 1

        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"Dry-run complete. Would add {added_total} listing(s)."))
            return

        self.stdout.write(self.style.SUCCESS(f"Done. Added {added_total} listing(s) across {touched} brand(s)."))