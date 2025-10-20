from django import template
from datetime import timedelta
from core.models import User, SystemConfig
register = template.Library()

@register.filter
def add_days(date, days):
    """Add days to a date"""
    try:
        return date + timedelta(days=int(days))
    except (ValueError, TypeError):
        return date


@register.filter(name='has_group')
def has_group(user, group_name):
    """Check if user belongs to a group"""
    return user.groups.filter(name=group_name).exists()



@register.filter
def get_salesman_name(salesman_id):
    """Return full name of salesman by ID"""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    try:
        user = User.objects.get(id=salesman_id)
        return user.get_full_name() or user.username
    except User.DoesNotExist:
        return "Unknown"
