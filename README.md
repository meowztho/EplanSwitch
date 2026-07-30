# ePlan Switch

A lightweight Windows tray application for quickly switching between configurable power profiles.

**ePlan Switch** can apply CPU limits, processor boost modes, cooling policies, display timeouts, sleep timeouts, and hibernation timeouts. It also includes a graphical configuration editor, global hotkey support, Windows autostart, and basic Windows power-plan management.

> Current application version: **1.3.0**  
> Supported platform: **Windows 10 / Windows 11**

## Features

- Global hotkey for switching between two configurable profiles
- Default hotkey: **Ctrl + F12**
- German and English user interface
- System tray menu with direct profile selection
- Small fading status popup
- Graphical configuration editor
- External `config.json` that remains editable after building the EXE
- Separate AC and battery settings
- Per-user Windows autostart option
- Automatic detection of installed Windows power plans
- Restoration of missing Windows standard power plans
- Activation and removal of unused power plans
- Optional custom `logo.ico` or `logo.png`
- Single-file Windows build through PyInstaller

## Default Profiles

### Summer / Browsing

Designed to reduce CPU power consumption and heat during light desktop work.

- Minimum processor state: **5%**
- Maximum processor state: **50%**
- Processor boost mode: **Disabled**
- Cooling policy: **Active**
- Display timeout: **Never**
- Sleep timeout: **Never**
- Hibernation timeout: **Never**

### Performance

Designed for gaming, rendering, compilation, and other demanding workloads.

- Minimum processor state: **5%**
- Maximum processor state: **100%**
- Processor boost mode: **Aggressive**
- Cooling policy: **Active**
- Display timeout: **Never**
- Sleep timeout: **Never**
- Hibernation timeout: **Never**

All values can be changed through the graphical editor or directly in `config.json`.

## Screens and Controls

The configuration editor provides the following sections:

- **General**
  - Language
  - Windows autostart
  - Global hotkey
  - Startup popup
  - Apply the active profile at application startup
  - Popup duration, size, and position
- **Profile settings**
  - Windows power plan assignment
  - Processor minimum and maximum state
  - Processor boost mode
  - Cooling policy
  - Display timeout
  - Sleep timeout
  - Hibernation timeout
  - Separate settings for AC and battery power
- **Power plans**
  - Reload installed plans from Windows
  - Mark the currently active plan
  - Activate a selected plan
  - Restore a missing Windows standard plan
  - Remove an inactive and unused plan

## Power Plan Management

ePlan Switch reads installed plans through Windows `powercfg` whenever the power-plan page is opened and after every plan change.

Supported Windows standard plans:

- Power saver
- Balanced
- High performance
- Ultimate Performance

A missing standard plan can be restored individually. The application intentionally does **not** use `powercfg /restoredefaultschemes`, because that command may remove custom power plans.

### Removing a Power Plan

The **Disable / Remove** action uses `powercfg /delete`.

The following plans are protected and cannot be removed from the application:

- The currently active Windows power plan
- A plan currently assigned to one of the two switch profiles

Custom plans cannot be restored automatically after deletion. Back up important custom plans before removing them.

## Timeout Values

Timeout fields use minutes:

| Value | Meaning |
|---:|---|
| `0` | Never turn off, sleep, or hibernate |
| Blank / `null` | Do not modify the existing Windows value |
| Positive number | Timeout in minutes |

## Running from Python

### Requirements

- Windows 10 or Windows 11
- Python 3 with the Windows Python Launcher (`py`)

Install the dependencies:

```powershell
py -3 -m pip install -r requirements.txt
```

Start the application:

```powershell
py -3 power_plan_switcher.py
```

Alternatively, double-click:

```text
start-python.bat
```

## Building the EXE

1. Place an optional `logo.ico` or `logo.png` in the project directory.
2. Double-click `build.bat`.
3. The script creates a local virtual environment, installs the required packages, and runs PyInstaller.

The current build script creates:

```text
dist\Energieplan-Umschalter.exe
```

Keep these files together:

```text
Energieplan-Umschalter.exe
config.json
logo.ico or logo.png        optional
README.md
README_EN.md
VERSION.txt
```

The repository can be named **ePlan Switch** independently of the current executable filename.

## Configuration

The external `config.json` contains all user-editable settings. The application automatically supplements older compatible configuration files with newly introduced default values.

Basic structure:

```json
{
  "schema_version": 2,
  "app": {
    "language": "en",
    "autostart": false,
    "hotkey": {
      "key": "F12",
      "ctrl": true,
      "alt": false,
      "shift": false,
      "win": false
    },
    "toggle_profiles": [
      "summer",
      "performance"
    ]
  },
  "profiles": {
    "summer": {},
    "performance": {}
  }
}
```

Supported interface languages:

```text
de
 en
```

The graphical editor is the recommended way to change settings. Manual JSON editing is useful for deployment, backups, and advanced customization.

## Autostart

The autostart option creates a value for the current Windows user under:

```text
HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run
```

Administrator rights are normally not required because the setting applies only to the current user.

## Logs and Troubleshooting

Warnings and errors are written next to the application as:

```text
energieplan-umschalter.log
```

Common checks:

1. Confirm that only one instance is running.
2. Confirm that the configured hotkey is not already registered by another application.
3. Keep `config.json` next to the EXE.
4. Open the power-plan manager and reload the Windows plans.
5. Restore a missing standard plan before assigning it to a profile.
6. Check the log file when a setting is unsupported or a Windows command fails.

Some motherboards and Windows installations do not expose every optional processor setting. ePlan Switch continues applying the remaining supported values and records unsupported operations in the log.

## Project Files

```text
power_plan_switcher.py   Main application
config.json              User-editable configuration
build.bat                Windows EXE build script
start-python.bat         Python development launcher
requirements.txt         Python dependencies
README.md                German/bilingual documentation
README_EN.md             English documentation
VERSION.txt              Current application version
logo.ico / logo.png      Optional application icon
```

## Important Notice

Changing Windows power settings can affect performance, battery runtime, system responsiveness, and sleep behavior. Review the selected values before applying them, especially on laptops or systems used for unattended tasks.
