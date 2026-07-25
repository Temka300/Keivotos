"""Behaviour shared across routers and modules, owned by neither.

A service knows nothing about Danbooru or the Files base — that is what makes
the module removable. Danbooru-specific behaviour belongs in
``modules/danbooru/``; the base's own behaviour belongs in ``files_base/``.

(The wording here previously referred to ``core.py``, which was deleted on
2026-07-25.)
"""
