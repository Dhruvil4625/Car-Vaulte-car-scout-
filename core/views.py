from django.shortcuts import render, redirect
from django.db.models import Q
from .forms import UserSignupForm, CarListingForm, CarForm, UpcomingArrivalForm
from .models import Car, CarListing, Message, TestDrive, Buyer, Seller, CarListingImage, Showroom, UpcomingArrival
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils.html import strip_tags
from django.contrib.auth import get_user_model
from .forms import UserLoginForm, InspectionForm
from django.http import JsonResponse
from django.core.mail import send_mail
from django.conf import settings
from core.email_utils import send_email_html
import os

User = get_user_model()

def HomeView(request):
    top_listings = CarListing.objects.select_related("car", "seller").prefetch_related("images").order_by("-created_at")[:8]
    return render(request, "home/index.html", {"listings": top_listings})

def CarsListView(request):
    qs = Car.objects.all().prefetch_related("listings__images")
    fuel = request.GET.get("fuel") or request.GET.get("fuel_type") or ""
    q = request.GET.get("q") or ""
    brand = request.GET.get("brand") or ""
    model = request.GET.get("model") or ""
    body = request.GET.get("body") or request.GET.get("body_type") or ""
    if fuel:
        qs = qs.filter(fuel_type__iexact=fuel)
    if q:
        qs = qs.filter(Q(make__icontains=q) | Q(model__icontains=q) | Q(color__icontains=q))
    if brand:
        qs = qs.filter(make__icontains=brand)
    if model:
        qs = qs.filter(model__icontains=model)
    if body:
        qs = qs.filter(body_type__icontains=body)
    return render(request, "cars/list.html", {"cars": qs, "fuel": fuel, "brand": brand, "model": model, "q": q, "body": body})

def ListingsListView(request):
    qs = CarListing.objects.select_related("car", "seller").prefetch_related("images").order_by("-created_at")
    q = request.GET.get("q") or ""
    budget = request.GET.get("budget") or ""
    fuel = request.GET.get("fuel") or ""
    brand = request.GET.get("brand") or ""
    model = request.GET.get("model") or ""
    if q:
        qs = qs.filter(Q(car__make__icontains=q) | Q(car__model__icontains=q) | Q(description__icontains=q) | Q(seller__email__icontains=q))
    if brand:
        qs = qs.filter(car__make__icontains=brand)
    if model:
        qs = qs.filter(car__model__icontains=model)
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
    return render(request, "listings/list.html", {"listings": listings, "q": q, "budget": budget, "fuel": fuel, "brand": brand, "model": model})

def ListingDetailView(request, listing_id):
    listing = CarListing.objects.select_related("car", "seller").prefetch_related("images", "inspections").get(listing_id=listing_id)
    is_buyer = request.user.is_authenticated and request.user.role == User.Role.BUYER
    try:
        inspection = listing.inspections.order_by("-inspection_date").first()
    except Exception:
        inspection = None
    return render(request, "listings/detail.html", {"listing": listing, "is_buyer": is_buyer, "inspection": inspection})

@login_required
def ListingMessageView(request, listing_id):
    listing = CarListing.objects.select_related("car", "seller").get(listing_id=listing_id)
    content = strip_tags(request.POST.get("content") or "").strip()
    if content:
        Message.objects.create(sender=request.user, receiver=listing.seller, listing=listing, content=content)
        return redirect("listing_detail", listing_id=listing.listing_id)
    return redirect("listing_detail", listing_id=listing.listing_id)

@login_required
def PurchaseListingView(request, listing_id):
    listing = CarListing.objects.select_related("car", "seller").get(listing_id=listing_id)
    if not (request.user.role == User.Role.BUYER):
        return redirect("listing_detail", listing_id=listing.listing_id)
    try:
        from .models import Transaction
        Transaction.objects.create(
            listing=listing,
            buyer=request.user,
            seller=listing.seller,
            final_price=listing.price,
        )
    except Exception:
        pass
    return redirect("messages")
def MessagesInboxView(request):
    inbox = Message.objects.filter(receiver=request.user).select_related("sender").order_by("-sent_at") if request.user.is_authenticated else []
    return render(request, "messages/inbox.html", {"messages": inbox})

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
    return render(request, "profiles/buyer_detail.html", {"buyer": buyer, "listings": listings})

def SellerDetailView(request, user_id):
    seller = Seller.objects.select_related("user").get(user__user_id=user_id)
    listings = CarListing.objects.select_related("car").filter(seller=seller.user, status=CarListing.Status.ACTIVE)
    return render(request, "profiles/seller_detail.html", {"seller": seller, "listings": listings})

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
            Message.objects.create(sender=request.user, receiver=seller.user, listing=listing, content=content)
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
            Message.objects.create(sender=request.user, receiver=buyer.user, listing=listing, content=content)
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
            car = car_form.save()
            listing = listing_form.save(commit=False)
            listing.car = car
            listing.seller = request.user
            listing.save()
            for f in request.FILES.getlist("images"):
                try:
                    CarListingImage.objects.create(listing=listing, image=f, alt=f.name)
                except Exception:
                    pass
            return redirect("listings")
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
    if not request.user.is_staff:
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
    if not request.user.is_staff:
        return redirect("cars")
    car = Car.objects.get(vin=vin)
    if request.method == "POST":
        car.delete()
        return redirect("cars")
    return render(request, "cars/delete_confirm.html", {"car": car})
    
from django.shortcuts import render, redirect
from django.conf import settings
from django.core.mail import send_mail
from django.contrib.auth import get_user_model

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

            # Create related profile
            if user.role == 'Buyer':
                Buyer.objects.get_or_create(user=user)
            elif user.role == 'Seller':
                Seller.objects.get_or_create(user=user)

            site_url = request.build_absolute_uri("/")
            img_path = os.path.join(settings.BASE_DIR, "static", "img", "bmw-m4-hero.jpg")
            try:
                send_email_html(
                    subject="Welcome to Car Scout",
                    template_name="emails/welcome_user.html",
                    context={"user": user, "site_url": site_url},
                    recipients=[user.email],
                    inline_images={"hero": img_path},
                )
            except Exception:
                pass

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
                auth_login(request, user)
                site_url = request.build_absolute_uri("/")
                img_path = os.path.join(settings.BASE_DIR, "static", "img", "bmw-m4-hero.jpg")
                try:
                    send_email_html(
                        subject="Welcome back to Car Scout",
                        template_name="emails/login_user.html",
                        context={"user": user, "site_url": site_url},
                        recipients=[user.email],
                        inline_images={"hero": img_path},
                    )
                except Exception:
                    pass
                next_url = request.GET.get('next') or request.POST.get('next')
                return redirect(next_url or 'dashboard')
    return render(request, 'core/login.html', {'form': form})

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
