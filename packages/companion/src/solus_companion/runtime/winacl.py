"""advapi32 DACL reader/writer for owner-only folders on Windows (§5).

Pure ctypes — no pywin32. Only ever constructed when `sys.platform == "win32"`
(ownership.owner_only_for); the decision logic it feeds is
`ownership.snapshot_is_owner_only`, tested on every platform. Everything here
needs a Windows host to execute, hence the coverage pragmas."""

import ctypes
from ctypes import wintypes
from pathlib import Path
from typing import Any

from solus_companion.runtime.ownership import FILE_ALL_ACCESS, SYSTEM_SID, Ace, AclSnapshot

_SE_FILE_OBJECT = 1
_OWNER_SECURITY_INFORMATION = 0x1
_DACL_SECURITY_INFORMATION = 0x4
_PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
_SE_DACL_PROTECTED = 0x1000
_ACL_REVISION = 2
_OBJECT_INHERIT_ACE = 0x1
_CONTAINER_INHERIT_ACE = 0x2
_ACCESS_ALLOWED_ACE_TYPE = 0
_ACCESS_DENIED_ACE_TYPE = 1
_TOKEN_QUERY = 0x8
_TOKEN_USER = 1


class _AceHeader(ctypes.Structure):
    _fields_ = [
        ("AceType", ctypes.c_ubyte),
        ("AceFlags", ctypes.c_ubyte),
        ("AceSize", ctypes.c_ushort),
    ]


class _KnownAce(ctypes.Structure):
    _fields_ = [("Header", _AceHeader), ("Mask", wintypes.DWORD), ("SidStart", wintypes.DWORD)]


class _AclSizeInformation(ctypes.Structure):
    _fields_ = [
        ("AceCount", wintypes.DWORD),
        ("AclBytesInUse", wintypes.DWORD),
        ("AclBytesFree", wintypes.DWORD),
    ]


_PVOID = ctypes.c_void_p
_PPVOID = ctypes.POINTER(ctypes.c_void_p)
_DW = wintypes.DWORD
_PDW = ctypes.POINTER(wintypes.DWORD)
Signature = tuple[Any, list[Any]]

#: (restype, argtypes) for every call made below. Without these ctypes passes
#: and returns C `int`, truncating 64-bit HANDLEs and pointers.
ADVAPI32_SIGNATURES: dict[str, Signature] = {
    "ConvertSidToStringSidW": (wintypes.BOOL, [_PVOID, ctypes.POINTER(wintypes.LPWSTR)]),
    "ConvertStringSidToSidW": (wintypes.BOOL, [wintypes.LPCWSTR, _PPVOID]),
    "OpenProcessToken": (wintypes.BOOL, [wintypes.HANDLE, _DW, ctypes.POINTER(wintypes.HANDLE)]),
    "GetTokenInformation": (wintypes.BOOL, [wintypes.HANDLE, ctypes.c_int, _PVOID, _DW, _PDW]),
    "GetNamedSecurityInfoW": (
        _DW,
        [wintypes.LPCWSTR, ctypes.c_int, _DW, _PPVOID, _PPVOID, _PPVOID, _PPVOID, _PPVOID],
    ),
    "GetSecurityDescriptorControl": (
        wintypes.BOOL,
        [_PVOID, ctypes.POINTER(wintypes.WORD), _PDW],
    ),
    "GetAclInformation": (wintypes.BOOL, [_PVOID, _PVOID, _DW, ctypes.c_int]),
    "GetAce": (wintypes.BOOL, [_PVOID, _DW, _PPVOID]),
    "InitializeAcl": (wintypes.BOOL, [_PVOID, _DW, _DW]),
    "AddAccessAllowedAceEx": (wintypes.BOOL, [_PVOID, _DW, _DW, _DW, _PVOID]),
    "SetNamedSecurityInfoW": (
        _DW,
        [wintypes.LPWSTR, ctypes.c_int, _DW, _PVOID, _PVOID, _PVOID, _PVOID],
    ),
}
KERNEL32_SIGNATURES: dict[str, Signature] = {
    "GetCurrentProcess": (wintypes.HANDLE, []),
    "CloseHandle": (wintypes.BOOL, [wintypes.HANDLE]),
    "LocalFree": (_PVOID, [_PVOID]),
}


def _dll(name: str, signatures: dict[str, Signature]) -> Any:  # pragma: no cover
    dll = getattr(ctypes, "WinDLL")(name, use_last_error=True)  # noqa: B009 — absent off Windows
    for function, (restype, argtypes) in signatures.items():
        bound = getattr(dll, function)
        bound.restype = restype
        bound.argtypes = argtypes
    return dll


def _check(ok: int) -> None:  # pragma: no cover
    if not ok:
        raise OSError(getattr(ctypes, "get_last_error")(), "advapi32 call failed")  # noqa: B009


class Advapi32Backend:  # pragma: no cover — Windows only
    def __init__(self) -> None:
        self._advapi = _dll("advapi32", ADVAPI32_SIGNATURES)
        self._kernel = _dll("kernel32", KERNEL32_SIGNATURES)

    def _sid_string(self, sid: Any) -> str:
        text = wintypes.LPWSTR()
        _check(self._advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)))
        try:
            return str(text.value)
        finally:
            self._kernel.LocalFree(ctypes.cast(text, ctypes.c_void_p))

    def current_user_sid(self) -> str:
        token = wintypes.HANDLE()
        process = self._kernel.GetCurrentProcess()
        _check(self._advapi.OpenProcessToken(process, _TOKEN_QUERY, ctypes.byref(token)))
        try:
            size = wintypes.DWORD()
            self._advapi.GetTokenInformation(token, _TOKEN_USER, None, 0, ctypes.byref(size))
            buffer = ctypes.create_string_buffer(size.value)
            _check(
                self._advapi.GetTokenInformation(
                    token, _TOKEN_USER, buffer, size, ctypes.byref(size)
                )
            )
            sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p)).contents
            return self._sid_string(sid)
        finally:
            self._kernel.CloseHandle(token)

    def read(self, path: Path) -> AclSnapshot | None:
        owner, dacl, descriptor = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        flags = _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION
        status = self._advapi.GetNamedSecurityInfoW(
            str(path),
            _SE_FILE_OBJECT,
            flags,
            ctypes.byref(owner),
            None,
            ctypes.byref(dacl),
            None,
            ctypes.byref(descriptor),
        )
        if status != 0:
            return None
        try:
            control, revision = wintypes.WORD(), wintypes.DWORD()
            _check(
                self._advapi.GetSecurityDescriptorControl(
                    descriptor, ctypes.byref(control), ctypes.byref(revision)
                )
            )
            if not dacl.value:
                return None
            return AclSnapshot(
                owner_sid=self._sid_string(owner),
                protected=bool(control.value & _SE_DACL_PROTECTED),
                aces=self._aces(dacl),
            )
        finally:
            self._kernel.LocalFree(descriptor)

    def _aces(self, dacl: Any) -> tuple[Ace, ...]:
        info = _AclSizeInformation()
        _check(self._advapi.GetAclInformation(dacl, ctypes.byref(info), ctypes.sizeof(info), 2))
        aces = []
        for index in range(info.AceCount):
            pointer = ctypes.c_void_p()
            _check(self._advapi.GetAce(dacl, index, ctypes.byref(pointer)))
            ace = ctypes.cast(pointer, ctypes.POINTER(_KnownAce)).contents
            kind = {_ACCESS_ALLOWED_ACE_TYPE: "allow", _ACCESS_DENIED_ACE_TYPE: "deny"}.get(
                ace.Header.AceType, "other"
            )
            sid = ctypes.c_void_p(pointer.value + _KnownAce.SidStart.offset)  # type: ignore[operator]
            aces.append(Ace(kind=kind, sid=self._sid_string(sid), mask=int(ace.Mask)))  # type: ignore[arg-type]
        return tuple(aces)

    def _sid(self, text: str) -> Any:
        sid = ctypes.c_void_p()
        _check(self._advapi.ConvertStringSidToSidW(text, ctypes.byref(sid)))
        return sid

    def apply(self, path: Path, user_sid: str) -> None:
        user, system = self._sid(user_sid), self._sid(SYSTEM_SID)
        try:
            size = 1024
            acl = ctypes.create_string_buffer(size)
            _check(self._advapi.InitializeAcl(acl, size, _ACL_REVISION))
            inherit = _OBJECT_INHERIT_ACE | _CONTAINER_INHERIT_ACE
            for sid in (user, system):
                _check(
                    self._advapi.AddAccessAllowedAceEx(
                        acl, _ACL_REVISION, inherit, FILE_ALL_ACCESS, sid
                    )
                )
            flags = (
                _OWNER_SECURITY_INFORMATION
                | _DACL_SECURITY_INFORMATION
                | _PROTECTED_DACL_SECURITY_INFORMATION
            )
            status = self._advapi.SetNamedSecurityInfoW(
                str(path), _SE_FILE_OBJECT, flags, user, None, acl, None
            )
            if status != 0:
                raise OSError(status, "SetNamedSecurityInfoW failed")
        finally:
            self._kernel.LocalFree(user)
            self._kernel.LocalFree(system)
