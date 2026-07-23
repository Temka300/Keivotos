"""Files base — the always-on neutral file layer (V1.1.0).

This package is deliberately isolated: it must never import Danbooru modules or
``core``. It stores only disk-derived facts in a disposable index and authors no
metadata. See docs/important/SUITE_MODULE_CONTRACT.md.
"""
