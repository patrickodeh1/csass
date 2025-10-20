from django.apps import AppConfig
from django.db.models.signals import post_migrate


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    
    def ready(self):
        import core.signals
        
        # Defer SystemConfig creation until after migrations are applied
        def ensure_system_config(sender, **kwargs):
            try:
                from .models import SystemConfig
                SystemConfig.get_config()
            except Exception:
                # Ignore errors if database isn't ready
                pass
        
        # Connect without sender filter so it runs regardless of which app just migrated
        post_migrate.connect(ensure_system_config, dispatch_uid='core_ensure_system_config')