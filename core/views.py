import os
import random
from datetime import timedelta
import razorpay

from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Q, Count, Avg
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_exempt
from django.utils.html import strip_tags
from django.contrib.auth import get_user_model
from django.http import JsonResponse, HttpResponse
from django.core.mail import send_mail
from django.conf import settings
from django.urls import reverse
from django.db import transaction
from django.core.cache import cache
from django.utils import timezone
import csv
import json
from urllib import request as urlrequest
from urllib.error import URLError, HTTPError

from core.email_utils import send_email_html, send_email_html_async
from .forms import UserSignupForm, CarListingForm, CarForm, UpcomingArrivalForm, UserLoginForm, InspectionForm
from .models import Car, CarListing, Message, TestDrive, Buyer, Seller, CarListingImage, Showroom, UpcomingArrival, CarListingAsset, DealRating
from .ai_utils import recommend_similar_listings, session_aware_recs, collaborative_recs, dealer_matches_for_buyer, image_condition_score, chatbot_query, price_fairness_info

User = get_user_model()

# Razorpay Client Initialization
RAZORPAY_KEY_ID = getattr(settings, "RAZORPAY_KEY_ID", "") or os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = getattr(settings, "RAZORPAY_KEY_SECRET", "") or os.getenv("RAZORPAY_KEY_SECRET", "")
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)) if (RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET) else None


def _marketing_brochure_attachments(user=None):
    # Try to load the pre-generated high-quality PDF from disk first
    try:
        pdf_path = os.path.join(settings.BASE_DIR, "Vehical Vault.pdf")
        if os.path.exists(pdf_path):
            with open(pdf_path, "rb") as f:
                content = f.read()
            return [("Vehicle_Vault_Brochure.pdf", content, "application/pdf")]
    except Exception:
        pass

    # Fallback to generating one on the fly if file is missing
    try:
        from core.pdf_utils import build_brochure_pdf
        brochure = build_brochure_pdf(user=user, base_dir=getattr(settings, "BASE_DIR", None))
        if brochure:
            return [("Vehicle_Vault_Brochure.pdf", brochure, "application/pdf")]
    except Exception:
        pass
    return None


def _rating_stats_for_user(user):
    stats = DealRating.objects.filter(rated_user=user).aggregate(avg=Avg("score"), count=Count("rating_id"))
    avg = stats.get("avg") or 0
    count = stats.get("count") or 0
    return {
        "avg": round(float(avg), 2) if avg else 0,
        "count": count,
    }


def _sync_seller_rating(user):
    try:
        seller = Seller.objects.get(user=user)
    except Seller.DoesNotExist:
        return
    stats = _rating_stats_for_user(user)
    seller.rating = stats["avg"]
    seller.save(update_fields=["rating"])


def _apply_ai_estimates_to_listings(listings):
    groups = {}
    for l in listings:
        car = getattr(l, "car", None)
        key = (getattr(car, "make", ""), getattr(car, "model", ""), getattr(car, "year", None))
        try:
            p = float(l.price)
        except Exception:
            p = None
        if key not in groups:
            groups[key] = {"sum": 0.0, "cnt": 0}
        if p:
            groups[key]["sum"] += p
            groups[key]["cnt"] += 1
            
    imported_brands = {"BMW", "Mercedes-Benz", "Audi", "Volkswagen", "Skoda", "Porsche", "Volvo", "Jaguar", "Land Rover"}
    for l in listings:
        car = getattr(l, "car", None)
        make = getattr(car, "make", "") or ""
        key = (getattr(car, "make", ""), getattr(car, "model", ""), getattr(car, "year", None))
        try:
            price_val = float(l.price)
        except Exception:
            price_val = 0.0
        grp = groups.get(key, {"sum": 0.0, "cnt": 0})
        market = (grp["sum"] / grp["cnt"]) if grp["cnt"] else price_val
        tax_pct = 0.10 if price_val < 2000000 else (0.12 if price_val < 4000000 else 0.15)
        insurance_pct = 0.025
        duty_pct = 0.15 if make in imported_brands else 0.0
        l.ai_market = round(market or 0.0, 0)
        l.ai_tax = round(price_val * tax_pct, 0)
        l.ai_ins = round(price_val * insurance_pct, 0)
        l.ai_duty = round(price_val * duty_pct, 0)
        try:
            l.ai_total = round(price_val + l.ai_tax + l.ai_ins + l.ai_duty, 0)
        except Exception:
            l.ai_total = None
        try:
            diff = (price_val - (market or 0.0)) / (market or (price_val or 1.0))
            if abs(diff) <= 0.05:
                lbl = "Fair Price"
            elif diff < -0.10:
                lbl = "Good Deal"
            elif diff > 0.10:
                lbl = "Expensive"
            else:
                lbl = "Slightly Off"
            l.ai_deal_label = lbl
        except Exception:
            l.ai_deal_label = None


def _apply_ai_estimates_to_cars(cars):
    imported_brands = {"BMW", "Mercedes-Benz", "Audi", "Volkswagen", "Skoda", "Porsche", "Volvo", "Jaguar", "Land Rover"}
    for c in cars:
        try:
            prices = [float(lst.price) for lst in getattr(c, "listings").all() if getattr(lst, "price", None)]
        except Exception:
            prices = []
        market = sum(prices) / len(prices) if prices else 0.0
        tax_pct = 0.10 if market < 2000000 else (0.12 if market < 4000000 else 0.15)
        insurance_pct = 0.025
        duty_pct = 0.15 if getattr(c, "make", "") in imported_brands else 0.0
        c.ai_market = round(market or 0.0, 0)
        c.ai_tax = round(market * tax_pct, 0)
        c.ai_ins = round(market * insurance_pct, 0)
        c.ai_duty = round(market * duty_pct, 0)
        try:
            c.ai_total = round(c.ai_market + c.ai_tax + c.ai_ins + c.ai_duty, 0)
        except Exception:
            c.ai_total = None


def CompareCarsView(request):
    vin1 = (request.GET.get("vin1") or "").strip()
    vin2 = (request.GET.get("vin2") or "").strip()
    car1 = None
    car2 = None
    
    if vin1:
        try:
            car1 = Car.objects.get(vin=vin1)
        except Car.DoesNotExist:
            try:
                # Fallback: if a listing id was supplied by mistake, resolve to car
                lst = CarListing.objects.select_related("car").get(listing_id=vin1)
                car1 = lst.car
            except Exception:
                car1 = None
                
    if vin2:
        try:
            car2 = Car.objects.get(vin=vin2)
        except Car.DoesNotExist:
            try:
                lst = CarListing.objects.select_related("car").get(listing_id=vin2)
                car2 = lst.car
            except Exception:
                car2 = None

    def _norm(s):
        return (s or "").strip().lower()

    FUEL_RANK = {"electric": 5, "ev": 5, "hybrid": 4, "petrol": 3, "gasoline": 3, "diesel": 2, "cng": 1}
    TRANS_RANK = {
        "automatic": 4,
        "automatic (torque converter)": 4,
        "dct": 4,
        "dual clutch": 4,
        "cvt": 3,
        "amt": 2,
        "manual": 1,
    }
    BODY_RANK = {"suv": 5, "sedan": 4, "hatchback": 3, "mpv": 3, "coupe": 2, "pickup": 3}

    def _fuel_score(car):
        if not car:
            return 0
        return FUEL_RANK.get(_norm(getattr(car, "fuel_type", None)), 0)

    def _trans_score(car):
        if not car:
            return 0
        t = _norm(getattr(car, "transmission", None))
        if t.startswith("automatic"):
            return 4
        return TRANS_RANK.get(t, 0)

    def _body_score(car):
        if not car:
            return 0
        return BODY_RANK.get(_norm(getattr(car, "body_type", None)), 0)

    def _year_score(car):
        if not car:
            return 0
        try:
            return int(getattr(car, "year", 0) or 0)
        except Exception:
            return 0

    def _mileage_score(car):
        if not car:
            return 0
        m = getattr(car, "mileage", None)
        try:
            return -int(m or 0)
        except Exception:
            return 0

    from django.db.models import Avg, Count
    dom = {
        "fuel": 1 if _fuel_score(car1) > _fuel_score(car2) else (2 if _fuel_score(car2) > _fuel_score(car1) else 0),
        "trans": 1 if _trans_score(car1) > _trans_score(car2) else (2 if _trans_score(car2) > _trans_score(car1) else 0),
        "body": 1 if _body_score(car1) > _body_score(car2) else (2 if _body_score(car2) > _body_score(car1) else 0),
        "year": 1 if _year_score(car1) > _year_score(car2) else (2 if _year_score(car2) > _year_score(car1) else 0),
        "mileage": 1 if _mileage_score(car1) > _mileage_score(car2) else (2 if _mileage_score(car2) > _mileage_score(car1) else 0),
    }
    def _num(val):
        try:
            return float(val or 0.0)
        except Exception:
            return 0.0
    dom.update({
        "engine": 1 if _num(getattr(car1, "engine_cc", None)) > _num(getattr(car2, "engine_cc", None)) else (2 if _num(getattr(car2, "engine_cc", None)) > _num(getattr(car1, "engine_cc", None)) else 0),
        "power": 1 if _num(getattr(car1, "power_bhp", None)) > _num(getattr(car2, "power_bhp", None)) else (2 if _num(getattr(car2, "power_bhp", None)) > _num(getattr(car1, "power_bhp", None)) else 0),
        "torque": 1 if _num(getattr(car1, "torque_nm", None)) > _num(getattr(car2, "torque_nm", None)) else (2 if _num(getattr(car2, "torque_nm", None)) > _num(getattr(car1, "torque_nm", None)) else 0),
        "safety": 1 if _num(getattr(car1, "gncap_rating", None)) > _num(getattr(car2, "gncap_rating", None)) else (2 if _num(getattr(car2, "gncap_rating", None)) > _num(getattr(car1, "gncap_rating", None)) else 0),
    })
    # Market averages by brand/model/year
    avg1 = avg2 = market_year_avg = None
    try:
        if car1:
            a1 = CarListing.objects.filter(car__make__iexact=car1.make, car__model__iexact=car1.model, car__year=car1.year).aggregate(avg=Avg("price"), cnt=Count("listing_id"))
            avg1 = float(a1.get("avg") or 0.0)
        if car2:
            a2 = CarListing.objects.filter(car__make__iexact=car2.make, car__model__iexact=car2.model, car__year=car2.year).aggregate(avg=Avg("price"), cnt=Count("listing_id"))
            avg2 = float(a2.get("avg") or 0.0)
        year_filter = car1.year if car1 else (car2.year if car2 else None)
        if year_filter:
            market_year_avg = float(CarListing.objects.filter(car__year=year_filter).aggregate(avg=Avg("price")).get("avg") or 0.0)
    except Exception:
        pass
    # Optional EPA fuel economy mapping
    epa_map = {
        ("BMW","M4",2021): {"comb_kmpl": 9.5},
        ("Audi","A4",2020): {"comb_kmpl": 14.2},
        ("Toyota","Camry",2021): {"comb_kmpl": 18.0},
    }
    def _epa(car):
        if not car:
            return None
        k = ((getattr(car, "make", "") or "").strip(), (getattr(car, "model", "") or "").strip(), int(getattr(car, "year", 0) or 0))
        return epa_map.get(k)
    epa1 = _epa(car1)
    epa2 = _epa(car2)
    chart = {
        "labels": ["Engine (cc)", "Power (bhp)", "Torque (Nm)", "Safety (NCAP)"],
        "car1": [ _num(getattr(car1, "engine_cc", None)), _num(getattr(car1, "power_bhp", None)), _num(getattr(car1, "torque_nm", None)), _num(getattr(car1, "gncap_rating", None)) ] if car1 else [],
        "car2": [ _num(getattr(car2, "engine_cc", None)), _num(getattr(car2, "power_bhp", None)), _num(getattr(car2, "torque_nm", None)), _num(getattr(car2, "gncap_rating", None)) ] if car2 else [],
        "avg1": avg1,
        "avg2": avg2,
        "market_year_avg": market_year_avg,
    }
    
    cars = Car.objects.all().prefetch_related("listings").order_by("make", "model", "year")
    return render(request, "cars/compare.html", {"cars": cars, "car1": car1, "car2": car2, "vin1": vin1, "vin2": vin2, "dom": dom, "chart": chart, "epa1": epa1, "epa2": epa2})


def HomeView(request):
    top_listings = CarListing.objects.select_related("car", "seller").prefetch_related("images").order_by("-created_at")[:8]
    try:
        _apply_ai_estimates_to_listings(top_listings)
    except Exception:
        pass
        
    makes = list(Car.objects.values_list("make", flat=True).distinct())
    logos = {
        "BMW": "https://cdn-icons-png.flaticon.com/512/732/732221.png",
        "Mercedes-Benz": "https://cdn-icons-png.flaticon.com/512/882/882731.png",
        "Audi": "https://cdn-icons-png.flaticon.com/512/882/882702.png",
        "Volkswagen": "https://cdn-icons-png.flaticon.com/512/882/882747.png",
        "Maruti Suzuki": "https://cdn-icons-png.flaticon.com/512/882/882744.png",
        "Hyundai": "https://cdn-icons-png.flaticon.com/512/882/882719.png",
        "Kia": "https://cdn-icons-png.flaticon.com/512/882/882724.png",
        "Toyota": "https://cdn-icons-png.flaticon.com/512/882/882735.png",
        "Tata": "https://cdn-icons-png.flaticon.com/512/882/882743.png",
        "Skoda": "https://cdn-icons-png.flaticon.com/512/882/882745.png",
        "Honda": "https://cdn-icons-png.flaticon.com/512/882/882716.png",
    }
    domestic = {"Maruti Suzuki", "Hyundai", "Kia", "Tata", "Mahindra"}

    def slugify_brand(s):
        return (s or "").strip().lower().replace(" ", "-")

    brands = []
    for m in makes:
        brands.append({
            "name": m,
            "slug": slugify_brand(m),
            "logo": logos.get(m, "https://cdn-icons-png.flaticon.com/512/741/741407.png"),
            "is_domestic": m in domestic,
        })
        
    ints = [b for b in brands if not b["is_domestic"]]
    doms = [b for b in brands if b["is_domestic"]]
    return render(request, "home/index.html", {"listings": top_listings, "brands_international": ints, "brands_domestic": doms})


def CarsListView(request):
    qs = Car.objects.all().prefetch_related("listings__images").order_by("-year", "make", "model")
    fuel = request.GET.get("fuel") or request.GET.get("fuel_type") or ""
    q = request.GET.get("q") or ""
    brand = request.GET.get("brand") or ""
    model = request.GET.get("model") or ""
    year = request.GET.get("year") or ""
    body = request.GET.get("body") or request.GET.get("body_type") or ""
    
    synonyms = {
        "mercedes": "Mercedes-Benz",
        "mercedies": "Mercedes-Benz",
        "benz": "Mercedes-Benz",
        "vw": "Volkswagen",
        "volkswagon": "Volkswagen",
        "maruti": "Maruti Suzuki",
        "suzuki": "Maruti Suzuki",
        "hyundai": "Hyundai",
        "kia": "Kia",
        "toyota": "Toyota",
        "tata": "Tata",
        "bmw": "BMW",
        "skoda": "Skoda",
        "honda": "Honda",
        "audi": "Audi",
    }
    
    bnorm = (brand or "").strip().lower()
    if bnorm in synonyms:
        brand = synonyms[bnorm]
    if fuel:
        qs = qs.filter(fuel_type__iexact=fuel)
    if q:
        qs = qs.filter(Q(make__icontains=q) | Q(model__icontains=q) | Q(color__icontains=q))
    if brand:
        qs = qs.filter(make__iexact=brand)
    if model:
        qs = qs.filter(model__iexact=model)
    if year:
        qs = qs.filter(year=year)
    if body:
        qs = qs.filter(body_type__icontains=body)
        
    try:
        _apply_ai_estimates_to_cars(qs)
    except Exception:
        pass
    
    # Dropdown options
    all_makes = Car.objects.values_list('make', flat=True).distinct().order_by('make')
    all_models = Car.objects.filter(make__iexact=brand).values_list('model', flat=True).distinct().order_by('model') if brand else []
    all_years = Car.objects.values_list('year', flat=True).distinct().order_by('-year')
        
    return render(request, "cars/list.html", {
        "cars": qs, 
        "fuel": fuel, 
        "brand": brand, 
        "model": model, 
        "year": year,
        "q": q, 
        "body": body,
        "all_makes": all_makes,
        "all_models": all_models,
        "all_years": all_years,
    })


def BrandView(request, brand_slug):
    synonyms = {
        "mercedes": "Mercedes-Benz",
        "mercedes-benz": "Mercedes-Benz",
        "benz": "Mercedes-Benz",
        "vw": "Volkswagen",
        "volkswagen": "Volkswagen",
        "maruti": "Maruti Suzuki",
        "maruti-suzuki": "Maruti Suzuki",
    }
    raw = (brand_slug or "").lower()
    brand = synonyms.get(raw, raw.replace("-", " ").title())
    
    qs = CarListing.objects.select_related("car", "seller").prefetch_related("images").filter(car__make__iexact=brand)
    ec_min = 100000
    ec_max = 2000000
    md_max = 4000000
    
    economy = qs.filter(price__gte=ec_min, price__lt=ec_max).order_by("price")[:24]
    moderate = qs.filter(price__gte=ec_max, price__lt=md_max).order_by("price")[:24]
    premium = qs.filter(price__gte=md_max).order_by("-price")[:24]
    arrivals = qs.order_by("-created_at")[:24]
    all_list = qs.order_by("-created_at")[:48]
    
    models = list(Car.objects.filter(make__iexact=brand).values_list("model", flat=True).distinct()[:12])
    logo = None
    
    try:
        _apply_ai_estimates_to_listings(economy)
        _apply_ai_estimates_to_listings(moderate)
        _apply_ai_estimates_to_listings(premium)
        _apply_ai_estimates_to_listings(arrivals)
        _apply_ai_estimates_to_listings(all_list)
    except Exception:
        pass
        
    return render(request, "cars/brand.html", {"brand": brand, "logo": logo, "top_models": models, "premium": premium, "economy": economy, "moderate": moderate, "arrivals": arrivals, "listings": all_list})


def AllCarsListView(request):
    qs = CarListing.objects.select_related("car", "seller").prefetch_related("images").order_by("-created_at")
    price_ranges = request.GET.getlist("price")
    fuels = request.GET.getlist("fuel")
    bodies = request.GET.getlist("body")
    trans = request.GET.getlist("trans")
    cats = request.GET.getlist("category")
    brand = request.GET.get("brand") or ""
    model = request.GET.get("model") or ""
    year = request.GET.get("year") or ""
    
    if brand:
        qs = qs.filter(car__make__iexact=brand)
    if model:
        qs = qs.filter(car__model__iexact=model)
    if year:
        qs = qs.filter(car__year=year)
        
    for r in price_ranges:
        try:
            if r.endswith("+"):
                low = float(r[:-1])
                qs = qs.filter(price__gte=low)
            elif "-" in r:
                a, b = r.split("-")
                qs = qs.filter(price__gte=float(a), price__lte=float(b))
        except Exception:
            pass
            
    if fuels:
        qs = qs.filter(car__fuel_type__in=fuels)
    if bodies:
        qs = qs.filter(car__body_type__in=bodies)
    if trans:
        qs = qs.filter(car__transmission__in=trans)
    if cats:
        from django.db.models import Q as _Q
        ec_min = 100000
        ec_max = 2000000
        md_max = 4000000
        qcat = _Q()
        for c in cats:
            if c == "Economy":
                qcat |= _Q(price__gte=ec_min, price__lt=ec_max)
            elif c == "Moderate":
                qcat |= _Q(price__gte=ec_max, price__lt=md_max)
            elif c == "Premium":
                qcat |= _Q(price__gte=md_max)
        if qcat:
            qs = qs.filter(qcat)
            
    listings = qs.distinct()[:60]
    
    try:
        _apply_ai_estimates_to_listings(listings)
    except Exception:
        pass
        
    price_options = ["0-500000", "500000-1500000", "1500000+"]
    fuel_options = ["EV", "Petrol", "Diesel", "Hybrid"]
    body_options = ["SUV", "Sedan", "Hatchback", "Luxury"]
    trans_options = ["Manual", "Automatic", "AMT", "CVT", "DCT"]
    category_options = ["Economy", "Moderate", "Premium"]

    # Dropdown options
    all_makes = Car.objects.values_list('make', flat=True).distinct().order_by('make')
    all_models = Car.objects.filter(make__iexact=brand).values_list('model', flat=True).distinct().order_by('model') if brand else []
    all_years = Car.objects.values_list('year', flat=True).distinct().order_by('-year')
    
    ctx = {
        "listings": listings,
        "brand": brand,
        "model": model,
        "year": year,
        "price_options": price_options,
        "fuel_options": fuel_options,
        "body_options": body_options,
        "trans_options": trans_options,
        "category_options": category_options,
        "price_selected": price_ranges,
        "fuels_selected": fuels,
        "bodies_selected": bodies,
        "trans_selected": trans,
        "cats_selected": cats,
        "all_makes": all_makes,
        "all_models": all_models,
        "all_years": all_years,
    }
    return render(request, "cars/all.html", ctx)


def ListingsListView(request):
    qs = CarListing.objects.select_related("car", "seller").prefetch_related("images").order_by("-created_at")
    q = request.GET.get("q") or ""
    budget = request.GET.get("budget") or ""
    fuel = request.GET.get("fuel") or ""
    brand = request.GET.get("brand") or ""
    model = request.GET.get("model") or ""
    year = request.GET.get("year") or ""
    city = request.GET.get("city") or ""
    
    if q:
        qs = qs.filter(Q(car__make__icontains=q) | Q(car__model__icontains=q) | Q(description__icontains=q) | Q(seller__email__icontains=q))
    if brand:
        qs = qs.filter(car__make__iexact=brand)
    if model:
        qs = qs.filter(car__model__iexact=model)
    if year:
        qs = qs.filter(car__year=year)
    if budget and "-" in budget:
        parts = budget.split("-")
        try:
            low = float(parts[0])
            high = float(parts[1])
            qs = qs.filter(price__gte=low, price__lte=high)
        except ValueError:
            pass
    if fuel:
        qs = qs.filter(car__fuel_type__iexact=fuel)
        
    listings = qs[:50]
    
    try:
        _apply_ai_estimates_to_listings(listings)
    except Exception:
        pass
        
    try:
        from .models import Showroom
        showrooms = Showroom.objects.all()
        dealer_matches = dealer_matches_for_buyer(city, listings, showrooms, top_k=5)
    except Exception:
        dealer_matches = []
        
    # Dropdown options
    all_makes = Car.objects.values_list('make', flat=True).distinct().order_by('make')
    all_models = Car.objects.filter(make__iexact=brand).values_list('model', flat=True).distinct().order_by('model') if brand else []
    all_years = Car.objects.values_list('year', flat=True).distinct().order_by('-year')

    return render(request, "listings/list.html", {
        "listings": listings, 
        "q": q, 
        "budget": budget, 
        "fuel": fuel, 
        "brand": brand, 
        "model": model, 
        "year": year,
        "dealer_matches": dealer_matches,
        "all_makes": all_makes,
        "all_models": all_models,
        "all_years": all_years,
    })


def ListingDetailView(request, listing_id):
    listing = CarListing.objects.select_related("car", "seller").prefetch_related("images", "inspections").get(listing_id=listing_id)
    try:
        _apply_ai_estimates_to_listings([listing])
    except Exception:
        pass
        
    try:
        P = float(listing.price or 0.0)
        months = int(request.GET.get("emi_months") or 48)
        rate = float(request.GET.get("emi_rate") or 9.8)  # annual %
        r = (rate / 12.0) / 100.0
        if P > 0 and months > 0 and r > 0:
            emi_val = (P * r * ((1 + r) ** months)) / (((1 + r) ** months) - 1)
        else:
            emi_val = 0.0
        emi = {
            "amount": round(emi_val, 0),
            "months": months,
            "rate": rate,
        }
    except Exception:
        emi = {"amount": 0, "months": 48, "rate": 9.8}
        
    try:
        variants = list(CarListing.objects.select_related("car").filter(
            car__make__iexact=getattr(listing.car, "make", ""),
            car__model__iexact=getattr(listing.car, "model", "")
        ).order_by("price")[:6])
    except Exception:
        variants = []
        
    try:
        cities = ["Bangalore","Mumbai","Pune","Hyderabad","Chennai","Ahmedabad","Lucknow","Jaipur","Patna","Chandigarh"]
        base_total = getattr(listing, "ai_total", None)
        if base_total is None:
            try:
                _apply_ai_estimates_to_listings([listing])
                base_total = getattr(listing, "ai_total", None)
            except Exception:
                base_total = None
        base_total = float(base_total or (listing.price or 0.0))
        CITY_ADJ = {
            "Bangalore": 1.08,
            "Mumbai": 1.05,
            "Pune": 1.03,
            "Hyderabad": 1.02,
            "Chennai": 1.04,
            "Ahmedabad": 1.01,
            "Lucknow": 1.00,
            "Jaipur": 1.01,
            "Patna": 1.00,
            "Chandigarh": 1.02,
        }
        make = (getattr(listing.car, "make", "") or "").strip()
        luxury_bonus = 1.02 if make in {"BMW","Mercedes-Benz","Audi","Volvo","Land Rover","Jaguar","Porsche"} else 1.00
        city_prices = [(c, round(base_total * CITY_ADJ.get(c, 1.00) * luxury_bonus, 0)) for c in cities]
    except Exception:
        city_prices = []
        
    try:
        from .models import ActivityLog
        ActivityLog.objects.create(user=request.user if request.user.is_authenticated else None, action="Viewed listing detail", path=request.path)
    except Exception:
        pass
        
    # Increment view count
    try:
        from django.db import models as dj_models
        CarListing.objects.filter(listing_id=listing.listing_id).update(views_count=dj_models.F("views_count") + 1)
        listing.views_count += 1
    except Exception:
        pass
        
    is_buyer = request.user.is_authenticated and request.user.role == User.Role.BUYER
    try:
        inspection = listing.inspections.order_by("-inspection_date").first()
    except Exception:
        inspection = None
        
    pano_exterior = None
    pano_interior = None
    model_3d_url = None
    sketchfab_uid = None
    imgs = []
    hero_bg_url = None
    
    try:
        imgs = list(listing.images.all())
            
        def pick(keys):
            for im in imgs:
                alt = (getattr(im, "alt", "") or "").lower()
                name = (getattr(im, "image", None).name or "").lower()
                for k in keys:
                    if k in alt or k in name:
                        return im.image.url
            return None
            
        pano_exterior = pick(["360", "exter", "outside", "pano", "equirect"])
        pano_interior = pick(["360", "inter", "inside", "cabin", "dashboard", "pano", "equirect"])
        
        try:
            if not pano_exterior:
                aext = listing.assets.filter(kind=CarListingAsset.Kind.PANORAMA_EXTERIOR).first()
                if aext:
                    pano_exterior = aext.asset.url
            if not pano_interior:
                aint = listing.assets.filter(kind=CarListingAsset.Kind.PANORAMA_INTERIOR).first()
                if aint:
                    pano_interior = aint.asset.url
        except Exception:
            pass
            
        # Fallback: if nothing tagged as panorama, use first/second image so the 360 tab at least shows something
        try:
            if (not pano_exterior) and imgs:
                pano_exterior = imgs[0].image.url
            if (not pano_interior) and len(imgs) > 1:
                pano_interior = imgs[1].image.url
        except Exception:
            pass
            
        def frames(keys):
            urls = []
            for im in imgs:
                alt = (getattr(im, "alt", "") or "").lower()
                name = (getattr(im, "image", None).name or "").lower()
                hit = True
                for k in keys:
                    if not (k in alt or k in name):
                        hit = False
                        break
                if hit:
                    urls.append(im.image.url)
            urls.sort()
            return urls
            
        spin_ext = frames(["spin", "exter"])
        spin_int = frames(["spin", "inter"])
        
        try:
            a = listing.assets.filter(kind=CarListingAsset.Kind.THREE_D).first()
            if a:
                model_3d_url = a.asset.url
        except Exception:
            model_3d_url = None
        try:
            sf = listing.assets.filter(kind=CarListingAsset.Kind.SKETCHFAB).first()
            sketchfab_uid = sf.label if sf else None
        except Exception:
            sketchfab_uid = None
    except Exception:
        pano_exterior = None
        pano_interior = None
        model_3d_url = None
        sketchfab_uid = None
    
    try:
        if imgs:
            # Prefer exterior 16x9 or main
            chosen = None
            for im in imgs:
                alt = (getattr(im, "alt", "") or "").lower()
                name = (getattr(im, "image", None).name or "").lower()
                if ("exter" in alt) and ("16x9" in alt or "main" in alt):
                    chosen = im.image.url
                    break
            if not chosen:
                # any exterior
                for im in imgs:
                    alt = (getattr(im, "alt", "") or "").lower()
                    if "exter" in alt:
                        chosen = im.image.url
                        break
            if not chosen:
                # first non-synthetic
                for im in imgs:
                    name = (getattr(im, "image", None).name or "").lower()
                    if "listing_images/generated/" not in name:
                        chosen = im.image.url
                        break
            hero_bg_url = chosen or imgs[0].image.url
        else:
            mk = (getattr(listing.car, "make", "") or "").strip()
            md = (getattr(listing.car, "model", "") or "").strip()
            if mk or md:
                from urllib.parse import quote
                q = quote(f"{mk} {md} car".strip())
                hero_bg_url = f"https://source.unsplash.com/1920x1080/?{q}"
    except Exception:
        hero_bg_url = None
        
    sess_recs = []
    collab = []
    try:
        candidates = CarListing.objects.select_related("car", "seller").prefetch_related("images").exclude(listing_id=listing.listing_id).order_by("-created_at")[:200]
        similar_cars = recommend_similar_listings(listing, candidates, top_k=6)
        if request.user.is_authenticated:
            try:
                sess_recs = session_aware_recs(request.user, listing, candidates, top_k=6)
            except Exception:
                sess_recs = []
            try:
                collab = collaborative_recs(request.user, candidates, top_k=4)
            except Exception:
                collab = []
            try:
                # Merge and de-duplicate preferring session-aware first
                seen = set()
                merged = []
                for c in sess_recs + collab + similar_cars:
                    if getattr(c, "listing_id", None) not in seen:
                        merged.append(c)
                        seen.add(getattr(c, "listing_id", None))
                similar_cars = merged[:6]
            except Exception:
                pass
    except Exception:
        similar_cars = []
        
    try:
        fairness = price_fairness_info(listing, candidates)
    except Exception:
        fairness = {"label": "Unknown", "median": None, "diff_pct": None}
        
    main_rating_avg = None
    main_rating_cnt = 0
    try:
        from django.db.models import Avg, Count
        from .models import UserReview
        stats = UserReview.objects.filter(car=listing.car).aggregate(avg=Avg("rating"), cnt=Count("id"))
        main_rating_avg = round(float(stats.get("avg") or 0.0), 1) if stats.get("avg") is not None else None
        main_rating_cnt = int(stats.get("cnt") or 0)
    except Exception:
        main_rating_avg = None
        main_rating_cnt = 0

    try:
        city = getattr(getattr(listing, "showroom", None), "city", "") or ""
        showrooms_qs = Showroom.objects.filter(city__iexact=city)
        dealer_matches = dealer_matches_for_buyer(city, candidates, showrooms_qs, top_k=5)
    except Exception:
        dealer_matches = []

    competitors = []
    try:
        low = float(listing.price or 0.0) * 0.9
        high = float(listing.price or 0.0) * 1.1
        comp_qs = CarListing.objects.select_related("car").filter(price__gte=low, price__lte=high).exclude(car__make__iexact=getattr(listing.car, "make", "")).order_by("price")[:2]
        from django.db.models import Avg, Count
        from .models import UserReview
        for c in comp_qs:
            try:
                stats = UserReview.objects.filter(car=c.car).aggregate(avg=Avg("rating"), cnt=Count("id"))
                competitors.append({
                    "make": getattr(c.car, "make", ""),
                    "model": getattr(c.car, "model", ""),
                    "price": c.price,
                    "rating_avg": round(float(stats.get("avg") or 0.0), 1) if stats.get("avg") is not None else None,
                    "rating_cnt": int(stats.get("cnt") or 0),
                    "transmission": getattr(c.car, "transmission", None),
                    "fuel_type": getattr(c.car, "fuel_type", None),
                    "mileage": getattr(c.car, "mileage", None),
                    "gncap": getattr(c.car, "gncap_rating", None),
                })
            except Exception:
                competitors.append({
                    "make": getattr(c.car, "make", ""),
                    "model": getattr(c.car, "model", ""),
                    "price": c.price,
                    "rating_avg": None,
                    "rating_cnt": 0,
                    "transmission": getattr(c.car, "transmission", None),
                    "fuel_type": getattr(c.car, "fuel_type", None),
                    "mileage": getattr(c.car, "mileage", None),
                    "gncap": getattr(c.car, "gncap_rating", None),
                })
    except Exception:
        competitors = []
        
    return render(request, "listings/detail.html", {
        "listing": listing,
        "images": imgs,
        "is_buyer": is_buyer,
        "inspection": inspection,
        "pano_exterior": pano_exterior,
        "pano_interior": pano_interior,
        "model_3d_url": model_3d_url,
        "sketchfab_uid": sketchfab_uid,
        "spin_ext": spin_ext,
        "spin_int": spin_int,
        "similar_cars": similar_cars,
        "dealer_matches": dealer_matches,
        "fairness": fairness,
        "emi": emi,
        "variants": variants,
        "city_prices": city_prices,
        "main_rating_avg": main_rating_avg,
        "main_rating_cnt": main_rating_cnt,
        "competitors": competitors,
        "hero_bg_url": hero_bg_url,
    })

def listing_specs_pdf(request, listing_id):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
    except Exception:
        return HttpResponse("PDF export requires reportlab. Please install it.", status=500)
    listing = get_object_or_404(CarListing.objects.select_related("car"), listing_id=listing_id)
    response = HttpResponse(content_type="application/pdf")
    fname = f"{listing.car.make}_{listing.car.model}_{listing.car.year}_specs.pdf".replace(" ", "_")
    response["Content-Disposition"] = f'attachment; filename="{fname}"'
    doc = SimpleDocTemplate(response, pagesize=A4, leftMargin=24, rightMargin=24, topMargin=24, bottomMargin=24)
    styles = getSampleStyleSheet()
    elems = []
    title = f"{listing.car.make} {listing.car.model} — Specifications"
    elems.append(Paragraph(title, styles["Title"]))
    elems.append(Paragraph(f"Year: {listing.car.year} • Transmission: {listing.car.transmission or '—'} • Fuel: {listing.car.fuel_type or '—'}", styles["Normal"]))
    elems.append(Spacer(1, 12))
    perf = [
        ["Performance"],
        ["Engine Capacity", f"{listing.car.engine_cc or '—'}{' cc' if listing.car.engine_cc else ''}"],
        ["Maximum Power", f"{listing.car.power_bhp or '—'}{' bhp' if listing.car.power_bhp else ''}"],
        ["Peak Torque", f"{listing.car.torque_nm or '—'}{' Nm' if listing.car.torque_nm else ''}"],
    ]
    drive = [
        ["Drivetrain"],
        ["Fuel Delivery", listing.car.fuel_type or "—"],
        ["Transmission", listing.car.transmission or "—"],
    ]
    dims = [
        ["Dimensions"],
        ["Body Configuration", listing.car.body_type or "—"],
        ["Current Odometer", f"{listing.mileage or '—'}{' km' if listing.mileage else ''}"],
    ]
    safe = [
        ["Safety"],
        ["Global NCAP Safety", f"{listing.car.gncap_rating or '—'}"],
    ]
    def make_table(data):
        t = Table(data, hAlign="LEFT", colWidths=[180, 260])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#f1f5f9")),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("TEXTCOLOR", (0,0), (-1,0), colors.HexColor("#0f172a")),
            ("ALIGN", (1,1), (-1,-1), "RIGHT"),
            ("INNERGRID", (0,0), (-1,-1), 0.25, colors.HexColor("#e2e8f0")),
            ("BOX", (0,0), (-1,-1), 0.5, colors.HexColor("#e2e8f0")),
        ]))
        return t
    for block in (perf, drive, dims, safe):
        elems.append(make_table(block))
        elems.append(Spacer(1, 8))
    doc.build(elems)
    return response
def compare_export_pdf(request):
    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
    except Exception:
        return HttpResponse("PDF export requires reportlab. Please install it.", status=500)
    vin1 = (request.GET.get("vin1") or "").strip()
    vin2 = (request.GET.get("vin2") or "").strip()
    car1 = car2 = None
    try:
        if vin1:
            car1 = Car.objects.get(vin=vin1)
    except Car.DoesNotExist:
        car1 = None
    try:
        if vin2:
            car2 = Car.objects.get(vin=vin2)
    except Car.DoesNotExist:
        car2 = None
    styles = getSampleStyleSheet()
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="comparison_matrix.pdf"'
    doc = SimpleDocTemplate(response, pagesize=landscape(A4), leftMargin=24, rightMargin=24, topMargin=24, bottomMargin=24)
    elems = []
    title = "Vehicle Comparison Matrix"
    elems.append(Paragraph(title, styles["Title"]))
    elems.append(Spacer(1, 8))
    def spec(v):
        if not v: return ["—","—","—","—","—","—"]
        return [
            f"{v.make} {v.model}",
            f"{v.year}",
            v.transmission or "—",
            v.fuel_type or "—",
            f"{v.engine_cc or '—'}",
            f"{v.power_bhp or '—'}",
        ]
    header = ["Specification","Car A","Car B"]
    rows = []
    rows.append(["Make & Model", spec(car1)[0], spec(car2)[0]])
    rows.append(["Year", spec(car1)[1], spec(car2)[1]])
    rows.append(["Transmission", spec(car1)[2], spec(car2)[2]])
    rows.append(["Fuel Type", spec(car1)[3], spec(car2)[3]])
    rows.append(["Engine (cc)", spec(car1)[4], spec(car2)[4]])
    rows.append(["Power (bhp)", spec(car1)[5], spec(car2)[5]])
    # Pricing stats
    try:
        from django.db.models import Avg, Count
        def stats(v):
            if not v: return ("—","—","—")
            a = CarListing.objects.filter(car__make__iexact=v.make, car__model__iexact=v.model, car__year=v.year).aggregate(avg=Avg("price"), cnt=Count("listing_id"))
            return (f"{float(a.get('avg') or 0.0):,.0f}", str(a.get("cnt") or 0), "")
        av1, cnt1, _ = stats(car1)
        av2, cnt2, _ = stats(car2)
        rows.append(["Avg Market Price (INR)", av1, av2])
        rows.append(["Sample Size", cnt1, cnt2])
    except Exception:
        pass
    data = [header] + rows
    tbl = Table(data, repeatRows=1, colWidths=[160, 260, 260])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#f1f5f9")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.HexColor("#0f172a")),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("ALIGN", (0,0), (-1,-1), "LEFT"),
        ("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#cbd5e1")),
        ("FONTSIZE", (0,0), (-1,0), 11),
        ("BOTTOMPADDING", (0,0), (-1,0), 8),
    ]))
    elems.append(tbl)
    doc.build(elems)
    return response
@login_required
def PricingAnalyticsView(request):
    from django.db.models import Avg, Count
    brands = list(Car.objects.values_list("make", flat=True).distinct().order_by("make"))
    years = list(Car.objects.values_list("year", flat=True).distinct().order_by("-year"))
    pre_brand = (request.GET.get("brand") or "").strip()
    pre_year = (request.GET.get("year") or "").strip()
    pre_model = (request.GET.get("model") or "").strip()
    models = []
    if pre_brand:
        models = list(Car.objects.filter(make__iexact=pre_brand).values_list("model", flat=True).distinct().order_by("model"))
    return render(request, "analytics/pricing.html", {"brands": brands, "years": years, "models": models, "pre_brand": pre_brand, "pre_year": pre_year, "pre_model": pre_model})

def price_chart_data(request):
    from django.db.models import Avg, Count
    brand = (request.GET.get("brand") or "").strip()
    year = request.GET.get("year")
    model = (request.GET.get("model") or "").strip()
    qs = CarListing.objects.select_related("car")
    if brand:
        qs = qs.filter(car__make__iexact=brand)
    if year:
        try:
            qs = qs.filter(car__year=int(year))
        except Exception:
            pass
    if model:
        qs = qs.filter(car__model__iexact=model)
    # Caching key based on filters
    cache_key = f"price_chart:{brand}:{year}:{model}"
    cached = cache.get(cache_key)
    if cached:
        return JsonResponse(cached)
    agg = (
        qs.values("car__make", "car__model", "car__year")
        .annotate(avg_price=Avg("price"), count=Count("listing_id"))
        .order_by("car__model")
    )
    data = {
        "brand": brand,
        "year": year,
        "points": [
            {"model": a["car__model"], "avg_price": float(a["avg_price"] or 0.0), "count": a["count"]}
            for a in agg
        ],
        "market_avg": float(qs.aggregate(Avg("price")).get("price__avg") or 0.0),
    }
    cache.set(cache_key, data, timeout=300)
    return JsonResponse(data)
@login_required
def ListingImagesDeleteView(request, listing_id):
    if request.method != "POST":
        return redirect("listing_edit", listing_id=listing_id)
    listing = get_object_or_404(CarListing.objects.select_related("seller"), listing_id=listing_id)
    if not (request.user.is_staff or request.user == listing.seller):
        return JsonResponse({"ok": False, "error": "Not allowed"}, status=403)
    ids = request.POST.getlist("image_id")
    try:
        imgs = list(listing.images.filter(pk__in=ids))
        deleted = 0
        for im in imgs:
            try:
                f = getattr(im, "image", None)
                name = getattr(f, "name", None)
                if f and name and f.storage.exists(name):
                    f.storage.delete(name)
            except Exception:
                pass
            try:
                im.delete()
                deleted += 1
            except Exception:
                pass
        xrw = request.headers.get("X-Requested-With", "")
        if xrw and xrw.lower() == "xmlhttprequest":
            return JsonResponse({"ok": True, "deleted": deleted})
        return redirect("listing_edit", listing_id=listing_id)
    except Exception:
        xrw = request.headers.get("X-Requested-With", "")
        if xrw and xrw.lower() == "xmlhttprequest":
            return JsonResponse({"ok": False}, status=500)
        return redirect("listing_edit", listing_id=listing_id)

def price_trend_data(request):
    try:
        from django.db.models import Avg, Count, Max
        from django.db.models.functions import TruncMonth
    except Exception:
        return JsonResponse({"error": "Missing ORM functions"}, status=500)
    brand = (request.GET.get("brand") or "").strip()
    model = (request.GET.get("model") or "").strip()
    year = request.GET.get("year")
    city = (request.GET.get("city") or "").strip()
    qs = CarListing.objects.select_related("car", "showroom")
    if brand:
        qs = qs.filter(car__make__iexact=brand)
    if model:
        qs = qs.filter(car__model__iexact=model)
    if year:
        try:
            qs = qs.filter(car__year=int(year))
        except Exception:
            return JsonResponse({"error": "Invalid year"}, status=400)
    if city:
        qs = qs.filter(showroom__city__iexact=city)
    # Time series trend by month
    series = (
        qs.annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(avg_price=Avg("price"), count=Count("listing_id"))
        .order_by("month")
    )
    # Regional variation
    regions = (
        qs.values("showroom__city")
        .annotate(avg_price=Avg("price"), count=Count("listing_id"))
        .order_by("-count")
    )
    # Freshness
    try:
        freshness = qs.aggregate(Max("updated_at")).get("updated_at__max")
    except Exception:
        freshness = None
    data = {
        "brand": brand, "model": model, "year": year,
        "trend": [
            {"month": (s["month"].strftime("%Y-%m") if s["month"] else None), "avg_price": float(s["avg_price"] or 0.0), "count": s["count"]}
            for s in series
        ],
        "regions": [
            {"city": (r["showroom__city"] or "Online"), "avg_price": float(r["avg_price"] or 0.0), "count": r["count"]}
            for r in regions[:12]
        ],
        "freshness_ts": (freshness.isoformat() if freshness else None),
        "sample_size": qs.count(),
    }
    return JsonResponse(data)

def pricing_aggregate_api(request):
    try:
        from django.db.models import Avg, Count, Min, Max
    except Exception:
        return JsonResponse({"error": "Aggregation not available"}, status=500)
    brand = (request.GET.get("brand") or "").strip()
    model = (request.GET.get("model") or "").strip()
    year_raw = request.GET.get("year")
    city = (request.GET.get("city") or "").strip()
    state = (request.GET.get("state") or "").strip()
    try:
        page = max(1, int(request.GET.get("page") or 1))
    except Exception:
        page = 1
    try:
        page_size = min(100, max(1, int(request.GET.get("page_size") or 25)))
    except Exception:
        page_size = 25
    qs = CarListing.objects.select_related("car", "showroom")
    try:
        mileage_min = request.GET.get("mileage_min")
        mileage_max = request.GET.get("mileage_max")
        if mileage_min:
            qs = qs.filter(mileage__gte=int(mileage_min))
        if mileage_max:
            qs = qs.filter(mileage__lte=int(mileage_max))
    except Exception:
        pass
    if brand:
        qs = qs.filter(car__make__iexact=brand)
    if model:
        qs = qs.filter(car__model__iexact=model)
    if year_raw:
        try:
            year = int(year_raw)
            qs = qs.filter(car__year=year)
        except Exception:
            return JsonResponse({"error": "Invalid year"}, status=400)
    if city:
        qs = qs.filter(showroom__city__iexact=city)
    if state:
        qs = qs.filter(showroom__state__iexact=state)
    # Cache per filter set and page
    cache_key = f"pricing_aggr:{brand}:{model}:{year_raw}:{city}:{state}:{page}:{page_size}"
    cached = cache.get(cache_key)
    if cached:
        return JsonResponse(cached)
    base = (
        qs.values("car__make", "car__model", "car__year")
        .annotate(
            count=Count("listing_id"),
            avg_price=Avg("price"),
            min_price=Min("price"),
            max_price=Max("price"),
        )
        .order_by("car__model")
    )
    # Build item list with optional median and region breakdown
    items = []
    total_items = 0
    sample_size = 0
    for row in base:
        total_items += 1
        sample_size += (row.get("count") or 0)
        mk = row.get("car__make") or ""
        md = row.get("car__model") or ""
        yr = row.get("car__year")
        # median calculation (best-effort)
        try:
            prices_qs = CarListing.objects.filter(
                car__make__iexact=mk, car__model__iexact=md, car__year=yr
            ).values_list("price", flat=True).order_by("price")
            n = prices_qs.count()
            if n:
                if n % 2 == 1:
                    median_price = float(prices_qs[n//2] or 0.0)
                else:
                    a = float(prices_qs[n//2 - 1] or 0.0)
                    b = float(prices_qs[n//2] or 0.0)
                    median_price = (a + b) / 2.0
            else:
                median_price = 0.0
        except Exception:
            median_price = 0.0
        # region counts
        try:
            regions = (
                CarListing.objects.filter(
                    car__make__iexact=mk, car__model__iexact=md, car__year=yr
                ).values("showroom__city")
                 .annotate(cnt=Count("listing_id"))
                 .order_by("-cnt")[:8]
            )
            region_counts = { (r["showroom__city"] or "Online"): r["cnt"] for r in regions }
        except Exception:
            region_counts = {}
        items.append({
            "brand": mk,
            "model": md,
            "year": yr,
            "count": row.get("count") or 0,
            "avg_price": float(row.get("avg_price") or 0.0),
            "median_price": float(median_price or 0.0),
            "min_price": float(row.get("min_price") or 0.0),
            "max_price": float(row.get("max_price") or 0.0),
            "regions": region_counts,
        })
    # Pagination
    start = (page - 1) * page_size
    end = start + page_size
    page_items = items[start:end]
    # Freshness
    try:
        from django.db.models import Max as _Max
        freshness = qs.aggregate(_Max("updated_at")).get("updated_at__max")
    except Exception:
        freshness = None
    out = {
        "ok": True,
        "meta": {
            "brand": brand, "model": model, "year": year_raw,
            "page": page, "page_size": page_size,
            "total_items": total_items, "sample_size": sample_size,
            "freshness_ts": (freshness.isoformat() if freshness else None),
        },
        "items": page_items,
    }
    cache.set(cache_key, out, timeout=300)
    return JsonResponse(out)

def pricing_export_csv(request):
    from django.db.models import Avg, Count
    brand = (request.GET.get("brand") or "").strip()
    model = (request.GET.get("model") or "").strip()
    year = request.GET.get("year")
    qs = CarListing.objects.select_related("car")
    if brand:
        qs = qs.filter(car__make__iexact=brand)
    if model:
        qs = qs.filter(car__model__iexact=model)
    if year:
        try:
            qs = qs.filter(car__year=int(year))
        except Exception:
            return HttpResponse("Invalid year", status=400)
    agg = (
        qs.values("car__make", "car__model", "car__year")
        .annotate(avg_price=Avg("price"), count=Count("listing_id"))
        .order_by("car__model")
    )
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="pricing_analytics.csv"'
    writer = csv.writer(response)
    writer.writerow(["Brand", "Model", "Year", "Average Price", "Sample Size"])
    for a in agg:
        writer.writerow([
            a.get("car__make") or "",
            a.get("car__model") or "",
            a.get("car__year") or "",
            str(float(a.get("avg_price") or 0.0)),
            a.get("count") or 0
        ])
    return response

@login_required
def toggle_favorite(request):
    if request.method != "POST" or request.user.role != User.Role.BUYER:
        return JsonResponse({"ok": False, "error": "Not allowed"}, status=403)
    from .models import Favorite
    listing_id = request.POST.get("listing_id")
    try:
        lst = CarListing.objects.get(listing_id=listing_id)
    except CarListing.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Listing not found"}, status=404)
    fav, created = Favorite.objects.get_or_create(user=request.user, listing=lst)
    if not created:
        fav.delete()
        delta = -1
        liked = False
    else:
        delta = 1
        liked = True
    # update buyer.favorite_count
    try:
        b, _ = Buyer.objects.get_or_create(user=request.user)
        b.favorite_count = max(0, int(getattr(b, "favorite_count", 0) or 0) + delta)
        b.save(update_fields=["favorite_count"])
    except Exception:
        pass
    return JsonResponse({"ok": True, "liked": liked})

@login_required
def save_search(request):
    if request.method != "POST" or request.user.role != User.Role.BUYER:
        return JsonResponse({"ok": False, "error": "Not allowed"}, status=403)
    from .models import SavedSearch
    name = (request.POST.get("name") or "").strip()
    params_json = request.POST.get("params") or "{}"
    try:
        import json
        params = json.loads(params_json)
    except Exception:
        params = {}
    ss = SavedSearch.objects.create(user=request.user, name=name or "", params=params)
    return JsonResponse({"ok": True, "id": str(ss.saved_search_id)})


@login_required
def saved_items(request):
    from .models import Favorite, SavedSearch
    if request.user.role != User.Role.BUYER:
        # sellers can still see saved for future parity; show empty lists
        favorites = Favorite.objects.filter(user=request.user).select_related("listing__car").order_by("-created_at")
        searches = SavedSearch.objects.filter(user=request.user).order_by("-created_at")
    else:
        favorites = Favorite.objects.filter(user=request.user).select_related("listing__car").order_by("-created_at")
        searches = SavedSearch.objects.filter(user=request.user).order_by("-created_at")
    return render(request, "account/saved.html", {"favorites": favorites, "saved_searches": searches})


@login_required
def favorite_delete(request, favorite_id):
    if request.method != "POST":
        return redirect("saved_items")
    from .models import Favorite
    try:
        fav = Favorite.objects.get(favorite_id=favorite_id, user=request.user)
        fav.delete()
    except Favorite.DoesNotExist:
        pass
    return redirect("saved_items")


@login_required
def saved_search_delete(request, saved_search_id):
    if request.method != "POST":
        return redirect("saved_items")
    from .models import SavedSearch
    try:
        ss = SavedSearch.objects.get(saved_search_id=saved_search_id, user=request.user)
        ss.delete()
    except SavedSearch.DoesNotExist:
        pass
    return redirect("saved_items")


@login_required
def account_exports(request):
    role = getattr(request.user, "role", None)
    return render(request, "account/exports.html", {"role": role})

@login_required
def ListingMessageView(request, listing_id):
    listing = CarListing.objects.select_related("car", "seller").get(listing_id=listing_id)
    content = strip_tags(request.POST.get("content") or "").strip()
    if content:
        m = Message.objects.create(sender=request.user, receiver=listing.seller, listing=listing, content=content)
        try:
            ctx = {
                "sender": request.user,
                "receiver": listing.seller,
                "listing": listing,
                "content": content,
                "sent_at": timezone.now(),
                "thread_url": request.build_absolute_uri(reverse("messages")),
            }
            send_email_html_async(
                subject="New Inquiry on Your Listing – Vehicle Vault",
                template_name="emails/message_notification.html",
                context=ctx,
                recipients=[listing.seller.email],
                attachments=_marketing_brochure_attachments(listing.seller),
            )
        except Exception:
            pass
        return redirect("listing_detail", listing_id=listing.listing_id)
    return redirect("listing_detail", listing_id=listing.listing_id)


@login_required
def PurchaseListingView(request, listing_id):
    listing = get_object_or_404(CarListing, listing_id=listing_id)
    if not (request.user.role == User.Role.BUYER):
        return redirect("listing_detail", listing_id=listing.listing_id)
    
    return redirect(f"/booking/?listing_id={listing.listing_id}")


def MessagesInboxView(request):
    inbox = Message.objects.filter(receiver=request.user).select_related("sender").order_by("-sent_at") if request.user.is_authenticated else []
    return render(request, "messages/inbox.html", {"messages": inbox})


@login_required
def ReplyToMessageView(request, message_id):
    if request.method != "POST":
        return redirect("messages")
    message = get_object_or_404(Message.objects.select_related("sender", "listing"), message_id=message_id, receiver=request.user)
    content = strip_tags(request.POST.get("content") or "").strip()
    if content:
        reply = Message.objects.create(
            sender=request.user,
            receiver=message.sender,
            listing=message.listing,
            content=content,
        )
        try:
            ctx = {
                "sender": request.user,
                "receiver": message.sender,
                "listing": message.listing,
                "content": content,
                "sent_at": timezone.now(),
                "thread_url": request.build_absolute_uri(reverse("messages")),
            }
            send_email_html_async(
                subject="You Have a New Reply – Vehicle Vault",
                template_name="emails/message_notification.html",
                context=ctx,
                recipients=[message.sender.email],
                attachments=_marketing_brochure_attachments(message.sender),
            )
        except Exception:
            pass
    return redirect(request.POST.get("next") or "messages")


@login_required
def AcceptDealView(request, message_id):
    if request.method != "POST":
        return redirect("messages")
    message = get_object_or_404(Message.objects.select_related("sender", "listing__seller", "listing__car"), message_id=message_id, receiver=request.user)
    listing = message.listing
    if not listing:
        return redirect(request.POST.get("next") or "messages")

    if request.user == listing.seller:
        buyer = message.sender
        seller = request.user
    else:
        buyer = request.user
        seller = listing.seller

    if buyer == seller:
        return redirect(request.POST.get("next") or "messages")

    from .models import Transaction

    transaction_obj, created = Transaction.objects.get_or_create(
        listing=listing,
        buyer=buyer,
        seller=seller,
        defaults={
            "final_price": listing.price,
            "status": Transaction.Status.PENDING,
        },
    )
    try:
        ctx = {
            "listing": listing,
            "buyer": buyer,
            "seller": seller,
            "sent_at": timezone.now(),
            "booking_url": request.build_absolute_uri(f"/booking/?listing_id={listing.listing_id}"),
        }
        send_email_html_async(
            subject="Deal Accepted – Proceed to Booking",
            template_name="emails/message_notification.html",
            context=ctx,
            recipients=[buyer.email, seller.email],
            attachments=_marketing_brochure_attachments(buyer),
        )
    except Exception:
        pass
    
    return redirect(f"/booking/?listing_id={listing.listing_id}")


@login_required
def RateUserView(request, user_id):
    if request.method != "POST":
        return redirect("messages")
    rated_user = get_object_or_404(User, user_id=user_id)
    if rated_user == request.user:
        return redirect(request.POST.get("next") or "messages")

    try:
        score = int(request.POST.get("score") or 5)
    except (TypeError, ValueError):
        score = 5
    score = max(1, min(5, score))
    review = strip_tags(request.POST.get("review") or "").strip()

    DealRating.objects.update_or_create(
        rater=request.user,
        rated_user=rated_user,
        defaults={"score": score, "review": review},
    )
    _sync_seller_rating(rated_user)
    return redirect(request.POST.get("next") or "messages")


def TestDrivesView(request):
    drives = []
    if request.user.is_authenticated:
        if request.user.is_staff:
            drives = TestDrive.objects.select_related("listing__car", "buyer").order_by("-proposed_date")
        else:
            drives = TestDrive.objects.filter(buyer=request.user).select_related("listing__car", "buyer").order_by("-proposed_date")
    return render(request, "testdrives/list.html", {"drives": drives})


def SellStartView(request):
    return render(request, "sell/start.html")


def ChatbotView(request):
    q = strip_tags(request.POST.get("q") or request.GET.get("q") or "")
    listings = CarListing.objects.select_related("car").order_by("-created_at")[:300]
    ans = chatbot_query(q, listings)
    return JsonResponse({"answer": ans})

def BrochureView(request):
    return render(request, "marketing/brochure.html")

def CitiesIndexView(request):
    cities = [
        {"name": "Ahmedabad", "state": "Gujarat"},
        {"name": "Vadodara", "state": "Gujarat"},
        {"name": "Surat", "state": "Gujarat"},
        {"name": "Rajkot", "state": "Gujarat"},
        {"name": "Mumbai", "state": "Maharashtra"},
        {"name": "Pune", "state": "Maharashtra"},
        {"name": "Nagpur", "state": "Maharashtra"},
        {"name": "Nashik", "state": "Maharashtra"},
        {"name": "Bengaluru", "state": "Karnataka"},
        {"name": "Mysuru", "state": "Karnataka"},
        {"name": "Chennai", "state": "Tamil Nadu"},
        {"name": "Coimbatore", "state": "Tamil Nadu"},
        {"name": "Hyderabad", "state": "Telangana"},
        {"name": "Warangal", "state": "Telangana"},
        {"name": "Delhi", "state": "Delhi"},
        {"name": "Noida", "state": "Uttar Pradesh"},
        {"name": "Gurugram", "state": "Haryana"},
        {"name": "Kolkata", "state": "West Bengal"},
        {"name": "Howrah", "state": "West Bengal"},
        {"name": "Jaipur", "state": "Rajasthan"},
        {"name": "Udaipur", "state": "Rajasthan"},
        {"name": "Lucknow", "state": "Uttar Pradesh"},
        {"name": "Kanpur", "state": "Uttar Pradesh"},
        {"name": "Agra", "state": "Uttar Pradesh"},
        {"name": "Bhopal", "state": "Madhya Pradesh"},
        {"name": "Indore", "state": "Madhya Pradesh"},
        {"name": "Patna", "state": "Bihar"},
        {"name": "Ranchi", "state": "Jharkhand"},
        {"name": "Bhubaneswar", "state": "Odisha"},
        {"name": "Chandigarh", "state": "Chandigarh"},
        {"name": "Dehradun", "state": "Uttarakhand"},
        {"name": "Raipur", "state": "Chhattisgarh"},
        {"name": "Guwahati", "state": "Assam"},
        {"name": "Imphal", "state": "Manipur"},
        {"name": "Shillong", "state": "Meghalaya"},
        {"name": "Aizawl", "state": "Mizoram"},
        {"name": "Itanagar", "state": "Arunachal Pradesh"},
        {"name": "Kohima", "state": "Nagaland"},
        {"name": "Srinagar", "state": "Jammu & Kashmir"},
        {"name": "Jammu", "state": "Jammu & Kashmir"},
        {"name": "Panaji", "state": "Goa"},
        {"name": "Thiruvananthapuram", "state": "Kerala"},
        {"name": "Kochi", "state": "Kerala"},
        {"name": "Madurai", "state": "Tamil Nadu"},
    ]
    for c in cities:
        c["slug"] = c["name"].lower().replace(" ", "-")
    return render(request, "cities/index.html", {"cities": cities})


def CityShowroomsView(request, city_slug):
    city = city_slug.replace("-", " ")
    brand = request.GET.get("brand") or ""
    fuel = request.GET.get("fuel") or ""
    budget = request.GET.get("budget") or ""
    body = request.GET.get("body") or ""
    trans = request.GET.get("trans") or ""
    sort = request.GET.get("sort") or ""

    sellers = Seller.objects.select_related("user").filter(Q(location__icontains=city) | Q(user__name__icontains=city))
    try:
        showrooms = list(Showroom.objects.filter(city__iexact=city).order_by("name"))
    except Exception:
        showrooms = []

    # Fallback curated showrooms if DB has none
    if not showrooms:
        city_key = city.lower()
        curated_map = {
            "vadodara": [
                {"name": "Maruti Suzuki Arena", "city": "Vadodara", "state": "Gujarat", "address": "Akota", "map_query": "Maruti Suzuki Arena Akota Vadodara"},
                {"name": "Nexa Showroom", "city": "Vadodara", "state": "Gujarat", "address": "Alkapuri", "map_query": "Nexa Alkapuri Vadodara"},
                {"name": "Hyundai Showroom", "city": "Vadodara", "state": "Gujarat", "address": "Old Padra Road", "map_query": "Hyundai Showroom Old Padra Road Vadodara"},
            ],
            "ahmedabad": [
                {"name": "Audi Ahmedabad", "city": "Ahmedabad", "state": "Gujarat", "address": "SG Highway", "map_query": "Audi showroom SG Highway Ahmedabad"},
                {"name": "Nexa Ahmedabad", "city": "Ahmedabad", "state": "Gujarat", "address": "CG Road", "map_query": "Nexa CG Road Ahmedabad"},
                {"name": "Hyundai Ahmedabad", "city": "Ahmedabad", "state": "Gujarat", "address": "Satellite", "map_query": "Hyundai Showroom Satellite Ahmedabad"},
            ],
            "mumbai": [
                {"name": "BMW Deutsche Motoren", "city": "Mumbai", "state": "Maharashtra", "address": "Worli", "map_query": "BMW showroom Worli Mumbai"},
                {"name": "Toyota Lakozy", "city": "Mumbai", "state": "Maharashtra", "address": "Andheri", "map_query": "Toyota showroom Andheri Mumbai"},
                {"name": "Audi Mumbai West", "city": "Mumbai", "state": "Maharashtra", "address": "Andheri West", "map_query": "Audi Mumbai West Andheri"},
            ],
            "delhi": [
                {"name": "NEXA Connaught Place", "city": "Delhi", "state": "Delhi", "address": "Connaught Place", "map_query": "NEXA Connaught Place Delhi"},
                {"name": "Hyundai Dwarka", "city": "Delhi", "state": "Delhi", "address": "Dwarka", "map_query": "Hyundai showroom Dwarka Delhi"},
                {"name": "Mercedes-Benz T&T Motors", "city": "Delhi", "state": "Delhi", "address": "Mathura Road", "map_query": "Mercedes Benz T&T Motors Mathura Road Delhi"},
            ],
            "pune": [
                {"name": "Toyota Pune", "city": "Pune", "state": "Maharashtra", "address": "Wakad", "map_query": "Toyota showroom Wakad Pune"},
                {"name": "Nexa Pune", "city": "Pune", "state": "Maharashtra", "address": "Baner", "map_query": "Nexa showroom Baner Pune"},
                {"name": "Hyundai Pune", "city": "Pune", "state": "Maharashtra", "address": "Kharadi", "map_query": "Hyundai showroom Kharadi Pune"},
            ],
            "bengaluru": [
                {"name": "Nexa Bengaluru", "city": "Bengaluru", "state": "Karnataka", "address": "Indiranagar", "map_query": "Nexa showroom Indiranagar Bengaluru"},
                {"name": "Hyundai Bengaluru", "city": "Bengaluru", "state": "Karnataka", "address": "Koramangala", "map_query": "Hyundai showroom Koramangala Bengaluru"},
                {"name": "Audi Bengaluru", "city": "Bengaluru", "state": "Karnataka", "address": "Richmond Road", "map_query": "Audi showroom Richmond Road Bengaluru"},
            ],
            "chennai": [
                {"name": "Hyundai Chennai", "city": "Chennai", "state": "Tamil Nadu", "address": "OMR", "map_query": "Hyundai showroom OMR Chennai"},
                {"name": "Nexa Chennai", "city": "Chennai", "state": "Tamil Nadu", "address": "T Nagar", "map_query": "Nexa showroom T Nagar Chennai"},
                {"name": "BMW Chennai", "city": "Chennai", "state": "Tamil Nadu", "address": "Mount Road", "map_query": "BMW showroom Mount Road Chennai"},
            ],
            "hyderabad": [
                {"name": "Nexa Hyderabad", "city": "Hyderabad", "state": "Telangana", "address": "Banjara Hills", "map_query": "Nexa showroom Banjara Hills Hyderabad"},
                {"name": "Hyundai Hyderabad", "city": "Hyderabad", "state": "Telangana", "address": "Kukatpally", "map_query": "Hyundai showroom Kukatpally Hyderabad"},
                {"name": "Audi Hyderabad", "city": "Hyderabad", "state": "Telangana", "address": "Madhapur", "map_query": "Audi showroom Madhapur Hyderabad"},
            ],
            "kolkata": [
                {"name": "NEXA Kolkata", "city": "Kolkata", "state": "West Bengal", "address": "Park Street", "map_query": "NEXA showroom Park Street Kolkata"},
                {"name": "Hyundai Kolkata", "city": "Kolkata", "state": "West Bengal", "address": "Salt Lake", "map_query": "Hyundai showroom Salt Lake Kolkata"},
                {"name": "BMW Kolkata", "city": "Kolkata", "state": "West Bengal", "address": "EM Bypass", "map_query": "BMW showroom EM Bypass Kolkata"},
            ],
            "jaipur": [
                {"name": "NEXA Jaipur", "city": "Jaipur", "state": "Rajasthan", "address": "Tonk Road", "map_query": "NEXA showroom Tonk Road Jaipur"},
                {"name": "Hyundai Jaipur", "city": "Jaipur", "state": "Rajasthan", "address": "Vaishali Nagar", "map_query": "Hyundai showroom Vaishali Nagar Jaipur"},
                {"name": "Audi Jaipur", "city": "Jaipur", "state": "Rajasthan", "address": "Ajmer Road", "map_query": "Audi showroom Ajmer Road Jaipur"},
            ],
        }
        curated = curated_map.get(city_key, [
            {"name": "Maruti Suzuki Arena", "city": city.title(), "state": "", "address": "", "map_query": f"Maruti Suzuki Arena {city.title()}"},
            {"name": "Nexa Showroom", "city": city.title(), "state": "", "address": "", "map_query": f"Nexa Showroom {city.title()}"},
            {"name": "Hyundai Showroom", "city": city.title(), "state": "", "address": "", "map_query": f"Hyundai Showroom {city.title()}"},
        ])
        
        # Convert curated dicts to lightweight objects for template iteration
        class Cur:
            def __init__(self, d): self.__dict__.update(d)
        showrooms = [Cur(d) for d in curated]

    # Map sellers to showrooms by rough location/name match
    seller_users = [s.user for s in sellers]
    qs = CarListing.objects.select_related("car", "seller", "showroom").prefetch_related("images").filter(Q(showroom__city__iexact=city) | Q(seller__in=seller_users)).order_by("-created_at")
    
    if brand:
        qs = qs.filter(Q(car__make__icontains=brand) | Q(car__model__icontains=brand))
    if fuel:
        qs = qs.filter(car__fuel_type__iexact=fuel)
    if body:
        qs = qs.filter(car__body_type__icontains=body)
    if trans:
        qs = qs.filter(car__transmission__icontains=trans)
    if budget and "-" in budget:
        try:
            low, high = [float(x) for x in budget.split("-")]
            qs = qs.filter(price__gte=low, price__lte=high)
        except Exception:
            pass

    if sort == "price_asc":
        qs = qs.order_by("price")
    elif sort == "price_desc":
        qs = qs.order_by("-price")
    else:
        qs = qs.order_by("-created_at")

    arrivals = UpcomingArrival.objects.filter(showroom__city__iexact=city).order_by("expected_date")
    gmaps_key = os.environ.get("GOOGLE_MAPS_API_KEY") or ""
    try:
        _apply_ai_estimates_to_listings(qs)
    except Exception:
        pass
        
    return render(request, "cities/city.html", {"city": city.title(), "sellers": sellers, "showrooms": showrooms, "listings": qs, "arrivals": arrivals, "brand": brand, "fuel": fuel, "budget": budget, "body": body, "trans": trans, "sort": sort, "gmaps_key": gmaps_key})


@login_required
def UpcomingArrivalCreateView(request):
    if request.user.role != User.Role.SELLER and not request.user.is_staff:
        return redirect("cities")
    form = UpcomingArrivalForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            form.save()
            showroom = form.cleaned_data.get("showroom")
            return redirect("city_showrooms", city_slug=(showroom.city.lower().replace(" ", "-") if showroom else "cities"))
    return render(request, "cities/arrival_new.html", {"form": form})


def BuyersListView(request):
    buyers = Buyer.objects.select_related("user").order_by("user__name", "user__email")
    return render(request, "profiles/buyers.html", {"buyers": buyers})


def SellersListView(request):
    sellers = Seller.objects.select_related("user").order_by("user__name", "user__email")
    return render(request, "profiles/sellers.html", {"sellers": sellers})


def BuyerDetailView(request, user_id):
    buyer = Buyer.objects.select_related("user").get(user__user_id=user_id)
    listings = []
    if request.user.is_authenticated and request.user.role == User.Role.SELLER:
        listings = CarListing.objects.select_related("car").filter(seller=request.user, status=CarListing.Status.ACTIVE)
    rating_stats = _rating_stats_for_user(buyer.user)
    current_user_rating = None
    if request.user.is_authenticated and request.user != buyer.user:
        current_user_rating = DealRating.objects.filter(rater=request.user, rated_user=buyer.user).first()
    return render(request, "profiles/buyer_detail.html", {"buyer": buyer, "listings": listings, "rating_stats": rating_stats, "current_user_rating": current_user_rating})


def SellerDetailView(request, user_id):
    seller = Seller.objects.select_related("user").get(user__user_id=user_id)
    listings = CarListing.objects.select_related("car").filter(seller=seller.user, status=CarListing.Status.ACTIVE)
    rating_stats = _rating_stats_for_user(seller.user)
    current_user_rating = None
    if request.user.is_authenticated and request.user != seller.user:
        current_user_rating = DealRating.objects.filter(rater=request.user, rated_user=seller.user).first()
    return render(request, "profiles/seller_detail.html", {"seller": seller, "listings": listings, "rating_stats": rating_stats, "current_user_rating": current_user_rating})


@login_required
def RequestSellToSellerView(request, user_id):
    seller = Seller.objects.select_related("user").get(user__user_id=user_id)
    listings = CarListing.objects.select_related("car").filter(seller=seller.user, status=CarListing.Status.ACTIVE)
    if request.method == "POST":
        content = strip_tags(request.POST.get("content") or "").strip()
        listing = None
        listing_id = request.POST.get("listing_id") or ""
        if listing_id:
            try:
                listing = CarListing.objects.get(listing_id=listing_id, seller=seller.user)
            except CarListing.DoesNotExist:
                listing = None
        if content:
            m = Message.objects.create(sender=request.user, receiver=seller.user, listing=listing, content=content)
            try:
                ctx = {
                    "sender": request.user,
                    "receiver": seller.user,
                    "listing": listing,
                    "content": content,
                    "sent_at": timezone.now(),
                    "thread_url": request.build_absolute_uri(reverse("messages")),
                }
                send_email_html_async(
                    subject="New Seller Approach – Vehicle Vault",
                    template_name="emails/message_notification.html",
                    context=ctx,
                    recipients=[seller.user.email],
                    attachments=_marketing_brochure_attachments(seller.user),
                )
            except Exception:
                pass
            return redirect("sellers_detail", user_id=seller.user.user_id)
    return render(request, "profiles/seller_detail.html", {"seller": seller, "listings": listings, "error": "Please add a message"})


@login_required
def RequestBuyToBuyerView(request, user_id):
    buyer = Buyer.objects.select_related("user").get(user__user_id=user_id)
    listings = []
    if request.user.is_authenticated and request.user.role == User.Role.SELLER:
        listings = CarListing.objects.select_related("car").filter(seller=request.user, status=CarListing.Status.ACTIVE)
    if request.method == "POST":
        content = strip_tags(request.POST.get("content") or "").strip()
        listing = None
        listing_id = request.POST.get("listing_id") or ""
        if listing_id and listings:
            try:
                listing = CarListing.objects.get(listing_id=listing_id, seller=request.user)
            except CarListing.DoesNotExist:
                listing = None
        if content:
            m = Message.objects.create(sender=request.user, receiver=buyer.user, listing=listing, content=content)
            try:
                ctx = {
                    "sender": request.user,
                    "receiver": buyer.user,
                    "listing": listing,
                    "content": content,
                    "sent_at": timezone.now(),
                    "thread_url": request.build_absolute_uri(reverse("messages")),
                }
                send_email_html_async(
                    subject="New Offer from Seller – Vehicle Vault",
                    template_name="emails/message_notification.html",
                    context=ctx,
                    recipients=[buyer.user.email],
                    attachments=_marketing_brochure_attachments(buyer.user),
                )
            except Exception:
                pass
            return redirect("buyers_detail", user_id=buyer.user.user_id)
    return render(request, "profiles/buyer_detail.html", {"buyer": buyer, "listings": listings, "error": "Please add a message"})


@login_required
def ListingCreateView(request):
    if not request.user.is_authenticated:
        return redirect("login")
    pre_showroom_id = request.GET.get("showroom_id") or ""
    car_form = CarForm(request.POST or None)
    listing_initial = {}
    if pre_showroom_id:
        try:
            from .models import Showroom
            pre_showroom = Showroom.objects.get(showroom_id=pre_showroom_id)
            listing_initial["showroom"] = pre_showroom
        except Exception:
            pass
    listing_form = CarListingForm(request.POST or None, initial=listing_initial)
    if request.method == "POST":
        if car_form.is_valid() and listing_form.is_valid():
            car = car_form.save(commit=False)
            vin = (getattr(car, "vin", "") or "").strip()
            if not vin or len(vin) < 10:
                import random
                allowed = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"
                gen = "".join(random.choice(allowed) for _ in range(17))
                from .models import Car
                while Car.objects.filter(vin=gen).exists():
                    gen = "".join(random.choice(allowed) for _ in range(17))
                car.vin = gen
            car.save()
            listing = listing_form.save(commit=False)
            listing.car = car
            listing.seller = request.user
            listing.save()
            for f in request.FILES.getlist("images"):
                try:
                    CarListingImage.objects.create(listing=listing, image=f, alt=f.name)
                except Exception:
                    pass
            try:
                frames_ext = request.FILES.getlist("spin_exterior")
                for idx, f in enumerate(frames_ext):
                    CarListingImage.objects.create(listing=listing, image=f, alt=f"Spin Exterior {idx+1:02d}")
                frames_int = request.FILES.getlist("spin_interior")
                for idx, f in enumerate(frames_int):
                    CarListingImage.objects.create(listing=listing, image=f, alt=f"Spin Interior {idx+1:02d}")
            except Exception:
                pass
            try:
                model3d = request.FILES.get("asset_3d")
                if model3d:
                    CarListingAsset.objects.create(listing=listing, asset=model3d, kind=CarListingAsset.Kind.THREE_D, label=model3d.name)
                sketchfab_url = request.POST.get("sketchfab_url", "").strip()
                if sketchfab_url:
                    import re as _re
                    uid_match = _re.search(r'([a-f0-9]{32})(?:[^a-f0-9]|$)', sketchfab_url)
                    sketchfab_uid = uid_match.group(1) if uid_match else sketchfab_url
                    listing.assets.filter(kind=CarListingAsset.Kind.SKETCHFAB).delete()
                    CarListingAsset.objects.create(listing=listing, kind=CarListingAsset.Kind.SKETCHFAB, label=sketchfab_uid)
                pano_ext = request.FILES.get("pano_exterior")
                if pano_ext:
                    CarListingImage.objects.create(listing=listing, image=pano_ext, alt="Exterior 360")
                    try:
                        CarListingAsset.objects.create(listing=listing, asset=pano_ext, kind=CarListingAsset.Kind.PANORAMA_EXTERIOR, label=getattr(pano_ext, "name", "Exterior 360"))
                    except Exception:
                        pass
                pano_int = request.FILES.get("pano_interior")
                if pano_int:
                    CarListingImage.objects.create(listing=listing, image=pano_int, alt="Interior 360")
                    try:
                        CarListingAsset.objects.create(listing=listing, asset=pano_int, kind=CarListingAsset.Kind.PANORAMA_INTERIOR, label=getattr(pano_int, "name", "Interior 360"))
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                return redirect(f"/cars/?brand={car.make}")
            except Exception:
                return redirect("cars")
    return render(request, "listings/new.html", {"car_form": car_form, "listing_form": listing_form})


@login_required
def TestDriveCreateView(request):
    if not request.user.is_staff:
        return redirect("testdrives")
    listings = CarListing.objects.select_related("car").order_by("-created_at")[:100]
    buyers = User.objects.filter(role='Buyer').order_by('name')
    preselected_listing_id = request.GET.get("listing_id") or ""
    if request.method == "POST":
        listing_id = request.POST.get("listing_id")
        buyer_id = request.POST.get("buyer_id")
        date = request.POST.get("proposed_date")
        notes = request.POST.get("notes") or ""
        try:
            listing = CarListing.objects.get(listing_id=listing_id)
            buyer = User.objects.get(user_id=buyer_id)
            TestDrive.objects.create(listing=listing, buyer=buyer, proposed_date=date, notes=notes)
            return redirect("testdrives")
        except Exception:
            pass
    return render(request, "testdrives/new.html", {"listings": listings, "buyers": buyers, "preselected_listing_id": preselected_listing_id})


@login_required
def InspectionCreateView(request):
    if not (request.user.is_staff or request.user.role == User.Role.SELLER):
        return redirect("listings")
    preselected_listing_id = request.GET.get("listing_id") or ""
    initial = {}
    if preselected_listing_id:
        try:
            pre_listing = CarListing.objects.get(listing_id=preselected_listing_id)
            initial["listing"] = pre_listing
        except CarListing.DoesNotExist:
            pass
    form = InspectionForm(request.POST or None, user=request.user, initial=initial)
    if request.method == "POST":
        if form.is_valid():
            insp = form.save(commit=False)
            if request.user.role == User.Role.SELLER and insp.listing.seller != request.user:
                return redirect("listings")
            insp.save()
            return redirect("listing_detail", listing_id=insp.listing.listing_id)
    return render(request, "inspections/new.html", {"form": form})


@login_required
def TestDriveUpdateView(request, test_drive_id):
    if not request.user.is_staff:
        return redirect("testdrives")
    drive = TestDrive.objects.select_related("listing__car", "buyer").get(test_drive_id=test_drive_id)
    if request.method == "POST":
        status = request.POST.get("status") or drive.status
        proposed_date = request.POST.get("proposed_date") or drive.proposed_date
        actual_date = request.POST.get("actual_date") or None
        notes = request.POST.get("notes") or ""
        drive.status = status
        drive.proposed_date = proposed_date
        drive.actual_date = actual_date
        drive.notes = notes
        drive.save()
        return redirect("testdrives")
    return render(request, "testdrives/edit.html", {"drive": drive})


@login_required
def ListingUpdateView(request, listing_id):
    listing = CarListing.objects.select_related("car", "seller").get(listing_id=listing_id)
    if not (request.user.is_staff or request.user == listing.seller):
        return redirect("listings")
    if request.method == "POST":
        form = CarListingForm(request.POST, instance=listing)
        if form.is_valid():
            form.save()
            for f in request.FILES.getlist("images"):
                try:
                    CarListingImage.objects.create(listing=listing, image=f, alt=f.name)
                except Exception:
                    pass
            try:
                frames_ext = request.FILES.getlist("spin_exterior")
                for idx, f in enumerate(frames_ext):
                    CarListingImage.objects.create(listing=listing, image=f, alt=f"Spin Exterior {idx+1:02d}")
                frames_int = request.FILES.getlist("spin_interior")
                for idx, f in enumerate(frames_int):
                    CarListingImage.objects.create(listing=listing, image=f, alt=f"Spin Interior {idx+1:02d}")
            except Exception:
                pass
            try:
                model3d = request.FILES.get("asset_3d")
                if model3d:
                    CarListingAsset.objects.create(listing=listing, asset=model3d, kind=CarListingAsset.Kind.THREE_D, label=model3d.name)
                sketchfab_url = request.POST.get("sketchfab_url", "").strip()
                if sketchfab_url:
                    import re as _re
                    uid_match = _re.search(r'([a-f0-9]{32})(?:[^a-f0-9]|$)', sketchfab_url)
                    sketchfab_uid = uid_match.group(1) if uid_match else sketchfab_url
                    listing.assets.filter(kind=CarListingAsset.Kind.SKETCHFAB).delete()
                    CarListingAsset.objects.create(listing=listing, kind=CarListingAsset.Kind.SKETCHFAB, label=sketchfab_uid)
                pano_ext = request.FILES.get("pano_exterior")
                if pano_ext:
                    CarListingImage.objects.create(listing=listing, image=pano_ext, alt="Exterior 360")
                pano_int = request.FILES.get("pano_interior")
                if pano_int:
                    CarListingImage.objects.create(listing=listing, image=pano_int, alt="Interior 360")
            except Exception:
                pass
            try:
                media_root = getattr(settings, "MEDIA_ROOT", "")
                paths = []
                for im in listing.images.all()[:12]:
                    try:
                        p = os.path.join(media_root, getattr(im.image, "name", ""))
                        if os.path.exists(p):
                            paths.append(p)
                    except Exception:
                        continue
                score = image_condition_score(paths) if paths else None
                if score is not None:
                    from .models import Inspection
                    insp = listing.inspections.filter(source=Inspection.Source.AI).order_by("-inspection_date").first()
                    from django.utils.timezone import now
                    if not insp:
                        insp = Inspection.objects.create(listing=listing, inspection_date=now(), source=Inspection.Source.AI, ai_condition_score=score)
                    else:
                        insp.ai_condition_score = score
                        insp.save(update_fields=["ai_condition_score"])
            except Exception:
                pass
            return redirect("listings")
    else:
        form = CarListingForm(instance=listing)
    return render(request, "listings/edit.html", {"form": form, "listing": listing})


@login_required
def ListingDeleteView(request, listing_id):
    listing = CarListing.objects.select_related("car", "seller").get(listing_id=listing_id)
    if not (request.user.is_staff or request.user == listing.seller):
        return redirect("listings")
    if request.method == "POST":
        listing.delete()
        return redirect("listings")
    return render(request, "listings/delete_confirm.html", {"listing": listing})


@login_required
def CarUpdateView(request, vin):
    if not (request.user.is_staff or request.user.is_superuser):
        return redirect("cars")
    car = Car.objects.get(vin=vin)
    if request.method == "POST":
        form = CarForm(request.POST, instance=car)
        if form.is_valid():
            form.save()
            return redirect("cars")
    else:
        form = CarForm(instance=car)
    return render(request, "cars/edit.html", {"form": form, "car": car})


@login_required
def CarDeleteView(request, vin):
    if not (request.user.is_staff or request.user.is_superuser):
        return redirect("cars")
    car = Car.objects.get(vin=vin)
    if request.method == "POST":
        car.delete()
        return redirect("cars")
    return render(request, "cars/delete_confirm.html", {"car": car})


@ensure_csrf_cookie
def UserSignupView(request):
    initial = {}
    pref_role = request.GET.get('role')

    if pref_role in ('Buyer', 'Seller'):
        initial['role'] = pref_role

    if request.method == 'POST':
        form = UserSignupForm(request.POST)

        if form.is_valid():
            user = form.save()
            try:
                user.status = getattr(User, "Status").INACTIVE if hasattr(User, "Status") else "Inactive"
            except Exception:
                user.status = "Inactive"
            code = f"{random.randint(0, 999999):06d}"
            user.otp_code = code
            user.otp_expires = timezone.now() + timedelta(minutes=15)
            user.save(update_fields=["status", "otp_code", "otp_expires"])

            # Create related profile
            if user.role == 'Buyer':
                Buyer.objects.get_or_create(user=user)
            elif user.role == 'Seller':
                Seller.objects.get_or_create(user=user)

            site_url = request.build_absolute_uri("/")
            img_path = os.path.join(settings.BASE_DIR, "static", "img", "bmw-m4-hero.jpg")
            
            def _send():
                try:
                    send_email_html_async(
                        subject="Verify your email – Vehicle Vault",
                        template_name="messages/otp_email.html",
                        context={"user": user, "site_url": site_url, "otp": code},
                        recipients=[user.email],
                        inline_images={"hero": img_path},
                        attachments=_marketing_brochure_attachments(user),
                    )
                except Exception:
                    pass
            transaction.on_commit(_send)

            return redirect('login')   # redirect to login page

        else:
            return render(request, 'core/signup.html', {'form': form})

    else:
        form = UserSignupForm(initial=initial)

    return render(request, 'core/signup.html', {'form': form})


@login_required
def AccountSettingsView(request):
    user = request.user
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'switch':
            user.role = 'Seller' if user.role == 'Buyer' else 'Buyer'
            user.save()
            if user.role == 'Buyer':
                Buyer.objects.get_or_create(user=user)
            else:
                Seller.objects.get_or_create(user=user)
            return redirect('account_settings')
        else:
            user.name = request.POST.get('name') or user.name
            user.phone = request.POST.get('phone') or user.phone
            user.save()
            return redirect('account_settings')
            
    msgs_in = Message.objects.filter(receiver=user).select_related("sender", "listing__car").order_by("-sent_at")
    msgs_out = Message.objects.filter(sender=user).select_related("receiver", "listing__car").order_by("-sent_at")
    listings = []
    purchases = []
    sales = []
    inbox_count = msgs_in.count()
    sent_count = msgs_out.count()
    users_count = 0
    buyers_count = 0
    sellers_count = 0
    listings_total = 0
    messages_total = 0
    drives_total = 0
    sales_total = 0
    
    if user.role == User.Role.SELLER:
        listings = CarListing.objects.select_related("car").filter(seller=user).order_by("-created_at")
        from .models import Transaction
        sales = Transaction.objects.filter(seller=user).select_related("listing__car", "buyer").order_by("-completed_at")
        sales_total = sales.count()
        listings_count = listings.count()
        purchases_count = 0
        drives_count = 0
    else:
        from .models import Transaction
        purchases = Transaction.objects.filter(buyer=user).select_related("listing__car", "seller").order_by("-completed_at")
        purchases_count = purchases.count()
        from .models import TestDrive
        drives_count = TestDrive.objects.filter(buyer=user).count()
        listings_count = 0
        sales_total = 0
        
    if user.is_staff or user.is_superuser:
        users_count = User.objects.count()
        buyers_count = Buyer.objects.count()
        sellers_count = Seller.objects.count()
        listings_total = CarListing.objects.count()
        messages_total = Message.objects.count()
        from .models import TestDrive, Transaction, Inspection
        drives_total = TestDrive.objects.count()
        sales_total = Transaction.objects.filter(status__in=["Paid", "Completed"]).count()
        inspections_total = Inspection.objects.count()
        
    return render(request, 'account/settings.html', {
        'user': user,
        'msgs_in': msgs_in,
        'msgs_out': msgs_out,
        'listings': listings,
        'purchases': purchases,
        'sales': sales,
        'inbox_count': inbox_count,
        'sent_count': sent_count,
        'listings_count': listings_count,
        'purchases_count': purchases_count,
        'drives_count': drives_count,
        'users_count': users_count,
        'buyers_count': buyers_count,
        'sellers_count': sellers_count,
        'listings_total': listings_total,
        'messages_total': messages_total,
        'drives_total': drives_total,
        'sales_total': sales_total,
        'inspections_total': inspections_total if (user.is_staff or user.is_superuser) else 0,
    })


def LogoutViewCustom(request):
    auth_logout(request)
    return redirect('login')


@ensure_csrf_cookie
def UserLoginView(request):
    if request.user.is_authenticated:
        return redirect('home')
    form = UserLoginForm(request.POST or None)
    if request.method == 'POST':
        if form.is_valid():
            user = getattr(form, 'user', None)
            if user:
                status = getattr(user, "status", "Active")
                next_url = request.GET.get('next') or request.POST.get('next')
                if status == "Inactive" and (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False) or (user.email or "").lower() == "admin@example.com"):
                    user.status = "Active"
                    user.otp_code = None
                    user.otp_expires = None
                    try:
                        user.save(update_fields=["status", "otp_code", "otp_expires"])
                    except Exception:
                        user.save()
                    try:
                        auth_login(request, user, backend=settings.AUTHENTICATION_BACKENDS[0])
                    except Exception:
                        auth_login(request, user)
                    site_url = request.build_absolute_uri("/")
                    img_path = os.path.join(settings.BASE_DIR, "static", "img", "bmw-m4-hero.jpg")
                    try:
                        send_email_html_async(
                            subject="Welcome back to Vehicle Vault",
                            template_name="emails/login_user.html",
                            context={"user": user, "site_url": site_url},
                            recipients=[user.email],
                            inline_images={"hero": img_path},
                            attachments=_marketing_brochure_attachments(user),
                        )
                    except Exception:
                        try:
                            send_email_html_async(
                                subject="Welcome back to Vehicle Vault",
                                template_name="emails/login_user.html",
                                context={"user": user, "site_url": site_url},
                                recipients=[user.email],
                                inline_images={"hero": img_path},
                            )
                        except Exception:
                            pass
                    next_url = request.GET.get('next') or request.POST.get('next')
                    return redirect(next_url or 'dashboard')
                    
                if status == "Inactive":
                    code = f"{random.randint(0, 999999):06d}"
                    user.otp_code = code
                    user.otp_expires = timezone.now() + timedelta(minutes=15)
                    user.save(update_fields=["otp_code", "otp_expires"])
                    site_url = request.build_absolute_uri("/")
                    img_path = os.path.join(settings.BASE_DIR, "static", "img", "bmw-m4-hero.jpg")
                    try:
                        send_email_html_async(
                            subject="Verify your email – Vehicle Vault",
                            template_name="messages/otp_email.html",
                            context={"user": user, "site_url": site_url, "otp": code},
                            recipients=[user.email],
                            inline_images={"hero": img_path},
                            attachments=_marketing_brochure_attachments(user),
                        )
                    except Exception:
                        pass
                    return render(request, 'core/login.html', {'form': form, 'otp_required': True, 'email': user.email, 'next': next_url})
                    
                if status == "Blocked":
                    return render(request, 'core/login.html', {'form': form, 'error': 'Your account is blocked.'})
                if status == "Deleted":
                    return render(request, 'core/login.html', {'form': form, 'error': 'This account is deleted.'})
                    
                try:
                    auth_login(request, user, backend=settings.AUTHENTICATION_BACKENDS[0])
                except Exception:
                    auth_login(request, user)
                site_url = request.build_absolute_uri("/")
                img_path = os.path.join(settings.BASE_DIR, "static", "img", "bmw-m4-hero.jpg")
                try:
                    send_email_html_async(
                        subject="Welcome back to Vehicle Vault",
                        template_name="emails/login_user.html",
                        context={"user": user, "site_url": site_url},
                        recipients=[user.email],
                        inline_images={"hero": img_path},
                        attachments=_marketing_brochure_attachments(user),
                    )
                except Exception:
                    try:
                        send_email_html_async(
                            subject="Welcome back to Vehicle Vault",
                            template_name="emails/login_user.html",
                            context={"user": user, "site_url": site_url},
                            recipients=[user.email],
                            inline_images={"hero": img_path},
                        )
                    except Exception:
                        pass
                next_url = request.GET.get('next') or request.POST.get('next')
                return redirect(next_url or 'dashboard')
                
    return render(request, 'core/login.html', {'form': form, 'next': request.GET.get('next', '')})


def VerifyOtpView(request):
    if request.method != "POST":
        return redirect("login")
    email = strip_tags(request.POST.get("email") or "").strip()
    code = strip_tags(request.POST.get("otp") or "").strip()
    next_url = request.POST.get("next") or ""
    try:
        user = User.objects.get(email=email)
        if user.status == "Inactive" and user.otp_code and user.otp_expires and user.otp_expires >= timezone.now() and user.otp_code == code:
            user.status = "Active"
            user.otp_code = None
            user.otp_expires = None
            user.save(update_fields=["status", "otp_code", "otp_expires"])
            try:
                auth_login(request, user, backend=settings.AUTHENTICATION_BACKENDS[0])
            except Exception:
                auth_login(request, user)
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"ok": True, "redirect": next_url or reverse("dashboard")})
            return redirect(next_url or "dashboard")
    except Exception:
        pass
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"ok": False, "error": "Invalid or expired OTP."}, status=400)
    form = UserLoginForm()
    return render(request, "core/login.html", {"form": form, "otp_required": True, "email": email, "error": "Invalid or expired OTP."})


def ResendOtpView(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Method not allowed"}, status=405)
    email = strip_tags(request.POST.get("email") or "").strip()
    try:
        user = User.objects.get(email=email)
        if user.status != "Inactive":
            return JsonResponse({"ok": False, "error": "Account already verified"}, status=400)
        if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False) or (user.email or "").lower() == "admin@example.com":
            return JsonResponse({"ok": False, "error": "Admin does not require OTP"}, status=400)
            
        code = f"{random.randint(0, 999999):06d}"
        user.otp_code = code
        user.otp_expires = timezone.now() + timedelta(minutes=15)
        user.save(update_fields=["otp_code", "otp_expires"])
        site_url = request.build_absolute_uri("/")
        img_path = os.path.join(settings.BASE_DIR, "static", "img", "bmw-m4-hero.jpg")
        try:
            send_email_html_async(
                subject="Your new verification code",
                template_name="messages/otp_email.html",
                context={"user": user, "site_url": site_url, "otp": code},
                recipients=[user.email],
                inline_images={"hero": img_path},
                attachments=_marketing_brochure_attachments(user),
            )
        except Exception:
            pass
        return JsonResponse({"ok": True})
    except User.DoesNotExist:
        return JsonResponse({"ok": False, "error": "User not found"}, status=404)


@login_required
def ActivityTodosView(request):
    from .models import Todo, ActivityLog
    if request.method == "POST":
        action = request.POST.get("action") or ""
        if action == "add":
            title = strip_tags(request.POST.get("title") or "").strip()
            if title:
                Todo.objects.create(user=request.user, title=title)
                ActivityLog.objects.create(user=request.user, action="Created todo", path=request.path)
            return redirect("activity_todos")
        if action == "toggle":
            tid = request.POST.get("id") or ""
            try:
                t = Todo.objects.get(todo_id=tid, user=request.user)
                t.done = not t.done
                t.save()
                ActivityLog.objects.create(user=request.user, action="Toggled todo", path=request.path)
            except Exception:
                pass
            return redirect("activity_todos")
        if action == "delete":
            tid = request.POST.get("id") or ""
            try:
                Todo.objects.get(todo_id=tid, user=request.user).delete()
                ActivityLog.objects.create(user=request.user, action="Deleted todo", path=request.path)
            except Exception:
                pass
            return redirect("activity_todos")
            
    todos = []
    try:
        from .models import Todo as T
        todos = T.objects.filter(user=request.user).order_by("-created_at")
    except Exception:
        todos = []
    return render(request, "activity/todos.html", {"todos": todos})


@login_required
def ActivityMeetingView(request):
    from .models import ActivityLog
    try:
        ActivityLog.objects.create(user=request.user, action="Viewed meeting page", path=request.path)
    except Exception:
        pass
    return render(request, "activity/meeting.html")


@login_required
def ActivityHistoryView(request):
    logs = []
    try:
        from .models import ActivityLog
        logs = ActivityLog.objects.filter(user=request.user).order_by("-created_at")[:200]
    except Exception:
        logs = []
    return render(request, "activity/history.html", {"logs": logs})


@login_required
def EmailStatusView(request):
    backend = getattr(settings, "EMAIL_BACKEND", "")
    host = getattr(settings, "EMAIL_HOST", "")
    user = getattr(settings, "EMAIL_HOST_USER", "")
    use_tls = getattr(settings, "EMAIL_USE_TLS", False)
    use_ssl = getattr(settings, "EMAIL_USE_SSL", False)
    port = getattr(settings, "EMAIL_PORT", None)
    pwd_len = len(getattr(settings, "EMAIL_HOST_PASSWORD", "") or "")
    status = {
        "backend": backend,
        "host_configured": bool(host),
        "user_configured": bool(user),
        "use_tls": use_tls,
        "use_ssl": use_ssl,
        "port": port,
        "password_len": pwd_len,
        "from_email": getattr(settings, "DEFAULT_FROM_EMAIL", ""),
    }
    
    if request.GET.get("send") == "1":
        to = request.GET.get("to") or request.user.email
        try:
            from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or getattr(settings, "EMAIL_HOST_USER", None) or "no-reply@carvault.local"
            n = send_mail("Email delivery test", "If you received this, SMTP is working.", from_email, [to], fail_silently=False)
            status["test_sent"] = n
            status["to"] = to
            return JsonResponse(status)
        except Exception as e:
            status["error"] = str(e)
            status["to"] = to
            return JsonResponse(status, status=500)
    return JsonResponse(status)


def booking(request):
    preselected_id = request.GET.get("listing_id")
    listings = CarListing.objects.select_related("car").filter(status=CarListing.Status.ACTIVE)
    return render(request, "core/booking.html", {
        "key_id": RAZORPAY_KEY_ID, 
        "listings": listings,
        "preselected_id": preselected_id
    })


def booke(request):
    return render(request, "core/booke.html", {"key_id": RAZORPAY_KEY_ID})


@login_required
@csrf_exempt
def create_razorpay_order(request):
    if not razorpay_client:
        return JsonResponse({"error": "Payment gateway is not configured"}, status=503)
    if request.method == "POST":
        listing_id = request.POST.get("listing_id")
        currency = "INR"
        listing = None
        TOKEN_BOOKING_INR = float(os.environ.get("TOKEN_BOOKING_INR", "500"))
        try:
            ORDER_MAX_INR = float(os.environ.get("RAZORPAY_ORDER_MAX_INR", "30000"))
        except Exception:
            ORDER_MAX_INR = 30000.0
            
        # Prefer server-side price from listing for security
        if listing_id:
            from .models import CarListing
            listing = get_object_or_404(CarListing, listing_id=listing_id)
            try:
                price_inr = float(listing.price)
            except Exception:
                return JsonResponse({"error": "Invalid listing price"}, status=400)
            # Fallback to token if exceeding gateway max
            if price_inr > ORDER_MAX_INR:
                amount = int(TOKEN_BOOKING_INR * 100)
                payment_mode = "Token Booking"
            else:
                amount = int(price_inr * 100)
                payment_mode = "Full Payment"
        else:
            # Fallback for minimal quick-pay page
            try:
                amount = int(max(1.0, float(request.POST.get("amount", 500))) * 100)
            except Exception:
                return JsonResponse({"error": "Invalid amount"}, status=400)
            payment_mode = "Full Payment"
            
        try:
            razorpay_order = razorpay_client.order.create({
                "amount": amount,
                "currency": currency,
                "payment_capture": "1"
            })
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)
            
        if listing:
            try:
                from .models import Transaction, CarListing
                # Shipping fields
                shipping_name = (request.POST.get("shipping_name") or "").strip()
                shipping_phone = (request.POST.get("shipping_phone") or "").strip()
                shipping_address = (request.POST.get("shipping_address") or "").strip()
                shipping_city = (request.POST.get("shipping_city") or "").strip()
                shipping_state = (request.POST.get("shipping_state") or "").strip()
                shipping_postcode = (request.POST.get("shipping_postcode") or "").strip()
                shipping_country = (request.POST.get("shipping_country") or "India").strip()
                
                # EMI fields
                try:
                    emi_months = int(request.POST.get("emi_months") or 0) or None
                except Exception:
                    emi_months = None
                try:
                    emi_rate = float(request.POST.get("emi_rate") or 0.0) or None
                except Exception:
                    emi_rate = None
                emi_amount = None
                try:
                    if emi_months and emi_rate:
                        P = float(listing.price or 0.0)
                        r = float(emi_rate) / 12.0 / 100.0
                        n = int(emi_months)
                        if P > 0 and r > 0 and n > 0:
                            emi_amount = P * r * ((1 + r) ** n) / (((1 + r) ** n) - 1)
                except Exception:
                    emi_amount = None

                txn_kwargs = {
                    "listing": listing,
                    "buyer": request.user,
                    "seller": listing.seller,
                    "final_price": (amount / 100.0),
                    "status": Transaction.Status.PENDING,
                    "razorpay_order_id": razorpay_order.get("id"),
                    "payment_method": payment_mode,
                }

                # Backward/forward compatible extras: include only if model supports them.
                optional_txn_kwargs = {
                    "shipping_name": shipping_name or (getattr(request.user, "name", "") or request.user.email),
                    "shipping_phone": shipping_phone or (getattr(request.user, "phone", "") or ""),
                    "shipping_address": shipping_address or "",
                    "shipping_city": shipping_city or "",
                    "shipping_state": shipping_state or "",
                    "shipping_postcode": shipping_postcode or "",
                    "shipping_country": shipping_country or "India",
                    "emi_months": emi_months,
                    "emi_rate": emi_rate,
                    "emi_amount": emi_amount,
                }
                existing_txn_fields = {f.name for f in Transaction._meta.get_fields()}
                for key, val in optional_txn_kwargs.items():
                    if key in existing_txn_fields:
                        txn_kwargs[key] = val

                Transaction.objects.create(**txn_kwargs)
            except Exception as e:
                return JsonResponse({"error": str(e)}, status=400)
        return JsonResponse(razorpay_order)
    return JsonResponse({"error": "Invalid request"}, status=400)


@login_required
@csrf_exempt
def verify_payment(request):
    if not razorpay_client:
        return JsonResponse({"error": "Payment gateway is not configured"}, status=503)
    if request.method == "POST":
        data = request.POST
        params_dict = {
            'razorpay_order_id': data.get('razorpay_order_id'),
            'razorpay_payment_id': data.get('razorpay_payment_id'),
            'razorpay_signature': data.get('razorpay_signature')
        }
        
        try:
            # Verify the payment signature
            razorpay_client.utility.verify_payment_signature(params_dict)
            
            # Update transaction status
            from .models import Transaction
            order_id = data.get('razorpay_order_id')
            transaction = Transaction.objects.get(razorpay_order_id=order_id)
            transaction.razorpay_payment_id = data.get('razorpay_payment_id')
            transaction.razorpay_signature = data.get('razorpay_signature')
            transaction.status = Transaction.Status.PAID
            transaction.completed_at = timezone.now()
            transaction.save()
            
            # Update listing status if it was a purchase
            listing = transaction.listing
            # Only mark SOLD if full payment was collected
            if (getattr(transaction, "payment_method", "") == "Full Payment") and listing.status != CarListing.Status.SOLD:
                listing.status = CarListing.Status.SOLD
                listing.save()
            
            try:
                site_url = request.build_absolute_uri("/")
                dashboard_url = request.build_absolute_uri(reverse("dashboard_buyer"))
                img_path = os.path.join(settings.BASE_DIR, "static", "img", "bmw-m4-hero.jpg")
                ctx = {
                    "site_name": "Vehicle Vault",
                    "dashboard_url": dashboard_url,
                    "buyer_name": getattr(transaction.buyer, "name", "") or transaction.buyer.email,
                    "buyer_email": transaction.buyer.email,
                    "seller_name": getattr(transaction.seller, "name", "") or transaction.seller.email,
                    "seller_email": transaction.seller.email,
                    "transaction_id": str(transaction.transaction_id),
                    "razorpay_order_id": transaction.razorpay_order_id,
                    "razorpay_payment_id": transaction.razorpay_payment_id,
                    "completed_at": timezone.localtime(transaction.completed_at) if transaction.completed_at else "",
                    "status": transaction.status,
                    "car_make": getattr(listing.car, "make", ""),
                    "car_model": getattr(listing.car, "model", ""),
                    "car_year": getattr(listing.car, "year", ""),
                    "vehicle_price": f"{float(listing.price):,.2f}",
                    "booking_amount": f"{float(transaction.final_price):,.2f}",
                    "year": timezone.now().year,
                    # shipping details
                    "shipping_name": getattr(transaction, "shipping_name", None),
                    "shipping_phone": getattr(transaction, "shipping_phone", None),
                    "shipping_address": getattr(transaction, "shipping_address", None),
                    "shipping_city": getattr(transaction, "shipping_city", None),
                    "shipping_state": getattr(transaction, "shipping_state", None),
                    "shipping_postcode": getattr(transaction, "shipping_postcode", None),
                    "shipping_country": getattr(transaction, "shipping_country", None),
                    # emi details
                    "emi_months": getattr(transaction, "emi_months", None),
                    "emi_rate": getattr(transaction, "emi_rate", None),
                    "emi_amount": getattr(transaction, "emi_amount", None),
                }
                send_email_html_async(
                    subject="Payment Receipt – Vehicle Vault",
                    template_name="emails/invoice.html",
                    context=ctx,
                    recipients=[transaction.buyer.email],
                    inline_images={"hero": img_path},
                    attachments=_marketing_brochure_attachments(transaction.buyer),
                )
                send_email_html_async(
                    subject="New Booking Payment Received – Vehicle Vault",
                    template_name="emails/invoice.html",
                    context=ctx,
                    recipients=[transaction.seller.email],
                    inline_images={"hero": img_path},
                    attachments=_marketing_brochure_attachments(transaction.seller),
                )
            except Exception:
                pass
            
            return JsonResponse({"status": "Payment verified successfully"})
        except Exception as e:
            return JsonResponse({"status": "Payment verification failed", "error": str(e)}, status=400)
    return JsonResponse({"error": "Invalid request"}, status=400)


@login_required
def transactions_export(request):
    from .models import Transaction
    fmt = (request.GET.get("format") or request.GET.get("fmt") or "csv").lower()
    if getattr(request.user, "role", None) == User.Role.SELLER:
        qs = Transaction.objects.filter(seller=request.user).select_related("listing__car", "buyer")
        filename_base = "sales"
    else:
        qs = Transaction.objects.filter(buyer=request.user).select_related("listing__car", "seller")
        filename_base = "purchases"

    rows = []
    for t in qs.order_by("-completed_at", "-transaction_id"):
        car = getattr(getattr(t, "listing", None), "car", None)
        rows.append({
            "Date": timezone.localtime(t.completed_at).strftime("%Y-%m-%d %H:%M") if t.completed_at else "",
            "Make": getattr(car, "make", ""),
            "Model": getattr(car, "model", ""),
            "Year": getattr(car, "year", ""),
            "Price": str(t.final_price),
            "Status": t.status,
            "Counterparty": (t.buyer.email if getattr(request.user, "role", None) == User.Role.SELLER else t.seller.email),
            "PaymentMethod": t.payment_method or "",
            "TransactionID": str(t.transaction_id),
        })

    if fmt == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename_base}_history.csv"'
        headers = list(rows[0].keys()) if rows else ["Date","Make","Model","Year","Price","Status","Counterparty","PaymentMethod","TransactionID"]
        writer = csv.DictWriter(response, fieldnames=headers)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
        return response
    elif fmt == "pdf":
        try:
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib import colors
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
            from reportlab.lib.styles import getSampleStyleSheet
        except Exception:
            return HttpResponse("PDF export requires reportlab. Please install it.", status=500)
        response = HttpResponse(content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename_base}_history.pdf"'
        doc = SimpleDocTemplate(response, pagesize=landscape(A4), leftMargin=24, rightMargin=24, topMargin=24, bottomMargin=24)
        elems = []
        styles = getSampleStyleSheet()
        elems.append(Paragraph(f"{filename_base.title()} History", styles["Title"]))
        elems.append(Spacer(1, 12))
        headers = list(rows[0].keys()) if rows else ["Date","Make","Model","Year","Price","Status","Counterparty","PaymentMethod","TransactionID"]
        data = [headers]
        for r in rows:
            data.append([r.get(h, "") for h in headers])
        tbl = Table(data, repeatRows=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#f1f5f9")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.HexColor("#0f172a")),
            ("ALIGN", (0,0), (-1,-1), "LEFT"),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE", (0,0), (-1,0), 10),
            ("BOTTOMPADDING", (0,0), (-1,0), 8),
            ("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#cbd5e1")),
        ]))
        elems.append(tbl)
        doc.build(elems)
        return response
    else:
        return HttpResponse("Unsupported format", status=400)


# --- Geo endpoints for exhaustive States/Cities with graceful fallback ---
def geo_states(request):
    # Try external registry (countriesnow) then fallback to curated list
    states = []
    try:
        data = json.dumps({"country": "India"}).encode("utf-8")
        req = urlrequest.Request(
            "https://countriesnow.space/api/v0.1/countries/states",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlrequest.urlopen(req, timeout=8) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            if body.get("error") is False and body.get("data") and body["data"].get("states"):
                states = [s.get("name") for s in body["data"]["states"] if s.get("name")]
    except Exception:
        states = []
    if not states:
        # minimal curated fallback
        states = sorted({
            "Gujarat","Maharashtra","Karnataka","Tamil Nadu","Telangana","Delhi",
            "Uttar Pradesh","Rajasthan","Madhya Pradesh","West Bengal","Bihar","Punjab","Kerala","Assam","Odisha","Chhattisgarh","Jharkhand","Uttarakhand","Haryana","Goa","Jammu & Kashmir"
        })
    return JsonResponse({"states": states})


def geo_cities(request):
    state = (request.GET.get("state") or "").strip()
    cities = []
    if state:
        try:
            data = json.dumps({"country": "India", "state": state}).encode("utf-8")
            req = urlrequest.Request(
                "https://countriesnow.space/api/v0.1/countries/state/cities",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlrequest.urlopen(req, timeout=8) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                if body.get("error") is False and body.get("data"):
                    cities = [c for c in body["data"] if c]
        except Exception:
            cities = []
    if not cities:
        # small curated fallback per state
        fallback = {
            "Gujarat": ["Ahmedabad","Vadodara","Surat","Rajkot"],
            "Maharashtra": ["Mumbai","Pune","Nagpur","Nashik","Thane"],
            "Karnataka": ["Bengaluru","Mysuru","Mangaluru","Hubballi"],
            "Tamil Nadu": ["Chennai","Coimbatore","Madurai","Tiruchirappalli"],
            "Telangana": ["Hyderabad","Warangal","Nizamabad"],
            "Delhi": ["New Delhi","Delhi"],
            "Uttar Pradesh": ["Lucknow","Kanpur","Agra","Noida","Ghaziabad"],
            "Rajasthan": ["Jaipur","Udaipur","Jodhpur","Kota"],
            "Madhya Pradesh": ["Indore","Bhopal","Gwalior","Jabalpur"],
            "West Bengal": ["Kolkata","Howrah","Durgapur","Siliguri"],
            "Punjab": ["Ludhiana","Amritsar","Jalandhar","Patiala"],
            "Kerala": ["Kochi","Thiruvananthapuram","Kozhikode"],
            "Assam": ["Guwahati","Silchar","Dibrugarh","Jorhat"],
            "Odisha": ["Bhubaneswar","Cuttack","Rourkela"],
            "Chhattisgarh": ["Raipur","Bhilai","Bilaspur"],
            "Jharkhand": ["Ranchi","Jamshedpur","Dhanbad"],
            "Uttarakhand": ["Dehradun","Haridwar"],
            "Haryana": ["Gurugram","Faridabad","Panipat","Karnal"],
            "Goa": ["Panaji","Margao"],
            "Jammu & Kashmir": ["Srinagar","Jammu"]
        }
        cities = fallback.get(state, [])
    return JsonResponse({"state": state, "cities": cities})
