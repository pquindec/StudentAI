"""Red local: IP de la Wi-Fi del Mac, estado del cortafuegos y QR."""

import ipaddress
import re
import socket
import subprocess
from pathlib import Path

import segno

NETWORKSETUP = "/usr/sbin/networksetup"
IPCONFIG = "/usr/sbin/ipconfig"
FIREWALL = "/usr/libexec/ApplicationFirewall/socketfilterfw"


def _run(args: list[str]) -> str:
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=5, check=False)  # noqa: S603
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return out.stdout


def wifi_device() -> str | None:
    """Nombre del interfaz Wi-Fi (normalmente `en0`)."""
    found = re.search(
        r"Hardware Port: Wi-Fi\s*\nDevice: (\S+)", _run([NETWORKSETUP, "-listallhardwareports"])
    )
    return found.group(1) if found else None


# Espacio compartido (RFC 6598): algunas redes grandes, como la Wi-Fi de una universidad, lo usan
# para sus dispositivos. No se enruta en internet, pero `ipaddress` no lo cuenta como privado.
SHARED = ipaddress.ip_network("100.64.0.0/10")


def is_private(ip: str) -> bool:
    """IPv4 de una red local (no alcanzable desde internet), sin loopback ni enlace local."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.version != 4 or addr.is_loopback or addr.is_link_local:
        return False
    return addr.is_private or addr in SHARED


def wifi_ip() -> str | None:
    """IP privada del Mac en la Wi-Fi; si no hay Wi-Fi, la de la interfaz de salida."""
    dev = wifi_device()
    if dev:
        ip = _run([IPCONFIG, "getifaddr", dev]).strip()
        if is_private(ip):
            return ip
    # Respaldo: un socket UDP «conectado» no envía nada, pero revela la interfaz de salida.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 9))  # dirección de documentación: nunca se contacta
            ip = str(s.getsockname()[0])
        except OSError:
            return None
    return ip if is_private(ip) else None


def firewall() -> dict[str, bool | None]:
    """Cortafuegos de macOS: activado y si bloquea todas las conexiones entrantes."""
    state = _run([FIREWALL, "--getglobalstate"])
    block = _run([FIREWALL, "--getblockall"])
    return {
        "enabled": None if not state else "enabled" in state.lower(),
        "block_all": None if not block else "enabled" in block.lower(),
    }


def qr_terminal(url: str) -> str:
    """QR del enlace como texto para la terminal (bloques Unicode)."""
    import io

    buf = io.StringIO()
    segno.make(url, error="m").terminal(out=buf, compact=True)
    return buf.getvalue()


def qr_svg(url: str, path: Path) -> Path:
    """QR del enlace como imagen SVG grande (negro sobre blanco): se lee con cualquier cámara."""
    segno.make(url, error="m").save(str(path), scale=16, border=4, dark="#000", light="#fff")
    return path


def qr_matrix(url: str) -> list[str]:
    """QR como filas de «1» (oscuro) y «0» (claro), sin margen: la UI lo dibuja como SVG."""
    return ["".join("1" if v else "0" for v in row) for row in segno.make(url, error="m").matrix]
