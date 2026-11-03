"""ASGI-Einstiegspunkt: wsgi:application ist ein ASGI-Callable und muss mit uvicorn oder im uWSGI-ASGI-Modus gestartet werden, NICHT als WSGI."""
from app import app as application
