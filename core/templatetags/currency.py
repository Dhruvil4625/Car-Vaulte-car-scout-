from django import template

register = template.Library()

@register.filter
def inr(amount):
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        return "₹ —"
    if amt >= 10000000:
        return f"₹ {amt/10000000:.2f} Cr"
    if amt >= 100000:
        return f"₹ {amt/100000:.2f} Lakh"
    return f"₹ {amt:,.0f}"
