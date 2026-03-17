import uuid

from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db.models.signals import post_save
from django.dispatch import receiver


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

    class Status(models.TextChoices):
        ACTIVE = 'Active', 'Active'
        INACTIVE = 'Inactive', 'Inactive'
        BLOCKED = 'Blocked', 'Blocked'
        DELETED = 'Deleted', 'Deleted'

    username = None
    user_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=100, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.BUYER)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.INACTIVE)
    otp_code = models.CharField(max_length=6, blank=True, null=True)
    otp_expires = models.DateTimeField(blank=True, null=True)
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


class DealRating(models.Model):
    rating_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rater = models.ForeignKey(User, on_delete=models.CASCADE, related_name='given_deal_ratings')
    rated_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_deal_ratings')
    score = models.PositiveSmallIntegerField(default=5)
    review = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['rater', 'rated_user'], name='unique_deal_rating_pair')
        ]

    def __str__(self):
        return f"{self.rater.email} rated {self.rated_user.email}: {self.score}/5"


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
    engine_cc = models.IntegerField(blank=True, null=True)
    power_bhp = models.DecimalField(max_digits=6, decimal_places=1, blank=True, null=True)
    torque_nm = models.DecimalField(max_digits=6, decimal_places=1, blank=True, null=True)
    gncap_rating = models.PositiveSmallIntegerField(blank=True, null=True)
    expert_overview = models.TextField(blank=True, null=True)
    expert_exterior = models.TextField(blank=True, null=True)
    expert_interior = models.TextField(blank=True, null=True)
    expert_performance = models.TextField(blank=True, null=True)
    expert_verdict = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.year} {self.make} {self.model} ({self.vin})"


class CarPro(models.Model):
    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='pros')
    text = models.CharField(max_length=200)

    def __str__(self):
        return f"Pro for {self.car}: {self.text[:30]}"


class CarCon(models.Model):
    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='cons')
    text = models.CharField(max_length=200)

    def __str__(self):
        return f"Con for {self.car}: {self.text[:30]}"


class CarVariant(models.Model):
    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='variants')
    name = models.CharField(max_length=120)
    ex_showroom_price = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    is_top_selling = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.car} {self.name}"


class UserReview(models.Model):
    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='user_reviews')
    reviewer_name = models.CharField(max_length=120)
    rating = models.DecimalField(max_digits=2, decimal_places=1, blank=True, null=True)
    title = models.CharField(max_length=200, blank=True, null=True)
    content = models.TextField(blank=True, null=True)
    date_posted = models.DateField(auto_now_add=True)

    def __str__(self):
        return f"{self.reviewer_name} on {self.car}"


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
    market_price = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    insurance_amount = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    import_duty = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    on_road_price = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    deal_label = models.CharField(max_length=24, blank=True, null=True)
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


class CarListingAsset(models.Model):
    class Kind(models.TextChoices):
        THREE_D = '3D_MODEL', '3D Model'
        PANORAMA_EXTERIOR = 'PANORAMA_EXTERIOR', 'Exterior Panorama'
        PANORAMA_INTERIOR = 'PANORAMA_INTERIOR', 'Interior Panorama'
        SKETCHFAB = 'SKETCHFAB', 'Sketchfab Embed'
        OTHER = 'OTHER', 'Other'

    listing = models.ForeignKey(CarListing, on_delete=models.CASCADE, related_name='assets')
    asset = models.FileField(upload_to='listing_assets/', blank=True, null=True)
    kind = models.CharField(max_length=32, choices=Kind.choices, default=Kind.OTHER)
    label = models.CharField(max_length=120, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.kind} for {self.listing}"


class Inspection(models.Model):
    class Source(models.TextChoices):
        AI = 'AI', 'AI'
        THIRD_PARTY = 'Third-party', 'Third-party'
        SELF = 'Self', 'Self'

    inspection_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    listing = models.ForeignKey(CarListing, on_delete=models.CASCADE, related_name='inspections')
    inspection_date = models.DateTimeField()
    condition_score = models.DecimalField(max_digits=3, decimal_places=1, blank=True, null=True)
    ai_condition_score = models.DecimalField(max_digits=3, decimal_places=1, blank=True, null=True)
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
    sentiment_score = models.FloatField(blank=True, null=True)
    sentiment_label = models.CharField(max_length=20, blank=True, null=True)
    toxicity_score = models.FloatField(blank=True, null=True)

    def __str__(self):
        return f"Message from {self.sender} to {self.receiver}"


@receiver(post_save, sender=Message)
def _analyze_sentiment(sender, instance, created, **kwargs):
    if not created:
        return
    try:
        from .ai_utils import sentiment_analyze, sentiment_analyze_multilingual, toxicity_detect
        s = sentiment_analyze(instance.content or "")
        ml = sentiment_analyze_multilingual(instance.content or "")
        tox = toxicity_detect(instance.content or "")
        instance.sentiment_score = s
        instance.sentiment_label = ml.get("label")
        instance.toxicity_score = tox
        instance.save(update_fields=["sentiment_score", "sentiment_label", "toxicity_score"])
    except Exception:
        pass


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
    razorpay_order_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_signature = models.CharField(max_length=200, blank=True, null=True)

    def __str__(self):
        return f"Transaction {self.transaction_id} - {self.status}"


@receiver(post_save, sender=Transaction)
def _set_listing_sold_on_payment(sender, instance, created, **kwargs):
    try:
        if instance.status in (Transaction.Status.PAID, Transaction.Status.COMPLETED):
            listing = instance.listing
            if listing and listing.status != CarListing.Status.SOLD:
                listing.status = CarListing.Status.SOLD
                try:
                    listing.save(update_fields=["status", "updated_at"])
                except Exception:
                    listing.save()
    except Exception:
        # Avoid blocking transactions on signal errors
        pass

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


class Favorite(models.Model):
    favorite_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="favorites")
    listing = models.ForeignKey(CarListing, on_delete=models.CASCADE, related_name="favorited_by")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "listing"], name="unique_favorite_user_listing")
        ]

    def __str__(self):
        return f"{self.user.email} ♥ {self.listing}"


class SavedSearch(models.Model):
    saved_search_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="saved_searches")
    name = models.CharField(max_length=120, blank=True)
    params = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Search by {self.user.email} - {self.name or self.saved_search_id}"
