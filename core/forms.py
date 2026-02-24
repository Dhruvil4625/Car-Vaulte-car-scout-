from django.contrib.auth.forms import UserCreationForm
from .models import User, CarListing, Car
from django import forms

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

class CarListingForm(forms.ModelForm):
    class Meta:
        model = CarListing
        fields = ('price', 'mileage', 'description', 'status')
        widgets = {
            'price': forms.NumberInput(attrs={'class': 'form-control'}),
            'mileage': forms.NumberInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'status': forms.Select(attrs={'class': 'form-select'}),
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
