from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
import logging
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from datetime import datetime, timedelta, time
import os
import pytz
from django.conf import settings
from .models import (SystemConfig, Booking, PayrollPeriod, AvailableTimeSlot, AvailabilityCycle, User, MessageTemplate, DripCampaign, 
                     ScheduledMessage, CommunicationLog)

logger = logging.getLogger(__name__)


def get_current_payroll_period():
    """
    Get current payroll period (Friday to Thursday 3 PM EST).
    
    CRITICAL: Payroll logic based on BOOKING CREATION TIME, not appointment date:
    - Payroll week: Friday 12:00 AM to Thursday 3:00 PM EST
    - After Thursday 3 PM: Booking goes to NEXT week's payroll
    
    Formula for finding current period:
    - Calculate days back to last Friday
    - Find corresponding Thursday (6 days forward)
    - If Thursday after 3 PM: shift to next week (Friday to Thursday)
    """
    # Get current time in EST
    est = pytz.timezone('US/Eastern')
    now_est = timezone.now().astimezone(est)
    today = now_est.date()
    
    # Calculate days since last Friday (weekday 4)
    # Monday(0): 3 days back, Tuesday(1): 4 days back, ..., Friday(4): 0 days, Saturday(5): 1 day back, Sunday(6): 2 days back
    if today.weekday() == 4:  # Friday
        days_back = 0
    elif today.weekday() > 4:  # Saturday(5), Sunday(6)
        days_back = today.weekday() - 4
    else:  # Monday(0) to Thursday(3)
        days_back = today.weekday() + 3
    
    period_start = today - timedelta(days=days_back)  # This Friday
    period_end = period_start + timedelta(days=6)  # This Thursday
    
    # CRITICAL: If Thursday after 3 PM EST, shift to NEXT week's payroll
    if today.weekday() == 3 and now_est.time() >= time(15, 0):  # Thursday after 3 PM
        period_start = period_start + timedelta(days=7)
        period_end = period_end + timedelta(days=7)
    
    return {
        'start': datetime.combine(period_start, time.min),
        'end': datetime.combine(period_end, time(15, 0)),  # Thursday 3 PM
        'start_date': period_start,
        'end_date': period_end
    }

def is_within_payroll_cutoff():
    """
    Check if current time is within payroll cutoff.
    Returns True if booking should go to current payroll, False if next payroll.
    """
    est = pytz.timezone('US/Eastern')
    now_est = timezone.now().astimezone(est)
    
    # If it's Thursday after 3 PM EST, bookings go to next week
    if now_est.weekday() == 3 and now_est.time() >= time(15, 0):
        return False
    
    # If it's Friday or Saturday, bookings go to next week
    if now_est.weekday() in [4, 5]:
        return False
    
    return True


def get_payroll_periods(weeks=3):
    """Get list of recent payroll periods"""
    periods = []
    current = get_current_payroll_period()
    
    for i in range(weeks):
        start = current['start_date'] - timedelta(weeks=i)
        end = start + timedelta(days=6)
        
        # Check if period exists in DB
        period = PayrollPeriod.objects.filter(start_date=start, end_date=end).first()
        
        periods.append({
            'start_date': start,
            'end_date': end,
            'label': f"Week of {start.strftime('%b %d')} - {end.strftime('%b %d, %Y')}",
            'is_finalized': period.status == 'finalized' if period else False,
            'period_obj': period
        })
    
    return periods

def delete_subsequent_timeslots(booking):
    """
    CRITICAL: Delete/deactivate 4 timeslots (including booked slot + next 3) = 2 hours total buffer.
    This ensures 1.5 hours AFTER the booking completes (30min booking + 1.5hr buffer = 2hr total).
    Deactivates BOTH zoom and in_person slots for the 2-hour window.
    
    Example: Booking at 9:00 AM → Deactivate 9:00, 9:30, 10:00, 10:30 (both types)
    
    Args:
        booking: Booking instance
    
    Returns:
        int: Number of slots deactivated
    """
    from datetime import datetime, timedelta
    
    # Calculate the booked slot + 3 subsequent time slots (30-minute intervals)
    base_time = datetime.combine(booking.appointment_date, booking.appointment_time)
    
    slots_to_deactivate = [booking.appointment_time]  # Include the booked time
    for i in range(1, 4):  # Next 3 slots (9:30, 10:00, 10:30 if booking at 9:00)
        slot_time = (base_time + timedelta(minutes=30 * i)).time()
        slots_to_deactivate.append(slot_time)
    
    # Deactivate BOTH zoom and in_person slots for this salesman on this date
    # Use update() instead of delete() to preserve data
    deactivated_count = AvailableTimeSlot.objects.filter(
        salesman=booking.salesman,
        date=booking.appointment_date,
        start_time__in=slots_to_deactivate,
        is_active=True
    ).update(is_active=False, is_booked=True)
    
    return deactivated_count

def generate_timeslots_for_cycle(salesman=None):
    """
    Generate timeslots automatically for each active salesman.
    NOW USES INDIVIDUAL SALESMAN SETTINGS AND RESPECTS SYSTEM CONFIG:
    - Days ahead from salesman.booking_advance_days
    - Weekdays from salesman.booking_weekdays
    - Time range from salesman.booking_start_time and booking_end_time
    - Meeting types from SystemConfig (zoom_enabled, in_person_enabled)
    Uses bulk_create for performance optimization.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Get system config to check which meeting types are enabled
    config = SystemConfig.get_config()
    enabled_types = []
    if config.zoom_enabled:
        enabled_types.append('zoom')
    if config.in_person_enabled:
        enabled_types.append('in_person')
    
    if not enabled_types:
        logger.warning("No meeting types are enabled in system config. Skipping slot generation.")
        return None
    
    logger.info(f"Enabled meeting types: {enabled_types}")
    
    cycle = AvailabilityCycle.get_current_cycle()
    logger.info(f"Using cycle: {cycle.start_date} to {cycle.end_date}")

    start_date = timezone.now().date()
    
    if salesman:
        salesmen = [salesman]
        logger.info(f"Generating slots for specific salesman: {salesman.get_full_name()} (ID: {salesman.id})")
    else:
        salesmen = User.objects.filter(is_active_salesman=True, is_active=True)
        logger.info(f"Generating slots for all {salesmen.count()} active salesmen")
    
    total_slots_created = 0
    for s_man in salesmen:
        # Use individual salesman settings
        days_ahead = s_man.booking_advance_days
        end_date = start_date + timedelta(days=days_ahead - 1)
        
        logger.info(f"Generating {days_ahead} days ahead for {s_man.get_full_name()} (until {end_date})")
        
        # Parse enabled weekdays from salesman settings
        enabled_weekdays = set()
        if s_man.booking_weekdays:
            try:
                enabled_weekdays = set(int(day.strip()) for day in s_man.booking_weekdays.split(',') if day.strip())
            except ValueError:
                logger.warning(f"Invalid weekday configuration for {s_man.get_full_name()}, defaulting to Mon-Fri")
                enabled_weekdays = {0, 1, 2, 3, 4}
        else:
            enabled_weekdays = {0, 1, 2, 3, 4}
        
        logger.info(f"Enabled weekdays for {s_man.get_full_name()}: {enabled_weekdays}")
        
        # Get time range from salesman settings
        start_time = s_man.booking_start_time
        end_time = s_man.booking_end_time
        
        slots_to_create = []
        current_date = start_date
        
        while current_date <= end_date:
            if current_date.weekday() in enabled_weekdays:
                current_dt = datetime.combine(current_date, start_time)
                end_dt = datetime.combine(current_date, end_time)

                while current_dt.time() < end_dt.time():
                    # Only generate slots for enabled meeting types
                    for appt_type in enabled_types:
                        slots_to_create.append(
                            AvailableTimeSlot(
                                cycle=cycle,
                                salesman=s_man,
                                date=current_date,
                                start_time=current_dt.time(),
                                appointment_type=appt_type,
                                created_by=s_man
                            )
                        )
                    current_dt += timedelta(minutes=30)
            
            current_date += timedelta(days=1)
        
        if slots_to_create:
            created_slots = AvailableTimeSlot.objects.bulk_create(
                slots_to_create, 
                ignore_conflicts=True
            )
            slots_count = len(created_slots) if created_slots else len(slots_to_create)
            total_slots_created += slots_count
            logger.info(f"Created {slots_count} slots for {s_man.get_full_name()}")

    logger.info(f"Total slots created: {total_slots_created}")
    return cycle


def ensure_timeslots_for_payroll_period(start_date, end_date, created_by=None):
    """
    Ensure timeslots exist for each active salesman within the given payroll period.
    Mon–Fri, 9:00–19:00, 30min intervals, both zoom and in_person.
    Uses bulk_create for performance optimization.
    """
    salesmen = User.objects.filter(is_active_salesman=True, is_active=True)
    
    for salesman in salesmen:
        # Pre-calculate all slots for this salesman
        slots_to_create = []
        current_date = start_date
        
        while current_date <= end_date:
            if current_date.weekday() < 5:  # Mon-Fri
                start = time(9, 0)
                end = time(19, 0)
                current_dt = datetime.combine(current_date, start)
                
                while current_dt.time() < end:
                    for appt_type in ['zoom', 'in_person']:
                        slots_to_create.append(
                            AvailableTimeSlot(
                                salesman=salesman,
                                date=current_date,
                                start_time=current_dt.time(),
                                appointment_type=appt_type,
                                created_by=(created_by or salesman)
                            )
                        )
                    current_dt += timedelta(minutes=30)
            current_date += timedelta(days=1)
        
        # Bulk create all slots for this salesman (PostgreSQL ON CONFLICT DO NOTHING)
        if slots_to_create:
            AvailableTimeSlot.objects.bulk_create(
                slots_to_create, 
                ignore_conflicts=True
            )


def cleanup_old_slots(weeks=2):
    """Mark unused slots older than N weeks as inactive (do not delete)."""
    cutoff = timezone.now().date() - timedelta(weeks=weeks)
    old_slots = AvailableTimeSlot.objects.filter(is_booked=False, date__lt=cutoff, is_active=True)
    count = old_slots.count()
    old_slots.update(is_active=False)
    return count


def mark_past_slots_inactive():
    """
    Auto-inactivate yesterday and older unbooked slots.
    Runs automatically on calendar view load.
    """
    today = timezone.now().date()
    qs = AvailableTimeSlot.objects.filter(
        date__lt=today, 
        is_active=True, 
        is_booked=False
    )
    updated = qs.update(is_active=False)
    return updated


def mark_elapsed_today_slots_inactive():
    """
    Auto-inactivate today's unbooked slots that have already elapsed.
    Runs automatically on calendar view load.
    """
    now = timezone.localtime()
    today = now.date()
    current_time = now.time()
    
    qs = AvailableTimeSlot.objects.filter(
        date=today, 
        start_time__lt=current_time, 
        is_active=True, 
        is_booked=False
    )
    updated = qs.update(is_active=False)
    return updated

def cleanup_past_dates_slots():
    """
    Enhanced cleanup: Mark all past date slots as inactive.
    Can be called from a daily cron job or management command.
    
    Returns:
        int: Number of slots deactivated
    """
    today = timezone.now().date()
    
    # Deactivate all past slots (including today if time has passed)
    past_slots = AvailableTimeSlot.objects.filter(
        date__lt=today,
        is_active=True
    )
    
    count = past_slots.update(is_active=False)
    
    # Also deactivate elapsed today slots
    now = timezone.localtime()
    today_elapsed = AvailableTimeSlot.objects.filter(
        date=today,
        start_time__lt=now.time(),
        is_active=True
    )
    
    count += today_elapsed.update(is_active=False)
    
    return count

def _get_twilio_client():
    """Create a Twilio client from environment variables/settings"""
    from django.conf import settings
    
    sid = settings.TWILIO_ACCOUNT_SID
    token = settings.TWILIO_AUTH_TOKEN
    from_number = settings.TWILIO_FROM_NUMBER
    
    # Check if credentials are configured
    if not sid or not token or not from_number:
        logger.warning("Twilio credentials not configured")
        return None, from_number
    
    try:
        from twilio.rest import Client
        client = Client(sid, token)
        return client, from_number
    except Exception as e:
        logger.error(f"Failed to create Twilio client: {str(e)}")
        return None, from_number


def is_sms_enabled():
    """Check if SMS is enabled via settings"""
    return getattr(settings, 'SMS_ENABLED', False)

def send_sms(to_phone: str, body: str) -> bool:
    """
    Send an SMS via Twilio. Returns True if sent, False otherwise.
    
    Args:
        to_phone: Phone number in E.164 format (e.g., +12345678900)
        body: SMS message body (max 1600 chars, but recommend 320 for single SMS)
    
    Returns:
        bool: True if SMS sent successfully, False otherwise
    """
    from .models import CommunicationLog
    
    if not to_phone or not body:
        logger.warning("SMS send failed: Missing phone number or body")
        return False
    
    # Check if SMS is enabled
    if not is_sms_enabled():
        logger.info("SMS sending disabled in settings")
        return False
    
    # Normalize phone number to E.164 format if needed
    to_phone = normalize_phone_number(to_phone)
    
    if not to_phone:
        logger.warning("Invalid phone number format")
        return False
    
    client, from_number = _get_twilio_client()
    if client is None:
        logger.error("Twilio client not available")
        return False
    
    try:
        # Truncate body to 320 chars for single SMS
        body = body[:320] if len(body) > 320 else body
        
        message = client.messages.create(
            from_=from_number,
            to=to_phone,
            body=body
        )
        
        # Log successful SMS
        CommunicationLog.objects.create(
            recipient_phone=to_phone,
            communication_type='sms',
            body=body,
            status='sent'
        )
        
        logger.info(f"SMS sent successfully to {to_phone}, SID: {message.sid}")
        return True
        
    except Exception as e:
        # Log failed SMS
        error_msg = str(e)
        logger.error(f"SMS send failed to {to_phone}: {error_msg}")
        
        CommunicationLog.objects.create(
            recipient_phone=to_phone,
            communication_type='sms',
            body=body,
            status='failed',
            error_message=error_msg
        )
        return False


def normalize_phone_number(phone: str) -> str:
    """
    Normalize phone number to E.164 format.
    
    Examples:
        '7025096502' -> '+17025096502'
        '702-509-6502' -> '+17025096502'
        '+17025096502' -> '+17025096502'
    
    Args:
        phone: Phone number in any common format
    
    Returns:
        str: Phone number in E.164 format, or empty string if invalid
    """
    if not phone:
        return ''
    
    # Remove all non-digit characters except leading +
    cleaned = ''.join(c for c in phone if c.isdigit() or c == '+')
    
    # If already has +, validate length
    if cleaned.startswith('+'):
        # E.164 format: +[country code][number]
        # US numbers: +1 followed by 10 digits = 12 chars total
        if len(cleaned) >= 11:  # Minimum valid length
            return cleaned
        else:
            logger.warning(f"Invalid E.164 phone number: {cleaned}")
            return ''
    
    # Assume US number if no country code
    if len(cleaned) == 10:
        return f'+1{cleaned}'
    elif len(cleaned) == 11 and cleaned.startswith('1'):
        return f'+{cleaned}'
    else:
        logger.warning(f"Invalid phone number length: {cleaned}")
        return ''


def validate_phone_number(phone: str) -> bool:
    """
    Validate if a phone number is in correct format.
    
    Args:
        phone: Phone number to validate
    
    Returns:
        bool: True if valid, False otherwise
    """
    normalized = normalize_phone_number(phone)
    return bool(normalized)


def start_drip_campaign(booking, campaign_type):
    """Start a drip campaign for a booking (AD or DNA)"""
    # Check if campaign already exists
    existing = DripCampaign.objects.filter(
        booking=booking,
        campaign_type=campaign_type,
        is_active=True
    ).exists()
    
    if existing:
        return None
    
    # Create the campaign
    campaign = DripCampaign.objects.create(
        booking=booking,
        campaign_type=campaign_type
    )
    
    # Schedule messages based on campaign type
    if campaign_type == 'attended':
        schedule_ad_drip(campaign)
    elif campaign_type == 'did_not_attend':
        schedule_dna_drip(campaign)
    
    return campaign


def schedule_ad_drip(campaign):
    """Schedule AD (Attended) drip messages - 21 days"""
    booking = campaign.booking
    now = timezone.now()
    
    # Day 1, 7, 14, 21
    days = [1, 7, 14, 21]
    template_types = ['ad_day_1', 'ad_day_7', 'ad_day_14', 'ad_day_21']
    
    for day, template_type in zip(days, template_types):
        try:
            template = MessageTemplate.objects.get(message_type=template_type, is_active=True)
            scheduled_for = now + timedelta(days=day)
            
            ScheduledMessage.objects.create(
                drip_campaign=campaign,
                message_template=template,
                recipient_email=booking.client.email,
                recipient_phone=booking.client.phone_number,
                scheduled_for=scheduled_for,
                status='pending'
            )
        except MessageTemplate.DoesNotExist:
            continue


def schedule_dna_drip(campaign):
    """Schedule DNA (Did Not Attend) drip messages - 90 days"""
    booking = campaign.booking
    now = timezone.now()
    
    # Day 1, 7, 30, 60, 90
    days = [1, 7, 30, 60, 90]
    template_types = ['dna_day_1', 'dna_day_7', 'dna_day_30', 'dna_day_60', 'dna_day_90']
    
    for day, template_type in zip(days, template_types):
        try:
            template = MessageTemplate.objects.get(message_type=template_type, is_active=True)
            scheduled_for = now + timedelta(days=day)
            
            ScheduledMessage.objects.create(
                drip_campaign=campaign,
                message_template=template,
                recipient_email=booking.client.email,
                recipient_phone=booking.client.phone_number,
                scheduled_for=scheduled_for,
                status='pending'
            )
        except MessageTemplate.DoesNotExist:
            logger.error(f"MessageTemplate '{template_type}' not found!")
            raise


def send_drip_message(scheduled_message):
    """
    Send a drip campaign message (both email and SMS) using the themed template.
    Updated to use the base email template wrapper.
    """
    message_template = scheduled_message.message_template
    recipient_email = scheduled_message.recipient_email
    recipient_phone = scheduled_message.recipient_phone
    
    # Build context from the booking
    booking = scheduled_message.drip_campaign.booking
    config = SystemConfig.get_config()
    
    context = {
        'client_name': booking.client.get_full_name(),
        'salesman_name': booking.salesman.get_full_name(),
        'business_name': booking.client.business_name,
        'appointment_date': booking.appointment_date.strftime('%B %d, %Y'),
        'appointment_time': booking.appointment_time.strftime('%I:%M %p'),
        'company_name': config.company_name,
    }
    
    email_sent = False
    sms_sent = False
    
    # Send email with theme
    try:
        subject, body_content = message_template.render_email(context)
        
        # Wrap in base theme
        email_context = {
            'subject': subject,
            'content': body_content,
            'company_name': context.get('company_name', 'RAU Scheduling'),
            'current_year': datetime.now().year,
        }
        
        html_message = render_to_string('emails/base_email_template.html', email_context)
        plain_message = strip_tags(body_content)
        
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            html_message=html_message,
            fail_silently=False,
        )
        email_sent = True
        
        CommunicationLog.objects.create(
            recipient_email=recipient_email,
            communication_type='email',
            message_template=message_template,
            subject=subject,
            body=html_message,
            status='sent'
        )
    except Exception as e:
        CommunicationLog.objects.create(
            recipient_email=recipient_email,
            communication_type='email',
            message_template=message_template,
            subject=message_template.email_subject,
            body=message_template.email_body,
            status='failed',
            error_message=str(e)
        )
    
    # Send SMS
    if recipient_phone:
        sms_body = message_template.render_sms(context)
        sms_sent = send_sms(recipient_phone, sms_body)
    
    return email_sent or sms_sent


def send_drip_message(scheduled_message):
    """
    Send a drip campaign message (both email and SMS) using the themed template.
    Updated to use the base email template wrapper.
    
    NOTE: This function takes a ScheduledMessage object, not individual parameters.
    """
    message_template = scheduled_message.message_template
    recipient_email = scheduled_message.recipient_email
    recipient_phone = scheduled_message.recipient_phone
    
    # Build context from the booking
    booking = scheduled_message.drip_campaign.booking
    config = SystemConfig.get_config()
    
    context = {
        'client_name': booking.client.get_full_name(),
        'salesman_name': booking.salesman.get_full_name(),
        'business_name': booking.client.business_name,
        'appointment_date': booking.appointment_date.strftime('%B %d, %Y'),
        'appointment_time': booking.appointment_time.strftime('%I:%M %p'),
        'company_name': config.company_name,
    }
    
    email_sent = False
    sms_sent = False
    
    # Send email with theme
    try:
        subject, body_content = message_template.render_email(context)
        
        # Wrap in base theme
        email_context = {
            'subject': subject,
            'content': body_content,
            'company_name': context.get('company_name', 'RAU Scheduling'),
            'current_year': datetime.now().year,
        }
        
        html_message = render_to_string('emails/base_email_template.html', email_context)
        plain_message = strip_tags(body_content)
        
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            html_message=html_message,
            fail_silently=False,
        )
        email_sent = True
        
        CommunicationLog.objects.create(
            recipient_email=recipient_email,
            communication_type='email',
            message_template=message_template,
            subject=subject,
            body=html_message,
            status='sent'
        )
    except Exception as e:
        logger.error(f"Error sending drip email to {recipient_email}: {str(e)}")
        CommunicationLog.objects.create(
            recipient_email=recipient_email,
            communication_type='email',
            message_template=message_template,
            subject=message_template.email_subject,
            body=message_template.email_body,
            status='failed',
            error_message=str(e)
        )
    
    # Send SMS
    if recipient_phone:
        try:
            sms_body = message_template.render_sms(context)
            sms_sent = send_sms(recipient_phone, sms_body)
        except Exception as e:
            logger.error(f"Error sending drip SMS to {recipient_phone}: {str(e)}")
    
    return email_sent or sms_sent


def send_drip_message(scheduled_message):
    """
    Send a drip campaign message (both email and SMS) using the themed template.
    Updated to use the base email template wrapper.
    
    NOTE: This function takes a ScheduledMessage object, not individual parameters.
    """
    message_template = scheduled_message.message_template
    recipient_email = scheduled_message.recipient_email
    recipient_phone = scheduled_message.recipient_phone
    
    # Build context from the booking
    booking = scheduled_message.drip_campaign.booking
    config = SystemConfig.get_config()
    
    context = {
        'client_name': booking.client.get_full_name(),
        'salesman_name': booking.salesman.get_full_name(),
        'business_name': booking.client.business_name,
        'appointment_date': booking.appointment_date.strftime('%B %d, %Y'),
        'appointment_time': booking.appointment_time.strftime('%I:%M %p'),
        'company_name': config.company_name,
    }
    
    email_sent = False
    sms_sent = False
    
    # Send email with theme
    try:
        subject, body_content = message_template.render_email(context)
        
        # Wrap in base theme
        email_context = {
            'subject': subject,
            'content': body_content,
            'company_name': context.get('company_name', 'RAU Scheduling'),
            'current_year': datetime.now().year,
        }
        
        html_message = render_to_string('emails/base_email_template.html', email_context)
        plain_message = strip_tags(body_content)
        
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            html_message=html_message,
            fail_silently=False,
        )
        email_sent = True
        
        CommunicationLog.objects.create(
            recipient_email=recipient_email,
            communication_type='email',
            message_template=message_template,
            subject=subject,
            body=html_message,
            status='sent'
        )
    except Exception as e:
        logger.error(f"Error sending drip email to {recipient_email}: {str(e)}")
        CommunicationLog.objects.create(
            recipient_email=recipient_email,
            communication_type='email',
            message_template=message_template,
            subject=message_template.email_subject,
            body=message_template.email_body,
            status='failed',
            error_message=str(e)
        )
    
    # Send SMS
    if recipient_phone:
        try:
            sms_body = message_template.render_sms(context)
            sms_sent = send_sms(recipient_phone, sms_body)
        except Exception as e:
            logger.error(f"Error sending drip SMS to {recipient_phone}: {str(e)}")
    
    return email_sent or sms_sent


def check_booking_conflicts(salesman, appointment_date, appointment_time, duration_minutes, exclude_booking_id=None):
    """Check for booking conflicts including buffer time"""
    config = SystemConfig.get_config()
    
    # Calculate time range including buffer
    start_dt = datetime.combine(appointment_date, appointment_time)
    end_dt = start_dt + timedelta(minutes=duration_minutes + config.buffer_time_minutes)
    
    # Check for overlapping bookings
    conflicts = Booking.objects.filter(
        salesman=salesman,
        appointment_date=appointment_date,
        status__in=['confirmed', 'completed']
    ).exclude(id=exclude_booking_id)
    
    for booking in conflicts:
        booking_start = datetime.combine(booking.appointment_date, booking.appointment_time)
        booking_end = booking_start + timedelta(minutes=booking.duration_minutes + config.buffer_time_minutes)
        
        # Check for overlap
        if start_dt < booking_end and end_dt > booking_start:
            return True, booking
    
    return False, None


def send_email_with_template(template_type, recipient_email, context, booking=None):
    """
    Send email using MessageTemplate with base theme wrapper.
    Automatically wraps database template content in styled email theme.
    """
    from .models import MessageTemplate, CommunicationLog
    
    try:
        template = MessageTemplate.objects.get(message_type=template_type, is_active=True)
    except MessageTemplate.DoesNotExist:
        logger.error(f"MessageTemplate '{template_type}' not found or inactive")
        return False
    
    try:
        # Render the subject and body from database template
        subject, body_content = template.render_email(context)
        
        # Add additional context for the base template
        email_context = {
            'subject': subject,
            'content': body_content,
            'company_name': context.get('company_name', 'RAU Scheduling'),
            'current_year': datetime.now().year,
        }
        
        # Wrap the content in the base email theme
        html_message = render_to_string('emails/base_email_template.html', email_context)
        
        # Create plain text version by stripping HTML tags
        plain_message = strip_tags(body_content)
        
        # Send email with both HTML and plain text versions
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            html_message=html_message,
            fail_silently=False,
        )
        
        # Log the email
        CommunicationLog.objects.create(
            booking=booking,
            recipient_email=recipient_email,
            communication_type='email',
            message_template=template,
            subject=subject,
            body=html_message,
            status='sent'
        )
        
        return True
        
    except Exception as e:
        logger.error(f"Error sending email with template '{template_type}' to {recipient_email}: {str(e)}")
        # Log failed email
        CommunicationLog.objects.create(
            booking=booking,
            recipient_email=recipient_email,
            communication_type='email',
            message_template=template,
            subject=template.email_subject,
            body=template.email_body,
            status='failed',
            error_message=str(e)
        )
        return False


def send_sms_with_template(template_type, recipient_phone, context, booking=None):
    """Send SMS using MessageTemplate"""
    from .models import MessageTemplate
    
    if not recipient_phone:
        return False
        
    try:
        template = MessageTemplate.objects.get(message_type=template_type, is_active=True)
    except MessageTemplate.DoesNotExist:
        logger.error(f"MessageTemplate '{template_type}' not found or inactive")
        return False
    
    try:
        from .utils import send_sms
        body = template.render_sms(context)
        return send_sms(recipient_phone, body)
    except Exception as e:
        logger.error(f"Error sending SMS with template '{template_type}' to {recipient_phone}: {str(e)}")
        return False


def send_booking_approved_notification(booking):
    """Send notifications when booking is approved - separate messages for agent, client, and salesman
    
    Live Transfer: Only sends to agent and admin (not client/salesman)
    In-Person: Includes location
    Zoom: Includes zoom_link
    """
    from .models import SystemConfig
    
    config = SystemConfig.get_config()
    
    # Determine meeting type details
    meeting_details = ''
    if booking.appointment_type == 'live_transfer':
        meeting_details = 'This is a LIVE TRANSFER appointment.'
    elif booking.appointment_type == 'in_person':
        meeting_details = f'Location: {booking.meeting_address}' if booking.meeting_address else 'In-Person Meeting'
    elif booking.appointment_type == 'zoom':
        meeting_details = f'Zoom Link: {booking.zoom_link}' if booking.zoom_link else 'Zoom Meeting'
    
    # Base context - INCLUDES booking_status
    base_context = {
        'client_name': booking.client.get_full_name(),
        'salesman_name': booking.salesman.get_full_name(),
        'business_name': booking.client.business_name,
        'appointment_date': booking.appointment_date.strftime('%B %d, %Y'),
        'appointment_time': booking.appointment_time.strftime('%I:%M %p'),
        'company_name': config.company_name,
        'meeting_type': booking.get_appointment_type_display(),
        'meeting_details': meeting_details,
        'location': booking.meeting_address if booking.appointment_type == 'in_person' else '',
        'zoom_link': booking.zoom_link if booking.appointment_type == 'zoom' else '',
        'booking_status': booking.get_status_display(),
    }
    
    # For LIVE TRANSFER: Only send to agent and admin
    if booking.appointment_type == 'live_transfer':
        # Send to Agent
        if booking.created_by and booking.created_by.groups.filter(name='remote_agent').exists():
            agent_context = {**base_context, 'agent_name': booking.created_by.get_full_name()}
            send_email_with_template('booking_approved_agent', booking.created_by.email, agent_context, booking)
            if hasattr(booking.created_by, 'phone_number') and booking.created_by.phone_number:
                send_sms_with_template('booking_approved_agent', booking.created_by.phone_number, agent_context, booking)
        
        # Send to Admin
        if booking.approved_by:
            admin_context = {**base_context, 'admin_name': booking.approved_by.get_full_name()}
            send_email_with_template('booking_approved_admin', booking.approved_by.email, admin_context, booking)
            if hasattr(booking.approved_by, 'phone_number') and booking.approved_by.phone_number:
                send_sms_with_template('booking_approved_admin', booking.approved_by.phone_number, admin_context, booking)
    else:
        # For IN-PERSON and ZOOM: Send to agent, client, and salesman
        
        # Send to Agent
        if booking.created_by and booking.created_by.groups.filter(name='remote_agent').exists():
            agent_context = {**base_context, 'agent_name': booking.created_by.get_full_name()}
            send_email_with_template('booking_approved_agent', booking.created_by.email, agent_context, booking)
            if hasattr(booking.created_by, 'phone_number') and booking.created_by.phone_number:
                send_sms_with_template('booking_approved_agent', booking.created_by.phone_number, agent_context, booking)
        
        # Send to Client
        client_context = base_context.copy()
        send_email_with_template('booking_approved_client', booking.client.email, client_context, booking)
        if booking.client.phone_number:
            send_sms_with_template('booking_approved_client', booking.client.phone_number, client_context, booking)
        
        # Send to Salesman
        salesman_context = base_context.copy()
        send_email_with_template('booking_approved_salesman', booking.salesman.email, salesman_context, booking)
        if hasattr(booking.salesman, 'phone_number') and booking.salesman.phone_number:
            send_sms_with_template('booking_approved_salesman', booking.salesman.phone_number, salesman_context, booking)


def send_booking_created_notification(booking):
    """Send notifications when a new booking is created"""
    from .models import SystemConfig, User
    
    config = SystemConfig.get_config()
    
    # Determine meeting type details
    meeting_details = ''
    if booking.appointment_type == 'live_transfer':
        meeting_details = 'This is a LIVE TRANSFER appointment.'
    elif booking.appointment_type == 'in_person':
        meeting_details = f'Location: {booking.meeting_address}' if booking.meeting_address else 'In-Person Meeting'
    elif booking.appointment_type == 'zoom':
        meeting_details = f'Zoom Link: {booking.zoom_link}' if booking.zoom_link else 'Zoom Meeting'
    
    # Base context
    base_context = {
        'client_name': booking.client.get_full_name(),
        'salesman_name': booking.salesman.get_full_name(),
        'business_name': booking.client.business_name,
        'appointment_date': booking.appointment_date.strftime('%B %d, %Y'),
        'appointment_time': booking.appointment_time.strftime('%I:%M %p'),
        'company_name': config.company_name,
        'meeting_type': booking.get_appointment_type_display(),
        'meeting_details': meeting_details,
        'location': booking.meeting_address if booking.appointment_type == 'in_person' else '',
        'zoom_link': booking.zoom_link if booking.appointment_type == 'zoom' else '',
        'booking_status': booking.get_status_display(),
    }
    
    # Send to Agent
    if booking.created_by and booking.created_by.groups.filter(name='remote_agent').exists():
        agent_context = {**base_context, 'agent_name': booking.created_by.get_full_name()}
        send_email_with_template('booking_created_agent', booking.created_by.email, agent_context, booking)
        if hasattr(booking.created_by, 'phone_number') and booking.created_by.phone_number:
            send_sms_with_template('booking_created_agent', booking.created_by.phone_number, agent_context, booking)
    
    # Send to Admin(s)
    admin_users = User.objects.filter(is_staff=True, is_active=True)
    for admin in admin_users:
        admin_context = {
            **base_context,
            'admin_name': admin.get_full_name(),
            'agent_name': booking.created_by.get_full_name() if booking.created_by else 'System',
        }
        send_email_with_template('booking_created_admin', admin.email, admin_context, booking)
        if hasattr(admin, 'phone_number') and admin.phone_number:
            send_sms_with_template('booking_created_admin', admin.phone_number, admin_context, booking)


def send_booking_declined_notification(booking):
    """Send notification when booking is declined"""
    from .models import SystemConfig
    
    config = SystemConfig.get_config()
    
    # Determine meeting type details
    meeting_details = ''
    if booking.appointment_type == 'live_transfer':
        meeting_details = 'LIVE TRANSFER'
    elif booking.appointment_type == 'in_person':
        meeting_details = f'In-Person at {booking.meeting_address}' if booking.meeting_address else 'In-Person Meeting'
    elif booking.appointment_type == 'zoom':
        meeting_details = 'Zoom Meeting'
    
    base_context = {
        'client_name': booking.client.get_full_name(),
        'salesman_name': booking.salesman.get_full_name(),
        'business_name': booking.client.business_name,
        'appointment_date': booking.appointment_date.strftime('%B %d, %Y'),
        'appointment_time': booking.appointment_time.strftime('%I:%M %p'),
        'company_name': config.company_name,
        'meeting_type': booking.get_appointment_type_display(),
        'meeting_details': meeting_details,
        'decline_reason': f'<p><strong>Reason:</strong> {booking.decline_reason}</p>' if booking.decline_reason else '',
        'decline_reason_short': booking.decline_reason[:50] if booking.decline_reason else 'See email',
        'admin_name': booking.declined_by.get_full_name() if booking.declined_by else 'Admin',
        'booking_status': booking.get_status_display(),
    }
    
    # Send to Agent
    if booking.created_by and booking.created_by.groups.filter(name='remote_agent').exists():
        agent_context = {**base_context, 'agent_name': booking.created_by.get_full_name()}
        send_email_with_template('booking_declined_agent', booking.created_by.email, agent_context, booking)
        if hasattr(booking.created_by, 'phone_number') and booking.created_by.phone_number:
            send_sms_with_template('booking_declined_agent', booking.created_by.phone_number, agent_context, booking)
    
    # Send to Admin
    if booking.declined_by:
        admin_context = base_context.copy()
        send_email_with_template('booking_declined_admin', booking.declined_by.email, admin_context, booking)


def send_booking_reminder(booking):
    """Send appointment reminder to client and salesman"""
    from .models import SystemConfig
    
    config = SystemConfig.get_config()
    
    # Skip reminders for live transfers
    if booking.appointment_type == 'live_transfer':
        return
    
    # Determine meeting type details
    meeting_details = ''
    if booking.appointment_type == 'in_person':
        meeting_details = f'Location: {booking.meeting_address}' if booking.meeting_address else 'In-Person Meeting'
    elif booking.appointment_type == 'zoom':
        meeting_details = f'Zoom Link: {booking.zoom_link}' if booking.zoom_link else 'Zoom Meeting'
    
    base_context = {
        'client_name': booking.client.get_full_name(),
        'salesman_name': booking.salesman.get_full_name(),
        'business_name': booking.client.business_name,
        'appointment_date': booking.appointment_date.strftime('%B %d, %Y'),
        'appointment_time': booking.appointment_time.strftime('%I:%M %p'),
        'company_name': config.company_name,
        'meeting_type': booking.get_appointment_type_display(),
        'meeting_details': meeting_details,
        'location': booking.meeting_address if booking.appointment_type == 'in_person' else '',
        'zoom_link': booking.zoom_link if booking.appointment_type == 'zoom' else '',
        'booking_status': booking.get_status_display(),
    }
    
    # Send to Client
    client_context = base_context.copy()
    send_email_with_template('booking_reminder_client', booking.client.email, client_context, booking)
    if booking.client.phone_number:
        send_sms_with_template('booking_reminder_client', booking.client.phone_number, client_context, booking)
    
    # Send to Salesman
    salesman_context = base_context.copy()
    send_email_with_template('booking_reminder_salesman', booking.salesman.email, salesman_context, booking)
    if hasattr(booking.salesman, 'phone_number') and booking.salesman.phone_number:
        send_sms_with_template('booking_reminder_salesman', booking.salesman.phone_number, salesman_context, booking)


def process_scheduled_messages():
    """Process all pending scheduled messages (call from cron job)"""
    now = timezone.now()
    
    # Get all pending messages that are due
    pending_messages = ScheduledMessage.objects.filter(
        status='pending',
        scheduled_for__lte=now
    ).select_related('drip_campaign', 'message_template')
    
    for message in pending_messages:
        message.send_message()