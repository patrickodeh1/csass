# Celery Setup Guide

## Setup Instructions

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Install and Start Redis

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install redis-server
sudo systemctl start redis-server
sudo systemctl enable redis-server
```

**macOS:**
```bash
brew install redis
brew services start redis
```

**Windows:**
Download Redis from https://github.com/microsoftarchive/redis/releases

### 3. Run Database Migrations

```bash
python manage.py migrate
python manage.py migrate django_celery_beat
```

### 4. Start Celery Worker (Terminal 1)

```bash
celery -A csass_project worker --loglevel=info
```

### 5. Start Celery Beat Scheduler (Terminal 2)

```bash
celery -A csass_project beat --loglevel=info
```

### 6. Start Django Server (Terminal 3)

```bash
python manage.py runserver
```

## Performance Improvements

- **Salesman creation**: <100ms response (from 5-10 seconds)
- **Slot generation**: ~200ms background task (from 5-10 seconds)  
- **DB queries**: ~7 bulk inserts (from ~1400 individual inserts)
- **SystemConfig**: Auto-created on startup

## Production Deployment

For production, use a process manager like supervisor or systemd to manage Celery workers and beat scheduler.

### Example Supervisor Config

```ini
[program:csass_celery_worker]
command=/path/to/venv/bin/celery -A csass_project worker --loglevel=info
directory=/path/to/csass_project
user=www-data
autostart=true
autorestart=true
redirect_stderr=true

[program:csass_celery_beat]
command=/path/to/venv/bin/celery -A csass_project beat --loglevel=info
directory=/path/to/csass_project
user=www-data
autostart=true
autorestart=true
redirect_stderr=true
```

## Monitoring

- Check Celery worker status: `celery -A csass_project inspect active`
- Monitor task queue: `celery -A csass_project inspect reserved`
- View task results in Django admin (if using database backend)
