from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from core.models import Booking, SystemConfig
from core.utils import send_booking_reminder

class Command(BaseCommand):
    help = 'Send appointment reminders for upcoming bookings'
    
    def handle(self, *args, **options):
        config = SystemConfig.get_config()
        
        # Calculate reminder time
        reminder_time = timezone.now() + timedelta(hours=config.reminder_lead_time_hours)
        
        # Get bookings that need reminders
        bookings = Booking.objects.filter(
            status='confirmed',
            appointment_date=reminder_time.date(),
            appointment_time__hour=reminder_time.hour
        )
        
        count = 0
        for booking in bookings:
            try:
                send_booking_reminder(booking)
                count += 1
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'Failed to send reminder for booking {booking.id}: {str(e)}')
                )
        
        self.stdout.write(
            self.style.SUCCESS(f'Successfully sent {count} reminder emails')
        )
