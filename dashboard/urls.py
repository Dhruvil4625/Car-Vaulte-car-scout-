from django.urls import path
from .views import dashboard_router, dashboard_admin, dashboard_buyer, dashboard_seller

urlpatterns = [
    path("", dashboard_router, name="dashboard"),
    path("admin/", dashboard_admin, name="dashboard_admin"),
    path("buyer/", dashboard_buyer, name="dashboard_buyer"),
    path("seller/", dashboard_seller, name="dashboard_seller"),
]
