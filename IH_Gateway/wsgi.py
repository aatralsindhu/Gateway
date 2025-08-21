import os
import sys

from django.core.wsgi import get_wsgi_application

# Set the default settings module for the 'wsgi' command.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'IH_Gateway.settings')

# Get the WSGI application for the project.
application = get_wsgi_application()