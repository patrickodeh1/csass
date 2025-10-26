from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    # Authentication
    path('', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.agent_registration, name='agent_registration'),

    # Password Reset
    path('password-reset/', views.CustomPasswordResetView.as_view(), name='password_reset'),
    path('password-reset/done/', views.CustomPasswordResetDoneView.as_view(), name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/', views.CustomPasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('password-reset-complete/', views.CustomPasswordResetCompleteView.as_view(), name='password_reset_complete'),
    
    # Password Change
    path('password-change/', views.password_change_view, name='password_change'),
    
    # Calendar & Bookings
    path('calendar/', views.calendar_view, name='calendar'),
    path('calendar/day/<str:date_str>/', views.calendar_day_detail, name='calendar_day_detail'),
    path('booking/new/', views.booking_create, name='booking_create'),
    path('booking/<int:pk>/', views.booking_detail, name='booking_detail'),
    path('booking/<int:pk>/edit/', views.booking_edit, name='booking_edit'),
    path('booking/<int:pk>/cancel/', views.booking_cancel, name='booking_cancel'),

    # Mark attendance - accessible by admin AND salesmen (for their own bookings)
    path('past-appointments/', views.past_appointments_view, name='past_appointments'),    
    path('booking/<int:pk>/mark-attended/', views.booking_mark_attended, name='booking_mark_attended'),
    path('booking/<int:pk>/mark-dna/', views.booking_mark_dna, name='booking_mark_dna'),
    
    # Booking Approvals (Admin & Salesman)
    path('bookings/pending/', views.pending_bookings_view, name='pending_bookings'),
    path('bookings/<int:pk>/approve/', views.booking_approve, name='booking_approve'),
    path('bookings/<int:pk>/decline/', views.booking_decline, name='booking_decline'),
    path('booking/<int:pk>/revert-to-pending/', views.booking_revert_to_pending, name='booking_revert_to_pending'),
    path('booking/<int:pk>/audio/upload/', views.booking_audio_upload, name='booking_audio_upload'),
    path('booking/<int:pk>/audio/delete/', views.booking_audio_delete, name='booking_audio_delete'),
    
    # Booking Approvals (Salesman)
    path('salesman/bookings/pending/', views.salesman_pending_bookings_view, name='salesman_pending_bookings'),
    path('salesman/bookings/<int:pk>/approve/', views.salesman_booking_approve, name='salesman_booking_approve'),
    path('salesman/bookings/<int:pk>/decline/', views.salesman_booking_decline, name='salesman_booking_decline'),
    # Live Transfer
    path('live-transfer/new/', views.live_transfer_create, name='live_transfer_create'),
    path('live-transfer/<int:booking_id>/edit/', views.live_transfer_edit, name='live_transfer_edit'),
    
    # Timeslot Management from Calendar
    path('timeslot/<int:slot_id>/delete-from-calendar/', views.timeslot_delete_from_calendar, name='timeslot_delete_from_calendar'),
    
    # Commissions
    path('commissions/', views.commissions_view, name='commissions'),
    
    path('pending-count/', views.pending_bookings_count_api, name='pending_count_api'),
    path('salesman-pending-count/', views.salesman_pending_bookings_count_api, name='salesman_pending_count_api'),

    # Time Slots (Admin)
    path('admiin/timeslots/', views.timeslots_view, name='timeslots'),
    path('admiin/timeslots/new/', views.timeslot_create, name='timeslot_create'),
    path('admiin/timeslots/<int:pk>/edit/', views.timeslot_edit, name='timeslot_edit'),
    path('admiin/timeslots/<int:pk>/delete/', views.timeslot_delete, name='timeslot_delete'),

    # Payroll (admiin)
    path('admiin/payroll/', views.payroll_view, name='payroll'),
    path('admiin/payroll/<int:pk>/finalize/', views.payroll_finalize, name='payroll_finalize'),
    path('admiin/payroll/export/', views.payroll_export, name='payroll_export'),
    path('admiin/payroll/adjustment/new/', views.payroll_adjustment_create, name='payroll_adjustment_create'),
    
    # Users (admiin)
    path('admiin/users/', views.users_view, name='users'),
    path('admiin/users/new/', views.user_create, name='user_create'),
    path('admiin/users/<int:pk>/edit/', views.user_edit, name='user_edit'),
    path('admiin/users/<int:pk>/deactivate/', views.user_deactivate, name='user_deactivate'),
    path('admiin/users/<int:pk>/reactivate/', views.user_reactivate, name='user_reactivate'),
    path('admiin/users/<int:pk>/delete/', views.user_delete, name='user_delete'),
    
    # Clients (admiin)
    path('admiin/clients/', views.clients_view, name='clients'),
    path('admiin/clients/<int:pk>/', views.client_detail, name='client_detail'),
    
    # Settings (admiin)
    path('admiin/settings/', views.settings_view, name='settings'),

    # Audit Log (admiin)
    path('admiin/audit-log/', views.audit_log_view, name='audit_log'),
     
    # Message template management
    path('settings/templates/', views.message_templates_view, name='message_templates'),
    path('settings/templates/create/', views.message_template_create, name='message_template_create'),
    path('settings/templates/<int:pk>/edit/', views.message_template_edit, name='message_template_edit'),
    path('settings/templates/<int:pk>/delete/', views.message_template_delete, name='message_template_delete'),
    
    # Drip campaign management
    path('drip-campaigns/', views.drip_campaigns_view, name='drip_campaigns'),
    path('drip-campaigns/<int:pk>/stop/', views.drip_campaign_stop, name='drip_campaign_stop'),
    path('drip-campaigns/<int:pk>/resume/', views.drip_campaign_resume, name='drip_campaign_resume'),
    
    # Communication logs
    path('communication-logs/', views.communication_logs_view, name='communication_logs'),
]