from datetime import timedelta
import os
import types
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Buyer, Car, CarListing, DealRating, Message, Seller, Transaction, User
from core.ai_utils import (
    recommend_similar_listings,
    session_aware_recs,
    sentiment_analyze,
    toxicity_detect,
    chatbot_query,
    price_fairness_info,
)


class OtpAuthFlowTests(TestCase):
    def setUp(self):
        self.password = "StrongPass123!"
        self.user = User.objects.create_user(
            email="buyer@example.com",
            password=self.password,
            role=User.Role.BUYER,
            status=User.Status.INACTIVE,
            otp_code="123456",
            otp_expires=timezone.now() + timedelta(minutes=15),
        )

    def test_verify_otp_allows_unauthenticated_access_and_logs_user_in(self):
        response = self.client.post(
            reverse("verify_otp"),
            {
                "email": self.user.email,
                "otp": "123456",
            },
        )

        self.assertRedirects(response, reverse("dashboard"), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertEqual(self.user.status, User.Status.ACTIVE)
        self.assertIsNone(self.user.otp_code)
        self.assertIsNone(self.user.otp_expires)

    def test_resend_otp_is_not_blocked_by_auth_middleware(self):
        response = self.client.post(reverse("resend_otp"), {"email": self.user.email})

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"ok": True})

        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.otp_code)
        self.assertEqual(len(self.user.otp_code), 6)

    def test_otp_is_required_only_for_first_login(self):
        verify_response = self.client.post(
            reverse("verify_otp"),
            {
                "email": self.user.email,
                "otp": "123456",
            },
        )
        self.assertEqual(verify_response.status_code, 302)

        self.client.get(reverse("logout"))

        response = self.client.post(
            reverse("login"),
            {
                "email": self.user.email,
                "password": self.password,
            },
        )

        self.assertRedirects(response, reverse("dashboard"), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertEqual(self.user.status, User.Status.ACTIVE)
        self.assertIsNone(self.user.otp_code)
        self.assertIsNone(self.user.otp_expires)


class DealInteractionTests(TestCase):
    def setUp(self):
        self.buyer = User.objects.create_user(
            email="buyer2@example.com",
            password="BuyerPass123!",
            role=User.Role.BUYER,
            status=User.Status.ACTIVE,
        )
        self.seller = User.objects.create_user(
            email="seller2@example.com",
            password="SellerPass123!",
            role=User.Role.SELLER,
            status=User.Status.ACTIVE,
        )
        Buyer.objects.get_or_create(user=self.buyer)
        Seller.objects.get_or_create(user=self.seller, defaults={"dealership_name": "Prime Motors"})
        self.car = Car.objects.create(
            vin="WBSPM9C0XBE999999",
            make="Toyota",
            model="Fortuner",
            year=2022,
            fuel_type="Diesel",
            transmission="Automatic",
            mileage=18000,
            body_type="SUV",
        )
        self.listing = CarListing.objects.create(
            car=self.car,
            seller=self.seller,
            price=3500000,
            mileage=18000,
            description="Ready for a serious deal",
            status=CarListing.Status.ACTIVE,
        )
        self.inquiry = Message.objects.create(
            sender=self.buyer,
            receiver=self.seller,
            listing=self.listing,
            content="I want to buy this car.",
        )

    def test_reply_to_message_creates_reverse_message(self):
        self.client.force_login(self.seller)

        response = self.client.post(
            reverse("message_reply", args=[self.inquiry.message_id]),
            {"content": "Sure, let's discuss the deal.", "next": reverse("messages")},
        )

        self.assertRedirects(response, reverse("messages"), fetch_redirect_response=False)
        reply = Message.objects.filter(sender=self.seller, receiver=self.buyer, listing=self.listing).latest("sent_at")
        self.assertEqual(reply.content, "Sure, let's discuss the deal.")

    def test_accept_deal_creates_completed_transaction(self):
        self.client.force_login(self.seller)

        response = self.client.post(
            reverse("message_accept_deal", args=[self.inquiry.message_id]),
            {"next": reverse("messages")},
        )

        self.assertRedirects(response, reverse("messages"), fetch_redirect_response=False)
        transaction = Transaction.objects.get(listing=self.listing, buyer=self.buyer, seller=self.seller)
        self.assertEqual(transaction.status, Transaction.Status.COMPLETED)
        self.assertIsNotNone(transaction.completed_at)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, CarListing.Status.SOLD)

    def test_rate_user_updates_existing_rating_and_syncs_seller_profile(self):
        self.client.force_login(self.buyer)

        first_response = self.client.post(
            reverse("rate_user", args=[self.seller.user_id]),
            {"score": "4", "review": "Helpful seller", "next": reverse("messages")},
        )
        second_response = self.client.post(
            reverse("rate_user", args=[self.seller.user_id]),
            {"score": "5", "review": "Excellent follow-up", "next": reverse("messages")},
        )

        self.assertRedirects(first_response, reverse("messages"), fetch_redirect_response=False)
        self.assertRedirects(second_response, reverse("messages"), fetch_redirect_response=False)
        self.assertEqual(DealRating.objects.filter(rater=self.buyer, rated_user=self.seller).count(), 1)
        rating = DealRating.objects.get(rater=self.buyer, rated_user=self.seller)
        self.assertEqual(rating.score, 5)
        self.assertEqual(rating.review, "Excellent follow-up")
        self.seller.seller_profile.refresh_from_db()
        self.assertEqual(float(self.seller.seller_profile.rating), 5.0)

    def test_buyer_can_also_be_rated(self):
        self.client.force_login(self.seller)

        response = self.client.post(
            reverse("rate_user", args=[self.buyer.user_id]),
            {"score": "3", "review": "Responsive buyer", "next": reverse("buyers_detail", args=[self.buyer.user_id])},
        )

        self.assertRedirects(response, reverse("buyers_detail", args=[self.buyer.user_id]), fetch_redirect_response=False)
        self.assertTrue(DealRating.objects.filter(rater=self.seller, rated_user=self.buyer, score=3).exists())


class AIFeatureTests(TestCase):
    def setUp(self):
        self.buyer = User.objects.create_user(
            email="aibuyer@example.com",
            password="BuyerPass123!",
            role=User.Role.BUYER,
            status=User.Status.ACTIVE,
        )
        self.seller = User.objects.create_user(
            email="aiseller@example.com",
            password="SellerPass123!",
            role=User.Role.SELLER,
            status=User.Status.ACTIVE,
        )
        self.seller2 = User.objects.create_user(
            email="aiseller2@example.com",
            password="SellerPass123!",
            role=User.Role.SELLER,
            status=User.Status.ACTIVE,
        )
        Seller.objects.update_or_create(
            user=self.seller,
            defaults={"dealership_name": "Alpha Motors", "rating": 4.8},
        )
        Seller.objects.update_or_create(
            user=self.seller2,
            defaults={"dealership_name": "Beta Cars", "rating": 3.6},
        )
        car1 = Car.objects.create(vin="WBSPM9C0XBE223451", make="Toyota", model="Fortuner", year=2021, fuel_type="Diesel", body_type="SUV")
        car2 = Car.objects.create(vin="WBSPM9C0XBE223452", make="Toyota", model="Fortuner", year=2022, fuel_type="Diesel", body_type="SUV")
        car3 = Car.objects.create(vin="WBSPM9C0XBE223453", make="Hyundai", model="Creta", year=2022, fuel_type="Petrol", body_type="SUV")
        car4 = Car.objects.create(vin="WBSPM9C0XBE223454", make="Honda", model="City", year=2021, fuel_type="Petrol", body_type="Sedan")
        self.lst1 = CarListing.objects.create(car=car1, seller=self.seller, price=3000000, mileage=30000, description="Primary SUV")
        self.lst2 = CarListing.objects.create(car=car2, seller=self.seller, price=3200000, mileage=25000, description="Similar SUV")
        self.lst3 = CarListing.objects.create(car=car3, seller=self.seller, price=1800000, mileage=15000, description="Compact SUV")
        self.lst4 = CarListing.objects.create(car=car4, seller=self.seller2, price=1400000, mileage=22000, description="City sedan")

    def test_recommendations_exclude_current_listing(self):
        recs = recommend_similar_listings(self.lst1, [self.lst1, self.lst2, self.lst3], top_k=3)
        self.assertNotIn(self.lst1, recs)
        self.assertGreaterEqual(len(recs), 1)

    def test_session_recommendations_exclude_current_listing(self):
        recs = session_aware_recs(self.buyer, self.lst1, [self.lst1, self.lst2, self.lst3], top_k=3)
        self.assertNotIn(self.lst1, recs)

    def test_sentiment_basic_ordering(self):
        s1 = sentiment_analyze("I love this car")
        s2 = sentiment_analyze("I hate this car")
        self.assertTrue((s1 or 0) > (s2 or 0))

    def test_toxicity_non_toxic_label_maps_to_zero(self):
        fake_transformers = types.SimpleNamespace(
            pipeline=lambda *_a, **_k: (lambda _t: [{"label": "non-toxic", "score": 0.99}])
        )
        with patch.dict("sys.modules", {"transformers": fake_transformers}):
            out = toxicity_detect("Have a nice day")
        self.assertEqual(out, 0.0)

    def test_price_fairness_uses_even_median(self):
        fair = price_fairness_info(self.lst1, [self.lst2, self.lst3])
        self.assertIn(fair["label"], {"Fair Price", "Expensive", "Good Deal", "Slightly Off", "Unknown"})
        self.assertIsNotNone(fair["median"])

    def test_chatbot_fallback_query_filters(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": ""}, clear=False):
            ans = chatbot_query("suv under 35 lakh", [self.lst1, self.lst2, self.lst3])
        self.assertIn("Top suggestions", ans)

    def test_chatbot_best_seller_question(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": ""}, clear=False):
            ans = chatbot_query("which seller is best?", [self.lst1, self.lst2, self.lst3, self.lst4])
        self.assertIn("Best seller right now", ans)
        self.assertIn("Alpha Motors", ans)

    def test_message_signal_populates_sentiment_fields(self):
        msg = Message.objects.create(
            sender=self.buyer,
            receiver=self.seller,
            listing=self.lst1,
            content="Great deal, I love this one",
        )
        msg.refresh_from_db()
        self.assertIsNotNone(msg.sentiment_score)
        self.assertIsNotNone(msg.sentiment_label)
        self.assertIsNotNone(msg.toxicity_score)
