"""
Management command to backup MySQL data before migration
Save as: core/management/commands/backup_mysql_data.py
"""
from django.core.management.base import BaseCommand
from django.core import serializers
from django.apps import apps
import json
from datetime import datetime

class Command(BaseCommand):
    help = 'Backup all data from MySQL database to JSON file'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output',
            type=str,
            default=f'backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json',
            help='Output file name'
        )

    def handle(self, *args, **options):
        output_file = options['output']
        
        self.stdout.write(self.style.SUCCESS(f'Starting backup to {output_file}...'))
        
        # Get all models from your app
        app_config = apps.get_app_config('core')
        models = app_config.get_models()
        
        all_data = []
        
        # Order models to handle dependencies
        # First backup models without foreign keys, then ones with dependencies
        ordered_models = [
            'User',
            'SystemConfig',
            'Client',
            'AvailabilityCycle',
            'AvailableTimeSlot',
            'MessageTemplate',
            'PayrollPeriod',
            'Booking',
            'PayrollAdjustment',
            'DripCampaign',
            'ScheduledMessage',
            'CommunicationLog',
            'AuditLog',
        ]
        
        for model_name in ordered_models:
            try:
                model = apps.get_model('core', model_name)
                objects = model.objects.all()
                count = objects.count()
                
                self.stdout.write(f'Backing up {model_name}: {count} records')
                
                # Serialize objects
                serialized = serializers.serialize('json', objects)
                all_data.extend(json.loads(serialized))
                
            except LookupError:
                self.stdout.write(self.style.WARNING(f'Model {model_name} not found, skipping...'))
                continue
        
        # Write to file
        with open(output_file, 'w') as f:
            json.dump(all_data, f, indent=2, default=str)
        
        self.stdout.write(self.style.SUCCESS(f'✓ Backup complete! {len(all_data)} total records saved to {output_file}'))
        self.stdout.write(self.style.WARNING('\nIMPORTANT: Keep this file safe! You\'ll need it for restoration.'))
