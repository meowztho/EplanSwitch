# ePlan Switch

<img src="logo.png" alt="ePlan Switch logo" width="50%">

ePlan Switch is a lightweight Windows tray application that switches between configurable power profiles manually or automatically based on user inactivity, system load, running processes, GPU activity, and Remote Desktop usage.

> Current application version: **1.9.0**  
> Supported platforms: **Windows 10 and Windows 11**

## New in version 1.9.0

* The tray tooltip and tray menu now show the currently active ePlan Switch profile.
* Remote Desktop activity is detected through the Windows session state instead of relying on `rdpclip.exe`.
* Only connected, unlocked, and recently used RDP sessions trigger the performance profile.
* Disconnected, locked, or longer-idle RDP sessions no longer keep the performance profile active.
* The RDP idle limit can be configured in the user interface.
* Automatic RDP detection can be disabled independently.
* Sessions transferred to the local console using `tscon` are not treated as active RDP connections.
* Existing compatible configuration files are migrated automatically to schema version `8`.

## Contents

- [Features](#features)
- [Automatic profile switching](#automatic-profile-switching)
- [Remote Desktop detection](#remote-desktop-detection)
- [Process rules](#process-rules)
- [CPU settings](#cpu-settings)
- [Power-plan management](#power-plan-management)
- [Building the EXE](#building-the-exe)
- [Troubleshooting](#logs-and-troubleshooting)

## Features

* Global hotkey, default **Ctrl + F12**
* Dynamic tray display of the currently active profile
* Any number of configurable profiles
* Select any installed Windows power plan for each profile
* Add, remove, rename, and disable profiles
* Include or exclude individual profiles from hotkey switching
* Processor minimum and maximum state
* Processor boost mode
* Core Parking: unchanged, custom, or fully disabled
* Energy Performance Preference, or EPP
* Cooling policy
* Separate display, sleep, and hibernation timeouts for AC and battery power
* Automatic detection of processor settings exposed by Windows
* Optional second-efficiency-class support for compatible hybrid CPUs
* Automatic switching based on user inactivity or system load
* Remote Desktop session detection
* Optional NVIDIA GPU, encoder, and decoder monitoring through NVML
* Process-based performance rules with wildcard support
* German and English interface
* Per-user Windows autostart
* Power-plan manager for activation, removal, and restoration
* Tray menu and fading status popup
* External `config.json`
* Automatic migration of older compatible configurations
* Log file for unsupported settings and Windows command errors

## Tray status

The tray tooltip and tray menu show the profile currently associated with the active Windows power plan.

Example:

```text
ePlan Switch v1.9.0 — Performance
```

The tray menu also contains a status entry such as:

```text
Active profile: Performance
```

The displayed value is updated after a profile has been applied successfully.

When the current Windows power plan cannot be associated unambiguously with a single ePlan Switch profile, the tray displays an unknown or ambiguous profile state instead of reporting an incorrect profile.

## Profile management

Each profile has its own tab in the configuration window.

* **+** adds a new profile by copying the last selected profile as a starting point.
* **Remove profile** removes only the ePlan Switch profile. It does not delete the assigned Windows power plan.
* **Include in hotkey switching** controls whether the profile is included in the normal hotkey cycle.
* Disabled profiles remain editable and can still be applied manually.
* Profiles can be renamed and reordered.

At least one profile must remain, and at least one profile must be enabled for hotkey switching.

The global hotkey cycles through enabled profiles in tab order.

If the Windows power plan assigned to a profile is unavailable:

* The missing plan is visibly marked in the profile selector.
* The profile is skipped during hotkey switching.
* The event is written to `energieplan-umschalter.log`.

## Automatic profile switching

Under **General → Automatic profile switching**, three modes are available:

1. **Disabled**
   No automatic polling or profile switching is performed.

2. **By user inactivity**
   Switches between an active profile and an idle profile based on keyboard and mouse inactivity.

3. **By system load**
   Switches between a power-saving profile and a performance profile based on processor, process, GPU, and Remote Desktop activity.

A manually selected profile is kept by default until the automatic state actually changes.

Immediate process triggers intentionally take priority and may directly override a manual profile selection.

## Switching by user inactivity

The inactivity mode checks how long the current Windows session has received no keyboard or mouse input.

Typical behavior:

* Apply the active profile when the user is working.
* Apply the configured idle profile after the inactivity limit is reached.
* Restore the active profile when input resumes.

User inactivity does not necessarily mean that the computer is unused. Downloads, rendering, compilation, game servers, media playback, and other unattended tasks may continue without keyboard or mouse input.

For such workloads, load-based switching is generally more appropriate.

## Load-based profile switching

Load mode uses separate thresholds for switching to the performance profile and returning to the power-saving profile.

This hysteresis prevents frequent profile flapping when load fluctuates near a threshold.

Default values:

* Performance profile above **35%** total CPU load
* Return below **15%** total CPU load
* Monitored processes above **3%** of total CPU capacity
* Return below **1%** monitored-process load
* High load must persist for **15 seconds**
* Low load must persist for **120 seconds**
* Minimum hold time of **30 seconds** after a switch
* Polling every **3 seconds**

All values can be changed through the graphical configuration editor.

### High-load conditions

The performance profile can be requested by one or more of the following conditions:

* High total processor utilization
* High combined utilization of monitored processes
* A matching immediate-trigger process
* High NVIDIA GPU utilization
* High NVIDIA video encoder utilization
* High NVIDIA video decoder utilization
* An actively connected and recently used Remote Desktop session

### Low-load conditions

The power-saving profile is restored only after the configured low-load conditions remain satisfied for the configured delay.

This prevents the application from switching back immediately during short pauses in a workload.

## Remote Desktop detection

Remote Desktop is handled separately from normal process rules.

ePlan Switch checks the actual Windows session state instead of assuming that `rdpclip.exe` means an RDP client is currently connected.

An RDP session counts as active only while it is:

* connected,
* unlocked,
* and used within the configured RDP inactivity window.

The performance profile is no longer kept active when:

* the Remote Desktop window is closed,
* the connection is interrupted,
* Windows reports the session as disconnected,
* the session is locked,
* or the configured RDP idle limit is exceeded.

The RDP idle limit can be configured in the user interface. Remote Desktop detection can also be disabled entirely.

### Compatibility with `tscon`

The detection is compatible with:

```bat
tscon <session ID> /dest:console
```

After a session is transferred to the local console, it is no longer treated as an active Remote Desktop connection.

ePlan Switch only reads the Windows session state. It does not:

* execute `tscon`,
* transfer sessions,
* lock the workstation,
* disconnect a user,
* or sign out a user.

A separate `tscon` script should not be launched automatically for every new Remote Desktop connection. Doing so can immediately transfer each new connection back to the console and create a reconnect loop.

## Process rules

Process fields accept one pattern per line.

Matching is:

* case-insensitive,
* based on the executable name,
* and compatible with `*` and `?` wildcards.

Example:

```text
PalServer-Win64-Shipping.exe
*Server-Win64-Shipping.exe
ffmpeg.exe
```

### Processes that trigger immediately

When a matching process is detected, ePlan Switch switches directly to the performance profile on the next scan.

This trigger is independent of:

* total processor thresholds,
* monitored-process thresholds,
* GPU thresholds,
* the normal high-load delay,
* the minimum profile hold time,
* and a manual profile selection.

Processes are scanned every three seconds, so “immediate” means no later than the next polling cycle.

Do not add permanently running services unless they should keep the performance profile active continuously.

Switching back after an immediate trigger ends still uses the configured low-load delay.

### Choose running processes

Each process field provides a **Choose from running processes...** button.

The dialog supports multiple selection and displays:

* executable name,
* process ID,
* executable path.

Windows system processes are hidden by default and can be displayed when necessary.

Only the executable name is added to the rule.

Example:

```text
PalServer-Win64-Shipping.exe
```

### Load-sensitive processes

Load-sensitive processes trigger the performance profile only when their combined CPU utilization exceeds the configured threshold.

Default patterns include:

```text
PalServer-Win64-Shipping.exe
PalServer.exe
*Server-Win64-Shipping.exe
ffmpeg.exe
sunshine.exe
```

`sunshine.exe` is deliberately load-sensitive because Sunshine is often installed as a continuously running service.

An active stream can additionally be detected through NVIDIA GPU, encoder, or decoder utilization when NVML is available.

### Launchers and parent processes

For launcher patterns, the launcher's own processor load is ignored. Only descendant processes are counted.

Default patterns:

```text
DGSM*.exe
dgsm*.exe
```

This prevents DGSM itself from activating the performance profile.

A dedicated game server started by DGSM can still trigger the performance profile when one of its child processes creates measurable load.

If the launcher exits after starting the server, add the dedicated server executable to the **Load-sensitive processes** list as well.

### WSL, Docker, and virtual machines

The following processes are considered only when they create measurable processor load:

```text
vmmem*
wslhost.exe
wsl.exe
wslservice.exe
wslrelay.exe
com.docker.backend.exe
com.docker.build.exe
Docker Desktop.exe
dockerd.exe
```

An idle container, virtual machine, or hosted website waiting for requests therefore does not keep the performance profile active.

Actual compute load is detected through `vmmem`, WSL, Docker backend, or related processes.

Very light websites may not require the performance profile.

A service that should always request performance can instead be added to **Processes that trigger immediately**.

## NVIDIA GPU monitoring

When enabled, ePlan Switch uses the NVML library supplied with the NVIDIA driver to read:

* GPU utilization
* video encoder utilization
* video decoder utilization

No additional Python package is required.

If NVML is unavailable, ePlan Switch continues operating without GPU metrics and uses the remaining processor, process, session, and inactivity conditions.

## Resource usage

Automatic switching is intentionally lightweight:

* No additional Windows service
* No keyboard or mouse hooks
* No input recording
* No `psutil` dependency
* CPU times and process trees are read directly through the Windows API
* Process and load polling occurs only every three seconds
* One idle-input check per second while idle-based switching is active
* No load or idle polling when automatic switching is disabled
* `powercfg` runs only when a profile actually changes

## CPU settings

### Processor performance range

The minimum and maximum processor states are percentages.

* The minimum value controls the lowest requested processor performance level.
* The maximum value acts as a hard upper limit.
* Processor boost may be restricted when the maximum value is below `100%`.

The processor maximum limit takes priority over EPP and processor boost settings.

### Processor boost mode

Available boost modes depend on the values exposed by Windows.

A mode such as **Aggressive** allows the processor to increase its clock speed more quickly when performance is required.

Boost may have little or no effect when the maximum processor state is below `100%`.

### Core Parking

Available modes:

* **Do not change** — preserve the current Windows value.
* **Custom** — configure minimum and maximum active-core percentages.
* **Disable Core Parking** — set both minimum and maximum to `100%`.

A minimum value of `100%` keeps all processors active.

A maximum below `100%` limits the number of processors Windows may use and can reduce performance.

### Energy Performance Preference

Energy Performance Preference controls whether Windows should favor performance or energy savings.

* `0` favors maximum performance.
* `100` favors maximum energy saving.

The processor maximum limit takes priority over EPP and boost settings.

### Cooling policy

The cooling policy controls how Windows reacts when the processor becomes warm.

* **Active** — increase fan speed before reducing processor performance.
* **Passive** — reduce processor performance before increasing fan speed.
* **Do not change** — preserve the current Windows value.

Available options depend on the Windows installation and hardware.

### Hybrid CPU support

The option for additional hybrid CPU settings applies values for a second processor efficiency class only when Windows exposes the required parameters.

The feature is not based on a fixed list of Intel or AMD processors.

If Windows does not report the additional parameters, no extra values are changed.

Unsupported optional values are skipped and written to:

```text
energieplan-umschalter.log
```

## UI warnings

The **Warnings** section appears only when ePlan Switch detects a conflicting or potentially limiting configuration.

Possible warnings include:

* Processor minimum above processor maximum
* Processor boost enabled while processor maximum is below `100%`
* Aggressive boost combined with a strong energy-saving preference
* Core Parking minimum above Core Parking maximum
* Core Parking maximum below `100%`, limiting available processors

When no relevant condition is detected, the section remains hidden.

Warnings normally do not prevent a profile from being saved or applied. They explain settings that may not behave as expected.

## Default profiles

Default values can be changed through the graphical editor or directly in `config.json`.

Both default profiles can be renamed, disabled, removed, or used as the basis for additional profiles.

### Summer / Browsing

Designed to reduce processor power consumption and heat during browsing, office work, media playback, and other light desktop tasks.

* Minimum processor state: **5%**
* Maximum processor state: **50%**
* Processor boost mode: **Disabled**
* Core Parking on AC power: **10–100%**
* Core Parking on battery power: **5–100%**
* EPP on AC power: **80**
* EPP on battery power: **90**
* Cooling policy: **Active**
* Display timeout: **Never**
* Sleep timeout: **Never**
* Hibernation timeout: **Never**

### Performance

Designed for gaming, rendering, compilation, streaming, and other demanding workloads.

* Minimum processor state: **5%**
* Maximum processor state: **100%**
* Processor boost mode: **Aggressive**
* Core Parking: **Disabled**
* EPP: **0**
* Cooling policy: **Active**
* Display timeout: **Never**
* Sleep timeout: **Never**
* Hibernation timeout: **Never**

## Time values

Timeout fields use minutes.

|           Value | Meaning                                         |
| --------------: | ----------------------------------------------- |
|             `0` | Never turn off the display, sleep, or hibernate |
| Blank or `null` | Preserve the current Windows value              |
| Positive number | Timeout in minutes                              |

Separate values can be configured for:

* AC power
* Battery power
* Display timeout
* Sleep timeout
* Hibernation timeout

## Configuration editor

The graphical configuration editor contains the following areas.

### General

* Interface language
* Windows autostart
* Global hotkey
* Startup popup
* Apply the active profile when the application starts
* Popup duration
* Popup size
* Popup position
* Automatic profile-switching mode
* User-inactivity settings
* System-load thresholds
* Process rules
* Remote Desktop detection
* RDP inactivity limit
* NVIDIA GPU monitoring

### Profile settings

* Profile name
* Include or exclude the profile from hotkey switching
* Windows power-plan assignment
* Processor minimum state
* Processor maximum state
* Processor boost mode
* Core Parking
* Energy Performance Preference
* Cooling policy
* Display timeout
* Sleep timeout
* Hibernation timeout
* Separate values for AC and battery power

### Power plans

* Reload installed plans from Windows
* Mark the currently active plan
* Activate a selected plan
* Restore a missing Windows standard plan
* Remove an inactive and unused plan

## Power-plan management

ePlan Switch reads the installed Windows power plans through `powercfg` whenever the **Power plans** page is opened and after every plan change.

Available actions:

* Activate an installed plan
* Remove an unused plan
* Restore a missing Windows standard plan
* Reload the plans reported by Windows

### Supported Windows standard plans

* Power saver
* Balanced
* High performance
* Ultimate Performance

A missing standard plan can be restored individually.

ePlan Switch intentionally does not use:

```text
powercfg /restoredefaultschemes
```

That command may remove custom power plans.

### Removing a power plan

The remove action uses:

```text
powercfg /delete
```

The following plans are protected and cannot be removed through ePlan Switch:

* The currently active Windows power plan
* A plan assigned to an ePlan Switch profile

Deleted custom plans cannot be restored automatically.

Back up important custom power plans before removing them.

Removing a Windows power plan is separate from removing an ePlan Switch profile. Deleting a profile does not delete the assigned Windows plan.

## Configuration and migration

User-editable application and profile settings are stored in the external `config.json`.

The graphical editor is the recommended way to change the configuration.

Manual editing can be useful for:

* deployments,
* backups,
* troubleshooting,
* and advanced customization.

The current configuration uses:

```json
{
  "schema_version": 8
}
```

Older compatible configurations are migrated automatically.

Backing up a customized `config.json` before upgrading is still recommended.

A simplified configuration structure looks like this:

```json
{
  "schema_version": 8,
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
    "profile_order": [
      "summer",
      "performance"
    ]
  },
  "profiles": {
    "summer": {
      "display_name": "Summer / Browsing",
      "enabled": true
    },
    "performance": {
      "display_name": "Performance",
      "enabled": true
    }
  }
}
```

Supported interface languages:

```text
de
en
```

## Autostart

The **Start automatically with Windows** option creates an entry for the current Windows user under:

```text
HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run
```

Administrator rights are normally not required because the setting applies only to the current user.

## Running from Python

### Requirements

* Windows 10 or Windows 11
* Python 3
* Windows Python Launcher `py`

Install the required packages:

```powershell
py -3 -m pip install -r requirements.txt
```

Start the application:

```powershell
py -3 power_plan_switcher.py
```

Alternatively, run:

```text
start-python.bat
```

## Building the EXE

Optionally place one of the following files in the project directory:

```text
logo.ico
logo.png
```

Run:

```text
build.bat
```

The build script creates a local virtual environment, installs the required packages, and runs PyInstaller.

Output:

```text
dist\ePlan-Switch.exe
```

Keep at least the following files together:

```text
ePlan-Switch.exe
config.json
```

Depending on the release package, the following files may also be included:

```text
logo.ico
logo.png
README.md
README_EN.md
VERSION.txt
```

## Logs and troubleshooting

Warnings and errors are written next to the application as:

```text
energieplan-umschalter.log
```

Common checks:

1. Confirm that only one instance of ePlan Switch is running.
2. Confirm that the configured global hotkey is not already registered by another application.
3. Keep `config.json` next to the EXE.
4. Open the power-plan manager and reload the installed plans.
5. Restore or reassign a missing Windows power plan.
6. Reload the power-plan list after changing plans outside ePlan Switch.
7. Check the log when a setting is unsupported or a Windows command fails.
8. Verify the automatic switching mode and selected target profiles.
9. Check whether an immediate-trigger process is permanently active.
10. Review the configured RDP inactivity limit when Remote Desktop does not switch as expected.

Some Windows installations, processors, and motherboards do not expose every optional processor setting.

ePlan Switch continues applying the remaining supported values and records unsupported operations in the log.

## Project files

```text
power_plan_switcher.py   Main application
config.json              User-editable configuration
build.bat                Windows EXE build script
start-python.bat         Python development launcher
requirements.txt         Python dependencies
README.md                German documentation
README_EN.md             English documentation
VERSION.txt              Current application version
logo.ico / logo.png      Optional application icon
```

## Important notice

Changing Windows power settings can affect:

* System performance
* Power consumption
* Battery runtime
* Processor temperature
* Fan noise
* System responsiveness
* Display timeout
* Sleep behavior
* Hibernation behavior
* Unattended tasks

Review the selected values before applying them, especially on laptops or computers that must remain available for unattended work.
