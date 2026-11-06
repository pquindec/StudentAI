"""Hora actual con la zona horaria del Mac. Las rutas la reciben como dependencia (`Now`) para
que las pruebas de repaso simulen días con un reloj falso."""

from datetime import datetime


def now() -> datetime:
    return datetime.now().astimezone()
