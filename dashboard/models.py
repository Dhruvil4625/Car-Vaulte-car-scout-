from django.db import models
from core.models import Seller, Buyer

class DashboardWidget(models.Model):
    """Model to store dashboard widget metadata and user preferences."""
    WIDGET_TYPES = [
        ('sales', 'Recent Sales'),
        ('inventory', 'Inventory Status'),
        ('inquiries', 'Recent Inquiries'),
        ('test_drives', 'Test Drive Requests'),
        ('messages', 'Messages'),
        ('analytics', 'Analytics'),
    ]
    
    name = models.CharField(max_length=100)
    widget_type = models.CharField(max_length=20, choices=WIDGET_TYPES)
    is_active = models.BooleanField(default=True)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.name} - {self.widget_type}"


class DashboardMetrics(models.Model):
    """Model to store dashboard metrics and statistics."""
    seller = models.OneToOneField(Seller, on_delete=models.CASCADE, related_name='metrics')
    total_listings = models.IntegerField(default=0)
    active_listings = models.IntegerField(default=0)
    total_views = models.IntegerField(default=0)
    total_inquiries = models.IntegerField(default=0)
    total_test_drives = models.IntegerField(default=0)
    response_rate = models.FloatField(default=0.0)  # Percentage
    average_days_to_sell = models.IntegerField(default=0)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Dashboard Metrics"

    def __str__(self):
        return f"Metrics for {self.seller.user.email}"
