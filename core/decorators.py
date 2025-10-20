from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import PermissionDenied
from functools import wraps

def group_required(*group_names):
    """Decorator to require user to be in specific groups"""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)
            
            if not request.user.groups.filter(name__in=group_names).exists():
                raise PermissionDenied
            
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator

def admin_required(view_func):
    """Decorator to require admin/staff access"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not (request.user.is_staff or request.user.is_superuser):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return wrapper

def remote_agent_required(view_func):
    """Decorator to require remote_agent role"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.groups.filter(name='remote_agent').exists():
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return wrapper