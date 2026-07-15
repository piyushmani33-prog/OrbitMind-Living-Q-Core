"""Narrow Windows API boundary for platform validation and single-instance control."""

from __future__ import annotations

import ctypes
import platform
import sys
import threading
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any, Protocol

from orbitmind.runtime.status import ExitCode, ReasonCode, RuntimeFailure

_ERROR_ALREADY_EXISTS = 183
_TOKEN_QUERY = 0x0008
_TOKEN_USER = 1
_TOKEN_ELEVATION = 20
_SDDL_REVISION_1 = 1
_MUTEX_IDENTITY = "Global\\OrbitMind.U5.0B0.Runtime.v1"
_CONSOLE_EVENTS = frozenset({0, 1, 2, 5, 6})


class MutexHandle(Protocol):
    def release(self) -> None: ...


class ConsoleHandler(Protocol):
    def unregister(self) -> None: ...


class WindowsRuntime(Protocol):
    def validate_environment(self) -> None: ...

    def acquire_mutex(self) -> MutexHandle: ...

    def register_console_handler(self, stop_event: threading.Event) -> ConsoleHandler: ...


@dataclass
class _NativeMutex:
    kernel32: Any
    handle: int
    _released: bool = False

    def release(self) -> None:
        if self._released:
            return
        self.kernel32.ReleaseMutex(self.handle)
        self.kernel32.CloseHandle(self.handle)
        self._released = True


@dataclass
class _NativeConsoleHandler:
    kernel32: Any
    callback: Any
    _registered: bool = True

    def unregister(self) -> None:
        if self._registered:
            self.kernel32.SetConsoleCtrlHandler(self.callback, False)
            self._registered = False


class NativeWindowsRuntime:
    """ctypes implementation; no pywin32 or broad privilege changes."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeFailure(
                ExitCode.UNSUPPORTED_ENVIRONMENT, ReasonCode.UNSUPPORTED_ENVIRONMENT
            )
        win_dll = ctypes.WinDLL
        self._kernel32 = win_dll("kernel32", use_last_error=True)
        self._advapi32 = win_dll("advapi32", use_last_error=True)
        self._configure_signatures()

    def _configure_signatures(self) -> None:
        self._kernel32.GetCurrentProcess.argtypes = []
        self._kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
        self._kernel32.LocalFree.restype = wintypes.HLOCAL
        self._kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self._kernel32.CreateMutexW.restype = wintypes.HANDLE
        self._kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
        self._kernel32.ReleaseMutex.restype = wintypes.BOOL
        self._advapi32.OpenProcessToken.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        self._advapi32.OpenProcessToken.restype = wintypes.BOOL
        self._advapi32.GetTokenInformation.argtypes = [
            wintypes.HANDLE,
            ctypes.c_uint,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._advapi32.GetTokenInformation.restype = wintypes.BOOL
        self._advapi32.ConvertSidToStringSidW.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.LPWSTR),
        ]
        self._advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
        self._advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL

    def validate_environment(self) -> None:
        machine = platform.machine().lower()
        windows = sys.getwindowsversion()
        if windows.major < 10 or machine not in {"amd64", "x86_64"} or self._is_elevated():
            raise RuntimeFailure(
                ExitCode.UNSUPPORTED_ENVIRONMENT, ReasonCode.UNSUPPORTED_ENVIRONMENT
            )

    def _open_process_token(self) -> int:
        token = wintypes.HANDLE()
        process = self._kernel32.GetCurrentProcess()
        if not self._advapi32.OpenProcessToken(process, _TOKEN_QUERY, ctypes.byref(token)):
            raise RuntimeFailure(
                ExitCode.UNSUPPORTED_ENVIRONMENT, ReasonCode.UNSUPPORTED_ENVIRONMENT
            )
        if token.value is None:
            raise RuntimeFailure(
                ExitCode.UNSUPPORTED_ENVIRONMENT, ReasonCode.UNSUPPORTED_ENVIRONMENT
            )
        return int(token.value)

    def _is_elevated(self) -> bool:
        token = self._open_process_token()
        try:
            elevated = wintypes.DWORD()
            returned = wintypes.DWORD()
            if not self._advapi32.GetTokenInformation(
                token,
                _TOKEN_ELEVATION,
                ctypes.byref(elevated),
                ctypes.sizeof(elevated),
                ctypes.byref(returned),
            ):
                raise RuntimeFailure(
                    ExitCode.UNSUPPORTED_ENVIRONMENT, ReasonCode.UNSUPPORTED_ENVIRONMENT
                )
            return bool(elevated.value)
        finally:
            self._kernel32.CloseHandle(token)

    def _current_user_sid(self) -> str:
        token = self._open_process_token()
        buffer = None
        sid_string = wintypes.LPWSTR()
        try:
            required = wintypes.DWORD()
            self._advapi32.GetTokenInformation(token, _TOKEN_USER, None, 0, ctypes.byref(required))
            if required.value == 0:
                raise RuntimeFailure(
                    ExitCode.UNSUPPORTED_ENVIRONMENT, ReasonCode.UNSUPPORTED_ENVIRONMENT
                )
            buffer = ctypes.create_string_buffer(required.value)
            if not self._advapi32.GetTokenInformation(
                token,
                _TOKEN_USER,
                buffer,
                required,
                ctypes.byref(required),
            ):
                raise RuntimeFailure(
                    ExitCode.UNSUPPORTED_ENVIRONMENT, ReasonCode.UNSUPPORTED_ENVIRONMENT
                )
            sid_pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p)).contents.value
            if not self._advapi32.ConvertSidToStringSidW(sid_pointer, ctypes.byref(sid_string)):
                raise RuntimeFailure(
                    ExitCode.UNSUPPORTED_ENVIRONMENT, ReasonCode.UNSUPPORTED_ENVIRONMENT
                )
            return str(sid_string.value)
        finally:
            if sid_string:
                self._kernel32.LocalFree(sid_string)
            self._kernel32.CloseHandle(token)

    def acquire_mutex(self) -> MutexHandle:
        sid = self._current_user_sid()
        descriptor = ctypes.c_void_p()
        sddl = f"D:P(A;;GA;;;SY)(A;;GA;;;{sid})"
        if not self._advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl,
            _SDDL_REVISION_1,
            ctypes.byref(descriptor),
            None,
        ):
            raise RuntimeFailure(
                ExitCode.UNSUPPORTED_ENVIRONMENT, ReasonCode.UNSUPPORTED_ENVIRONMENT
            )

        class SecurityAttributes(ctypes.Structure):
            _fields_ = [
                ("nLength", wintypes.DWORD),
                ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", wintypes.BOOL),
            ]

        attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
        try:
            ctypes.set_last_error(0)
            handle = self._kernel32.CreateMutexW(
                ctypes.byref(attributes), True, f"{_MUTEX_IDENTITY}.{sid}"
            )
            last_error = ctypes.get_last_error()
            if not handle:
                raise RuntimeFailure(
                    ExitCode.UNSUPPORTED_ENVIRONMENT, ReasonCode.UNSUPPORTED_ENVIRONMENT
                )
            if last_error == _ERROR_ALREADY_EXISTS:
                self._kernel32.CloseHandle(handle)
                raise RuntimeFailure(
                    ExitCode.SINGLE_INSTANCE_CONFLICT, ReasonCode.SINGLE_INSTANCE_CONFLICT
                )
            return _NativeMutex(self._kernel32, int(handle))
        finally:
            self._kernel32.LocalFree(descriptor)

    def register_console_handler(self, stop_event: threading.Event) -> ConsoleHandler:
        handler_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

        def handle_console_event(event: int) -> bool:
            if event in _CONSOLE_EVENTS:
                stop_event.set()
                return True
            return False

        callback = handler_type(handle_console_event)
        self._kernel32.SetConsoleCtrlHandler.argtypes = [handler_type, wintypes.BOOL]
        self._kernel32.SetConsoleCtrlHandler.restype = wintypes.BOOL
        if not self._kernel32.SetConsoleCtrlHandler(callback, True):
            raise RuntimeFailure(ExitCode.BACKEND_FAILURE, ReasonCode.BACKEND_FAILURE)
        return _NativeConsoleHandler(self._kernel32, callback)


class FakeMutex:
    """Small injectable mutex used by tests and bounded integration probes."""

    def __init__(self, on_release: Callable[[], None] | None = None) -> None:
        self.released = False
        self._on_release = on_release

    def release(self) -> None:
        self.released = True
        if self._on_release is not None:
            self._on_release()
