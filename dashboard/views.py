from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from core.models import CarListing, Transaction, Message, Buyer, Seller, TestDrive

User = get_user_model()

@login_required(login_url="login")
def dashboard_router(request):
    user = request.user
    if user.is_staff or user.is_superuser:
        return redirect("dashboard_admin")
    if user.role == User.Role.SELLER:
        return redirect("dashboard_seller")
    return redirect("dashboard_buyer")

@login_required(login_url="login")
def dashboard_admin(request):
    users_count = User.objects.count()
    buyers_count = Buyer.objects.count()
    sellers_count = Seller.objects.count()
    listings_count = CarListing.objects.count()
    sales_count = Transaction.objects.filter(status__in=["Paid", "Completed"]).count()
    messages_count = Message.objects.count()
    drives_count = TestDrive.objects.count()
    ctx = {
        "users_count": users_count,
        "buyers_count": buyers_count,
        "sellers_count": sellers_count,
        "listings_count": listings_count,
        "sales_count": sales_count,
        "messages_count": messages_count,
        "drives_count": drives_count,
    }
    return render(request, "dashboard/admin.html", ctx)

@login_required(login_url="login")
def dashboard_seller(request):
    listings = CarListing.objects.select_related("car").filter(seller=request.user).order_by("-created_at")[:10]
    sales = Transaction.objects.filter(seller=request.user).select_related("listing__car", "buyer").order_by("-completed_at")[:10]
    inbox = Message.objects.filter(receiver=request.user).select_related("sender").order_by("-sent_at")[:10]
    ctx = {"listings": listings, "sales": sales, "inbox": inbox}
    return render(request, "dashboard/seller.html", ctx)

@login_required(login_url="login")
def dashboard_buyer(request):
    purchases = Transaction.objects.filter(buyer=request.user).select_related("listing__car", "seller").order_by("-completed_at")[:10]
    drives = TestDrive.objects.filter(buyer=request.user).select_related("listing__car").order_by("-proposed_date")[:10]
    inbox = Message.objects.filter(receiver=request.user).select_related("sender").order_by("-sent_at")[:10]
    ctx = {"purchases": purchases, "drives": drives, "inbox": inbox}
    return render(request, "dashboard/buyer.html", ctx)
