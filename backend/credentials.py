"""Compatibility import for Danbooru-owned credentials.

Alias the owner itself so historical callers and patches share its lock/state.
"""
import sys

from modules.danbooru import credentials as _credentials

sys.modules[__name__] = _credentials
