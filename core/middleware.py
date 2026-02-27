from django.shortcuts import redirect
from django.urls import reverse
from django.conf import settings


class AuthGateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if request.user.is_authenticated:
            return self.get_response(request)

        login_url = reverse("login")
        signup_url = reverse("signup")

        static_prefix = (settings.STATIC_URL or "/static/").rstrip("/")
        media_prefix = (settings.MEDIA_URL or "/media/").rstrip("/")

        allowed = {
            "/",
            "/core/",
            login_url,
            signup_url,
            "/favicon.ico",
        }
        allowed_prefixes = (
            static_prefix,
            media_prefix,
            "/admin/",
        )

        if path in allowed or any(path.startswith(p) for p in allowed_prefixes):
            return self.get_response(request)

        next_url = request.get_full_path()
        return redirect(f"{login_url}?next={next_url}")

