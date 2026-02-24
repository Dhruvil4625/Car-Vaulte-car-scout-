from django.shortcuts import render, redirect
from django.db.models import Q
from .forms import UserSignupForm, CarListingForm, CarForm
from .models import Car, CarListing, Message, TestDrive, Buyer, Seller, CarListingImage
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.utils.html import strip_tags
from django.contrib.auth import get_user_model
User = get_user_model()

def HomeView(request):
    top_listings = CarListing.objects.select_related("car", "seller").prefetch_related("images").order_by("-created_at")[:8]
    return render(request, "home/index.html", {"listings": top_listings})

def CarsListView(request):
    qs = Car.objects.all()
    fuel = request.GET.get("fuel") or ""
    q = request.GET.get("q") or ""
    brand = request.GET.get("brand") or ""
    model = request.GET.get("model") or ""
    if fuel:
        qs = qs.filter(fuel_type__iexact=fuel)
    if q:
        qs = qs.filter(Q(make__icontains=q) | Q(model__icontains=q) | Q(color__icontains=q))
    if brand:
        qs = qs.filter(make__icontains=brand)
    if model:
        qs = qs.filter(model__icontains=model)
    return render(request, "cars/list.html", {"cars": qs, "fuel": fuel, "brand": brand, "model": model, "q": q})

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
    car_form = CarForm(request.POST or None)
    listing_form = CarListingForm(request.POST or None)
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
def UserSignupView(request):
    initial = {}
    pref_role = request.GET.get('role')
    if pref_role in ('Buyer', 'Seller'):
        initial['role'] = pref_role
    if request.method == 'POST':
        form = UserSignupForm(request.POST, initial=initial)
        if form.is_valid():
            user = form.save()
            if user.role == 'Buyer':
                Buyer.objects.get_or_create(user=user)
            elif user.role == 'Seller':
                Seller.objects.get_or_create(user=user)
            auth_login(request, user)
            return redirect('home')
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
    return render(request, 'account/settings.html', {'user': user})

def LogoutViewCustom(request):
    auth_logout(request)
    return redirect('login')
