from __future__ import annotations

import ctypes
import fnmatch
from functools import partial
import json
import logging
import os
import queue
import re
import subprocess
import sys
import threading
import time
import winreg
from ctypes import wintypes
from pathlib import Path
from typing import Any, Callable

import tkinter as tk
from tkinter import messagebox, ttk

from PIL import Image, ImageDraw
import pystray


APP_NAME = "ePlan Switch"
APP_VERSION = "1.9.0"
CONFIG_FILE_NAME = "config.json"
LOG_FILE_NAME = "energieplan-umschalter.log"
MUTEX_NAME = "Local\\Energieplan-Umschalter-6D7F0D5E"
AUTOSTART_REGISTRY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_VALUE_NAME = "Energieplan-Umschalter"
POWERCFG = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "powercfg.exe")

BALANCED_GUID = "381b4222-f694-41f0-9685-ff5bb260df2e"
POWER_SAVER_GUID = "a1841308-3541-4fab-bc81-f71556f20b4a"
HIGH_PERFORMANCE_GUID = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
ULTIMATE_GUID = "e9a42b02-d5df-448d-aa00-03f14749eb61"

STANDARD_SCHEMES: dict[str, dict[str, Any]] = {
    "power_saver": {
        "guid": POWER_SAVER_GUID,
        "names": {
            "de": "Energiesparmodus",
            "en": "Power saver",
        },
        "aliases": ["energiesparmodus", "power saver"],
    },
    "balanced": {
        "guid": BALANCED_GUID,
        "names": {
            "de": "Ausbalanciert",
            "en": "Balanced",
        },
        "aliases": ["ausbalanciert", "balanced"],
    },
    "high_performance": {
        "guid": HIGH_PERFORMANCE_GUID,
        "names": {
            "de": "Höchstleistung",
            "en": "High performance",
        },
        "aliases": ["höchstleistung", "hochstleistung", "high performance"],
    },
    "ultimate": {
        "guid": ULTIMATE_GUID,
        "names": {
            "de": "Ultimative Leistung",
            "en": "Ultimate Performance",
        },
        "aliases": ["ultimative leistung", "ultimate performance"],
    },
}

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
ERROR_ALREADY_EXISTS = 183

ACTION_QUEUE_POLL_MS = 100
DYNAMIC_ACTIVE_POLL_MS = 3000
DYNAMIC_IDLE_POLL_MS = 1000
SYSTEM_LOAD_POLL_MS = 3000

TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

KNOWN_WINDOWS_PROCESS_NAMES = {
    "idle", "system", "registry", "memory compression", "secure system",
    "smss.exe", "csrss.exe", "wininit.exe", "services.exe", "lsass.exe",
    "svchost.exe", "fontdrvhost.exe", "winlogon.exe", "dwm.exe",
    "sihost.exe", "taskhostw.exe", "runtimebroker.exe", "searchhost.exe",
    "startmenuexperiencehost.exe", "shellexperiencehost.exe", "ctfmon.exe",
    "audiodg.exe", "spoolsv.exe", "securityhealthservice.exe", "msmpeng.exe",
    "nissrv.exe", "smartscreen.exe", "conhost.exe", "dllhost.exe",
    "backgroundtaskhost.exe", "applicationframehost.exe", "systemsettings.exe",
}

VK_CODES: dict[str, int] = {
    **{f"F{i}": 0x6F + i for i in range(1, 25)},
    "PAUSE": 0x13,
    "INSERT": 0x2D,
    "DELETE": 0x2E,
    "HOME": 0x24,
    "END": 0x23,
    "PAGEUP": 0x21,
    "PAGEDOWN": 0x22,
    "SCROLLLOCK": 0x91,
}

BOOST_VALUES = [0, 1, 2, 3, 4]
COOLING_VALUES: list[int | None] = [None, 0, 1]
KNOWN_PROCESSOR_ALIASES = {
    "PROCTHROTTLEMIN", "PROCTHROTTLEMIN1",
    "PROCTHROTTLEMAX", "PROCTHROTTLEMAX1",
    "PERFBOOSTMODE", "SYSCOOLPOL",
    "CPMINCORES", "CPMINCORES1",
    "CPMAXCORES", "CPMAXCORES1",
    "PERFEPP", "PERFEPP1",
}

TRANSLATIONS: dict[str, dict[str, str]] = {
    "de": {
        "app_config": "Konfiguration",
        "general": "Allgemein",
        "power_plans": "Energiepläne",
        "language": "Sprache",
        "language_de": "Deutsch",
        "language_en": "English",
        "autostart": "Mit Windows automatisch starten",
        "global_hotkey": "Globaler Hotkey",
        "key": "Taste",
        "ctrl": "Strg",
        "alt": "Alt",
        "shift": "Umschalt",
        "win": "Win",
        "startup_popup": "Beim Start ein kurzes Status-Popup anzeigen",
        "apply_on_start": "Beim Start die Werte des aktuell aktiven Profils erneut anwenden",
        "dynamic_switch": "Dynamischer Profilwechsel",
        "dynamic_switch_enable": "Bei Inaktivität automatisch das Energiesparprofil verwenden",
        "dynamic_active_profile": "Profil bei Nutzung",
        "dynamic_idle_profile": "Profil bei Inaktivität",
        "dynamic_idle_minutes": "Wechsel nach (Minuten)",
        "dynamic_switch_note": "Es werden genau zwei Profile verwendet. Bei Maus- oder Tastatureingabe wird sofort zum Nutzungsprofil zurückgewechselt.",
        "dynamic_same_profile": "Für Nutzung und Inaktivität müssen unterschiedliche Profile gewählt werden.",
        "dynamic_profile_missing": "Das für den dynamischen Wechsel ausgewählte Profil '{profile}' existiert nicht.",
        "dynamic_idle_invalid": "Die Inaktivitätszeit muss mindestens 1 Minute betragen.",
        "automatic_mode": "Automatischer Profilwechsel",
        "automatic_mode_disabled": "Deaktiviert",
        "automatic_mode_idle": "Nach Benutzer-Inaktivität",
        "automatic_mode_load": "Nach Systemauslastung",
        "manual_override": "Manuelle Profilwahl bis zum nächsten automatischen Zustandswechsel beibehalten",
        "idle_mode": "Inaktivität",
        "load_mode": "Systemauslastung",
        "load_low_profile": "Energiesparprofil",
        "load_high_profile": "Leistungsprofil",
        "load_cpu_high": "Leistung ab CPU-Auslastung (%)",
        "load_cpu_low": "Zurück unter CPU-Auslastung (%)",
        "load_process_high": "Leistung ab überwachten Prozessen (%)",
        "load_process_low": "Zurück unter überwachten Prozessen (%)",
        "load_gpu_enable": "NVIDIA-GPU, Encoder und Decoder berücksichtigen, wenn NVML verfügbar ist",
        "load_gpu_high": "Leistung ab GPU-Auslastung (%)",
        "load_gpu_low": "Zurück unter GPU-Auslastung (%)",
        "load_high_delay": "Hohe Last muss anliegen (Sek.)",
        "load_low_delay": "Niedrige Last muss anliegen (Sek.)",
        "load_min_hold": "Mindestdauer nach einem Wechsel (Sek.)",
        "load_include_children": "Unterprozesse der überwachten Prozesse mit berücksichtigen",
        "rdp_session_trigger": "Aktive Remotedesktop-Sitzung sofort berücksichtigen",
        "rdp_idle_minutes": "RDP gilt nach dieser Inaktivität nicht mehr als aktiv (Min.)",
        "rdp_session_note": "Nur eine verbundene, entsperrte und kürzlich verwendete RDP-Sitzung löst aus. Getrennte Sitzungen und per tscon an die Konsole übergebene Sitzungen werden ignoriert.",
        "process_always": "Sofort auslösende Prozesse",
        "process_load": "Lastabhängige Prozesse",
        "process_launchers": "Launcher / Elternprozesse (nur Unterprozesse zählen)",
        "process_containers": "WSL-, Docker- und VM-Prozesse (nur bei Last)",
        "process_patterns_note": "Ein Muster pro Zeile; * und ? sind erlaubt. Laufende, aber untätige WSL-/Docker-Prozesse lösen keinen Wechsel aus.",
        "process_immediate_note": "Sofort-Auslöser wechseln beim nächsten Prüflauf direkt zum Leistungsprofil. Prozentwerte, Verzögerungen, Mindesthaltezeit und manuelle Auswahl werden dabei ignoriert.",
        "choose_running_processes": "Aus laufenden Prozessen auswählen...",
        "process_picker_title": "Laufende Prozesse auswählen",
        "process_picker_filter": "Filtern",
        "process_picker_show_windows": "Windows-Systemprozesse anzeigen",
        "process_picker_name": "Prozess",
        "process_picker_pid": "PID",
        "process_picker_path": "Pfad",
        "process_picker_refresh": "Neu laden",
        "process_picker_add": "Auswahl hinzufügen",
        "process_picker_none": "Bitte mindestens einen Prozess auswählen.",
        "process_picker_hidden_note": "Windows-Systemprozesse sind standardmäßig ausgeblendet. Die Auswahl fügt nur den Dateinamen zur Regel hinzu.",
        "load_mode_note": "Schnelles Hochschalten, langsames Zurückschalten. Hohe und niedrige Schwellen verhindern ständiges Wechseln.",
        "invalid_automatic_mode": "Unbekannter Automatikmodus: {mode}",
        "load_threshold_order": "Die niedrige Schwelle für {label} darf nicht über der hohen Schwelle liegen.",
        "load_profile_missing": "Das für die Lastautomatik ausgewählte Profil '{profile}' existiert nicht.",
        "load_same_profile": "Energiespar- und Leistungsprofil müssen unterschiedlich sein.",
        "popup": "Popup",
        "visible_ms": "Sichtbar (ms)",
        "fade_ms": "Ausblenddauer (ms)",
        "width": "Breite",
        "height": "Höhe",
        "cancel": "Abbrechen",
        "save": "Speichern",
        "save_apply": "Speichern und ausgewähltes Profil anwenden",
        "profile_name": "Profilname",
        "profile_enabled": "Beim Hotkey-Wechsel verwenden",
        "add_profile": "Neues Profil hinzufügen",
        "remove_profile": "Profil entfernen",
        "new_profile": "Neues Profil {number}",
        "confirm_remove_profile_title": "Profil entfernen",
        "confirm_remove_profile": "Soll das Profil '{name}' wirklich entfernt werden?",
        "cannot_remove_last_profile": "Mindestens ein Profil muss erhalten bleiben.",
        "at_least_one_enabled": "Mindestens ein Profil muss für den Hotkey-Wechsel aktiviert sein.",
        "disabled_profile_note": "Deaktivierte Profile werden beim Hotkey-Wechsel übersprungen, bleiben aber bearbeitbar.",
        "profile_disabled_suffix": "aus",
        "windows_plan": "Windows-Energieplan",
        "missing_plan_selection": "Fehlender Plan | {guid}",
        "mains": "Netzbetrieb",
        "battery": "Akkubetrieb",
        "cpu_min": "CPU Minimum (%)",
        "cpu_max": "CPU Maximum (%)",
        "display_timeout": "Bildschirm aus nach (Min.)",
        "sleep_timeout": "Standby nach (Min.)",
        "hibernate_timeout": "Ruhezustand nach (Min.)",
        "boost_mode": "CPU-Boostmodus",
        "cooling_policy": "Systemkühlungsrichtlinie",
        "advanced_cpu": "Prozessorleistung",
        "core_parking": "Core Parking",
        "core_parking_mode": "Core-Parking-Modus",
        "parking_unchanged": "Nicht verändern",
        "parking_custom": "Benutzerdefiniert",
        "parking_disabled": "Core Parking deaktivieren (alle Kerne aktiv)",
        "parking_min": "Mindestens aktive Kerne (%)",
        "parking_max": "Höchstens aktive Kerne (%)",
        "core_parking_note": "100 % Minimum hält alle Kerne aktiv. Ein Maximum unter 100 % kann die Leistung begrenzen.",
        "energy_preference": "Energie-/Leistungspräferenz (EPP)",
        "energy_preference_enable": "Energiepräferenz für diesen Betriebsmodus festlegen",
        "energy_preference_value": "EPP-Wert (0 = Leistung, 100 = Energiesparen)",
        "energy_preference_note": "0 bevorzugt Leistung, 100 bevorzugt Energiesparen. Die CPU-Maximalgrenze hat Vorrang.",
        "timeouts": "Bildschirm und Energiesparzeiten",
        "interaction_summary": "Warnungen",
        "interaction_ok": "Keine Konflikte erkannt.",
        "interaction_cpu_range": "CPU Minimum liegt über CPU Maximum.",
        "interaction_boost_cap": "CPU Maximum unter 100 % kann Turbo Boost begrenzen oder vollständig wirkungslos machen.",
        "interaction_epp_boost": "Aggressiver Boost und ein hoher EPP-Wert verfolgen unterschiedliche Ziele; Windows versucht zwischen Leistung und Sparen abzuwägen.",
        "interaction_parking_limit": "Ein Core-Parking-Maximum unter 100 % begrenzt, wie viele logische Prozessoren gleichzeitig genutzt werden können.",
        "interaction_parking_disabled": "Core Parking ist deaktiviert.",
        "interaction_parking_range": "Die Mindestzahl aktiver Kerne darf nicht über der Höchstzahl liegen.",
        "cpu_compatibility": "CPU-Erkennung",
        "detected_cpu": "Erkannte CPU: {name}",
        "cpu_details": "Hersteller: {vendor} | Logische Prozessoren: {logical} | Architektur: {architecture}",
        "cpu_features": "Von Windows erkannte Profilfunktionen: {features}",
        "cpu_features_unknown": "Die verfügbaren CPU-Profilfunktionen konnten nicht vollständig ermittelt werden. Standardwerte werden weiterhin vorsichtig angewendet.",
        "auto_class1": "Zusätzliche Hybrid-CPU-Einstellungen automatisch anwenden",
        "auto_class1_note": "Nur wenn Windows diese Einstellungen unterstützt. Auf normalen Intel- und AMD-CPUs hat die Option keine Wirkung.",
        "feature_cpu_range": "CPU-Leistungsbereich",
        "feature_boost": "Boost",
        "feature_cooling": "Kühlungsrichtlinie",
        "feature_parking": "Core Parking",
        "feature_epp": "Energiepräferenz",
        "feature_class1": "Effizienzklasse 1 / Hybrid",
        "boost_0": "0 - Deaktiviert",
        "boost_1": "1 - Aktiviert",
        "boost_2": "2 - Aggressiv",
        "boost_3": "3 - Effizient aktiviert",
        "boost_4": "4 - Effizient aggressiv",
        "cool_none": "Leer - Nicht verändern",
        "cool_0": "0 - Passiv",
        "cool_1": "1 - Aktiv",
        "time_note": "Zeitwerte: 0 = Nie, leer = vorhandene Windows-Einstellung beibehalten.",
        "boost_note": "Boost 0 = aus. Boost 2 = aggressiv. CPU-Maximum und EPP können den Boost zusätzlich begrenzen.",
        "installed_plans": "Installierte Energiepläne",
        "status": "Status",
        "name": "Name",
        "guid": "GUID",
        "active": "Aktiv",
        "installed": "Installiert",
        "missing": "Fehlt",
        "refresh": "Neu laden",
        "activate_selected": "Ausgewählten Plan aktivieren",
        "remove_selected": "Ausgewählten Plan deaktivieren / entfernen",
        "restore_standard": "Fehlenden Standardplan installieren / wiederherstellen",
        "standard_plan": "Windows-Standardplan",
        "plan_manager_note": "Entfernen löscht den Energieplan aus Windows. Aktive oder einem Profil zugeordnete Pläne sind geschützt.",
        "select_installed": "Wähle zuerst einen installierten Energieplan aus.",
        "select_standard": "Wähle zuerst einen Windows-Standardplan aus.",
        "cannot_remove_active": "Der aktuell aktive Energieplan kann nicht entfernt werden. Aktiviere zuerst einen anderen Plan.",
        "cannot_remove_profile": "Dieser Energieplan ist einem Profil zugeordnet. Weise dem Profil zuerst einen anderen Plan zu und speichere.",
        "confirm_remove_title": "Energieplan entfernen",
        "confirm_remove": "Soll der Energieplan '{name}' wirklich aus Windows entfernt werden?\n\nBenutzerdefinierte Einstellungen dieses Plans gehen verloren.",
        "plan_removed": "Energieplan entfernt: {name}",
        "plan_activated": "Energieplan aktiviert: {name}",
        "plan_restored": "Standardplan installiert: {name}",
        "plan_already_present": "Der Standardplan ist bereits vorhanden: {name}",
        "no_plans": "Windows hat keine lesbaren Energiepläne zurückgegeben.",
        "config_saved": "Konfiguration gespeichert.",
        "config_saved_applied": "Konfiguration gespeichert und Profil angewendet.",
        "select_profile_tab": "Wähle zuerst den Reiter eines Energieprofils aus.",
        "config_reloaded": "Konfiguration neu geladen",
        "ready": "{hotkey} bereit - v{version}",
        "profile_active": "Energieprofil: {name}",
        "profile_warning": "{name} aktiv - {count} Wert(e) konnten nicht gesetzt werden. Siehe Logdatei.",
        "error": "Fehler: {error}",
        "action_error": "Fehler bei '{action}': {error}",
        "toggle": "Umschalten ({hotkey})",
        "apply_profile": "Profil anwenden: {name}",
        "edit_config": "Konfiguration bearbeiten",
        "reload_config": "Konfiguration neu laden",
        "open_folder": "Programmordner öffnen",
        "exit": "Beenden",
        "version": "Version {version}",
        "active_profile_tray": "Aktiv: {name}",
        "active_profile_unknown": "Nicht erkannt",
        "already_running": "ePlan Switch läuft bereits.",
        "hotkey_unknown": "Unbekannte Taste: {key}",
        "hotkey_failed": "{hotkey} konnte nicht registriert werden (Windows-Fehler {code}). Öffne die Konfiguration und wähle eine andere Kombination.",
        "profile_plan_missing": "Der Windows-Energieplan für '{name}' wurde nicht gefunden. Öffne die Energieplan-Verwaltung und installiere einen fehlenden Standardplan oder wähle einen vorhandenen Plan aus.",
        "invalid_profiles": "Unter 'profiles' muss mindestens ein Profil vorhanden sein.",
        "invalid_toggle": "Mindestens ein Profil muss für den Hotkey aktiviert sein.",
        "invalid_profile_ref": "Das Profil '{profile}' existiert nicht.",
        "invalid_hotkey": "Nicht unterstützte Hotkey-Taste: {key}",
        "invalid_cpu_range": "{profile}: CPU Minimum darf nicht über CPU Maximum liegen ({source}).",
        "invalid_parking_range": "{profile}: Core-Parking-Minimum darf nicht über dem Maximum liegen ({source}).",
        "invalid_int": "'{label}' muss eine ganze Zahl oder leer sein.",
        "invalid_range": "'{label}' muss {range} sein.",
        "not_empty": "'{label}' darf nicht leer sein.",
        "at_least": "mindestens {minimum}",
        "between": "{minimum} bis {maximum}",
        "config_reset": "Die config.json war fehlerhaft und wurde zurückgesetzt.\n\n{error}",
        "backup": "Sicherung: {name}",
        "windows_only": "{app} unterstützt nur Windows.",
        "autostart_error": "Die Autostart-Einstellung konnte nicht geändert werden: {error}",
    },
    "en": {
        "app_config": "Configuration",
        "general": "General",
        "power_plans": "Power plans",
        "language": "Language",
        "language_de": "Deutsch",
        "language_en": "English",
        "autostart": "Start automatically with Windows",
        "global_hotkey": "Global hotkey",
        "key": "Key",
        "ctrl": "Ctrl",
        "alt": "Alt",
        "shift": "Shift",
        "win": "Win",
        "startup_popup": "Show a short status popup at startup",
        "apply_on_start": "Reapply the settings of the currently active profile at startup",
        "dynamic_switch": "Dynamic profile switching",
        "dynamic_switch_enable": "Automatically use the power-saving profile when idle",
        "dynamic_active_profile": "Profile while active",
        "dynamic_idle_profile": "Profile while idle",
        "dynamic_idle_minutes": "Switch after (minutes)",
        "dynamic_switch_note": "Exactly two profiles are used. Mouse or keyboard input returns to the active profile.",
        "dynamic_same_profile": "The active and idle profiles must be different.",
        "dynamic_profile_missing": "The profile selected for dynamic switching does not exist: '{profile}'.",
        "dynamic_idle_invalid": "The idle time must be at least 1 minute.",
        "automatic_mode": "Automatic profile switching",
        "automatic_mode_disabled": "Disabled",
        "automatic_mode_idle": "By user inactivity",
        "automatic_mode_load": "By system load",
        "manual_override": "Keep a manual profile selection until the next automatic state transition",
        "idle_mode": "Inactivity",
        "load_mode": "System load",
        "load_low_profile": "Power-saving profile",
        "load_high_profile": "Performance profile",
        "load_cpu_high": "Use performance above CPU load (%)",
        "load_cpu_low": "Return below CPU load (%)",
        "load_process_high": "Use performance above monitored-process load (%)",
        "load_process_low": "Return below monitored-process load (%)",
        "load_gpu_enable": "Include NVIDIA GPU, encoder and decoder load when NVML is available",
        "load_gpu_high": "Use performance above GPU load (%)",
        "load_gpu_low": "Return below GPU load (%)",
        "load_high_delay": "High load must persist (sec.)",
        "load_low_delay": "Low load must persist (sec.)",
        "load_min_hold": "Minimum time after a switch (sec.)",
        "load_include_children": "Include child processes of monitored processes",
        "rdp_session_trigger": "Treat an active Remote Desktop session as an immediate trigger",
        "rdp_idle_minutes": "Stop treating RDP as active after this idle time (min.)",
        "rdp_session_note": "Only a connected, unlocked and recently used RDP session triggers. Disconnected sessions and sessions transferred to the console with tscon are ignored.",
        "process_always": "Processes that trigger immediately",
        "process_load": "Load-sensitive processes",
        "process_launchers": "Launchers / parent processes (only children count)",
        "process_containers": "WSL, Docker and VM processes (load-sensitive)",
        "process_patterns_note": "One pattern per line; * and ? are supported. Running but idle WSL/Docker processes do not trigger a switch.",
        "process_immediate_note": "Immediate triggers switch directly to the performance profile on the next scan. Percentage thresholds, delays, minimum hold time and manual selection are ignored.",
        "choose_running_processes": "Choose from running processes...",
        "process_picker_title": "Choose running processes",
        "process_picker_filter": "Filter",
        "process_picker_show_windows": "Show Windows system processes",
        "process_picker_name": "Process",
        "process_picker_pid": "PID",
        "process_picker_path": "Path",
        "process_picker_refresh": "Refresh",
        "process_picker_add": "Add selection",
        "process_picker_none": "Select at least one process.",
        "process_picker_hidden_note": "Windows system processes are hidden by default. Only the executable name is added to the rule.",
        "load_mode_note": "Switch up quickly and back down slowly. Separate high and low thresholds prevent profile flapping.",
        "invalid_automatic_mode": "Unknown automatic mode: {mode}",
        "load_threshold_order": "The low threshold for {label} must not exceed the high threshold.",
        "load_profile_missing": "The profile selected for load automation does not exist: '{profile}'.",
        "load_same_profile": "The power-saving and performance profiles must be different.",
        "popup": "Popup",
        "visible_ms": "Visible (ms)",
        "fade_ms": "Fade duration (ms)",
        "width": "Width",
        "height": "Height",
        "cancel": "Cancel",
        "save": "Save",
        "save_apply": "Save and apply selected profile",
        "profile_name": "Profile name",
        "profile_enabled": "Include in hotkey switching",
        "add_profile": "Add new profile",
        "remove_profile": "Remove profile",
        "new_profile": "New profile {number}",
        "confirm_remove_profile_title": "Remove profile",
        "confirm_remove_profile": "Really remove the profile '{name}'?",
        "cannot_remove_last_profile": "At least one profile must remain.",
        "at_least_one_enabled": "At least one profile must be enabled for hotkey switching.",
        "disabled_profile_note": "Disabled profiles are skipped by the hotkey but remain editable.",
        "profile_disabled_suffix": "off",
        "windows_plan": "Windows power plan",
        "missing_plan_selection": "Missing plan | {guid}",
        "mains": "AC power",
        "battery": "Battery",
        "cpu_min": "CPU minimum (%)",
        "cpu_max": "CPU maximum (%)",
        "display_timeout": "Turn display off after (min.)",
        "sleep_timeout": "Sleep after (min.)",
        "hibernate_timeout": "Hibernate after (min.)",
        "boost_mode": "CPU boost mode",
        "cooling_policy": "System cooling policy",
        "advanced_cpu": "Processor performance",
        "core_parking": "Core Parking",
        "core_parking_mode": "Core parking mode",
        "parking_unchanged": "Do not change",
        "parking_custom": "Custom",
        "parking_disabled": "Disable Core Parking (all cores active)",
        "parking_min": "Minimum active cores (%)",
        "parking_max": "Maximum active cores (%)",
        "core_parking_note": "A 100% minimum keeps all cores active. A maximum below 100% can reduce performance.",
        "energy_preference": "Energy/performance preference (EPP)",
        "energy_preference_enable": "Set energy preference for this power source",
        "energy_preference_value": "EPP value (0 = performance, 100 = power saving)",
        "energy_preference_note": "0 favors performance and 100 favors power saving. The CPU maximum limit takes priority.",
        "timeouts": "Display and power timers",
        "interaction_summary": "Warnings",
        "interaction_ok": "No conflicts detected.",
        "interaction_cpu_range": "CPU minimum is higher than CPU maximum.",
        "interaction_boost_cap": "A CPU maximum below 100% can restrict Turbo Boost or make it ineffective.",
        "interaction_epp_boost": "Aggressive boost and a high EPP value pursue different goals; Windows will balance performance and efficiency.",
        "interaction_parking_limit": "A Core Parking maximum below 100% limits how many logical processors can be used at the same time.",
        "interaction_parking_disabled": "Core Parking is disabled.",
        "interaction_parking_range": "The minimum active-core percentage must not exceed the maximum.",
        "cpu_compatibility": "CPU detection",
        "detected_cpu": "Detected CPU: {name}",
        "cpu_details": "Vendor: {vendor} | Logical processors: {logical} | Architecture: {architecture}",
        "cpu_features": "Power-profile features detected by Windows: {features}",
        "cpu_features_unknown": "Available CPU power-profile features could not be detected completely. Standard values will still be applied conservatively.",
        "auto_class1": "Automatically apply additional hybrid CPU settings",
        "auto_class1_note": "Only used when Windows supports these settings. It has no effect on standard Intel or AMD CPUs.",
        "feature_cpu_range": "CPU performance range",
        "feature_boost": "Boost",
        "feature_cooling": "Cooling policy",
        "feature_parking": "Core Parking",
        "feature_epp": "Energy preference",
        "feature_class1": "Efficiency class 1 / hybrid",
        "boost_0": "0 - Disabled",
        "boost_1": "1 - Enabled",
        "boost_2": "2 - Aggressive",
        "boost_3": "3 - Efficient enabled",
        "boost_4": "4 - Efficient aggressive",
        "cool_none": "Blank - Do not change",
        "cool_0": "0 - Passive",
        "cool_1": "1 - Active",
        "time_note": "Time values: 0 = Never, blank = keep the existing Windows setting.",
        "boost_note": "Boost 0 = off. Boost 2 = aggressive. CPU maximum and EPP can limit boost further.",
        "installed_plans": "Installed power plans",
        "status": "Status",
        "name": "Name",
        "guid": "GUID",
        "active": "Active",
        "installed": "Installed",
        "missing": "Missing",
        "refresh": "Refresh",
        "activate_selected": "Activate selected plan",
        "remove_selected": "Disable / remove selected plan",
        "restore_standard": "Install / restore missing standard plan",
        "standard_plan": "Windows standard plan",
        "plan_manager_note": "Removing deletes the power plan from Windows. Active plans and plans assigned to a profile are protected.",
        "select_installed": "Select an installed power plan first.",
        "select_standard": "Select a Windows standard plan first.",
        "cannot_remove_active": "The currently active power plan cannot be removed. Activate another plan first.",
        "cannot_remove_profile": "This power plan is assigned to a profile. Assign another plan and save first.",
        "confirm_remove_title": "Remove power plan",
        "confirm_remove": "Really remove the power plan '{name}' from Windows?\n\nCustom settings stored in this plan will be lost.",
        "plan_removed": "Power plan removed: {name}",
        "plan_activated": "Power plan activated: {name}",
        "plan_restored": "Standard plan installed: {name}",
        "plan_already_present": "The standard plan is already installed: {name}",
        "no_plans": "Windows did not return any readable power plans.",
        "config_saved": "Configuration saved.",
        "config_saved_applied": "Configuration saved and profile applied.",
        "select_profile_tab": "Select a power profile tab first.",
        "config_reloaded": "Configuration reloaded",
        "ready": "{hotkey} ready - v{version}",
        "profile_active": "Power profile: {name}",
        "profile_warning": "{name} active - {count} setting(s) could not be applied. See the log file.",
        "error": "Error: {error}",
        "action_error": "Error during '{action}': {error}",
        "toggle": "Toggle ({hotkey})",
        "apply_profile": "Apply profile: {name}",
        "edit_config": "Edit configuration",
        "reload_config": "Reload configuration",
        "open_folder": "Open application folder",
        "exit": "Exit",
        "version": "Version {version}",
        "active_profile_tray": "Active: {name}",
        "active_profile_unknown": "Not detected",
        "already_running": "The power plan switcher is already running.",
        "hotkey_unknown": "Unknown key: {key}",
        "hotkey_failed": "{hotkey} could not be registered (Windows error {code}). Open the configuration and choose another combination.",
        "profile_plan_missing": "The Windows power plan for '{name}' was not found. Open Power plans and install a missing standard plan or select an installed plan.",
        "invalid_profiles": "At least one profile is required under 'profiles'.",
        "invalid_toggle": "At least one profile must be enabled for the hotkey.",
        "invalid_profile_ref": "Profile '{profile}' does not exist.",
        "invalid_hotkey": "Unsupported hotkey: {key}",
        "invalid_cpu_range": "{profile}: CPU minimum must not exceed CPU maximum ({source}).",
        "invalid_parking_range": "{profile}: Core Parking minimum must not exceed the maximum ({source}).",
        "invalid_int": "'{label}' must be an integer or blank.",
        "invalid_range": "'{label}' must be {range}.",
        "not_empty": "'{label}' must not be blank.",
        "at_least": "at least {minimum}",
        "between": "between {minimum} and {maximum}",
        "config_reset": "config.json was invalid and has been reset.\n\n{error}",
        "backup": "Backup: {name}",
        "windows_only": "{app} supports Windows only.",
        "autostart_error": "The autostart setting could not be changed: {error}",
    },
}

DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": 8,
    "app": {
        "language": "de",
        "autostart": False,
        "hotkey": {
            "key": "F12",
            "ctrl": True,
            "alt": False,
            "shift": False,
            "win": False,
        },
        "profile_order": ["summer", "performance"],
        "show_startup_popup": True,
        "apply_active_profile_on_start": False,
        "dynamic_switch": {
            "mode": "disabled",
            "manual_override_until_transition": True,
            "idle": {
                "active_profile_id": "performance",
                "idle_profile_id": "summer",
                "idle_minutes": 10,
            },
            "load": {
                "low_profile_id": "summer",
                "high_profile_id": "performance",
                "cpu_high_percent": 35,
                "cpu_low_percent": 15,
                "process_high_percent": 3,
                "process_low_percent": 1,
                "gpu_enabled": True,
                "gpu_high_percent": 25,
                "gpu_low_percent": 10,
                "high_delay_seconds": 15,
                "low_delay_seconds": 120,
                "minimum_hold_seconds": 30,
                "include_process_children": True,
                "rdp_session_trigger_enabled": True,
                "rdp_idle_minutes": 5,
                "always_process_patterns": [],
                "load_process_patterns": [
                    "PalServer-Win64-Shipping.exe",
                    "PalServer.exe",
                    "*Server-Win64-Shipping.exe",
                    "ffmpeg.exe",
                    "sunshine.exe"
                ],
                "launcher_process_patterns": [
                    "DGSM*.exe",
                    "dgsm*.exe"
                ],
                "container_process_patterns": [
                    "vmmem*",
                    "wslhost.exe",
                    "wsl.exe",
                    "wslservice.exe",
                    "wslrelay.exe",
                    "com.docker.backend.exe",
                    "com.docker.build.exe",
                    "Docker Desktop.exe",
                    "dockerd.exe"
                ]
            },
        },
        "cpu_compatibility": {
            "auto_apply_efficiency_class_1": True,
        },
        "popup": {
            "hold_ms": 900,
            "fade_ms": 900,
            "width": 390,
            "height": 78,
            "position": "bottom_right",
        },
    },
    "profiles": {
        "summer": {
            "display_name": "Sommer / Browsen",
            "enabled": True,
            "plan": {
                "guid": BALANCED_GUID,
                "name_contains": ["Ausbalanciert", "Balanced"],
            },
            "settings": {
                "processor_min_ac_percent": 5,
                "processor_max_ac_percent": 50,
                "processor_boost_mode_ac": 0,
                "core_parking_min_ac_percent": 10,
                "core_parking_max_ac_percent": 100,
                "energy_preference_ac_percent": 80,
                "cooling_policy_ac": 1,
                "display_timeout_ac_minutes": 0,
                "sleep_timeout_ac_minutes": 0,
                "hibernate_timeout_ac_minutes": 0,
                "processor_min_dc_percent": 5,
                "processor_max_dc_percent": 50,
                "processor_boost_mode_dc": 0,
                "core_parking_min_dc_percent": 5,
                "core_parking_max_dc_percent": 100,
                "energy_preference_dc_percent": 90,
                "cooling_policy_dc": 1,
                "display_timeout_dc_minutes": 0,
                "sleep_timeout_dc_minutes": 0,
                "hibernate_timeout_dc_minutes": 0,
            },
        },
        "performance": {
            "display_name": "Leistung",
            "enabled": True,
            "plan": {
                "guid": ULTIMATE_GUID,
                "name_contains": ["Ultimative Leistung", "Ultimate Performance"],
            },
            "settings": {
                "processor_min_ac_percent": 5,
                "processor_max_ac_percent": 100,
                "processor_boost_mode_ac": 2,
                "core_parking_min_ac_percent": 100,
                "core_parking_max_ac_percent": 100,
                "energy_preference_ac_percent": 0,
                "cooling_policy_ac": 1,
                "display_timeout_ac_minutes": 0,
                "sleep_timeout_ac_minutes": 0,
                "hibernate_timeout_ac_minutes": 0,
                "processor_min_dc_percent": 5,
                "processor_max_dc_percent": 100,
                "processor_boost_mode_dc": 2,
                "core_parking_min_dc_percent": 100,
                "core_parking_max_dc_percent": 100,
                "energy_preference_dc_percent": 0,
                "cooling_policy_dc": 1,
                "display_timeout_dc_minutes": 0,
                "sleep_timeout_dc_minutes": 0,
                "hibernate_timeout_dc_minutes": 0,
            },
        },
    },
}

SETTING_DEFINITIONS: dict[
    str, tuple[str, str, tuple[str, ...], Callable[[Any], int]]
] = {
    # Aliases ending in "1" target efficiency class 1 on heterogeneous CPUs.
    # They are optional and are silently skipped on systems without that class.
    "processor_min_ac_percent": ("ac", "SUB_PROCESSOR", ("PROCTHROTTLEMIN", "PROCTHROTTLEMIN1"), int),
    "processor_max_ac_percent": ("ac", "SUB_PROCESSOR", ("PROCTHROTTLEMAX", "PROCTHROTTLEMAX1"), int),
    "processor_boost_mode_ac": ("ac", "SUB_PROCESSOR", ("PERFBOOSTMODE",), int),
    "core_parking_min_ac_percent": ("ac", "SUB_PROCESSOR", ("CPMINCORES", "CPMINCORES1"), int),
    "core_parking_max_ac_percent": ("ac", "SUB_PROCESSOR", ("CPMAXCORES", "CPMAXCORES1"), int),
    "energy_preference_ac_percent": ("ac", "SUB_PROCESSOR", ("PERFEPP", "PERFEPP1"), int),
    "cooling_policy_ac": ("ac", "SUB_PROCESSOR", ("SYSCOOLPOL",), int),
    "display_timeout_ac_minutes": ("ac", "SUB_VIDEO", ("VIDEOIDLE",), lambda value: int(value) * 60),
    "sleep_timeout_ac_minutes": ("ac", "SUB_SLEEP", ("STANDBYIDLE",), lambda value: int(value) * 60),
    "hibernate_timeout_ac_minutes": ("ac", "SUB_SLEEP", ("HIBERNATEIDLE",), lambda value: int(value) * 60),
    "processor_min_dc_percent": ("dc", "SUB_PROCESSOR", ("PROCTHROTTLEMIN", "PROCTHROTTLEMIN1"), int),
    "processor_max_dc_percent": ("dc", "SUB_PROCESSOR", ("PROCTHROTTLEMAX", "PROCTHROTTLEMAX1"), int),
    "processor_boost_mode_dc": ("dc", "SUB_PROCESSOR", ("PERFBOOSTMODE",), int),
    "core_parking_min_dc_percent": ("dc", "SUB_PROCESSOR", ("CPMINCORES", "CPMINCORES1"), int),
    "core_parking_max_dc_percent": ("dc", "SUB_PROCESSOR", ("CPMAXCORES", "CPMAXCORES1"), int),
    "energy_preference_dc_percent": ("dc", "SUB_PROCESSOR", ("PERFEPP", "PERFEPP1"), int),
    "cooling_policy_dc": ("dc", "SUB_PROCESSOR", ("SYSCOOLPOL",), int),
    "display_timeout_dc_minutes": ("dc", "SUB_VIDEO", ("VIDEOIDLE",), lambda value: int(value) * 60),
    "sleep_timeout_dc_minutes": ("dc", "SUB_SLEEP", ("STANDBYIDLE",), lambda value: int(value) * 60),
    "hibernate_timeout_dc_minutes": ("dc", "SUB_SLEEP", ("HIBERNATEIDLE",), lambda value: int(value) * 60),
}

ADVANCED_CPU_SETTING_KEYS = (
    "core_parking_min_{source}_percent",
    "core_parking_max_{source}_percent",
    "energy_preference_{source}_percent",
)


def application_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_DIR = application_directory()
CONFIG_PATH = APP_DIR / CONFIG_FILE_NAME
LOG_PATH = APP_DIR / LOG_FILE_NAME

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    encoding="utf-8",
)
LOGGER = logging.getLogger(APP_NAME)


def language_from_config(config: dict[str, Any] | None) -> str:
    try:
        language = str((config or {}).get("app", {}).get("language", "de")).lower()
    except Exception:
        language = "de"
    return language if language in TRANSLATIONS else "de"


def translate(config: dict[str, Any] | None, key: str, **values: Any) -> str:
    language = language_from_config(config)
    template = TRANSLATIONS.get(language, TRANSLATIONS["de"]).get(key, key)
    try:
        return template.format(**values)
    except (KeyError, ValueError):
        return template


def deep_copy_json(value: Any) -> Any:
    return json.loads(json.dumps(value))


def deep_merge(default: Any, custom: Any) -> Any:
    if isinstance(default, dict) and isinstance(custom, dict):
        merged = {key: deep_copy_json(value) for key, value in default.items()}
        for key, value in custom.items():
            merged[key] = deep_merge(merged[key], value) if key in merged else deep_copy_json(value)
        return merged
    return deep_copy_json(custom)


def ordered_profile_ids(config: dict[str, Any], enabled_only: bool = False) -> list[str]:
    profiles = config.get("profiles", {})
    if not isinstance(profiles, dict):
        return []
    configured_order = config.get("app", {}).get("profile_order", [])
    order: list[str] = []
    if isinstance(configured_order, list):
        for profile_id in configured_order:
            profile_id = str(profile_id)
            if profile_id in profiles and profile_id not in order:
                order.append(profile_id)
    for profile_id in profiles:
        if profile_id not in order:
            order.append(profile_id)
    if enabled_only:
        order = [profile_id for profile_id in order if bool(profiles[profile_id].get("enabled", True))]
    return order


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def migrate_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Migrate older configs without silently enabling newly added CPU tweaks."""
    migrated = deep_copy_json(raw)
    try:
        schema_version = int(migrated.get("schema_version", 1))
    except (TypeError, ValueError):
        schema_version = 1

    app_config = migrated.setdefault("app", {})
    app_config.setdefault("cpu_compatibility", {})
    app_config["cpu_compatibility"].setdefault("auto_apply_efficiency_class_1", True)

    profiles = migrated.setdefault("profiles", {})
    old_toggle = app_config.get("toggle_profiles", [])
    if not isinstance(old_toggle, list):
        old_toggle = []

    if schema_version < 3:
        for profile in profiles.values():
            if not isinstance(profile, dict):
                continue
            settings = profile.setdefault("settings", {})
            if not isinstance(settings, dict):
                continue
            for source in ("ac", "dc"):
                for template in ADVANCED_CPU_SETTING_KEYS:
                    settings.setdefault(template.format(source=source), None)

    if schema_version < 4:
        order: list[str] = []
        for profile_id in old_toggle:
            profile_id = str(profile_id)
            if profile_id in profiles and profile_id not in order:
                order.append(profile_id)
        for profile_id in profiles:
            if profile_id not in order:
                order.append(profile_id)
        app_config["profile_order"] = order
        for profile_id, profile in profiles.items():
            if isinstance(profile, dict):
                profile.setdefault("enabled", profile_id in old_toggle if old_toggle else True)
        app_config.pop("toggle_profiles", None)

    for profile in profiles.values():
        if isinstance(profile, dict):
            profile.setdefault("enabled", True)

    app_config["profile_order"] = ordered_profile_ids(migrated)
    app_config.pop("toggle_profiles", None)
    dynamic_switch = app_config.setdefault("dynamic_switch", {})
    default_active = "performance" if "performance" in profiles else next(iter(profiles), "")
    default_idle = "summer" if "summer" in profiles else next(iter(profiles), "")
    if "mode" not in dynamic_switch:
        old_enabled = bool(dynamic_switch.get("enabled", False))
        old_active = str(dynamic_switch.get("active_profile_id", default_active))
        old_idle = str(dynamic_switch.get("idle_profile_id", default_idle))
        try:
            old_minutes = int(dynamic_switch.get("idle_minutes", 10))
        except (TypeError, ValueError):
            old_minutes = 10
        dynamic_switch.clear()
        dynamic_switch.update({
            "mode": "idle" if old_enabled else "disabled",
            "manual_override_until_transition": True,
            "idle": {
                "active_profile_id": old_active,
                "idle_profile_id": old_idle,
                "idle_minutes": old_minutes,
            },
            "load": deep_copy_json(DEFAULT_CONFIG["app"]["dynamic_switch"]["load"]),
        })
    dynamic_switch.setdefault("mode", "disabled")
    dynamic_switch.setdefault("manual_override_until_transition", True)
    idle_config = dynamic_switch.setdefault("idle", {})
    idle_config.setdefault("active_profile_id", default_active)
    idle_config.setdefault("idle_profile_id", default_idle)
    idle_config.setdefault("idle_minutes", 10)
    load_config = dynamic_switch.setdefault("load", {})
    for key, value in DEFAULT_CONFIG["app"]["dynamic_switch"]["load"].items():
        load_config.setdefault(key, deep_copy_json(value) if isinstance(value, (dict, list)) else value)
    if schema_version < 8:
        # Replace the old process-based RDP trigger with native session state.
        patterns = load_config.get("always_process_patterns", [])
        if isinstance(patterns, list):
            load_config["always_process_patterns"] = [
                item for item in patterns
                if str(item).strip().lower() != "rdpclip.exe"
            ]
        load_config.setdefault("rdp_session_trigger_enabled", True)
        load_config.setdefault("rdp_idle_minutes", 5)
    dynamic_switch.pop("enabled", None)
    dynamic_switch.pop("active_profile_id", None)
    dynamic_switch.pop("idle_profile_id", None)
    dynamic_switch.pop("idle_minutes", None)
    migrated["schema_version"] = 8
    return migrated

def load_or_create_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        write_json_atomic(CONFIG_PATH, DEFAULT_CONFIG)
        return deep_copy_json(DEFAULT_CONFIG)
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        migrated = migrate_config(raw)
        merged = deep_merge(DEFAULT_CONFIG, migrated)
        if isinstance(migrated.get("profiles"), dict):
            merged["profiles"] = deep_copy_json(migrated["profiles"])
        merged.setdefault("app", {})["profile_order"] = ordered_profile_ids(migrated)
        merged["app"].pop("toggle_profiles", None)
        merged["schema_version"] = 8
        validate_config(merged)
        return merged
    except Exception as exc:
        fallback = deep_copy_json(DEFAULT_CONFIG)
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        backup = APP_DIR / f"config-fehlerhaft-{timestamp}.json"
        try:
            CONFIG_PATH.replace(backup)
        except OSError:
            backup = None
        write_json_atomic(CONFIG_PATH, fallback)
        details = translate(fallback, "config_reset", error=exc)
        if backup is not None:
            details += "\n\n" + translate(fallback, "backup", name=backup.name)
        LOGGER.exception("Invalid config; defaults restored")
        raise ValueError(details) from exc


def validate_config(config: dict[str, Any]) -> None:
    profiles = config.get("profiles")
    if not isinstance(profiles, dict) or len(profiles) < 1:
        raise ValueError(translate(config, "invalid_profiles"))

    profile_order = config.get("app", {}).get("profile_order")
    if not isinstance(profile_order, list):
        raise ValueError("app.profile_order must be a list.")
    for profile_id in profile_order:
        if str(profile_id) not in profiles:
            raise ValueError(translate(config, "invalid_profile_ref", profile=profile_id))
    if not ordered_profile_ids(config, enabled_only=True):
        raise ValueError(translate(config, "at_least_one_enabled"))

    dynamic_switch = config.get("app", {}).get("dynamic_switch", {})
    if not isinstance(dynamic_switch, dict):
        raise ValueError("app.dynamic_switch must be an object.")
    mode = str(dynamic_switch.get("mode", "disabled")).lower()
    if mode not in ("disabled", "idle", "load"):
        raise ValueError(translate(config, "invalid_automatic_mode", mode=mode))
    if mode == "idle":
        idle_config = dynamic_switch.get("idle", {})
        if not isinstance(idle_config, dict):
            raise ValueError("app.dynamic_switch.idle must be an object.")
        active_profile_id = str(idle_config.get("active_profile_id", ""))
        idle_profile_id = str(idle_config.get("idle_profile_id", ""))
        for selected_profile_id in (active_profile_id, idle_profile_id):
            if selected_profile_id not in profiles:
                raise ValueError(translate(config, "dynamic_profile_missing", profile=selected_profile_id))
        if active_profile_id == idle_profile_id:
            raise ValueError(translate(config, "dynamic_same_profile"))
        try:
            idle_minutes = int(idle_config.get("idle_minutes", 0))
        except (TypeError, ValueError) as exc:
            raise ValueError(translate(config, "dynamic_idle_invalid")) from exc
        if idle_minutes < 1:
            raise ValueError(translate(config, "dynamic_idle_invalid"))
    elif mode == "load":
        load_config = dynamic_switch.get("load", {})
        if not isinstance(load_config, dict):
            raise ValueError("app.dynamic_switch.load must be an object.")
        low_profile_id = str(load_config.get("low_profile_id", ""))
        high_profile_id = str(load_config.get("high_profile_id", ""))
        for selected_profile_id in (low_profile_id, high_profile_id):
            if selected_profile_id not in profiles:
                raise ValueError(translate(config, "load_profile_missing", profile=selected_profile_id))
        if low_profile_id == high_profile_id:
            raise ValueError(translate(config, "load_same_profile"))
        threshold_pairs = (
            ("cpu", "cpu_low_percent", "cpu_high_percent"),
            ("process", "process_low_percent", "process_high_percent"),
            ("gpu", "gpu_low_percent", "gpu_high_percent"),
        )
        for label, low_key, high_key in threshold_pairs:
            low_value = int(load_config.get(low_key, 0))
            high_value = int(load_config.get(high_key, 0))
            if not 0 <= low_value <= 100 or not 0 <= high_value <= 100:
                raise ValueError(f"{low_key}/{high_key}: expected 0..100")
            if low_value > high_value:
                raise ValueError(translate(config, "load_threshold_order", label=label))
        for key in ("high_delay_seconds", "low_delay_seconds", "minimum_hold_seconds"):
            if int(load_config.get(key, 0)) < 0:
                raise ValueError(f"{key}: expected >= 0")
        rdp_idle_minutes = int(load_config.get("rdp_idle_minutes", 5))
        if not 1 <= rdp_idle_minutes <= 1440:
            raise ValueError("rdp_idle_minutes: expected 1..1440")
        for key in ("always_process_patterns", "load_process_patterns", "launcher_process_patterns", "container_process_patterns"):
            patterns = load_config.get(key, [])
            if not isinstance(patterns, list) or not all(isinstance(item, str) for item in patterns):
                raise ValueError(f"{key}: expected a list of strings")

    language = str(config.get("app", {}).get("language", "de")).lower()
    if language not in TRANSLATIONS:
        raise ValueError("app.language must be 'de' or 'en'.")
    compatibility = config.get("app", {}).get("cpu_compatibility", {})
    if not isinstance(compatibility, dict):
        raise ValueError("app.cpu_compatibility must be an object.")
    hotkey = config.get("app", {}).get("hotkey", {})
    key = str(hotkey.get("key", "")).upper()
    if key not in VK_CODES:
        raise ValueError(translate(config, "invalid_hotkey", key=key))

    for profile_id, profile in profiles.items():
        if not isinstance(profile, dict):
            raise ValueError(f"Invalid profile: {profile_id}")
        profile["enabled"] = bool(profile.get("enabled", True))
        for setting_name, value in profile.get("settings", {}).items():
            if setting_name not in SETTING_DEFINITIONS or value is None or value == "":
                continue
            numeric = int(value)
            if "percent" in setting_name and not 0 <= numeric <= 100:
                raise ValueError(f"{profile_id}.{setting_name}: expected 0..100")
            if "timeout" in setting_name and numeric < 0:
                raise ValueError(f"{profile_id}.{setting_name}: expected >= 0")
            if "boost_mode" in setting_name and numeric not in BOOST_VALUES:
                raise ValueError(f"{profile_id}.{setting_name}: expected 0..4")
            if "cooling_policy" in setting_name and numeric not in (0, 1):
                raise ValueError(f"{profile_id}.{setting_name}: expected 0, 1 or null")

        settings = profile.get("settings", {})
        for source in ("ac", "dc"):
            cpu_min = settings.get(f"processor_min_{source}_percent")
            cpu_max = settings.get(f"processor_max_{source}_percent")
            if cpu_min is not None and cpu_max is not None and int(cpu_min) > int(cpu_max):
                raise ValueError(translate(config, "invalid_cpu_range", profile=profile.get("display_name", profile_id), source=source.upper()))

            parking_min = settings.get(f"core_parking_min_{source}_percent")
            parking_max = settings.get(f"core_parking_max_{source}_percent")
            if parking_min is not None and parking_max is not None and int(parking_min) > int(parking_max):
                raise ValueError(translate(config, "invalid_parking_range", profile=profile.get("display_name", profile_id), source=source.upper()))

def autostart_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'
    python_executable = Path(sys.executable).resolve()
    pythonw = python_executable.with_name("pythonw.exe")
    runner = pythonw if pythonw.exists() else python_executable
    return f'"{runner}" "{Path(__file__).resolve()}"'


def is_autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_REGISTRY_PATH, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, AUTOSTART_VALUE_NAME)
            return True
    except FileNotFoundError:
        return False
    except OSError:
        LOGGER.exception("Could not read autostart registry value")
        return False


def set_autostart_enabled(enabled: bool) -> None:
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER,
        AUTOSTART_REGISTRY_PATH,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        if enabled:
            winreg.SetValueEx(key, AUTOSTART_VALUE_NAME, 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(key, AUTOSTART_VALUE_NAME)
            except FileNotFoundError:
                pass


def decode_windows_console_output(data: bytes) -> str:
    if not data:
        return ""
    encodings: list[str] = []
    try:
        encodings.append(f"cp{ctypes.windll.kernel32.GetOEMCP()}")
    except Exception:
        pass
    encodings.extend(["mbcs", "utf-8", "cp1252"])
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")


def run_powercfg_result(arguments: list[str]) -> tuple[int, str]:
    completed = subprocess.run(
        [POWERCFG, *arguments],
        capture_output=True,
        text=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
        check=False,
    )
    output = (decode_windows_console_output(completed.stdout) + decode_windows_console_output(completed.stderr)).strip()
    return completed.returncode, output


def run_powercfg(arguments: list[str]) -> str:
    return_code, output = run_powercfg_result(arguments)
    if return_code != 0:
        raise RuntimeError(
            f"powercfg {' '.join(arguments)} failed (code {return_code}).\n"
            f"{output or 'No error text returned.'}"
        )
    return output


def detect_cpu_info() -> dict[str, Any]:
    info: dict[str, Any] = {
        "name": os.environ.get("PROCESSOR_IDENTIFIER", "Unknown CPU"),
        "vendor": "Unknown",
        "architecture": os.environ.get("PROCESSOR_ARCHITECTURE", "Unknown"),
        "logical_processors": os.cpu_count() or 0,
    }
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            0,
            winreg.KEY_READ,
        ) as key:
            for registry_name, target_name in (
                ("ProcessorNameString", "name"),
                ("VendorIdentifier", "vendor"),
                ("Identifier", "identifier"),
            ):
                try:
                    value, _ = winreg.QueryValueEx(key, registry_name)
                    if value:
                        info[target_name] = str(value).strip()
                except OSError:
                    pass
    except OSError:
        LOGGER.exception("Could not read CPU information from registry")

    vendor_text = f"{info.get('vendor', '')} {info.get('name', '')}".casefold()
    if "genuineintel" in vendor_text or "intel" in vendor_text:
        info["vendor_family"] = "Intel"
    elif "authenticamd" in vendor_text or "amd" in vendor_text:
        info["vendor_family"] = "AMD"
    elif "arm" in vendor_text or "qualcomm" in vendor_text:
        info["vendor_family"] = "ARM"
    else:
        info["vendor_family"] = str(info.get("vendor") or "Unknown")
    return info


_PROCESSOR_CAPABILITY_CACHE: dict[str, tuple[bool, set[str]]] = {}


def query_supported_processor_aliases(plan_guid: str, refresh: bool = False) -> tuple[bool, set[str]]:
    normalized = plan_guid.lower()
    if not refresh and normalized in _PROCESSOR_CAPABILITY_CACHE:
        query_ok, aliases = _PROCESSOR_CAPABILITY_CACHE[normalized]
        return query_ok, set(aliases)

    output = ""
    authoritative_query = False

    # /qh includes hidden processor settings such as Core Parking and EPP.
    # If a Windows build does not support /qh, /query is used for display only;
    # it is not treated as an authoritative absence test for hidden settings.
    return_code, candidate = run_powercfg_result(["/qh", normalized, "SUB_PROCESSOR"])
    if return_code == 0 and candidate:
        output = candidate
        authoritative_query = True
    else:
        return_code, candidate = run_powercfg_result(["/query", normalized, "SUB_PROCESSOR"])
        if return_code == 0 and candidate:
            output = candidate

    upper_output = output.upper()
    aliases = {
        alias
        for alias in KNOWN_PROCESSOR_ALIASES
        if re.search(rf"(?<![A-Z0-9_]){re.escape(alias)}(?![A-Z0-9_])", upper_output)
    }
    # An output without recognizable aliases cannot safely be used to decide
    # that a setting is unsupported, for example on unusual localized builds.
    query_ok = authoritative_query and bool(aliases)
    _PROCESSOR_CAPABILITY_CACHE[normalized] = (query_ok, aliases)
    return query_ok, set(aliases)


def processor_capability_summary(plan_guid: str) -> dict[str, Any]:
    query_ok, aliases = query_supported_processor_aliases(plan_guid)
    return {
        "query_ok": query_ok,
        "aliases": sorted(aliases),
        "cpu_range": bool({"PROCTHROTTLEMIN", "PROCTHROTTLEMAX"} & aliases),
        "class1": bool({"PROCTHROTTLEMIN1", "PROCTHROTTLEMAX1", "CPMINCORES1", "CPMAXCORES1", "PERFEPP1"} & aliases),
        "parking": bool({"CPMINCORES", "CPMAXCORES"} & aliases),
        "epp": "PERFEPP" in aliases,
        "boost": "PERFBOOSTMODE" in aliases,
        "cooling": "SYSCOOLPOL" in aliases,
    }


def extract_guids(text: str) -> list[str]:
    return [
        match.lower()
        for match in re.findall(
            r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}",
            text,
        )
    ]


def list_power_plans() -> list[dict[str, Any]]:
    output = run_powercfg(["/list"])
    guid_pattern = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
    patterns = [
        re.compile(rf"(?P<guid>{guid_pattern})\s+\((?P<name>[^)\r\n]+)\)\s*(?P<active>\*)?", re.IGNORECASE),
        re.compile(rf"(?P<guid>{guid_pattern})\s*[:-]\s*(?P<name>[^*\r\n]+?)\s*(?P<active>\*)?$", re.IGNORECASE | re.MULTILINE),
    ]
    plans_by_guid: dict[str, dict[str, Any]] = {}
    for pattern in patterns:
        for match in pattern.finditer(output):
            guid = match.group("guid").lower()
            name = match.group("name").strip().strip("()")
            if name:
                plans_by_guid[guid] = {
                    "guid": guid,
                    "name": name,
                    "active": bool(match.groupdict().get("active")),
                }
    if not plans_by_guid:
        raise RuntimeError("Windows returned no readable power plans. Raw output:\n" + output)
    active_guid = None
    try:
        active_guid = get_active_plan_guid()
    except Exception:
        LOGGER.exception("Could not verify active plan while listing plans")
    plans = list(plans_by_guid.values())
    if active_guid:
        for plan in plans:
            plan["active"] = plan["guid"] == active_guid
    return sorted(plans, key=lambda plan: (not plan["active"], plan["name"].casefold()))


def get_active_plan_guid() -> str:
    guids = extract_guids(run_powercfg(["/getactivescheme"]))
    if not guids:
        raise RuntimeError("The active power plan could not be detected.")
    return guids[0]


def standard_scheme_match(scheme_key: str, plans: list[dict[str, Any]]) -> dict[str, Any] | None:
    scheme = STANDARD_SCHEMES[scheme_key]
    for plan in plans:
        if plan["guid"] == scheme["guid"]:
            return plan
    aliases = [alias.casefold() for alias in scheme["aliases"]]
    for plan in plans:
        name = plan["name"].casefold()
        if any(alias in name for alias in aliases):
            return plan
    return None


def restore_standard_scheme(scheme_key: str, language: str) -> tuple[str, bool]:
    plans = list_power_plans()
    existing = standard_scheme_match(scheme_key, plans)
    if existing is not None:
        return existing["guid"], False
    scheme = STANDARD_SCHEMES[scheme_key]
    output = run_powercfg(["/duplicatescheme", scheme["guid"]])
    guids = extract_guids(output)
    new_guid = guids[-1] if guids else ""
    if not new_guid:
        refreshed = list_power_plans()
        existing = standard_scheme_match(scheme_key, refreshed)
        if existing is None:
            raise RuntimeError("powercfg did not return a new power plan GUID.")
        new_guid = existing["guid"]
    desired_name = scheme["names"].get(language, scheme["names"]["en"])
    try:
        run_powercfg(["/changename", new_guid, desired_name])
    except RuntimeError:
        LOGGER.exception("Could not rename restored standard plan %s", scheme_key)
    return new_guid, True


def remove_power_plan(plan_guid: str) -> None:
    run_powercfg(["/delete", plan_guid])


def resolve_plan_guid(profile: dict[str, Any], plans: list[dict[str, Any]], config: dict[str, Any]) -> str:
    plan_config = profile.get("plan", {})
    configured_guid = str(plan_config.get("guid") or "").strip().lower()
    if configured_guid:
        for plan in plans:
            if plan["guid"] == configured_guid:
                return configured_guid
    aliases = [str(alias).strip().casefold() for alias in plan_config.get("name_contains", []) if str(alias).strip()]
    for alias in aliases:
        for plan in plans:
            if alias in plan["name"].casefold():
                return plan["guid"]
    raise RuntimeError(
        translate(config, "profile_plan_missing", name=profile.get("display_name", "Unknown"))
    )


def apply_profile_settings(
    plan_guid: str,
    settings: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> list[str]:
    warnings: list[str] = []
    query_ok, supported_aliases = query_supported_processor_aliases(plan_guid, refresh=True)
    auto_class1 = bool(
        (config or {}).get("app", {}).get("cpu_compatibility", {}).get(
            "auto_apply_efficiency_class_1", True
        )
    )

    for setting_name, definition in SETTING_DEFINITIONS.items():
        if setting_name not in settings:
            continue
        raw_value = settings.get(setting_name)
        if raw_value is None or raw_value == "":
            continue
        power_source, subgroup, setting_aliases, converter = definition
        command = "/setacvalueindex" if power_source == "ac" else "/setdcvalueindex"
        converted_value = str(converter(raw_value))

        for setting_alias in setting_aliases:
            is_class1 = setting_alias.endswith("1")
            if is_class1 and not auto_class1:
                LOGGER.info("Skipping class-1 setting %s because automatic class-1 support is disabled", setting_alias)
                continue
            if subgroup == "SUB_PROCESSOR" and query_ok and setting_alias not in supported_aliases:
                LOGGER.info("Skipping unsupported processor setting %s on plan %s", setting_alias, plan_guid)
                continue
            try:
                run_powercfg([command, plan_guid, subgroup, setting_alias, converted_value])
            except RuntimeError as exc:
                if is_class1:
                    LOGGER.info("Optional class-1 setting %s is unavailable: %s", setting_alias, exc)
                    continue
                warnings.append(f"{setting_name}/{setting_alias}: {exc}")
                LOGGER.warning("Could not apply %s using %s: %s", setting_name, setting_alias, exc)
    return warnings


def create_mutex_or_exit(config: dict[str, Any] | None = None) -> Any:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        ctypes.windll.user32.MessageBoxW(None, translate(config, "already_running"), APP_NAME, 0x40)
        sys.exit(0)
    return handle


class HotkeyThread(threading.Thread):
    def __init__(self, hotkey_config: dict[str, Any], language: str, action_queue: queue.Queue[tuple[str, Any]]) -> None:
        super().__init__(name="GlobalHotkey", daemon=True)
        self.hotkey_config = hotkey_config
        self.language = language
        self.action_queue = action_queue
        self.thread_id: int | None = None
        self._registered = False

    @staticmethod
    def modifiers_from_config(config: dict[str, Any]) -> int:
        modifiers = MOD_NOREPEAT
        if config.get("ctrl"):
            modifiers |= MOD_CONTROL
        if config.get("alt"):
            modifiers |= MOD_ALT
        if config.get("shift"):
            modifiers |= MOD_SHIFT
        if config.get("win"):
            modifiers |= MOD_WIN
        return modifiers

    @staticmethod
    def display_name(config: dict[str, Any], language: str = "de") -> str:
        labels = TRANSLATIONS.get(language, TRANSLATIONS["de"])
        parts: list[str] = []
        if config.get("ctrl"):
            parts.append(labels["ctrl"])
        if config.get("alt"):
            parts.append(labels["alt"])
        if config.get("shift"):
            parts.append(labels["shift"])
        if config.get("win"):
            parts.append(labels["win"])
        parts.append(str(config.get("key", "F12")).upper())
        return " + ".join(parts)

    def run(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.thread_id = kernel32.GetCurrentThreadId()
        key_name = str(self.hotkey_config.get("key", "F12")).upper()
        virtual_key = VK_CODES.get(key_name)
        if virtual_key is None:
            self.action_queue.put(("hotkey_error", translate({"app": {"language": self.language}}, "hotkey_unknown", key=key_name)))
            return
        modifiers = self.modifiers_from_config(self.hotkey_config)
        if not user32.RegisterHotKey(None, 1, modifiers, virtual_key):
            error_code = ctypes.get_last_error()
            self.action_queue.put((
                "hotkey_error",
                translate(
                    {"app": {"language": self.language}},
                    "hotkey_failed",
                    hotkey=self.display_name(self.hotkey_config, self.language),
                    code=error_code,
                ),
            ))
            return
        self._registered = True
        self.action_queue.put(("hotkey_ready", self.display_name(self.hotkey_config, self.language)))
        message = wintypes.MSG()
        try:
            while True:
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result in (0, -1):
                    break
                if message.message == WM_HOTKEY:
                    self.action_queue.put(("toggle", None))
        finally:
            if self._registered:
                user32.UnregisterHotKey(None, 1)
                self._registered = False

    def stop(self) -> None:
        if self.thread_id is not None:
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)


class ConfigEditor:
    FIELD_ROWS = [
        ("cpu_min", "processor_min_{source}_percent"),
        ("cpu_max", "processor_max_{source}_percent"),
        ("display_timeout", "display_timeout_{source}_minutes"),
        ("sleep_timeout", "sleep_timeout_{source}_minutes"),
        ("hibernate_timeout", "hibernate_timeout_{source}_minutes"),
    ]

    def __init__(self, app: "PowerPlanSwitcherApp") -> None:
        self.app = app
        self.working_profiles: dict[str, dict[str, Any]] = deep_copy_json(app.config.get("profiles", {}))
        self.profile_order: list[str] = ordered_profile_ids(app.config)
        self.profile_tabs: dict[str, ttk.Frame] = {}
        self.profile_tab_ids: dict[str, str] = {}
        self.plus_tab: ttk.Frame | None = None
        self.plans_tab: ttk.Frame | None = None
        self.last_selected_profile_id: str | None = self.profile_order[0] if self.profile_order else None
        self._adding_profile = False
        self.window = tk.Toplevel(app.root)
        self.window.title(f"{APP_NAME} - {self.t('app_config')}")
        self.window.geometry("1020x860")
        self.window.minsize(900, 740)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.variables: dict[str, tk.Variable] = {}
        self.profile_variables: dict[str, dict[str, tk.Variable]] = {}
        self.plan_values: dict[str, str] = {}
        self.plan_comboboxes: list[ttk.Combobox] = []
        self.plan_tree: ttk.Treeview | None = None
        self.standard_var = tk.StringVar()
        self.standard_display_to_key: dict[str, str] = {}
        self.standard_combo: ttk.Combobox | None = None
        self.main_notebook: ttk.Notebook | None = None
        self.dynamic_profile_map: dict[str, str] = {}
        self.dynamic_profile_combos: list[ttk.Combobox] = []
        self.dynamic_mode_map: dict[str, str] = {}
        self.dynamic_mode_combo: ttk.Combobox | None = None
        self.dynamic_idle_frame: ttk.LabelFrame | None = None
        self.dynamic_load_frame: ttk.LabelFrame | None = None
        self.dynamic_idle_widgets: list[tk.Widget] = []
        self.dynamic_load_widgets: list[tk.Widget] = []
        self.dynamic_text_widgets: dict[str, tk.Text] = {}
        self._set_window_icon()
        self._build_ui()
        self._show_window()

    def t(self, key: str, **values: Any) -> str:
        return self.app.t(key, **values)

    def _show_window(self) -> None:
        self.window.update_idletasks()
        self.window.deiconify()
        self.window.lift()
        try:
            self.window.attributes("-topmost", True)
            self.window.after(250, self._disable_topmost)
        except tk.TclError:
            LOGGER.exception("Could not foreground config editor")
        self.window.after(50, self._focus_window)

    def _disable_topmost(self) -> None:
        try:
            if self.window.winfo_exists():
                self.window.attributes("-topmost", False)
        except tk.TclError:
            pass

    def _focus_window(self) -> None:
        try:
            if self.window.winfo_exists():
                self.window.lift()
                self.window.focus_force()
        except tk.TclError:
            LOGGER.exception("Could not focus config editor")

    def _set_window_icon(self) -> None:
        ico = APP_DIR / "logo.ico"
        png = APP_DIR / "logo.png"
        try:
            if ico.exists():
                self.window.iconbitmap(str(ico))
            elif png.exists():
                image = tk.PhotoImage(file=str(png))
                self.window.iconphoto(True, image)
                self.window._icon_reference = image  # type: ignore[attr-defined]
        except tk.TclError:
            LOGGER.exception("Could not set editor icon")

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.window, padding=12)
        outer.pack(fill="both", expand=True)
        notebook = ttk.Notebook(outer)
        self.main_notebook = notebook
        notebook.pack(fill="both", expand=True)

        general_tab = self._create_scrollable_source_tab(notebook, self.t("general"))
        self._build_general_tab(general_tab)

        for profile_id in self.profile_order:
            self._insert_profile_tab(profile_id)

        self.plus_tab = ttk.Frame(notebook, padding=14)
        notebook.add(self.plus_tab, text="+")
        ttk.Label(self.plus_tab, text=self.t("add_profile"), font=("Segoe UI", 12, "bold")).pack(pady=30)

        self.plans_tab = ttk.Frame(notebook, padding=14)
        notebook.add(self.plans_tab, text=self.t("power_plans"))
        self._build_plan_manager_tab(self.plans_tab)

        notebook.bind("<<NotebookTabChanged>>", self._on_main_tab_changed)

        ttk.Label(outer, text=self.t("disabled_profile_note"), wraplength=880, justify="left").pack(fill="x", pady=(10, 2))
        ttk.Label(outer, text=self.t("time_note"), wraplength=880, justify="left").pack(fill="x", pady=(2, 6))
        buttons = ttk.Frame(outer)
        buttons.pack(fill="x")
        ttk.Button(buttons, text=self.t("cancel"), command=self.close).pack(side="right")
        ttk.Button(buttons, text=self.t("save"), command=self.save).pack(side="right", padx=8)
        ttk.Button(buttons, text=self.t("save_apply"), command=self.save_and_apply).pack(side="right")

    def _profile_tab_title(self, profile_id: str) -> str:
        profile = self.working_profiles.get(profile_id, {})
        variables = self.profile_variables.get(profile_id, {})
        name = str(variables.get("display_name").get()).strip() if variables.get("display_name") is not None else str(profile.get("display_name", profile_id))
        enabled = bool(variables.get("enabled").get()) if variables.get("enabled") is not None else bool(profile.get("enabled", True))
        if not enabled:
            return f"{name} [{self.t('profile_disabled_suffix')}]"
        return name

    def _insert_profile_tab(self, profile_id: str) -> None:
        if self.main_notebook is None or profile_id not in self.working_profiles:
            return
        tab = ttk.Frame(self.main_notebook, padding=14)
        self.profile_tabs[profile_id] = tab
        self.profile_tab_ids[str(tab)] = profile_id
        if self.plus_tab is not None:
            plus_index = self.main_notebook.index(self.plus_tab)
            self.main_notebook.insert(plus_index, tab, text=self._profile_tab_title(profile_id))
        else:
            self.main_notebook.add(tab, text=self._profile_tab_title(profile_id))
        self._build_profile_tab(tab, profile_id, self.working_profiles[profile_id])

    def _selected_profile_id(self) -> str | None:
        if self.main_notebook is None:
            return None
        selected = self.main_notebook.select()
        return self.profile_tab_ids.get(str(selected))

    def _on_main_tab_changed(self, _event: tk.Event[Any]) -> None:
        if self.main_notebook is None:
            return
        selected = self.main_notebook.select()
        profile_id = self.profile_tab_ids.get(str(selected))
        if profile_id is not None:
            self.last_selected_profile_id = profile_id
            return
        if self.plus_tab is not None and str(selected) == str(self.plus_tab) and not self._adding_profile:
            self._adding_profile = True
            self.window.after_idle(self.add_profile)

    def add_profile(self) -> None:
        try:
            number = 1
            while f"profile_{number}" in self.working_profiles:
                number += 1
            profile_id = f"profile_{number}"
            template_id = self.last_selected_profile_id if self.last_selected_profile_id in self.working_profiles else (self.profile_order[0] if self.profile_order else None)
            if template_id is not None:
                profile = deep_copy_json(self.working_profiles[template_id])
            else:
                profile = deep_copy_json(DEFAULT_CONFIG["profiles"]["summer"])
            profile["display_name"] = self.t("new_profile", number=number)
            profile["enabled"] = True
            self.working_profiles[profile_id] = profile
            self.profile_order.append(profile_id)
            self._insert_profile_tab(profile_id)
            self.last_selected_profile_id = profile_id
            if self.main_notebook is not None:
                self.main_notebook.select(self.profile_tabs[profile_id])
        finally:
            self._adding_profile = False

    def remove_profile(self, profile_id: str) -> None:
        if profile_id not in self.working_profiles:
            return
        if len(self.working_profiles) <= 1:
            messagebox.showwarning(APP_NAME, self.t("cannot_remove_last_profile"), parent=self.window)
            return
        name = self._profile_tab_title(profile_id)
        if not messagebox.askyesno(
            self.t("confirm_remove_profile_title"),
            self.t("confirm_remove_profile", name=name),
            parent=self.window,
            icon="warning",
        ):
            return
        tab = self.profile_tabs.pop(profile_id, None)
        if tab is not None and self.main_notebook is not None:
            self.profile_tab_ids.pop(str(tab), None)
            self.main_notebook.forget(tab)
            tab.destroy()
        combo_list: list[ttk.Combobox] = []
        for combo in self.plan_comboboxes:
            if str(getattr(combo, "_profile_id", "")) != profile_id:
                combo_list.append(combo)
        self.plan_comboboxes = combo_list
        self.profile_variables.pop(profile_id, None)
        self.working_profiles.pop(profile_id, None)
        self.profile_order = [item for item in self.profile_order if item != profile_id]
        self.last_selected_profile_id = self.profile_order[0] if self.profile_order else None
        self._refresh_dynamic_profile_choices()
        if self.main_notebook is not None and self.last_selected_profile_id is not None:
            self.main_notebook.select(self.profile_tabs[self.last_selected_profile_id])

    def _dynamic_profile_choices(self) -> dict[str, str]:
        choices: dict[str, str] = {}
        for profile_id in self.profile_order:
            profile = self.working_profiles.get(profile_id, {})
            variables = self.profile_variables.get(profile_id, {})
            if variables.get("display_name") is not None:
                name = str(variables["display_name"].get()).strip() or profile_id
            else:
                name = str(profile.get("display_name", profile_id))
            choices[f"{name} [{profile_id}]"] = profile_id
        return choices

    def _refresh_dynamic_profile_choices(self) -> None:
        profile_keys = (
            "dynamic_switch.idle.active_profile_id",
            "dynamic_switch.idle.idle_profile_id",
            "dynamic_switch.load.low_profile_id",
            "dynamic_switch.load.high_profile_id",
        )
        previous_ids: dict[str, str] = {}
        for key in profile_keys:
            variable = self.variables.get(key)
            if variable is not None:
                previous_ids[key] = self.dynamic_profile_map.get(str(variable.get()), "")
        self.dynamic_profile_map = self._dynamic_profile_choices()
        values = list(self.dynamic_profile_map.keys())
        reverse_new = {value: key for key, value in self.dynamic_profile_map.items()}
        for combo in self.dynamic_profile_combos:
            combo.configure(values=values)
        for key, profile_id in previous_ids.items():
            variable = self.variables.get(key)
            if variable is not None and profile_id in reverse_new:
                variable.set(reverse_new[profile_id])
        for key in profile_keys:
            variable = self.variables.get(key)
            if variable is not None and str(variable.get()) not in self.dynamic_profile_map and values:
                variable.set(values[0])

    @staticmethod
    def _set_widget_enabled(widget: tk.Widget, enabled: bool, readonly: bool = False) -> None:
        try:
            if isinstance(widget, ttk.Combobox):
                widget.configure(state="readonly" if enabled and readonly else ("normal" if enabled else "disabled"))
            elif isinstance(widget, tk.Text):
                widget.configure(state="normal" if enabled else "disabled")
            else:
                if enabled:
                    widget.state(["!disabled"])  # type: ignore[attr-defined]
                else:
                    widget.state(["disabled"])  # type: ignore[attr-defined]
        except (tk.TclError, AttributeError):
            LOGGER.exception("Could not update automatic-switch control state")

    def _update_dynamic_control_state(self) -> None:
        mode_variable = self.variables.get("dynamic_switch.mode")
        mode_display = str(mode_variable.get()) if mode_variable is not None else ""
        mode = self.dynamic_mode_map.get(mode_display, "disabled")
        for widget in self.dynamic_idle_widgets:
            self._set_widget_enabled(widget, mode == "idle", readonly=isinstance(widget, ttk.Combobox))
        for widget in self.dynamic_load_widgets:
            self._set_widget_enabled(widget, mode == "load", readonly=isinstance(widget, ttk.Combobox))
        if self.dynamic_idle_frame is not None:
            if mode == "idle":
                self.dynamic_idle_frame.grid()
            else:
                self.dynamic_idle_frame.grid_remove()
        if self.dynamic_load_frame is not None:
            if mode == "load":
                self.dynamic_load_frame.grid()
            else:
                self.dynamic_load_frame.grid_remove()

    def open_process_picker(self, config_key: str) -> None:
        editor = self.dynamic_text_widgets.get(config_key)
        if editor is None:
            return

        dialog = tk.Toplevel(self.window)
        dialog.title(f"{APP_NAME} - {self.t('process_picker_title')}")
        dialog.geometry("920x600")
        dialog.minsize(720, 460)
        dialog.transient(self.window)
        dialog.grab_set()

        outer = ttk.Frame(dialog, padding=12)
        outer.pack(fill="both", expand=True)
        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(0, 8))
        ttk.Label(controls, text=self.t("process_picker_filter")).pack(side="left")
        filter_var = tk.StringVar()
        filter_entry = ttk.Entry(controls, textvariable=filter_var, width=34)
        filter_entry.pack(side="left", padx=(8, 16))
        show_windows_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            controls,
            text=self.t("process_picker_show_windows"),
            variable=show_windows_var,
        ).pack(side="left")

        tree_frame = ttk.Frame(outer)
        tree_frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(
            tree_frame,
            columns=("pid", "path"),
            show="tree headings",
            selectmode="extended",
        )
        tree.heading("#0", text=self.t("process_picker_name"))
        tree.heading("pid", text=self.t("process_picker_pid"))
        tree.heading("path", text=self.t("process_picker_path"))
        tree.column("#0", width=250, minwidth=150, stretch=False)
        tree.column("pid", width=80, minwidth=60, anchor="e", stretch=False)
        tree.column("path", width=520, minwidth=220, stretch=True)
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        note = ttk.Label(outer, text=self.t("process_picker_hidden_note"), wraplength=860, justify="left")
        note.pack(fill="x", pady=(8, 6))
        buttons = ttk.Frame(outer)
        buttons.pack(fill="x")

        process_records: list[dict[str, Any]] = []

        def populate() -> None:
            tree.delete(*tree.get_children())
            query = filter_var.get().strip().lower()
            show_windows = bool(show_windows_var.get())
            for process in process_records:
                if bool(process.get("is_windows")) and not show_windows:
                    continue
                name = str(process.get("name", ""))
                path = str(process.get("path", ""))
                pid = int(process.get("pid", 0))
                haystack = f"{name} {path} {pid}".lower()
                if query and query not in haystack:
                    continue
                tree.insert("", "end", iid=str(pid), text=name, values=(pid, path))

        def refresh() -> None:
            nonlocal process_records
            dialog.configure(cursor="watch")
            dialog.update_idletasks()
            try:
                process_records = list_processes_for_picker()
                populate()
            except Exception as exc:
                LOGGER.exception("Could not enumerate running processes")
                messagebox.showerror(APP_NAME, str(exc), parent=dialog)
            finally:
                dialog.configure(cursor="")

        def add_selection() -> None:
            selected = tree.selection()
            if not selected:
                messagebox.showwarning(APP_NAME, self.t("process_picker_none"), parent=dialog)
                return
            existing = [line.strip() for line in editor.get("1.0", "end").splitlines() if line.strip()]
            existing_lower = {line.lower() for line in existing}
            additions: list[str] = []
            for item_id in selected:
                name = str(tree.item(item_id, "text")).strip()
                if name and name.lower() not in existing_lower:
                    additions.append(name)
                    existing_lower.add(name.lower())
            combined = existing + additions
            editor.delete("1.0", "end")
            editor.insert("1.0", "\n".join(combined))
            dialog.destroy()

        ttk.Button(buttons, text=self.t("cancel"), command=dialog.destroy).pack(side="right")
        ttk.Button(buttons, text=self.t("process_picker_add"), command=add_selection).pack(side="right", padx=8)
        ttk.Button(buttons, text=self.t("process_picker_refresh"), command=refresh).pack(side="left")
        filter_var.trace_add("write", lambda *_args: populate())
        show_windows_var.trace_add("write", lambda *_args: populate())
        tree.bind("<Double-1>", lambda _event: add_selection())
        dialog.after(20, refresh)
        filter_entry.focus_set()

    def _build_general_tab(self, parent: ttk.Frame) -> None:
        config = self.app.config["app"]
        hotkey = config["hotkey"]

        ttk.Label(parent, text=self.t("language"), font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 10))
        language_display = {"Deutsch": "de", "English": "en"}
        current_language = "English" if config.get("language") == "en" else "Deutsch"
        language_var = tk.StringVar(value=current_language)
        self.variables["language"] = language_var
        ttk.Combobox(parent, textvariable=language_var, values=list(language_display.keys()), state="readonly", width=18).grid(row=0, column=1, sticky="w", pady=(0, 10))
        self.variables["language_map"] = language_display  # type: ignore[assignment]

        autostart_var = tk.BooleanVar(value=is_autostart_enabled())
        self.variables["autostart"] = autostart_var
        ttk.Checkbutton(parent, text=self.t("autostart"), variable=autostart_var).grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 16))

        ttk.Label(parent, text=self.t("global_hotkey"), font=("Segoe UI", 11, "bold")).grid(row=2, column=0, columnspan=4, sticky="w", pady=(0, 10))
        ttk.Label(parent, text=self.t("key")).grid(row=3, column=0, sticky="w", padx=(0, 8))
        key_var = tk.StringVar(value=str(hotkey.get("key", "F12")).upper())
        self.variables["hotkey.key"] = key_var
        ttk.Combobox(parent, textvariable=key_var, values=list(VK_CODES.keys()), state="readonly", width=18).grid(row=3, column=1, sticky="w")

        modifiers = ttk.Frame(parent)
        modifiers.grid(row=4, column=0, columnspan=4, sticky="w", pady=(10, 18))
        for column, key in enumerate(("ctrl", "alt", "shift", "win")):
            variable = tk.BooleanVar(value=bool(hotkey.get(key, False)))
            self.variables[f"hotkey.{key}"] = variable
            ttk.Checkbutton(modifiers, text=self.t(key), variable=variable).grid(row=0, column=column, padx=(0, 16))

        show_popup = tk.BooleanVar(value=bool(config.get("show_startup_popup", True)))
        self.variables["show_startup_popup"] = show_popup
        ttk.Checkbutton(parent, text=self.t("startup_popup"), variable=show_popup).grid(row=5, column=0, columnspan=4, sticky="w", pady=4)

        apply_start = tk.BooleanVar(value=bool(config.get("apply_active_profile_on_start", False)))
        self.variables["apply_active_profile_on_start"] = apply_start
        ttk.Checkbutton(parent, text=self.t("apply_on_start"), variable=apply_start).grid(row=6, column=0, columnspan=4, sticky="w", pady=4)

        dynamic = config.get("dynamic_switch", {})
        dynamic_frame = ttk.LabelFrame(parent, text=self.t("automatic_mode"), padding=10)
        dynamic_frame.grid(row=7, column=0, columnspan=4, sticky="ew", pady=(18, 4))
        dynamic_frame.columnconfigure(1, weight=1)

        self.dynamic_mode_map = {
            self.t("automatic_mode_disabled"): "disabled",
            self.t("automatic_mode_idle"): "idle",
            self.t("automatic_mode_load"): "load",
        }
        reverse_modes = {value: key for key, value in self.dynamic_mode_map.items()}
        mode_var = tk.StringVar(value=reverse_modes.get(str(dynamic.get("mode", "disabled")), self.t("automatic_mode_disabled")))
        self.variables["dynamic_switch.mode"] = mode_var
        ttk.Label(dynamic_frame, text=self.t("automatic_mode")).grid(row=0, column=0, sticky="w", padx=(0, 12), pady=4)
        self.dynamic_mode_combo = ttk.Combobox(dynamic_frame, textvariable=mode_var, values=list(self.dynamic_mode_map.keys()), state="readonly", width=38)
        self.dynamic_mode_combo.grid(row=0, column=1, sticky="ew", pady=4)
        self.dynamic_mode_combo.bind("<<ComboboxSelected>>", lambda _event: self._update_dynamic_control_state())

        manual_override = tk.BooleanVar(value=bool(dynamic.get("manual_override_until_transition", True)))
        self.variables["dynamic_switch.manual_override_until_transition"] = manual_override
        ttk.Checkbutton(dynamic_frame, text=self.t("manual_override"), variable=manual_override).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 10))

        self.dynamic_profile_map = self._dynamic_profile_choices()
        reverse_profiles = {profile_id: display for display, profile_id in self.dynamic_profile_map.items()}

        idle_config = dynamic.get("idle", {})
        idle_frame = ttk.LabelFrame(dynamic_frame, text=self.t("idle_mode"), padding=8)
        self.dynamic_idle_frame = idle_frame
        idle_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=5)
        idle_frame.columnconfigure(1, weight=1)
        for row, (label_key, config_key, default_id) in enumerate((
            ("dynamic_active_profile", "active_profile_id", "performance"),
            ("dynamic_idle_profile", "idle_profile_id", "summer"),
        )):
            label = ttk.Label(idle_frame, text=self.t(label_key))
            label.grid(row=row, column=0, sticky="w", padx=(0, 12), pady=4)
            self.dynamic_idle_widgets.append(label)
            profile_id = str(idle_config.get(config_key, default_id))
            variable = tk.StringVar(value=reverse_profiles.get(profile_id, next(iter(self.dynamic_profile_map), "")))
            self.variables[f"dynamic_switch.idle.{config_key}"] = variable
            combo = ttk.Combobox(idle_frame, textvariable=variable, values=list(self.dynamic_profile_map.keys()), state="readonly", width=42)
            combo.grid(row=row, column=1, sticky="ew", pady=4)
            self.dynamic_profile_combos.append(combo)
            self.dynamic_idle_widgets.append(combo)
        idle_label = ttk.Label(idle_frame, text=self.t("dynamic_idle_minutes"))
        idle_label.grid(row=2, column=0, sticky="w", padx=(0, 12), pady=4)
        self.dynamic_idle_widgets.append(idle_label)
        idle_minutes = tk.StringVar(value=str(idle_config.get("idle_minutes", 10)))
        self.variables["dynamic_switch.idle.idle_minutes"] = idle_minutes
        idle_spinbox = ttk.Spinbox(idle_frame, textvariable=idle_minutes, from_=1, to=1440, width=12)
        idle_spinbox.grid(row=2, column=1, sticky="w", pady=4)
        self.dynamic_idle_widgets.append(idle_spinbox)
        idle_note = ttk.Label(idle_frame, text=self.t("dynamic_switch_note"), wraplength=790, justify="left")
        idle_note.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.dynamic_idle_widgets.append(idle_note)

        load_config = dynamic.get("load", {})
        load_frame = ttk.LabelFrame(dynamic_frame, text=self.t("load_mode"), padding=8)
        self.dynamic_load_frame = load_frame
        load_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=5)
        load_frame.columnconfigure(1, weight=1)
        for row, (label_key, config_key, default_id) in enumerate((
            ("load_low_profile", "low_profile_id", "summer"),
            ("load_high_profile", "high_profile_id", "performance"),
        )):
            label = ttk.Label(load_frame, text=self.t(label_key))
            label.grid(row=row, column=0, sticky="w", padx=(0, 12), pady=4)
            self.dynamic_load_widgets.append(label)
            profile_id = str(load_config.get(config_key, default_id))
            variable = tk.StringVar(value=reverse_profiles.get(profile_id, next(iter(self.dynamic_profile_map), "")))
            self.variables[f"dynamic_switch.load.{config_key}"] = variable
            combo = ttk.Combobox(load_frame, textvariable=variable, values=list(self.dynamic_profile_map.keys()), state="readonly", width=42)
            combo.grid(row=row, column=1, sticky="ew", pady=4)
            self.dynamic_profile_combos.append(combo)
            self.dynamic_load_widgets.append(combo)

        numeric_fields = (
            ("load_cpu_high", "cpu_high_percent", 35, 0, 100),
            ("load_cpu_low", "cpu_low_percent", 15, 0, 100),
            ("load_process_high", "process_high_percent", 3, 0, 100),
            ("load_process_low", "process_low_percent", 1, 0, 100),
            ("load_gpu_high", "gpu_high_percent", 25, 0, 100),
            ("load_gpu_low", "gpu_low_percent", 10, 0, 100),
            ("load_high_delay", "high_delay_seconds", 15, 0, 86400),
            ("load_low_delay", "low_delay_seconds", 120, 0, 86400),
            ("load_min_hold", "minimum_hold_seconds", 30, 0, 86400),
        )
        for offset, (label_key, config_key, default, _minimum, _maximum) in enumerate(numeric_fields, start=2):
            label = ttk.Label(load_frame, text=self.t(label_key))
            label.grid(row=offset, column=0, sticky="w", padx=(0, 12), pady=3)
            self.dynamic_load_widgets.append(label)
            variable = tk.StringVar(value=str(load_config.get(config_key, default)))
            self.variables[f"dynamic_switch.load.{config_key}"] = variable
            entry = ttk.Entry(load_frame, textvariable=variable, width=12)
            entry.grid(row=offset, column=1, sticky="w", pady=3)
            self.dynamic_load_widgets.append(entry)

        gpu_enabled = tk.BooleanVar(value=bool(load_config.get("gpu_enabled", True)))
        self.variables["dynamic_switch.load.gpu_enabled"] = gpu_enabled
        gpu_check = ttk.Checkbutton(load_frame, text=self.t("load_gpu_enable"), variable=gpu_enabled)
        gpu_check.grid(row=11, column=0, columnspan=2, sticky="w", pady=(6, 3))
        self.dynamic_load_widgets.append(gpu_check)

        include_children = tk.BooleanVar(value=bool(load_config.get("include_process_children", True)))
        self.variables["dynamic_switch.load.include_process_children"] = include_children
        children_check = ttk.Checkbutton(load_frame, text=self.t("load_include_children"), variable=include_children)
        children_check.grid(row=12, column=0, columnspan=2, sticky="w", pady=3)
        self.dynamic_load_widgets.append(children_check)

        rdp_enabled = tk.BooleanVar(value=bool(load_config.get("rdp_session_trigger_enabled", True)))
        self.variables["dynamic_switch.load.rdp_session_trigger_enabled"] = rdp_enabled
        rdp_check = ttk.Checkbutton(load_frame, text=self.t("rdp_session_trigger"), variable=rdp_enabled)
        rdp_check.grid(row=13, column=0, columnspan=2, sticky="w", pady=(8, 3))
        self.dynamic_load_widgets.append(rdp_check)

        rdp_idle_label = ttk.Label(load_frame, text=self.t("rdp_idle_minutes"))
        rdp_idle_label.grid(row=14, column=0, sticky="w", padx=(0, 12), pady=3)
        self.dynamic_load_widgets.append(rdp_idle_label)
        rdp_idle_minutes = tk.StringVar(value=str(load_config.get("rdp_idle_minutes", 5)))
        self.variables["dynamic_switch.load.rdp_idle_minutes"] = rdp_idle_minutes
        rdp_idle_entry = ttk.Entry(load_frame, textvariable=rdp_idle_minutes, width=12)
        rdp_idle_entry.grid(row=14, column=1, sticky="w", pady=3)
        self.dynamic_load_widgets.append(rdp_idle_entry)

        rdp_note = ttk.Label(load_frame, text=self.t("rdp_session_note"), wraplength=790, justify="left")
        rdp_note.grid(row=15, column=0, columnspan=2, sticky="w", pady=(3, 4))
        self.dynamic_load_widgets.append(rdp_note)

        patterns_frame = ttk.Frame(load_frame)
        patterns_frame.grid(row=16, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        patterns_frame.columnconfigure(1, weight=1)
        self.dynamic_load_widgets.append(patterns_frame)
        pattern_fields = (
            ("process_always", "always_process_patterns"),
            ("process_load", "load_process_patterns"),
            ("process_launchers", "launcher_process_patterns"),
            ("process_containers", "container_process_patterns"),
        )
        for row, (label_key, config_key) in enumerate(pattern_fields):
            label = ttk.Label(patterns_frame, text=self.t(label_key))
            label.grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=4)
            self.dynamic_load_widgets.append(label)
            editor = tk.Text(patterns_frame, height=3, width=48, wrap="none")
            editor.grid(row=row, column=1, sticky="ew", pady=4)
            patterns = load_config.get(config_key, [])
            editor.insert("1.0", "\n".join(str(item) for item in patterns if str(item).strip()))
            self.dynamic_text_widgets[config_key] = editor
            self.dynamic_load_widgets.append(editor)
            picker_button = ttk.Button(
                patterns_frame,
                text=self.t("choose_running_processes"),
                command=partial(self.open_process_picker, config_key),
            )
            picker_button.grid(row=row, column=2, sticky="n", padx=(10, 0), pady=4)
            self.dynamic_load_widgets.append(picker_button)

        immediate_note = ttk.Label(load_frame, text=self.t("process_immediate_note"), wraplength=790, justify="left")
        immediate_note.grid(row=17, column=0, columnspan=2, sticky="w", pady=(5, 0))
        self.dynamic_load_widgets.append(immediate_note)
        patterns_note = ttk.Label(load_frame, text=self.t("process_patterns_note"), wraplength=790, justify="left")
        patterns_note.grid(row=18, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.dynamic_load_widgets.append(patterns_note)
        load_note = ttk.Label(load_frame, text=self.t("load_mode_note"), wraplength=790, justify="left")
        load_note.grid(row=19, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.dynamic_load_widgets.append(load_note)
        self._update_dynamic_control_state()

        ttk.Label(parent, text=self.t("cpu_compatibility"), font=("Segoe UI", 11, "bold")).grid(row=8, column=0, columnspan=4, sticky="w", pady=(20, 8))
        cpu_info = self.app.cpu_info
        ttk.Label(parent, text=self.t("detected_cpu", name=cpu_info.get("name", "Unknown")), wraplength=850, justify="left").grid(row=9, column=0, columnspan=4, sticky="w", pady=2)
        ttk.Label(parent, text=self.t("cpu_details", vendor=cpu_info.get("vendor_family", cpu_info.get("vendor", "Unknown")), logical=cpu_info.get("logical_processors", 0), architecture=cpu_info.get("architecture", "Unknown")), wraplength=850, justify="left").grid(row=10, column=0, columnspan=4, sticky="w", pady=2)
        ttk.Label(parent, text=self.app.cpu_capability_text(), wraplength=850, justify="left").grid(row=11, column=0, columnspan=4, sticky="w", pady=(2, 8))
        compatibility = config.get("cpu_compatibility", {})
        auto_class1 = tk.BooleanVar(value=bool(compatibility.get("auto_apply_efficiency_class_1", True)))
        self.variables["cpu_compatibility.auto_apply_efficiency_class_1"] = auto_class1
        ttk.Checkbutton(parent, text=self.t("auto_class1"), variable=auto_class1).grid(row=12, column=0, columnspan=4, sticky="w", pady=4)
        ttk.Label(parent, text=self.t("auto_class1_note"), wraplength=850, justify="left").grid(row=13, column=0, columnspan=4, sticky="w", pady=(0, 8))

        popup = config.get("popup", {})
        ttk.Label(parent, text=self.t("popup"), font=("Segoe UI", 11, "bold")).grid(row=14, column=0, columnspan=4, sticky="w", pady=(20, 10))
        popup_fields = [(self.t("visible_ms"), "hold_ms", 900), (self.t("fade_ms"), "fade_ms", 900), (self.t("width"), "width", 390), (self.t("height"), "height", 78)]
        for row, (label, key, default) in enumerate(popup_fields, start=15):
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
            variable = tk.StringVar(value=str(popup.get(key, default)))
            self.variables[f"popup.{key}"] = variable
            ttk.Entry(parent, textvariable=variable, width=16).grid(row=row, column=1, sticky="w")
        parent.columnconfigure(1, weight=1)

    def _create_scrollable_source_tab(
        self, notebook: ttk.Notebook, title: str
    ) -> ttk.Frame:
        container = ttk.Frame(notebook)
        notebook.add(container, text=title)
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        canvas = tk.Canvas(container, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        content = ttk.Frame(canvas, padding=12)
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")

        def update_scroll_region(_event: tk.Event[Any]) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def fit_content_width(event: tk.Event[Any]) -> None:
            canvas.itemconfigure(window_id, width=event.width)

        def scroll_with_wheel(event: tk.Event[Any]) -> None:
            delta = -1 if event.delta > 0 else 1
            canvas.yview_scroll(delta * 3, "units")

        def bind_mousewheel(_event: tk.Event[Any]) -> None:
            canvas.bind_all("<MouseWheel>", scroll_with_wheel)

        def unbind_mousewheel(_event: tk.Event[Any]) -> None:
            canvas.unbind_all("<MouseWheel>")

        content.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", fit_content_width)
        canvas.bind("<Enter>", bind_mousewheel)
        canvas.bind("<Leave>", unbind_mousewheel)
        content.bind("<Enter>", bind_mousewheel)
        content.bind("<Leave>", unbind_mousewheel)
        return content


    def _build_profile_tab(self, parent: ttk.Frame, profile_id: str, profile: dict[str, Any]) -> None:
        variables: dict[str, tk.Variable] = {}
        self.profile_variables[profile_id] = variables

        enabled_var = tk.BooleanVar(value=bool(profile.get("enabled", True)))
        variables["enabled"] = enabled_var
        ttk.Checkbutton(parent, text=self.t("profile_enabled"), variable=enabled_var).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        ttk.Button(parent, text=self.t("remove_profile"), command=partial(self.remove_profile, profile_id)).grid(row=0, column=3, sticky="e", pady=(0, 8))

        ttk.Label(parent, text=self.t("profile_name")).grid(row=1, column=0, sticky="w", pady=4)
        name_var = tk.StringVar(value=str(profile.get("display_name", profile_id)))
        variables["display_name"] = name_var
        ttk.Entry(parent, textvariable=name_var, width=36).grid(row=1, column=1, columnspan=3, sticky="ew", pady=4)

        ttk.Label(parent, text=self.t("windows_plan")).grid(row=2, column=0, sticky="w", pady=4)
        plan_var = tk.StringVar()
        variables["plan_selection"] = plan_var
        combo = ttk.Combobox(parent, textvariable=plan_var, width=70)
        combo.grid(row=2, column=1, columnspan=3, sticky="ew", pady=4)
        self.plan_comboboxes.append(combo)
        combo._profile_id = profile_id  # type: ignore[attr-defined]

        settings = profile.get("settings", {})
        notebook = ttk.Notebook(parent)
        notebook.grid(row=3, column=0, columnspan=4, sticky="nsew", pady=(14, 0))
        for source, title_key in (("ac", "mains"), ("dc", "battery")):
            tab = self._create_scrollable_source_tab(notebook, self.t(title_key))
            self._build_source_settings(tab, variables, settings, source)
        parent.rowconfigure(3, weight=1)
        parent.columnconfigure(1, weight=1)
        parent.columnconfigure(2, weight=1)
        parent.columnconfigure(3, weight=1)
        self._refresh_profile_plan_combobox(combo, profile_id)

        def update_profile_tab_title(*_args: Any) -> None:
            if self.main_notebook is None:
                return
            tab = self.profile_tabs.get(profile_id)
            if tab is None:
                return
            try:
                self.main_notebook.tab(tab, text=self._profile_tab_title(profile_id))
            except tk.TclError:
                pass

        def update_profile_choices(*_args: Any) -> None:
            update_profile_tab_title()
            self._refresh_dynamic_profile_choices()

        name_var.trace_add("write", update_profile_choices)
        enabled_var.trace_add("write", update_profile_tab_title)
        update_profile_tab_title()

    def _boost_labels(self) -> dict[str, int]:
        return {self.t(f"boost_{value}"): value for value in BOOST_VALUES}

    def _cooling_labels(self) -> dict[str, int | None]:
        return {
            self.t("cool_none"): None,
            self.t("cool_0"): 0,
            self.t("cool_1"): 1,
        }

    def _parking_labels(self) -> dict[str, str]:
        return {
            self.t("parking_unchanged"): "unchanged",
            self.t("parking_custom"): "custom",
            self.t("parking_disabled"): "disabled",
        }

    def _build_source_settings(
        self,
        parent: ttk.Frame,
        variables: dict[str, tk.Variable],
        settings: dict[str, Any],
        source: str,
    ) -> None:
        parent.columnconfigure(0, weight=1)

        performance_frame = ttk.LabelFrame(parent, text=self.t("advanced_cpu"), padding=10)
        performance_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        performance_frame.columnconfigure(2, weight=1)

        performance_rows = [
            ("cpu_min", f"processor_min_{source}_percent"),
            ("cpu_max", f"processor_max_{source}_percent"),
        ]
        row = 0
        for label_key, key in performance_rows:
            ttk.Label(performance_frame, text=self.t(label_key)).grid(row=row, column=0, sticky="w", pady=5)
            value = settings.get(key)
            variable = tk.StringVar(value="" if value is None else str(value))
            variables[key] = variable
            ttk.Spinbox(performance_frame, textvariable=variable, from_=0, to=100, width=12).grid(row=row, column=1, sticky="w", padx=(12, 0), pady=5)
            row += 1

        boost_labels = self._boost_labels()
        boost_key = f"processor_boost_mode_{source}"
        ttk.Label(performance_frame, text=self.t("boost_mode")).grid(row=row, column=0, sticky="w", pady=5)
        boost_value = settings.get(boost_key, 0)
        boost_label = next((label for label, value in boost_labels.items() if value == boost_value), self.t("boost_0"))
        boost_var = tk.StringVar(value=boost_label)
        variables[boost_key] = boost_var
        ttk.Combobox(performance_frame, textvariable=boost_var, values=list(boost_labels.keys()), state="readonly", width=32).grid(row=row, column=1, sticky="w", padx=(12, 0), pady=5)
        row += 1

        cooling_labels = self._cooling_labels()
        cooling_key = f"cooling_policy_{source}"
        ttk.Label(performance_frame, text=self.t("cooling_policy")).grid(row=row, column=0, sticky="w", pady=5)
        cooling_value = settings.get(cooling_key)
        cooling_label = next((label for label, value in cooling_labels.items() if value == cooling_value), self.t("cool_none"))
        cooling_var = tk.StringVar(value=cooling_label)
        variables[cooling_key] = cooling_var
        ttk.Combobox(performance_frame, textvariable=cooling_var, values=list(cooling_labels.keys()), state="readonly", width=32).grid(row=row, column=1, sticky="w", padx=(12, 0), pady=5)

        parking_frame = ttk.LabelFrame(parent, text=self.t("core_parking"), padding=10)
        parking_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        parking_frame.columnconfigure(2, weight=1)

        parking_min_key = f"core_parking_min_{source}_percent"
        parking_max_key = f"core_parking_max_{source}_percent"
        parking_min_value = settings.get(parking_min_key)
        parking_max_value = settings.get(parking_max_key)
        parking_labels = self._parking_labels()
        if parking_min_value is None and parking_max_value is None:
            parking_mode_value = "unchanged"
        elif int(parking_min_value or 0) == 100 and int(parking_max_value or 100) == 100:
            parking_mode_value = "disabled"
        else:
            parking_mode_value = "custom"
        parking_mode_label = next(label for label, value in parking_labels.items() if value == parking_mode_value)
        parking_mode_var = tk.StringVar(value=parking_mode_label)
        variables[f"core_parking_mode_{source}"] = parking_mode_var
        ttk.Label(parking_frame, text=self.t("core_parking_mode")).grid(row=0, column=0, sticky="w", pady=5)
        ttk.Combobox(parking_frame, textvariable=parking_mode_var, values=list(parking_labels.keys()), state="readonly", width=42).grid(row=0, column=1, sticky="w", padx=(12, 0), pady=5)

        parking_min_var = tk.StringVar(value="10" if parking_min_value is None else str(parking_min_value))
        parking_max_var = tk.StringVar(value="100" if parking_max_value is None else str(parking_max_value))
        variables[parking_min_key] = parking_min_var
        variables[parking_max_key] = parking_max_var
        ttk.Label(parking_frame, text=self.t("parking_min")).grid(row=1, column=0, sticky="w", pady=5)
        parking_min_widget = ttk.Spinbox(parking_frame, textvariable=parking_min_var, from_=0, to=100, width=12)
        parking_min_widget.grid(row=1, column=1, sticky="w", padx=(12, 0), pady=5)
        ttk.Label(parking_frame, text=self.t("parking_max")).grid(row=2, column=0, sticky="w", pady=5)
        parking_max_widget = ttk.Spinbox(parking_frame, textvariable=parking_max_var, from_=0, to=100, width=12)
        parking_max_widget.grid(row=2, column=1, sticky="w", padx=(12, 0), pady=5)
        ttk.Label(parking_frame, text=self.t("core_parking_note"), wraplength=780, justify="left").grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))

        epp_frame = ttk.LabelFrame(parent, text=self.t("energy_preference"), padding=10)
        epp_frame.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        epp_frame.columnconfigure(2, weight=1)
        epp_key = f"energy_preference_{source}_percent"
        epp_value = settings.get(epp_key)
        epp_enabled_var = tk.BooleanVar(value=epp_value is not None)
        epp_var = tk.StringVar(value="50" if epp_value is None else str(epp_value))
        variables[f"energy_preference_enabled_{source}"] = epp_enabled_var
        variables[epp_key] = epp_var
        ttk.Checkbutton(epp_frame, text=self.t("energy_preference_enable"), variable=epp_enabled_var).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 5))
        ttk.Label(epp_frame, text=self.t("energy_preference_value")).grid(row=1, column=0, sticky="w", pady=5)
        epp_widget = ttk.Spinbox(epp_frame, textvariable=epp_var, from_=0, to=100, width=12)
        epp_widget.grid(row=1, column=1, sticky="w", padx=(12, 0), pady=5)
        ttk.Label(epp_frame, text=self.t("energy_preference_note"), wraplength=780, justify="left").grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))

        time_frame = ttk.LabelFrame(parent, text=self.t("timeouts"), padding=10)
        time_frame.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        time_fields = [
            ("display_timeout", f"display_timeout_{source}_minutes"),
            ("sleep_timeout", f"sleep_timeout_{source}_minutes"),
            ("hibernate_timeout", f"hibernate_timeout_{source}_minutes"),
        ]
        for time_row, (label_key, key) in enumerate(time_fields):
            ttk.Label(time_frame, text=self.t(label_key)).grid(row=time_row, column=0, sticky="w", pady=5)
            value = settings.get(key)
            variable = tk.StringVar(value="" if value is None else str(value))
            variables[key] = variable
            ttk.Entry(time_frame, textvariable=variable, width=14).grid(row=time_row, column=1, sticky="w", padx=(12, 0), pady=5)

        summary_frame = ttk.LabelFrame(parent, text=self.t("interaction_summary"), padding=10)
        summary_frame.grid(row=4, column=0, sticky="ew")
        summary_label = ttk.Label(summary_frame, text="", wraplength=800, justify="left")
        summary_label.pack(fill="x")
        summary_frame.grid_remove()

        def safe_int(variable: tk.Variable, fallback: int) -> int:
            try:
                return int(str(variable.get()).strip())
            except (TypeError, ValueError, tk.TclError):
                return fallback

        def update_summary(*_args: Any) -> None:
            messages: list[str] = []
            cpu_min = safe_int(variables[f"processor_min_{source}_percent"], 0)
            cpu_max = safe_int(variables[f"processor_max_{source}_percent"], 100)
            boost_mode = boost_labels.get(boost_var.get(), 0)
            parking_mode = parking_labels.get(parking_mode_var.get(), "unchanged")
            parking_min = safe_int(parking_min_var, 0)
            parking_max = safe_int(parking_max_var, 100)
            epp = safe_int(epp_var, 50)
            if cpu_min > cpu_max:
                messages.append(self.t("interaction_cpu_range"))
            if cpu_max < 100 and boost_mode > 0:
                messages.append(self.t("interaction_boost_cap"))
            if epp_enabled_var.get() and epp >= 70 and boost_mode >= 2:
                messages.append(self.t("interaction_epp_boost"))
            if parking_mode == "custom":
                if parking_min > parking_max:
                    messages.append(self.t("interaction_parking_range"))
                if parking_max < 100:
                    messages.append(self.t("interaction_parking_limit"))
            if messages:
                summary_label.configure(text="\n".join(f"• {message}" for message in messages))
                summary_frame.grid()
            else:
                summary_label.configure(text="")
                summary_frame.grid_remove()

        def update_parking_controls(*_args: Any) -> None:
            mode = parking_labels.get(parking_mode_var.get(), "unchanged")
            state = "normal" if mode == "custom" else "disabled"
            parking_min_widget.configure(state=state)
            parking_max_widget.configure(state=state)
            update_summary()

        def update_epp_controls(*_args: Any) -> None:
            epp_widget.configure(state="normal" if epp_enabled_var.get() else "disabled")
            update_summary()

        for variable in (variables[f"processor_min_{source}_percent"], variables[f"processor_max_{source}_percent"], boost_var, parking_min_var, parking_max_var, epp_var):
            variable.trace_add("write", update_summary)
        parking_mode_var.trace_add("write", update_parking_controls)
        epp_enabled_var.trace_add("write", update_epp_controls)
        update_parking_controls()
        update_epp_controls()

    def _build_plan_manager_tab(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text=self.t("installed_plans"), font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 8))
        columns = ("status", "name", "guid")
        tree = ttk.Treeview(parent, columns=columns, show="headings", height=12, selectmode="browse")
        self.plan_tree = tree
        tree.heading("status", text=self.t("status"))
        tree.heading("name", text=self.t("name"))
        tree.heading("guid", text=self.t("guid"))
        tree.column("status", width=90, stretch=False)
        tree.column("name", width=280)
        tree.column("guid", width=330)
        tree.pack(fill="both", expand=True)

        plan_buttons = ttk.Frame(parent)
        plan_buttons.pack(fill="x", pady=(8, 14))
        ttk.Button(plan_buttons, text=self.t("refresh"), command=self.refresh_plan_views).pack(side="left")
        ttk.Button(plan_buttons, text=self.t("activate_selected"), command=self.activate_selected_plan).pack(side="left", padx=8)
        ttk.Button(plan_buttons, text=self.t("remove_selected"), command=self.remove_selected_plan).pack(side="left")

        standard_frame = ttk.LabelFrame(parent, text=self.t("restore_standard"), padding=10)
        standard_frame.pack(fill="x", pady=(0, 10))
        ttk.Label(standard_frame, text=self.t("standard_plan")).pack(side="left")
        self.standard_combo = ttk.Combobox(
            standard_frame,
            textvariable=self.standard_var,
            values=[],
            state="readonly",
            width=42,
        )
        self.standard_combo.pack(side="left", padx=10)
        ttk.Button(standard_frame, text=self.t("restore_standard"), command=self.restore_selected_standard).pack(side="left")
        ttk.Label(parent, text=self.t("plan_manager_note"), wraplength=880, justify="left").pack(fill="x")
        self.refresh_plan_views()

    def _plans(self) -> list[dict[str, Any]]:
        plans = self.app.safe_list_power_plans(show_error=True)
        if not plans:
            raise RuntimeError(self.t("no_plans"))
        return plans

    def refresh_plan_views(self) -> None:
        try:
            plans = self._plans()
            self.plan_values.clear()
            if self.plan_tree is not None:
                for item in self.plan_tree.get_children():
                    self.plan_tree.delete(item)
                for plan in plans:
                    status = self.t("active") if plan["active"] else self.t("installed")
                    self.plan_tree.insert("", "end", iid=plan["guid"], values=(status, plan["name"], plan["guid"]))
            for combo in self.plan_comboboxes:
                profile_id = str(combo._profile_id)  # type: ignore[attr-defined]
                self._refresh_profile_plan_combobox(combo, profile_id, plans)
            self._refresh_standard_combo(plans)
        except Exception as exc:
            LOGGER.exception("Could not refresh plan views")
            messagebox.showerror(APP_NAME, str(exc), parent=self.window)


    def _refresh_standard_combo(self, plans: list[dict[str, Any]]) -> None:
        if self.standard_combo is None:
            return
        previous_key = self.standard_display_to_key.get(self.standard_var.get())
        self.standard_display_to_key.clear()
        values: list[str] = []
        selected_display = ""
        for scheme_key, scheme in STANDARD_SCHEMES.items():
            name = scheme["names"].get(self.app.language, scheme["names"]["en"])
            present = standard_scheme_match(scheme_key, plans) is not None
            status = self.t("installed") if present else self.t("missing")
            display = f"{name} — {status}"
            values.append(display)
            self.standard_display_to_key[display] = scheme_key
            if scheme_key == previous_key:
                selected_display = display
        self.standard_combo.configure(values=values)
        if not selected_display and values:
            selected_display = values[0]
        self.standard_var.set(selected_display)

    def _refresh_profile_plan_combobox(self, combo: ttk.Combobox, profile_id: str, plans: list[dict[str, Any]] | None = None) -> None:
        plans = plans if plans is not None else self.app.safe_list_power_plans(show_error=False)
        profile = self.working_profiles[profile_id]
        configured_guid = str(profile.get("plan", {}).get("guid") or "").lower()
        values: list[str] = []
        selected = ""
        for plan in plans:
            display = f"{plan['name']} | {plan['guid']}"
            values.append(display)
            self.plan_values[display] = plan["guid"]
            if plan["guid"] == configured_guid:
                selected = display
        if configured_guid and not selected:
            selected = self.t("missing_plan_selection", guid=configured_guid)
            values.insert(0, selected)
            self.plan_values[selected] = configured_guid
        combo.configure(values=values, state="readonly" if values else "normal")
        variable = self.profile_variables[profile_id]["plan_selection"]
        if selected:
            variable.set(selected)
        elif values and not variable.get():
            variable.set(values[0])

    def _selected_plan(self) -> dict[str, Any]:
        if self.plan_tree is None:
            raise ValueError(self.t("select_installed"))
        selection = self.plan_tree.selection()
        if not selection:
            raise ValueError(self.t("select_installed"))
        guid = selection[0]
        for plan in self._plans():
            if plan["guid"] == guid:
                return plan
        raise ValueError(self.t("select_installed"))

    def activate_selected_plan(self) -> None:
        try:
            plan = self._selected_plan()
            run_powercfg(["/setactive", plan["guid"]])
            self.app.show_popup(self.t("plan_activated", name=plan["name"]))
            self.refresh_plan_views()
        except Exception as exc:
            LOGGER.exception("Could not activate selected plan")
            messagebox.showerror(APP_NAME, str(exc), parent=self.window)

    def _profile_uses_guid(self, guid: str) -> bool:
        plans = self.app.safe_list_power_plans(show_error=False)
        for profile_id in self.profile_order:
            try:
                variables = self.profile_variables.get(profile_id, {})
                selected = self.plan_values.get(str(variables.get("plan_selection").get())) if variables.get("plan_selection") is not None else None
                if selected == guid:
                    return True
                profile = self.working_profiles[profile_id]
                if resolve_plan_guid(profile, plans, self.app.config) == guid:
                    return True
            except Exception:
                continue
        return False

    def remove_selected_plan(self) -> None:
        try:
            plan = self._selected_plan()
            if plan["active"] or plan["guid"] == get_active_plan_guid():
                raise ValueError(self.t("cannot_remove_active"))
            if self._profile_uses_guid(plan["guid"]):
                raise ValueError(self.t("cannot_remove_profile"))
            confirmed = messagebox.askyesno(
                self.t("confirm_remove_title"),
                self.t("confirm_remove", name=plan["name"]),
                parent=self.window,
                icon="warning",
            )
            if not confirmed:
                return
            remove_power_plan(plan["guid"])
            self.app.show_popup(self.t("plan_removed", name=plan["name"]))
            self.refresh_plan_views()
        except Exception as exc:
            LOGGER.exception("Could not remove selected plan")
            messagebox.showerror(APP_NAME, str(exc), parent=self.window)

    def restore_selected_standard(self) -> None:
        try:
            display = self.standard_var.get()
            scheme_key = self.standard_display_to_key.get(display)
            if not scheme_key:
                raise ValueError(self.t("select_standard"))
            guid, created = restore_standard_scheme(scheme_key, self.app.language)
            scheme_name = STANDARD_SCHEMES[scheme_key]["names"].get(self.app.language, display)
            message = self.t("plan_restored", name=scheme_name) if created else self.t("plan_already_present", name=scheme_name)
            self.app.show_popup(message)
            LOGGER.info("Standard plan %s resolved as %s, created=%s", scheme_key, guid, created)
            self.refresh_plan_views()
        except Exception as exc:
            LOGGER.exception("Could not restore standard plan")
            messagebox.showerror(APP_NAME, str(exc), parent=self.window)

    @staticmethod
    def _optional_int(value: str, label: str, config: dict[str, Any], minimum: int = 0, maximum: int | None = None) -> int | None:
        stripped = value.strip()
        if stripped == "":
            return None
        try:
            number = int(stripped)
        except ValueError as exc:
            raise ValueError(translate(config, "invalid_int", label=label)) from exc
        if number < minimum or (maximum is not None and number > maximum):
            range_text = translate(config, "between", minimum=minimum, maximum=maximum) if maximum is not None else translate(config, "at_least", minimum=minimum)
            raise ValueError(translate(config, "invalid_range", label=label, range=range_text))
        return number

    def save_and_apply(self) -> None:
        self.save(apply_selected=True)

    def save(self, apply_selected: bool = False) -> None:
        try:
            selected_profile_id = self._selected_profile_id()
            config = deep_copy_json(self.app.config)
            config["schema_version"] = 8
            config["profiles"] = deep_copy_json(self.working_profiles)
            language_map = self.variables["language_map"]  # type: ignore[assignment]
            language_display = str(self.variables["language"].get())
            config["app"]["language"] = language_map.get(language_display, "de")
            app_config = config["app"]
            app_config["profile_order"] = list(self.profile_order)
            app_config.pop("toggle_profiles", None)
            hotkey = app_config["hotkey"]
            hotkey["key"] = str(self.variables["hotkey.key"].get()).upper()
            for key in ("ctrl", "alt", "shift", "win"):
                hotkey[key] = bool(self.variables[f"hotkey.{key}"].get())
            app_config["show_startup_popup"] = bool(self.variables["show_startup_popup"].get())
            app_config["apply_active_profile_on_start"] = bool(self.variables["apply_active_profile_on_start"].get())
            app_config["autostart"] = bool(self.variables["autostart"].get())

            mode_display = str(self.variables["dynamic_switch.mode"].get())
            dynamic_mode = self.dynamic_mode_map.get(mode_display, "disabled")
            idle_active_display = str(self.variables["dynamic_switch.idle.active_profile_id"].get())
            idle_idle_display = str(self.variables["dynamic_switch.idle.idle_profile_id"].get())
            load_low_display = str(self.variables["dynamic_switch.load.low_profile_id"].get())
            load_high_display = str(self.variables["dynamic_switch.load.high_profile_id"].get())
            idle_minutes = self._optional_int(str(self.variables["dynamic_switch.idle.idle_minutes"].get()), self.t("dynamic_idle_minutes"), config, minimum=1, maximum=1440)
            load_config: dict[str, Any] = {
                "low_profile_id": self.dynamic_profile_map.get(load_low_display, ""),
                "high_profile_id": self.dynamic_profile_map.get(load_high_display, ""),
                "gpu_enabled": bool(self.variables["dynamic_switch.load.gpu_enabled"].get()),
                "include_process_children": bool(self.variables["dynamic_switch.load.include_process_children"].get()),
                "rdp_session_trigger_enabled": bool(self.variables["dynamic_switch.load.rdp_session_trigger_enabled"].get()),
            }
            numeric_limits = {
                "cpu_high_percent": (0, 100),
                "cpu_low_percent": (0, 100),
                "process_high_percent": (0, 100),
                "process_low_percent": (0, 100),
                "gpu_high_percent": (0, 100),
                "gpu_low_percent": (0, 100),
                "high_delay_seconds": (0, 86400),
                "low_delay_seconds": (0, 86400),
                "minimum_hold_seconds": (0, 86400),
                "rdp_idle_minutes": (1, 1440),
            }
            for key, (minimum, maximum) in numeric_limits.items():
                parsed = self._optional_int(
                    str(self.variables[f"dynamic_switch.load.{key}"].get()),
                    key,
                    config,
                    minimum=minimum,
                    maximum=maximum,
                )
                if parsed is None:
                    raise ValueError(translate(config, "not_empty", label=key))
                load_config[key] = parsed
            for key, editor in self.dynamic_text_widgets.items():
                load_config[key] = [line.strip() for line in editor.get("1.0", "end").splitlines() if line.strip()]
            app_config["dynamic_switch"] = {
                "mode": dynamic_mode,
                "manual_override_until_transition": bool(self.variables["dynamic_switch.manual_override_until_transition"].get()),
                "idle": {
                    "active_profile_id": self.dynamic_profile_map.get(idle_active_display, ""),
                    "idle_profile_id": self.dynamic_profile_map.get(idle_idle_display, ""),
                    "idle_minutes": idle_minutes if idle_minutes is not None else 10,
                },
                "load": load_config,
            }

            app_config.setdefault("cpu_compatibility", {})["auto_apply_efficiency_class_1"] = bool(
                self.variables["cpu_compatibility.auto_apply_efficiency_class_1"].get()
            )

            for key in ("hold_ms", "fade_ms", "width", "height"):
                parsed = self._optional_int(
                    str(self.variables[f"popup.{key}"].get()),
                    key,
                    config,
                    minimum=100 if key in ("hold_ms", "fade_ms") else 40,
                    maximum=10000 if key in ("hold_ms", "fade_ms") else 2000,
                )
                if parsed is None:
                    raise ValueError(translate(config, "not_empty", label=key))
                app_config["popup"][key] = parsed

            boost_labels = self._boost_labels()
            cooling_labels = self._cooling_labels()
            parking_labels = self._parking_labels()
            for profile_id in self.profile_order:
                variables = self.profile_variables[profile_id]
                profile = config["profiles"][profile_id]
                profile["display_name"] = str(variables["display_name"].get()).strip() or profile_id
                profile["enabled"] = bool(variables["enabled"].get())
                selected_guid = self.plan_values.get(str(variables["plan_selection"].get()))
                if selected_guid:
                    profile.setdefault("plan", {})["guid"] = selected_guid
                settings = profile.setdefault("settings", {})
                for source in ("ac", "dc"):
                    for _, template in self.FIELD_ROWS:
                        key = template.format(source=source)
                        settings[key] = self._optional_int(
                            str(variables[key].get()),
                            key,
                            config,
                            minimum=0,
                            maximum=100 if "percent" in key else None,
                        )
                    boost_key = f"processor_boost_mode_{source}"
                    settings[boost_key] = boost_labels[str(variables[boost_key].get())]
                    cooling_key = f"cooling_policy_{source}"
                    settings[cooling_key] = cooling_labels[str(variables[cooling_key].get())]

                    parking_mode_key = f"core_parking_mode_{source}"
                    parking_mode = parking_labels[str(variables[parking_mode_key].get())]
                    parking_min_key = f"core_parking_min_{source}_percent"
                    parking_max_key = f"core_parking_max_{source}_percent"
                    if parking_mode == "unchanged":
                        settings[parking_min_key] = None
                        settings[parking_max_key] = None
                    elif parking_mode == "disabled":
                        settings[parking_min_key] = 100
                        settings[parking_max_key] = 100
                    else:
                        parking_min = self._optional_int(str(variables[parking_min_key].get()), parking_min_key, config, minimum=0, maximum=100)
                        parking_max = self._optional_int(str(variables[parking_max_key].get()), parking_max_key, config, minimum=0, maximum=100)
                        if parking_min is None or parking_max is None:
                            raise ValueError(translate(config, "not_empty", label=self.t("core_parking")))
                        if parking_min > parking_max:
                            raise ValueError(translate(config, "invalid_parking_range", profile=profile.get("display_name", profile_id), source=source.upper()))
                        settings[parking_min_key] = parking_min
                        settings[parking_max_key] = parking_max

                    epp_key = f"energy_preference_{source}_percent"
                    if bool(variables[f"energy_preference_enabled_{source}"].get()):
                        epp_value = self._optional_int(str(variables[epp_key].get()), epp_key, config, minimum=0, maximum=100)
                        if epp_value is None:
                            raise ValueError(translate(config, "not_empty", label=self.t("energy_preference")))
                        settings[epp_key] = epp_value
                    else:
                        settings[epp_key] = None

            validate_config(config)
            try:
                set_autostart_enabled(bool(app_config["autostart"]))
            except OSError as exc:
                raise RuntimeError(translate(config, "autostart_error", error=exc)) from exc
            write_json_atomic(CONFIG_PATH, config)
            self.app.reload_config(show_confirmation=False)

            if apply_selected:
                if selected_profile_id is None or selected_profile_id not in self.app.config["profiles"]:
                    raise ValueError(self.app.t("select_profile_tab"))
                self.app.apply_profile(selected_profile_id)
                messagebox.showinfo(APP_NAME, self.app.t("config_saved_applied"), parent=self.window)
            else:
                messagebox.showinfo(APP_NAME, self.app.t("config_saved"), parent=self.window)
            self.close()
        except Exception as exc:
            LOGGER.exception("Could not save config")
            messagebox.showerror(APP_NAME, str(exc), parent=self.window)

    def close(self) -> None:
        try:
            if self.window.winfo_exists():
                self.window.destroy()
        finally:
            self.app.config_editor = None


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def get_idle_seconds() -> float:
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    current_tick = ctypes.windll.kernel32.GetTickCount()
    elapsed_ms = (current_tick - info.dwTime) & 0xFFFFFFFF
    return elapsed_ms / 1000.0


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]



WTS_CURRENT_SERVER_HANDLE = wintypes.HANDLE(0)
WTS_ACTIVE = 0
WTS_CLIENT_PROTOCOL_TYPE = 16
WTS_SESSION_INFO_EX = 25
WTS_SESSIONSTATE_LOCK = 0
WINSTATIONNAME_LENGTH = 32
USERNAME_LENGTH = 20
DOMAIN_LENGTH = 17


class WTS_SESSION_INFOW(ctypes.Structure):
    _fields_ = [
        ("SessionId", wintypes.DWORD),
        ("pWinStationName", wintypes.LPWSTR),
        ("State", ctypes.c_int),
    ]


class WTSINFOEX_LEVEL1_W(ctypes.Structure):
    _fields_ = [
        ("SessionId", wintypes.ULONG),
        ("SessionState", ctypes.c_int),
        ("SessionFlags", wintypes.LONG),
        ("WinStationName", wintypes.WCHAR * (WINSTATIONNAME_LENGTH + 1)),
        ("UserName", wintypes.WCHAR * (USERNAME_LENGTH + 1)),
        ("DomainName", wintypes.WCHAR * (DOMAIN_LENGTH + 1)),
        ("LogonTime", ctypes.c_longlong),
        ("ConnectTime", ctypes.c_longlong),
        ("DisconnectTime", ctypes.c_longlong),
        ("LastInputTime", ctypes.c_longlong),
        ("CurrentTime", ctypes.c_longlong),
        ("IncomingBytes", wintypes.DWORD),
        ("OutgoingBytes", wintypes.DWORD),
        ("IncomingFrames", wintypes.DWORD),
        ("OutgoingFrames", wintypes.DWORD),
        ("IncomingCompressedBytes", wintypes.DWORD),
        ("OutgoingCompressedBytes", wintypes.DWORD),
    ]


class WTSINFOEX_DATA(ctypes.Union):
    _fields_ = [("WTSInfoExLevel1", WTSINFOEX_LEVEL1_W)]


class WTSINFOEXW(ctypes.Structure):
    _anonymous_ = ("Data",)
    _fields_ = [("Level", wintypes.DWORD), ("Data", WTSINFOEX_DATA)]


def _query_wts_value(session_id: int, info_class: int, value_type: Any) -> Any | None:
    try:
        wtsapi32 = ctypes.WinDLL("Wtsapi32.dll", use_last_error=True)
        wtsapi32.WTSQuerySessionInformationW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.DWORD),
        ]
        wtsapi32.WTSQuerySessionInformationW.restype = wintypes.BOOL
        wtsapi32.WTSFreeMemory.argtypes = [ctypes.c_void_p]
        buffer = ctypes.c_void_p()
        size = wintypes.DWORD()
        if not wtsapi32.WTSQuerySessionInformationW(
            WTS_CURRENT_SERVER_HANDLE,
            int(session_id),
            int(info_class),
            ctypes.byref(buffer),
            ctypes.byref(size),
        ):
            return None
        try:
            if int(size.value) < ctypes.sizeof(value_type):
                return None
            data = ctypes.string_at(buffer, int(size.value))
            return value_type.from_buffer_copy(data)
        finally:
            wtsapi32.WTSFreeMemory(buffer)
    except Exception:
        LOGGER.debug("WTS query failed for session %s class %s", session_id, info_class, exc_info=True)
        return None


def get_current_process_session_id() -> int | None:
    try:
        session_id = wintypes.DWORD()
        kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
        kernel32.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        kernel32.ProcessIdToSessionId.restype = wintypes.BOOL
        if kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session_id)):
            return int(session_id.value)
    except Exception:
        LOGGER.debug("Could not determine current Windows session", exc_info=True)
    return None


def list_active_rdp_sessions(max_idle_seconds: float) -> list[dict[str, Any]]:
    """Return connected, unlocked and recently used RDP sessions."""
    try:
        wtsapi32 = ctypes.WinDLL("Wtsapi32.dll", use_last_error=True)
        wtsapi32.WTSEnumerateSessionsW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(WTS_SESSION_INFOW)),
            ctypes.POINTER(wintypes.DWORD),
        ]
        wtsapi32.WTSEnumerateSessionsW.restype = wintypes.BOOL
        wtsapi32.WTSFreeMemory.argtypes = [ctypes.c_void_p]
        sessions_ptr = ctypes.POINTER(WTS_SESSION_INFOW)()
        count = wintypes.DWORD()
        if not wtsapi32.WTSEnumerateSessionsW(
            WTS_CURRENT_SERVER_HANDLE, 0, 1, ctypes.byref(sessions_ptr), ctypes.byref(count)
        ):
            return []
        active: list[dict[str, Any]] = []
        current_session_id = get_current_process_session_id()
        try:
            for index in range(int(count.value)):
                session = sessions_ptr[index]
                if int(session.State) != WTS_ACTIVE:
                    continue
                protocol = _query_wts_value(int(session.SessionId), WTS_CLIENT_PROTOCOL_TYPE, wintypes.USHORT)
                if protocol is None or int(protocol.value) != 2:
                    continue
                info = _query_wts_value(int(session.SessionId), WTS_SESSION_INFO_EX, WTSINFOEXW)
                idle_seconds: float | None = None
                unlocked = True
                user_name = ""
                if info is not None and int(info.Level) == 1:
                    level = info.WTSInfoExLevel1
                    user_name = str(level.UserName).strip()
                    if int(level.SessionFlags) == WTS_SESSIONSTATE_LOCK:
                        unlocked = False
                    if int(level.CurrentTime) > 0 and int(level.LastInputTime) > 0:
                        idle_seconds = max(
                            0.0,
                            (int(level.CurrentTime) - int(level.LastInputTime)) / 10_000_000.0,
                        )
                elif current_session_id == int(session.SessionId):
                    try:
                        idle_seconds = get_idle_seconds()
                    except Exception:
                        idle_seconds = None
                else:
                    # Without session details we cannot reliably distinguish an
                    # active user from a stale or locked session.
                    continue
                if not unlocked:
                    continue
                if idle_seconds is None or idle_seconds > max_idle_seconds:
                    continue
                active.append({
                    "session_id": int(session.SessionId),
                    "station": str(session.pWinStationName or ""),
                    "user": user_name,
                    "idle_seconds": idle_seconds,
                })
        finally:
            wtsapi32.WTSFreeMemory(ctypes.cast(sessions_ptr, ctypes.c_void_p))
        return active
    except Exception:
        LOGGER.debug("Could not enumerate Remote Desktop sessions", exc_info=True)
        return []


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def filetime_value(value: FILETIME) -> int:
    return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)


def get_system_times_snapshot() -> tuple[int, int, int]:
    kernel32 = ctypes.windll.kernel32
    kernel32.GetSystemTimes.argtypes = [ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME)]
    kernel32.GetSystemTimes.restype = wintypes.BOOL
    idle = FILETIME()
    kernel = FILETIME()
    user = FILETIME()
    if not kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        raise ctypes.WinError(ctypes.get_last_error())
    return filetime_value(idle), filetime_value(kernel), filetime_value(user)


def list_process_snapshot() -> list[dict[str, Any]]:
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    records: list[dict[str, Any]] = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        success = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while success:
            records.append({
                "pid": int(entry.th32ProcessID),
                "ppid": int(entry.th32ParentProcessID),
                "name": str(entry.szExeFile),
            })
            success = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return records


def get_process_image_path(pid: int) -> str:
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return buffer.value
    finally:
        kernel32.CloseHandle(handle)


def is_windows_system_process(process: dict[str, Any]) -> bool:
    pid = int(process.get("pid", 0))
    name = str(process.get("name", "")).strip().lower()
    path = str(process.get("path", "")).strip()
    if pid <= 4 or pid == os.getpid() or name in KNOWN_WINDOWS_PROCESS_NAMES:
        return True
    if path:
        windows_root = os.path.normcase(os.path.abspath(os.environ.get("SystemRoot", r"C:\Windows"))).rstrip("\\/")
        process_path = os.path.normcase(os.path.abspath(path))
        if process_path == windows_root or process_path.startswith(windows_root + os.sep):
            return True
    return False


def list_processes_for_picker() -> list[dict[str, Any]]:
    records = list_process_snapshot()
    result: list[dict[str, Any]] = []
    for record in records:
        pid = int(record.get("pid", 0))
        item = dict(record)
        item["path"] = get_process_image_path(pid)
        item["is_windows"] = is_windows_system_process(item)
        result.append(item)
    result.sort(key=lambda item: (str(item.get("name", "")).lower(), int(item.get("pid", 0))))
    return result


def get_process_cpu_time(pid: int) -> int | None:
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(FILETIME),
        ctypes.POINTER(FILETIME),
        ctypes.POINTER(FILETIME),
        ctypes.POINTER(FILETIME),
    ]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return None
    try:
        creation = FILETIME()
        exit_time = FILETIME()
        kernel = FILETIME()
        user = FILETIME()
        if not kernel32.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        return filetime_value(kernel) + filetime_value(user)
    finally:
        kernel32.CloseHandle(handle)


def process_name_matches(name: str, patterns: list[str]) -> bool:
    lowered = name.lower()
    return any(fnmatch.fnmatchcase(lowered, str(pattern).strip().lower()) for pattern in patterns if str(pattern).strip())


class NvmlMonitor:
    class Utilization(ctypes.Structure):
        _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

    def __init__(self) -> None:
        self.library: Any = None
        self.handles: list[ctypes.c_void_p] = []
        self.available = False
        self._attempted = False

    @staticmethod
    def _function(library: Any, *names: str) -> Any:
        for name in names:
            function = getattr(library, name, None)
            if function is not None:
                return function
        raise AttributeError(names[0])

    def initialize(self) -> bool:
        if self._attempted:
            return self.available
        self._attempted = True
        try:
            library = ctypes.WinDLL("nvml.dll")
            init = self._function(library, "nvmlInit_v2", "nvmlInit")
            init.restype = ctypes.c_int
            if init() != 0:
                return False
            get_count = self._function(library, "nvmlDeviceGetCount_v2", "nvmlDeviceGetCount")
            get_count.argtypes = [ctypes.POINTER(ctypes.c_uint)]
            count = ctypes.c_uint()
            if get_count(ctypes.byref(count)) != 0:
                return False
            get_handle = self._function(library, "nvmlDeviceGetHandleByIndex_v2", "nvmlDeviceGetHandleByIndex")
            get_handle.argtypes = [ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)]
            handles: list[ctypes.c_void_p] = []
            for index in range(int(count.value)):
                handle = ctypes.c_void_p()
                if get_handle(index, ctypes.byref(handle)) == 0:
                    handles.append(handle)
            self.library = library
            self.handles = handles
            self.available = bool(handles)
            LOGGER.info("NVML monitoring available for %s NVIDIA GPU(s)", len(handles))
        except Exception:
            LOGGER.info("NVML monitoring is not available", exc_info=True)
            self.available = False
        return self.available

    def sample(self) -> dict[str, float] | None:
        if not self.initialize() or self.library is None:
            return None
        maximum = {"gpu": 0.0, "encoder": 0.0, "decoder": 0.0}
        try:
            get_utilization = self._function(self.library, "nvmlDeviceGetUtilizationRates")
            get_utilization.argtypes = [ctypes.c_void_p, ctypes.POINTER(self.Utilization)]
            encoder_function = getattr(self.library, "nvmlDeviceGetEncoderUtilization", None)
            decoder_function = getattr(self.library, "nvmlDeviceGetDecoderUtilization", None)
            for function in (encoder_function, decoder_function):
                if function is not None:
                    function.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)]
                    function.restype = ctypes.c_int
            for handle in self.handles:
                utilization = self.Utilization()
                if get_utilization(handle, ctypes.byref(utilization)) == 0:
                    maximum["gpu"] = max(maximum["gpu"], float(utilization.gpu))
                for key, function in (("encoder", encoder_function), ("decoder", decoder_function)):
                    if function is None:
                        continue
                    value = ctypes.c_uint()
                    sampling_period = ctypes.c_uint()
                    if function(handle, ctypes.byref(value), ctypes.byref(sampling_period)) == 0:
                        maximum[key] = max(maximum[key], float(value.value))
            return maximum
        except Exception:
            LOGGER.exception("NVML sampling failed")
            return None

    def shutdown(self) -> None:
        if self.library is not None:
            try:
                shutdown = getattr(self.library, "nvmlShutdown", None)
                if shutdown is not None:
                    shutdown()
            except Exception:
                LOGGER.exception("NVML shutdown failed")
        self.library = None
        self.handles = []
        self.available = False


class SystemLoadMonitor:
    def __init__(self) -> None:
        self.previous_system: tuple[int, int, int] | None = None
        self.previous_process_times: dict[int, int] = {}
        self.nvml = NvmlMonitor()

    def reset(self) -> None:
        self.previous_system = None
        self.previous_process_times.clear()

    @staticmethod
    def _descendants(root_pids: set[int], children: dict[int, list[int]]) -> set[int]:
        result: set[int] = set()
        pending = list(root_pids)
        while pending:
            parent = pending.pop()
            for child in children.get(parent, []):
                if child not in result:
                    result.add(child)
                    pending.append(child)
        return result

    def sample(self, config: dict[str, Any]) -> dict[str, Any]:
        current_system = get_system_times_snapshot()
        processes = list_process_snapshot()
        children: dict[int, list[int]] = {}
        by_pid: dict[int, dict[str, Any]] = {}
        for process in processes:
            pid = int(process["pid"])
            by_pid[pid] = process
            children.setdefault(int(process["ppid"]), []).append(pid)

        always_patterns = [str(item) for item in config.get("always_process_patterns", [])]
        load_patterns = [str(item) for item in config.get("load_process_patterns", [])]
        launcher_patterns = [str(item) for item in config.get("launcher_process_patterns", [])]
        container_patterns = [str(item) for item in config.get("container_process_patterns", [])]
        include_children = bool(config.get("include_process_children", True))

        always_pids = {pid for pid, process in by_pid.items() if process_name_matches(str(process["name"]), always_patterns)}
        load_pids = {pid for pid, process in by_pid.items() if process_name_matches(str(process["name"]), load_patterns)}
        launcher_pids = {pid for pid, process in by_pid.items() if process_name_matches(str(process["name"]), launcher_patterns)}
        container_pids = {pid for pid, process in by_pid.items() if process_name_matches(str(process["name"]), container_patterns)}

        if include_children:
            load_pids |= self._descendants(load_pids, children)
            container_pids |= self._descendants(container_pids, children)
        launcher_child_pids = self._descendants(launcher_pids, children)
        monitored_pids = load_pids | launcher_child_pids | container_pids

        current_process_times: dict[int, int] = {}
        for pid in monitored_pids:
            value = get_process_cpu_time(pid)
            if value is not None:
                current_process_times[pid] = value

        overall_cpu = 0.0
        process_cpu = 0.0
        if self.previous_system is not None:
            previous_idle, previous_kernel, previous_user = self.previous_system
            idle, kernel, user = current_system
            total_delta = max(0, (kernel - previous_kernel) + (user - previous_user))
            idle_delta = max(0, idle - previous_idle)
            if total_delta > 0:
                overall_cpu = max(0.0, min(100.0, 100.0 * (total_delta - idle_delta) / total_delta))
                process_delta = 0
                for pid, value in current_process_times.items():
                    previous = self.previous_process_times.get(pid)
                    if previous is not None and value >= previous:
                        process_delta += value - previous
                process_cpu = max(0.0, min(100.0, 100.0 * process_delta / total_delta))

        self.previous_system = current_system
        self.previous_process_times = current_process_times
        gpu = self.nvml.sample() if bool(config.get("gpu_enabled", True)) else None
        matched_names = sorted({str(by_pid[pid]["name"]) for pid in monitored_pids if pid in by_pid})

        rdp_sessions: list[dict[str, Any]] = []
        if bool(config.get("rdp_session_trigger_enabled", True)):
            idle_minutes = max(1, int(config.get("rdp_idle_minutes", 5)))
            rdp_sessions = list_active_rdp_sessions(float(idle_minutes * 60))

        always_names = sorted({str(by_pid[pid]["name"]) for pid in always_pids if pid in by_pid})
        for session in rdp_sessions:
            user = str(session.get("user", "")).strip()
            always_names.append(f"Remote Desktop ({user})" if user else "Remote Desktop")
        return {
            "cpu": overall_cpu,
            "process_cpu": process_cpu,
            "always_active": bool(always_pids or rdp_sessions),
            "always_names": always_names,
            "rdp_active": bool(rdp_sessions),
            "rdp_sessions": rdp_sessions,
            "matched_names": matched_names,
            "gpu": gpu,
        }


class PowerPlanSwitcherApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(APP_NAME)
        self.root.protocol("WM_DELETE_WINDOW", self.exit_app)
        self.action_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.config: dict[str, Any] = deep_copy_json(DEFAULT_CONFIG)
        self.config_editor: ConfigEditor | None = None
        self.hotkey_thread: HotkeyThread | None = None
        self.tray_icon: pystray.Icon | None = None
        self.popup: tk.Toplevel | None = None
        self.popup_after_ids: list[str] = []
        self.is_switching = False
        self.last_applied_profile_id: str | None = None
        self.dynamic_state: str | None = None
        self.dynamic_candidate_state: str | None = None
        self.dynamic_candidate_since: float | None = None
        self.dynamic_last_transition: float = 0.0
        self.manual_override_pending: bool = False
        self.dynamic_after_id: str | None = None
        self.load_monitor = SystemLoadMonitor()
        self.cpu_info = detect_cpu_info()
        self.mutex_handle = create_mutex_or_exit(self.config)

        self.reload_config(show_confirmation=False, initial=True)
        self._start_tray_icon()
        self._start_hotkey()
        self.root.after(ACTION_QUEUE_POLL_MS, self._process_action_queue)
        self._schedule_dynamic_check(750)
        if self.config["app"].get("apply_active_profile_on_start"):
            self._apply_active_profile_settings_only()
        if self.config["app"].get("show_startup_popup", True):
            self.root.after(250, self._show_ready_popup)

    @property
    def language(self) -> str:
        return language_from_config(self.config)

    def t(self, key: str, **values: Any) -> str:
        return translate(self.config, key, **values)

    def cpu_capability_text(self) -> str:
        try:
            capabilities = processor_capability_summary(get_active_plan_guid())
            features: list[str] = []
            if capabilities["cpu_range"]:
                features.append(self.t("feature_cpu_range"))
            if capabilities["boost"]:
                features.append(self.t("feature_boost"))
            if capabilities["cooling"]:
                features.append(self.t("feature_cooling"))
            if capabilities["parking"]:
                features.append(self.t("feature_parking"))
            if capabilities["epp"]:
                features.append(self.t("feature_epp"))
            if capabilities["class1"]:
                features.append(self.t("feature_class1"))
            if not capabilities["query_ok"] or not features:
                return self.t("cpu_features_unknown")
            return self.t("cpu_features", features=", ".join(features))
        except Exception:
            LOGGER.exception("Could not build CPU capability summary")
            return self.t("cpu_features_unknown")

    def _show_ready_popup(self) -> None:
        hotkey_name = HotkeyThread.display_name(self.config["app"]["hotkey"], self.language)
        self.show_popup(self.t("ready", hotkey=hotkey_name, version=APP_VERSION))

    def safe_list_power_plans(self, show_error: bool = False) -> list[dict[str, Any]]:
        try:
            return list_power_plans()
        except Exception as exc:
            LOGGER.exception("Could not list power plans")
            if show_error:
                self.show_popup(self.t("error", error=exc), error=True)
            return []

    def _detect_active_profile_id(self) -> str | None:
        try:
            active_guid = get_active_plan_guid()
            plans = list_power_plans()
            candidates = ordered_profile_ids(self.config, enabled_only=False)
            if self.last_applied_profile_id in candidates:
                candidates.remove(self.last_applied_profile_id)
                candidates.insert(0, self.last_applied_profile_id)
            for profile_id in candidates:
                profile = self.config.get("profiles", {}).get(profile_id)
                if not isinstance(profile, dict):
                    continue
                try:
                    if resolve_plan_guid(profile, plans, self.config) == active_guid:
                        return profile_id
                except Exception:
                    continue
        except Exception:
            LOGGER.debug("Could not detect active profile for tray", exc_info=True)
        return self.last_applied_profile_id if self.last_applied_profile_id in self.config.get("profiles", {}) else None

    def _active_profile_name(self) -> str:
        profile_id = self._detect_active_profile_id()
        if profile_id is None:
            return self.t("active_profile_unknown")
        profile = self.config.get("profiles", {}).get(profile_id, {})
        return str(profile.get("display_name", profile_id))

    def _tray_title(self) -> str:
        text = f"{APP_NAME} - {self.t('active_profile_tray', name=self._active_profile_name())}"
        return text[:127]

    def _update_tray_status(self, rebuild_menu: bool = True) -> None:
        if self.tray_icon is None:
            return
        try:
            self.tray_icon.title = self._tray_title()
            if rebuild_menu:
                self.tray_icon.menu = self._create_tray_menu()
                self.tray_icon.update_menu()
        except Exception:
            LOGGER.debug("Could not update tray status", exc_info=True)

    def _start_tray_icon(self) -> None:
        self.tray_icon = pystray.Icon(APP_NAME, self._load_icon_image(), self._tray_title(), self._create_tray_menu())
        threading.Thread(target=self.tray_icon.run, name="TrayIcon", daemon=True).start()

    def _profile_menu_action(self, profile_id: str) -> Callable[[Any, Any], None]:
        def action(icon: Any, item: Any) -> None:
            del icon, item
            self.action_queue.put(("apply_profile", profile_id))
        return action

    def _tray_toggle(self, icon: Any, item: Any) -> None:
        del icon, item
        self.action_queue.put(("toggle", None))

    def _tray_edit_config(self, icon: Any, item: Any) -> None:
        del icon, item
        self.action_queue.put(("edit_config", None))

    def _tray_reload_config(self, icon: Any, item: Any) -> None:
        del icon, item
        self.action_queue.put(("reload_config", True))

    def _tray_open_folder(self, icon: Any, item: Any) -> None:
        del icon, item
        self.action_queue.put(("open_folder", None))

    def _tray_exit(self, icon: Any, item: Any) -> None:
        del icon, item
        self.action_queue.put(("exit", None))

    @staticmethod
    def _tray_noop(icon: Any, item: Any) -> None:
        del icon, item

    def _create_tray_menu(self) -> pystray.Menu:
        profile_items = []
        for profile_id in ordered_profile_ids(self.config, enabled_only=True):
            display_name = self.config["profiles"][profile_id].get("display_name", profile_id)
            profile_items.append(pystray.MenuItem(self.t("apply_profile", name=display_name), self._profile_menu_action(profile_id)))
        hotkey_name = HotkeyThread.display_name(self.config["app"]["hotkey"], self.language)
        return pystray.Menu(
            pystray.MenuItem(
                self.t("active_profile_tray", name=self._active_profile_name()),
                self._tray_noop,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(self.t("toggle", hotkey=hotkey_name), self._tray_toggle, default=True),
            *profile_items,
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(self.t("edit_config"), self._tray_edit_config),
            pystray.MenuItem(self.t("reload_config"), self._tray_reload_config),
            pystray.MenuItem(self.t("open_folder"), self._tray_open_folder),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(self.t("version", version=APP_VERSION), self._tray_noop, enabled=False),
            pystray.MenuItem(self.t("exit"), self._tray_exit),
        )

    @staticmethod
    def _load_icon_image() -> Image.Image:
        for name in ("logo.ico", "logo.png"):
            path = APP_DIR / name
            if path.exists():
                try:
                    return Image.open(path).convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)
                except Exception:
                    LOGGER.exception("Could not load icon %s", path)
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((4, 4, 60, 60), radius=14, fill=(36, 99, 235, 255))
        draw.line((21, 32, 31, 42, 45, 20), fill=(255, 255, 255, 255), width=6)
        return image

    def _start_hotkey(self) -> None:
        self._stop_hotkey()
        self.hotkey_thread = HotkeyThread(self.config["app"]["hotkey"], self.language, self.action_queue)
        self.hotkey_thread.start()

    def _stop_hotkey(self) -> None:
        if self.hotkey_thread is not None:
            self.hotkey_thread.stop()
            self.hotkey_thread.join(timeout=1.0)
            self.hotkey_thread = None

    def _process_action_queue(self) -> None:
        try:
            while True:
                action, payload = self.action_queue.get_nowait()
                try:
                    if action == "toggle":
                        self.toggle_profile()
                    elif action == "apply_profile":
                        self.apply_profile(str(payload))
                    elif action == "edit_config":
                        self.open_config_editor()
                    elif action == "reload_config":
                        self.reload_config(show_confirmation=bool(payload))
                    elif action == "open_folder":
                        os.startfile(APP_DIR)  # type: ignore[attr-defined]
                    elif action == "exit":
                        self.exit_app()
                        return
                    elif action == "hotkey_error":
                        self.show_popup(str(payload), error=True)
                        LOGGER.error("Hotkey registration failed: %s", payload)
                    elif action == "hotkey_ready":
                        LOGGER.info("Hotkey registered: %s", payload)
                except Exception as exc:
                    LOGGER.exception("Action failed: %s", action)
                    self.show_popup(self.t("action_error", action=action, error=exc), error=True)
        except queue.Empty:
            pass
        try:
            if self.root.winfo_exists():
                self.root.after(ACTION_QUEUE_POLL_MS, self._process_action_queue)
        except tk.TclError:
            pass

    def _cancel_dynamic_check(self) -> None:
        if self.dynamic_after_id is None:
            return
        try:
            self.root.after_cancel(self.dynamic_after_id)
        except tk.TclError:
            pass
        self.dynamic_after_id = None

    def _dynamic_mode(self) -> str:
        dynamic = self.config.get("app", {}).get("dynamic_switch", {})
        return str(dynamic.get("mode", "disabled")).lower()

    def _reset_dynamic_state(self) -> None:
        self.dynamic_state = None
        self.dynamic_candidate_state = None
        self.dynamic_candidate_since = None
        self.dynamic_last_transition = 0.0
        self.manual_override_pending = False
        self.load_monitor.reset()

    def _schedule_dynamic_check(self, delay_ms: int = DYNAMIC_ACTIVE_POLL_MS) -> None:
        self._cancel_dynamic_check()
        if self._dynamic_mode() == "disabled":
            self._reset_dynamic_state()
            return
        try:
            if self.root.winfo_exists():
                self.dynamic_after_id = self.root.after(max(250, int(delay_ms)), self._check_dynamic_switch)
        except tk.TclError:
            self.dynamic_after_id = None

    def _apply_dynamic_state(self, state: str, profile_id: str) -> bool:
        if profile_id not in self.config.get("profiles", {}):
            LOGGER.error("Automatic profile does not exist: %s", profile_id)
            return False
        if self.apply_profile(profile_id, automatic=True):
            self.dynamic_state = state
            self.dynamic_candidate_state = None
            self.dynamic_candidate_since = None
            self.dynamic_last_transition = time.monotonic()
            return True
        return False

    def _check_idle_dynamic(self, dynamic: dict[str, Any]) -> int:
        idle_config = dynamic.get("idle", {})
        idle_seconds = get_idle_seconds()
        threshold_seconds = max(60, int(idle_config.get("idle_minutes", 10)) * 60)
        target_state = "idle" if idle_seconds >= threshold_seconds else "active"
        profile_key = "idle_profile_id" if target_state == "idle" else "active_profile_id"
        profile_id = str(idle_config.get(profile_key, ""))
        preserve_manual = bool(dynamic.get("manual_override_until_transition", True))
        if preserve_manual and self.manual_override_pending:
            if self.dynamic_state is None:
                self.dynamic_state = target_state
                self.manual_override_pending = False
                return DYNAMIC_IDLE_POLL_MS if target_state == "idle" else DYNAMIC_ACTIVE_POLL_MS
            self.manual_override_pending = False
        should_apply = target_state != self.dynamic_state
        if not preserve_manual and self.last_applied_profile_id != profile_id:
            should_apply = True
        if should_apply and not self.is_switching:
            self._apply_dynamic_state(target_state, profile_id)
        return DYNAMIC_IDLE_POLL_MS if self.dynamic_state == "idle" else DYNAMIC_ACTIVE_POLL_MS

    def _check_load_dynamic(self, dynamic: dict[str, Any]) -> int:
        load_config = dynamic.get("load", {})
        metrics = self.load_monitor.sample(load_config)
        gpu_data = metrics.get("gpu") or {}
        gpu_value = max(float(gpu_data.get("gpu", 0.0)), float(gpu_data.get("encoder", 0.0)), float(gpu_data.get("decoder", 0.0)))
        gpu_enabled = bool(load_config.get("gpu_enabled", True)) and metrics.get("gpu") is not None

        immediate_active = bool(metrics.get("always_active"))
        if immediate_active:
            high_profile_id = str(load_config.get("high_profile_id", ""))
            self.manual_override_pending = False
            self.dynamic_candidate_state = None
            self.dynamic_candidate_since = None
            if not self.is_switching and (
                self.dynamic_state != "high" or self.last_applied_profile_id != high_profile_id
            ):
                LOGGER.info(
                    "Immediate process trigger: %s",
                    ", ".join(metrics.get("always_names", [])),
                )
                self._apply_dynamic_state("high", high_profile_id)
            else:
                self.dynamic_state = "high"
            return SYSTEM_LOAD_POLL_MS

        high_signal = (
            float(metrics.get("cpu", 0.0)) >= float(load_config.get("cpu_high_percent", 35))
            or float(metrics.get("process_cpu", 0.0)) >= float(load_config.get("process_high_percent", 3))
            or (gpu_enabled and gpu_value >= float(load_config.get("gpu_high_percent", 25)))
        )
        low_signal = (
            float(metrics.get("cpu", 0.0)) <= float(load_config.get("cpu_low_percent", 15))
            and float(metrics.get("process_cpu", 0.0)) <= float(load_config.get("process_low_percent", 1))
            and (not gpu_enabled or gpu_value <= float(load_config.get("gpu_low_percent", 10)))
        )

        desired_state: str | None = "high" if high_signal else ("low" if low_signal else None)
        now = time.monotonic()
        preserve_manual = bool(dynamic.get("manual_override_until_transition", True))
        if preserve_manual and self.manual_override_pending and desired_state is not None:
            if self.dynamic_state is None:
                self.dynamic_state = desired_state
                self.dynamic_candidate_state = None
                self.dynamic_candidate_since = None
                self.manual_override_pending = False
                return SYSTEM_LOAD_POLL_MS
            self.manual_override_pending = False
        if desired_state is None:
            self.dynamic_candidate_state = None
            self.dynamic_candidate_since = None
            return SYSTEM_LOAD_POLL_MS
        if desired_state == self.dynamic_state:
            self.dynamic_candidate_state = None
            self.dynamic_candidate_since = None
            if not preserve_manual and not self.is_switching:
                profile_key = "high_profile_id" if desired_state == "high" else "low_profile_id"
                profile_id = str(load_config.get(profile_key, ""))
                if self.last_applied_profile_id != profile_id:
                    self._apply_dynamic_state(desired_state, profile_id)
            return SYSTEM_LOAD_POLL_MS

        if self.dynamic_candidate_state != desired_state:
            self.dynamic_candidate_state = desired_state
            self.dynamic_candidate_since = now
            LOGGER.debug(
                "Automatic load candidate=%s cpu=%.1f monitored=%.1f gpu=%.1f processes=%s",
                desired_state,
                float(metrics.get("cpu", 0.0)),
                float(metrics.get("process_cpu", 0.0)),
                gpu_value,
                ", ".join(metrics.get("matched_names", [])),
            )
            return SYSTEM_LOAD_POLL_MS

        required_delay = float(load_config.get("high_delay_seconds", 15) if desired_state == "high" else load_config.get("low_delay_seconds", 120))
        candidate_age = now - (self.dynamic_candidate_since or now)
        minimum_hold = float(load_config.get("minimum_hold_seconds", 30))
        hold_ok = self.dynamic_last_transition <= 0 or (now - self.dynamic_last_transition) >= minimum_hold
        if candidate_age >= required_delay and hold_ok and not self.is_switching:
            profile_key = "high_profile_id" if desired_state == "high" else "low_profile_id"
            self._apply_dynamic_state(desired_state, str(load_config.get(profile_key, "")))
        return SYSTEM_LOAD_POLL_MS

    def _check_dynamic_switch(self) -> None:
        self.dynamic_after_id = None
        next_delay = DYNAMIC_ACTIVE_POLL_MS
        try:
            dynamic = self.config.get("app", {}).get("dynamic_switch", {})
            mode = self._dynamic_mode()
            if mode == "disabled":
                self._reset_dynamic_state()
                return
            if mode == "idle":
                next_delay = self._check_idle_dynamic(dynamic)
            elif mode == "load":
                next_delay = self._check_load_dynamic(dynamic)
        except Exception:
            LOGGER.exception("Automatic profile switching failed")
        finally:
            if self._dynamic_mode() != "disabled":
                self._schedule_dynamic_check(next_delay)

    def reload_config(self, show_confirmation: bool = True, initial: bool = False) -> None:
        try:
            self.config = load_or_create_config()
            validate_config(self.config)
            self.config["app"]["autostart"] = is_autostart_enabled()
            self._reset_dynamic_state()
            self._cancel_dynamic_check()
            if self.config["app"]["autostart"]:
                try:
                    # Refresh the command after an EXE rename or application move.
                    set_autostart_enabled(True)
                except OSError:
                    LOGGER.exception("Could not refresh autostart command")
            if not initial:
                self._start_hotkey()
                if self.tray_icon is not None:
                    self._update_tray_status(rebuild_menu=True)
                self._schedule_dynamic_check(250)
            if show_confirmation:
                self.show_popup(self.t("config_reloaded"))
        except ValueError as exc:
            self.config = deep_copy_json(DEFAULT_CONFIG)
            self.root.after(100, lambda: messagebox.showwarning(APP_NAME, str(exc)))
        except Exception as exc:
            LOGGER.exception("Could not reload config")
            self.root.after(100, lambda: messagebox.showerror(APP_NAME, str(exc)))

    def open_config_editor(self) -> None:
        try:
            if self.config_editor is not None and self.config_editor.window.winfo_exists():
                self.config_editor.window.deiconify()
                self.config_editor.window.lift()
                self.config_editor.window.focus_force()
                return
            self.config_editor = ConfigEditor(self)
            LOGGER.info("Config editor opened")
        except Exception:
            self.config_editor = None
            LOGGER.exception("Could not open config editor")
            raise

    def toggle_profile(self) -> None:
        if self.is_switching:
            return
        try:
            enabled_ids = ordered_profile_ids(self.config, enabled_only=True)
            if not enabled_ids:
                raise ValueError(self.t("at_least_one_enabled"))

            plans = list_power_plans()
            active_guid = get_active_plan_guid()
            available: list[tuple[str, str]] = []
            for profile_id in enabled_ids:
                try:
                    guid = resolve_plan_guid(self.config["profiles"][profile_id], plans, self.config)
                    available.append((profile_id, guid))
                except Exception as exc:
                    LOGGER.warning("Skipping unavailable profile %s: %s", profile_id, exc)

            if not available:
                raise RuntimeError(self.t("no_plans"))

            current_index = -1
            if self.last_applied_profile_id is not None:
                for index, (profile_id, guid) in enumerate(available):
                    if profile_id == self.last_applied_profile_id and guid == active_guid:
                        current_index = index
                        break
            if current_index < 0:
                for index, (_profile_id, guid) in enumerate(available):
                    if guid == active_guid:
                        current_index = index
                        break

            target_id = available[(current_index + 1) % len(available)][0]
            self.apply_profile(target_id)
        except Exception as exc:
            LOGGER.exception("Could not toggle profile")
            self.show_popup(self.t("error", error=exc), error=True)

    def apply_profile(self, profile_id: str, automatic: bool = False) -> bool:
        if self.is_switching:
            return False
        self.is_switching = True
        try:
            profile = self.config["profiles"][profile_id]
            plans = list_power_plans()
            plan_guid = resolve_plan_guid(profile, plans, self.config)
            warnings = apply_profile_settings(plan_guid, profile.get("settings", {}), self.config)
            run_powercfg(["/setactive", plan_guid])
            display_name = profile.get("display_name", profile_id)
            if warnings:
                self.show_popup(self.t("profile_warning", name=display_name, count=len(warnings)), error=True)
            else:
                self.show_popup(self.t("profile_active", name=display_name))
            self.last_applied_profile_id = profile_id
            self._update_tray_status(rebuild_menu=True)
            dynamic = self.config.get("app", {}).get("dynamic_switch", {})
            if (
                not automatic
                and str(dynamic.get("mode", "disabled")).lower() != "disabled"
                and bool(dynamic.get("manual_override_until_transition", True))
            ):
                self.manual_override_pending = True
            LOGGER.info("Applied profile %s to plan %s", profile_id, plan_guid)
            return True
        except Exception as exc:
            LOGGER.exception("Could not apply profile %s", profile_id)
            self.show_popup(self.t("error", error=exc), error=True)
            return False
        finally:
            self.is_switching = False

    def _apply_active_profile_settings_only(self) -> None:
        try:
            active_guid = get_active_plan_guid()
            plans = list_power_plans()
            for profile_id in ordered_profile_ids(self.config, enabled_only=True):
                profile = self.config["profiles"][profile_id]
                if resolve_plan_guid(profile, plans, self.config) == active_guid:
                    apply_profile_settings(active_guid, profile.get("settings", {}), self.config)
                    return
        except Exception:
            LOGGER.exception("Could not reapply active profile settings")

    def show_popup(self, text: str, error: bool = False) -> None:
        self.close_popup()
        popup_config = self.config.get("app", {}).get("popup", {})
        width = int(popup_config.get("width", 390))
        height = int(popup_config.get("height", 78))
        hold_ms = int(popup_config.get("hold_ms", 900))
        fade_ms = max(100, int(popup_config.get("fade_ms", 900)))
        popup = tk.Toplevel(self.root)
        self.popup = popup
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.attributes("-alpha", 0.96)
        background = "#8b1e1e" if error else "#202124"
        popup.configure(bg=background)
        tk.Label(
            popup,
            text=text,
            bg=background,
            fg="white",
            font=("Segoe UI", 11, "bold"),
            padx=16,
            pady=12,
            wraplength=width - 30,
            justify="center",
        ).pack(fill="both", expand=True)
        x, y = self._popup_position(width, height)
        popup.geometry(f"{width}x{height}+{x}+{y}")
        popup.update_idletasks()
        steps = 25
        interval = max(10, fade_ms // steps)

        def fade(step: int = 0) -> None:
            if self.popup is None or not self.popup.winfo_exists():
                return
            if step >= steps:
                self.close_popup()
                return
            self.popup.attributes("-alpha", max(0.0, 0.96 * (1 - ((step + 1) / steps))))
            self.popup_after_ids.append(self.root.after(interval, lambda: fade(step + 1)))

        self.popup_after_ids.append(self.root.after(hold_ms, fade))

    @staticmethod
    def _popup_position(width: int, height: int) -> tuple[int, int]:
        class POINT(ctypes.Structure):
            _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

        class RECT(ctypes.Structure):
            _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]

        user32 = ctypes.windll.user32
        point = POINT()
        if user32.GetCursorPos(ctypes.byref(point)):
            monitor = user32.MonitorFromPoint(point, 2)
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                return info.rcWork.right - width - 24, info.rcWork.bottom - height - 24
        return 24, 24

    def close_popup(self) -> None:
        for after_id in self.popup_after_ids:
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass
        self.popup_after_ids.clear()
        if self.popup is not None:
            try:
                self.popup.destroy()
            except tk.TclError:
                pass
            self.popup = None

    def exit_app(self) -> None:
        self._cancel_dynamic_check()
        self.load_monitor.nvml.shutdown()
        self._stop_hotkey()
        self.close_popup()
        if self.tray_icon is not None:
            self.tray_icon.stop()
            self.tray_icon = None
        if self.config_editor is not None:
            self.config_editor.close()
        try:
            ctypes.windll.kernel32.CloseHandle(self.mutex_handle)
        except Exception:
            pass
        self.root.quit()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    if os.name != "nt":
        print(translate(DEFAULT_CONFIG, "windows_only", app=APP_NAME))
        return 1
    try:
        app = PowerPlanSwitcherApp()
        app.run()
        return 0
    except SystemExit:
        return 0
    except Exception as exc:
        LOGGER.exception("Fatal application error")
        ctypes.windll.user32.MessageBoxW(None, str(exc), APP_NAME, 0x10)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
