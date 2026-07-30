from __future__ import annotations

import ctypes
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


APP_NAME = "Energieplan-Umschalter"
APP_VERSION = "1.3.0"
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
        "apply_on_start": "Beim Start die Werte des aktuell aktiven Umschaltprofils erneut anwenden",
        "popup": "Popup",
        "visible_ms": "Sichtbar (ms)",
        "fade_ms": "Ausblenddauer (ms)",
        "width": "Breite",
        "height": "Höhe",
        "cancel": "Abbrechen",
        "save": "Speichern",
        "save_apply": "Speichern und ausgewähltes Profil anwenden",
        "profile_name": "Profilname",
        "windows_plan": "Windows-Energieplan",
        "mains": "Netzbetrieb",
        "battery": "Akkubetrieb",
        "cpu_min": "CPU Minimum (%)",
        "cpu_max": "CPU Maximum (%)",
        "display_timeout": "Bildschirm aus nach (Min.)",
        "sleep_timeout": "Standby nach (Min.)",
        "hibernate_timeout": "Ruhezustand nach (Min.)",
        "boost_mode": "CPU-Boostmodus",
        "cooling_policy": "Systemkühlungsrichtlinie",
        "boost_0": "0 - Deaktiviert",
        "boost_1": "1 - Aktiviert",
        "boost_2": "2 - Aggressiv",
        "boost_3": "3 - Effizient aktiviert",
        "boost_4": "4 - Effizient aggressiv",
        "cool_none": "Leer - Nicht verändern",
        "cool_0": "0 - Passiv",
        "cool_1": "1 - Aktiv",
        "time_note": "Bei Zeitwerten bedeutet 0 = Nie. Ein leeres Feld verändert die vorhandene Windows-Einstellung nicht. Die Werte werden beim Wechsel auf das jeweilige Profil angewendet.",
        "boost_note": "Boost 0 deaktiviert den Turbo. Boost 2 ist aggressiv und für das Leistungsprofil gedacht. Bei Bildschirm, Standby und Ruhezustand gilt: 0 = Nie, leer = unverändert.",
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
        "plan_manager_note": "Deaktivieren entfernt einen Energieplan aus Windows. Der aktive Plan und Pläne, die einem Profil zugeordnet sind, werden geschützt. Gelöschte benutzerdefinierte Pläne können nicht automatisch wiederhergestellt werden.",
        "select_installed": "Wähle zuerst einen installierten Energieplan aus.",
        "select_standard": "Wähle zuerst einen Windows-Standardplan aus.",
        "cannot_remove_active": "Der aktuell aktive Energieplan kann nicht entfernt werden. Aktiviere zuerst einen anderen Plan.",
        "cannot_remove_profile": "Dieser Energieplan ist einem Umschaltprofil zugeordnet. Weise dem Profil zuerst einen anderen Plan zu und speichere die Konfiguration.",
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
        "already_running": "Der Energieplan-Umschalter läuft bereits.",
        "hotkey_unknown": "Unbekannte Taste: {key}",
        "hotkey_failed": "{hotkey} konnte nicht registriert werden (Windows-Fehler {code}). Öffne die Konfiguration und wähle eine andere Kombination.",
        "profile_plan_missing": "Der Windows-Energieplan für '{name}' wurde nicht gefunden. Öffne die Energieplan-Verwaltung und installiere einen fehlenden Standardplan oder wähle einen vorhandenen Plan aus.",
        "invalid_profiles": "Unter 'profiles' müssen mindestens zwei Profile vorhanden sein.",
        "invalid_toggle": "app.toggle_profiles muss genau zwei Profil-IDs enthalten.",
        "invalid_profile_ref": "Das Umschaltprofil '{profile}' existiert nicht.",
        "invalid_hotkey": "Nicht unterstützte Hotkey-Taste: {key}",
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
        "apply_on_start": "Reapply the settings of the currently active toggle profile at startup",
        "popup": "Popup",
        "visible_ms": "Visible (ms)",
        "fade_ms": "Fade duration (ms)",
        "width": "Width",
        "height": "Height",
        "cancel": "Cancel",
        "save": "Save",
        "save_apply": "Save and apply selected profile",
        "profile_name": "Profile name",
        "windows_plan": "Windows power plan",
        "mains": "AC power",
        "battery": "Battery",
        "cpu_min": "CPU minimum (%)",
        "cpu_max": "CPU maximum (%)",
        "display_timeout": "Turn display off after (min.)",
        "sleep_timeout": "Sleep after (min.)",
        "hibernate_timeout": "Hibernate after (min.)",
        "boost_mode": "CPU boost mode",
        "cooling_policy": "System cooling policy",
        "boost_0": "0 - Disabled",
        "boost_1": "1 - Enabled",
        "boost_2": "2 - Aggressive",
        "boost_3": "3 - Efficient enabled",
        "boost_4": "4 - Efficient aggressive",
        "cool_none": "Blank - Do not change",
        "cool_0": "0 - Passive",
        "cool_1": "1 - Active",
        "time_note": "For time values, 0 means Never. A blank field leaves the existing Windows setting unchanged. Values are applied when switching to the profile.",
        "boost_note": "Boost 0 disables turbo boost. Boost 2 is aggressive and intended for the performance profile. For display, sleep and hibernate: 0 = Never, blank = unchanged.",
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
        "plan_manager_note": "Disabling removes a power plan from Windows. The active plan and plans assigned to a toggle profile are protected. Deleted custom plans cannot be restored automatically.",
        "select_installed": "Select an installed power plan first.",
        "select_standard": "Select a Windows standard plan first.",
        "cannot_remove_active": "The currently active power plan cannot be removed. Activate another plan first.",
        "cannot_remove_profile": "This power plan is assigned to a toggle profile. Assign another plan to the profile and save the configuration first.",
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
        "already_running": "The power plan switcher is already running.",
        "hotkey_unknown": "Unknown key: {key}",
        "hotkey_failed": "{hotkey} could not be registered (Windows error {code}). Open the configuration and choose another combination.",
        "profile_plan_missing": "The Windows power plan for '{name}' was not found. Open Power plans and install a missing standard plan or select an installed plan.",
        "invalid_profiles": "At least two profiles are required under 'profiles'.",
        "invalid_toggle": "app.toggle_profiles must contain exactly two profile IDs.",
        "invalid_profile_ref": "The toggle profile '{profile}' does not exist.",
        "invalid_hotkey": "Unsupported hotkey: {key}",
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
    "schema_version": 2,
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
        "toggle_profiles": ["summer", "performance"],
        "show_startup_popup": True,
        "apply_active_profile_on_start": False,
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
            "plan": {
                "guid": BALANCED_GUID,
                "name_contains": ["Ausbalanciert", "Balanced"],
            },
            "settings": {
                "processor_min_ac_percent": 5,
                "processor_max_ac_percent": 50,
                "processor_boost_mode_ac": 0,
                "cooling_policy_ac": 1,
                "display_timeout_ac_minutes": 0,
                "sleep_timeout_ac_minutes": 0,
                "hibernate_timeout_ac_minutes": 0,
                "processor_min_dc_percent": 5,
                "processor_max_dc_percent": 50,
                "processor_boost_mode_dc": 0,
                "cooling_policy_dc": 1,
                "display_timeout_dc_minutes": 0,
                "sleep_timeout_dc_minutes": 0,
                "hibernate_timeout_dc_minutes": 0,
            },
        },
        "performance": {
            "display_name": "Leistung",
            "plan": {
                "guid": ULTIMATE_GUID,
                "name_contains": ["Ultimative Leistung", "Ultimate Performance"],
            },
            "settings": {
                "processor_min_ac_percent": 5,
                "processor_max_ac_percent": 100,
                "processor_boost_mode_ac": 2,
                "cooling_policy_ac": 1,
                "display_timeout_ac_minutes": 0,
                "sleep_timeout_ac_minutes": 0,
                "hibernate_timeout_ac_minutes": 0,
                "processor_min_dc_percent": 5,
                "processor_max_dc_percent": 100,
                "processor_boost_mode_dc": 2,
                "cooling_policy_dc": 1,
                "display_timeout_dc_minutes": 0,
                "sleep_timeout_dc_minutes": 0,
                "hibernate_timeout_dc_minutes": 0,
            },
        },
    },
}

SETTING_DEFINITIONS: dict[str, tuple[str, str, str, Callable[[Any], int]]] = {
    "processor_min_ac_percent": ("ac", "SUB_PROCESSOR", "PROCTHROTTLEMIN", int),
    "processor_max_ac_percent": ("ac", "SUB_PROCESSOR", "PROCTHROTTLEMAX", int),
    "processor_boost_mode_ac": ("ac", "SUB_PROCESSOR", "PERFBOOSTMODE", int),
    "cooling_policy_ac": ("ac", "SUB_PROCESSOR", "SYSCOOLPOL", int),
    "display_timeout_ac_minutes": ("ac", "SUB_VIDEO", "VIDEOIDLE", lambda value: int(value) * 60),
    "sleep_timeout_ac_minutes": ("ac", "SUB_SLEEP", "STANDBYIDLE", lambda value: int(value) * 60),
    "hibernate_timeout_ac_minutes": ("ac", "SUB_SLEEP", "HIBERNATEIDLE", lambda value: int(value) * 60),
    "processor_min_dc_percent": ("dc", "SUB_PROCESSOR", "PROCTHROTTLEMIN", int),
    "processor_max_dc_percent": ("dc", "SUB_PROCESSOR", "PROCTHROTTLEMAX", int),
    "processor_boost_mode_dc": ("dc", "SUB_PROCESSOR", "PERFBOOSTMODE", int),
    "cooling_policy_dc": ("dc", "SUB_PROCESSOR", "SYSCOOLPOL", int),
    "display_timeout_dc_minutes": ("dc", "SUB_VIDEO", "VIDEOIDLE", lambda value: int(value) * 60),
    "sleep_timeout_dc_minutes": ("dc", "SUB_SLEEP", "STANDBYIDLE", lambda value: int(value) * 60),
    "hibernate_timeout_dc_minutes": ("dc", "SUB_SLEEP", "HIBERNATEIDLE", lambda value: int(value) * 60),
}


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


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_or_create_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        write_json_atomic(CONFIG_PATH, DEFAULT_CONFIG)
        return deep_copy_json(DEFAULT_CONFIG)
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        merged = deep_merge(DEFAULT_CONFIG, raw)
        merged["schema_version"] = 2
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
    if not isinstance(profiles, dict) or len(profiles) < 2:
        raise ValueError(translate(config, "invalid_profiles"))
    toggle_profiles = config.get("app", {}).get("toggle_profiles")
    if not isinstance(toggle_profiles, list) or len(toggle_profiles) != 2:
        raise ValueError(translate(config, "invalid_toggle"))
    for profile_id in toggle_profiles:
        if profile_id not in profiles:
            raise ValueError(translate(config, "invalid_profile_ref", profile=profile_id))
    language = str(config.get("app", {}).get("language", "de")).lower()
    if language not in TRANSLATIONS:
        raise ValueError("app.language must be 'de' or 'en'.")
    hotkey = config.get("app", {}).get("hotkey", {})
    key = str(hotkey.get("key", "")).upper()
    if key not in VK_CODES:
        raise ValueError(translate(config, "invalid_hotkey", key=key))
    for profile_id, profile in profiles.items():
        if not isinstance(profile, dict):
            raise ValueError(f"Invalid profile: {profile_id}")
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


def run_powercfg(arguments: list[str]) -> str:
    completed = subprocess.run(
        [POWERCFG, *arguments],
        capture_output=True,
        text=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
        check=False,
    )
    output = (decode_windows_console_output(completed.stdout) + decode_windows_console_output(completed.stderr)).strip()
    if completed.returncode != 0:
        raise RuntimeError(
            f"powercfg {' '.join(arguments)} failed (code {completed.returncode}).\n"
            f"{output or 'No error text returned.'}"
        )
    return output


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


def apply_profile_settings(plan_guid: str, settings: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for setting_name, definition in SETTING_DEFINITIONS.items():
        if setting_name not in settings:
            continue
        raw_value = settings.get(setting_name)
        if raw_value is None or raw_value == "":
            continue
        power_source, subgroup, setting, converter = definition
        command = "/setacvalueindex" if power_source == "ac" else "/setdcvalueindex"
        try:
            run_powercfg([command, plan_guid, subgroup, setting, str(converter(raw_value))])
        except RuntimeError as exc:
            warnings.append(f"{setting_name}: {exc}")
            LOGGER.warning("Could not apply %s: %s", setting_name, exc)
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
        self.window = tk.Toplevel(app.root)
        self.window.title(f"{APP_NAME} - {self.t('app_config')}")
        self.window.geometry("940x780")
        self.window.minsize(850, 680)
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

        general_tab = ttk.Frame(notebook, padding=14)
        notebook.add(general_tab, text=self.t("general"))
        self._build_general_tab(general_tab)

        for profile_id in self.app.config["app"]["toggle_profiles"]:
            profile = self.app.config["profiles"][profile_id]
            tab = ttk.Frame(notebook, padding=14)
            notebook.add(tab, text=profile.get("display_name", profile_id))
            self._build_profile_tab(tab, profile_id, profile)

        plans_tab = ttk.Frame(notebook, padding=14)
        notebook.add(plans_tab, text=self.t("power_plans"))
        self._build_plan_manager_tab(plans_tab)

        ttk.Label(outer, text=self.t("time_note"), wraplength=880, justify="left").pack(fill="x", pady=(10, 6))
        buttons = ttk.Frame(outer)
        buttons.pack(fill="x")
        ttk.Button(buttons, text=self.t("cancel"), command=self.close).pack(side="right")
        ttk.Button(buttons, text=self.t("save"), command=self.save).pack(side="right", padx=8)
        ttk.Button(buttons, text=self.t("save_apply"), command=self.save_and_apply).pack(side="right")

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

        popup = config.get("popup", {})
        ttk.Label(parent, text=self.t("popup"), font=("Segoe UI", 11, "bold")).grid(row=7, column=0, columnspan=4, sticky="w", pady=(20, 10))
        popup_fields = [
            (self.t("visible_ms"), "hold_ms", 900),
            (self.t("fade_ms"), "fade_ms", 900),
            (self.t("width"), "width", 390),
            (self.t("height"), "height", 78),
        ]
        for row, (label, key, default) in enumerate(popup_fields, start=8):
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
            variable = tk.StringVar(value=str(popup.get(key, default)))
            self.variables[f"popup.{key}"] = variable
            ttk.Entry(parent, textvariable=variable, width=16).grid(row=row, column=1, sticky="w")
        parent.columnconfigure(3, weight=1)

    def _build_profile_tab(self, parent: ttk.Frame, profile_id: str, profile: dict[str, Any]) -> None:
        variables: dict[str, tk.Variable] = {}
        self.profile_variables[profile_id] = variables
        ttk.Label(parent, text=self.t("profile_name")).grid(row=0, column=0, sticky="w", pady=4)
        name_var = tk.StringVar(value=str(profile.get("display_name", profile_id)))
        variables["display_name"] = name_var
        ttk.Entry(parent, textvariable=name_var, width=36).grid(row=0, column=1, columnspan=3, sticky="ew", pady=4)

        ttk.Label(parent, text=self.t("windows_plan")).grid(row=1, column=0, sticky="w", pady=4)
        plan_var = tk.StringVar()
        variables["plan_selection"] = plan_var
        combo = ttk.Combobox(parent, textvariable=plan_var, width=70)
        combo.grid(row=1, column=1, columnspan=3, sticky="ew", pady=4)
        self.plan_comboboxes.append(combo)
        combo._profile_id = profile_id  # type: ignore[attr-defined]

        settings = profile.get("settings", {})
        notebook = ttk.Notebook(parent)
        notebook.grid(row=2, column=0, columnspan=4, sticky="nsew", pady=(14, 0))
        for source, title_key in (("ac", "mains"), ("dc", "battery")):
            tab = ttk.Frame(notebook, padding=12)
            notebook.add(tab, text=self.t(title_key))
            self._build_source_settings(tab, variables, settings, source)
        parent.rowconfigure(2, weight=1)
        parent.columnconfigure(1, weight=1)
        parent.columnconfigure(2, weight=1)
        parent.columnconfigure(3, weight=1)
        self._refresh_profile_plan_combobox(combo, profile_id)

    def _boost_labels(self) -> dict[str, int]:
        return {self.t(f"boost_{value}"): value for value in BOOST_VALUES}

    def _cooling_labels(self) -> dict[str, int | None]:
        return {
            self.t("cool_none"): None,
            self.t("cool_0"): 0,
            self.t("cool_1"): 1,
        }

    def _build_source_settings(self, parent: ttk.Frame, variables: dict[str, tk.Variable], settings: dict[str, Any], source: str) -> None:
        row = 0
        for label_key, template in self.FIELD_ROWS:
            key = template.format(source=source)
            ttk.Label(parent, text=self.t(label_key)).grid(row=row, column=0, sticky="w", pady=5)
            value = settings.get(key)
            variable = tk.StringVar(value="" if value is None else str(value))
            variables[key] = variable
            ttk.Entry(parent, textvariable=variable, width=18).grid(row=row, column=1, sticky="w", padx=(12, 0), pady=5)
            row += 1

        boost_labels = self._boost_labels()
        boost_key = f"processor_boost_mode_{source}"
        ttk.Label(parent, text=self.t("boost_mode")).grid(row=row, column=0, sticky="w", pady=5)
        boost_value = settings.get(boost_key, 0)
        boost_label = next((label for label, value in boost_labels.items() if value == boost_value), self.t("boost_0"))
        boost_var = tk.StringVar(value=boost_label)
        variables[boost_key] = boost_var
        ttk.Combobox(parent, textvariable=boost_var, values=list(boost_labels.keys()), state="readonly", width=30).grid(row=row, column=1, sticky="w", padx=(12, 0), pady=5)
        row += 1

        cooling_labels = self._cooling_labels()
        cooling_key = f"cooling_policy_{source}"
        ttk.Label(parent, text=self.t("cooling_policy")).grid(row=row, column=0, sticky="w", pady=5)
        cooling_value = settings.get(cooling_key)
        cooling_label = next((label for label, value in cooling_labels.items() if value == cooling_value), self.t("cool_none"))
        cooling_var = tk.StringVar(value=cooling_label)
        variables[cooling_key] = cooling_var
        ttk.Combobox(parent, textvariable=cooling_var, values=list(cooling_labels.keys()), state="readonly", width=30).grid(row=row, column=1, sticky="w", padx=(12, 0), pady=5)

        ttk.Label(parent, text=self.t("boost_note"), wraplength=700, justify="left").grid(row=row + 1, column=0, columnspan=3, sticky="w", pady=(18, 0))
        parent.columnconfigure(2, weight=1)

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
        profile = self.app.config["profiles"][profile_id]
        configured_guid = str(profile.get("plan", {}).get("guid") or "").lower()
        values: list[str] = []
        selected = ""
        for plan in plans:
            display = f"{plan['name']} | {plan['guid']}"
            values.append(display)
            self.plan_values[display] = plan["guid"]
            if plan["guid"] == configured_guid:
                selected = display
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
        for profile_id in self.app.config["app"]["toggle_profiles"]:
            try:
                profile = self.app.config["profiles"][profile_id]
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
            config = deep_copy_json(self.app.config)
            language_map = self.variables["language_map"]  # type: ignore[assignment]
            language_display = str(self.variables["language"].get())
            config["app"]["language"] = language_map.get(language_display, "de")
            app_config = config["app"]
            hotkey = app_config["hotkey"]
            hotkey["key"] = str(self.variables["hotkey.key"].get()).upper()
            for key in ("ctrl", "alt", "shift", "win"):
                hotkey[key] = bool(self.variables[f"hotkey.{key}"].get())
            app_config["show_startup_popup"] = bool(self.variables["show_startup_popup"].get())
            app_config["apply_active_profile_on_start"] = bool(self.variables["apply_active_profile_on_start"].get())
            app_config["autostart"] = bool(self.variables["autostart"].get())

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
            for profile_id, variables in self.profile_variables.items():
                profile = config["profiles"][profile_id]
                profile["display_name"] = str(variables["display_name"].get()).strip() or profile_id
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

            validate_config(config)
            try:
                set_autostart_enabled(bool(app_config["autostart"]))
            except OSError as exc:
                raise RuntimeError(translate(config, "autostart_error", error=exc)) from exc
            write_json_atomic(CONFIG_PATH, config)
            selected_index = self.main_notebook.index(self.main_notebook.select()) if self.main_notebook is not None else 0
            self.app.reload_config(show_confirmation=False)

            if apply_selected:
                profile_ids = self.app.config["app"]["toggle_profiles"]
                if selected_index == 0 or selected_index > len(profile_ids):
                    raise ValueError(self.app.t("select_profile_tab"))
                self.app.apply_profile(profile_ids[selected_index - 1])
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
        self.mutex_handle = create_mutex_or_exit(self.config)

        self.reload_config(show_confirmation=False, initial=True)
        self._start_tray_icon()
        self._start_hotkey()
        self.root.after(50, self._process_action_queue)
        if self.config["app"].get("apply_active_profile_on_start"):
            self._apply_active_profile_settings_only()
        if self.config["app"].get("show_startup_popup", True):
            self.root.after(250, self._show_ready_popup)

    @property
    def language(self) -> str:
        return language_from_config(self.config)

    def t(self, key: str, **values: Any) -> str:
        return translate(self.config, key, **values)

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

    def _start_tray_icon(self) -> None:
        self.tray_icon = pystray.Icon(APP_NAME, self._load_icon_image(), f"{APP_NAME} v{APP_VERSION}", self._create_tray_menu())
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
        for profile_id in self.config["app"]["toggle_profiles"]:
            display_name = self.config["profiles"][profile_id].get("display_name", profile_id)
            profile_items.append(pystray.MenuItem(self.t("apply_profile", name=display_name), self._profile_menu_action(profile_id)))
        hotkey_name = HotkeyThread.display_name(self.config["app"]["hotkey"], self.language)
        return pystray.Menu(
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
                self.root.after(50, self._process_action_queue)
        except tk.TclError:
            pass

    def reload_config(self, show_confirmation: bool = True, initial: bool = False) -> None:
        try:
            self.config = load_or_create_config()
            validate_config(self.config)
            self.config["app"]["autostart"] = is_autostart_enabled()
            if not initial:
                self._start_hotkey()
                if self.tray_icon is not None:
                    self.tray_icon.menu = self._create_tray_menu()
                    self.tray_icon.update_menu()
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
            profile_ids = self.config["app"]["toggle_profiles"]
            plans = list_power_plans()
            active_guid = get_active_plan_guid()
            first_id, second_id = profile_ids
            first_guid = resolve_plan_guid(self.config["profiles"][first_id], plans, self.config)
            second_guid = resolve_plan_guid(self.config["profiles"][second_id], plans, self.config)
            target_id = second_id if active_guid == first_guid else first_id
            if active_guid not in (first_guid, second_guid):
                target_id = first_id
            self.apply_profile(target_id)
        except Exception as exc:
            LOGGER.exception("Could not toggle profile")
            self.show_popup(self.t("error", error=exc), error=True)

    def apply_profile(self, profile_id: str) -> None:
        if self.is_switching:
            return
        self.is_switching = True
        try:
            profile = self.config["profiles"][profile_id]
            plans = list_power_plans()
            plan_guid = resolve_plan_guid(profile, plans, self.config)
            warnings = apply_profile_settings(plan_guid, profile.get("settings", {}))
            run_powercfg(["/setactive", plan_guid])
            display_name = profile.get("display_name", profile_id)
            if warnings:
                self.show_popup(self.t("profile_warning", name=display_name, count=len(warnings)), error=True)
            else:
                self.show_popup(self.t("profile_active", name=display_name))
            LOGGER.info("Applied profile %s to plan %s", profile_id, plan_guid)
        except Exception as exc:
            LOGGER.exception("Could not apply profile %s", profile_id)
            self.show_popup(self.t("error", error=exc), error=True)
        finally:
            self.is_switching = False

    def _apply_active_profile_settings_only(self) -> None:
        try:
            active_guid = get_active_plan_guid()
            plans = list_power_plans()
            for profile_id in self.config["app"]["toggle_profiles"]:
                profile = self.config["profiles"][profile_id]
                if resolve_plan_guid(profile, plans, self.config) == active_guid:
                    apply_profile_settings(active_guid, profile.get("settings", {}))
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
