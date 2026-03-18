"""Network infrastructure — LAN IP detection for API server."""

import socket


def get_lan_ip() -> str:
    """Auto-detect LAN IP by probing default route interface.

    Opens a UDP socket to a public DNS (no data sent) to determine
    which local interface the OS would route through.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
