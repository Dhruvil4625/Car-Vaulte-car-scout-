from django.shortcuts import redirect
from django.http import HttpResponse
from django.contrib import messages
from functools import wraps

def role_required(allowed_roles=[], login_url="login"):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper_func(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(login_url)
            
            # Admins (staff/superuser) are always authorized
            if request.user.is_staff or request.user.is_superuser:
                return view_func(request, *args, **kwargs)
            
            # Check for specific allowed roles
            if request.user.role in allowed_roles:
                return view_func(request, *args, **kwargs)
            
            # Special case for "ADMIN" in allowed_roles (already covered by is_staff check above, 
            # but kept for semantic clarity if needed elsewhere)
            if "ADMIN" in allowed_roles:
                 return view_func(request, *args, **kwargs) # Already returned if staff
            
            return HttpResponse("You are not authorized to view this page.", status=403)
        return wrapper_func
    return decorator
