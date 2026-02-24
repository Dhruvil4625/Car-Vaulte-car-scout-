from django import template

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
