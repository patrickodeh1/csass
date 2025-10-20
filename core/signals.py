from django.db.models.signals import post_save, post_delete
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver
from django.db import transaction
from .models import User, Booking, PayrollPeriod, AvailableTimeSlot, AuditLog, Client, PayrollAdjustment, AvailabilityCycle
from .utils import generate_timeslots_for_cycle
from .tasks import generate_timeslots_async
from django.utils import timezone
import logging
import threading
import json

def get_client_ip(request):
    """Get client IP from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

def create_audit_log(user, action, entity_type, entity_id, changes, request=None):
    """Create audit log entry"""
    ip_address = get_client_ip(request) if request else None
    user_agent = request.META.get('HTTP_USER_AGENT', '') if request else ''
    
    AuditLog.objects.create(
        user=user,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        changes=changes,
        ip_address=ip_address,
        user_agent=user_agent
    )

@receiver(post_save, sender=Booking)
def log_booking_changes(sender, instance, created, **kwargs):
    """Log booking creates/updates"""
    action = 'create' if created else 'update'
    changes = {
        'client': str(instance.client),
        'salesman': instance.salesman.get_full_name(),
        'date': str(instance.appointment_date),
        'time': str(instance.appointment_time),
        'type': instance.appointment_type,
        'status': instance.status,
    }
    
    create_audit_log(
        user=instance.created_by if created else instance.updated_by,
        action=action,
        entity_type='Booking',
        entity_id=instance.id,
        changes=changes
        )

@receiver(post_save, sender=User)
def log_user_changes(sender, instance, created, **kwargs):
    """Log user creation"""
    if created and not instance.is_superuser:
        changes = {
            'username': instance.username,
            'email': instance.email,
            'employee_id': instance.employee_id,
            'name': instance.get_full_name(),
        }
        create_audit_log(
            user=None,  # System action
            action='create',
            entity_type='User',
            entity_id=instance.id,
            changes=changes
        )

@receiver(post_save, sender=User)
def auto_generate_timeslots_for_salesman(sender, instance, created, **kwargs):
    """
    Automatically generate timeslots for a new salesman or when a user becomes an active salesman.
    Uses async Celery task to avoid blocking the HTTP response.
    """
    logger = logging.getLogger(__name__)
    
    # Only proceed if the user is an active salesman
    if instance.is_active_salesman:
        logger.info(f"User {instance.id} ({instance.get_full_name()}) is an active salesman. Created: {created}")
        
        # For new users, always generate slots if they're active salesmen
        # For existing users, check if is_active_salesman was just enabled
        should_generate = created
        
        if not created:
            # Check if is_active_salesman was just changed to True
            try:
                original_value = getattr(instance, '_original_is_active_salesman', False)
                should_generate = not original_value and instance.is_active_salesman
                logger.info(f"Existing user {instance.id}: original={original_value}, current={instance.is_active_salesman}, should_generate={should_generate}")
            except AttributeError:
                # Fallback: if we can't determine the original state, generate slots
                should_generate = True
                logger.info(f"Could not determine original state for user {instance.id}, generating slots")
        
        if should_generate:
            logger.info(f"Generating slots for salesman {instance.id} ({instance.get_full_name()})")
            
            # Ensure an AvailabilityCycle exists
            AvailabilityCycle.get_current_cycle() # This will create a cycle if none exists
            
            # Schedule async slot generation after the transaction commits
            # This ensures the user is fully saved before generating slots
            def schedule_slot_generation():
                try:
                    generate_timeslots_async.delay(instance.id)
                    logger.info(f"Scheduled async slot generation for user {instance.id}")
                except Exception as e:
                    # Fallback: if Celery/broker is unavailable, do it in a background thread
                    logger.warning(f"Celery unavailable for slot generation (user {instance.id}): {e}. Falling back to local thread.")
                    def _local_generate():
                        try:
                            # Ensure user still exists and is active salesman
                            user = User.objects.filter(id=instance.id, is_active_salesman=True).first()
                            if not user:
                                logger.warning(f"User {instance.id} not found or not active salesman in fallback")
                                return
                            AvailabilityCycle.get_current_cycle()
                            generate_timeslots_for_cycle(salesman=user)
                            logger.info(f"Successfully generated slots for user {instance.id} via fallback")
                        except Exception:
                            logger.exception("Local slot generation fallback failed")
                    threading.Thread(target=_local_generate, daemon=True).start()
            
            transaction.on_commit(schedule_slot_generation)

@receiver(post_save, sender=Client)
def log_client_changes(sender, instance, created, **kwargs):
    """Log client creation"""
    if created:
        changes = {
            'name': instance.get_full_name(),
            'email': instance.email,
            'phone': instance.phone_number,
        }
        create_audit_log(
            user=instance.created_by,
            action='create',
            entity_type='Client',
            entity_id=instance.id,
            changes=changes
        )

@receiver(post_save, sender=AvailableTimeSlot)
def log_available_time_slot_changes(sender, instance, created, **kwargs):
    """Log available time slot changes - FIXED"""
    if created:
        changes = {
            'salesman': instance.salesman.get_full_name(),
            'date': str(instance.date),
            'start_time': str(instance.start_time),
            'appointment_type': instance.get_appointment_type_display(),
        }
        create_audit_log(
            user=instance.created_by,
            action='create',
            entity_type='AvailableTimeSlot',
            entity_id=instance.id,
            changes=changes
        )

@receiver(post_save, sender=PayrollPeriod)
def log_payroll_finalize(sender, instance, created, **kwargs):
    """Log payroll finalization"""
    if not created and instance.status == 'finalized' and instance.finalized_by:
        changes = {
            'start_date': str(instance.start_date),
            'end_date': str(instance.end_date),
            'status': instance.status,
        }
        create_audit_log(
            user=instance.finalized_by,
            action='finalize',
            entity_type='PayrollPeriod',
            entity_id=instance.id,
            changes=changes
        )

@receiver(post_save, sender=PayrollAdjustment)
def log_payroll_adjustment(sender, instance, created, **kwargs):
    """Log payroll adjustments"""
    if created:
        changes = {
            'user': instance.user.get_full_name(),
            'type': instance.adjustment_type,
            'amount': str(instance.amount),
            'reason': instance.reason,
        }
        create_audit_log(
            user=instance.created_by,
            action='adjust',
            entity_type='PayrollAdjustment',
            entity_id=instance.id,
            changes=changes
        )

@receiver(user_logged_in)
def log_user_login(sender, request, user, **kwargs):
    """Log user login"""
    create_audit_log(
        user=user,
        action='login',
        entity_type='User',
        entity_id=user.id,
        changes={'username': user.username},
        request=request
    )

@receiver(user_logged_out)
def log_user_logout(sender, request, user, **kwargs):
    """Log user logout"""
    if user:
        create_audit_log(
            user=user,
            action='logout',
            entity_type='User',
            entity_id=user.id,
            changes={'username': user.username},
            request=request
        )

@receiver(post_delete, sender=Booking)
def log_booking_delete(sender, instance, **kwargs):
    """Log booking deletion"""
    changes = {
        'client': str(instance.client),
        'salesman': instance.salesman.get_full_name(),
        'date': str(instance.appointment_date),
        'status': instance.status,
    }
    create_audit_log(
        user=None,
        action='delete',
        entity_type='Booking',
        entity_id=instance.id,
        changes=changes
    )
