"""
KeyFreeze - A Windows utility to temporarily block all keyboard and mouse input
while keeping the screen fully active and visible.

Use cases:
    * Cleaning your keyboard without triggering random key presses.
    * Letting a toddler/pet "watch" a video without interrupting playback.

How it works:
    * Installs global low-level Windows hooks (WH_KEYBOARD_LL + WH_MOUSE_LL) via
      ctypes. While active, every keyboard and mouse event is swallowed
      (the hook returns 1 instead of calling the next hook).
    * The hooks run on a dedicated background thread that pumps the Win32
      message queue (GetMessage). This is REQUIRED - low-level hooks are
      silently removed by Windows if the installing thread does not pump
      messages.
    * The Tk GUI runs on the main thread and talks to the hook thread through
      thread-safe primitives.

Safety / Unlock:
    * Hard-coded, always-working unlock hotkey:  Ctrl + Alt + O
      (detected INSIDE the keyboard hook, so it fires even though every other
      key is blocked).
    * Ctrl + Alt + Del is a Secure Attention Sequence handled by Windows
      itself; it CANNOT be hooked, so it is always available as an OS-level
      escape hatch.
    * An automatic safety timeout unlocks the machine after a configurable
      number of minutes even if nobody presses the hotkey.
    * All hooks are uninstalled on unlock, on window close and on process
      exit, so the computer always returns to normal.

Requires: Windows + standard CPython (tkinter ships with Python). No external
packages are needed.
"""

import atexit
import ctypes
import ctypes.wintypes as wt
import threading
import tkinter as tk
from tkinter import font as tkfont

# --------------------------------------------------------------------------- #
# Win32 constants
# --------------------------------------------------------------------------- #
WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012

# Virtual-key codes we care about for the unlock combo.
VK_CONTROL = 0x11
VK_MENU = 0x12       # ALT
VK_O = 0x4F
# The low-level hook reports modifiers by their LEFT/RIGHT specific codes
# (e.g. VK_LCONTROL, not VK_CONTROL), so we must track all of them.
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4
VK_RMENU = 0xA5

_CTRL_VKS = (VK_CONTROL, VK_LCONTROL, VK_RCONTROL)
_ALT_VKS = (VK_MENU, VK_LMENU, VK_RMENU)

HC_ACTION = 0

# LowLevelKeyboardProc / LowLevelMouseProc signature:
#   LRESULT CALLBACK proc(int nCode, WPARAM wParam, LPARAM lParam)
LRESULT = ctypes.c_ssize_t
ULONG_PTR = wt.WPARAM
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wt.DWORD),
        ("scanCode", wt.DWORD),
        ("flags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# --- argtypes / restypes so ctypes marshals pointers correctly on 64-bit ---
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
user32.SetWindowsHookExW.restype = wt.HHOOK

user32.CallNextHookEx.argtypes = [wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM]
user32.CallNextHookEx.restype = LRESULT

user32.UnhookWindowsHookEx.argtypes = [wt.HHOOK]
user32.UnhookWindowsHookEx.restype = wt.BOOL

user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.GetMessageW.restype = wt.BOOL

user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.PostThreadMessageW.restype = wt.BOOL

kernel32.GetCurrentThreadId.restype = wt.DWORD



# --------------------------------------------------------------------------- #
# InputBlocker: owns the hook thread + the low-level hooks.
# --------------------------------------------------------------------------- #
class InputBlocker:
    """Installs/removes global low-level keyboard & mouse hooks on a dedicated
    message-pumping thread."""

    def __init__(self, on_unlock_hotkey):
        """on_unlock_hotkey: callable invoked (from the hook thread) when the
        Ctrl+Alt+O combo is detected."""
        self._on_unlock_hotkey = on_unlock_hotkey
        self._thread = None
        self._thread_id = None
        self._kbd_handle = None
        self._mouse_handle = None
        self._active = False
        self._ready = threading.Event()

        # Ctrl / Alt state for the unlock combo. We track this ourselves
        # because BOTH GetKeyState() and GetAsyncKeyState() read 0 inside this
        # hook: swallowing the modifier keydown prevents Windows from updating
        # its key-state table, so the only reliable source is the hook's own
        # keydown/keyup events.
        self._ctrl_down = False
        self._alt_down = False

        # Keep references so the callbacks are not garbage-collected while the
        # hooks are installed (that would crash the process).
        self._kbd_proc = HOOKPROC(self._keyboard_proc)
        self._mouse_proc = HOOKPROC(self._mouse_proc)

    # ---- the actual hook callbacks (run on the hook thread) --------------- #
    def _keyboard_proc(self, nCode, wParam, lParam):
        if nCode == HC_ACTION and self._active:
            kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            vk = kb.vkCode
            is_down = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)

            # Track Ctrl / Alt state ourselves. GetKeyState() reads per-thread
            # state (never updated, because we swallow every key), and
            # GetAsyncKeyState() ALSO reads 0 here for the same reason:
            # swallowing a keydown stops Windows from updating its key-state
            # table. Watching the modifier keydown/keyup events directly is the
            # only reliable approach.
            if vk in _CTRL_VKS:
                self._ctrl_down = is_down
            elif vk in _ALT_VKS:
                self._alt_down = is_down

            # Unlock combo: Ctrl + Alt + O (detected inside the hook, so it
            # fires even though every other key is blocked).
            if is_down and vk == VK_O and self._ctrl_down and self._alt_down:
                try:
                    self._on_unlock_hotkey()
                except Exception:
                    pass

            # Swallow EVERY keyboard event while active.
            return 1
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    def _mouse_proc(self, nCode, wParam, lParam):
        if nCode == HC_ACTION and self._active:
            # Swallow EVERY mouse event (move, click, wheel) while active.
            return 1
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    # ---- hook thread ------------------------------------------------------ #
    def _run(self):
        self._thread_id = kernel32.GetCurrentThreadId()

        self._kbd_handle = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._kbd_proc, None, 0
        )
        self._mouse_handle = user32.SetWindowsHookExW(
            WH_MOUSE_LL, self._mouse_proc, None, 0
        )
        self._ready.set()

        if not self._kbd_handle or not self._mouse_handle:
            # Failed to install - bail out cleanly.
            self._cleanup_hooks()
            return

        # Pump the message queue. GetMessage blocks; low-level hooks require
        # this pump to keep delivering events. The loop ends when we
        # PostThreadMessage(WM_QUIT) from stop().
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass

        self._cleanup_hooks()

    def _cleanup_hooks(self):
        if self._kbd_handle:
            user32.UnhookWindowsHookEx(self._kbd_handle)
            self._kbd_handle = None
        if self._mouse_handle:
            user32.UnhookWindowsHookEx(self._mouse_handle)
            self._mouse_handle = None

    # ---- public API (called from the Tk thread) -------------------------- #
    def start(self):
        """Install the hooks and begin swallowing input. Returns True on success."""
        # Fresh lock: assume no modifier is held (we can't see keys pressed
        # while the hook was inactive).
        self._ctrl_down = False
        self._alt_down = False

        if self._thread and self._thread.is_alive():
            self._active = True
            return True

        self._ready.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        # Wait until hooks are installed (or installation failed).
        self._ready.wait(timeout=5)
        if not (self._kbd_handle and self._mouse_handle):
            return False
        self._active = True
        return True

    def stop(self):
        """Stop swallowing input and tear down the hook thread cleanly."""
        self._active = False
        if self._thread and self._thread.is_alive() and self._thread_id:
            # Ask the hook thread's GetMessage loop to exit.
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread.join(timeout=5)
        self._thread = None
        self._thread_id = None
        # Belt-and-braces: make sure handles are gone.
        self._cleanup_hooks()

    @property
    def is_active(self):
        return self._active


# --------------------------------------------------------------------------- #
# GUI
# --------------------------------------------------------------------------- #
class KeyFreezeApp:
    DEFAULT_COUNTDOWN = 5          # seconds before input is blocked (3..5)
    SAFETY_TIMEOUT_MIN = 1        # auto-unlock after this many minutes

    def __init__(self, root):
        self.root = root
        self.root.title("KeyFreeze")
        self.root.geometry("420x330")
        self.root.resizable(False, False)

        # Thread-safe flag used by the hook thread to request an unlock.
        self._unlock_requested = threading.Event()

        self.blocker = InputBlocker(on_unlock_hotkey=self._request_unlock)

        self._overlay = None
        self._banner = None
        self._cd_label = None
        self._countdown_job = None
        self._poll_job = None
        self._safety_job = None

        self._build_ui()

        # Make sure we always clean up, even on unexpected close.
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        atexit.register(self._emergency_cleanup)

    # ---- UI construction ------------------------------------------------- #
    def _build_ui(self):
        title_font = tkfont.Font(family="Segoe UI", size=18, weight="bold")
        btn_font = tkfont.Font(family="Segoe UI", size=16, weight="bold")
        info_font = tkfont.Font(family="Segoe UI", size=9)

        tk.Label(self.root, text="KeyFreeze", font=title_font).pack(pady=(18, 2))
        tk.Label(
            self.root,
            text="Temporarily block keyboard & mouse\n(screen stays on).",
            justify="center",
        ).pack(pady=(0, 10))

        # Countdown selector.
        frm = tk.Frame(self.root)
        frm.pack(pady=(0, 8))
        tk.Label(frm, text="Countdown:").pack(side="left")
        self.countdown_var = tk.IntVar(value=self.DEFAULT_COUNTDOWN)
        tk.Spinbox(
            frm, from_=3, to=5, width=4, textvariable=self.countdown_var,
            state="readonly", justify="center",
        ).pack(side="left", padx=6)
        tk.Label(frm, text="sec").pack(side="left")

        self.lock_btn = tk.Button(
            self.root,
            text="\U0001F512  Lock Input",
            font=btn_font,
            bg="#2d7d46",
            fg="white",
            activebackground="#256b3b",
            activeforeground="white",
            width=18,
            height=2,
            command=self._on_lock_clicked,
        )
        self.lock_btn.pack(pady=10)

        self.status = tk.Label(self.root, text="Ready.", fg="#333")
        self.status.pack()

        tk.Label(
            self.root,
            text="Unlock while locked:  Ctrl + Alt + O\n"
                 "(Ctrl + Alt + Del also always works.)",
            font=info_font,
            fg="#666",
            justify="center",
        ).pack(side="bottom", pady=10)

    # ---- locking flow ---------------------------------------------------- #
    def _on_lock_clicked(self):
        if self.blocker.is_active:
            return
        self.lock_btn.config(state="disabled")
        seconds = int(self.countdown_var.get())
        self._show_countdown(seconds)

    def _show_countdown(self, seconds):
        self._overlay = self._make_overlay()
        self._cd_label = tk.Label(
            self._overlay,
            text="",
            font=tkfont.Font(family="Segoe UI", size=120, weight="bold"),
            fg="white",
            bg="black",
        )
        self._cd_label.place(relx=0.5, rely=0.42, anchor="center")
        tk.Label(
            self._overlay,
            text="Move your hands away \u2014 input will be blocked\u2026",
            font=tkfont.Font(family="Segoe UI", size=20),
            fg="#cccccc",
            bg="black",
        ).place(relx=0.5, rely=0.62, anchor="center")

        self._tick_countdown(seconds)

    def _tick_countdown(self, remaining):
        if remaining <= 0:
            self._engage_lock()
            return
        self._cd_label.config(text=str(remaining))
        self.status.config(text=f"Locking in {remaining}\u2026")
        self._countdown_job = self.root.after(
            1000, lambda: self._tick_countdown(remaining - 1)
        )

    def _engage_lock(self):
        ok = self.blocker.start()
        if not ok:
            self._destroy_overlay()
            self.lock_btn.config(state="normal")
            self.status.config(
                text="ERROR: could not install hooks.", fg="#b00020"
            )
            return

        self._unlock_requested.clear()
        self._show_locked_overlay()
        self.status.config(
            text="LOCKED. Press Ctrl+Alt+O to unlock.", fg="#b00020"
        )

        # Poll for an unlock request coming from the hook thread.
        self._poll_unlock()
        # Safety auto-unlock.
        self._safety_job = self.root.after(
            self.SAFETY_TIMEOUT_MIN * 60 * 1000, self._do_unlock
        )

    def _show_locked_overlay(self):
        # IMPORTANT: once input is actually blocked we do NOT cover the screen.
        # The whole point of KeyFreeze is that the screen stays fully visible
        # (e.g. so you can keep watching a video) while keyboard & mouse are
        # disabled. So we tear down the fullscreen countdown overlay and show a
        # small, non-fullscreen "locked" banner that stays out of the way.
        self._destroy_overlay()
        self._show_locked_banner()

    def _show_locked_banner(self):
        """Tiny always-on-top banner shown while input is locked.

        It occupies only a small strip at the top of the screen so the rest of
        the display (your video) remains fully visible.
        """
        banner = tk.Toplevel(self.root)
        banner.configure(bg="black")
        banner.overrideredirect(True)
        banner.attributes("-topmost", True)
        try:
            banner.attributes("-alpha", 0.82)
        except Exception:
            pass

        screen_w = banner.winfo_screenwidth()
        width, height = 520, 44
        x = (screen_w - width) // 2
        banner.geometry(f"{width}x{height}+{x}+0")

        tk.Label(
            banner,
            text="\U0001F512  INPUT LOCKED \u2014 press  Ctrl + Alt + O  to unlock",
            font=tkfont.Font(family="Segoe UI", size=12, weight="bold"),
            fg="white",
            bg="black",
        ).place(relx=0.5, rely=0.5, anchor="center")

        self._banner = banner

    def _poll_unlock(self):
        if self._unlock_requested.is_set():
            self._do_unlock()
            return
        self._poll_job = self.root.after(100, self._poll_unlock)

    # Called from the HOOK THREAD - must be thread-safe, so just set a flag.
    def _request_unlock(self):
        self._unlock_requested.set()

    def _do_unlock(self):
        # Cancel pending timers.
        for job in (self._poll_job, self._safety_job, self._countdown_job):
            if job:
                try:
                    self.root.after_cancel(job)
                except Exception:
                    pass
        self._poll_job = self._safety_job = self._countdown_job = None

        self.blocker.stop()
        self._destroy_overlay()
        self._destroy_banner()
        self.lock_btn.config(state="normal")
        self.status.config(text="Unlocked. Ready.", fg="#2d7d46")

    # ---- overlay helpers ------------------------------------------------- #
    def _make_overlay(self):
        top = tk.Toplevel(self.root)
        top.configure(bg="black")
        top.attributes("-fullscreen", True)
        top.attributes("-topmost", True)
        top.overrideredirect(True)
        top.config(cursor="none")
        return top

    def _destroy_overlay(self):
        if self._overlay is not None:
            try:
                self._overlay.destroy()
            except Exception:
                pass
            self._overlay = None

    def _destroy_banner(self):
        if self._banner is not None:
            try:
                self._banner.destroy()
            except Exception:
                pass
            self._banner = None

    # ---- shutdown -------------------------------------------------------- #
    def _on_close(self):
        if self.blocker.is_active:
            self._do_unlock()
        self._emergency_cleanup()
        self.root.destroy()

    def _emergency_cleanup(self):
        try:
            self.blocker.stop()
        except Exception:
            pass


def main():
    root = tk.Tk()
    KeyFreezeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
