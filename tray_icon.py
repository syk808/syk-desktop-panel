"""System-tray icon for a Tk app, with ctypes only (no pystray / pywin32).

Create it on the Tk thread: Tk's event loop is an ordinary Windows message loop, so the hidden
message window made here gets its callbacks from that same loop and may touch Tk directly.

    tray = TrayIcon("icon.ico", "My app", on_click=restore)
    tray.show(); tray.set_tip("12:30 · BTC 82,000"); tray.hide()
"""
import ctypes
from ctypes import wintypes

user32, shell32, kernel32 = ctypes.windll.user32, ctypes.windll.shell32, ctypes.windll.kernel32

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
WM_APP_TRAY = 0x8000 + 1
WM_LBUTTONUP, WM_LBUTTONDBLCLK, WM_RBUTTONUP = 0x0202, 0x0203, 0x0205
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 1, 2, 4
IMAGE_ICON, LR_LOADFROMFILE, LR_DEFAULTSIZE = 1, 0x10, 0x40
HWND_MESSAGE = wintypes.HWND(-3)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HANDLE),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HANDLE),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HANDLE),
                ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD), ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", wintypes.HANDLE)]


user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wintypes.HWND, wintypes.HANDLE, wintypes.HINSTANCE, wintypes.LPVOID]
user32.LoadImageW.restype = wintypes.HANDLE
user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.DestroyWindow.argtypes = [wintypes.HWND]
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

_seq = 0


class TrayIcon:
    def __init__(self, ico_path, tip="", on_click=None, on_right_click=None):
        global _seq
        _seq += 1
        self.on_click, self.on_right_click = on_click, on_right_click
        self.visible = False
        self._proc = WNDPROC(self._wndproc)                 # keep a reference or the callback is collected
        inst = kernel32.GetModuleHandleW(None)
        cls = WNDCLASSW()
        cls.lpfnWndProc, cls.hInstance, cls.lpszClassName = self._proc, inst, "SYKTray%d" % _seq
        if not user32.RegisterClassW(ctypes.byref(cls)):
            raise OSError("RegisterClassW failed")
        self.hwnd = user32.CreateWindowExW(0, cls.lpszClassName, "SYK tray", 0, 0, 0, 0, 0, HWND_MESSAGE, None, inst, None)
        if not self.hwnd:
            raise OSError("CreateWindowExW failed")
        self.hicon = user32.LoadImageW(None, ico_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)
        if not self.hicon:
            raise OSError("could not load icon: %s" % ico_path)
        self.nid = NOTIFYICONDATAW()
        self.nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        self.nid.hWnd, self.nid.uID = self.hwnd, 1
        self.nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        self.nid.uCallbackMessage, self.nid.hIcon, self.nid.szTip = WM_APP_TRAY, self.hicon, tip[:127]

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_APP_TRAY:
            event = lparam & 0xFFFF
            try:
                if event in (WM_LBUTTONUP, WM_LBUTTONDBLCLK) and self.on_click:
                    self.on_click()
                elif event == WM_RBUTTONUP and self.on_right_click:
                    self.on_right_click()
            except Exception:
                pass                                        # never let an exception cross into the window procedure
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def show(self):
        if not self.visible:
            self.visible = bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self.nid)))
        return self.visible

    def set_tip(self, tip):
        self.nid.szTip = tip[:127]
        if self.visible:
            shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self.nid))

    def hide(self):
        if self.visible:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self.nid))
            self.visible = False

    def destroy(self):
        self.hide()
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)
            self.hwnd = None
