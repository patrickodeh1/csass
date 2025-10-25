# core/management/commands/restore_historical_data.py

from django.core.management.base import BaseCommand
from django.db import transaction
from django.apps import apps
from django.utils import timezone
import json
import logging
from datetime import datetime, date

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Restore only historical (past) timeslots and bookings from backup'

    def add_arguments(self, parser):
        parser.add_argument(
            '--input',
            type=str,
            default='mysql_backup.json',
            help='Input JSON file with backup data'
        )
        parser.add_argument(
            '--date-threshold',
            type=str,
            default=None,
            help='Only restore data before this date (YYYY-MM-DD). Defaults to today.'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be restored without actually doing it'
        )

    def handle(self, *args, **options):
        input_file = options['input']
        dry_run = options['dry_run']
        
        # Set date threshold (default to today)
        if options['date_threshold']:
            threshold_date = datetime.strptime(options['date_threshold'], '%Y-%m-%d').date()
        else:
            threshold_date = timezone.now().date()
        
        self.stdout.write(f"Restoring historical data from {input_file}...")
        self.stdout.write(f"Date threshold: {threshold_date} (only data BEFORE this date)")
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be made"))
        
        try:
            with open(input_file, 'r') as f:
                data = json.load(f)
            
            # Filter only timeslots and bookings
            timeslots = [item for item in data if item['model'] == 'core.availabletimeslot']
            bookings = [item for item in data if item['model'] == 'core.booking']
            
            self.stdout.write(f"Found {len(timeslots)} timeslots and {len(bookings)} bookings in backup")
            
            # Filter historical data only
            historical_timeslots = []
            for ts in timeslots:
                ts_date = datetime.strptime(ts['fields']['date'], '%Y-%m-%d').date()
                if ts_date < threshold_date:
                    historical_timeslots.append(ts)
            
            self.stdout.write(f"Filtered to {len(historical_timeslots)} historical timeslots (before {threshold_date})")
            
            # Restore timeslots first
            restored_slots = 0
            skipped_slots = 0
            error_slots = 0
            
            self.stdout.write("\nRestoring historical timeslots...")
            for ts_data in historical_timeslots:
                try:
                    if dry_run:
                        self.stdout.write(f"  [DRY RUN] Would restore slot: {ts_data['fields']['date']} - {ts_data['fields']['start_time']}")
                        restored_slots += 1
                    else:
                        restored, skipped = self.restore_timeslot(ts_data)
                        if restored:
                            restored_slots += 1
                        elif skipped:
                            skipped_slots += 1
                except Exception as e:
                    error_slots += 1
                    logger.error(f"Error restoring timeslot {ts_data.get('pk')}: {e}")
            
            self.stdout.write(self.style.SUCCESS(f"  ✓ Restored {restored_slots} timeslots"))
            if skipped_slots > 0:
                self.stdout.write(self.style.WARNING(f"  ⊘ Skipped {skipped_slots} timeslots (already exist)"))
            if error_slots > 0:
                self.stdout.write(self.style.ERROR(f"  ✗ {error_slots} timeslots failed"))
            
            # Now restore bookings for those timeslots
            self.stdout.write("\nRestoring historical bookings...")
            restored_bookings = 0
            skipped_bookings = 0
            error_bookings = 0
            
            # Get all restored timeslot IDs
            restored_timeslot_ids = set(ts['pk'] for ts in historical_timeslots)
            
            for booking_data in bookings:
                try:
                    timeslot_id = booking_data['fields'].get('timeslot')
                    # Only restore bookings that reference historical timeslots
                    if timeslot_id in restored_timeslot_ids:
                        if dry_run:
                            self.stdout.write(f"  [DRY RUN] Would restore booking: {booking_data['pk']}")
                            restored_bookings += 1
                        else:
                            restored, skipped = self.restore_booking(booking_data)
                            if restored:
                                restored_bookings += 1
                            elif skipped:
                                skipped_bookings += 1
                except Exception as e:
                    error_bookings += 1
                    logger.error(f"Error restoring booking {booking_data.get('pk')}: {e}")
            
            self.stdout.write(self.style.SUCCESS(f"  ✓ Restored {restored_bookings} bookings"))
            if skipped_bookings > 0:
                self.stdout.write(self.style.WARNING(f"  ⊘ Skipped {skipped_bookings} bookings (already exist)"))
            if error_bookings > 0:
                self.stdout.write(self.style.ERROR(f"  ✗ {error_bookings} bookings failed"))
            
            # Summary
            self.stdout.write(self.style.SUCCESS('\n' + '='*50))
            self.stdout.write(self.style.SUCCESS(f"Historical data restore complete!"))
            self.stdout.write(f"  Timeslots restored: {restored_slots}")
            self.stdout.write(f"  Bookings restored: {restored_bookings}")
            
        except FileNotFoundError:
            self.stdout.write(
                self.style.ERROR(f"Error: File '{input_file}' not found")
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Error during restore: {e}")
            )
            import traceback
            traceback.print_exc()

    def restore_timeslot(self, item_data):
        """Restore a single timeslot"""
        from core.models import AvailableTimeSlot, User, AvailabilityCycle
        
        fields = item_data['fields'].copy()
        pk = item_data['pk']
        
        # Check if already exists
        existing = AvailableTimeSlot.objects.filter(pk=pk).first()
        if existing:
            return False, True  # Already exists, skip
        
        # Also check by unique constraint
        existing_by_constraint = AvailableTimeSlot.objects.filter(
            salesman_id=fields.get('salesman'),
            date=fields.get('date'),
            start_time=fields.get('start_time'),
            appointment_type=fields.get('appointment_type')
        ).first()
        
        if existing_by_constraint:
            return False, True  # Already exists, skip
        
        # Handle all ForeignKey fields
        fk_data = {}
        
        # Get salesman
        salesman_id = fields.pop('salesman', None)
        if salesman_id:
            salesman = User.objects.filter(pk=salesman_id).first()
            if not salesman:
                logger.warning(f"Skipping timeslot {pk}: salesman {salesman_id} not found")
                return False, True
            fk_data['salesman'] = salesman
        
        # Get cycle (or use current cycle if old one doesn't exist)
        cycle_id = fields.pop('cycle', None)
        cycle = None
        if cycle_id:
            cycle = AvailabilityCycle.objects.filter(pk=cycle_id).first()
        
        # If the old cycle doesn't exist, try to find or create an appropriate cycle
        if not cycle:
            slot_date = datetime.strptime(fields['date'], '%Y-%m-%d').date()
            # Try to find a cycle that contains this date
            cycle = AvailabilityCycle.objects.filter(
                start_date__lte=slot_date,
                end_date__gte=slot_date
            ).first()
            
            # If still no cycle, create a historical cycle for this date range
            if not cycle:
                # Create a 2-week cycle starting from the slot date
                from datetime import timedelta
                cycle_start = slot_date
                cycle_end = slot_date + timedelta(days=13)
                
                cycle = AvailabilityCycle.objects.create(
                    start_date=cycle_start,
                    end_date=cycle_end,
                    is_active=False  # Mark as historical
                )
                logger.info(f"Created historical cycle {cycle.pk} for date range {cycle_start} to {cycle_end}")
        
        fk_data['cycle'] = cycle
        
        # Handle created_by and updated_by fields
        created_by_id = fields.pop('created_by', None)
        if created_by_id:
            created_by = User.objects.filter(pk=created_by_id).first()
            if created_by:
                fk_data['created_by'] = created_by
        
        updated_by_id = fields.pop('updated_by', None)
        if updated_by_id:
            updated_by = User.objects.filter(pk=updated_by_id).first()
            if updated_by:
                fk_data['updated_by'] = updated_by
        
        # Create the timeslot with all fields
        obj = AvailableTimeSlot(pk=pk, **fk_data, **fields)
        obj.save()
        
        return True, False

    def restore_booking(self, item_data):
        """Restore a single booking"""
        from core.models import Booking, AvailableTimeSlot, Client, User
        
        fields = item_data['fields'].copy()
        pk = item_data['pk']
        
        # Check if already exists
        existing = Booking.objects.filter(pk=pk).first()
        if existing:
            return False, True  # Already exists, skip
        
        # Handle all ForeignKey fields
        fk_data = {}
        
        # Get timeslot
        timeslot_id = fields.pop('timeslot', None)
        if timeslot_id:
            timeslot = AvailableTimeSlot.objects.filter(pk=timeslot_id).first()
            if not timeslot:
                logger.warning(f"Skipping booking {pk}: timeslot {timeslot_id} not found")
                return False, True
            fk_data['timeslot'] = timeslot
        
        # Get client (can be null)
        client_id = fields.pop('client', None)
        if client_id:
            client = Client.objects.filter(pk=client_id).first()
            if client:
                fk_data['client'] = client
        
        # Handle created_by and updated_by fields
        created_by_id = fields.pop('created_by', None)
        if created_by_id:
            created_by = User.objects.filter(pk=created_by_id).first()
            if created_by:
                fk_data['created_by'] = created_by
        
        updated_by_id = fields.pop('updated_by', None)
        if updated_by_id:
            updated_by = User.objects.filter(pk=updated_by_id).first()
            if updated_by:
                fk_data['updated_by'] = updated_by
        
        # Create the booking
        obj = Booking(pk=pk, **fk_data, **fields)
        obj.save()
        
        return True, False