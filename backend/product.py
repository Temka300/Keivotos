"""Suite-owned product identity exposed by the application."""

SUITE_NAME = "Keivotos"
VERSION = "1.2.2"
# Set from an explicit, timezone-aware release record when an artifact is prepared.
# An empty value means this version has no recorded release date yet.
RELEASED_AT = ""
DISPLAY_NAME = SUITE_NAME
WEB_TITLE = SUITE_NAME
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 52325
DEFAULT_ORIGIN = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
