from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from core.models import CarListing, Transaction, Message, Buyer, Seller, TestDrive, Inspection
from .decorators import role_required
from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth

User = get_user_model()

@login_required(login_url="login")
def dashboard_router(request):
    user = request.user
    if user.is_staff or user.is_superuser:
        return redirect("dashboard_admin")
    if user.role == User.Role.SELLER:
        return redirect("dashboard_seller")
    return redirect("dashboard_buyer")

@role_required(allowed_roles=["ADMIN"], login_url="login")
def dashboard_admin(request):
    users_count = User.objects.count()
    buyers_count = Buyer.objects.count()
    sellers_count = Seller.objects.count()
    listings_count = CarListing.objects.count()
    sales_count = Transaction.objects.filter(status__in=["Paid", "Completed"]).count()
    messages_count = Message.objects.count()
    drives_count = TestDrive.objects.count()
    inspections_count = Inspection.objects.count()
    # Platform-wide analytics
    from django.db.models import Count, Sum
    from django.db.models.functions import TruncMonth
    monthly = (
        Transaction.objects.filter(status__in=["Paid", "Completed"])
        .annotate(month=TruncMonth("completed_at"))
        .values("month")
        .annotate(count=Count("transaction_id"), revenue=Sum("final_price"))
        .order_by("month")
    )
    monthly_labels = [m["month"].strftime("%b %Y") if m["month"] else "N/A" for m in monthly]
    monthly_counts = [int(m["count"]) for m in monthly]
    monthly_revenue = [float(m["revenue"] or 0.0) for m in monthly]
    top_views_qs = CarListing.objects.order_by("-views_count").values_list("car__model", "views_count")[:10]
    top_labels = [t[0] or "Listing" for t in top_views_qs]
    top_views = [int(t[1] or 0) for t in top_views_qs]
    ctx = {
        "users_count": users_count,
        "buyers_count": buyers_count,
        "sellers_count": sellers_count,
        "listings_count": listings_count,
        "sales_count": sales_count,
        "messages_count": messages_count,
        "drives_count": drives_count,
        "inspections_count": inspections_count,
        "monthly_labels": monthly_labels,
        "monthly_counts": monthly_counts,
        "monthly_revenue": monthly_revenue,
        "top_labels": top_labels,
        "top_views": top_views,
    }
    return render(request, "dashboard/admin.html", ctx)

@role_required(allowed_roles=[User.Role.SELLER], login_url="login")
def dashboard_seller(request):
    listings = CarListing.objects.select_related("car").filter(seller=request.user).order_by("-created_at")[:10]
    sales = Transaction.objects.filter(seller=request.user).select_related("listing__car", "buyer").order_by("-completed_at")[:10]
    inbox = Message.objects.filter(receiver=request.user).select_related("sender").order_by("-sent_at")[:10]
    # Analytics
    monthly = (
        Transaction.objects.filter(seller=request.user, status__in=["Paid", "Completed"])
        .annotate(month=TruncMonth("completed_at"))
        .values("month")
        .annotate(count=Count("transaction_id"), revenue=Sum("final_price"))
        .order_by("month")
    )
    monthly_labels = [m["month"].strftime("%b %Y") if m["month"] else "N/A" for m in monthly]
    monthly_counts = [int(m["count"]) for m in monthly]
    monthly_revenue = [float(m["revenue"] or 0.0) for m in monthly]
    tops = CarListing.objects.filter(seller=request.user).order_by("-views_count").values_list("car__model", "views_count")[:5]
    top_labels = [t[0] or "Listing" for t in tops]
    top_views = [int(t[1] or 0) for t in tops]
    ctx = {
        "listings": listings,
        "sales": sales,
        "inbox": inbox,
        "monthly_labels": monthly_labels,
        "monthly_counts": monthly_counts,
        "monthly_revenue": monthly_revenue,
        "top_labels": top_labels,
        "top_views": top_views,
    }
    return render(request, "dashboard/seller.html", ctx)

@role_required(allowed_roles=[User.Role.BUYER], login_url="login")
def dashboard_buyer(request):
    purchases = Transaction.objects.filter(buyer=request.user).select_related("listing__car", "seller").order_by("-completed_at")[:10]
    drives = TestDrive.objects.filter(buyer=request.user).select_related("listing__car").order_by("-proposed_date")[:10]
    inbox = Message.objects.filter(receiver=request.user).select_related("sender").order_by("-sent_at")[:10]
    from django.db.models import Count, Sum
    from django.db.models.functions import TruncMonth
    from core.models import Favorite, SavedSearch
    favs = Favorite.objects.filter(user=request.user).select_related("listing__car").order_by("-created_at")[:6]
    searches = SavedSearch.objects.filter(user=request.user).order_by("-created_at")[:6]
    monthly = (
        Transaction.objects.filter(buyer=request.user, status__in=["Paid", "Completed"])
        .annotate(month=TruncMonth("completed_at"))
        .values("month")
        .annotate(count=Count("transaction_id"), amount=Sum("final_price"))
        .order_by("month")
    )
    monthly_labels = [m["month"].strftime("%b %Y") if m["month"] else "N/A" for m in monthly]
    monthly_counts = [int(m["count"]) for m in monthly]
    monthly_amount = [float(m["amount"] or 0.0) for m in monthly]
    ctx = {
        "purchases": purchases,
        "drives": drives,
        "inbox": inbox,
        "favorites": favs,
        "saved_searches": searches,
        "monthly_labels": monthly_labels,
        "monthly_counts": monthly_counts,
        "monthly_amount": monthly_amount,
    }
    return render(request, "dashboard/buyer.html", ctx)
