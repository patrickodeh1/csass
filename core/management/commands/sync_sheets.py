from django.core.management.base import BaseCommand
from core.sheets_sync import GoogleSheetsSyncService
from core.models import Booking
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Manually sync bookings with Google Sheets'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--initialize',
            action='store_true',
            help='Initialize sheet with headers',
        )
        parser.add_argument(
            '--from-db',
            action='store_true',
            help='Sync all unsynced bookings from DB to sheet',
        )
        parser.add_argument(
            '--from-sheet',
            action='store_true',
            help='Sync changes from sheet to DB',
        )
        parser.add_argument(
            '--booking-id',
            type=int,
            help='Sync a specific booking by ID',
        )
    
    def handle(self, *args, **options):
        try:
            sync_service = GoogleSheetsSyncService()
            
            if options['initialize']:
                self.stdout.write('Initializing sheet...')
                if sync_service.initialize_sheet():
                    self.stdout.write(self.style.SUCCESS('✓ Sheet initialized'))
                else:
                    self.stdout.write(self.style.ERROR('✗ Sheet initialization failed'))
            
            if options['booking_id']:
                self.stdout.write(f'Syncing booking {options["booking_id"]} to sheet...')
                try:
                    booking = Booking.objects.get(id=options['booking_id'])
                    if booking.appointment_type != 'live_transfer':
                        self.stdout.write(self.style.WARNING(f'⚠ Booking {booking.id} is not a live transfer'))
                    else:
                        if sync_service.sync_new_booking_to_sheet(booking):
                            self.stdout.write(self.style.SUCCESS(f'✓ Synced booking {booking.id} to sheet'))
                        else:
                            self.stdout.write(self.style.WARNING(f'⚠ Booking {booking.id} may already be synced'))
                except Booking.DoesNotExist:
                    self.stdout.write(self.style.ERROR(f'✗ Booking {options["booking_id"]} not found'))
            
            if options['from_db']:
                self.stdout.write('Syncing unsynced live transfers from DB to sheet...')
                
                # Get all live transfer bookings without sheet row number
                bookings = Booking.objects.filter(
                    appointment_type='live_transfer',
                    sheet_row_number__isnull=True
                ).order_by('-created_at')
                
                total = bookings.count()
                self.stdout.write(f'Found {total} unsynced live transfer bookings')
                
                count = 0
                for booking in bookings:
                    self.stdout.write(f'  Processing booking {booking.id}...', ending='')
                    if sync_service.sync_new_booking_to_sheet(booking):
                        count += 1
                        self.stdout.write(self.style.SUCCESS(' ✓'))
                    else:
                        self.stdout.write(self.style.WARNING(' ⚠'))
                
                self.stdout.write(self.style.SUCCESS(f'✓ Synced {count}/{total} bookings to sheet'))
            
            if options['from_sheet']:
                self.stdout.write('Syncing from sheet to DB...')
                count = sync_service.sync_sheet_changes_to_db()
                self.stdout.write(self.style.SUCCESS(f'✓ Updated {count} bookings from sheet'))
            
            if not any([options['initialize'], options['from_db'], options['from_sheet'], options['booking_id']]):
                self.stdout.write(self.style.WARNING('No action specified. Use --help for options.'))
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Error: {str(e)}'))
            logger.exception('Sheet sync command failed')