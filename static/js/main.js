// Main JavaScript for CSASS

document.addEventListener('DOMContentLoaded', function() {
    
    // Auto-hide alerts after 5 seconds
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        setTimeout(() => {
            const bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        }, 5000);
    });
    
    // Confirm delete actions
    const deleteButtons = document.querySelectorAll('[data-confirm-delete]');
    deleteButtons.forEach(button => {
        button.addEventListener('click', function(e) {
            if (!confirm('Are you sure you want to delete this item?')) {
                e.preventDefault();
            }
        });
    });
    
    // Form validation enhancement
    const forms = document.querySelectorAll('form[data-validate]');
    forms.forEach(form => {
        form.addEventListener('submit', function(e) {
            if (!form.checkValidity()) {
                e.preventDefault();
                e.stopPropagation();
            }
            form.classList.add('was-validated');
        });
    });
    
    // Calendar navigation
    const calendarCells = document.querySelectorAll('.calendar-day');
    calendarCells.forEach(cell => {
        cell.addEventListener('click', function() {
            const date = this.dataset.date;
            if (date) {
                window.location.href = `/booking/new/?date=${date}`;
            }
        });
    });
    
    // Initialize tooltips
    const tooltipTriggerList = [].slice.call(
        document.querySelectorAll('[data-bs-toggle="tooltip"]')
    );
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
    
    // Auto-format phone numbers
    const phoneInputs = document.querySelectorAll('input[name*="phone"]');
    phoneInputs.forEach(input => {
        input.addEventListener('input', function(e) {
            let value = e.target.value.replace(/\D/g, '');
            if (value.length >= 10) {
                value = value.slice(0, 10);
                const formatted = `(${value.slice(0,3)}) ${value.slice(3,6)}-${value.slice(6)}`;
                e.target.value = formatted;
            }
        });
    });
    
    // Loading state for forms
    const submitButtons = document.querySelectorAll('form button[type="submit"]');
    submitButtons.forEach(button => {
        button.closest('form').addEventListener('submit', function() {
            button.disabled = true;
            button.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Loading...';
        });
    });
    
    // Client duplicate detection
    const clientEmailInput = document.querySelector('input[name="client_email"]');
    if (clientEmailInput) {
        let debounceTimer;
        clientEmailInput.addEventListener('input', function() {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                checkClientExists(this.value);
            }, 500);
        });
    }
    
    function checkClientExists(email) {
        if (!email || !email.includes('@')) return;
        
        // This would typically make an AJAX call to check if client exists
        // For now, just a placeholder
        console.log('Checking if client exists:', email);
    }
    
    // Booking time slot selection
    const timeSlots = document.querySelectorAll('.time-slot');
    timeSlots.forEach(slot => {
        slot.addEventListener('click', function() {
            timeSlots.forEach(s => s.classList.remove('selected'));
            this.classList.add('selected');
            
            const time = this.dataset.time;
            const date = this.dataset.date;
            
            document.querySelector('input[name="appointment_time"]').value = time;
            document.querySelector('input[name="appointment_date"]').value = date;
        });
    });
    
    // Commission calculations display
    updateCommissionTotal();
    
    function updateCommissionTotal() {
        const commissionElements = document.querySelectorAll('[data-commission]');
        let total = 0;
        
        commissionElements.forEach(el => {
            const amount = parseFloat(el.dataset.commission);
            if (!isNaN(amount)) {
                total += amount;
            }
        });
        
        const totalDisplay = document.getElementById('commission-total');
        if (totalDisplay) {
            totalDisplay.textContent = `${total.toFixed(2)}`;
        }
    }
    
    // Date picker constraints
    const datePickers = document.querySelectorAll('input[type="date"]');
    const today = new Date().toISOString().split('T')[0];
    
    datePickers.forEach(picker => {
        if (picker.name.includes('appointment') || picker.name.includes('start')) {
            picker.setAttribute('min', today);
        }
    });
    
    // Enhanced table row click
    const clickableRows = document.querySelectorAll('tr[data-href]');
    clickableRows.forEach(row => {
        row.style.cursor = 'pointer';
        row.addEventListener('click', function(e) {
            if (e.target.tagName !== 'BUTTON' && e.target.tagName !== 'A') {
                window.location.href = this.dataset.href;
            }
        });
    });
    
    console.log('CSASS initialized successfully');

    // Pending approvals badge updater (navbar)
    const pendingBadge = document.getElementById('pending-count');
    if (pendingBadge) {
        const updatePendingCount = () => {
            fetch('/pending-count/')
                .then(r => r.json())
                .then(data => {
                    if (data && typeof data.count === 'number' && data.count > 0) {
                        pendingBadge.textContent = data.count;
                        pendingBadge.style.display = 'inline';
                    } else {
                        pendingBadge.style.display = 'none';
                    }
                })
                .catch(() => {});
        };
        updatePendingCount();
        setInterval(updatePendingCount, 30000);
    }
});

// Utility functions
function formatCurrency(amount) {
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD'
    }).format(amount);
}

function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric'
    });
}

function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `alert alert-${type} alert-dismissible fade show position-fixed top-0 end-0 m-3`;
    toast.style.zIndex = '9999';
    toast.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    document.body.appendChild(toast);
    
    setTimeout(() => {
        const bsAlert = new bootstrap.Alert(toast);
        bsAlert.close();
    }, 5000);
}