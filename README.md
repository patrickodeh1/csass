# Commission-Based Sales Appointment Scheduling System (CSASS)

A comprehensive Django-based web application for managing sales appointments, tracking commissions, and automating payroll processing.

## Features

- 📅 **Calendar Management**: Book and manage appointments with real-time availability
- 💰 **Commission Tracking**: Automatic calculation of sales commissions
- 📊 **Payroll Processing**: Weekly payroll with CSV export and period locking
- 👥 **User Management**: Role-based access control (Sales Support, Salesman, Admin)
- 📧 **Email Notifications**: Automated booking confirmations and reminders
- ⏰ **Availability Management**: Self-service unavailability blocking
- 📝 **Audit Trail**: Complete logging of all system changes
- 🔒 **Security**: Built-in authentication, session management, and CSRF protection

## Tech Stack

- **Backend**: Django 4.2.7
- **Database**: PostgreSQL
- **Frontend**: Bootstrap 5.3, Django Templates
- **Email**: SMTP (Gmail, SendGrid, AWS SES compatible)

## Installation

### Prerequisites

- Python 3.10+
- PostgreSQL 14+
- pip
- virtualenv (recommended)

### Step 1: Clone Repository

```bash
git clone <repository-url>
cd csass_project
```

### Step 2: Create Virtual Environment

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Setup Environment Variables

Create a `.env` file in the project root:

```env
DEBUG=True
SECRET_KEY=your-secret-key-here-change-in-production
DATABASE_NAME=csass_db
DATABASE_USER=postgres
DATABASE_PASSWORD=your-password
DATABASE_HOST=localhost
DATABASE_PORT=5432

SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
FROM_EMAIL=noreply@yourcompany.com

TIMEZONE=America/New_York
```

### Step 5: Create Database

```bash
# Login to PostgreSQL
psql -U postgres

# Create database
CREATE DATABASE csass_db;

# Exit psql
\q
```

### Step 6: Run Migrations

```bash
python manage.py makemigrations
python manage.py migrate
```

### Step 7: Create Superuser

```bash
python manage.py createsuperuser
```

Follow prompts to create admin account.

### Step 8: Create User Groups

```bash
python manage.py shell
```

```python
from django.contrib.auth.models import Group

# Create groups
Group.objects.create(name='sales_support')
Group.objects.create(name='salesman')
Group.objects.create(name='admin')

exit()
```

### Step 9: Load Initial Data (Optional)

```bash
# Create system config
python manage.py shell
```

```python
from core.models import SystemConfig
SystemConfig.get_config()
exit()
```

### Step 10: Collect Static Files

```bash
python manage.py collectstatic
```

### Step 11: Run Development Server

```bash
python manage.py runserver
```

Visit: `http://localhost:8000`

## Setup Cron Jobs (Production)

Add these to your crontab for automated tasks:

```bash
# Open crontab
crontab -e

# Add these lines (adjust paths):

# Update booking statuses daily at 2 AM
0 2 * * * /path/to/venv/bin/python /path/to/manage.py update_booking_statuses

# Send appointment reminders hourly
0 * * * * /path/to/venv/bin/python /path/to/manage.py send_reminders
```

## User Roles

### Sales Support Employee
- Book appointments for clients
- View own commissions
- Access calendar

### Salesman
- All Sales Support permissions
- Manage own availability/unavailability
- View own bookings

### Administrator
- Full system access
- Process payroll
- Manage users
- Configure system settings
- View audit logs
- Manage all availability

## Usage Guide

### Creating a Booking

1. Navigate to Calendar
2. Click "New Booking" or click on a time slot
3. Fill in client information
4. Select salesman, date, time, and type (Zoom/In-Person)
5. Add notes (optional)
6. Click "Save Booking"
7. Confirmation emails sent automatically

### Processing Payroll

1. Navigate to Admin > Payroll Processing
2. Select pay period (Friday-Thursday)
3. Review employee commissions
4. Add adjustments if needed (bonus/penalty)
5. Export CSV for accounting
6. Click "Finalize & Lock"
7. All bookings in period are locked

### Managing Availability

1. Navigate to Manage Availability
2. Click "Add Unavailability"
3. Set date range and time
4. Select reason (vacation, sick, training, etc.)
5. System prevents bookings during blocked times

## Configuration

### Email Setup (Gmail Example)

1. Enable 2-Factor Authentication on Gmail
2. Generate App Password: https://myaccount.google.com/apppasswords
3. Use App Password in `.env` file

### Timezone Configuration

Update `TIMEZONE` in `.env` to your location:
- `America/New_York` (EST)
- `America/Chicago` (CST)
- `America/Los_Angeles` (PST)
- `UTC` (Universal)

### Commission Rate

Default: $50 per confirmed booking

To change:
1. Login as Admin
2. Navigate to Admin > System Settings
3. Update "Default Commission Rate"
4. Can override per-user in User Management

## Troubleshooting

### Database Connection Error
```
Check PostgreSQL is running:
sudo service postgresql status

Verify credentials in .env match database
```

### Email Not Sending
```
Check SMTP credentials in .env
For Gmail: Ensure "Less secure app access" is ON
Or use App Password with 2FA
```

### Static Files Not Loading
```
python manage.py collectstatic --clear
python manage.py collectstatic
```

### Migrations Error
```
python manage.py migrate --run-syncdb
```

## Security Notes

### Production Checklist

- [ ] Change `SECRET_KEY` to a strong random string
- [ ] Set `DEBUG=False` in production
- [ ] Use strong database password
- [ ] Enable HTTPS/SSL
- [ ] Configure allowed hosts in `settings.py`
- [ ] Set up proper firewall rules
- [ ] Regular database backups
- [ ] Use environment variables for secrets
- [ ] Enable CSRF protection (already configured)
- [ ] Review user permissions regularly

## Backup & Restore

### Backup Database
```bash
pg_dump -U postgres csass_db > backup.sql
```

### Restore Database
```bash
psql -U postgres csass_db < backup.sql
```

## API Documentation

This is a Django fullstack application with no REST API. All interactions are through Django views and templates.

## Support

For issues or questions:
1. Check this README
2. Review Django documentation: https://docs.djangoproject.com/
3. Check system audit log for errors
4. Contact system administrator

## License

Proprietary - All Rights Reserved

## Version

1.0.0 - Initial Release

---