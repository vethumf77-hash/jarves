# Building the Windows installer (Jarvis-Setup.exe)

This kit turns Jarvis into a normal Windows program. Your customer gets **one file** -
`Jarvis-Setup.exe` - runs it, **types their Groq API key on the 2nd screen**, and Jarvis is
installed and runs on that key. No Python, no command line, no editing files on their side.

## Where the API key is entered (important)

* **NOT** in `build_installer.bat`. That script only *builds* the installer; it never asks for a key.
  (Typing or pasting into its window does nothing - and used to close it.)
* The key screen is **inside `Jarvis-Setup.exe`**: Welcome -> **Enter your Groq API key** -> folder -> ...
  It cannot be skipped. If a key from an earlier install exists it is filled in for you.

## What the customer sees

1. Double-click `Jarvis-Setup.exe` (no administrator password needed - it installs for their user).
2. **Welcome**, then the **"Enter your Groq API key"** screen.
   - They paste the key (Ctrl+V or right-click > Paste). Setup refuses an empty key and asks Groq
     whether it works, so a typo is caught immediately ("Groq rejected this API key").
   - A clickable link to console.groq.com/keys is shown for people who don't have a key yet.
3. Folder / shortcut options > Install > "Start Jarvis now". Jarvis opens already knowing the key.
4. The key is stored in `%LOCALAPPDATA%\Jarvis\.env` on their PC only. They can change it any time in
   Jarvis > Settings (there is a **Paste** button). Uninstalling deletes it.

If a PC lacks Microsoft's Visual C++ runtime (common on clean Windows), the installer adds it
automatically (Windows may show one permission prompt). Silent/IT install:
`Jarvis-Setup.exe /VERYSILENT /KEY=gsk_theirkey`

## What you do (once per release)

Needs: Windows 10/11 (64-bit), internet, **Python 3.10+** (the one Jarvis already runs on).
Inno Setup is installed for you by the script if it is missing (it asks first).

1. Open `jarvis_installer.iss` and change `MyAppPublisher` (and `MyAppVersion` for updates).
2. Double-click **`build_installer.bat`** and wait ~10-15 minutes. The window now **stays open**.
3. It self-tests the packaged program (`Jarvis.exe --selftest`) and prints a PASS/WARN/FAIL report.
   Any FAIL means that build would not work on a customer's PC - send me that text.
4. Your installer appears at **`release\Jarvis-Setup.exe`**; the script offers to open it so you can
   try the key screen yourself.

## Test before you ship

Run `Jarvis-Setup.exe` on a PC (or Windows Sandbox / a VM) that does **not** have Python or your project:
enter a key, start Jarvis, say "Hey Jarvis", try volume, a screenshot, and hand mouse.
Logs: `%LOCALAPPDATA%\Jarvis\jarvis.log`. Health check any time: `Jarvis.exe --selftest`
(writes `%LOCALAPPDATA%\Jarvis\selftest.txt`).

## Good to know

- **Windows 10 (1809) or newer, 64-bit.** The installer refuses older systems.
- **Microphone / camera permission:** Windows Settings > Privacy & security > Microphone (and Camera)
  must allow desktop apps, or Jarvis can't hear / see.
- **Size:** the installer is large (several hundred MB) because of the speech/hand-tracking libraries.
- **"Windows protected your PC" (SmartScreen):** an unsigned installer shows this on other people's PCs -
  *More info > Run anyway*. A code-signing certificate removes it. Antivirus false alarms are also
  possible with any bundled Python app; signing helps there too.
- **Each customer uses their own Groq key** (free tier is fine). Never put your own key in the build.
- Files the program writes (key, settings, logs) go to `%LOCALAPPDATA%\Jarvis`, never the install folder.
- Running from source still works (`python app.py`, or `run_debug.bat`).
