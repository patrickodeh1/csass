from django.db import models
import os
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin, Group
from django.core.validators import MinValueValidator
from django.utils import timezone
from decimal import Decimal
from datetime import datetime, timedelta, time
import uuid


class UserManager(BaseUserManager):
    """Custom user manager for email-based authentication"""
    
    def create_user(self, email, username, password=None, **extra_fields):
        """Create and save a regular user"""
        if not email:
            raise ValueError('Users must have an email address')
        if not username:
            raise ValueError('Users must have a username')
        
        email = self.normalize_email(email)
        user = self.model(email=email, username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, username, password=None, **extra_fields):
        """Create and save a superuser"""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True')
        
        return self.create_user(email, username, password, **extra_fields)

# ============================================================
# CUSTOM USER MODEL
# ============================================================

class User(AbstractBaseUser, PermissionsMixin):
    """Custom User model with email and username authentication"""
    
    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    plain_text_password = models.CharField(max_length=255, blank=True, null=True)
    
    #payment details
    paypal_email = models.EmailField(blank=True, null=True)
    bitcoin_wallet_address = models.CharField(max_length=255, blank=True, null=True)
    ACH_bank_name = models.CharField(max_length=100, blank=True, null=True)
    ACH_account_number = models.CharField(max_length=50, blank=True, null=True)
    ACH_routing_number = models.CharField(max_length=50, blank=True, null = True)

    # Additional fields
    employee_id = models.CharField(max_length=20, unique=True, null=True, blank=True)
    phone_number = models.CharField(max_length=20)
    commission_rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    is_active_salesman = models.BooleanField(default=False)
    hire_date = models.DateField(null=True)
    
    # Status fields
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    
    # Timestamps
    date_joined = models.DateTimeField(default=timezone.now)
    last_login = models.DateTimeField(null=True, blank=True)
    
    # Password reset
    password_reset_token = models.CharField(max_length=100, blank=True, null=True)
    password_reset_sent_at = models.DateTimeField(null=True, blank=True)
    
    # Login attempts tracking
    failed_login_attempts = models.IntegerField(default=0)
    last_failed_login = models.DateTimeField(null=True, blank=True)
    
    objects = UserManager()
    
    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email', 'first_name', 'last_name']
    
    class Meta:
        db_table = 'users'
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        ordering = ['last_name', 'first_name']
    
    def __str__(self):
        return f"{self.get_full_name()} ({self.username})"

    def get_full_name(self):
        """Return the first_name plus the last_name, with a space in between"""
        return f"{self.first_name} {self.last_name}".strip()
    
    def get_short_name(self):
        """Return the short name for the user"""
        return self.first_name
    
    def get_commission_rate(self):
        """Get user's commission rate or system default"""
        if self.commission_rate:
            return self.commission_rate
        return SystemConfig.get_config().default_commission_rate
    
    def has_group(self, group_name):
        """Check if user belongs to a group"""
        return self.groups.filter(name=group_name).exists()
    
    def get_roles(self):
        """Get list of user's role names"""
        return list(self.groups.values_list('name', flat=True))
    
    def reset_failed_login_attempts(self):
        """Reset failed login attempts counter"""
        self.failed_login_attempts = 0
        self.last_failed_login = None
        self.save(update_fields=['failed_login_attempts', 'last_failed_login'])
    
    def increment_failed_login(self):
        """Increment failed login attempts"""
        self.failed_login_attempts += 1
        self.last_failed_login = timezone.now()
        self.save(update_fields=['failed_login_attempts', 'last_failed_login'])
    
    def is_account_locked(self):
        """Check if account is locked due to too many failed attempts"""
        from django.conf import settings
        max_attempts = getattr(settings, 'MAX_LOGIN_ATTEMPTS', 5)
        
        if self.failed_login_attempts >= max_attempts:
            # Check if 30 minutes have passed since last failed attempt
            if self.last_failed_login:
                time_since_last_fail = timezone.now() - self.last_failed_login
                if time_since_last_fail < timedelta(minutes=30):
                    return True
                else:
                    # Auto-reset after 30 minutes
                    self.reset_failed_login_attempts()
        return False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._original_is_active_salesman = self.is_active_salesman

    def get_available_slots_for_date(self, date):
        """Get available time slots for a specific date"""
        date = date.date()
        return self.available_timeslots.filter(
            date=date,
            is_active=True
        ).order_by('start_time')

        
class Client(models.Model):
    business_name = models.CharField(max_length=200, help_text="business name")
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True, null=True)
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=20)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='clients_created')
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['phone_number']),
            models.Index(fields=['email', 'phone_number']),
        ]
    
    def __str__(self):
        return f"{self.first_name} {self.last_name}".strip() if self.last_name else self.first_name
    
    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip() if self.last_name else self.first_name
    
    def get_booking_count(self):
        return self.bookings.exclude(status='canceled').count()

    
class Booking(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('completed', 'Completed'),
        ('canceled', 'Canceled'),
        ('no_show', 'No Show'),
        ('declined', 'Declined'),
    ]
    
    TYPE_CHOICES = [
        ('zoom', 'Zoom'),
        ('in_person', 'In-Person'),
    ]
    
    CANCELLATION_REASONS = [
        ('client_request', 'Client Requested Cancellation'),
        ('no_show', 'Client No-Show'),
        ('salesman_unavailable', 'Salesman Unavailable'),
        ('duplicate', 'Duplicate Booking'),
        ('other', 'Other'),
    ]
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name='bookings')
    salesman = models.ForeignKey(User, on_delete=models.PROTECT, related_name='bookings')
    appointment_date = models.DateField()
    appointment_time = models.TimeField()
    duration_minutes = models.IntegerField(default=60)
    appointment_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    meeting_address = models.CharField(max_length=255, blank=True)
    zoom_link = models.URLField(blank=True)
    location = models.CharField(max_length=255, blank=True, help_text="State or City of salesman for in-person appointments")

    notes = models.TextField(blank=True)
    commission_amount = models.DecimalField(max_digits=10, decimal_places=2)
    audio_file = models.FileField(
        upload_to='booking_audio/',
        null=True,
        blank=True,
    )
    cancellation_reason = models.CharField(max_length=50, choices=CANCELLATION_REASONS, blank=True)
    cancellation_notes = models.TextField(blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)
    canceled_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name='bookings_canceled')
    is_locked = models.BooleanField(default=False)
    payroll_period = models.ForeignKey('PayrollPeriod', on_delete=models.PROTECT, null=True, blank=True, related_name='bookings')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='bookings_created')
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name='bookings_updated')
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name='bookings_approved')
    declined_at = models.DateTimeField(null=True, blank=True)
    declined_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name='bookings_declined')
    decline_reason = models.TextField(blank=True)
    available_slot = models.ForeignKey(
        'AvailableTimeSlot', 
        on_delete=models.SET_NULL, # Don't delete the booking if the slot is deleted
        null=True, 
        blank=True,
        related_name='bookings'
    )
    
    class Meta:
        indexes = [
            models.Index(fields=['appointment_date']),
            models.Index(fields=['created_at']),  # CRITICAL: Added for payroll filtering by creation date
            models.Index(fields=['salesman']),
            models.Index(fields=['status']),
            models.Index(fields=['salesman', 'appointment_date', 'status']),
            models.Index(fields=['created_by', 'created_at']),  # CRITICAL: Added for remote agent commission queries
            models.Index(fields=['payroll_period']),
        ]
        ordering = ['appointment_date', 'appointment_time']
    
    def __str__(self):
        return f"{self.client} with {self.salesman.get_full_name()} on {self.appointment_date}"
    
    def counts_for_commission(self):
        """Check if booking counts for commission - must be confirmed or completed"""
        return self.status in ['confirmed', 'completed']
    
    def can_be_approved(self):
        """Check if booking can be approved"""
        return self.status == 'pending' and not self.is_in_past()
    
    def can_be_declined(self):
        """Check if booking can be declined"""
        return self.status == 'pending'

   
    
    def is_editable(self):
        """Check if booking can be edited"""
        if self.is_locked:
            return False
        if self.is_in_past():
            return False
        return True
    
    def is_in_past(self):
        """Check if appointment has passed"""
        appt_datetime = datetime.combine(self.appointment_date, self.appointment_time)
        return timezone.make_aware(appt_datetime) < timezone.now()
    
    def save(self, *args, **kwargs):
             # Set commission amount if not set
        if not self.commission_amount:
            # Commission only applies to bookings created by remote agents
            if self.created_by and self.created_by.groups.filter(name='remote_agent').exists():
                config = SystemConfig.get_config()
                if self.appointment_type == 'zoom':
                    self.commission_amount = config.default_commission_rate_zoom
                else:  # in_person
                    self.commission_amount = config.default_commission_rate_in_person
            else:
                self.commission_amount = Decimal('0.00') 
        is_new = self.pk is None
        new_status = self.status
        old_status = self.__original_status if not is_new else None
        
        super().save(*args, **kwargs)
        # Always evaluate slot activation on create, and on any status change
        if is_new:
            self._handle_slot_activation(new_status)
        elif new_status != old_status:
            self._handle_slot_activation(new_status)
            
        # Update the original status for next save
        self.__original_status = self.status
        # ---------------------------------------------------------------------
    
    def __str__(self):
        return f"{self.client} with {self.salesman.get_full_name()} on {self.appointment_date}"

    def _handle_slot_activation(self, new_status):
        """Logic to activate or deactivate the associated AvailableTimeSlot."""
        if not self.available_slot:
            return # Exit if no slot is linked
            
        slot = self.available_slot
        
        # 1. Statuses that DEACTIVATE the slot (i.e., the slot is used)
        #    Deactivate immediately for pending to prevent double-booking; keep inactive for confirmed/completed
        if new_status in ['pending', 'confirmed', 'completed']:
            if slot.is_active:
                slot.is_active = False
                slot.save(update_fields=['is_active'])
                
        # 2. Statuses that ACTIVATE the slot (i.e., the slot is released)
        elif new_status in ['canceled', 'declined', 'no_show']:
            if not slot.is_active:
                slot.is_active = True
                slot.save(update_fields=['is_active'])

    def conflicts_with_booking(self):
        """Check if this unavailability conflicts with any confirmed bookings"""
        return Booking.objects.filter(
            salesman=self.salesman,
            status='confirmed',
            appointment_date__gte=self.start_date,
            appointment_date__lte=self.end_date,
            appointment_time__gte=self.start_time,
        ).exists()
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Check if the instance has a primary key (meaning it's loaded from DB)
        # If the instance has been initialized and has a status, set the original status.
        # This fixes the issue when Django loads the object from the database.
        if 'status' in self.__dict__:
            self.__original_status = self.status
        else:
            # Fallback for new objects (where status might not be set yet)
            self.__original_status = self.status if self.status else 'pending'

        

class PayrollPeriod(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('finalized', 'Finalized'),
    ]
    
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    finalized_at = models.DateTimeField(null=True, blank=True)
    finalized_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='payrolls_finalized')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['start_date']),
            models.Index(fields=['status']),
        ]
        unique_together = ['start_date', 'end_date']
        ordering = ['-start_date']
    
    def __str__(self):
        return f"Week of {self.start_date.strftime('%b %d')} - {self.end_date.strftime('%b %d, %Y')}"
    
    def get_week_label(self):
        return self.__str__()
    
    def calculate_commissions(self):
        """Calculate total commissions for all users in this period"""
        bookings = self.bookings.filter(
            status__in=['confirmed', 'completed']
        ).values('salesman').annotate(
            total=models.Sum('commission_amount'),
            count=models.Count('id')
        )
        
        return {b['salesman']: {'total': b['total'], 'count': b['count']} for b in bookings}

class PayrollAdjustment(models.Model):
    ADJUSTMENT_TYPES = [
        ('bonus', 'Bonus'),
        ('penalty', 'Penalty'),
        ('correction', 'Correction'),
        ('cancellation_after_finalized', 'Cancellation After Finalized'),
    ]
    
    payroll_period = models.ForeignKey(PayrollPeriod, on_delete=models.PROTECT, null=True, blank=True, related_name='adjustments')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='payroll_adjustments')
    booking = models.ForeignKey(Booking, on_delete=models.PROTECT, null=True, blank=True, related_name='adjustments')
    adjustment_type = models.CharField(max_length=50, choices=ADJUSTMENT_TYPES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='adjustments_created')
    
    class Meta:
        indexes = [
            models.Index(fields=['payroll_period']),
            models.Index(fields=['user']),
        ]
    
    def __str__(self):
        return f"{self.adjustment_type} - {self.user.get_full_name()} - ${self.amount}"



class SystemConfig(models.Model):
    # Singleton pattern - only one record with id=1
    company_name = models.CharField(max_length=200, default='Revenue Acceleration Unit')
    timezone = models.CharField(max_length=50, default='UTC')
    default_commission_rate_in_person = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('50.00'))
    default_commission_rate_zoom = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('30.00'))
    buffer_time_minutes = models.IntegerField(default=30)
    zoom_link = models.URLField(
        blank=True,
        default='https://us04web.zoom.us/j/77703295752?pwd=n8xdNGWmJa7mFnn1JlFwUw0C0jXNH0.1'
        )
    zoom_enabled = models.BooleanField(default=True, help_text="Enable/disable Zoom appointment bookings")
    in_person_enabled = models.BooleanField(default=True, help_text="Enable/disable in-person appointment bookings")
    reminder_lead_time_hours = models.IntegerField(default=24)
    max_advance_booking_days = models.IntegerField(default=90)
    min_advance_booking_hours = models.IntegerField(default=2)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    @classmethod
    def get_config(cls):
        """Get or create the singleton config without leaking DoesNotExist."""
        # Try fast path
        config = cls.objects.filter(id=1).first()
        if config:
            return config
        # Create deterministically with id=1
        obj = cls(id=1)
        try:
            obj.save()
        except Exception:
            # In case of race condition, fetch again
            existing = cls.objects.filter(id=1).first()
            if existing:
                return existing
            raise
        return obj
    
    def save(self, *args, **kwargs):
        self.id = 1
        
        # For updates only (skip on initial create to avoid DoesNotExist)
        if not self._state.adding and self.pk and SystemConfig.objects.filter(pk=self.pk).exists():
            original = SystemConfig.objects.get(pk=self.pk)
            today = timezone.now().date()
            
            # If zoom was enabled but now disabled, deactivate zoom slots
            if original.zoom_enabled and not self.zoom_enabled:
                AvailableTimeSlot.objects.filter(
                    appointment_type='zoom',
                    is_active=True
                ).update(is_active=False)
            
            # If zoom was disabled but now enabled, reactivate FUTURE zoom slots
            elif not original.zoom_enabled and self.zoom_enabled:
                AvailableTimeSlot.objects.filter(
                    appointment_type='zoom',
                    is_active=False,
                    date__gte=today  # Only reactivate current/future slots
                ).exclude(
                    bookings__status__in=['pending', 'confirmed', 'completed']
                ).update(is_active=True)
            
            # If in_person was enabled but now disabled, deactivate in-person slots
            if original.in_person_enabled and not self.in_person_enabled:
                AvailableTimeSlot.objects.filter(
                    appointment_type='in_person',
                    is_active=True
                ).update(is_active=False)
            
            # If in_person was disabled but now enabled, reactivate FUTURE in-person slots
            elif not original.in_person_enabled and self.in_person_enabled:
                AvailableTimeSlot.objects.filter(
                    appointment_type='in_person',
                    is_active=False,
                    date__gte=today  # Only reactivate current/future slots
                ).exclude(
                    bookings__status__in=['pending', 'confirmed', 'completed']
                ).update(is_active=True)
        
        super().save(*args, **kwargs)
        
    def __str__(self):
        return f"System Configuration - {self.company_name}"

class AuditLog(models.Model):
    ACTION_CHOICES = [
        ('create', 'Create'),
        ('update', 'Update'),
        ('delete', 'Delete'),
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('finalize', 'Finalize'),
        ('adjust', 'Adjust'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    entity_type = models.CharField(max_length=50)
    entity_id = models.IntegerField()
    changes = models.JSONField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['timestamp']),
            models.Index(fields=['user']),
            models.Index(fields=['entity_type']),
            models.Index(fields=['entity_type', 'entity_id']),
        ]
        ordering = ['-timestamp']
    
    def __str__(self):
        user_str = self.user.get_full_name() if self.user else 'System'
        return f"{user_str} - {self.action} {self.entity_type} ({self.timestamp})"


class AvailabilityCycle(models.Model):
    """Represents a 2-week availability period for all salesmen."""
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-start_date']
        indexes = [
            models.Index(fields=['start_date', 'end_date', 'is_active'])
        ]

    def __str__(self):
        return f"{self.start_date.strftime('%b %d')} - {self.end_date.strftime('%b %d, %Y')}"

    @classmethod
    def get_current_cycle(cls):
        """Return active cycle or create one covering the next 14 days."""
        today = timezone.now().date()
        active = cls.objects.filter(start_date__lte=today, end_date__gte=today, is_active=True).first()
        if not active:
            start_date = today
            end_date = today + timedelta(days=13)
            active = cls.objects.create(start_date=start_date, end_date=end_date)
        return active


class AvailableTimeSlot(models.Model):
    """Admin-defined or auto-generated time slots for bookings."""
    APPOINTMENT_TYPE_CHOICES = [
        ('zoom', 'Zoom'),
        ('in_person', 'In-Person'),
    ]

    cycle = models.ForeignKey(AvailabilityCycle, on_delete=models.CASCADE, related_name='slots', null=True, blank=True)
    salesman = models.ForeignKey(User, on_delete=models.CASCADE, related_name='available_timeslots')
    date = models.DateField()
    start_time = models.TimeField()
    appointment_type = models.CharField(max_length=20, choices=APPOINTMENT_TYPE_CHOICES)
    is_active = models.BooleanField(default=True)
    is_booked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='timeslots_created')

    class Meta:
        ordering = ['salesman', 'date', 'start_time']
        unique_together = ('salesman', 'date', 'start_time', 'appointment_type')
        indexes = [
            models.Index(fields=['salesman', 'date', 'appointment_type', 'is_active']),
        ]
    
    def is_time_in_slot(self, check_time):
        """
        Check if a given time falls within this slot.
        Since all slots are 30-minute intervals, we just check if the time matches the start_time.
        """
        return self.start_time == check_time

    def __str__(self):
        return f"{self.salesman.get_full_name()} - {self.date.strftime('%b %d, %Y')} {self.start_time} ({self.get_appointment_type_display()})"


class MessageTemplate(models.Model):
    """Store customizable email and SMS templates"""
    MESSAGE_TYPES = [
        ('booking_approved_agent', 'Booking Approved - To Agent'),
        ('booking_approved_client', 'Booking Approved - To Client'),
        ('booking_approved_salesman', 'Booking Approved - To Salesman'),
        ('booking_reminder_client', 'Booking Reminder - To Client'),
        ('booking_reminder_salesman', 'Booking Reminder - To Salesman'),
        ('ad_day_1', 'Attended Drip - Day 1'),
        ('ad_day_7', 'Attended Drip - Day 7'),
        ('ad_day_14', 'Attended Drip - Day 14'),
        ('ad_day_21', 'Attended Drip - Day 21'),
        ('dna_day_1', 'Did Not Attend Drip - Day 1'),
        ('dna_day_7', 'Did Not Attend Drip - Day 7'),
        ('dna_day_30', 'Did Not Attend Drip - Day 30'),
        ('dna_day_60', 'Did Not Attend Drip - Day 60'),
        ('dna_day_90', 'Did Not Attend Drip - Day 90'),
    ]
    
    message_type = models.CharField(max_length=50, choices=MESSAGE_TYPES, unique=True)
    email_subject = models.CharField(max_length=200, blank=True)
    email_body = models.TextField(help_text='HTML email template. Available variables: {client_name}, {salesman_name}, {business_name}, {appointment_date}, {appointment_time}, {company_name}')
    sms_body = models.TextField(max_length=320, help_text='SMS message (max 320 chars). Same variables as email.')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['message_type']
    
    def __str__(self):
        return f"{self.get_message_type_display()}"
    
    def render_email(self, context):
        """Render email with context variables"""
        subject = self.email_subject.format(**context)
        body = self.email_body.format(**context)
        return subject, body
    
    def render_sms(self, context):
        """Render SMS with context variables"""
        return self.sms_body.format(**context)


class DripCampaign(models.Model):
    """Track drip campaign progress for clients"""
    CAMPAIGN_TYPES = [
        ('attended', 'Attended (AD) - 21 Days'),
        ('did_not_attend', 'Did Not Attend (DNA) - 90 Days'),
    ]
    
    booking = models.ForeignKey('Booking', on_delete=models.CASCADE, related_name='drip_campaigns')
    campaign_type = models.CharField(max_length=20, choices=CAMPAIGN_TYPES)
    started_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    is_stopped = models.BooleanField(default=False)
    stopped_at = models.DateTimeField(null=True, blank=True)
    stopped_by = models.ForeignKey('User', null=True, blank=True, on_delete=models.SET_NULL, related_name='stopped_campaigns')
    
    class Meta:
        ordering = ['-started_at']
    
    def __str__(self):
        return f"{self.get_campaign_type_display()} - {self.booking.client.get_full_name()}"
    
    def stop_campaign(self, user):
        """Stop all future messages in this campaign"""
        self.is_active = False
        self.is_stopped = True
        self.stopped_at = timezone.now()
        self.stopped_by = user
        self.save()
        
        # Cancel all pending scheduled messages
        self.scheduled_messages.filter(status='pending').update(status='canceled')


class ScheduledMessage(models.Model):
    """Individual scheduled message in a drip campaign"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
        ('canceled', 'Canceled'),
    ]
    
    drip_campaign = models.ForeignKey(DripCampaign, on_delete=models.CASCADE, related_name='scheduled_messages')
    message_template = models.ForeignKey(MessageTemplate, on_delete=models.CASCADE)
    recipient_email = models.EmailField()
    recipient_phone = models.CharField(max_length=20, blank=True)
    scheduled_for = models.DateTimeField()
    sent_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error_message = models.TextField(blank=True)
    
    class Meta:
        ordering = ['scheduled_for']
    
    def __str__(self):
        return f"{self.message_template.message_type} to {self.recipient_email} on {self.scheduled_for}"
    
    def send_message(self):
        """Send this scheduled message"""
        from .utils import send_drip_message
        
        if self.status != 'pending':
            return False
        
        if not self.drip_campaign.is_active or self.drip_campaign.is_stopped:
            self.status = 'canceled'
            self.save()
            return False
        
        try:
            booking = self.drip_campaign.booking
            context = {
                'client_name': booking.client.get_full_name(),
                'salesman_name': booking.salesman.get_full_name(),
                'business_name': booking.client.business_name,
                'appointment_date': booking.appointment_date.strftime('%B %d, %Y'),
                'appointment_time': booking.appointment_time.strftime('%I:%M %p'),
                'company_name': SystemConfig.get_config().company_name,
            }
            
            success = send_drip_message(
                message_template=self.message_template,
                recipient_email=self.recipient_email,
                recipient_phone=self.recipient_phone,
                context=context
            )
            
            if success:
                self.status = 'sent'
                self.sent_at = timezone.now()
            else:
                self.status = 'failed'
                self.error_message = 'Failed to send message'
            
            self.save()
            return success
            
        except Exception as e:
            self.status = 'failed'
            self.error_message = str(e)
            self.save()
            return False


class CommunicationLog(models.Model):
    """Log all communications sent (email + SMS)"""
    COMM_TYPES = [
        ('email', 'Email'),
        ('sms', 'SMS'),
    ]
    
    booking = models.ForeignKey('Booking', null=True, blank=True, on_delete=models.CASCADE, related_name='communications')
    recipient_email = models.EmailField(blank=True)
    recipient_phone = models.CharField(max_length=20, blank=True)
    communication_type = models.CharField(max_length=10, choices=COMM_TYPES)
    message_template = models.ForeignKey(MessageTemplate, null=True, blank=True, on_delete=models.SET_NULL)
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField()
    sent_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, default='sent')
    error_message = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-sent_at']
    
    def __str__(self):
        return f"{self.communication_type} to {self.recipient_email or self.recipient_phone} at {self.sent_at}"
