"""
Management command to restore data from JSON backup to PostgreSQL
Save as: core/management/commands/restore_postgres_data.py
"""
from django.core.management.base import BaseCommand
from django.core import serializers
from django.db import transaction
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import Group, Permission
import json

class Command(BaseCommand):
    help = 'Restore data from JSON backup to PostgreSQL'

    def add_arguments(self, parser):
        parser.add_argument(
            '--input',
            type=str,
            required=True,
            help='Input JSON file from backup'
        )
        parser.add_argument(
            '--skip-users',
            action='store_true',
            help='Skip restoring User model (if you want to keep existing users)'
        )

    def handle(self, *args, **options):
        input_file = options['input']
        skip_users = options['skip_users']
        
        self.stdout.write(self.style.SUCCESS(f'Starting restore from {input_file}...'))
        
        try:
            with open(input_file, 'r') as f:
                data = json.load(f)
            
            self.stdout.write(f'Loaded {len(data)} records from backup file')
            
            # Group data by model to restore in correct order
            models_data = {}
            for obj in data:
                model = obj['model']
                if model not in models_data:
                    models_data[model] = []
                models_data[model].append(obj)
            
            # Order of restoration (respects foreign key dependencies)
            restore_order = [
                'auth.group',
                'auth.permission',
                'contenttypes.contenttype',
                'core.user',
                'core.systemconfig',
                'core.client',
                'core.availabilitycycle',
                'core.availabletimeslot',
                'core.messagetemplate',
                'core.payrollperiod',
                'core.booking',
                'core.payrolladjustment',
                'core.dripcampaign',
                'core.scheduledmessage',
                'core.communicationlog',
                'core.auditlog',
            ]
            
            total_restored = 0
            
            with transaction.atomic():
                for model_name in restore_order:
                    if model_name not in models_data:
                        continue
                    
                    # Skip users if requested
                    if skip_users and model_name == 'core.user':
                        self.stdout.write(self.style.WARNING(f'Skipping {model_name} (--skip-users flag)'))
                        continue
                    
                    objects = models_data[model_name]
                    self.stdout.write(f'Restoring {model_name}: {len(objects)} records...')
                    
                    try:
                        # Deserialize and save
                        for obj_data in serializers.deserialize('json', json.dumps(objects)):
                            obj_data.save()
                            total_restored += 1
                        
                        self.stdout.write(self.style.SUCCESS(f'  ✓ Restored {len(objects)} {model_name} records'))
                        
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f'  ✗ Error restoring {model_name}: {str(e)}'))
                        raise
                
                # Fix PostgreSQL sequences (important!)
                self.stdout.write('\nFixing PostgreSQL sequences...')
                from django.core.management import call_command
                call_command('sqlsequencereset', 'core')
                
            self.stdout.write(self.style.SUCCESS(f'\n✓ Restore complete! {total_restored} total records restored'))
            self.stdout.write(self.style.WARNING('\nIMPORTANT: Run the following commands to fix sequences:'))
            self.stdout.write('python manage.py fix_sequences')
            
        except FileNotFoundError:
            self.stdout.write(self.style.ERROR(f'Error: File {input_file} not found'))
        except json.JSONDecodeError:
            self.stdout.write(self.style.ERROR(f'Error: Invalid JSON in {input_file}'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error during restore: {str(e)}'))
            raise
