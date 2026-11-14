"""Entry point for the Mi Band 6 interactive Web GUI console."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import webbrowser
from typing import Optional

from ..cli.logging import configure_logging
from ..config.defaults import DEFAULT_DATA_DIR, DEFAULT_LOG_LEVEL, DEFAULT_WEB_HOST
from ..config.env import load_env, secure_env_file
from ..dashboard import DashboardServer, TelemetryHub, make_db_history_provider
from ..storage.schema import STORAGE_BACKENDS
from .controller import GuiSessionController

logger = logging.getLogger("MiBandGUI")


def build_gui_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch the Mi Band 6 interactive Web GUI console and live dashboard."
    )
    parser.add_argument("--host", default=DEFAULT_WEB_HOST, help="HTTP bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="HTTP port (0 = random free port; default: 8080)")
    parser.add_argument("--output", default=DEFAULT_DATA_DIR, help="telemetry output directory (default: data)")
    parser.add_argument(
        "--storage",
        choices=list(STORAGE_BACKENDS),
        default="both",
        help="storage backend (default: both)",
    )
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    parser.add_argument("--auto-connect", action="store_true", help="start a session immediately on launch")
    parser.add_argument("--demo", action="store_true", help="use simulated band when --auto-connect is set")
    parser.add_argument("--log-level", default=DEFAULT_LOG_LEVEL, help="DEBUG | INFO | WARNING | ERROR")
    return parser


async def run_gui_server(
    *,
    host: str = DEFAULT_WEB_HOST,
    port: int = 8080,
    output_dir: str = DEFAULT_DATA_DIR,
    storage_backend: str = "both",
    open_browser: bool = True,
    auto_connect: bool = False,
    demo: bool = False,
) -> int:
    """Start the HTTP/SSE GUI server and serve until interrupted."""
    loop = asyncio.get_running_loop()
    hub = TelemetryHub()
    hub.attach_loop(loop)
    controller = GuiSessionController(
        hub, output_dir=output_dir, storage_backend=storage_backend
    )
    db_path = f"{output_dir}/mi_band.db"
    server = DashboardServer(
        hub,
        host=host,
        port=port,
        history_provider=make_db_history_provider(db_path),
        controller=controller,
    )

    stop_event = asyncio.Event()

    def _request_stop() -> None:
        stop_event.set()

    registered_signals: list[signal.Signals] = []
    for sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, _request_stop)
            registered_signals.append(sig)
        except (NotImplementedError, RuntimeError):
            pass

    await server.start()
    logger.info("Mi Band 6 GUI console ready at %s", server.url)

    with contextlib.suppress(Exception):
        await controller.run_doctor_check()

    if auto_connect:
        with contextlib.suppress(Exception):
            await controller.start_session({"demo": demo})

    if open_browser:
        with contextlib.suppress(Exception):
            webbrowser.open(server.url)

    try:
        await stop_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        for sig in registered_signals:
            with contextlib.suppress(Exception):
                loop.remove_signal_handler(sig)
        await controller.stop_session()
        controller.close()
        await server.stop()
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    load_env()
    secure_env_file()
    args = build_gui_parser().parse_args(argv)
    configure_logging(args.log_level)
    try:
        return asyncio.run(
            run_gui_server(
                host=args.host,
                port=args.port,
                output_dir=args.output,
                storage_backend=args.storage,
                open_browser=not args.no_browser,
                auto_connect=args.auto_connect,
                demo=args.demo,
            )
        )
    except KeyboardInterrupt:
        return 0
