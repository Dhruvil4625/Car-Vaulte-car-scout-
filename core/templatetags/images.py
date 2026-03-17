from django import template
from core.models import CarListing
import math

register = template.Library()

SYN = {
    "suzuki": "Suzuki,Maruti,Suzuki Swift,Swift,hatchback",
    "maruti": "Maruti,Maruti Suzuki,Swift,Baleno,hatchback",
    "toyota": "Toyota,Toyota India,SUV,Sedan",
    "tata": "Tata,Tata Motors,EV,SUV",
    "hyundai": "Hyundai,Hyundai India,SUV,Hatchback",
    "kia": "Kia,Kia India,SUV",
    "mercedes": "Mercedes-Benz,Mercedes AMG,Mercedes",
    "mercedies": "Mercedes-Benz,Mercedes AMG,Mercedes",
    "mecedies": "Mercedes-Benz,Mercedes AMG,Mercedes",
    "benz": "Mercedes-Benz,Mercedes AMG,Mercedes",
    "vw": "Volkswagen,VW",
    "volkswagon": "Volkswagen,VW",
}

@register.simple_tag
def car_image(make=None, model=None, size="600x400"):
    m = (make or "").lower().strip()
    mdl = (model or "").lower().strip()
    base = f"/static/img/placeholder.svg"
    seed = str((sum(ord(c) for c in (mdl or m)) % 997) if (mdl or m) else 0)
    if m and mdl:
        return f"https://source.unsplash.com/{size}/?{make},{model},car&sig={seed}"
    if m:
        syn = SYN.get(m, m)
        return f"https://source.unsplash.com/{size}/?{syn},car&sig={seed}"
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
        imgs = list(getattr(listing, "images").all())
        if imgs:
            # Prefer exterior 16x9 or main, then any exterior, then first non-synthetic, else first
            def good(im):
                alt = (getattr(im, "alt", "") or "").lower()
                name = str(getattr(getattr(im, "image", None), "name", "")).lower()
                url = getattr(getattr(im, "image", None), "url", None)
                return alt, name, url
            # Exterior 16x9 or main
            for im in imgs:
                alt, name, url = good(im)
                if url and ("exter" in alt) and ("16x9" in alt or "main" in alt):
                    return url
            # Any exterior
            for im in imgs:
                alt, name, url = good(im)
                if url and ("exter" in alt):
                    return url
            # First non-synthetic
            for im in imgs:
                alt, name, url = good(im)
                if url and "listing_images/generated/" not in name:
                    return url
            # Fallback to very first url, even if synthetic
            u0 = getattr(imgs[0].image, "url", None)
            if u0:
                return u0
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
                im = imgs[0]
                name = str(getattr(im.image, "name", "")).lower()
                url = getattr(im.image, "url", None)
                if "listing_images/generated/" in name:
                    return car_image(getattr(car, "make", None), getattr(car, "model", None), size)
                if url:
                    return url
    except Exception:
        pass
    return car_image(getattr(car, "make", None), getattr(car, "model", None), size)

@register.simple_tag
def listing_thumbs(listing, count=4, size="300x200"):
    try:
        imgs = list(getattr(listing, "images").all())
    except Exception:
        imgs = []
    urls = []
    def add_if(im):
        alt = (getattr(im, "alt", "") or "").lower()
        name = str(getattr(getattr(im, "image", None), "name", "")).lower()
        url = getattr(getattr(im, "image", None), "url", None)
        if not url:
            return
        # Skip spin frames and 360/panos and synthetic placeholders
        if any(t in alt for t in ["spin", "360", "pano", "equirect"]):
            return
        if "listing_images/generated/" in name:
            return
        urls.append(url)
    def add_any(im):
        url = getattr(getattr(im, "image", None), "url", None)
        if url:
            urls.append(url)
    # Prefer exterior, then interior, then the rest
    for im in imgs:
        if len(urls) >= count: break
        if "exter" in ((im.alt or "").lower()):
            add_if(im)
    for im in imgs:
        if len(urls) >= count: break
        if "inter" in ((im.alt or "").lower()):
            add_if(im)
    for im in imgs:
        if len(urls) >= count: break
        add_if(im)
    # If still short, allow synthetic or any remaining images
    for im in imgs:
        if len(urls) >= count: break
        add_any(im)
    # If still short, fill with model-based fallbacks for variety
    while len(urls) < int(count):
        urls.append(car_image(getattr(listing.car, "make", None), getattr(listing.car, "model", None), size))
    return urls
