import json
import time
from django.core.management.base import BaseCommand
from django.conf import settings
from openai import OpenAI
from core.models import Car, CarListing, CarPro, CarCon
from decimal import Decimal
import re
from django.db.models import Q

class Command(BaseCommand):
    help = "Master script to update ALL missing Car Specs, Pros/Cons, and Listing Descriptions using Groq AI."

    def handle(self, *args, **options):
        api_key = getattr(settings, "GROQ_API_KEY", None)
        
        if not api_key:
            self.stdout.write(self.style.ERROR("ERROR: GROQ_API_KEY is missing from settings.py!"))
            return
            
        client = OpenAI(
            api_key=api_key, 
            base_url="https://api.groq.com/openai/v1"
        )
        
        # ==========================================
        # PART 1: UPDATE ALL CAR SPECS & PROS/CONS
        # ==========================================
        cars_missing_data = Car.objects.filter(
            Q(engine_cc__isnull=True) |
            Q(expert_overview__isnull=True) | Q(expert_overview="")
        )
        
        if cars_missing_data.exists():
            self.stdout.write(self.style.WARNING(f"\n--- Found {cars_missing_data.count()} Car(s) missing Base Specs ---"))
            
            for car in cars_missing_data:
                title = f"{car.year} {car.make} {car.model}"
                self.stdout.write(f"Fetching specs for {title}...")
                
                prompt = f"""
                You are an expert automotive editor. Provide specs and a review for the {title}.
                Return ONLY a valid JSON object with these EXACT keys (flat JSON; spec values must be numeric only, no units):
                {{
                  "overview": "Concise overview",
                  "exterior": "Concise exterior",
                  "interior": "Concise interior",
                  "performance": "Concise performance",
                  "verdict": "Concise verdict",
                  "engine_cc": "2998",
                  "power_bhp": "473",
                  "torque_nm": "550",
                  "pros": ["Pro 1","Pro 2","Pro 3"],
                  "cons": ["Con 1","Con 2","Con 3"]
                }}
                """
                
                try:
                    resp = client.chat.completions.create(
                        model="llama-3.3-70b-versatile", 
                        messages=[
                            {"role": "system", "content": "You are a JSON-only data generator. Output valid JSON only."},
                            {"role": "user", "content": prompt},
                        ],
                        response_format={"type": "json_object"},
                    )
                    
                    data = json.loads(resp.choices[0].message.content)
                    
                    # ---- Parse and Save numeric specs safely ----
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
                        "engine_cc","power_bhp","torque_nm",
                        "expert_overview","expert_exterior","expert_interior",
                        "expert_performance","expert_verdict"
                    ])
                    
                    # Save Pros & Cons
                    CarPro.objects.filter(car=car).delete()
                    CarCon.objects.filter(car=car).delete()
                    for t in data.get("pros", [])[:3]: CarPro.objects.create(car=car, text=t[:200])
                    for t in data.get("cons", [])[:3]: CarCon.objects.create(car=car, text=t[:200])
                        
                    self.stdout.write(self.style.SUCCESS(f"  ✅ Specs updated for {title}"))
                    time.sleep(1) # Tiny pause to respect Groq API rate limits
                    
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"  ❌ Failed Specs for {title}: {e}"))
        else:
            self.stdout.write(self.style.SUCCESS("\n--- All base Car specs are already up to date! ---"))

        # ==========================================
        # PART 2: UPDATE ALL LISTING DESCRIPTIONS
        # ==========================================
        listings_missing_desc = CarListing.objects.filter(
            Q(description__isnull=True) | Q(description="")
        )
        
        if listings_missing_desc.exists():
            self.stdout.write(self.style.WARNING(f"\n--- Found {listings_missing_desc.count()} Listing(s) missing HTML Descriptions ---"))
            
            for lst in listings_missing_desc:
                title = f"{lst.car.year} {lst.car.make} {lst.car.model}"
                self.stdout.write(f"Writing description for {title}...")
                
                prompt = f"""
                You are an expert automotive journalist. Write a detailed 3-paragraph review for the {title}.
                Return ONLY a valid JSON object with the exact key "description".
                The description must contain HTML <p> tags for formatting.
                """
                
                try:
                    resp = client.chat.completions.create(
                        model="llama-3.3-70b-versatile",
                        messages=[
                            {"role": "system", "content": "You are a JSON-generating automotive AI. Output valid JSON only."},
                            {"role": "user", "content": prompt},
                        ],
                        response_format={"type": "json_object"},
                    )
                    
                    data = json.loads(resp.choices[0].message.content)
                    
                    lst.description = data.get("description", "")
                    lst.save(update_fields=["description"])
                    
                    self.stdout.write(self.style.SUCCESS(f"  ✅ Description written for {title}"))
                    time.sleep(1) # Tiny pause
                    
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"  ❌ Failed Description for {title}: {e}"))
        else:
            self.stdout.write(self.style.SUCCESS("\n--- All Listing descriptions are already up to date! ---"))

        self.stdout.write(self.style.SUCCESS("\n🎉 BATCH PROCESS COMPLETE! All database entries are full. 🎉"))
