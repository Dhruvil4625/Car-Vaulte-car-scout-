from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Buyer, Car, CarListing, DealRating, Message, Seller, Transaction, User


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
