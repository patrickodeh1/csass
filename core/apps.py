from django.apps import AppConfig
from django.db.models.signals import post_migrate
import sys


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    
    def ready(self):
        # Import signals
        import core.signals
        
        # Only run setup tasks if not in migration or test mode
        if not any(cmd in sys.argv for cmd in ['migrate', 'makemigrations', 'test']):
            # Defer SystemConfig creation until after migrations
            post_migrate.connect(
                self.ensure_system_config, 
                dispatch_uid='core_ensure_system_config'
            )
            
            # Sync beat schedule after migrations
            post_migrate.connect(
                self.sync_beat_schedule, 
                dispatch_uid='core_sync_beat_schedule'
            )
    
    def ensure_system_config(self, sender, **kwargs):
        """Ensure SystemConfig singleton exists after migrations"""
        try:
            from .models import SystemConfig
            SystemConfig.get_config()
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Could not ensure SystemConfig: {e}")
    
    def sync_beat_schedule(self, sender, **kwargs):
        """Sync CELERY_BEAT_SCHEDULE to database after migrations"""
        try:
            from django.core.management import call_command
            call_command('sync_beat_schedule', verbosity=0)
            
            import logging
            logger = logging.getLogger(__name__)
            logger.info("Celery Beat schedule synced to database")
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Could not sync beat schedule: {e}")