"""
wsgi.py – uWSGI Entry Point für CloudPanel
CloudPanel ruft: uwsgi --module wsgi:application
"""
from app import app

# uWSGI / WSGI compatibility via asgiref
try:
    from asgiref.wsgi import WsgiToAsgi
    # FastAPI is ASGI – wrap for uWSGI
    # Actually use uvicorn's ASGI interface directly
    application = app
except ImportError:
    application = app

# For uWSGI with --gevent or --asyncio support:
# uwsgi --http :8000 --module wsgi:application --gevent 100

# Standard ASGI callable for uvicorn / uWSGI asyncio mode
application = app
