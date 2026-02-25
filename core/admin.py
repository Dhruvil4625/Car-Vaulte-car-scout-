from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Buyer, Seller, Car, CarListing, CarListingImage, Inspection, Message, TestDrive, Transaction, Showroom, UpcomingArrival

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    ordering = ['email']
    list_display = ['email', 'role', 'name', 'is_staff']
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {'fields': ('name', 'phone', 'role')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'password1', 'password2', 'role', 'is_staff', 'is_superuser'),
        }),
    )

search_fields = ('email')
admin.site.register(Buyer)
admin.site.register(Seller)
admin.site.register(Car)
admin.site.register(CarListing)
admin.site.register(Inspection)
admin.site.register(Message)
admin.site.register(TestDrive)
admin.site.register(Transaction)
admin.site.register(CarListingImage)
@admin.register(Showroom)
class ShowroomAdmin(admin.ModelAdmin):
    list_display = ('name', 'city', 'state', 'seller')
    search_fields = ('name', 'city', 'state', 'address', 'map_query')
    list_filter = ('state', 'city')

@admin.register(UpcomingArrival)
class UpcomingArrivalAdmin(admin.ModelAdmin):
    list_display = ('make', 'model', 'year', 'showroom', 'expected_date', 'status')
    list_filter = ('status', 'expected_date', 'showroom')
    search_fields = ('make', 'model', 'notes')
