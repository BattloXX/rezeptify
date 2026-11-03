"""Guard server-side HTTP downloads against private destinations and large bodies."""
from dataclasses import dataclass
import ipaddress
import socket
from urllib.parse import urljoin

import httpx


ALLOWED_PORTS = {None, 80, 443}


class UnsafeUrlError(ValueError):
    pass


class TooLargeError(ValueError):
    pass


def _resolve(host):
    return [entry[4][0] for entry in socket.getaddrinfo(host, None)]


def check_url(url) -> None:
    try:
        parsed = httpx.URL(url)
        if parsed.scheme not in {"http", "https"} or not parsed.host or parsed.port not in ALLOWED_PORTS:
            raise ValueError
        try:
            addresses = [ipaddress.ip_address(parsed.host)]
        except ValueError:
            addresses = [ipaddress.ip_address(address) for address in _resolve(parsed.host)]
        if not addresses:
            raise ValueError
        for address in addresses:
            if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
                address = address.ipv4_mapped
            if not address.is_global or address.is_multicast:
                raise ValueError
    except (ValueError, TypeError, httpx.InvalidURL, OSError) as exc:
        raise UnsafeUrlError("Adresse nicht erlaubt") from exc


@dataclass
class SafeResponse:
    status_code: int
    headers: httpx.Headers
    content: bytes
    url: str
    encoding: str

    @property
    def text(self):
        try:
            return self.content.decode(self.encoding, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")


def safe_get(url, *, max_bytes, timeout=15.0, headers=None, params=None, transport=None):
    # DNS rebinding between validation and connection is not fully prevented;
    # this limitation is accepted for this family app.
    with httpx.Client(follow_redirects=False, timeout=timeout, headers=headers,
                      transport=transport, trust_env=False) as client:
        for redirects in range(6):
            check_url(url)
            with client.stream("GET", url, params=params) as response:
                if response.status_code in {301, 302, 303, 307, 308} and "location" in response.headers:
                    if redirects == 5:
                        raise UnsafeUrlError("Zu viele Weiterleitungen")
                    url = urljoin(str(response.url), response.headers["location"])
                    params = None
                    continue
                content = bytearray()
                for chunk in response.iter_bytes():
                    if len(content) + len(chunk) > max_bytes:
                        raise TooLargeError("Antwort zu groß")
                    content.extend(chunk)
                return SafeResponse(response.status_code, response.headers, bytes(content),
                                    str(response.url), response.encoding or "utf-8")
