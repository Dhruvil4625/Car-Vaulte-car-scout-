import json
from django.core.management.base import BaseCommand
from django.conf import settings
from openai import OpenAI
from core.models import CarListing

class Command(BaseCommand):
    help = "Generates expert reviews for listings using Groq"

    def handle(self, *args, **kwargs):
        # FIX 1: Look for the GROQ key
        api_key = getattr(settings, "GROQ_API_KEY", "")
        if not api_key:
            self.stdout.write(self.style.ERROR("GROQ_API_KEY missing from settings.py"))
            return
            
        # FIX 2: Point to Groq's API
        client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
        
        listings = CarListing.objects.filter(description__isnull=True)
        if not listings.exists():
            self.stdout.write(self.style.SUCCESS("No pending listings"))
            return
            
        for lst in listings:
            car_name = f"{lst.car.year} {lst.car.make} {lst.car.model}"
            prompt = (
                "You are an expert automotive journalist. "
                f"Write an expert review and pros/cons for the {car_name}. "
                'Return JSON with keys "description","pros","cons". '
                'Description must contain HTML <p> tags. '
                "Pros and cons must be arrays with 3 short items each."
            )
            try:
                # FIX 3: Use the fast, free Groq model
                resp = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {"role": "system", "content": "You are a JSON-generating automotive AI. Output valid JSON only."},
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                )
                data = json.loads(resp.choices[0].message.content)
                lst.description = data.get("description") or ""
                lst.save(update_fields=["description"])
                self.stdout.write(self.style.SUCCESS(f"Updated {car_name}"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Failed {car_name}: {e}"))