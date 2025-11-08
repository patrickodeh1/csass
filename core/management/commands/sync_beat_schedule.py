# core/management/commands/sync_beat_schedule.py

from django.core.management.base import BaseCommand
from django.conf import settings
from django_celery_beat.models import PeriodicTask, IntervalSchedule, CrontabSchedule
from celery.schedules import crontab as celery_crontab
import json

class Command(BaseCommand):
    help = 'Sync CELERY_BEAT_SCHEDULE from settings.py to database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--delete-unmanaged',
            action='store_true',
            help='Delete tasks in DB that are not in settings',
        )

    def handle(self, *args, **options):
        beat_schedule = getattr(settings, 'CELERY_BEAT_SCHEDULE', {})
        
        if not beat_schedule:
            self.stdout.write(self.style.WARNING('No CELERY_BEAT_SCHEDULE found in settings'))
            return
        
        self.stdout.write(f'Found {len(beat_schedule)} tasks in settings')
        synced_tasks = []
        
        for task_name, task_config in beat_schedule.items():
            schedule_value = task_config['schedule']
            task_path = task_config['task']
            task_options = task_config.get('options', {})
            
            try:
                # Handle interval schedules (seconds as int/float)
                if isinstance(schedule_value, (int, float)):
                    schedule, created = IntervalSchedule.objects.get_or_create(
                        every=int(schedule_value),
                        period=IntervalSchedule.SECONDS,
                    )
                    
                    # Prepare defaults dict
                    defaults = {
                        'interval': schedule,
                        'crontab': None,  # Clear crontab if switching from cron
                        'task': task_path,
                        'enabled': True,
                        'description': f'Auto-synced from settings.py',
                    }
                    
                    # Only add expires if it exists (skip it entirely otherwise)
                    # django-celery-beat doesn't use expires field, it's handled by Celery
                    
                    task, created = PeriodicTask.objects.update_or_create(
                        name=task_name,
                        defaults=defaults
                    )
                    synced_tasks.append(task_name)
                    action = 'Created' if created else 'Updated'
                    self.stdout.write(
                        self.style.SUCCESS(f'  ✓ {action}: {task_name} (every {schedule_value}s)')
                    )
                
                # Handle crontab schedules
                elif isinstance(schedule_value, celery_crontab):
                    schedule, created = CrontabSchedule.objects.get_or_create(
                        minute=schedule_value._orig_minute or '*',
                        hour=schedule_value._orig_hour or '*',
                        day_of_week=schedule_value._orig_day_of_week or '*',
                        day_of_month=schedule_value._orig_day_of_month or '*',
                        month_of_year=schedule_value._orig_month_of_year or '*',
                        timezone=settings.TIME_ZONE,
                    )
                    
                    # Prepare defaults dict
                    defaults = {
                        'crontab': schedule,
                        'interval': None,  # Clear interval if switching from interval
                        'task': task_path,
                        'enabled': True,
                        'description': f'Auto-synced from settings.py',
                    }
                    
                    task, created = PeriodicTask.objects.update_or_create(
                        name=task_name,
                        defaults=defaults
                    )
                    synced_tasks.append(task_name)
                    action = 'Created' if created else 'Updated'
                    cron_str = f"{schedule.minute} {schedule.hour} {schedule.day_of_month} {schedule.month_of_year} {schedule.day_of_week}"
                    self.stdout.write(
                        self.style.SUCCESS(f'  ✓ {action}: {task_name} (cron: {cron_str})')
                    )
                
                else:
                    self.stdout.write(
                        self.style.WARNING(f'  ⚠ Unsupported schedule type for {task_name}: {type(schedule_value)}')
                    )
            
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'  ✗ Error syncing {task_name}: {str(e)}')
                )
        
        # Optionally delete tasks not in settings
        if options['delete_unmanaged']:
            all_db_tasks = PeriodicTask.objects.filter(
                description='Auto-synced from settings.py'
            )
            for db_task in all_db_tasks:
                if db_task.name not in synced_tasks:
                    db_task.delete()
                    self.stdout.write(
                        self.style.WARNING(f'  🗑 Deleted: {db_task.name} (not in settings)')
                    )
        
        self.stdout.write(
            self.style.SUCCESS(f'\n✓ Successfully synced {len(synced_tasks)} tasks to database')
        )
        self.stdout.write(
            self.style.SUCCESS('You can now view and manage them in Django Admin under "Periodic Tasks"')
        )