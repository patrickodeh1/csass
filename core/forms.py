from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, PasswordResetForm, SetPasswordForm
from django.contrib.auth.models import Group
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Row, Column, Field, Div, HTML
from .models import Booking, Client, AvailableTimeSlot, PayrollAdjustment, SystemConfig, User, MessageTemplate
from datetime import datetime, timedelta
import logging
from .utils import check_booking_conflicts
from django.db import transaction

logger = logging.getLogger(__name__)

class UserForm(forms.ModelForm):
    username = forms.CharField(
        max_length=150, 
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        help_text='Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.'
    )
    first_name = forms.CharField(max_length=100, required=True, widget=forms.TextInput(attrs={'class': 'form-control'}))
    last_name = forms.CharField(max_length=100, required=True, widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={'class': 'form-control'}))
    phone_number = forms.CharField(max_length=20, required=True, widget=forms.TextInput(attrs={'class': 'form-control'}))
    commission_rate = forms.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        required=False, 
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'})
    )
    paypal_email = forms.EmailField(required=False, widget=forms.EmailInput(attrs={'class': 'form-control'}))
    bitcoin_wallet_address = forms.CharField(
        max_length=255, 
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    ACH_bank_name = forms.CharField(
        max_length=100, 
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    ACH_account_number = forms.CharField(
        max_length=50, 
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    ACH_routing_number = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    is_active_salesman = forms.BooleanField(required=False)
    hire_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}))
    
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control', 
            'placeholder': 'Leave blank to keep current password'
        }),
        help_text='Leave blank if password is set programmatically.'
    )
    password_confirm = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control', 
            'placeholder': 'Confirm password'
        }),
        label='Confirm Password'
    )
    
    roles = forms.MultipleChoiceField(
        choices=[
            ('remote_agent', 'Remote Agent'), 
            ('salesman', 'Salesman'), 
            ('admin', 'Administrator')
        ],
        widget=forms.CheckboxSelectMultiple,
        required=False
    )
    
    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'phone_number',
                  'commission_rate', 'is_active_salesman', 'hire_date', 'is_active']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        if self.instance and self.instance.pk:
            # Editing existing user
            self.fields['phone_number'].initial = self.instance.phone_number
            self.fields['commission_rate'].initial = self.instance.commission_rate
            self.fields['is_active_salesman'].initial = self.instance.is_active_salesman
            self.fields['hire_date'].initial = self.instance.hire_date
            user_groups = list(self.instance.groups.values_list('name', flat=True))
            self.fields['roles'].initial = user_groups
            self.fields['password'].help_text = 'Leave blank to keep current password.'
        else:
            # Creating new user
            self.fields['password'].help_text = 'Leave blank if password is set programmatically.'
    
    def clean_username(self):
        username = self.cleaned_data.get('username')
        if not self.instance.pk:
            if User.objects.filter(username=username).exists():
                raise forms.ValidationError("A user with this username already exists.")
        else:
            if User.objects.filter(username=username).exclude(pk=self.instance.pk).exists():
                raise forms.ValidationError("A user with this username already exists.")
        return username
    
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if not self.instance.pk:
            if User.objects.filter(email=email).exists():
                raise forms.ValidationError("A user with this email already exists.")
        else:
            if User.objects.filter(email=email).exclude(pk=self.instance.pk).exists():
                raise forms.ValidationError("A user with this email already exists.")
        return email
    
    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')
        
        if password and password_confirm:
            if password != password_confirm:
                raise forms.ValidationError("Passwords do not match.")
        elif password and not password_confirm:
            raise forms.ValidationError("Please confirm the password.")
        elif password_confirm and not password:
            raise forms.ValidationError("Please enter a password.")
        
        return cleaned_data
    
   
    def save(self, commit=True):
        user = super().save(commit=False)
        user.paypal_email = self.cleaned_data.get('paypal_email', '')
        user.bitcoin_wallet_address = self.cleaned_data.get('bitcoin_wallet_address', '')
        user.ACH_account_number = self.cleaned_data.get('ACH_account_number', '')
        user.ACH_routing_number = self.cleaned_data.get('ACH_routing_number', '')
        user.ACH_bank_name = self.cleaned_data.get('ACH_bank_name', '')
        # Set password only if provided in form data
        password = self.cleaned_data.get('password')
        
        if password:
            user.set_password(password)
            # CRITICAL: Store plain text password
            user.plain_text_password = password
        
        # Set additional fields
        user.phone_number = self.cleaned_data['phone_number']
        user.commission_rate = self.cleaned_data.get('commission_rate')
        user.is_active_salesman = self.cleaned_data.get('is_active_salesman', False)
        user.hire_date = self.cleaned_data['hire_date']
        
        # AUTO-GENERATE employee_id for new users only
        if not self.instance.pk:
            if not user.employee_id:
                with transaction.atomic():
                    # Find the highest existing employee number
                    max_attempts = 100
                    for attempt in range(max_attempts):
                        # Get all existing employee IDs that match the pattern
                        existing_ids = User.objects.filter(
                            employee_id__startswith='EMP'
                        ).values_list('employee_id', flat=True)
                        
                        # Extract numbers from existing IDs
                        numbers = []
                        for emp_id in existing_ids:
                            try:
                                num = int(emp_id.replace('EMP', ''))
                                numbers.append(num)
                            except (ValueError, AttributeError):
                                continue
                        
                        # Find next available number
                        if numbers:
                            new_number = max(numbers) + 1
                        else:
                            new_number = 1
                        
                        new_employee_id = f'EMP{new_number:05d}'
                        
                        # Check if this ID already exists (race condition protection)
                        if not User.objects.filter(employee_id=new_employee_id).exists():
                            user.employee_id = new_employee_id
                            logger.debug(f"Assigned employee_id: {user.employee_id}")
                            break
                    else:
                        # If we exhausted all attempts
                        raise forms.ValidationError("Unable to generate unique employee ID. Please try again.")
        
        if commit:
            try:
                user.save()
                logger.info(f"User saved: {user.username}, Employee ID: {user.employee_id}, Password stored: {bool(user.plain_text_password)}")
                
                # Update groups
                user.groups.clear()
                for role in self.cleaned_data.get('roles', []):
                    group, created = Group.objects.get_or_create(name=role)
                    user.groups.add(group)
            except Exception as e:
                logger.error(f"Error saving user: {str(e)}")
                raise forms.ValidationError(f"Error saving user: {str(e)}")
        
        return user



class LoginForm(AuthenticationForm):
    username = forms.CharField(
        label='Username',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Username', 'autofocus': True})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Password'})
    )
    remember_me = forms.BooleanField(required=False, initial=False, label='Remember Me')
    
    def confirm_login_allowed(self, user):
        """Check if user account is locked before allowing login"""
        if user.is_account_locked():
            raise forms.ValidationError(
                'Account is locked due to too many failed login attempts. Please try again in 30 minutes.',
                code='account_locked',
            )
        
        if not user.is_active:
            raise forms.ValidationError(
                'This account is inactive.',
                code='inactive',
            )

class CustomPasswordChangeForm(forms.Form):
    """Simple password change form - just old and new password"""
    old_password = forms.CharField(
        label="Current Password",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter current password',
            'autocomplete': 'current-password'
        })
    )
    new_password = forms.CharField(
        label="New Password",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter new password',
            'autocomplete': 'new-password'
        }),
        min_length=4,  # Minimum 4 characters only
    )
    confirm_password = forms.CharField(
        label="Confirm New Password",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm new password',
            'autocomplete': 'new-password'
        })
    )
    
    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
    
    def clean_old_password(self):
        """Check if old password is correct"""
        old_password = self.cleaned_data.get('old_password')
        if not self.user.check_password(old_password):
            raise forms.ValidationError("Current password is incorrect.")
        return old_password
    
    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get('new_password')
        confirm_password = cleaned_data.get('confirm_password')
        
        if new_password and confirm_password:
            if new_password != confirm_password:
                raise forms.ValidationError("New passwords do not match.")
        
        return cleaned_data
    
    def save(self):
        """Save the new password"""
        self.user.set_password(self.cleaned_data['new_password'])
        self.user.save()
        return self.user

class CustomSetPasswordForm(SetPasswordForm):
    new_password1 = forms.CharField(
        label="New Password",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter new password',
            'autocomplete': 'new-password'
        }),
        strip=False,
    )
    new_password2 = forms.CharField(
        label="Confirm New Password",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm new password',
            'autocomplete': 'new-password'
        }),
        strip=False,
    )

class CustomPasswordResetForm(PasswordResetForm):
    """Password reset form - just email to send reset link"""
    email = forms.EmailField(
        label="Email Address",
        max_length=254,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your email address',
            'autocomplete': 'email'
        })
    )

class BookingForm(forms.ModelForm):
    business_name = forms.CharField(max_length=200, required=True)
    client_first_name = forms.CharField(max_length=100, required=True)
    client_last_name = forms.CharField(max_length=100, required=True)
    client_email = forms.EmailField(required=True)
    client_phone = forms.CharField(max_length=20, required=True)
    zoom_link = forms.URLField(required=False, widget=forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'Zoom meeting link (if applicable)'}))
    location = forms.CharField(max_length=255, required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'State or City'}))
    audio_file = forms.FileField(required=False)
    meeting_address = forms.CharField(required=False, label='Meeting Address')

    class Meta:
        model = Booking
        fields = [
            'business_name', 'client_first_name', 'client_last_name',
            'client_email', 'client_phone', 'salesman', 'appointment_date',
            'appointment_time', 'duration_minutes', 'appointment_type', 'location', 'zoom_link', 'meeting_address', 'notes', 'audio_file'
        ]
        widgets = {
            'appointment_date': forms.DateInput(attrs={'type': 'date'}),
            'appointment_time': forms.TimeInput(attrs={'type': 'time'}),
            'duration_minutes': forms.NumberInput(attrs={'readonly': True, 'class': 'form-control'}),
            'meeting_address': forms.Textarea(attrs={'row': 4}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }
    
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)
        
        for field_name, field in self.fields.items():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({'class': 'form-control'})

        # only do this if 'salesman' exists
        if 'salesman' in self.fields:
            self.fields['salesman'].queryset = User.objects.filter(
                is_active_salesman=True,
                is_active=True
            )
            self.fields['salesman'].widget.attrs['class'] = 'form-control'
        
        # Always force duration to 15 minutes in the UI
        if 'duration_minutes' in self.fields:
            self.fields['duration_minutes'].initial = 15
            self.fields['duration_minutes'].disabled = True

        # Pre-fill client info if editing
        if self.instance and self.instance.pk:
            # Business name
            self.fields['business_name'].initial = getattr(self.instance.client, 'business_name', '')
            self.fields['client_first_name'].initial = self.instance.client.first_name
            self.fields['client_last_name'].initial = self.instance.client.last_name
            self.fields['client_email'].initial = self.instance.client.email
            self.fields['client_phone'].initial = self.instance.client.phone_number
            
            
            # Lock fields based on user role
            is_admin = self.request and self.request.user.is_staff
            is_remote_agent = self.request and self.request.user.groups.filter(name='remote_agent').exists()
            
            # If booking is pending
            if self.instance.status == 'pending':
                lock_fields = [
                    'business_name', 'client_first_name', 'client_last_name', 'client_email', 'client_phone',
                    'salesman', 'appointment_date', 'appointment_time', 'duration_minutes', 'appointment_type', 
                    'location', 'zoom_link', 'meeting_address'
                ]
                
                # Admin can edit all fields - don't lock anything for admin
                if is_admin:
                    # Admin can edit everything - remove readonly
                    pass
                else:
                    # Remote agents: lock all salesman-related fields
                    for name in lock_fields:
                        if name in self.fields:
                            self.fields[name].disabled = True
                            self.fields[name].required = False
        
        # Set zoom link from SystemConfig for zoom appointments
        if self.initial.get('appointment_type') == 'zoom':
            try:
                config = SystemConfig.get_config()
                if config and config.zoom_link:
                    self.fields['zoom_link'].initial = config.zoom_link
            except SystemConfig.DoesNotExist:
                pass
    
    def clean(self):
        cleaned_data = super().clean()
        salesman = cleaned_data.get('salesman')
        location = cleaned_data.get('location')
        appointment_date = cleaned_data.get('appointment_date')
        appointment_time = cleaned_data.get('appointment_time')
        appointment_type = cleaned_data.get('appointment_type')
        duration_minutes = 15  # Force 15 minutes
        zoom_link = cleaned_data.get('zoom_link')
        meeting_address = cleaned_data.get('meeting_address')

        if appointment_type == 'zoom' and not zoom_link:
            self.add_error('zoom_link', 'A meeting link is required for Zoom appointments.')
        if appointment_type == 'in_person' and not meeting_address:
            self.add_error('meeting_address', 'A meeting address is required for in-person appointments.')
        """if appointment_type == 'in_person' and not location:
            self.add_error('location', 'Location (State/City) is required for in-person appointments.')
            """
        
        if all([salesman, appointment_date, appointment_time, appointment_type]):
            # Determine if we should skip availability validation
            skip_availability_checks = False
            if self.instance and self.instance.pk:
                original_same = (
                    self.instance.salesman_id == (salesman.id if hasattr(salesman, 'id') else getattr(salesman, 'pk', salesman)) and
                    self.instance.appointment_date == appointment_date and
                    self.instance.appointment_time == appointment_time and
                    self.instance.appointment_type == appointment_type
                )
                if original_same:
                    skip_availability_checks = True
            # Admins can bypass availability constraints during edit
            if self.request and (self.request.user.is_staff or self.request.user.is_superuser) and self.instance and self.instance.pk:
                skip_availability_checks = True

            if skip_availability_checks:
                return cleaned_data
                
            # Get available slots for this day and appointment type
            date = appointment_date
            available_slots = AvailableTimeSlot.objects.filter(
                salesman=salesman,
                date=date,
                appointment_type=appointment_type,
                is_active=True
            )
            
            if not available_slots.exists():
                raise forms.ValidationError(
                    f"{salesman.get_full_name()} has no available {appointment_type} slots on {appointment_date.strftime('%A')}s at location '{location}'. "
                    f"Please select a different salesman, day, location, or appointment type."
                )
            
            # Check if time falls within any available slot
            time_is_valid = False
            valid_slot = None
            for slot in available_slots:
                if slot.is_time_in_slot(appointment_time):
                    time_is_valid = True
                    valid_slot = slot
                    break
            
            if not time_is_valid:
                available_times = ", ".join([
                    f"{slot.start_time.strftime('%I:%M %p')}"
                    for slot in available_slots
                ])
                raise forms.ValidationError(
                    f"Selected time is not available for {appointment_type} appointments at location '{location}'. "
                    f"{salesman.get_full_name()}'s available times on {appointment_date.strftime('%A')}s: {available_times}"
                )
            
            # Force duration to 15 minutes regardless of slot
            cleaned_data['duration_minutes'] = 15
            duration_minutes = 15
            
            # Check for booking conflicts
            if duration_minutes:
                has_conflict, conflict_booking = check_booking_conflicts(
                    salesman, appointment_date, appointment_time, duration_minutes,
                    exclude_booking_id=self.instance.pk if self.instance.pk else None
                )
                
                if has_conflict:
                    raise forms.ValidationError(
                        f"Time slot already booked: {conflict_booking.client.get_full_name()} "
                        f"at {conflict_booking.appointment_time.strftime('%I:%M %p')}"
                    )
        
        # Restrict audio upload to admins only
        if self.files and self.files.get('audio_file'):
            if not (self.request and (self.request.user.is_staff or self.request.user.is_superuser)):
                self.add_error('audio_file', 'Only administrators can upload audio files.')

            # Optional: limit file types to audio
            uploaded = self.files.get('audio_file')
            if uploaded and hasattr(uploaded, 'content_type'):
                if not uploaded.content_type.startswith('audio/'):
                    self.add_error('audio_file', 'Invalid file type. Please upload an audio file.')

        # Ensure duration is always 15
        cleaned_data['duration_minutes'] = 15
        return cleaned_data
    
    def save(self, commit=True):
        booking = super().save(commit=False)
        booking.meeting_address = self.cleaned_data.get('meeting_address', '')

        # Get or create client
        client, created = Client.objects.get_or_create(
            email=self.cleaned_data['client_email'],
            defaults={
                'business_name': self.cleaned_data['business_name'],
                'first_name': self.cleaned_data['client_first_name'],
                'last_name': self.cleaned_data['client_last_name'],
                'phone_number': self.cleaned_data['client_phone'],
                'created_by': self.request.user if self.request else booking.salesman
            }
        )
        
        if not created:
            # Update existing client info
            client.business_name = self.cleaned_data['business_name']
            client.first_name = self.cleaned_data['client_first_name']
            client.last_name = self.cleaned_data['client_last_name']
            client.phone_number = self.cleaned_data['client_phone']
            client.save()
        
        booking.client = client

        # Admin can edit locked fields - don't restore original values
        is_admin = self.request and self.request.user.is_staff
        
        # If editing a pending booking AND not admin, ignore changes to locked fields
        if booking.pk and booking.status == 'pending' and not is_admin:
            original = Booking.objects.get(pk=booking.pk)
            booking.salesman = original.salesman
            booking.appointment_date = original.appointment_date
            booking.appointment_time = original.appointment_time
            booking.duration_minutes = original.duration_minutes
            booking.appointment_type = original.appointment_type
            booking.zoom_link = original.zoom_link
            booking.meeting_address = original.meeting_address
            booking.client = original.client
           
        # Force duration to 15 minutes at save-time
        booking.duration_minutes = 15

        audio = self.files.get('audio_file') if self.files else None
        if audio and (self.request and (self.request.user.is_staff or self.request.user.is_superuser)):
            booking.audio_file = audio

        if not booking.pk:
            booking.created_by = self.request.user if self.request else booking.salesman
            
            if self.request and self.request.user.groups.filter(name='remote_agent').exists():
                booking.status = 'pending'
            else:
                booking.status = 'confirmed'
        else:
            booking.updated_by = self.request.user if self.request else booking.salesman

        if commit:
            booking.save()
        
        return booking

class CancelBookingForm(forms.Form):
    cancellation_reason = forms.ChoiceField(
        choices=Booking.CANCELLATION_REASONS,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    cancellation_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-control', 'placeholder': 'Additional notes...'})
    )

class PayrollAdjustmentForm(forms.ModelForm):
    class Meta:
        model = PayrollAdjustment
        fields = ['user', 'adjustment_type', 'amount', 'reason', 'booking']
        widgets = {
            'user': forms.Select(attrs={'class': 'form-control'}),
            'adjustment_type': forms.Select(attrs={'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'reason': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'booking': forms.Select(attrs={'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        self.payroll_period = kwargs.pop('payroll_period', None)
        super().__init__(*args, **kwargs)
        
        # Filter users to remote_agents who are on the payroll
        self.fields['user'].queryset = User.objects.filter(
            groups__name='remote_agent',
            is_active=True
        ).distinct().order_by('first_name', 'last_name')
        
        if self.payroll_period:
            self.fields['booking'].queryset = Booking.objects.filter(
                appointment_date__gte=self.payroll_period.start_date,
                appointment_date__lte=self.payroll_period.end_date,
                created_by__groups__name='remote_agent'
            )
        
        self.fields['booking'].required = False


class SystemConfigForm(forms.ModelForm):
    class Meta:
        model = SystemConfig
        fields = [
            'company_name', 'timezone', 
            'default_commission_rate_in_person', 'default_commission_rate_zoom', 
            'zoom_link', 'reminder_lead_time_hours',
            'zoom_enabled', 'in_person_enabled'
        ]
        widgets = {
            'company_name': forms.TextInput(attrs={'class': 'form-control'}),
            'timezone': forms.TextInput(attrs={'class': 'form-control'}),
            'default_commission_rate_in_person': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'default_commission_rate_zoom': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'zoom_link': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://zoom.us/j/...'}),
            'reminder_lead_time_hours': forms.NumberInput(attrs={'class': 'form-control'}),
            'zoom_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'in_person_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Add help text for better UX
        self.fields['company_name'].help_text = 'Company name displayed in emails and system'
        self.fields['timezone'].help_text = 'System timezone (e.g., America/New_York, UTC)'
        self.fields['default_commission_rate_in_person'].help_text = 'Default commission for in-person appointments ($)'
        self.fields['default_commission_rate_zoom'].help_text = 'Default commission for zoom appointments ($)'
        self.fields['zoom_link'].help_text = 'Default zoom meeting link for all zoom appointments'
        self.fields['reminder_lead_time_hours'].help_text = 'Hours before appointment to send reminder'
        self.fields['zoom_enabled'].help_text = 'Enable Zoom appointments. Disabling this will deactivate all active Zoom time slots.'
        self.fields['in_person_enabled'].help_text = 'Enable in-person appointments. Disabling this will deactivate all active in-person time slots.'

class MessageTemplateCSVUploadForm(forms.Form):
    """Form for uploading message templates via CSV"""
    csv_file = forms.FileField(
        label='CSV File',
        help_text='Upload a CSV file with columns: message_type, email_subject, email_body, sms_body, is_active',
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.csv'
        })
    )
    
    def clean_csv_file(self):
        csv_file = self.cleaned_data.get('csv_file')
        if csv_file:
            if not csv_file.name.endswith('.csv'):
                raise forms.ValidationError('File must be a CSV file.')
            
            # Check file size (max 5MB)
            if csv_file.size > 5 * 1024 * 1024:
                raise forms.ValidationError('File size must be less than 5MB.')
                
        return csv_file


class MessageTemplateForm(forms.ModelForm):
    class Meta:
        model = MessageTemplate
        fields = ['message_type', 'email_subject', 'email_body', 'sms_body', 'is_active']
        widgets = {
            'message_type': forms.Select(attrs={'class': 'form-control'}),
            'email_subject': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Email subject line'}),
            'email_body': forms.Textarea(attrs={
                'class': 'form-control', 
                'rows': 10,
                'placeholder': 'HTML email body. Use {client_name}, {salesman_name}, {business_name}, {appointment_date}, {appointment_time}, {company_name}'
            }),
            'sms_body': forms.Textarea(attrs={
                'class': 'form-control', 
                'rows': 3,
                'maxlength': 320,
                'placeholder': 'SMS message (max 320 chars). Same variables as email.'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Add help text
        self.fields['email_body'].help_text = 'Available variables: {client_name}, {salesman_name}, {business_name}, {appointment_date}, {appointment_time}, {company_name}'
        self.fields['sms_body'].help_text = 'Max 320 characters. Same variables as email template.'
        
        # Add character counter for SMS
        self.fields['sms_body'].widget.attrs['oninput'] = 'updateCharCount(this)'
    
    def clean_sms_body(self):
        sms_body = self.cleaned_data.get('sms_body', '')
        if len(sms_body) > 320:
            raise forms.ValidationError('SMS message must be 320 characters or less.')
        return sms_body


class AvailableTimeSlotForm(forms.ModelForm):
    class Meta:
        model = AvailableTimeSlot
        fields = ['salesman', 'date', 'start_time', 'appointment_type', 'is_active']
        widgets = {
            'salesman': forms.Select(attrs={'class': 'form-control'}),
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'start_time': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'appointment_type': forms.Select(attrs={'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        self.is_admin = kwargs.pop('is_admin', False)
        self.current_user = kwargs.pop('current_user', None)
        super().__init__(*args, **kwargs)
        
        # Filter salesmen to only active salesmen
        self.fields['salesman'].queryset = User.objects.filter(
            is_active_salesman=True,
            is_active=True
        )
        
        # If not admin, make salesman field readonly and hide it
        if not self.is_admin:
            self.fields['salesman'].disabled = True
            self.fields['salesman'].required = False
            # Set to current user
            if self.current_user:
                self.fields['salesman'].initial = self.current_user
        
        # Add help text
        self.fields['start_time'].help_text = 'Format: HH:MM (24-hour)'
    
    def clean(self):
        cleaned_data = super().clean()
        start_time = cleaned_data.get('start_time')
        salesman = cleaned_data.get('salesman')
        date = cleaned_data.get('date')
        appointment_type = cleaned_data.get('appointment_type')
        
    
        
        # Check for overlapping slots for the same salesman, day, and type
        if salesman and date is not None and start_time and appointment_type:
            overlapping = AvailableTimeSlot.objects.filter(
                salesman=salesman,
                date=date,
                appointment_type=appointment_type,
                is_active=True
            )
            
            # Exclude current instance if editing
            if self.instance.pk:
                overlapping = overlapping.exclude(pk=self.instance.pk)
            
            # Check for time overlap
            """for slot in overlapping:
                if (start_time < slot.end_time and end_time > slot.start_time):
                    raise forms.ValidationError(
                        f"This time slot overlaps with an existing {appointment_type} slot: "
                        f"{slot.start_time.strftime('%I:%M %p')} - {slot.end_time.strftime('%I:%M %p')}"
                    )
        """
        return cleaned_data


class AgentRegistrationForm(forms.ModelForm):
    """Simplified self-registration form for remote agents - uses UserForm logic"""
    username = forms.CharField(
        max_length=150, 
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        help_text='Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.'
    )
    first_name = forms.CharField(max_length=100, required=True, widget=forms.TextInput(attrs={'class': 'form-control'}))
    last_name = forms.CharField(max_length=100, required=True, widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={'class': 'form-control'}))
    phone_number = forms.CharField(max_length=20, required=True, widget=forms.TextInput(attrs={'class': 'form-control'}))
    paypal_email = forms.EmailField(required=False, widget=forms.EmailInput(attrs={'class': 'form-control'}))
    bitcoin_wallet_address = forms.CharField(
        max_length=255, 
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    ACH_bank_name = forms.CharField(
        max_length=100, 
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    ACH_account_number = forms.CharField(
        max_length=50, 
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    ACH_routing_number = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control', 
            'placeholder': 'Leave blank to auto-generate a temporary password'
        }),
        help_text='Leave blank if you want a temporary password to be generated.',
        min_length=4,
        strip=False
    )
    password_confirm = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control', 
            'placeholder': 'Confirm password'
        }),
        label='Confirm Password',
        strip=False
    )
    
    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'phone_number']
    
    def clean_username(self):
        username = self.cleaned_data.get('username')
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("A user with this username already exists.")
        return username
    
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email
    
    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password', '').strip() if cleaned_data.get('password') else ''
        password_confirm = cleaned_data.get('password_confirm', '').strip() if cleaned_data.get('password_confirm') else ''
        
        # Only validate if at least one password field is filled
        if password or password_confirm:
            if password != password_confirm:
                raise forms.ValidationError("Passwords do not match.")
            if password and len(password) < 4:
                raise forms.ValidationError("Password must be at least 4 characters long.")
        
        return cleaned_data
    
    def save(self, commit=True):
        user = super().save(commit=False)
        # Set payment details from form
        user.paypal_email = self.cleaned_data.get('paypal_email', '')
        user.bitcoin_wallet_address = self.cleaned_data.get('bitcoin_wallet_address', '')
        user.ACH_account_number = self.cleaned_data.get('ACH_account_number', '')
        user.ACH_routing_number = self.cleaned_data.get('ACH_routing_number', '')
        user.ACH_bank_name = self.cleaned_data.get('ACH_bank_name', '')
                
        # Check if password was provided in form data
        password_from_form = self.cleaned_data.get('password')
        
        if password_from_form:
            # Password provided - use it
            user.set_password(password_from_form)
            user.plain_text_password = password_from_form
        else:
            # No password provided - generate temp password (SAME LOGIC AS user_create)
            from django.utils.crypto import get_random_string
            temp_password = get_random_string(length=12)
            user.set_password(temp_password)
            user.plain_text_password = temp_password
        
        # AUTO-GENERATE employee_id (SAME LOGIC AS UserForm)
        if not user.employee_id:
            with transaction.atomic():
                max_attempts = 100
                for attempt in range(max_attempts):
                    existing_ids = User.objects.filter(
                        employee_id__startswith='EMP'
                    ).values_list('employee_id', flat=True)
                    
                    numbers = []
                    for emp_id in existing_ids:
                        try:
                            num = int(emp_id.replace('EMP', ''))
                            numbers.append(num)
                        except (ValueError, AttributeError):
                            continue
                    
                    if numbers:
                        new_number = max(numbers) + 1
                    else:
                        new_number = 1
                    
                    new_employee_id = f'EMP{new_number:05d}'
                    
                    if not User.objects.filter(employee_id=new_employee_id).exists():
                        user.employee_id = new_employee_id
                        logger.debug(f"Assigned employee_id: {user.employee_id}")
                        break
                else:
                    raise forms.ValidationError("Unable to generate unique employee ID. Please try again.")
        
        # Set as active user
        user.is_active = True
        
        if commit:
            try:
                user.save()
                logger.info(f"Agent self-registered: {user.username}, Employee ID: {user.employee_id}, Password stored: {bool(user.plain_text_password)}")
            except Exception as e:
                logger.error(f"Error saving agent: {str(e)}")
                raise forms.ValidationError(f"Error saving user: {str(e)}")
        
        return user