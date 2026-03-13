from django.test import TestCase
from django.utils.timezone import now
from core.models import User, Car, CarListing, Message, Inspection, Showroom
from core.ai_utils import recommend_similar_listings, sentiment_analyze

class AiBasicsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="seller@example.com", password="x", role=User.Role.SELLER)
        car1 = Car.objects.create(vin="WBSPM9C0XBE123456", make="Toyota", model="Fortuner", year=2021, fuel_type="Diesel", body_type="SUV")
        car2 = Car.objects.create(vin="WBSPM9C0XBE123457", make="Toyota", model="Innova", year=2020, fuel_type="Diesel", body_type="MPV")
        car3 = Car.objects.create(vin="WBSPM9C0XBE123458", make="Hyundai", model="Creta", year=2022, fuel_type="Petrol", body_type="SUV")
        self.lst1 = CarListing.objects.create(car=car1, seller=self.user, price=3000000, mileage=30000, description="Nice SUV")
        self.lst2 = CarListing.objects.create(car=car2, seller=self.user, price=2400000, mileage=25000, description="Family MPV")
        self.lst3 = CarListing.objects.create(car=car3, seller=self.user, price=1800000, mileage=15000, description="Compact SUV")

    def test_recommendations(self):
        recs = recommend_similar_listings(self.lst1, [self.lst2, self.lst3], top_k=2)
        self.assertTrue(len(recs) >= 1)

    def test_sentiment(self):
        s1 = sentiment_analyze("I love this car")
        s2 = sentiment_analyze("I hate this car")
        self.assertTrue((s1 or 0) > (s2 or 0))
