from django.contrib import admin
from .models import (User, Client, Booking, 
                     PayrollPeriod, PayrollAdjustment, AvailabilityCycle,
                     SystemConfig, AuditLog, AvailableTimeSlot)
@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['id', 'client', 'salesman', 'appointment_date', 'appointment_time', 'status', 'appointment_type']
    list_filter = ['status', 'appointment_type', 'appointment_date']
    search_fields = ['client__first_name', 'client__last_name', 'client__email', 'salesman__first_name', 'salesman__last_name']
    date_hierarchy = 'appointment_date'
    
    # CRITICAL: Optimize queries by prefetching related objects
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Prefetch related salesman and client to avoid N+1 queries
        return qs.select_related('salesman', 'client', 'created_by', 'payroll_period')
    
    # Use select_related for list view as well
    list_select_related = ['salesman', 'client', 'created_by']
    
    # For large datasets, use raw_id_fields instead of dropdowns
    # This creates a search popup instead of loading all options
    raw_id_fields = ['salesman', 'client', 'created_by', 'updated_by', 
                     'approved_by', 'declined_by', 'canceled_by', 'available_slot']
    
    # Optimize autocomplete fields
    autocomplete_fields = []  # Add fields here if you set up autocomplete
    
    fieldsets = (
        ('Appointment Details', {
            'fields': ('client', 'salesman', 'appointment_date', 'appointment_time', 
                      'duration_minutes', 'appointment_type', 'status')
        }),
        ('Location Details', {
            'fields': ('meeting_address', 'zoom_link', 'location', 'resort'),
            'classes': ('collapse',)
        }),
        ('Financial Details', {
            'fields': ('maintenance_fees', 'mortgage_balance', 'commission_amount'),
            'classes': ('collapse',)
        }),
        ('Additional Information', {
            'fields': ('notes', 'audio_file'),
            'classes': ('collapse',)
        }),
        ('Status Information', {
            'fields': ('cancellation_reason', 'cancellation_notes', 'decline_reason', 
                      'is_locked', 'payroll_period'),
            'classes': ('collapse',)
        }),
        ('System Fields', {
            'fields': ('created_by', 'created_at', 'updated_by', 'updated_at',
                      'approved_by', 'approved_at', 'declined_by', 'declined_at',
                      'canceled_by', 'canceled_at'),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ['created_at', 'updated_at', 'approved_at', 'declined_at', 'canceled_at']
    
    def save_model(self, request, obj, form, change):
        if not change:  # New object
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


# Also optimize Client and User admin if needed
@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ['id', 'first_name', 'last_name', 'email', 'phone_number', 'business_name']
    search_fields = ['first_name', 'last_name', 'email', 'phone_number', 'business_name']
    list_filter = ['created_at']
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('created_by')


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['username', 'email', 'first_name', 'last_name', 'is_active', 'is_staff']
    search_fields = ['username', 'email', 'first_name', 'last_name']
    list_filter = ['is_active', 'is_staff', 'is_active_salesman']




admin.site.register(AvailableTimeSlot)
admin.site.register(AvailabilityCycle)

admin.site.register(PayrollPeriod)


admin.site.register(PayrollAdjustment)


admin.site.register(SystemConfig)
admin.site.site_header = "CSASS Administration"
admin.site.site_title = "CSASS Admin Portal"
admin.site.index_title = "Welcome to CSASS Admin Portal"


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['timestamp', 'user', 'action', 'entity_type', 'entity_id']
    list_filter = ['action', 'entity_type', 'timestamp']
    search_fields = ['user__first_name', 'user__last_name', 'entity_type']
    readonly_fields = ['timestamp']
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False

