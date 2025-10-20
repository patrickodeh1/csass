from django import template

register = template.Library()

@register.filter
def mul(value, arg):
    return value * arg

@register.filter
def div(value, arg):
    if arg == 0:
        return 0
    return (value / arg) * 100  # Returns percentage as float; adjust as needed