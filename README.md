# KeyFreeze

A small Windows utility that temporarily **blocks all keyboard and mouse input**
while keeping the screen fully on and visible.

Useful for:
- Cleaning your keyboard without triggering random key presses.
- Letting a toddler / pet "watch" a video without pausing or closing it.

## How it works

- Installs global **low-level Windows hooks** (`WH_KEYBOARD_LL` + `WH_MOUSE_LL`)
  via `ctypes`. While active, every keyboard and mouse event is swallowed.
- The hooks run on a **dedicated background thread that pumps the Win32 message
  queue**. This is required — Windows silently removes low-level hooks whose
  installing thread does not pump messages.
- It does **not** use `BlockInput()` (which needs elevated/UIAccess rights and
  is easy for the OS to ignore).

## Requirements

- **Windows** (uses `user32.dll` / `kernel32.dll`).
- **Python 3.8+** (tested on 3.13). `tkinter` ships with the official CPython
  Windows installer.
- **No external packages.** See `requirements.txt`.

## Run

```powershell
python keyfreeze.py
```

1. Pick a countdown (3–5 seconds).
2. Click **🔒 Lock Input**.
3. A full-screen countdown gives you time to move your hands away, then input
   is blocked and a "INPUT LOCKED" screen is shown.

## Unlocking (important — read before you lock!)

- **Primary hotkey:** `Ctrl + Alt + O` — works even while everything else is
  blocked, because it is detected *inside* the keyboard hook.
- **OS escape hatch:** `Ctrl + Alt + Del` — the Windows Secure Attention
  Sequence can never be hooked, so it always works. From that screen press
  *Escape* to return, or *Sign out* if needed.
- **Automatic safety timeout:** input auto-unlocks after 15 minutes even if no
  key is pressed (change `SAFETY_TIMEOUT_MIN` in `keyfreeze.py`).
- Closing the KeyFreeze window also unlocks and removes the hooks.

## Safety notes

- Hooks are always removed on unlock, on window close, and on process exit
  (via `UnhookWindowsHookEx` + an `atexit` handler), so your machine returns to
  normal.
- No administrator privileges are required for normal use. (If another app is
  running elevated, its windows may still receive input because an unelevated
  hook cannot block a higher-integrity process — a Windows security rule. For
  full coverage you can run KeyFreeze elevated, but it is not required for the
  typical "clean the keyboard / toddler video" use case.)
- Test it the first time with the auto-unlock timeout in mind, and keep
  `Ctrl+Alt+Del` in your back pocket.

## Optional: build a standalone .exe

```powershell
pip install pyinstaller

# 1. Generate the lock icon (keyfreeze.ico) using only the standard library.
python build_icon.py

# 2. Build a single-file, no-console exe with that icon.
pyinstaller --noconsole --onefile --icon keyfreeze.ico --name KeyFreeze keyfreeze.py
```

The finished app is `dist\KeyFreeze.exe`.

To put an icon on the desktop (so you can launch it instead of the original
KeyFreeze), run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File create_shortcut.ps1
```

That creates a `KeyFreeze.lnk` on your desktop pointing at `dist\KeyFreeze.exe`
with the padlock icon embedded in the exe.
