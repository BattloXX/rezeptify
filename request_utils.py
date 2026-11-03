"""Client address resolution for requests through trusted reverse proxies."""
from fastapi import Request

TRUSTED_PROXIES = {"127.0.0.1", "::1"}


def client_ip(request: Request, trusted=None) -> str:
    if trusted is None:
        trusted = TRUSTED_PROXIES
    host = request.client.host if request.client else "unknown"
    if host in trusted:
        real_ip = request.headers.get("X-Real-IP", "").strip()
        if real_ip:
            return real_ip
        forwarded = request.headers.get("X-Forwarded-For", "").split(",")[-1].strip()
        if forwarded:
            return forwarded
    return host
