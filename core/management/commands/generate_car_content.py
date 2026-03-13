import json
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import models
from openai import OpenAI
from core.models import Car, CarPro, CarCon
from decimal import Decimal
import re

class Command(BaseCommand):
    help = "Generates complete specs and expert content using Groq"

    def add_arguments(self, parser):
        parser.add_argument("--make", type=str, help="Make of the car to update", default=None)
        parser.add_argument("--model", type=str, help="Model filter (optional)", default=None)
        parser.add_argument("--year", type=int, help="Year filter (optional)", default=None)
        parser.add_argument("--vin", type=str, help="Target a single VIN (optional)", default=None)
        parser.add_argument("--force", action="store_true", help="Force refresh even if specs exist")

    def handle(self, *args, **options):
        api_key = getattr(settings, "GROQ_API_KEY", None)
        
        if not api_key:
            self.stdout.write(self.style.ERROR("ERROR: GROQ_API_KEY is missing!"))
            return
            
        client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
        
        # 1. Target the cars
        vin = options.get("vin")
        make = options.get("make")
        model = options.get("model")
        year = options.get("year")
        force = bool(options.get("force"))

        if vin:
            cars = Car.objects.filter(vin=vin)
            if not cars.exists():
                self.stdout.write(self.style.ERROR(f"No car found for VIN: {vin}"))
                return
        elif make or model or year:
            qs = Car.objects.all()
            if make:
                qs = qs.filter(make__icontains=make)
            if model:
                qs = qs.filter(model__icontains=model)
            if year:
                qs = qs.filter(year=year)
            cars = qs
            if not cars.exists():
                self.stdout.write(self.style.ERROR("No cars found for given filters"))
                return
        else:
            # If no filters provided, update cars that are missing any expert section or engine spec
            cars = Car.objects.filter(
                (models.Q(engine_cc__isnull=True)) |
                (models.Q(expert_overview__isnull=True) | models.Q(expert_overview="")) |
                (models.Q(expert_exterior__isnull=True) | models.Q(expert_exterior="")) |
                (models.Q(expert_interior__isnull=True) | models.Q(expert_interior="")) |
                (models.Q(expert_performance__isnull=True) | models.Q(expert_performance="")) |
                (models.Q(expert_verdict__isnull=True) | models.Q(expert_verdict=""))
            )
            if not cars.exists():
                self.stdout.write(self.style.SUCCESS("All cars have specs!"))
                return
                
        for car in cars:
            title = f"{car.year} {car.make} {car.model}"
            self.stdout.write(f"\nAsking Groq to research: {title}...")
            
            if not force:
                # Skip if everything already present
                already = all([
                    car.expert_overview, car.expert_exterior, car.expert_interior,
                    car.expert_performance, car.expert_verdict, car.engine_cc
                ])
                if already:
                    self.stdout.write(self.style.WARNING("Skipping (already populated). Use --force to refresh."))
                    continue
            
            # 2. Strict, flat JSON Prompt
            prompt = f"""
            You are an expert automotive editor. Provide specs and a review for {title}.
            Return ONLY a valid JSON object with these EXACT keys (flat JSON, no extra keys):
            {{
              "overview": "A concise professional overview paragraph",
              "exterior": "Concise exterior paragraph",
              "interior": "Concise interior paragraph",
              "performance": "Concise performance/drivability paragraph",
              "verdict": "Concise verdict paragraph",
              "engine_cc": "2998",
              "power_bhp": "473",
              "torque_nm": "550",
              "pros": ["Pro 1", "Pro 2", "Pro 3"],
              "cons": ["Con 1", "Con 2", "Con 3"]
            }}
            Spec values must contain only numbers (no units like cc/bhp/Nm).
            """
            
            try:
                resp = client.chat.completions.create(
                    model="llama-3.3-70b-versatile", 
                    messages=[
                        {"role": "system", "content": "You are a JSON-only data generator."},
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1
                )
                
                data = json.loads(resp.choices[0].message.content)
                
                # 3. DEBUG: Print exactly what the AI found
                self.stdout.write(self.style.WARNING(f"--> Found Engine: {data.get('engine_cc')} cc"))
                self.stdout.write(self.style.WARNING(f"--> Found Power: {data.get('power_bhp')} bhp"))
                self.stdout.write(self.style.WARNING(f"--> Found Torque: {data.get('torque_nm')} Nm"))
                
                # 4. Save Specs to the Car with safe numeric parsing
                def _to_int(val):
                    try:
                        if val is None:
                            return None
                        s = str(val).strip()
                        if not s:
                            return None
                        s = re.sub(r"[^\d\-]", "", s)
                        return int(s)
                    except Exception:
                        return None
                def _to_decimal(val):
                    try:
                        if val is None:
                            return None
                        s = str(val).strip()
                        if not s:
                            return None
                        s = re.sub(r"[^\d\.\-]", "", s)
                        return Decimal(s)
                    except Exception:
                        return None

                car.engine_cc = _to_int(data.get("engine_cc"))
                car.power_bhp = _to_decimal(data.get("power_bhp"))
                car.torque_nm = _to_decimal(data.get("torque_nm"))
                car.expert_overview = data.get("overview", "") or car.expert_overview
                car.expert_exterior = data.get("exterior", "") or car.expert_exterior
                car.expert_interior = data.get("interior", "") or car.expert_interior
                car.expert_performance = data.get("performance", "") or car.expert_performance
                car.expert_verdict = data.get("verdict", "") or car.expert_verdict
                car.save(update_fields=[
                    "engine_cc", "power_bhp", "torque_nm",
                    "expert_overview", "expert_exterior", "expert_interior",
                    "expert_performance", "expert_verdict"
                ])
                
                # 5. Save Pros & Cons
                CarPro.objects.filter(car=car).delete()
                CarCon.objects.filter(car=car).delete()
                
                for t in data.get("pros", [])[:3]:
                    CarPro.objects.create(car=car, text=t[:200])
                for t in data.get("cons", [])[:3]:
                    CarCon.objects.create(car=car, text=t[:200])
                    
                self.stdout.write(self.style.SUCCESS(f"✅ Successfully updated Database for {title}!"))
                
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"❌ Failed {title}: {e}"))
