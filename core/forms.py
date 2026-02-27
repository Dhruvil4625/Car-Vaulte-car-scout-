from django.contrib.auth.forms import UserCreationForm
from django import forms
from django.core.exceptions import ValidationError
from .models import User, CarListing, Car, Showroom, UpcomingArrival, Inspection

class UserSignupForm(UserCreationForm):
    class Meta:
        model = User
        fields = ('email', 'name', 'phone', 'role', 'password1', 'password2')
        widgets = {
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'role': forms.Select(attrs={'class': 'form-control'}),
            'password1': forms.PasswordInput(attrs={'class': 'form-control'}),
            'password2': forms.PasswordInput(attrs={'class': 'form-control'}),
        }

class UserLoginForm(forms.Form):
    email = forms.EmailField(widget=forms.EmailInput(attrs={'class': 'form-control'}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control'}))

    def clean(self):
        cleaned = super().clean()
        email = cleaned.get('email')
        password = cleaned.get('password')
        if not email or not password:
            raise ValidationError('Please enter email and password.')
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise ValidationError('No account found for this email. Please register first.')
        if not user.is_active:
            raise ValidationError('This account is inactive.')
        if not user.check_password(password):
            raise ValidationError('Invalid password.')
        self.user = user
        return cleaned

class CarListingForm(forms.ModelForm):
    class Meta:
        model = CarListing
        fields = ('price', 'mileage', 'description', 'status', 'showroom')
        widgets = {
            'price': forms.NumberInput(attrs={'class': 'form-control'}),
            'mileage': forms.NumberInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'showroom': forms.Select(attrs={'class': 'form-select'}),
        }

class MultiFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True

class CarListingImageUploadForm(forms.Form):
    images = forms.ImageField(widget=MultiFileInput(attrs={'multiple': True, 'class': 'form-control', 'accept': 'image/*'}), required=False)

class CarForm(forms.ModelForm):
    class Meta:
        model = Car
        fields = ('make', 'model', 'year', 'color', 'fuel_type', 'transmission', 'mileage', 'body_type')
        widgets = {
            'make': forms.TextInput(attrs={'class': 'form-control'}),
            'model': forms.TextInput(attrs={'class': 'form-control'}),
            'year': forms.NumberInput(attrs={'class': 'form-control'}),
            'color': forms.TextInput(attrs={'class': 'form-control'}),
            'fuel_type': forms.TextInput(attrs={'class': 'form-control'}),
            'transmission': forms.TextInput(attrs={'class': 'form-control'}),
            'mileage': forms.NumberInput(attrs={'class': 'form-control'}),
            'body_type': forms.TextInput(attrs={'class': 'form-control'}),
        }

class UpcomingArrivalForm(forms.ModelForm):
    class Meta:
        model = UpcomingArrival
        fields = ('showroom', 'make', 'model', 'year', 'expected_date', 'status', 'notes')
        widgets = {
            'showroom': forms.Select(attrs={'class': 'form-select'}),
            'make': forms.TextInput(attrs={'class': 'form-control'}),
            'model': forms.TextInput(attrs={'class': 'form-control'}),
            'year': forms.NumberInput(attrs={'class': 'form-control'}),
            'expected_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

class InspectionForm(forms.ModelForm):
    class Meta:
        model = Inspection
        fields = ('listing', 'inspection_date', 'condition_score', 'accident_history', 'report_details', 'source')
        widgets = {
            'listing': forms.Select(attrs={'class': 'form-select'}),
            'inspection_date': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'condition_score': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1', 'min': '0', 'max': '10', 'placeholder': '0.0 – 10.0'}),
            'accident_history': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Accident summary...'}),
            'report_details': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Detailed report or JSON...'}),
            'source': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        qs = CarListing.objects.select_related("car", "seller").order_by("-created_at")
        if user and not getattr(user, "is_staff", False) and getattr(user, "role", "") == "Seller":
            qs = qs.filter(seller=user)
        self.fields['listing'].queryset = qs
