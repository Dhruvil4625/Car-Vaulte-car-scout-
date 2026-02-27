import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager

class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        
        return self.create_user(email, password, **extra_fields)

class User(AbstractUser):
    class Role(models.TextChoices):
        BUYER = 'Buyer', 'Buyer'
        SELLER = 'Seller', 'Seller'

    username = None
    user_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=100, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.BUYER)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return self.email

class Buyer(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True, related_name='buyer_profile')
    preferences = models.JSONField(blank=True, null=True)
    favorite_count = models.IntegerField(default=0)

    def __str__(self):
        return f"Buyer: {self.user.email}"

class Seller(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True, related_name='seller_profile')
    dealership_name = models.CharField(max_length=100, blank=True, null=True)
    location = models.CharField(max_length=150, blank=True, null=True)
    rating = models.DecimalField(max_digits=3, decimal_places=2, default=0.00)

    def __str__(self):
        return f"Seller: {self.user.email}"

class Car(models.Model):
    vin = models.CharField(max_length=17, primary_key=True)
    make = models.CharField(max_length=50)
    model = models.CharField(max_length=100)
    year = models.PositiveSmallIntegerField()
    color = models.CharField(max_length=50, blank=True, null=True)
    fuel_type = models.CharField(max_length=30, blank=True, null=True)
    transmission = models.CharField(max_length=30, blank=True, null=True)
    mileage = models.IntegerField(blank=True, null=True, help_text="Odometer reading (km)")
    body_type = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return f"{self.year} {self.make} {self.model} ({self.vin})"

class CarListing(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'Active', 'Active'
        PENDING = 'Pending', 'Pending'
        SOLD = 'Sold', 'Sold'
        WITHDRAWN = 'Withdrawn', 'Withdrawn'

    listing_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='listings')
    seller = models.ForeignKey(User, on_delete=models.CASCADE, related_name='listings')
    price = models.DecimalField(max_digits=12, decimal_places=2)
    mileage = models.IntegerField()
    description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    views_count = models.IntegerField(default=0)
    showroom = models.ForeignKey('Showroom', on_delete=models.SET_NULL, related_name='car_listings', blank=True, null=True)

    def __str__(self):
        return f"Listing {self.listing_id} - {self.car}"

class CarListingImage(models.Model):
    listing = models.ForeignKey(CarListing, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='listing_images/')
    alt = models.CharField(max_length=120, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Image for {self.listing_id if hasattr(self,'listing_id') else self.listing}"

class Inspection(models.Model):
    class Source(models.TextChoices):
        AI = 'AI', 'AI'
        THIRD_PARTY = 'Third-party', 'Third-party'
        SELF = 'Self', 'Self'

    inspection_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    listing = models.ForeignKey(CarListing, on_delete=models.CASCADE, related_name='inspections')
    inspection_date = models.DateTimeField()
    condition_score = models.DecimalField(max_digits=3, decimal_places=1, blank=True, null=True)
    accident_history = models.TextField(blank=True, null=True)
    report_details = models.JSONField(blank=True, null=True)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.SELF)

    def __str__(self):
        return f"Inspection {self.inspection_id} for {self.listing}"

class Message(models.Model):
    message_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_messages')
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_messages')
    listing = models.ForeignKey(CarListing, on_delete=models.SET_NULL, blank=True, null=True, related_name='messages')
    content = models.TextField()
    sent_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    def __str__(self):
        return f"Message from {self.sender} to {self.receiver}"

class TestDrive(models.Model):
    class Status(models.TextChoices):
        REQUESTED = 'Requested', 'Requested'
        CONFIRMED = 'Confirmed', 'Confirmed'
        COMPLETED = 'Completed', 'Completed'
        CANCELLED = 'Cancelled', 'Cancelled'

    test_drive_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    listing = models.ForeignKey(CarListing, on_delete=models.CASCADE, related_name='test_drives')
    buyer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='test_drives')
    proposed_date = models.DateTimeField()
    actual_date = models.DateTimeField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REQUESTED)
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Test Drive {self.status} - {self.listing}"

class Transaction(models.Model):
    class Status(models.TextChoices):
        PENDING = 'Pending', 'Pending'
        PAID = 'Paid', 'Paid'
        COMPLETED = 'Completed', 'Completed'
        CANCELLED = 'Cancelled', 'Cancelled'
        REFUNDED = 'Refunded', 'Refunded'

    transaction_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    listing = models.ForeignKey(CarListing, on_delete=models.CASCADE, related_name='transactions')
    buyer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='purchases')
    seller = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sales')
    final_price = models.DecimalField(max_digits=12, decimal_places=2)
    completed_at = models.DateTimeField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    payment_method = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return f"Transaction {self.transaction_id} - {self.status}"

class Showroom(models.Model):
    showroom_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    city = models.CharField(max_length=80)
    state = models.CharField(max_length=80)
    address = models.CharField(max_length=200, blank=True)
    map_query = models.CharField(max_length=200, blank=True, help_text="Query string used for Google Maps search")
    seller = models.ForeignKey(User, on_delete=models.SET_NULL, related_name='showrooms', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} — {self.city}, {self.state}"

class UpcomingArrival(models.Model):
    class Status(models.TextChoices):
        ANNOUNCED = 'Announced', 'Announced'
        DELAYED = 'Delayed', 'Delayed'
        CANCELLED = 'Cancelled', 'Cancelled'

    arrival_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    showroom = models.ForeignKey(Showroom, on_delete=models.CASCADE, related_name='arrivals')
    make = models.CharField(max_length=50, blank=True)
    model = models.CharField(max_length=100, blank=True)
    year = models.PositiveSmallIntegerField(blank=True, null=True)
    expected_date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ANNOUNCED)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"Arrival {self.make} {self.model} at {self.showroom}"

class Todo(models.Model):
    todo_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='todos')
    title = models.CharField(max_length=200)
    done = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

class ActivityLog(models.Model):
    log_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='activity_logs')
    action = models.CharField(max_length=200)
    path = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.email} - {self.action}"
