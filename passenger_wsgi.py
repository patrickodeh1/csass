import sys, os
from pathlib import Path

# Define the project base directory
BASE_DIR = Path(__file__).resolve().parent

# Add project and virtual environment paths
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "csass_project"))

# Activate virtual environment if it exists
venv_path = BASE_DIR / "venv" / "bin" / "activate_this.py"
if venv_path.exists():
    with open(venv_path) as f:
        exec(f.read(), dict(__file__=str(venv_path)))

# Set the Django settings module
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "csass_project.settings")

# Import and expose the WSGI application
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
