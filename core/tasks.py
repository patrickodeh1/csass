from celery import shared_task
from django.db import transaction
from .models import User, AvailabilityCycle
from .utils import generate_timeslots_for_cycle


@shared_task
def generate_timeslots_async(salesman_id):
    """
    Asynchronously generate timeslots for a specific salesman.
    This task runs in the background after user creation.
    """
    try:
        salesman = User.objects.get(id=salesman_id, is_active_salesman=True)
        
        # Ensure an AvailabilityCycle exists
        cycle = AvailabilityCycle.get_current_cycle()
        
        # Generate timeslots for this specific salesman
        generate_timeslots_for_cycle(salesman=salesman)
        
        return f"Successfully generated timeslots for salesman {salesman.get_full_name()}"
        
    except User.DoesNotExist:
        return f"Salesman with ID {salesman_id} not found or not active"
    except Exception as e:
        return f"Error generating timeslots for salesman {salesman_id}: {str(e)}"


@shared_task
def cleanup_old_slots_async():
    """
    Asynchronously clean up old unused slots.
    This can be run as a periodic task.
    """
    from .utils import cleanup_old_slots, mark_past_slots_inactive, mark_elapsed_today_slots_inactive
    
    try:
        # Clean up slots older than 2 weeks
        old_count = cleanup_old_slots(weeks=2)
        
        # Mark past slots as inactive
        past_count = mark_past_slots_inactive()
        
        # Mark today's elapsed slots as inactive
        today_count = mark_elapsed_today_slots_inactive()
        
        return f"Cleanup completed: {old_count} old slots, {past_count} past slots, {today_count} today's elapsed slots"
        
    except Exception as e:
        return f"Error during slot cleanup: {str(e)}"
