"""Single source of truth for product identity exposed by the application."""

SUITE_NAME = "Keivotos"
MODULE_NAME = "Danbooru"
VERSION = "1.0.0"
DISPLAY_NAME = f"{SUITE_NAME} - {MODULE_NAME}"
WEB_TITLE = DISPLAY_NAME
USER_AGENT = f"{SUITE_NAME}/{VERSION} ({MODULE_NAME})"
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 52325
DEFAULT_ORIGIN = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
