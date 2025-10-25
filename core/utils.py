from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from django.utils import timezone
from datetime import datetime, timedelta, time
import os
import pytz
from .models import (SystemConfig, Booking, PayrollPeriod, AvailableTimeSlot, AvailabilityCycle, User, MessageTemplate, DripCampaign, 
                     ScheduledMessage, CommunicationLog)


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
    CRITICAL NEW FUNCTION: Delete 3 subsequent timeslots after a booking (1.5 hours buffer).
    Deletes BOTH zoom and in_person slots for the 1.5 hour window.
    
    Example: Booking at 9:00 AM → Delete 9:30, 10:00, 10:30 (both types)
    
    Args:
        booking: Booking instance
    """
    from datetime import datetime, timedelta
    
    # Calculate the 3 subsequent time slots (30-minute intervals)
    base_time = datetime.combine(booking.appointment_date, booking.appointment_time)
    
    slots_to_delete = []
    for i in range(1, 4):  # Next 3 slots (9:30, 10:00, 10:30)
        slot_time = (base_time + timedelta(minutes=30 * i)).time()
        slots_to_delete.append(slot_time)
    
    # Delete BOTH zoom and in_person slots for this salesman on this date
    deleted_count = AvailableTimeSlot.objects.filter(
        salesman=booking.salesman,
        date=booking.appointment_date,
        start_time__in=slots_to_delete
    ).delete()[0]
    
    return deleted_count

def generate_timeslots_for_cycle(salesman=None):
    """
    Generate timeslots automatically for each active salesman.
    NOW USES INDIVIDUAL SALESMAN SETTINGS:
    - Days ahead from salesman.booking_advance_days
    - Weekdays from salesman.booking_weekdays
    - Time range from salesman.booking_start_time and booking_end_time
    Uses bulk_create for performance optimization.
    """
    import logging
    logger = logging.getLogger(__name__)
    
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
                    for appt_type in ['zoom', 'in_person']:
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
    """Auto-inactivate yesterday and older unbooked slots (keep data)."""
    today = timezone.now().date()
    qs = AvailableTimeSlot.objects.filter(date__lt=today, is_active=True, is_booked=False)
    updated = qs.update(is_active=False)
    return updated


def mark_elapsed_today_slots_inactive():
    """Auto-inactivate today's unbooked slots that have already elapsed."""
    now = timezone.localtime()
    today = now.date()
    qs = AvailableTimeSlot.objects.filter(date=today, start_time__lt=now.time(), is_active=True, is_booked=False)
    updated = qs.update(is_active=False)
    return updated


def _get_twilio_client():
    """Create a Twilio client from environment variables only"""
    # Get credentials from environment variables
    sid = os.getenv('TWILIO_ACCOUNT_SID', '')
    token = os.getenv('TWILIO_AUTH_TOKEN', '')
    from_number = os.getenv('TWILIO_FROM_NUMBER', '')
    
    # Check if credentials are configured
    if not sid or not token or not from_number:
        return None, from_number
    
    try:
        from twilio.rest import Client
        client = Client(sid, token)
        return client, from_number
    except Exception:
        return None, from_number


def is_sms_enabled():
    """Check if SMS is enabled via environment variable"""
    return os.getenv('SMS_ENABLED', 'false').lower() in ('true', '1', 'yes')


def send_sms(to_phone: str, body: str) -> bool:
    """Send an SMS via Twilio. Returns True if sent, False otherwise."""
    if not to_phone or not body:
        return False
    
    # Check if SMS is enabled
    if not is_sms_enabled():
        return False
    
    client, from_number = _get_twilio_client()
    if client is None:
        return False
    
    try:
        message = client.messages.create(
            from_=from_number,
            to=to_phone,
            body=body[:320]  # Limit to 320 chars
        )
        
        # Log the SMS
        CommunicationLog.objects.create(
            recipient_phone=to_phone,
            communication_type='sms',
            body=body,
            status='sent'
        )
        
        return True
    except Exception as e:
        # Log failed SMS
        CommunicationLog.objects.create(
            recipient_phone=to_phone,
            communication_type='sms',
            body=body,
            status='failed',
            error_message=str(e)
        )
        return False


def send_email_with_template(template_type, recipient_email, context, booking=None):
    """Send email using MessageTemplate"""
    try:
        template = MessageTemplate.objects.get(message_type=template_type, is_active=True)
    except MessageTemplate.DoesNotExist:
        return False
    
    try:
        subject, body = template.render_email(context)
        
        send_mail(
            subject=subject,
            message=strip_tags(body),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            html_message=body,
            fail_silently=False,
        )
        
        # Log the email
        CommunicationLog.objects.create(
            booking=booking,
            recipient_email=recipient_email,
            communication_type='email',
            message_template=template,
            subject=subject,
            body=body,
            status='sent'
        )
        
        return True
    except Exception as e:
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
    try:
        template = MessageTemplate.objects.get(message_type=template_type, is_active=True)
    except MessageTemplate.DoesNotExist:
        return False
    
    body = template.render_sms(context)
    return send_sms(recipient_phone, body)




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
            continue


def send_drip_message(message_template, recipient_email, recipient_phone, context):
    """Send a drip campaign message (both email and SMS)"""
    email_sent = False
    sms_sent = False
    
    # Send email
    try:
        subject, body = message_template.render_email(context)
        send_mail(
            subject=subject,
            message=strip_tags(body),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            html_message=body,
            fail_silently=False,
        )
        email_sent = True
        
        CommunicationLog.objects.create(
            recipient_email=recipient_email,
            communication_type='email',
            message_template=message_template,
            subject=subject,
            body=body,
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


def send_email_with_template(template_type, recipient_email, context, booking=None):
    """Send email using MessageTemplate"""
    try:
        template = MessageTemplate.objects.get(message_type=template_type, is_active=True)
    except MessageTemplate.DoesNotExist:
        return False
    
    try:
        subject, body = template.render_email(context)
        
        send_mail(
            subject=subject,
            message=strip_tags(body),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            html_message=body,
            fail_silently=False,
        )
        
        # Log the email
        CommunicationLog.objects.create(
            booking=booking,
            recipient_email=recipient_email,
            communication_type='email',
            message_template=template,
            subject=subject,
            body=body,
            status='sent'
        )
        
        return True
    except Exception as e:
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
    try:
        template = MessageTemplate.objects.get(message_type=template_type, is_active=True)
    except MessageTemplate.DoesNotExist:
        return False
    
    body = template.render_sms(context)
    return send_sms(recipient_phone, body)


def send_booking_approved_notification(booking):
    """Send notifications when booking is approved - uses templates"""
    config = SystemConfig.get_config()
    
    context = {
        'client_name': booking.client.get_full_name(),
        'salesman_name': booking.salesman.get_full_name(),
        'business_name': booking.client.business_name,
        'appointment_date': booking.appointment_date.strftime('%B %d, %Y'),
        'appointment_time': booking.appointment_time.strftime('%I:%M %p'),
        'company_name': config.company_name,
    }
    
    # Send to Agent (who created the booking)
    if booking.created_by.groups.filter(name='remote_agent').exists():
        send_email_with_template('booking_approved_agent', booking.created_by.email, context, booking)
        send_sms_with_template('booking_approved_agent', getattr(booking.created_by, 'phone_number', None), context, booking)
    
    # Send to Client
    send_email_with_template('booking_approved_client', booking.client.email, context, booking)
    send_sms_with_template('booking_approved_client', booking.client.phone_number, context, booking)
    
    # Send to Salesman
    send_email_with_template('booking_approved_salesman', booking.salesman.email, context, booking)
    send_sms_with_template('booking_approved_salesman', getattr(booking.salesman, 'phone_number', None), context, booking)

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


def send_booking_reminder(booking):
    """Send appointment reminder to client and salesman - uses templates"""
    config = SystemConfig.get_config()
    
    context = {
        'client_name': booking.client.get_full_name(),
        'salesman_name': booking.salesman.get_full_name(),
        'business_name': booking.client.business_name,
        'appointment_date': booking.appointment_date.strftime('%B %d, %Y'),
        'appointment_time': booking.appointment_time.strftime('%I:%M %p'),
        'company_name': config.company_name,
    }
    
    # Send to Client
    send_email_with_template('booking_reminder_client', booking.client.email, context, booking)
    send_sms_with_template('booking_reminder_client', booking.client.phone_number, context, booking)
    
    # Send to Salesman
    send_email_with_template('booking_reminder_salesman', booking.salesman.email, context, booking)
    send_sms_with_template('booking_reminder_salesman', getattr(booking.salesman, 'phone_number', None), context, booking)


def send_booking_confirmation(booking, to_client=True, to_salesman=True):
    """Send booking confirmation email + SMS (if configured)."""
    config = SystemConfig.get_config()
    
    context = {
        'booking': booking,
        'company_name': config.company_name,
    }
    
    if to_client:
        subject = f"Appointment Confirmed with {booking.salesman.get_full_name()}"
        html_message = render_to_string('emails/booking_confirmation_client.html', context)
        plain_message = strip_tags(html_message)
        
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[booking.client.email],
            html_message=html_message,
            fail_silently=False,
        )
        # SMS to client
        try:
            sms_body = f"Confirmed: {booking.appointment_date} at {booking.appointment_time.strftime('%I:%M %p')} with {booking.salesman.get_full_name()}"
            send_sms(getattr(booking.client, 'phone_number', None), sms_body)
        except Exception:
            pass
    
    if to_salesman:
        subject = f"New Appointment: {booking.client.get_full_name()} on {booking.appointment_date}"
        html_message = render_to_string('emails/booking_confirmation_salesman.html', context)
        plain_message = strip_tags(html_message)
        
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[booking.salesman.email],
            html_message=html_message,
            fail_silently=False,
        )
        # SMS to salesman
        try:
            sms_body = f"New appt: {booking.client.get_full_name()} {booking.appointment_date} {booking.appointment_time.strftime('%I:%M %p')}"
            send_sms(getattr(booking.salesman, 'phone_number', None), sms_body)
        except Exception:
            pass
def send_booking_cancellation(booking):
    """Send cancellation notification"""
    config = SystemConfig.get_config()
    
    context = {
        'booking': booking,
        'company_name': config.company_name,
    }
    
    subject = f"Appointment Canceled: {booking.appointment_date}"
    html_message = render_to_string('emails/booking_cancellation.html', context)
    plain_message = strip_tags(html_message)
    
    send_mail(
        subject=subject,
        message=plain_message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[booking.client.email, booking.salesman.email],
        html_message=html_message,
        fail_silently=False,
    )

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

def send_booking_declined_notification(booking):
    """
    Send notification when booking is declined by admin (email + SMS to agent)
    """
    # Email/SMS to remote agent who created the booking
    if booking.created_by.groups.filter(name='remote_agent').exists():
        subject = f'Booking Declined - {booking.client.get_full_name()}'
        
        context = {
            'booking': booking,
            'agent': booking.created_by,
            'admin': booking.declined_by,
        }
        
        message = render_to_string('emails/booking_declined.txt', context)
        html_message = render_to_string('emails/booking_declined.html', context)
        
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[booking.created_by.email],
            html_message=html_message,
            fail_silently=False,
        )
        # SMS to agent
        try:
            sms_body = f"Declined: {booking.client.get_full_name()} {booking.appointment_date} {booking.appointment_time.strftime('%I:%M %p')}"
            send_sms(getattr(booking.created_by, 'phone_number', None), sms_body)
        except Exception:
            pass



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
            continue


def send_drip_message(message_template, recipient_email, recipient_phone, context):
    """Send a drip campaign message (both email and SMS)"""
    email_sent = False
    sms_sent = False
    
    # Send email
    try:
        subject, body = message_template.render_email(context)
        send_mail(
            subject=subject,
            message=strip_tags(body),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            html_message=body,
            fail_silently=False,
        )
        email_sent = True
        
        CommunicationLog.objects.create(
            recipient_email=recipient_email,
            communication_type='email',
            message_template=message_template,
            subject=subject,
            body=body,
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