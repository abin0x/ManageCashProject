"""
WSGI config for Mahmudul_Hasan_Abin_1554_ManageCash project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Mahmudul_Hasan_Abin_1554_ManageCash.settings')

application = get_wsgi_application()
