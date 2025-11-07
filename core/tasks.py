from celery import shared_task
from django.utils import timezone
from datetime import timedelta, datetime, time
from .sheets_sync import GoogleSheetsSyncService

import logging

logger = logging.getLogger(__name__)


@shared_task
def generate_timeslots_async(salesman_id):
    """
    Asynchronously generate timeslots for a specific salesman.
    Called when a new salesman is created or activated.
    """
    from .models import User
    from .utils import generate_timeslots_for_cycle
    
    try:
        salesman = User.objects.get(id=salesman_id, is_active_salesman=True)
        generate_timeslots_for_cycle(salesman=salesman)
        logger.info(f"Successfully generated timeslots for {salesman.get_full_name()}")
        return f"Successfully generated timeslots for {salesman.get_full_name()}"
    except User.DoesNotExist:
        logger.error(f"Salesman with ID {salesman_id} not found or not active")
        return f"Salesman with ID {salesman_id} not found"
    except Exception as e:
        logger.error(f"Error generating timeslots for salesman {salesman_id}: {str(e)}")
        return f"Error: {str(e)}"


@shared_task
def generate_daily_timeslots():
    """
    CRITICAL: Runs at midnight EST to generate the next day's timeslots.
    Generates slots ONLY for dates that don't already have slots.
    Uses each salesman's individual settings:
    - booking_advance_days
    - booking_weekdays
    - booking_start_time
    - booking_end_time
    """
    from .models import User, AvailabilityCycle, AvailableTimeSlot, SystemConfig
    
    logger.info("=" * 80)
    logger.info("MIDNIGHT TIMESLOT GENERATION STARTED")
    logger.info("=" * 80)
    
    # Get system config for enabled meeting types
    config = SystemConfig.get_config()
    enabled_types = []
    if config.zoom_enabled:
        enabled_types.append('zoom')
    if config.in_person_enabled:
        enabled_types.append('in_person')
    
    if not enabled_types:
        logger.warning("No meeting types enabled in system config. Skipping generation.")
        return "No meeting types enabled"
    
    logger.info(f"Enabled meeting types: {enabled_types}")
    
    # Get or create current cycle
    cycle = AvailabilityCycle.get_current_cycle()
    logger.info(f"Using cycle: {cycle.start_date} to {cycle.end_date}")
    
    # Get all active salesmen
    salesmen = User.objects.filter(is_active_salesman=True, is_active=True)
    logger.info(f"Found {salesmen.count()} active salesmen")
    
    total_created = 0
    total_skipped = 0
    
    for salesman in salesmen:
        try:
            created, skipped = generate_timeslots_for_salesman_rolling(salesman, cycle, enabled_types)
            total_created += created
            total_skipped += skipped
            logger.info(
                f"✅ {salesman.get_full_name()}: Created {created} slots, Skipped {skipped} existing dates"
            )
        except Exception as e:
            logger.error(f"❌ Error for {salesman.get_full_name()}: {e}")
            continue
    
    logger.info("=" * 80)
    logger.info(f"MIDNIGHT GENERATION COMPLETE: {total_created} slots created, {total_skipped} dates skipped")
    logger.info("=" * 80)
    
    return f"Created {total_created} slots, skipped {total_skipped} dates"


def generate_timeslots_for_salesman_rolling(salesman, cycle, enabled_types):
    """
    Generate timeslots for a single salesman using rolling window approach.
    Only generates slots for dates that don't already have ANY slots.
    
    Args:
        salesman: User object
        cycle: AvailabilityCycle object
        enabled_types: List of enabled appointment types ['zoom', 'in_person']
    
    Returns:
        tuple: (slots_created, dates_skipped)
    """
    from .models import AvailableTimeSlot
    
    today = timezone.now().date()
    
    # Calculate the furthest date based on salesman's booking_advance_days
    days_ahead = salesman.booking_advance_days
    furthest_date = today + timedelta(days=days_ahead - 1)
    
    logger.info(
        f"  → Generating for {salesman.get_full_name()}: "
        f"Today={today}, Furthest={furthest_date} ({days_ahead} days ahead)"
    )
    
    # Parse enabled weekdays from salesman settings
    enabled_weekdays = set()
    if salesman.booking_weekdays:
        try:
            enabled_weekdays = set(int(day.strip()) for day in salesman.booking_weekdays.split(',') if day.strip())
        except ValueError:
            logger.warning(f"  ⚠️  Invalid weekday config for {salesman.get_full_name()}, using Mon-Fri")
            enabled_weekdays = {0, 1, 2, 3, 4}
    else:
        enabled_weekdays = {0, 1, 2, 3, 4}
    
    logger.info(f"  → Enabled weekdays: {enabled_weekdays}")
    logger.info(f"  → Time range: {salesman.booking_start_time} - {salesman.booking_end_time}")
    
    slots_to_create = []
    dates_skipped = 0
    current_date = today
    
    while current_date <= furthest_date:
        # Skip if not an enabled weekday
        if current_date.weekday() not in enabled_weekdays:
            current_date += timedelta(days=1)
            continue
        
        # CRITICAL: Check if ANY slots exist for this salesman on this date
        existing_slots_count = AvailableTimeSlot.objects.filter(
            salesman=salesman,
            date=current_date
        ).count()
        
        if existing_slots_count > 0:
            # Slots already exist for this date, skip
            dates_skipped += 1
            current_date += timedelta(days=1)
            continue
        
        # Generate slots for this date
        current_dt = datetime.combine(current_date, salesman.booking_start_time)
        end_dt = datetime.combine(current_date, salesman.booking_end_time)
        
        daily_slots = 0
        while current_dt.time() < end_dt.time():
            for appt_type in enabled_types:
                slots_to_create.append(
                    AvailableTimeSlot(
                        cycle=cycle,
                        salesman=salesman,
                        date=current_date,
                        start_time=current_dt.time(),
                        appointment_type=appt_type,
                        created_by=salesman
                    )
                )
                daily_slots += 1
            current_dt += timedelta(minutes=30)
        
        logger.info(f"  → {current_date}: Generated {daily_slots} slots")
        current_date += timedelta(days=1)
    
    # Bulk create all slots
    if slots_to_create:
        created_slots = AvailableTimeSlot.objects.bulk_create(
            slots_to_create,
            ignore_conflicts=True
        )
        slots_created = len(created_slots) if created_slots else len(slots_to_create)
    else:
        slots_created = 0
    
    return slots_created, dates_skipped


@shared_task
def cleanup_past_slots_task():
    """
    Daily cleanup of past slots.
    Runs at 1 AM EST to deactivate yesterday's unused slots.
    """
    from .utils import cleanup_past_dates_slots
    
    logger.info("Starting daily slot cleanup")
    
    try:
        count = cleanup_past_dates_slots()
        logger.info(f"✅ Deactivated {count} past slots")
        return f"Deactivated {count} past slots"
    except Exception as e:
        logger.error(f"❌ Error during slot cleanup: {str(e)}")
        return f"Error: {str(e)}"


@shared_task
def cleanup_old_slots_async():
    """
    Weekly cleanup of old unused slots (older than 2 weeks).
    Marks them as inactive to keep database clean.
    """
    from .utils import cleanup_old_slots
    
    logger.info("Starting weekly old slot cleanup")
    
    try:
        count = cleanup_old_slots(weeks=2)
        logger.info(f"✅ Cleaned up {count} old slots (2+ weeks old)")
        return f"Cleaned up {count} old slots"
    except Exception as e:
        logger.error(f"❌ Error during old slot cleanup: {str(e)}")
        return f"Error: {str(e)}"
    


@shared_task
def sync_sheet_to_db_periodic():
    """
    Periodic task to sync changes from Google Sheets to DB.
    Run this every 30 seconds or as needed.
    """
    try:
        sync_service = GoogleSheetsSyncService()
        updated_count = sync_service.sync_sheet_changes_to_db()
        return f"Sheet sync completed: {updated_count} bookings updated"
    except Exception as e:
        logger.error(f"Error in periodic sheet sync: {str(e)}")
        return f"Sheet sync failed: {str(e)}"