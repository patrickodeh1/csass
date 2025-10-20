from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import ScheduledMessage
from core.utils import process_scheduled_messages
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Process all pending scheduled messages that are due'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting scheduled message processing...'))
        
        now = timezone.now()
        pending_messages = ScheduledMessage.objects.filter(
            status='pending',
            scheduled_for__lte=now
        ).select_related('drip_campaign', 'message_template')
        
        total = pending_messages.count()
        self.stdout.write(f'Found {total} messages to process')
        
        sent_count = 0
        failed_count = 0
        canceled_count = 0
        
        for message in pending_messages:
            # Check if campaign is still active
            if not message.drip_campaign.is_active or message.drip_campaign.is_stopped:
                message.status = 'canceled'
                message.save()
                canceled_count += 1
                continue
            
            # Send the message
            try:
                success = message.send_message()
                if success:
                    sent_count += 1
                    self.stdout.write(self.style.SUCCESS(
                        f'✓ Sent: {message.message_template.message_type} to {message.recipient_email}'
                    ))
                else:
                    failed_count += 1
                    self.stdout.write(self.style.ERROR(
                        f'✗ Failed: {message.message_template.message_type} to {message.recipient_email}'
                    ))
            except Exception as e:
                failed_count += 1
                logger.error(f'Error sending message {message.id}: {str(e)}')
                self.stdout.write(self.style.ERROR(
                    f'✗ Error: {message.message_template.message_type} to {message.recipient_email} - {str(e)}'
                ))
        
        self.stdout.write(self.style.SUCCESS(
            f'\nProcessing complete:\n'
            f'  - Sent: {sent_count}\n'
            f'  - Failed: {failed_count}\n'
            f'  - Canceled: {canceled_count}\n'
            f'  - Total: {total}'
        ))


# Also create a command for sending booking reminders
# Create this file at: your_app/management/commands/send_booking_reminders.py

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from core.models import Booking, SystemConfig
from core.utils import send_booking_reminder
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Send booking reminders based on reminder_lead_time_hours'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting booking reminder processing...'))
        
        config = SystemConfig.get_config()
        now = timezone.now()
        reminder_time = now + timedelta(hours=config.reminder_lead_time_hours)
        
        # Get confirmed bookings that are within the reminder window
        bookings = Booking.objects.filter(
            status='confirmed',
            appointment_date=reminder_time.date(),
            appointment_time__hour=reminder_time.hour
        ).select_related('client', 'salesman')
        
        total = bookings.count()
        self.stdout.write(f'Found {total} bookings requiring reminders')
        
        sent_count = 0
        failed_count = 0
        
        for booking in bookings:
            try:
                send_booking_reminder(booking)
                sent_count += 1
                self.stdout.write(self.style.SUCCESS(
                    f'✓ Reminder sent for: {booking.client.get_full_name()} - {booking.appointment_date} {booking.appointment_time}'
                ))
            except Exception as e:
                failed_count += 1
                logger.error(f'Error sending reminder for booking {booking.id}: {str(e)}')
                self.stdout.write(self.style.ERROR(
                    f'✗ Failed: {booking.client.get_full_name()} - {str(e)}'
                ))
        
        self.stdout.write(self.style.SUCCESS(
            f'\nReminder processing complete:\n'
            f'  - Sent: {sent_count}\n'
            f'  - Failed: {failed_count}\n'
            f'  - Total: {total}'
        ))
