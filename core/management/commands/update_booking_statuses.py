
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from core.models import Booking

class Command(BaseCommand):
    help = 'Update booking statuses to completed for past appointments'
    
    def handle(self, *args, **options):
        # Get bookings that are 24+ hours past appointment time
        cutoff = timezone.now() - timedelta(hours=24)
        
        bookings_to_update = Booking.objects.filter(
            status='confirmed',
            appointment_date__lt=cutoff.date()
        )
        
        count = bookings_to_update.count()
        bookings_to_update.update(status='completed')
        
        self.stdout.write(
            self.style.SUCCESS(f'Successfully updated {count} bookings to completed status')
        )
