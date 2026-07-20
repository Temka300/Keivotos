"""Open the modern Windows Explorer folder picker through IFileOpenDialog.

The selected filesystem path is written to stdout. Cancelling writes an empty
line and exits successfully so the API can distinguish cancellation from a
COM failure. This helper intentionally has no third-party dependencies.
"""
from __future__ import annotations

import ctypes
import os
import sys
import uuid
from ctypes import wintypes


CLSCTX_INPROC_SERVER = 0x1
COINIT_APARTMENTTHREADED = 0x2
FOS_PICKFOLDERS = 0x20
FOS_FORCEFILESYSTEM = 0x40
FOS_PATHMUSTEXIST = 0x800
SIGDN_FILESYSPATH = 0x80058000
ERROR_CANCELLED_HRESULT = 0x800704C7


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def parse(cls, value: str) -> "GUID":
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


CLSID_FILE_OPEN_DIALOG = GUID.parse("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")
IID_FILE_OPEN_DIALOG = GUID.parse("D57C7288-D4AD-4768-BE02-9D969532D960")


def _code(result: int) -> int:
    return result & 0xFFFFFFFF


def _check(result: int, operation: str) -> None:
    if _code(result) & 0x80000000:
        raise OSError(f"{operation} failed with HRESULT 0x{_code(result):08X}")


def _method(interface: ctypes.c_void_p, index: int, *argument_types):
    vtable = ctypes.cast(
        interface,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
    ).contents
    prototype = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argument_types)
    return prototype(vtable[index])


def _release(interface: ctypes.c_void_p | None) -> None:
    if interface:
        _method(interface, 2)(interface)


def select_folder(title: str = "Add folder to Keivotos - Danbooru") -> str | None:
    if os.name != "nt":
        raise OSError("IFileOpenDialog is only available on Windows")

    ole32 = ctypes.OleDLL("ole32")
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(GUID),
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    ole32.CoCreateInstance.restype = ctypes.c_long
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole32.CoTaskMemFree.restype = None

    initialized = False
    dialog = ctypes.c_void_p()
    shell_item = ctypes.c_void_p()
    display_name = ctypes.c_wchar_p()
    try:
        result = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
        _check(result, "CoInitializeEx")
        initialized = True

        result = ole32.CoCreateInstance(
            ctypes.byref(CLSID_FILE_OPEN_DIALOG),
            None,
            CLSCTX_INPROC_SERVER,
            ctypes.byref(IID_FILE_OPEN_DIALOG),
            ctypes.byref(dialog),
        )
        _check(result, "CoCreateInstance(IFileOpenDialog)")

        options = wintypes.DWORD()
        _check(_method(dialog, 10, ctypes.POINTER(wintypes.DWORD))(dialog, ctypes.byref(options)), "GetOptions")
        options.value |= FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST
        _check(_method(dialog, 9, wintypes.DWORD)(dialog, options), "SetOptions")
        _check(_method(dialog, 17, wintypes.LPCWSTR)(dialog, title), "SetTitle")

        result = _method(dialog, 3, wintypes.HWND)(dialog, None)
        if _code(result) == ERROR_CANCELLED_HRESULT:
            return None
        _check(result, "Show")

        _check(
            _method(dialog, 20, ctypes.POINTER(ctypes.c_void_p))(dialog, ctypes.byref(shell_item)),
            "GetResult",
        )
        _check(
            _method(shell_item, 5, ctypes.c_uint, ctypes.POINTER(ctypes.c_wchar_p))(
                shell_item,
                SIGDN_FILESYSPATH,
                ctypes.byref(display_name),
            ),
            "IShellItem.GetDisplayName",
        )
        return display_name.value
    finally:
        if display_name:
            ole32.CoTaskMemFree(ctypes.cast(display_name, ctypes.c_void_p))
        _release(shell_item)
        _release(dialog)
        if initialized:
            ole32.CoUninitialize()


def main() -> int:
    try:
        print(select_folder() or "")
        return 0
    except Exception as exc:
        print(f"Modern folder picker failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
