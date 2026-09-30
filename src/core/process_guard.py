"""
Process Guard module to prevent duplicate instances and terminate previous bot processes.
"""
import os
import sys
import ctypes
from ctypes import wintypes
import logging
import time

logger = logging.getLogger(__name__)

user32 = ctypes.windll.user32 if sys.platform == "win32" else None
kernel32 = ctypes.windll.kernel32 if sys.platform == "win32" else None

PROCESS_TERMINATE = 0x0001
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_READ = 0x0010


def get_process_name(pid: int) -> str:
    """Returns the executable file name for the given PID."""
    if not kernel32 or pid <= 0:
        return ""
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
    finally:
        kernel32.CloseHandle(h)
    return ""


def get_process_cmdline(pid: int) -> str:
    """Reads the process command line via PEB."""
    if not kernel32 or pid <= 0:
        return ""
    h = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not h:
        return ""
    try:
        class PROCESS_BASIC_INFORMATION(ctypes.Structure):
            _fields_ = [
                ('Reserved1', ctypes.c_void_p),
                ('PebBaseAddress', ctypes.c_void_p),
                ('Reserved2', ctypes.c_void_p * 2),
                ('UniqueProcessId', ctypes.c_void_p),
                ('Reserved3', ctypes.c_void_p)
            ]

        pbi = PROCESS_BASIC_INFORMATION()
        ret = ctypes.windll.ntdll.NtQueryInformationProcess(
            h, 0, ctypes.byref(pbi), ctypes.sizeof(pbi), None
        )
        if ret != 0 or not pbi.PebBaseAddress:
            return ""

        peb_addr = pbi.PebBaseAddress
        proc_params_addr = ctypes.c_void_p()
        read = ctypes.c_size_t()
        kernel32.ReadProcessMemory(
            h, ctypes.c_void_p(peb_addr + 0x20), ctypes.byref(proc_params_addr), ctypes.sizeof(proc_params_addr), ctypes.byref(read)
        )
        if not proc_params_addr.value:
            return ""

        class UNICODE_STRING(ctypes.Structure):
            _fields_ = [
                ('Length', wintypes.USHORT),
                ('MaximumLength', wintypes.USHORT),
                ('Pad', wintypes.DWORD),
                ('Buffer', ctypes.c_void_p)
            ]

        cmd_str = UNICODE_STRING()
        kernel32.ReadProcessMemory(
            h, ctypes.c_void_p(proc_params_addr.value + 0x70), ctypes.byref(cmd_str), ctypes.sizeof(cmd_str), ctypes.byref(read)
        )
        if not cmd_str.Buffer or cmd_str.Length == 0:
            return ""

        buf = ctypes.create_unicode_buffer(cmd_str.Length // 2)
        kernel32.ReadProcessMemory(
            h, ctypes.c_void_p(cmd_str.Buffer), buf, cmd_str.Length, ctypes.byref(read)
        )
        return buf.value
    except Exception:
        return ""
    finally:
        kernel32.CloseHandle(h)


def kill_previous_instances() -> int:
    """Safe no-op to ensure no external server or cmd windows are terminated."""
    return 0

