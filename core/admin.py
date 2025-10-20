from django.contrib import admin
from .models import (User, Client, Booking, 
                     PayrollPeriod, PayrollAdjustment, 
                     SystemConfig, AuditLog, AvailableTimeSlot)

@admin.register(User)
class User(admin.ModelAdmin):
    list_display = ['username', 'employee_id', 'phone_number', 'is_active_salesman', 'hire_date']
    list_filter = ['is_active_salesman', 'hire_date']
    search_fields = ['user__first_name', 'user__last_name', 'employee_id', 'phone_number']

@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ['first_name', 'last_name', 'email', 'phone_number', 'created_at']
    search_fields = ['first_name', 'last_name', 'email', 'phone_number']
    readonly_fields = ['created_at', 'updated_at']

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['client', 'salesman', 'appointment_date', 'appointment_time', 
                    'appointment_type', 'status', 'commission_amount']
    list_filter = ['status', 'appointment_type', 'appointment_date', 'is_locked']
    search_fields = ['client__first_name', 'client__last_name', 'salesman__first_name', 
                     'salesman__last_name']
    readonly_fields = ['created_at', 'updated_at', 'canceled_at']
    date_hierarchy = 'appointment_date'

admin.site.register(AvailableTimeSlot)

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

