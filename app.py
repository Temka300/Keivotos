"""Launch Keivotos and its Danbooru module.

Source examples:
    python app.py
    python app.py --dev
    python app.py --no-browser --port 52326

Maintainer LAN runs use the ignored run-lan.local.bat launcher.
"""
from __future__ import annotations

import argparse
import ctypes
import importlib
import ipaddress
import logging
import os
import runpy
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


def resource_root() -> Path:
    bundled = getattr(sys, "_MEIPASS", None)
    return Path(bundled).resolve() if bundled else Path(__file__).resolve().parent


ROOT = resource_root()
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from product import DEFAULT_HOST, DEFAULT_PORT, DISPLAY_NAME, VERSION, WEB_TITLE  # noqa: E402


LAN_HOST_ENV = "KEIVOTOS_LAN_HOST"
LAN_DEVELOPER_ENV = "KEIVOTOS_DEVELOPER_LAN"
MIGRATE_LEGACY_HOME_ENV = "KEIVOTOS_MIGRATE_LEGACY_HOME"
CONSOLE_ICON_PATH = ROOT / "assets" / "branding" / "keivotos" / "keivotos.ico"
LAN_IPV4_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "10.0.0.0/8",
        "100.64.0.0/10",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.168.0.0/16",
    )
)


def _load_configuration(*, migrate_legacy_home: bool):
    if migrate_legacy_home:
        os.environ[MIGRATE_LEGACY_HOME_ENV] = "1"
    try:
        return importlib.import_module("config")
    except Exception as exc:  # noqa: BLE001 - configuration must fail clearly before logging exists.
        message = f"Keivotos could not load its configuration. {exc}"
        print(message, file=sys.stderr)
        if getattr(sys, "frozen", False) and sys.platform == "win32":
            try:
                ctypes.windll.user32.MessageBoxW(None, message, "Keivotos configuration error", 0x10)
            except (AttributeError, OSError):
                pass
        raise SystemExit(2) from None


def _load_asgi_app():
    # Keep this as a real import so frozen builds include the backend composition
    # root. Uvicorn's string form ("server:app") is intentionally retained only
    # for source development, where reload needs an import string.
    from server import app as asgi_app

    return asgi_app


def _set_console_branding() -> None:
    if sys.platform != "win32":
        return
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32.SetConsoleTitleW.argtypes = [ctypes.c_wchar_p]
        kernel32.SetConsoleTitleW.restype = ctypes.c_int
        kernel32.GetConsoleWindow.argtypes = []
        kernel32.GetConsoleWindow.restype = ctypes.c_void_p
        user32.LoadImageW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        user32.LoadImageW.restype = ctypes.c_void_p
        user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_void_p]
        user32.SendMessageW.restype = ctypes.c_ssize_t

        kernel32.SetConsoleTitleW(WEB_TITLE)
        console_window = kernel32.GetConsoleWindow()
        if not console_window or not CONSOLE_ICON_PATH.is_file():
            return

        image_icon = 1
        load_from_file = 0x0010
        wm_seticon = 0x0080
        for icon_kind, size in ((1, 32), (0, 16)):
            icon = user32.LoadImageW(
                None,
                str(CONSOLE_ICON_PATH),
                image_icon,
                size,
                size,
                load_from_file,
            )
            if icon:
                user32.SendMessageW(console_window, wm_seticon, icon_kind, icon)
    except (AttributeError, OSError):
        pass


def _run_helper(script_name: str, arguments: list[str]) -> int:
    script = ROOT / "scripts" / script_name
    if not script.is_file():
        print(f"Packaged helper is missing: {script}", file=sys.stderr)
        return 2
    sys.argv = [str(script), *arguments]
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as exc:
        if exc.code is None:
            return 0
        if isinstance(exc.code, int):
            return exc.code
        print(str(exc.code), file=sys.stderr)
        return 1
    return 0


def _open_browser_when_ready(url: str) -> None:
    def worker() -> None:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=0.5) as response:
                    if response.status < 500:
                        webbrowser.open(url)
                        return
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(0.25)
        logging.getLogger("keivotos").warning("Browser was not opened because %s did not become ready", url)

    threading.Thread(target=worker, name="keivotos-browser-launch", daemon=True).start()


def _portable_check(configuration) -> int:
    frontend = ROOT / "frontend" / "dist" / "index.html"
    folder_picker = ROOT / "scripts" / "windows_folder_picker.py"
    asgi_app = _load_asgi_app()
    backend_ok = any(getattr(route, "path", None) == "/" for route in asgi_app.routes)
    print(f"{DISPLAY_NAME} {VERSION}")
    print(f"Resources: {ROOT}")
    print(f"Frontend: {'ok' if frontend.is_file() else 'missing'} ({frontend})")
    print(f"Backend: {'ok' if backend_ok else 'missing root route'}")
    print(f"Folder picker: {'ok' if folder_picker.is_file() else 'missing'} ({folder_picker})")
    print(f"Writable home: {configuration.SUITE_HOME}")
    print(f"Runtime config: {configuration.RUNTIME_CONFIG_FILE}")
    print(f"Library: {configuration.DATA_ROOT}")
    print(f"Metadata: {configuration.METADATA_DIR}")
    print(f"gallery-dl: {configuration.GALLERY_DL_DIR}")
    tools_ok = True
    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        for tool_name in ("gallery-dl.exe", "ffmpeg.exe"):
            tool_path = executable_dir / tool_name
            present = tool_path.is_file()
            tools_ok = tools_ok and present
            print(f"{tool_name}: {'ok' if present else 'missing'} ({tool_path})")
    return 0 if frontend.is_file() and backend_ok and folder_picker.is_file() and tools_ok else 1


def _port_available(host: str, port: int) -> tuple[bool, str | None]:
    probe_host = "127.0.0.1" if host == "localhost" else host
    family = socket.AF_INET6 if probe_host == "::1" else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind((probe_host, port))
    except OSError as exc:
        return False, str(exc)
    return True, None


def _is_lan_ipv4(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return address.version == 4 and any(address in network for network in LAN_IPV4_NETWORKS)


def _discover_lan_ipv4() -> str | None:
    candidates: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            candidates.append(str(probe.getsockname()[0]))
    except OSError:
        pass
    try:
        candidates.extend(
            str(sockaddr[0])
            for family, _kind, _protocol, _canonical, sockaddr in socket.getaddrinfo(
                socket.gethostname(),
                None,
                family=socket.AF_INET,
                type=socket.SOCK_STREAM,
            )
            if family == socket.AF_INET
        )
    except OSError:
        pass
    return next((candidate for candidate in candidates if _is_lan_ipv4(candidate)), None)


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["--pipeline"]:
        _load_configuration(migrate_legacy_home=True)
        return _run_helper("danbooru_gallery_dl.py", arguments[1:])
    if arguments[:1] == ["--folder-picker"]:
        return _run_helper("windows_folder_picker.py", arguments[1:])

    frozen = bool(getattr(sys, "frozen", False))
    parser = argparse.ArgumentParser(description=DISPLAY_NAME)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--dev", action="store_true", help="Enable backend reload for source development")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the web interface automatically")
    parser.add_argument("--version", action="store_true", help="Print the Keivotos version and exit")
    parser.add_argument("--portable-check", action="store_true", help="Validate packaged resources and print data paths")
    developer_lan_enabled = os.environ.get(LAN_DEVELOPER_ENV, "").strip() == "1"
    if not frozen and developer_lan_enabled:
        parser.add_argument(
            "--lan",
            action="store_true",
            help="Allow trusted devices on the same private network to open this source run",
        )
    args = parser.parse_args(arguments)
    os.environ.pop(LAN_HOST_ENV, None)

    if args.version:
        _load_configuration(migrate_legacy_home=False)
        print(f"{DISPLAY_NAME} {VERSION}")
        return 0
    if args.portable_check:
        configuration = _load_configuration(migrate_legacy_home=False)
        return _portable_check(configuration)
    configuration = _load_configuration(migrate_legacy_home=True)
    lan_enabled = bool(getattr(args, "lan", False))
    lan_host: str | None = None
    bind_host = args.host
    browser_host = args.host
    if lan_enabled:
        if args.host != DEFAULT_HOST:
            parser.error("--lan cannot be combined with --host")
        lan_host = _discover_lan_ipv4()
        if lan_host is None:
            parser.error("--lan could not find a private IPv4 address for this computer")
        bind_host = lan_host
        browser_host = DEFAULT_HOST
        os.environ[LAN_HOST_ENV] = lan_host
    elif args.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("Keivotos only binds to a local loopback host")

    import uvicorn
    runtime_logging = importlib.import_module("runtime_logging")

    runtime_log_path, access_log_path = runtime_logging.configure_runtime_logging()
    logger = logging.getLogger("keivotos")
    _set_console_branding()
    url_host = f"[{browser_host}]" if browser_host == "::1" else browser_host
    url = f"http://{url_host}:{args.port}/"
    logger.info("Starting %s %s at %s", DISPLAY_NAME, VERSION, url)
    if lan_host is not None:
        logger.warning("Trusted-network LAN access is enabled at http://%s:%s/", lan_host, args.port)
        logger.warning("Devices on this network can use Keivotos while this process is running")
    migration = configuration.SUITE_HOME_MIGRATION
    if migration.get("migrated"):
        logger.info(
            "Copied and verified legacy application data: %s files from %s to %s; the original was preserved",
            migration["files"],
            migration["source"],
            migration["destination"],
        )
    logger.info("Writable application data: %s", configuration.SUITE_HOME)
    logger.info("Runtime log: %s", runtime_log_path)
    logger.info("HTTP access log: %s", access_log_path)
    port_available, port_error = _port_available(bind_host, args.port)
    if not port_available:
        alternate_action = "--lan --port <another-port>" if lan_enabled else "--port <another-loopback-port>"
        logger.error(
            "Cannot start Keivotos because %s:%s is already in use or unavailable: %s. "
            "Close the other process or start with %s.",
            bind_host,
            args.port,
            port_error,
            alternate_action,
        )
        return 2
    if not args.no_browser:
        _open_browser_when_ready(url)
    application = "server:app" if args.dev and not frozen else _load_asgi_app()
    uvicorn.run(
        application,
        host=bind_host,
        port=args.port,
        reload=bool(args.dev and not frozen),
        app_dir=str(BACKEND_DIR),
        log_config=None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
