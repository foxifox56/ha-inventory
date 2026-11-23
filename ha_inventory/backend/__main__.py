"""Run the local development or Home Assistant web server."""

from __future__ import annotations

from .app import create_handler
from .config import Settings
from .web.server import serve


def main() -> None:
    settings = Settings.from_environment()
    handler = create_handler(
        data_dir=settings.data_dir,
        ingress_ip_check=settings.ingress_ip_check,
    )
    serve(handler, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
