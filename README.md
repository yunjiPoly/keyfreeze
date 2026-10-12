One-Prompter message to Claude Opus 5.5

Act as an expert Windows desktop application developer. I want you to write the complete code for a Windows utility similar to "KeyFreeze."

The application's goal is to block all keyboard and mouse input from the user while keeping the screen fully active and visible (useful for cleaning a keyboard or letting a toddler watch a video without interrupting it).

Please write this application in Python (using tkinter or customtkinter for a simple UI, and ctypes or the keyboard/mouse libraries for the input blocking).

Requirements:

User Interface: A simple GUI with a large "Lock Input" button.

Countdown: When the button is clicked, show a 3 to 5-second countdown on the screen before the input is actually blocked, giving the user time to move their hands away.

Input Blocking: Use Windows Low-Level Hooks (WH_KEYBOARD_LL and WH_MOUSE_LL via ctypes, or a reliable wrapper library) to intercept and discard all keyboard presses and mouse movements/clicks. Do NOT just use BlockInput() as it requires strict Admin privileges.

Safety / Unlock Mechanism: Include a hardcoded, unblockable hotkey combination to restore input (e.g., Ctrl + Alt + U or relying on the native OS Ctrl + Alt + Del).

Graceful Exit: Make sure that when the input is unlocked, the hooks are cleanly removed so the user's computer functions normally again.

Please provide the complete, runnable code, along with a requirements.txt if any external libraries are needed, and brief instructions on how to run it safely.
