"""
Window Finder module for STOVE Epic Seven PC client using native Win32 ctypes.
Zero external DLL dependencies.
"""
import ctypes
from ctypes import wintypes
import os
from typing import List, Optional, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

# Windows API Types and Constants
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# Enable DPI awareness if possible so coordinates match exact physical pixels
try:
    # Per-Monitor V2 DPI awareness (Windows 10 1703+)
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


@dataclass
class WindowInfo:
    """Detailed information about an identified window."""
    hwnd: int
    title: str
    class_name: str
    pid: int
    process_name: str
    window_rect: Tuple[int, int, int, int]  # (left, top, right, bottom)
    client_rect: Tuple[int, int, int, int]  # (left, top, right, bottom)
    client_size: Tuple[int, int]            # (width, height)
    is_minimized: bool

    def __repr__(self) -> str:
        w, h = self.client_size
        return (
            f"<WindowInfo hwnd=0x{self.hwnd:X} title='{self.title}' "
            f"process='{self.process_name}' client={w}x{h} minimized={self.is_minimized}>"
        )


class WindowFinder:
    """Finds and inspects Windows processes and windows."""

    DEFAULT_TARGET_TITLES = ["Epic Seven", "에픽세븐", "EpicSeven"]
    DEFAULT_TARGET_PROCESSES = ["epicseven.exe", "stove.exe", "epic7.exe"]

    @staticmethod
    def ensure_default_desktop() -> None:
        """Ensures the current thread is attached to the interactive 'default' desktop on WinSta0."""
        try:
            hwinsta = user32.OpenWindowStationW("WinSta0", False, 0x0000037F)
            if hwinsta:
                user32.SetProcessWindowStation(hwinsta)
            h_default = user32.OpenDesktopW("default", 0, False, 0x01FF)
            if not h_default:
                h_default = user32.OpenDesktopW("default", 0, False, 0x0041)
            if not h_default:
                h_default = user32.OpenDesktopW("default", 0, False, 0x10000000)
            if h_default:
                user32.SetThreadDesktop(h_default)
        except Exception:
            pass

    @staticmethod
    def get_window_text(hwnd: int) -> str:
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value

    @staticmethod
    def get_class_name(hwnd: int) -> str:
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        return buf.value

    @staticmethod
    def _get_process_name_by_snapshot(target_pid: int) -> str:
        """Fallback to retrieve process name using Toolhelp32Snapshot if OpenProcess is denied by UIPI."""
        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [
                ('dwSize', wintypes.DWORD),
                ('cntUsage', wintypes.DWORD),
                ('th32ProcessID', wintypes.DWORD),
                ('th32DefaultHeapID', ctypes.c_size_t),
                ('th32ModuleID', wintypes.DWORD),
                ('cntThreads', wintypes.DWORD),
                ('th32ParentProcessID', wintypes.DWORD),
                ('pcPriClassBase', wintypes.LONG),
                ('dwFlags', wintypes.DWORD),
                ('szExeFile', ctypes.c_char * 260)
            ]

        try:
            h_snap = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
            if not h_snap or h_snap == ctypes.c_void_p(-1).value:
                return ""
            pe = PROCESSENTRY32()
            pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
            if kernel32.Process32First(h_snap, ctypes.byref(pe)):
                while True:
                    if pe.th32ProcessID == target_pid:
                        kernel32.CloseHandle(h_snap)
                        return pe.szExeFile.decode('utf-8', errors='ignore')
                    if not kernel32.Process32Next(h_snap, ctypes.byref(pe)):
                        break
            kernel32.CloseHandle(h_snap)
        except Exception:
            pass
        return ""

    _proc_name_cache = {}

    @classmethod
    def get_process_info(cls, hwnd: int) -> Tuple[int, str]:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process_id = pid.value
        if not process_id:
            return 0, ""

        if process_id in cls._proc_name_cache:
            return process_id, cls._proc_name_cache[process_id]

        process_name = ""
        h_process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, process_id)
        if h_process:
            try:
                buf = ctypes.create_unicode_buffer(1024)
                size = wintypes.DWORD(1024)
                if kernel32.QueryFullProcessImageNameW(h_process, 0, buf, ctypes.byref(size)):
                    process_name = os.path.basename(buf.value)
            finally:
                kernel32.CloseHandle(h_process)

        cls._proc_name_cache[process_id] = process_name
        return process_id, process_name

    @staticmethod
    def get_rects(hwnd: int) -> Tuple[Tuple[int, int, int, int], Tuple[int, int, int, int], Tuple[int, int]]:
        """
        Returns:
            (window_rect, client_rect, client_size)
        """
        w_rect = wintypes.RECT()
        c_rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(w_rect))
        user32.GetClientRect(hwnd, ctypes.byref(c_rect))

        window_rect = (w_rect.left, w_rect.top, w_rect.right, w_rect.bottom)
        client_rect = (c_rect.left, c_rect.top, c_rect.right, c_rect.bottom)
        client_size = (c_rect.right - c_rect.left, c_rect.bottom - c_rect.top)
        return window_rect, client_rect, client_size

    @classmethod
    def get_window_info(cls, hwnd: int) -> Optional[WindowInfo]:
        if not user32.IsWindow(hwnd):
            return None
        title = cls.get_window_text(hwnd)
        class_name = cls.get_class_name(hwnd)
        pid, proc_name = cls.get_process_info(hwnd)
        w_rect, c_rect, c_size = cls.get_rects(hwnd)
        is_minimized = bool(user32.IsIconic(hwnd))
        if is_minimized and c_size == (0, 0):
            class WINDOWPLACEMENT(ctypes.Structure):
                _fields_ = [
                    ('length', wintypes.UINT),
                    ('flags', wintypes.UINT),
                    ('showCmd', wintypes.UINT),
                    ('ptMinPosition', wintypes.POINT),
                    ('ptMaxPosition', wintypes.POINT),
                    ('rcNormalPosition', wintypes.RECT),
                ]
            wp = WINDOWPLACEMENT()
            wp.length = ctypes.sizeof(WINDOWPLACEMENT)
            if user32.GetWindowPlacement(hwnd, ctypes.byref(wp)):
                rc = wp.rcNormalPosition
                norm_w = max(0, rc.right - rc.left - 16)
                norm_h = max(0, rc.bottom - rc.top - 39)
                c_size = (norm_w, norm_h)

        # If title is empty due to UIPI or GLFW, default to process name or "에픽세븐"
        if not title:
            if proc_name.lower() == "epicseven.exe" or class_name == "GLFW30":
                title = "에픽세븐"

        return WindowInfo(
            hwnd=hwnd,
            title=title,
            class_name=class_name,
            pid=pid,
            process_name=proc_name,
            window_rect=w_rect,
            client_rect=c_rect,
            client_size=c_size,
            is_minimized=is_minimized,
        )

    @classmethod
    def find_all_windows(
        cls,
        visible_only: bool = True,
        title_keywords: Optional[List[str]] = None,
        process_names: Optional[List[str]] = None,
    ) -> List[WindowInfo]:
        """Enumerate all top-level windows, optionally filtered by title or process name."""
        cls.ensure_default_desktop()
        h_desk = user32.OpenDesktopW("default", 0, False, 0x01FF)
        if not h_desk:
            h_desk = user32.OpenDesktopW("default", 0, False, 0x0041)
        if not h_desk:
            h_desk = user32.OpenDesktopW("default", 0, False, 0x10000000)
        if h_desk:
            user32.SetThreadDesktop(h_desk)

        windows_result: List[WindowInfo] = []
        seen_hwnds = set()

        def enum_window_callback(hwnd, _):
            if hwnd in seen_hwnds:
                return True
            seen_hwnds.add(hwnd)
            info = cls.get_window_info(hwnd)
            if not info:
                return True
            is_epic = (info.class_name == "GLFW30" or "epicseven" in info.process_name.lower())
            if visible_only and not is_epic:
                if not user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
                    return True
            if info.title or is_epic:
                windows_result.append(info)
            return True

        cb = WNDENUMPROC(enum_window_callback)
        if h_desk:
            user32.EnumDesktopWindows(h_desk, cb, 0)
            user32.CloseDesktop(h_desk)

        # Also enumerate top-level windows via EnumWindows
        user32.EnumWindows(cb, 0)

        if title_keywords or process_names:
            titles = [t.lower() for t in (title_keywords or [])]
            procs = [p.lower() for p in (process_names or [])]
            filtered = []
            for win in windows_result:
                t_lower = win.title.lower()
                p_lower = win.process_name.lower()
                title_match = any(t in t_lower for t in titles) if titles else False
                proc_match = any(p in p_lower for p in procs) if procs else False
                class_match = (win.class_name == "GLFW30" and (win.client_size[0] >= 320 or win.is_minimized))
                if title_match or proc_match or class_match:
                    filtered.append(win)
            return filtered

        return windows_result

    @classmethod
    def find_target_window(
        cls,
        title_keywords: Optional[List[str]] = None,
        process_names: Optional[List[str]] = None,
    ) -> Optional[WindowInfo]:
        """
        Find STOVE Epic Seven client window by matching title or process name.
        """
        cls.ensure_default_desktop()
        titles = [t.lower() for t in (title_keywords or cls.DEFAULT_TARGET_TITLES)]
        procs = [p.lower() for p in (process_names or cls.DEFAULT_TARGET_PROCESSES)]

        all_wins = cls.find_all_windows(visible_only=False)
        # Priority 1: Match by GLFW30 class name and valid size
        for win in all_wins:
            if win.class_name == "GLFW30" and (win.client_size[0] >= 320 or win.is_minimized):
                if "_thread_" not in win.title and "message" not in win.title.lower():
                    logger.info("Found game window by GLFW30 class: %s", win)
                    return win

        # Priority 2: Match by process name (excluding NVOpenGLPbuffer and helper threads)
        for win in all_wins:
            p_lower = win.process_name.lower()
            if any(proc in p_lower for proc in procs):
                if win.class_name not in ("NVOpenGLPbuffer", "MSCTFIME UI", "IME"):
                    if "_thread_" not in win.title and "message" not in win.title.lower():
                        w, h = win.client_size
                        if (w >= 320 and h >= 180) or win.is_minimized:
                            logger.info("Found game window by process name: %s", win)
                            return win

        # Priority 3: Exact or substring match in title
        for win in all_wins:
            t_lower = win.title.lower()
            if any(target in t_lower for target in titles):
                w, h = win.client_size
                if (w >= 320 and h >= 180) or win.is_minimized:  # exclude tiny tooltips / splash
                    logger.info("Found game window by title: %s", win)
                    return win

        return None
