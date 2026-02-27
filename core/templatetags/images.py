from django import template
from core.models import CarListing

register = template.Library()

SYN = {
    "suzuki": "Suzuki,Maruti,Suzuki Swift,Swift,hatchback",
    "maruti": "Maruti,Maruti Suzuki,Swift,Baleno,hatchback",
    "toyota": "Toyota,Toyota India,SUV,Sedan",
    "tata": "Tata,Tata Motors,EV,SUV",
    "hyundai": "Hyundai,Hyundai India,SUV,Hatchback",
    "kia": "Kia,Kia India,SUV",
}

@register.simple_tag
def car_image(make=None, model=None, size="600x400"):
    m = (make or "").lower().strip()
    mdl = (model or "").lower().strip()
    base = f"/static/img/placeholder.svg"
    if m and mdl:
        return f"https://source.unsplash.com/{size}/?{make},{model},car"
    if m:
        syn = SYN.get(m, m)
        return f"https://source.unsplash.com/{size}/?{syn},car"
    return base

@register.simple_tag
def car_gallery(make=None, model=None, size="600x400", count=4):
    m = (make or "").strip()
    mdl = (model or "").strip()
    urls = []
    if m and mdl:
        base = f"https://source.unsplash.com/{size}/?{m},{mdl},car"
    elif m:
        base = f"https://source.unsplash.com/{size}/?{m},car"
    else:
        base = f"https://source.unsplash.com/{size}/?car"
    for i in range(int(count)):
        urls.append(f"{base}&sig={i}")
    return urls

@register.simple_tag
def listing_main_image(listing, size="600x400"):
    try:
        imgs = getattr(listing, "images").all()
        if imgs:
            return imgs[0].image.url
    except Exception:
        pass
    return car_image(getattr(listing.car, "make", None), getattr(listing.car, "model", None), size)

@register.simple_tag
def car_main_image(car, size="600x400"):
    try:
        lst = car.listings.order_by("-created_at").first()
        if lst:
            imgs = lst.images.all()
            if imgs:
                return imgs[0].image.url
    except Exception:
        pass
    return car_image(getattr(car, "make", None), getattr(car, "model", None), size)
