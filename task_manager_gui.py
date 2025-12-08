#!/usr/bin/env python3
"""
Task Manager GUI - Display running processes with RAM usage
PyQt5-based GUI showing system memory and process information
"""

import sys
import os
import json
import psutil
import threading
import subprocess
import shutil
import ctypes
import webbrowser
import urllib.parse
import time
try:
    import pygame
    GAMEPAD_AVAILABLE = True
except ImportError:
    GAMEPAD_AVAILABLE = False
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QLabel, QProgressBar, QHeaderView, QMenu, QMessageBox, QPushButton,
    QDialog, QRadioButton, QButtonGroup, QCheckBox, QSizePolicy, QLineEdit, QTextEdit
)
from PyQt5.QtCore import QTimer, Qt, pyqtSignal, QObject, QPoint, QRect, QEvent, QUrl, QThread
from PyQt5.QtGui import QFont, QColor, QBrush, QKeyEvent
try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings
    from PyQt5.QtWebEngineCore import QWebEngineUrlRequestInterceptor
    WEBENGINE_AVAILABLE = True
except ImportError:
    WEBENGINE_AVAILABLE = False
from datetime import datetime

# Config file path (use APPDATA on Windows, dotfile on Unix-like systems)
if os.name == 'nt':
    _appdata = os.getenv('APPDATA') or os.path.expanduser('~')
    CONFIG_FILE = os.path.join(_appdata, 'task_manager_config.json')
else:
    CONFIG_FILE = os.path.expanduser('~/.task_manager_config.json')

# (No hard cap on processes; iterate all available processes)


class ClickableLabel(QLabel):
    """Label that emits a signal when clicked"""
    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self.parent_callback = None
    
    def mousePressEvent(self, event):
        if self.parent_callback:
            self.parent_callback()
        super().mousePressEvent(event)


def load_theme():
    """Load saved theme from config file"""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                if 'theme' in config:
                    return config.get('theme', 'light')
    except Exception as e:
        print(f"Error loading theme: {e}")
    # Fallback: return light theme if no saved config
    return 'light'


def is_windows_admin() -> bool:
    """Return True if running with admin rights on Windows."""
    if os.name != 'nt':
        return False
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def detect_system_theme() -> str:
    """Return 'dark' or 'light' based on OS preference. Minimal implementation."""
    try:
        if os.name == 'nt':
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
                val, _ = winreg.QueryValueEx(key, 'AppsUseLightTheme')
                winreg.CloseKey(key)
                return 'light' if val == 1 else 'dark'
            except Exception:
                return 'light'
        else:
            # Default to light on non-Windows
            return 'light'
    except Exception:
        return 'light'


def detect_gpu_info() -> dict:
    """Try to detect GPU name and driver version. Returns dict with 'name' and 'driver'."""
    info = {'name': 'Unknown', 'driver': 'Unknown'}
    try:
        # Try nvidia-smi for NVIDIA GPUs
        out = shutil.which('nvidia-smi')
        if out:
            proc = subprocess.run(['nvidia-smi', '--query-gpu=name,driver_version', '--format=csv,noheader'], capture_output=True, text=True)
            if proc.returncode == 0 and proc.stdout.strip():
                parts = [p.strip() for p in proc.stdout.strip().split(',')]
                if parts:
                    info['name'] = parts[0]
                    if len(parts) > 1:
                        info['driver'] = parts[1]
                    return info
    except Exception:
        pass

    # Fallback Windows WMI via PowerShell
    if os.name == 'nt':
        try:
            ps_cmd = [
                'powershell', '-NoProfile', '-Command',
                'Get-CimInstance Win32_VideoController | Select-Object -First 1 Name,DriverVersion | ForEach-Object { "$($_.Name)|$($_.DriverVersion)" }'
            ]
            out = subprocess.run(ps_cmd, capture_output=True, text=True)
            if out.returncode == 0 and out.stdout.strip():
                line = out.stdout.strip().splitlines()[0]
                if '|' in line:
                    name, driver = [part.strip() or 'Unknown' for part in line.split('|', 1)]
                    info['name'] = name
                    info['driver'] = driver
                    return info
        except Exception:
            pass

    return info


def detect_os_name() -> str:
    """Return a friendly OS name."""
    try:
        import platform
        # On Windows, prefer ProductName from the registry for friendly names
        if os.name == 'nt':
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion")
                product_name, _ = winreg.QueryValueEx(key, 'ProductName')
                build_str, _ = winreg.QueryValueEx(key, 'CurrentBuildNumber')
                try:
                    ubr, _ = winreg.QueryValueEx(key, 'UBR')
                except Exception:
                    ubr = None
                winreg.CloseKey(key)
                # Normalize Windows 11 detection by build number >= 22000
                try:
                    build_num = int(build_str)
                except Exception:
                    build_num = 0
                if 'Windows 11' in product_name or build_num >= 22000:
                    base = 'Windows 11'
                else:
                    base = product_name
                if ubr:
                    return f"{base} (Build {build_str}, UBR {ubr})"
                return f"{base} (Build {build_str})"
            except Exception:
                # Fallback to platform APIs
                try:
                    ver = platform.version()
                    return f"Windows {ver}"
                except Exception:
                    return 'Windows'

        # Non-Windows: use platform system + release
        name = platform.system()
        rel = platform.release()
        return f"{name} {rel}"
    except Exception:
        return 'Unknown'


def detect_cpu_name() -> str:
    """Return a short CPU name if available."""
    try:
        import platform
        # On Windows, platform.processor() often returns vendor strings like 'GenuineIntel'.
        # Prefer using PowerShell/WMI to get the friendly processor name if available.
        if os.name == 'nt':
            try:
                ps_cmd = [
                    'powershell', '-NoProfile', '-Command',
                    'Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name'
                ]
                out = subprocess.run(ps_cmd, capture_output=True, text=True)
                if out.returncode == 0 and out.stdout.strip():
                    name = out.stdout.strip().splitlines()[0].strip()
                    if name:
                        return name
            except Exception:
                pass

        # Fallback to platform.processor()
        cpu = platform.processor() or ''
        if cpu and cpu.lower() not in ('', 'genuineintel', 'authenticamd'):
            return cpu

        # Try Linux /proc
        if os.path.exists('/proc/cpuinfo'):
            try:
                with open('/proc/cpuinfo', 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        if 'model name' in line.lower():
                            return line.split(':', 1)[1].strip()
            except Exception:
                pass
    except Exception:
        pass
    return 'Unknown'


def save_theme(theme_name):
    """Save theme to config file"""
    try:
        config = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
        config['theme'] = theme_name
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"Error saving theme: {e}")


def load_hide_system_processes():
    """Load hide system processes setting from config file"""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                return config.get('hide_system_processes', False)
    except Exception as e:
        print(f"Error loading hide_system_processes: {e}")
    return False


def save_hide_system_processes(hide_system: bool):
    """Save hide system processes setting to config file"""
    try:
        config = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
        config['hide_system_processes'] = hide_system
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"Error saving hide_system_processes: {e}")


def load_hide_inaccessible_processes():
    """Load hide inaccessible processes setting from config file"""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                return config.get('hide_inaccessible_processes', False)
    except Exception as e:
        print(f"Error loading hide_inaccessible_processes: {e}")
    return False


def save_hide_inaccessible_processes(hide_inaccessible: bool):
    """Save hide inaccessible processes setting to config file"""
    try:
        config = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
        config['hide_inaccessible_processes'] = hide_inaccessible
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"Error saving hide_inaccessible_processes: {e}")


class DataFetcher(QThread):
    """Persistent background thread that polls system data at a configurable interval.

    Emits `data_ready` with (mem_info, processes).
    """
    data_ready = pyqtSignal(dict, list)

    def __init__(self, interval_sec=4.0):
        super().__init__()
        self.interval = float(interval_sec)
        self.process_cache = {}
        self.total_memory = psutil.virtual_memory().total
        self._stop_event = threading.Event()
        self._immediate_event = threading.Event()
        # CPU sampling: sample every N cycles
        self._cpu_sample_rate = 4
        self._cpu_sample_counter = 0
        # Whether we've performed an initial cpu_percent() warm-up pass
        self._cpu_initialized = False
        # Disk IO sampling threshold (MB)
        self._disk_io_threshold_mb = 50

    def trigger_fetch(self):
        """Trigger an immediate fetch outside the regular interval."""
        self._immediate_event.set()

    def stop(self):
        self._stop_event.set()
        self._immediate_event.set()

    def run(self):
        while not self._stop_event.is_set():
            try:
                mem = psutil.virtual_memory()
                gb_divisor = 1073741824
                mem_info = {
                    'total': round(mem.total / gb_divisor, 2),
                    'used': round(mem.used / gb_divisor, 2),
                    'available': round(mem.available / gb_divisor, 2),
                    'percent': round(mem.percent, 1)
                }

                processes = []
                do_cpu_sample = (self._cpu_sample_counter == 0)

                for proc in psutil.process_iter(['pid', 'name', 'memory_info', 'username']):
                    try:
                        with proc.oneshot():
                            pid = proc.pid
                            pinfo = proc.as_dict(attrs=['pid', 'name', 'memory_info', 'username'])
                            rss = pinfo['memory_info'].rss
                            memory_mb = round(rss / 1048576, 1)

                            cpu_percent = 0.0
                            try:
                                if do_cpu_sample:
                                    # Use interval=None to get non-blocking percent compared to last call.
                                    # On the very first sampling pass we must "warm up" the counters
                                    # by calling cpu_percent once (it will return 0.0). Subsequent
                                    # calls with interval=None return meaningful percentages.
                                    if not self._cpu_initialized:
                                        proc.cpu_percent(interval=None)
                                        self.process_cache[pid] = 0.0
                                    else:
                                        cpu_percent = proc.cpu_percent(interval=None)
                                        # store last seen value in cache for use between sample cycles
                                        self.process_cache[pid] = float(cpu_percent)
                                else:
                                    cpu_percent = float(self.process_cache.get(pid, 0.0))
                            except (psutil.AccessDenied, psutil.NoSuchProcess):
                                cpu_percent = 0.0

                            disk_mb = 0.0
                            if memory_mb > self._disk_io_threshold_mb:
                                try:
                                    io = proc.io_counters()
                                    disk_mb = round((io.read_bytes + io.write_bytes) / 1048576, 1)
                                except (psutil.AccessDenied, psutil.NoSuchProcess, AttributeError):
                                    pass

                            username = pinfo.get('username') or 'unknown'
                            if '\\' in username:
                                username = username.rpartition('\\')[2]

                            processes.append({
                                'pid': pinfo['pid'],
                                'name': (pinfo['name'] or '')[:30],
                                'username': username[:15],
                                'cpu_percent': round(cpu_percent, 1),
                                'memory_mb': memory_mb,
                                'memory_percent': round(rss / self.total_memory * 100, 1),
                                'disk_io_mb': disk_mb
                            })
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        pass

                # Clean up process cache
                current_pids = {p['pid'] for p in processes}
                for pid in list(self.process_cache.keys()):
                    if pid not in current_pids:
                        del self.process_cache[pid]

                # Mark CPU initialized once we've completed one warm-up sampling pass
                if do_cpu_sample and not self._cpu_initialized:
                    self._cpu_initialized = True

                processes.sort(key=lambda x: x['memory_mb'], reverse=True)
                # Emit data to UI thread
                self.data_ready.emit(mem_info, processes)
            except Exception as e:
                print(f"Error in DataFetcher run loop: {e}")
            finally:
                # advance sampling counter
                try:
                    self._cpu_sample_counter = (self._cpu_sample_counter + 1) % self._cpu_sample_rate
                except Exception:
                    self._cpu_sample_counter = 0

            # Wait for interval or immediate trigger or stop
            if self._stop_event.is_set():
                break
            signaled = self._immediate_event.wait(self.interval)
            if signaled:
                self._immediate_event.clear()


# Removed ProcessTableModel to restore original QTableWidget implementation


class VirtualKeyboard(QDialog):
    """Virtual keyboard for gamepad input"""
    def __init__(self, parent=None, initial_text=''):
        super().__init__(parent)
        self.setWindowTitle('Virtual Keyboard')
        self.setModal(True)
        self.parent_window = parent
        self.text_buffer = initial_text
        
        # Keyboard layout
        self.keys = [
            ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
            ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'],
            ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', 'BACK'],
            ['z', 'x', 'c', 'v', 'b', 'n', 'm', '-', '_', 'SPACE'],
            ['CLEAR', 'DONE']
        ]
        
        layout = QVBoxLayout()
        
        # Text display
        self.text_display = QLineEdit()
        self.text_display.setText(self.text_buffer)
        self.text_display.setReadOnly(True)
        self.text_display.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setPointSize(14)
        self.text_display.setFont(font)
        layout.addWidget(self.text_display)
        
        # Keyboard grid
        self.key_buttons = []
        for row in self.keys:
            row_layout = QHBoxLayout()
            row_buttons = []
            for key in row:
                btn = QPushButton(key)
                btn.setMinimumHeight(40)
                if key in ['BACK', 'SPACE', 'CLEAR', 'DONE']:
                    btn.setMinimumWidth(80)
                else:
                    btn.setMinimumWidth(50)
                btn.clicked.connect(lambda checked, k=key: self.key_pressed(k))
                row_layout.addWidget(btn)
                row_buttons.append(btn)
            self.key_buttons.append(row_buttons)
            layout.addLayout(row_layout)
        
        self.setLayout(layout)
        
        # Gamepad navigation
        self.current_row = 0
        self.current_col = 0
        self.gamepad_button_states = {}
        self.gamepad_last_axis = {'x': 0, 'y': 0}
        self.gamepad_repeat_counter = 0
        self.gamepad_repeat_delay = 3  # Initial delay before repeat starts
        self.gamepad_repeat_rate = 1   # Frames between repeats after initial delay
        
        # Highlight initial key
        self.update_key_highlight()
        
        # Start gamepad timer
        self.gamepad_timer = None
        if parent and hasattr(parent, 'gamepad') and parent.gamepad:
            self.gamepad_timer = QTimer()
            self.gamepad_timer.timeout.connect(self.process_keyboard_gamepad)
            self.gamepad_timer.start(100)
    
    def closeEvent(self, event):
        """Stop gamepad timer when dialog closes"""
        if self.gamepad_timer:
            self.gamepad_timer.stop()
            self.gamepad_timer = None
        super().closeEvent(event)
    
    def accept(self):
        """Override accept to stop timer"""
        if self.gamepad_timer:
            self.gamepad_timer.stop()
            self.gamepad_timer = None
        super().accept()
    
    def reject(self):
        """Override reject to stop timer"""
        if self.gamepad_timer:
            self.gamepad_timer.stop()
            self.gamepad_timer = None
        super().reject()
    
    def key_pressed(self, key):
        """Handle key press"""
        print(f"Key pressed: '{key}', Buffer before: '{self.text_buffer}'")
        if key == 'BACK':
            if len(self.text_buffer) > 0:
                self.text_buffer = self.text_buffer[:-1]
        elif key == 'SPACE':
            self.text_buffer += ' '
        elif key == 'CLEAR':
            self.text_buffer = ''
        elif key == 'DONE':
            print(f"Final buffer: '{self.text_buffer}'")
            self.accept()
            return
        else:
            self.text_buffer += key
        
        print(f"Buffer after: '{self.text_buffer}'")
        self.text_display.setText(self.text_buffer)
        
        # Update parent search box immediately
        if self.parent_window and hasattr(self.parent_window, 'search_input'):
            self.parent_window.search_input.setText(self.text_buffer)
            print(f"Parent search box updated to: '{self.parent_window.search_input.text()}'")
    
    def get_text(self):
        """Return the entered text"""
        return self.text_buffer
    
    def update_key_highlight(self):
        """Highlight the currently selected key"""
        for row_idx, row in enumerate(self.key_buttons):
            for col_idx, btn in enumerate(row):
                if row_idx == self.current_row and col_idx == self.current_col:
                    btn.setStyleSheet("QPushButton { background-color: rgba(255, 165, 0, 0.5); font-weight: bold; }")
                else:
                    btn.setStyleSheet("")
    
    def process_keyboard_gamepad(self):
        """Handle gamepad input for virtual keyboard"""
        if not self.parent_window or not hasattr(self.parent_window, 'gamepad') or not self.parent_window.gamepad:
            return
        
        try:
            pygame.event.pump()
            gamepad = self.parent_window.gamepad
            
            # Button handling FIRST - check if A button is pressed to lock position
            button_pressed = False
            for button_id in range(min(10, gamepad.get_numbuttons())):
                is_pressed = gamepad.get_button(button_id)
                was_pressed = self.gamepad_button_states.get(button_id, False)
                
                if is_pressed and not was_pressed:
                    button_pressed = True
                    if button_id == 0:  # A button - Press key
                        # Reset navigation counter to prevent drift
                        self.gamepad_repeat_counter = 0
                        # Ensure indices are valid
                        if 0 <= self.current_row < len(self.keys) and 0 <= self.current_col < len(self.keys[self.current_row]):
                            key = self.keys[self.current_row][self.current_col]
                            print(f"Button A pressed - Row: {self.current_row}, Col: {self.current_col}, Key: '{key}'")
                            self.key_pressed(key)
                        else:
                            print(f"Invalid position - Row: {self.current_row}, Col: {self.current_col}")
                    elif button_id == 1:  # B button - Cancel
                        self.reject()
                    elif button_id == 7:  # Start button - Done
                        self.accept()
                
                self.gamepad_button_states[button_id] = is_pressed
            
            # Only process navigation if no action button was pressed
            if not button_pressed:
                # D-pad / Left stick for navigation
                hat = gamepad.get_hat(0) if gamepad.get_numhats() > 0 else (0, 0)
                axis_x = gamepad.get_axis(0) if gamepad.get_numaxes() > 0 else 0
                axis_y = gamepad.get_axis(1) if gamepad.get_numaxes() > 1 else 0
                
                current_y = hat[1] if hat[1] != 0 else (1 if axis_y < -0.5 else (-1 if axis_y > 0.5 else 0))
                current_x = hat[0] if hat[0] != 0 else (-1 if axis_x < -0.5 else (1 if axis_x > 0.5 else 0))
                
                # Check for direction changes or continuous hold
                should_move = False
                if current_y != self.gamepad_last_axis['y'] or current_x != self.gamepad_last_axis['x']:
                    # Direction changed - reset counter and move
                    should_move = True
                    self.gamepad_repeat_counter = 0
                    self.gamepad_last_axis['y'] = current_y
                    self.gamepad_last_axis['x'] = current_x
                elif current_y != 0 or current_x != 0:
                    # Direction held - check repeat timing
                    if self.gamepad_repeat_counter >= self.gamepad_repeat_delay:
                        should_move = True
                        # Reset counter to repeat rate after initial delay
                        if self.gamepad_repeat_counter >= self.gamepad_repeat_delay:
                            self.gamepad_repeat_counter = self.gamepad_repeat_delay - self.gamepad_repeat_rate
                    
                    self.gamepad_repeat_counter += 1
                else:
                    # No input - reset counter
                    self.gamepad_repeat_counter = 0
                
                if should_move:
                    if current_y > 0:  # Up
                        self.current_row = max(0, self.current_row - 1)
                        self.current_col = min(self.current_col, len(self.key_buttons[self.current_row]) - 1)
                        self.update_key_highlight()
                    elif current_y < 0:  # Down
                        self.current_row = min(len(self.key_buttons) - 1, self.current_row + 1)
                        self.current_col = min(self.current_col, len(self.key_buttons[self.current_row]) - 1)
                        self.update_key_highlight()
                    
                    if current_x < 0:  # Left
                        self.current_col = max(0, self.current_col - 1)
                        self.update_key_highlight()
                    elif current_x > 0:  # Right
                        self.current_col = min(len(self.key_buttons[self.current_row]) - 1, self.current_col + 1)
                        self.update_key_highlight()
        
        except Exception as e:
            print(f"Virtual keyboard gamepad error: {e}")


class ControllerTestDialog(QDialog):
    """Dialog for testing controller input"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Controller Input Test')
        self.setFixedSize(500, 400)
        self.parent_window = parent
        
        layout = QVBoxLayout()
        
        # Info label
        info_label = QLabel('Press buttons, move sticks, or use D-pad to test controller input')
        info_label.setAlignment(Qt.AlignCenter)
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # Test display area
        self.test_display = QTextEdit()
        self.test_display.setReadOnly(True)
        self.test_display.setFont(QFont('Courier', 10))
        layout.addWidget(self.test_display)
        
        # Close button
        close_btn = QPushButton('Close')
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
        
        self.setLayout(layout)
        
        # Gamepad state
        self.gamepad_button_states = {}
        self.gamepad_last_axis = {'x': 0, 'y': 0, 'rx': 0, 'ry': 0}
        
        # Start gamepad timer
        self.gamepad_timer = None
        if parent and hasattr(parent, 'gamepad') and parent.gamepad:
            self.gamepad_timer = QTimer()
            self.gamepad_timer.timeout.connect(self.process_controller_input)
            self.gamepad_timer.start(50)  # Poll every 50ms for responsive testing
    
    def closeEvent(self, event):
        """Stop gamepad timer when dialog closes"""
        if self.gamepad_timer:
            self.gamepad_timer.stop()
            self.gamepad_timer = None
        super().closeEvent(event)
    
    def accept(self):
        """Override accept to stop timer"""
        if self.gamepad_timer:
            self.gamepad_timer.stop()
            self.gamepad_timer = None
        super().accept()
    
    def process_controller_input(self):
        """Process and display controller input"""
        if not self.parent_window or not hasattr(self.parent_window, 'gamepad') or not self.parent_window.gamepad:
            return
        
        try:
            pygame.event.pump()
            gamepad = self.parent_window.gamepad
            
            # Check buttons
            for button_id in range(min(16, gamepad.get_numbuttons())):
                is_pressed = gamepad.get_button(button_id)
                was_pressed = self.gamepad_button_states.get(button_id, False)
                
                if is_pressed and not was_pressed:
                    self.test_display.append(f"Button {button_id} pressed")
                elif not is_pressed and was_pressed:
                    self.test_display.append(f"Button {button_id} released")
                
                self.gamepad_button_states[button_id] = is_pressed
            
            # Check D-pad
            if gamepad.get_numhats() > 0:
                hat = gamepad.get_hat(0)
                if hat != (0, 0):
                    direction = []
                    if hat[0] < 0:
                        direction.append('Left')
                    elif hat[0] > 0:
                        direction.append('Right')
                    if hat[1] > 0:
                        direction.append('Up')
                    elif hat[1] < 0:
                        direction.append('Down')
                    self.test_display.append(f"D-pad: {' + '.join(direction)}")
            
            # Check axes (sticks)
            if gamepad.get_numaxes() >= 2:
                axis_x = gamepad.get_axis(0)
                axis_y = gamepad.get_axis(1)
                
                if abs(axis_x - self.gamepad_last_axis['x']) > 0.1 or abs(axis_y - self.gamepad_last_axis['y']) > 0.1:
                    self.test_display.append(f"Left Stick: X={axis_x:.2f}, Y={axis_y:.2f}")
                    self.gamepad_last_axis['x'] = axis_x
                    self.gamepad_last_axis['y'] = axis_y
            
            if gamepad.get_numaxes() >= 4:
                axis_rx = gamepad.get_axis(2)
                axis_ry = gamepad.get_axis(3)
                
                if abs(axis_rx - self.gamepad_last_axis['rx']) > 0.1 or abs(axis_ry - self.gamepad_last_axis['ry']) > 0.1:
                    self.test_display.append(f"Right Stick: X={axis_rx:.2f}, Y={axis_ry:.2f}")
                    self.gamepad_last_axis['rx'] = axis_rx
                    self.gamepad_last_axis['ry'] = axis_ry
            
            # Auto-scroll to bottom
            scrollbar = self.test_display.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
        
        except Exception as e:
            self.test_display.append(f"Error: {e}")


class BrowserDialog(QDialog):
    """Embedded browser dialog for viewing web content"""
    def __init__(self, parent=None, url=''):
        super().__init__(parent)
        self.setWindowTitle('Process Lookup')
        self.parent_window = parent
        
        # Block parent window movement by setting a flag
        if parent:
            parent.browser_dialog_open = True
        
        # Make dialog smaller than main window
        if parent:
            parent_geometry = parent.geometry()
            width = int(parent_geometry.width() * 0.7)
            height = int(parent_geometry.height() * 0.8)
            self.resize(width, height)
        else:
            self.resize(800, 600)
        
        layout = QVBoxLayout()
        
        if WEBENGINE_AVAILABLE:
            # Create web view
            self.browser = QWebEngineView()
            
            # Disable sandbox if running as root
            if (hasattr(os, 'geteuid') and os.geteuid() == 0) or (os.name == 'nt' and is_windows_admin()):
                # Running with elevated privileges - disable sandbox for security
                settings = self.browser.settings()
                settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
            
            self.browser.setUrl(QUrl(url))
            layout.addWidget(self.browser)
        else:
            # Fallback message if QtWebEngine not available
            message = QLabel('QtWebEngine not available.\nInstall with: pip install PyQtWebEngine')
            message.setAlignment(Qt.AlignCenter)
            message.setStyleSheet("QLabel { padding: 20px; }")
            layout.addWidget(message)
            
            # Show URL
            url_label = QLabel(f'URL: {url}')
            url_label.setWordWrap(True)
            url_label.setStyleSheet("QLabel { padding: 10px; font-size: 10px; }")
            layout.addWidget(url_label)
        
        # Close button
        self.close_btn = QPushButton('Close')
        self.close_btn.clicked.connect(self.accept)
        layout.addWidget(self.close_btn)
        
        self.setLayout(layout)
        
        # Gamepad support
        self.gamepad_button_states = {}
        
        # Start gamepad timer
        self.gamepad_timer = None
        if parent and hasattr(parent, 'gamepad') and parent.gamepad:
            self.gamepad_timer = QTimer()
            self.gamepad_timer.timeout.connect(self.process_gamepad_input)
            self.gamepad_timer.start(100)
    
    def process_gamepad_input(self):
        """Handle gamepad input for browser dialog"""
        if not self.parent_window or not hasattr(self.parent_window, 'gamepad') or not self.parent_window.gamepad:
            return
        
        try:
            pygame.event.pump()
            gamepad = self.parent_window.gamepad
            
            # Button handling
            for button_id in range(min(10, gamepad.get_numbuttons())):
                is_pressed = gamepad.get_button(button_id)
                was_pressed = self.gamepad_button_states.get(button_id, False)
                
                if is_pressed and not was_pressed:
                    if button_id == 0:  # A button - Press Close
                        self.close_btn.click()
                    elif button_id == 1:  # B button - Cancel/Close
                        self.reject()
                    elif button_id == 7:  # Start button - Close
                        self.accept()
                
                self.gamepad_button_states[button_id] = is_pressed
        
        except Exception as e:
            print(f"Browser dialog gamepad error: {e}")
    
    def closeEvent(self, event):
        """Allow parent window movement and stop timer when dialog closes"""
        if self.gamepad_timer:
            self.gamepad_timer.stop()
            self.gamepad_timer = None
        if self.parent_window:
            self.parent_window.browser_dialog_open = False
        super().closeEvent(event)
    
    def accept(self):
        """Allow parent window movement and stop timer when accepting"""
        if self.gamepad_timer:
            self.gamepad_timer.stop()
            self.gamepad_timer = None
        if self.parent_window:
            self.parent_window.browser_dialog_open = False
        super().accept()
    
    def reject(self):
        """Allow parent window movement and stop timer when rejecting"""
        if self.gamepad_timer:
            self.gamepad_timer.stop()
            self.gamepad_timer = None
        if self.parent_window:
            self.parent_window.browser_dialog_open = False
        super().reject()


class ThemeDialog(QDialog):
    """Dialog for selecting application theme"""
    def __init__(self, parent=None, current_theme='light'):
        super().__init__(parent)
        self.setWindowTitle('Select Theme')
        self.setFixedSize(300, 200)
        self.parent_window = parent
        
        layout = QVBoxLayout()
        
        self.button_group = QButtonGroup()
        self.radio_buttons = []
        
        # Light theme
        light_radio = QRadioButton('Light Theme')
        light_radio.setChecked(current_theme == 'light')
        self.button_group.addButton(light_radio, 0)
        self.radio_buttons.append(light_radio)
        layout.addWidget(light_radio)
        
        # Dark theme
        dark_radio = QRadioButton('Dark Theme')
        dark_radio.setChecked(current_theme == 'dark')
        self.button_group.addButton(dark_radio, 1)
        self.radio_buttons.append(dark_radio)
        layout.addWidget(dark_radio)
        
        # Modern theme
        modern_radio = QRadioButton('Modern Theme')
        modern_radio.setChecked(current_theme == 'modern')
        self.button_group.addButton(modern_radio, 2)
        self.radio_buttons.append(modern_radio)
        layout.addWidget(modern_radio)

        # System default theme
        system_radio = QRadioButton('System Default')
        system_radio.setChecked(current_theme == 'system')
        self.button_group.addButton(system_radio, 3)
        self.radio_buttons.append(system_radio)
        layout.addWidget(system_radio)
        
        layout.addStretch()
        
        # OK button
        self.ok_button = QPushButton('Apply')
        self.ok_button.clicked.connect(self.accept)
        layout.addWidget(self.ok_button)
        
        self.setLayout(layout)
        
        # Gamepad navigation state
        self.gamepad_button_states = {}
        self.dialog_focus_index = self.button_group.checkedId()  # Start at current selection
        self.dialog_focus_on_button = False  # False = radio buttons, True = apply button
        self.last_dialog_y = 0
        
        # Highlight current selection
        if 0 <= self.dialog_focus_index < len(self.radio_buttons):
            self.radio_buttons[self.dialog_focus_index].setFocus()
            self.update_radio_highlight()
        
        # Start gamepad timer if parent has gamepad
        if parent and hasattr(parent, 'gamepad') and parent.gamepad:
            self.gamepad_timer = QTimer()
            self.gamepad_timer.timeout.connect(self.process_dialog_gamepad)
            self.gamepad_timer.start(100)
            print(f"Theme dialog gamepad timer started")
        
        # Center dialog on parent window
        if parent:
            self.center_on_parent(parent)
    
    def center_on_parent(self, parent):
        """Center dialog on parent window"""
        parent_geometry = parent.geometry()
        dialog_width = self.width()
        dialog_height = self.height()
        
        x = parent_geometry.x() + (parent_geometry.width() - dialog_width) // 2
        y = parent_geometry.y() + (parent_geometry.height() - dialog_height) // 2
        
        self.move(x, y)
    
    def get_theme(self):
        """Get selected theme"""
        themes = ['light', 'dark', 'modern', 'system']
        idx = self.button_group.checkedId()
        # Ensure index is in range
        if idx < 0 or idx >= len(themes):
            return 'light'
        return themes[idx]
    
    def update_radio_highlight(self):
        """Update the visual highlight for radio buttons based on gamepad focus"""
        # Clear all highlights
        for i, radio in enumerate(self.radio_buttons):
            if i == self.dialog_focus_index and not self.dialog_focus_on_button:
                radio.setStyleSheet("QRadioButton { background-color: rgba(255, 165, 0, 0.3); padding: 5px; border-radius: 3px; }")
            else:
                radio.setStyleSheet("")
        
        # Highlight Apply button if focused
        if self.dialog_focus_on_button:
            self.ok_button.setStyleSheet("QPushButton { background-color: rgba(255, 165, 0, 0.5); }")
        else:
            self.ok_button.setStyleSheet("")
    
    def process_dialog_gamepad(self):
        """Handle gamepad input for theme dialog"""
        if not self.parent_window or not hasattr(self.parent_window, 'gamepad') or not self.parent_window.gamepad:
            return
        
        try:
            pygame.event.pump()
            gamepad = self.parent_window.gamepad
            
            # D-pad / Left stick for navigation
            hat = gamepad.get_hat(0) if gamepad.get_numhats() > 0 else (0, 0)
            axis_y = gamepad.get_axis(1) if gamepad.get_numaxes() > 1 else 0
            current_y = hat[1] if hat[1] != 0 else (1 if axis_y < -0.5 else (-1 if axis_y > 0.5 else 0))
            
            # Track if we should process directional input
            should_navigate_up = False
            should_navigate_down = False
            
            # Check if direction changed from last frame
            if current_y != self.last_dialog_y:
                print(f"Dialog Y changed: {self.last_dialog_y} -> {current_y}")
                if current_y > 0:
                    should_navigate_up = True
                elif current_y < 0:
                    should_navigate_down = True
            self.last_dialog_y = current_y
            
            # Handle navigation
            if should_navigate_up:
                print(f"Navigating UP - focus_on_button: {self.dialog_focus_on_button}, index: {self.dialog_focus_index}")
                if self.dialog_focus_on_button:
                    # Move from Apply button to last radio button
                    self.dialog_focus_on_button = False
                    self.dialog_focus_index = len(self.radio_buttons) - 1
                    self.radio_buttons[self.dialog_focus_index].setFocus()
                    print(f"Moved to radio button {self.dialog_focus_index}")
                elif self.dialog_focus_index > 0:
                    self.dialog_focus_index -= 1
                    self.radio_buttons[self.dialog_focus_index].setFocus()
                    print(f"Moved to radio button {self.dialog_focus_index}")
                self.update_radio_highlight()
            
            elif should_navigate_down:
                print(f"Navigating DOWN - focus_on_button: {self.dialog_focus_on_button}, index: {self.dialog_focus_index}")
                if not self.dialog_focus_on_button:
                    if self.dialog_focus_index < len(self.radio_buttons) - 1:
                        self.dialog_focus_index += 1
                        self.radio_buttons[self.dialog_focus_index].setFocus()
                        print(f"Moved to radio button {self.dialog_focus_index}")
                    else:
                        # Move to Apply button
                        self.dialog_focus_on_button = True
                        self.ok_button.setFocus()
                        print(f"Moved to Apply button")
                self.update_radio_highlight()
            
            # Button handling
            for button_id in range(min(10, gamepad.get_numbuttons())):
                is_pressed = gamepad.get_button(button_id)
                was_pressed = self.gamepad_button_states.get(button_id, False)
                
                if is_pressed and not was_pressed:
                    if button_id == 0:  # A button - Select/Apply
                        if self.dialog_focus_on_button:
                            self.accept()
                        else:
                            self.radio_buttons[self.dialog_focus_index].setChecked(True)
                    
                    elif button_id == 1:  # B button - Cancel
                        self.reject()
                
                self.gamepad_button_states[button_id] = is_pressed
        
        except Exception as e:
            print(f"Dialog gamepad error: {e}")


class TaskManagerGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.data_fetcher = DataFetcher(interval_sec=4.0)
        self.current_theme = load_theme()  # Load saved theme
        
        # Track selected rows
        self.selected_pid = None
        
        # Track browser dialog state
        self.browser_dialog_open = False
        
        # Initialize gamepad support early (before initUI)
        self.gamepad = None
        self.gamepad_name = None
        self.gamepad_button_states = {}
        self.gamepad_last_axis = {'x': 0, 'y': 0}
        self.gamepad_repeat_counter = 0
        self.gamepad_repeat_delay = 3  # Initial delay before repeat (in 100ms cycles)
        self.active_menu = None  # Track active context menu
        self.gamepad_focus_mode = 'table'  # Can be 'table', 'hide_system', 'hide_inaccessible', or 'search'
        self.gamepad_input_blocked = False  # Flag to temporarily block input
        self.gamepad_input_block_timer = None  # Timer for unblocking input
        if GAMEPAD_AVAILABLE:
            try:
                # Initialize pygame for joystick support
                pygame.init()
                pygame.joystick.init()
                
                # Enable joystick events
                pygame.event.set_allowed([pygame.JOYAXISMOTION, pygame.JOYBUTTONDOWN, 
                                         pygame.JOYBUTTONUP, pygame.JOYHATMOTION])
                
                if pygame.joystick.get_count() > 0:
                    self.gamepad = pygame.joystick.Joystick(0)
                    self.gamepad.init()
                    self.gamepad_name = self.gamepad.get_name()
                    print(f"Gamepad connected: {self.gamepad_name}")
                    print(f"Gamepad details: {self.gamepad.get_numaxes()} axes, {self.gamepad.get_numbuttons()} buttons, {self.gamepad.get_numhats()} hats")
            except Exception as e:
                print(f"Gamepad initialization failed: {e}")
        
        # Initialize UI
        self.initUI()
        
        # Start gamepad timer after UI is ready
        if self.gamepad:
            self.gamepad_timer = QTimer()
            self.gamepad_timer.timeout.connect(self.process_gamepad_input)
            self.gamepad_timer.start(250)  # Poll gamepad every 250ms (reduced for CPU efficiency)
        
        # Timer for auto-refresh
        self.timer = QTimer()
        self.timer.timeout.connect(self.request_data_update)
        self.timer.start(2000)  # Update every 2 seconds to reduce CPU usage ~50%
        
        # Cached latest fetched data to allow fast local filtering (search/hide)
        self._cached_processes = []
        self._last_mem_info = None
        # Track last rendered rows for diff-based table updates
        self._last_rendered = []
        # Debounce timer for search input to make typing feel responsive
        self._search_debounce_timer = QTimer()
        self._search_debounce_timer.setSingleShot(True)
        self._search_debounce_timer.setInterval(200)  # ms
        self._search_debounce_timer.timeout.connect(self._apply_search_filter)
        # UI coalescing timer: batch rapid data_ready calls into a single UI update
        self._ui_update_timer = QTimer()
        self._ui_update_timer.setSingleShot(True)
        self._ui_update_timer.setInterval(20)  # ms; small delay to coalesce bursts (reduced for snappier UI)
        self._ui_update_timer.timeout.connect(self._flush_ui_update)
        # Pending render parameters (set by _apply_search_filter)
        self._pending_render_mem_info = None
        self._pending_render_processes = None
        self._pending_total_processes = 0
        # User scrolling detection: postpone rendering while user scrolls
        self._user_scrolling = False
        self._scroll_inactive_timer = QTimer()
        self._scroll_inactive_timer.setSingleShot(True)
        self._scroll_inactive_timer.setInterval(300)  # ms of idle before considered stopped
        self._scroll_inactive_timer.timeout.connect(self._on_scroll_stopped)
        # Background filler: populate off-screen rows progressively to keep UI responsive
        self._bg_fill_timer = QTimer()
        self._bg_fill_timer.setSingleShot(False)
        self._bg_fill_timer.setInterval(80)  # ms between background batches
        self._bg_fill_timer.timeout.connect(self._bg_fill_step)
        self._pending_offscreen_fill = []  # list of (row, proc)
        # Window move optimization: pause heavy UI updates while the window is being moved
        self._window_moving = False
        self._bg_fill_was_active = False
        self._ui_update_was_active = False
        self._move_idle_timer = QTimer()
        self._move_idle_timer.setSingleShot(True)
        self._move_idle_timer.setInterval(300)  # ms of idle after move before resuming updates
        self._move_idle_timer.timeout.connect(self._on_move_stopped)
    
    def initUI(self):
        """Initialize the user interface"""
        self.setWindowTitle('Task Manager - System Monitor')
        self.setGeometry(100, 100, 1400, 900)
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QVBoxLayout()
        
        # Title
        title = QLabel('Task Manager - System Resource Monitor')
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title.setFont(title_font)
        main_layout.addWidget(title)
        
        # System memory section
        memory_layout = QHBoxLayout()
        
        # Total RAM
        total_label = QLabel('Total RAM:')
        total_label.setStyleSheet("font-weight: bold;")
        self.total_ram_label = QLabel()
        memory_layout.addWidget(total_label)
        memory_layout.addWidget(self.total_ram_label)
        memory_layout.addSpacing(30)
        
        # Used RAM
        used_label = QLabel('Used RAM:')
        used_label.setStyleSheet("font-weight: bold;")
        self.used_ram_label = QLabel()
        memory_layout.addWidget(used_label)
        memory_layout.addWidget(self.used_ram_label)
        memory_layout.addSpacing(30)
        
        # Available RAM
        available_label = QLabel('Available RAM:')
        available_label.setStyleSheet("font-weight: bold;")
        self.available_ram_label = QLabel()
        memory_layout.addWidget(available_label)
        memory_layout.addWidget(self.available_ram_label)
        memory_layout.addStretch()
        
        main_layout.addLayout(memory_layout)
        
        # Memory progress bar
        bar_layout = QHBoxLayout()
        bar_label = QLabel('Memory Usage:')
        bar_label.setStyleSheet("font-weight: bold;")
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(100)
        self.progress_label = QLabel()
        bar_layout.addWidget(bar_label)
        bar_layout.addWidget(self.progress_bar, 1)
        bar_layout.addWidget(self.progress_label)
        
        # Run as Admin button (Windows) / Run as Sudo (POSIX)
        self.sudo_button = QPushButton('Run as Admin')
        self.sudo_button.clicked.connect(self.run_with_sudo)
        self.sudo_button.setMaximumWidth(120)
        bar_layout.addWidget(self.sudo_button)
        
        # Theme button
        self.theme_button = QPushButton('Theme')
        self.theme_button.clicked.connect(self.open_theme_dialog)
        self.theme_button.setMaximumWidth(80)
        bar_layout.addWidget(self.theme_button)
        
        main_layout.addLayout(bar_layout)
        
        # Search bar
        search_layout = QHBoxLayout()
        search_label = QLabel('Search:')
        search_label.setStyleSheet("font-weight: bold;")
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('Type to filter processes...')
        self.search_input.textChanged.connect(self.on_search_changed)
        self.search_input.setMaximumWidth(300)
        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_input)
        search_layout.addStretch()
        main_layout.addLayout(search_layout)
        
        # Processes table
        table_title = QLabel('Running Processes (sorted by RAM usage)')
        table_title_font = QFont()
        table_title_font.setPointSize(12)
        table_title_font.setBold(True)
        table_title.setFont(table_title_font)
        main_layout.addWidget(table_title)
        
        # Create table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(['PID', 'User', 'Process Name', 'CPU (%)', 'RAM (MB)', 'RAM (%)', 'Disk I/O (MB)'])
        
        # Install event filter to catch key presses
        self.table.installEventFilter(self)
        
        # Enable right-click context menu
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        
        # Configure table
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)  # Ctrl/Shift for multi-select
        self.table.verticalScrollBar().setSingleStep(3)  # Faster scrolling
        self.table.verticalScrollBar().setPageStep(10)
        # Improve rendering performance for uniform rows
        try:
            self.table.setUniformRowHeights(True)
        except Exception:
            pass
        # Connect scrollbar activity to detect user scrolling
        try:
            self.table.verticalScrollBar().valueChanged.connect(self._on_user_scrolled)
        except Exception:
            pass
        self.table.setStyleSheet("""
            QTableWidget {
                alternate-background-color: #f0f0f0;
                background-color: #ffffff;
                gridline-color: #d0d0d0;
            }
            QHeaderView::section {
                background-color: #2c3e50;
                color: white;
                padding: 4px;
                border: none;
                font-weight: bold;
            }
            QScrollBar:vertical {
                width: 12px;
            }
            QScrollBar::handle:vertical {
                background: #888;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: #555;
            }
        """)
        
        main_layout.addWidget(self.table)

        # System info area (directly below table) - GPU, checkbox, OS, CPU all in one row
        system_info_layout = QHBoxLayout()
        gpu_label = QLabel('GPU:')
        gpu_label.setStyleSheet("font-weight: bold;")
        self.gpu_name_label = QLabel('Detecting...')
        system_info_layout.addWidget(gpu_label)
        system_info_layout.addWidget(self.gpu_name_label)
        system_info_layout.addSpacing(20)
        driver_label = QLabel('Driver:')
        driver_label.setStyleSheet("font-weight: bold;")
        self.gpu_driver_label = QLabel('Detecting...')
        system_info_layout.addWidget(driver_label)
        system_info_layout.addWidget(self.gpu_driver_label)
        self.hide_system_checkbox = QCheckBox('Hide system processes')
        self.hide_system_checkbox.setChecked(load_hide_system_processes())
        self.hide_system_checkbox.stateChanged.connect(self.on_hide_system_changed)
        self.hide_system_checkbox.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.hide_system_checkbox.setMaximumWidth(170)
        self.hide_system_checkbox.setFixedHeight(self.gpu_driver_label.sizeHint().height())
        self.hide_system_checkbox.setContentsMargins(0, 0, 0, 0)
        self.hide_system_checkbox.installEventFilter(self)
        system_info_layout.addSpacing(20)
        system_info_layout.addWidget(self.hide_system_checkbox, 0, Qt.AlignLeft)
        
        self.hide_inaccessible_checkbox = QCheckBox('Hide inaccessible processes')
        self.hide_inaccessible_checkbox.setChecked(load_hide_inaccessible_processes())
        self.hide_inaccessible_checkbox.stateChanged.connect(self.on_hide_inaccessible_changed)
        self.hide_inaccessible_checkbox.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.hide_inaccessible_checkbox.setMaximumWidth(200)
        self.hide_inaccessible_checkbox.setFixedHeight(self.gpu_driver_label.sizeHint().height())
        self.hide_inaccessible_checkbox.setContentsMargins(0, 0, 0, 0)
        self.hide_inaccessible_checkbox.installEventFilter(self)
        system_info_layout.addSpacing(20)
        system_info_layout.addWidget(self.hide_inaccessible_checkbox, 0, Qt.AlignLeft)
        system_info_layout.addStretch()
        os_label_title = QLabel('OS:')
        os_label_title.setStyleSheet("font-weight: bold;")
        self.os_label = QLabel('Detecting...')
        system_info_layout.addWidget(os_label_title)
        system_info_layout.addWidget(self.os_label)
        system_info_layout.addSpacing(20)
        cpu_label_title = QLabel('CPU:')
        cpu_label_title.setStyleSheet("font-weight: bold;")
        self.cpu_label = QLabel('Detecting...')
        system_info_layout.addWidget(cpu_label_title)
        system_info_layout.addWidget(self.cpu_label)
        main_layout.addLayout(system_info_layout)

        # Status bar with controller label (clickable)
        self.controller_label = ClickableLabel('')
        self.controller_label.setStyleSheet("QLabel { color: blue; text-decoration: underline; }")
        self.controller_label.setCursor(Qt.PointingHandCursor)
        self.controller_label.parent_callback = self.open_controller_test
        self.statusBar().addPermanentWidget(self.controller_label)
        self.statusBar().showMessage('Loading...')
        
        central_widget.setLayout(main_layout)
        
        # Apply initial theme
        self.apply_theme(self.current_theme)

        # Detect and display GPU info
        try:
            gpu = detect_gpu_info()
            self.gpu_name_label.setText(gpu.get('name', 'Unknown'))
            self.gpu_driver_label.setText(gpu.get('driver', 'Unknown'))
        except Exception:
            self.gpu_name_label.setText('Unknown')
            self.gpu_driver_label.setText('Unknown')

        # Detect and display OS info
        try:
            os_name = detect_os_name()
            self.os_label.setText(f"OS: {os_name}")
        except Exception:
            self.os_label.setText('OS: Unknown')

        # Detect and display CPU info
        try:
            cpu_name = detect_cpu_name()
            self.cpu_label.setText(f"CPU: {cpu_name}")
        except Exception:
            self.cpu_label.setText('CPU: Unknown')
        
        # Display controller info
        if hasattr(self, 'gamepad_name') and self.gamepad_name:
            self.controller_label.setText(f"Controller: {self.gamepad_name}")
        else:
            self.controller_label.setText('')
        
        # Connect data fetcher signal
        self.data_fetcher.data_ready.connect(self.on_data_ready)
        # Start persistent fetcher thread
        self.data_fetcher.start()
        # Trigger initial fetch
        self.request_data_update()
        
        # Connect table selection signal
        self.table.itemSelectionChanged.connect(self.on_selection_changed)
    
    def run_with_sudo(self):
        """Restart the application with sudo privileges and close current window"""
        script_path = os.path.abspath(__file__)
        my_pid = os.getpid()

        # Windows elevation path: use ShellExecute with the 'runas' verb to request elevation
        if os.name == 'nt':
            if is_windows_admin():
                QMessageBox.information(self, "Info", "Already running with Administrator privileges!")
                return
            try:
                # Build argument string to pass the script path and an indicator that it was elevated
                arg_str = f'"{script_path}" --elevated-from {my_pid}'
                # Use ShellExecuteW to request elevation (returns >32 on success)
                ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, arg_str, None, 1)
                if int(ret) <= 32:
                    raise OSError(f"ShellExecuteW failed with code {ret}")
                self.statusBar().showMessage('Launching elevated instance...')
                QTimer.singleShot(1000, lambda: self.check_elevated_started(my_pid))
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to request elevation: {str(e)}")
            return

        # POSIX sudo path
        if hasattr(os, 'geteuid') and os.geteuid() == 0:
            QMessageBox.information(self, "Info", "Already running with sudo privileges!")
            return

        try:
            subprocess.Popen(['sudo', sys.executable, script_path, '--elevated-from', str(my_pid)])
            self.statusBar().showMessage('Launching sudo instance...')
            # Start checking for elevated process
            QTimer.singleShot(1000, lambda: self.check_elevated_started(my_pid))
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to run with sudo: {str(e)}")
    
    def check_elevated_started(self, original_pid, attempts=0):
        """Check if elevated instance has started and close this window"""
        try:
            # Look for task_manager processes running with elevated privileges
            script_name = os.path.basename(__file__)
            python_name = os.path.basename(sys.executable)
            
            for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'username']):
                try:
                    cmdline = proc.info.get('cmdline', [])
                    pid = proc.info['pid']
                    name = proc.info.get('name', '')
                    username = proc.info.get('username', '')
                    
                    # Check if this is a Python process running our script
                    if python_name in name and cmdline and any(script_name in str(cmd) for cmd in cmdline):
                        # Check if it's a different process with elevated privileges
                        if pid != original_pid:
                            # On POSIX, check if running as root
                            if hasattr(os, 'geteuid'):
                                if username in ['root', 'SYSTEM']:
                                    QTimer.singleShot(200, lambda: QApplication.quit())
                                    return
                            else:
                                # On Windows, just check if it's a different instance
                                QTimer.singleShot(200, lambda: QApplication.quit())
                                return
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                
        except Exception as e:
            pass
        
        if attempts < 20:  # Check for up to 10 seconds
            QTimer.singleShot(500, lambda: self.check_elevated_started(original_pid, attempts + 1))

    def on_hide_system_changed(self, state):
        """Handle hide system processes checkbox state change"""
        save_hide_system_processes(self.hide_system_checkbox.isChecked())
        # If we have cached data, just re-apply filters locally for responsiveness
        if self._last_mem_info is not None:
            self._apply_search_filter()
        else:
            self.request_data_update()
    
    def on_hide_inaccessible_changed(self, state):
        """Handle hide inaccessible processes checkbox state change"""
        save_hide_inaccessible_processes(self.hide_inaccessible_checkbox.isChecked())
        # If we have cached data, just re-apply filters locally for responsiveness
        if self._last_mem_info is not None:
            self._apply_search_filter()
        else:
            self.request_data_update()
    
    def on_search_changed(self, text):
        """Handle search input text change"""
        # Debounce and, if we have cached data, filter locally for snappy typing
        if self._last_mem_info is None:
            # No data yet: request initial fetch
            self.request_data_update()
            return

        # Restart debounce timer
        self._search_debounce_timer.start()

    def _apply_search_filter(self):
        """Apply current search and hide filters to cached processes and update UI."""
        if self._last_mem_info is None:
            return

        # Start from the full cached process list (as received from fetcher)
        processes = list(self._cached_processes)

        total_processes = len(processes)

        # Apply system-process filter if enabled
        if self.hide_system_checkbox.isChecked():
            processes = [p for p in processes if not self.is_system_process(p)]

        # Apply inaccessible-process filter if enabled
        if self.hide_inaccessible_checkbox.isChecked():
            processes = [p for p in processes if not self.is_inaccessible_process(p)]

        # Apply search filter if search text is entered
        search_text = self.search_input.text().strip().lower()
        if search_text:
            processes = [p for p in processes if search_text in p.get('name', '').lower()]

        # Schedule the (filtered) processes to be rendered by the UI coalescer
        self._pending_render_mem_info = self._last_mem_info
        self._pending_render_processes = processes
        self._pending_total_processes = total_processes
        # Restart the UI update timer (coalesce multiple rapid updates)
        try:
            if self._ui_update_timer.isActive():
                self._ui_update_timer.stop()
        except Exception:
            pass
        self._ui_update_timer.start()
    
    @staticmethod
    def is_inaccessible_process(proc: dict) -> bool:
        """Check if process has an inaccessible executable path."""
        pid = proc.get('pid', -1)
        try:
            process = psutil.Process(pid)
            exe_path = process.exe()
            if not exe_path or not os.path.exists(exe_path):
                return True
            directory = os.path.dirname(exe_path)
            return not os.access(directory, os.R_OK)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            return True
        return False
    
    @staticmethod
    def is_system_process(proc: dict) -> bool:
        """Heuristic to detect system processes for filtering."""
        pid = proc.get('pid', -1)
        user = (proc.get('username') or '').lower()
        system_users = {
            'root',
            'system',
            'local system',
            'nt authority\\system',
            'nt authority\\localservice',
            'nt authority\\networkservice',
            'localservice',
            'networkservice'
        }
        if pid in (0, 1, 2):
            return True
        if user in system_users:
            return True
        return False
    
    def open_controller_test(self):
        """Open controller test dialog"""
        if self.gamepad:
            # Disable main window gamepad input
            self.gamepad_input_blocked = True
            dialog = ControllerTestDialog(self)
            dialog.exec_()
            # Re-enable main window gamepad input and block briefly
            self.gamepad_input_blocked = False
            self.block_gamepad_input(500)
    
    def open_theme_dialog(self):
        """Open theme selection dialog"""
        dialog = ThemeDialog(self, self.current_theme)
        if dialog.exec_() == QDialog.Accepted:
            new_theme = dialog.get_theme()
            if new_theme != self.current_theme:
                self.current_theme = new_theme
                save_theme(new_theme)  # Save theme to config
                self.apply_theme(new_theme)
        # Block gamepad input temporarily after dialog closes
        self.block_gamepad_input(500)  # Block for 500ms
    
    def open_virtual_keyboard(self):
        """Open virtual keyboard for search input"""
        current_text = self.search_input.text()
        dialog = VirtualKeyboard(self, current_text)
        if dialog.exec_() == QDialog.Accepted:
            new_text = dialog.get_text()
            self.search_input.setText(new_text)
            # Return focus to table after keyboard closes
            self.gamepad_focus_mode = 'table'
            if self.table.rowCount() > 0:
                self.table.setCurrentCell(0, 0)
                self.table.setFocus()
        # Block gamepad input temporarily after keyboard closes
        self.block_gamepad_input(500)  # Block for 500ms
    
    def block_gamepad_input(self, duration_ms):
        """Temporarily block gamepad input for specified duration"""
        print(f"Blocking gamepad input for {duration_ms}ms")
        self.gamepad_input_blocked = True
        # Mark all buttons as currently pressed to prevent immediate re-trigger
        if self.gamepad:
            for button_id in range(min(10, self.gamepad.get_numbuttons())):
                self.gamepad_button_states[button_id] = True
        self.gamepad_last_axis = {'x': 0, 'y': 0}
        self.gamepad_repeat_counter = 0
        # Cancel existing timer if any
        if self.gamepad_input_block_timer:
            self.gamepad_input_block_timer.stop()
        # Create new timer to unblock input
        self.gamepad_input_block_timer = QTimer()
        self.gamepad_input_block_timer.setSingleShot(True)
        self.gamepad_input_block_timer.timeout.connect(self.unblock_gamepad_input)
        self.gamepad_input_block_timer.start(duration_ms)
    
    def unblock_gamepad_input(self):
        """Unblock gamepad input"""
        print("Unblocking gamepad input")
        # Update button states to current reality before unblocking
        if self.gamepad:
            pygame.event.pump()
            for button_id in range(min(10, self.gamepad.get_numbuttons())):
                self.gamepad_button_states[button_id] = self.gamepad.get_button(button_id)
        self.gamepad_input_blocked = False
        self.gamepad_last_axis = {'x': 0, 'y': 0}
        self.gamepad_repeat_counter = 0
    
    def apply_theme(self, theme_name: str):
        """Apply the selected theme to the application"""
        # If the user selected the explicit 'system' option, resolve it now
        if theme_name == 'system':
            resolved = detect_system_theme()
            # Fall back to light if detection fails
            theme_name = resolved if resolved in ('dark', 'light') else 'light'

        if theme_name == 'light':
            self.apply_light_theme()
        elif theme_name == 'dark':
            self.apply_dark_theme()
        elif theme_name == 'modern':
            self.apply_modern_theme()
    
    def apply_light_theme(self):
        """Apply light theme"""
        stylesheet = """
            QMainWindow {
                background-color: #ffffff;
            }
            QTableWidget {
                alternate-background-color: #f0f0f0;
                background-color: #ffffff;
                gridline-color: #d0d0d0;
                color: #000000;
            }
            QTableWidget::item {
                color: #000000;
                background-color: #ffffff;
                padding: 2px;
            }
            QTableWidget::item:alternate {
                background-color: #f0f0f0;
            }
            QTableWidget::item:selected {
                background-color: #3daee9;
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #2c3e50;
                color: white;
                padding: 4px;
                border: none;
                font-weight: bold;
            }
            QLabel {
                color: #000000;
            }
            QCheckBox {
                color: #000000;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border: 1px solid #7f8c8d;
                background: #ffffff;
            }
            QCheckBox::indicator:checked {
                background: #2c3e50;
            }
            QCheckBox[gamepadFocus="true"] {
                background-color: rgba(61, 174, 233, 0.3);
                border: 2px solid #3daee9;
                border-radius: 3px;
                padding: 2px;
            }
            QPushButton {
                background-color: #2c3e50;
                color: white;
                border: none;
                padding: 5px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #34495e;
            }
            QProgressBar {
                color: #000000;
            }
            QScrollBar:vertical {
                background-color: #f5f5f5;
                width: 12px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background-color: #2c3e50;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #34495e;
            }
            QScrollBar::sub-line:vertical, QScrollBar::add-line:vertical {
                border: none;
                background: none;
            }
            QMenu {
                background-color: #ffffff;
                color: #000000;
                border: 1px solid #d0d0d0;
            }
            QMenu::item:selected {
                background-color: #3daee9;
                color: #ffffff;
            }
            QMenu::item:hover {
                background-color: #3daee9;
                color: #ffffff;
            }
        """
        self.setStyleSheet(stylesheet)
    
    def apply_dark_theme(self):
        """Apply dark theme"""
        stylesheet = """
            QMainWindow {
                background-color: #1e1e1e;
                color: #ffffff;
            }
            QTableWidget {
                alternate-background-color: #2d2d2d;
                background-color: #252525;
                gridline-color: #3d3d3d;
                color: #ffffff;
            }
            QTableWidget::item {
                color: #ffffff;
                background-color: #252525;
                padding: 2px;
            }
            QTableWidget::item:alternate {
                background-color: #2d2d2d;
            }
            QTableWidget::item:selected {
                background-color: #ff6f00;
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #0d47a1;
                color: white;
                padding: 4px;
                border: none;
                font-weight: bold;
            }
            QLabel {
                color: #ffffff;
            }
            QCheckBox {
                color: #ffffff;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border: 1px solid #5d5d5d;
                background: #1e1e1e;
            }
            QCheckBox::indicator:checked {
                background: #0d47a1;
            }
            QCheckBox[gamepadFocus="true"] {
                background-color: rgba(255, 111, 0, 0.3);
                border: 2px solid #ff6f00;
                border-radius: 3px;
                padding: 2px;
            }
            QPushButton {
                background-color: #0d47a1;
                color: white;
                border: none;
                padding: 5px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #1565c0;
            }
            QProgressBar {
                background-color: #2d2d2d;
                color: #ffffff;
                border: 1px solid #3d3d3d;
            }
            QProgressBar::chunk {
                background-color: #1976d2;
            }
            QDialog {
                background-color: #1e1e1e;
                color: #ffffff;
            }
            QRadioButton {
                color: #ffffff;
            }
            QMessageBox {
                background-color: #1e1e1e;
            }
            QMessageBox QLabel {
                color: #ffffff;
            }
            QStatusBar {
                background-color: #1e1e1e;
                color: #ffffff;
            }
            QStatusBar QLabel {
                color: #ffffff;
            }
            QScrollBar:vertical {
                background-color: #252525;
                width: 12px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background-color: #0d47a1;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #1565c0;
            }
            QScrollBar::sub-line:vertical, QScrollBar::add-line:vertical {
                border: none;
                background: none;
            }
            QMenu {
                background-color: #2d2d2d;
                color: #ffffff;
                border: 1px solid #3d3d3d;
            }
            QMenu::item:selected {
                background-color: #ff6f00;
                color: #ffffff;
            }
            QMenu::item:hover {
                background-color: #ff6f00;
                color: #ffffff;
            }
        """
        self.setStyleSheet(stylesheet)
    
    def apply_modern_theme(self):
        """Apply modern theme"""
        stylesheet = """
            QMainWindow {
                background-color: #f5f5f5;
                color: #212121;
            }
            QTableWidget {
                alternate-background-color: #eeeeee;
                background-color: #ffffff;
                gridline-color: #e0e0e0;
                color: #212121;
            }
            QTableWidget::item {
                color: #212121;
                background-color: #ffffff;
                padding: 2px;
            }
            QTableWidget::item:alternate {
                background-color: #eeeeee;
            }
            QTableWidget::item:selected {
                background-color: #ff6f00;
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #ff6f00;
                color: white;
                padding: 4px;
                border: none;
                font-weight: bold;
            }
            QLabel {
                color: #212121;
            }
            QCheckBox {
                color: #212121;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border: 1px solid #bdbdbd;
                background: #ffffff;
            }
            QCheckBox::indicator:checked {
                background: #ff6f00;
                border-color: #ff6f00;
            }
            QCheckBox[gamepadFocus="true"] {
                background-color: rgba(255, 111, 0, 0.3);
                border: 2px solid #ff6f00;
                border-radius: 3px;
                padding: 2px;
            }
            QPushButton {
                background-color: #ff6f00;
                color: white;
                border: none;
                padding: 6px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #ff8f00;
            }
            QProgressBar {
                background-color: #eeeeee;
                color: #212121;
                border-radius: 3px;
                border: 1px solid #e0e0e0;
            }
            QProgressBar::chunk {
                background-color: #4caf50;
                border-radius: 3px;
            }
            QDialog {
                background-color: #f5f5f5;
                color: #212121;
            }
            QRadioButton {
                color: #212121;
            }
            QScrollBar:vertical {
                background-color: #eeeeee;
                width: 12px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background-color: #ff6f00;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #ff8f00;
            }
            QScrollBar::sub-line:vertical, QScrollBar::add-line:vertical {
                border: none;
                background: none;
            }
            QMenu {
                background-color: #ffffff;
                color: #212121;
                border: 1px solid #e0e0e0;
            }
            QMenu::item:selected {
                background-color: #ff6f00;
                color: #ffffff;
            }
            QMenu::item:hover {
                background-color: #ff8f00;
                color: #ffffff;
            }
        """
        self.setStyleSheet(stylesheet)
    
    def on_selection_changed(self):
        """Track when rows are selected"""
        selected_items = self.table.selectedItems()
        if selected_items:
            # Get unique PIDs from selected rows
            pids = set()
            for item in selected_items:
                row = item.row()
                pid_item = self.table.item(row, 0)
                if pid_item:
                    try:
                        pids.add(int(pid_item.text()))
                    except ValueError:
                        pass
            self.selected_pid = pids if pids else None
        else:
            self.selected_pid = None
    
    def show_context_menu(self, position: QPoint):
        """Show right-click context menu"""
        row = self.table.rowAt(position.y())
        if row < 0:
            return
        
        # Get selected PIDs
        selected_items = self.table.selectedItems()
        if not selected_items:
            return
        
        selected_pids = {}
        for item in selected_items:
            row = item.row()
            pid_item = self.table.item(row, 0)
            name_item = self.table.item(row, 2)  # Process name is column 2 now
            if pid_item and name_item:
                try:
                    pid = int(pid_item.text())
                    name = name_item.text()
                    selected_pids[pid] = name
                except ValueError:
                    pass
        
        if not selected_pids:
            return
        
        # Create context menu
        menu = QMenu(self)
        count = len(selected_pids)
        if count == 1:
            name = list(selected_pids.values())[0]
            pid = list(selected_pids.keys())[0]
            kill_action = menu.addAction(f"End Task: {name}")
            open_location_action = menu.addAction("Open File Location")
            lookup_action = menu.addAction("Lookup Process")
            
            # Connect actions
            kill_action.triggered.connect(lambda: self.kill_processes(selected_pids))
            open_location_action.triggered.connect(lambda: self.open_file_location(pid))
            lookup_action.triggered.connect(lambda: self.lookup_process(name))
        else:
            kill_action = menu.addAction(f"End {count} Tasks")
            open_location_action = menu.addAction(f"Open {count} File Locations")
            
            # Connect actions
            kill_action.triggered.connect(lambda: self.kill_processes(selected_pids))
            open_location_action.triggered.connect(lambda: self.open_multiple_file_locations(selected_pids))
        
        # Set first action as active for gamepad
        menu.setActiveAction(kill_action)
        
        # Track menu for gamepad navigation
        self.active_menu = menu
        self.active_menu_pids = selected_pids
        
        # Show menu (non-blocking for gamepad support)
        menu.popup(self.table.mapToGlobal(position))
        
        # Clear active menu when it closes
        menu.aboutToHide.connect(lambda: self.clear_active_menu())
    
    def clear_active_menu(self):
        """Clear the active menu reference"""
        self.active_menu = None
        self.active_menu_pids = None
    
    def open_file_location(self, pid: int):
        """Open the file location of a process"""
        try:
            proc = psutil.Process(pid)
            exe_path = proc.exe()
            if not exe_path or not os.path.exists(exe_path):
                QMessageBox.warning(self, "Error", "Cannot locate executable path for this process.")
                return
            
            directory = os.path.dirname(exe_path)
            
            # Cross-platform directory opening
            if os.name == 'nt':  # Windows
                # Use start command with /B to avoid new window, handle paths with spaces
                subprocess.Popen(f'explorer /select,"{exe_path}"', shell=True)
            elif sys.platform == 'darwin':  # macOS
                subprocess.Popen(['open', '-R', exe_path])
            else:  # Linux
                # Suppress stderr to avoid net usershare errors and try multiple file managers
                try:
                    subprocess.Popen(['xdg-open', directory], stderr=subprocess.DEVNULL)
                except Exception:
                    # Fallback to common file managers
                    for fm in ['nautilus', 'dolphin', 'thunar', 'nemo', 'caja']:
                        if shutil.which(fm):
                            subprocess.Popen([fm, directory], stderr=subprocess.DEVNULL)
                            break
            
            self.statusBar().showMessage(f"Opened location: {directory}")
        except psutil.NoSuchProcess:
            QMessageBox.warning(self, "Error", "Process no longer exists.")
        except psutil.AccessDenied:
            QMessageBox.warning(self, "Error", "Access denied. Cannot access process executable path.")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to open file location: {str(e)}")
    
    def open_multiple_file_locations(self, pids_dict: dict):
        """Open file locations for multiple processes"""
        opened = []
        failed = []
        access_denied = []
        unique_dirs = set()
        
        for pid, name in pids_dict.items():
            try:
                proc = psutil.Process(pid)
                exe_path = proc.exe()
                if not exe_path or not os.path.exists(exe_path):
                    failed.append(f"{name} (PID: {pid})")
                    continue
                
                directory = os.path.dirname(exe_path)
                
                # Skip if directory already opened
                if directory in unique_dirs:
                    continue
                unique_dirs.add(directory)
                
                # Cross-platform directory opening
                if os.name == 'nt':  # Windows
                    subprocess.Popen(f'explorer /select,"{exe_path}"', shell=True)
                elif sys.platform == 'darwin':  # macOS
                    subprocess.Popen(['open', '-R', exe_path])
                else:  # Linux
                    try:
                        subprocess.Popen(['xdg-open', directory], stderr=subprocess.DEVNULL)
                    except Exception:
                        for fm in ['nautilus', 'dolphin', 'thunar', 'nemo', 'caja']:
                            if shutil.which(fm):
                                subprocess.Popen([fm, directory], stderr=subprocess.DEVNULL)
                                break
                
                opened.append(directory)
            except psutil.NoSuchProcess:
                failed.append(f"{name} (PID: {pid})")
            except psutil.AccessDenied:
                access_denied.append(f"{name} (PID: {pid})")
            except Exception as e:
                failed.append(f"{name} (PID: {pid}): {str(e)}")
        
        # Show status message
        if opened:
            self.statusBar().showMessage(f"Opened {len(opened)} location(s)")
        
        # Show warnings if there were issues
        if access_denied or failed:
            msg = ""
            if access_denied:
                msg += f"Access denied for:\n" + "\n".join(access_denied) + "\n\n"
            if failed:
                msg += f"Failed to open location for:\n" + "\n".join(failed)
            QMessageBox.warning(self, "Error", msg.strip())
    
    def lookup_process(self, process_name: str):
        """Search for process information on Google in embedded browser"""
        try:
            # Detect operating system
            if os.name == 'nt':
                os_name = 'Windows'
            elif sys.platform == 'darwin':
                os_name = 'macOS'
            else:
                os_name = 'Linux'
            
            # Create search query with process name, "process", and OS
            search_query = f"{process_name} process {os_name}"
            encoded_query = urllib.parse.quote(search_query)
            search_url = f"https://www.google.com/search?q={encoded_query}"
            
            if WEBENGINE_AVAILABLE:
                # Open in embedded browser dialog
                dialog = BrowserDialog(self, search_url)
                dialog.exec_()
            else:
                # Fallback to external browser
                webbrowser.open(search_url)
                QMessageBox.information(self, "Info", 
                    "QtWebEngine not available. Opened in external browser.\n\n"
                    "To enable embedded browser, install:\n"
                    "pip install PyQtWebEngine")
            
            self.statusBar().showMessage(f"Opened search for: {process_name}")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to open browser: {str(e)}")
    
    def kill_process(self, pid: int, process_name: str):
        """Kill a process by PID"""
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            self.statusBar().showMessage(f"Terminated process: {process_name} (PID: {pid})")
        except psutil.NoSuchProcess:
            QMessageBox.warning(self, "Error", f"Process {process_name} (PID: {pid}) no longer exists")
        except psutil.AccessDenied:
            QMessageBox.warning(self, "Error", f"Access denied. Cannot terminate {process_name}.\nYou may need to run with sudo.")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to terminate {process_name}: {str(e)}")
    
    def kill_processes(self, pids_dict: dict):
        """Kill multiple processes by PID"""
        failed = []
        access_denied = []
        terminated = []
        
        for pid, name in pids_dict.items():
            try:
                proc = psutil.Process(pid)
                proc.terminate()
                terminated.append(f"{name} (PID: {pid})")
            except psutil.NoSuchProcess:
                pass  # Process already gone
            except psutil.AccessDenied:
                access_denied.append(f"{name} (PID: {pid})")
            except Exception as e:
                failed.append(f"{name} (PID: {pid}): {str(e)}")
        
        # Show status message
        if terminated:
            self.statusBar().showMessage(f"Terminated {len(terminated)} process(es)")
        
        # Show warnings if there were issues
        if access_denied or failed:
            msg = ""
            if access_denied:
                msg += f"Access denied for:\n" + "\n".join(access_denied) + "\n\nYou may need to run with sudo.\n\n"
            if failed:
                msg += f"Failed to terminate:\n" + "\n".join(failed)
            QMessageBox.warning(self, "Error", msg.strip())
    
    def process_gamepad_input(self):
        """Process gamepad input and convert to keyboard/mouse events"""
        if not self.gamepad:
            return
        
        # Block input if flag is set
        if hasattr(self, 'gamepad_input_blocked') and self.gamepad_input_blocked:
            return
        
        try:
            # Process all pygame events to update joystick state
            events = pygame.event.get()
            if not events:
                pygame.event.pump()  # Only pump if no events to process
            
            # Handle menu navigation if a menu is active
            if self.active_menu and self.active_menu.isVisible():
                self.process_menu_navigation()
                return
            
            # D-pad / Left stick for navigation with continuous input
            hat = self.gamepad.get_hat(0) if self.gamepad.get_numhats() > 0 else (0, 0)
            axis_x = self.gamepad.get_axis(0) if self.gamepad.get_numaxes() > 0 else 0
            axis_y = self.gamepad.get_axis(1) if self.gamepad.get_numaxes() > 1 else 0
            
            # Trigger axes for fast scrolling (LT = axis 2, RT = axis 5 on Xbox controllers)
            trigger_left = self.gamepad.get_axis(2) if self.gamepad.get_numaxes() > 2 else -1
            trigger_right = self.gamepad.get_axis(5) if self.gamepad.get_numaxes() > 5 else -1
            
            # Check if axis moved significantly from last position
            # Invert axis_y: negative values mean up, positive means down
            current_y = hat[1] if hat[1] != 0 else (1 if axis_y < -0.5 else (-1 if axis_y > 0.5 else 0))
            current_x = hat[0] if hat[0] != 0 else (-1 if axis_x < -0.5 else (1 if axis_x > 0.5 else 0))
            
            # If direction changed or stopped, reset counter
            if current_y != self.gamepad_last_axis['y'] or current_x != self.gamepad_last_axis['x']:
                self.gamepad_repeat_counter = 0
                self.gamepad_last_axis['y'] = current_y
                self.gamepad_last_axis['x'] = current_x
            
            # Navigate if direction is held
            if current_y != 0 or current_x != 0:
                # Initial press or repeat after delay
                if self.gamepad_repeat_counter == 0 or self.gamepad_repeat_counter >= self.gamepad_repeat_delay:
                    if current_y > 0:
                        # Navigate up
                        if self.gamepad_focus_mode == 'table':
                            current_row = self.table.currentRow()
                            if current_row > 0:
                                self.table.setCurrentCell(current_row - 1, 0)
                            else:
                                # At top of table, move to search box and open virtual keyboard
                                self.gamepad_focus_mode = 'search'
                                self.table.clearSelection()
                                self.search_input.clear()
                                self.search_input.setFocus()
                                self.open_virtual_keyboard()
                        elif self.gamepad_focus_mode == 'search':
                            # Move to hide_inaccessible checkbox
                            self.gamepad_focus_mode = 'hide_inaccessible'
                            self.hide_inaccessible_checkbox.setProperty('gamepadFocus', True)
                            self.hide_inaccessible_checkbox.style().unpolish(self.hide_inaccessible_checkbox)
                            self.hide_inaccessible_checkbox.style().polish(self.hide_inaccessible_checkbox)
                            self.hide_inaccessible_checkbox.setFocus()
                        elif self.gamepad_focus_mode == 'hide_inaccessible':
                            # Move to hide_system checkbox
                            self.gamepad_focus_mode = 'hide_system'
                            self.hide_inaccessible_checkbox.setProperty('gamepadFocus', False)
                            self.hide_inaccessible_checkbox.style().unpolish(self.hide_inaccessible_checkbox)
                            self.hide_inaccessible_checkbox.style().polish(self.hide_inaccessible_checkbox)
                            self.hide_system_checkbox.setProperty('gamepadFocus', True)
                            self.hide_system_checkbox.style().unpolish(self.hide_system_checkbox)
                            self.hide_system_checkbox.style().polish(self.hide_system_checkbox)
                            self.hide_system_checkbox.setFocus()
                        elif self.gamepad_focus_mode == 'hide_system':
                            # Wrap around to last process
                            self.gamepad_focus_mode = 'table'
                            self.hide_system_checkbox.setProperty('gamepadFocus', False)
                            self.hide_system_checkbox.style().unpolish(self.hide_system_checkbox)
                            self.hide_system_checkbox.style().polish(self.hide_system_checkbox)
                            last_row = self.table.rowCount() - 1
                            if last_row >= 0:
                                self.table.setCurrentCell(last_row, 0)
                                self.table.setFocus()
                    elif current_y < 0:
                        # Navigate down
                        if self.gamepad_focus_mode == 'table':
                            current_row = self.table.currentRow()
                            if current_row < self.table.rowCount() - 1:
                                self.table.setCurrentCell(current_row + 1, 0)
                            else:
                                # At bottom of table, wrap to hide_system checkbox
                                self.gamepad_focus_mode = 'hide_system'
                                self.table.clearSelection()
                                self.hide_inaccessible_checkbox.setProperty('gamepadFocus', False)
                                self.hide_inaccessible_checkbox.style().unpolish(self.hide_inaccessible_checkbox)
                                self.hide_inaccessible_checkbox.style().polish(self.hide_inaccessible_checkbox)
                                self.hide_system_checkbox.setProperty('gamepadFocus', True)
                                self.hide_system_checkbox.style().unpolish(self.hide_system_checkbox)
                                self.hide_system_checkbox.style().polish(self.hide_system_checkbox)
                                self.hide_system_checkbox.setFocus()
                        elif self.gamepad_focus_mode == 'hide_system':
                            # Move to hide_inaccessible checkbox
                            self.gamepad_focus_mode = 'hide_inaccessible'
                            self.hide_system_checkbox.setProperty('gamepadFocus', False)
                            self.hide_system_checkbox.style().unpolish(self.hide_system_checkbox)
                            self.hide_system_checkbox.style().polish(self.hide_system_checkbox)
                            self.hide_inaccessible_checkbox.setProperty('gamepadFocus', True)
                            self.hide_inaccessible_checkbox.style().unpolish(self.hide_inaccessible_checkbox)
                            self.hide_inaccessible_checkbox.style().polish(self.hide_inaccessible_checkbox)
                            self.hide_inaccessible_checkbox.setFocus()
                        elif self.gamepad_focus_mode == 'hide_inaccessible':
                            # Move to search box and open virtual keyboard
                            self.gamepad_focus_mode = 'search'
                            self.hide_inaccessible_checkbox.setProperty('gamepadFocus', False)
                            self.hide_inaccessible_checkbox.style().unpolish(self.hide_inaccessible_checkbox)
                            self.hide_inaccessible_checkbox.style().polish(self.hide_inaccessible_checkbox)
                            self.search_input.clear()
                            self.search_input.setFocus()
                            self.open_virtual_keyboard()
                        elif self.gamepad_focus_mode == 'search':
                            # Wrap to first process
                            self.gamepad_focus_mode = 'table'
                            if self.table.rowCount() > 0:
                                self.table.setCurrentCell(0, 0)
                                self.table.setFocus()
                    
                    # Handle left/right navigation for checkboxes
                    elif current_x > 0:
                        # Navigate right
                        if self.gamepad_focus_mode == 'hide_system':
                            self.gamepad_focus_mode = 'hide_inaccessible'
                            self.hide_system_checkbox.setProperty('gamepadFocus', False)
                            self.hide_system_checkbox.style().unpolish(self.hide_system_checkbox)
                            self.hide_system_checkbox.style().polish(self.hide_system_checkbox)
                            self.hide_inaccessible_checkbox.setProperty('gamepadFocus', True)
                            self.hide_inaccessible_checkbox.style().unpolish(self.hide_inaccessible_checkbox)
                            self.hide_inaccessible_checkbox.style().polish(self.hide_inaccessible_checkbox)
                            self.hide_inaccessible_checkbox.setFocus()
                    elif current_x < 0:
                        # Navigate left
                        if self.gamepad_focus_mode == 'hide_inaccessible':
                            self.gamepad_focus_mode = 'hide_system'
                            self.hide_inaccessible_checkbox.setProperty('gamepadFocus', False)
                            self.hide_inaccessible_checkbox.style().unpolish(self.hide_inaccessible_checkbox)
                            self.hide_inaccessible_checkbox.style().polish(self.hide_inaccessible_checkbox)
                            self.hide_system_checkbox.setProperty('gamepadFocus', True)
                            self.hide_system_checkbox.style().unpolish(self.hide_system_checkbox)
                            self.hide_system_checkbox.style().polish(self.hide_system_checkbox)
                            self.hide_system_checkbox.setFocus()
                    
                    # Reset counter for continuous repeat
                    if self.gamepad_repeat_counter >= self.gamepad_repeat_delay:
                        self.gamepad_repeat_counter = self.gamepad_repeat_delay - 1  # Fast repeat
                
                self.gamepad_repeat_counter += 1
            
            # Trigger axes for fast continuous scrolling (LT/RT)
            # Xbox controllers: triggers range from -1.0 (not pressed) to 1.0 (fully pressed)
            if self.gamepad_focus_mode == 'table':
                # Left trigger (LT) - scroll up fast (axis 2)
                # Convert trigger range: -1.0 to 1.0 becomes 0.0 to 1.0
                lt_value = (trigger_left + 1.0) / 2.0
                if lt_value > 0.3:
                    if not hasattr(self, 'trigger_left_counter'):
                        self.trigger_left_counter = 0
                    
                    if self.trigger_left_counter == 0 or self.trigger_left_counter >= 2:
                        current_row = self.table.currentRow()
                        new_row = max(0, current_row - 10)
                        self.table.setCurrentCell(new_row, 0)
                        if self.trigger_left_counter >= 2:
                            self.trigger_left_counter = 0
                    self.trigger_left_counter += 1
                else:
                    self.trigger_left_counter = 0
                
                # Right trigger (RT) - scroll down fast (axis 5)
                # Convert trigger range: -1.0 to 1.0 becomes 0.0 to 1.0
                rt_value = (trigger_right + 1.0) / 2.0
                if rt_value > 0.3:
                    if not hasattr(self, 'trigger_right_counter'):
                        self.trigger_right_counter = 0
                    
                    if self.trigger_right_counter == 0 or self.trigger_right_counter >= 2:
                        current_row = self.table.currentRow()
                        new_row = min(self.table.rowCount() - 1, current_row + 10)
                        self.table.setCurrentCell(new_row, 0)
                        if self.trigger_right_counter >= 2:
                            self.trigger_right_counter = 0
                    self.trigger_right_counter += 1
                else:
                    self.trigger_right_counter = 0
            
            # Button handling with state tracking
            for button_id in range(min(10, self.gamepad.get_numbuttons())):
                is_pressed = self.gamepad.get_button(button_id)
                was_pressed = self.gamepad_button_states.get(button_id, False)
                
                # Only trigger on button press (not hold)
                if is_pressed and not was_pressed:
                    if button_id == 0:  # Button A - Open context menu or toggle checkbox
                        if self.gamepad_focus_mode == 'table':
                            current_row = self.table.currentRow()
                            if current_row >= 0:
                                rect = self.table.visualItemRect(self.table.item(current_row, 0))
                                self.show_context_menu(rect.center())
                        elif self.gamepad_focus_mode == 'hide_system':
                            self.hide_system_checkbox.setChecked(not self.hide_system_checkbox.isChecked())
                        elif self.gamepad_focus_mode == 'hide_inaccessible':
                            self.hide_inaccessible_checkbox.setChecked(not self.hide_inaccessible_checkbox.isChecked())
                    
                    elif button_id == 1:  # Button B - End task
                        selected_items = self.table.selectedItems()
                        if selected_items:
                            selected_pids = {}
                            for item in selected_items:
                                row = item.row()
                                pid_item = self.table.item(row, 0)
                                name_item = self.table.item(row, 2)
                                if pid_item and name_item:
                                    try:
                                        pid = int(pid_item.text())
                                        name = name_item.text()
                                        selected_pids[pid] = name
                                    except ValueError:
                                        pass
                            if selected_pids:
                                self.kill_processes(selected_pids)
                    
                    elif button_id == 4:  # L1 - Page up
                        current_row = self.table.currentRow()
                        new_row = max(0, current_row - 10)
                        self.table.setCurrentCell(new_row, 0)
                    
                    elif button_id == 5:  # R1 - Page down
                        current_row = self.table.currentRow()
                        new_row = min(self.table.rowCount() - 1, current_row + 10)
                        self.table.setCurrentCell(new_row, 0)
                    
                    elif button_id == 6:  # Back/Select button - Open context menu
                        if self.gamepad_focus_mode == 'table':
                            current_row = self.table.currentRow()
                            if current_row >= 0:
                                rect = self.table.visualItemRect(self.table.item(current_row, 0))
                                self.show_context_menu(rect.center())
                    
                    elif button_id == 7:  # Start button - Open theme menu
                        self.open_theme_dialog()
                
                self.gamepad_button_states[button_id] = is_pressed
            
        except Exception as e:
            print(f"Gamepad input error: {e}")
    
    def process_menu_navigation(self):
        """Handle gamepad navigation within context menus"""
        if not self.active_menu:
            return
        
        try:
            print("Processing menu navigation")
            # Get current direction
            hat = self.gamepad.get_hat(0) if self.gamepad.get_numhats() > 0 else (0, 0)
            axis_y = self.gamepad.get_axis(1) if self.gamepad.get_numaxes() > 1 else 0
            current_y = hat[1] if hat[1] != 0 else (1 if axis_y < -0.5 else (-1 if axis_y > 0.5 else 0))
            print(f"Menu nav - current_y: {current_y}, hat: {hat}, axis_y: {axis_y}")
            
            # Direction change detection
            if current_y != self.gamepad_last_axis['y']:
                self.gamepad_repeat_counter = 0
                self.gamepad_last_axis['y'] = current_y
            
            # Navigate menu items
            if current_y != 0:
                if self.gamepad_repeat_counter == 0 or self.gamepad_repeat_counter >= self.gamepad_repeat_delay:
                    actions = self.active_menu.actions()
                    current_action = self.active_menu.activeAction()
                    
                    if current_action:
                        current_index = actions.index(current_action)
                        if current_y > 0:  # Up
                            new_index = max(0, current_index - 1)
                        else:  # Down
                            new_index = min(len(actions) - 1, current_index + 1)
                        self.active_menu.setActiveAction(actions[new_index])
                    
                    if self.gamepad_repeat_counter >= self.gamepad_repeat_delay:
                        self.gamepad_repeat_counter = self.gamepad_repeat_delay - 1
                
                self.gamepad_repeat_counter += 1
            
            # Update button states for menu context
            for button_id in range(min(10, self.gamepad.get_numbuttons())):
                is_pressed = self.gamepad.get_button(button_id)
                was_pressed = self.gamepad_button_states.get(button_id, False)
                
                if is_pressed and not was_pressed:
                    if button_id == 0:  # Button A - Select menu item
                        current_action = self.active_menu.activeAction()
                        if current_action:
                            print(f"Triggering action: {current_action.text()}")
                            self.active_menu.close()
                            current_action.trigger()
                    elif button_id == 1:  # Button B - Close menu
                        print("Closing menu")
                        self.active_menu.close()
                
                self.gamepad_button_states[button_id] = is_pressed
            
            # Update button states
            for button_id in range(min(10, self.gamepad.get_numbuttons())):
                self.gamepad_button_states[button_id] = self.gamepad.get_button(button_id)
        
        except Exception as e:
            print(f"Menu navigation error: {e}")
    
    def moveEvent(self, event):
        """Block window movement when browser dialog is open"""
        # If a blocking dialog is open, ignore moves
        if hasattr(self, 'browser_dialog_open') and self.browser_dialog_open:
            event.ignore()
            return

        # Mark window as moving and pause heavy UI updates to avoid stutter
        try:
            self._window_moving = True

            # Remember and stop background filler to avoid spikes
            try:
                self._bg_fill_was_active = self._bg_fill_timer.isActive()
                if self._bg_fill_timer.isActive():
                    self._bg_fill_timer.stop()
            except Exception:
                self._bg_fill_was_active = False

            # Pause UI coalescer
            try:
                self._ui_update_was_active = self._ui_update_timer.isActive()
                if self._ui_update_timer.isActive():
                    self._ui_update_timer.stop()
            except Exception:
                self._ui_update_was_active = False

            # Temporarily disable widget updates to reduce repaint overhead
            try:
                self.setUpdatesEnabled(False)
                self.table.setUpdatesEnabled(False)
            except Exception:
                pass

            # Restart idle timer to detect when move stops
            try:
                if self._move_idle_timer.isActive():
                    self._move_idle_timer.stop()
                self._move_idle_timer.start()
            except Exception:
                pass
        except Exception:
            pass

        super().moveEvent(event)
    
    def eventFilter(self, source, event):
        """Filter events to catch key presses on the table and focus changes on checkboxes"""
        # Handle checkbox focus out events
        if (hasattr(self, 'hide_system_checkbox') and hasattr(self, 'hide_inaccessible_checkbox') and
            source in [self.hide_system_checkbox, self.hide_inaccessible_checkbox]):
            if event.type() == QEvent.FocusOut:
                source.setProperty('gamepadFocus', False)
                source.style().unpolish(source)
                source.style().polish(source)
                return False
            elif event.type() == QEvent.FocusIn:
                # Clear other checkbox when this one gets focus
                if source == self.hide_system_checkbox:
                    self.hide_inaccessible_checkbox.setProperty('gamepadFocus', False)
                    self.hide_inaccessible_checkbox.style().unpolish(self.hide_inaccessible_checkbox)
                    self.hide_inaccessible_checkbox.style().polish(self.hide_inaccessible_checkbox)
                else:
                    self.hide_system_checkbox.setProperty('gamepadFocus', False)
                    self.hide_system_checkbox.style().unpolish(self.hide_system_checkbox)
                    self.hide_system_checkbox.style().polish(self.hide_system_checkbox)
                return False
        
        if hasattr(self, 'table') and source == self.table and event.type() == QEvent.KeyPress:
            key = event.key()
            
            # Handle Home, End, and Delete keys
            if key == Qt.Key_Home:
                if self.table.rowCount() > 0:
                    self.table.setCurrentCell(0, 0)
                return True
            elif key == Qt.Key_End:
                if self.table.rowCount() > 0:
                    self.table.setCurrentCell(self.table.rowCount() - 1, 0)
                return True
            elif key == Qt.Key_Delete:
                selected_items = self.table.selectedItems()
                if selected_items:
                    selected_pids = {}
                    for item in selected_items:
                        row = item.row()
                        pid_item = self.table.item(row, 0)
                        name_item = self.table.item(row, 2)
                        if pid_item and name_item:
                            try:
                                pid = int(pid_item.text())
                                name = name_item.text()
                                selected_pids[pid] = name
                            except ValueError:
                                pass
                    if selected_pids:
                        self.kill_processes(selected_pids)
                return True
        
        return super().eventFilter(source, event)
    
    def keyPressEvent(self, event: QKeyEvent):
        """Handle keyboard events - focus search on alphanumeric key press and navigation"""
        key = event.key()
        text = event.text()
        
        # Arrow key navigation with wraparound (Page Up/Down, Home, End, Delete handled by eventFilter)
        if key == Qt.Key_Up:
            if self.table.hasFocus():
                current_row = self.table.currentRow()
                if current_row > 0:
                    self.table.setCurrentCell(current_row - 1, 0)
                else:
                    # At top of table, move to search box
                    self.table.clearSelection()
                    # Clear any checkbox highlights
                    self.hide_system_checkbox.setProperty('gamepadFocus', False)
                    self.hide_system_checkbox.style().unpolish(self.hide_system_checkbox)
                    self.hide_system_checkbox.style().polish(self.hide_system_checkbox)
                    self.hide_inaccessible_checkbox.setProperty('gamepadFocus', False)
                    self.hide_inaccessible_checkbox.style().unpolish(self.hide_inaccessible_checkbox)
                    self.hide_inaccessible_checkbox.style().polish(self.hide_inaccessible_checkbox)
                    self.search_input.setFocus()
            elif self.search_input.hasFocus():
                # From search, go to hide_inaccessible
                # Clear hide_system highlight
                self.hide_system_checkbox.setProperty('gamepadFocus', False)
                self.hide_system_checkbox.style().unpolish(self.hide_system_checkbox)
                self.hide_system_checkbox.style().polish(self.hide_system_checkbox)
                # Set hide_inaccessible highlight
                self.hide_inaccessible_checkbox.setProperty('gamepadFocus', True)
                self.hide_inaccessible_checkbox.style().unpolish(self.hide_inaccessible_checkbox)
                self.hide_inaccessible_checkbox.style().polish(self.hide_inaccessible_checkbox)
                self.hide_inaccessible_checkbox.setFocus()
            elif self.hide_inaccessible_checkbox.hasFocus():
                # From hide_inaccessible, go to hide_system
                self.hide_inaccessible_checkbox.setProperty('gamepadFocus', False)
                self.hide_inaccessible_checkbox.style().unpolish(self.hide_inaccessible_checkbox)
                self.hide_inaccessible_checkbox.style().polish(self.hide_inaccessible_checkbox)
                self.hide_system_checkbox.setProperty('gamepadFocus', True)
                self.hide_system_checkbox.style().unpolish(self.hide_system_checkbox)
                self.hide_system_checkbox.style().polish(self.hide_system_checkbox)
                self.hide_system_checkbox.setFocus()
            elif self.hide_system_checkbox.hasFocus():
                # From hide_system, wrap to last process
                self.hide_system_checkbox.setProperty('gamepadFocus', False)
                self.hide_system_checkbox.style().unpolish(self.hide_system_checkbox)
                self.hide_system_checkbox.style().polish(self.hide_system_checkbox)
                # Also clear hide_inaccessible in case it was highlighted
                self.hide_inaccessible_checkbox.setProperty('gamepadFocus', False)
                self.hide_inaccessible_checkbox.style().unpolish(self.hide_inaccessible_checkbox)
                self.hide_inaccessible_checkbox.style().polish(self.hide_inaccessible_checkbox)
                last_row = self.table.rowCount() - 1
                if last_row >= 0:
                    self.table.setCurrentCell(last_row, 0)
                    self.table.setFocus()
            event.accept()
            return
        elif key == Qt.Key_Down:
            if self.table.hasFocus():
                current_row = self.table.currentRow()
                if current_row < self.table.rowCount() - 1:
                    self.table.setCurrentCell(current_row + 1, 0)
                else:
                    # At bottom of table, move to hide_system
                    self.table.clearSelection()
                    # Clear hide_inaccessible highlight
                    self.hide_inaccessible_checkbox.setProperty('gamepadFocus', False)
                    self.hide_inaccessible_checkbox.style().unpolish(self.hide_inaccessible_checkbox)
                    self.hide_inaccessible_checkbox.style().polish(self.hide_inaccessible_checkbox)
                    # Set hide_system highlight
                    self.hide_system_checkbox.setProperty('gamepadFocus', True)
                    self.hide_system_checkbox.style().unpolish(self.hide_system_checkbox)
                    self.hide_system_checkbox.style().polish(self.hide_system_checkbox)
                    self.hide_system_checkbox.setFocus()
            elif self.hide_system_checkbox.hasFocus():
                # From hide_system, go to hide_inaccessible
                self.hide_system_checkbox.setProperty('gamepadFocus', False)
                self.hide_system_checkbox.style().unpolish(self.hide_system_checkbox)
                self.hide_system_checkbox.style().polish(self.hide_system_checkbox)
                self.hide_inaccessible_checkbox.setProperty('gamepadFocus', True)
                self.hide_inaccessible_checkbox.style().unpolish(self.hide_inaccessible_checkbox)
                self.hide_inaccessible_checkbox.style().polish(self.hide_inaccessible_checkbox)
                self.hide_inaccessible_checkbox.setFocus()
            elif self.hide_inaccessible_checkbox.hasFocus():
                # From hide_inaccessible, go to search
                self.hide_inaccessible_checkbox.setProperty('gamepadFocus', False)
                self.hide_inaccessible_checkbox.style().unpolish(self.hide_inaccessible_checkbox)
                self.hide_inaccessible_checkbox.style().polish(self.hide_inaccessible_checkbox)
                # Also clear hide_system in case it was highlighted
                self.hide_system_checkbox.setProperty('gamepadFocus', False)
                self.hide_system_checkbox.style().unpolish(self.hide_system_checkbox)
                self.hide_system_checkbox.style().polish(self.hide_system_checkbox)
                self.search_input.setFocus()
            elif self.search_input.hasFocus():
                # From search, wrap to first process
                # Clear any checkbox highlights
                self.hide_system_checkbox.setProperty('gamepadFocus', False)
                self.hide_system_checkbox.style().unpolish(self.hide_system_checkbox)
                self.hide_system_checkbox.style().polish(self.hide_system_checkbox)
                self.hide_inaccessible_checkbox.setProperty('gamepadFocus', False)
                self.hide_inaccessible_checkbox.style().unpolish(self.hide_inaccessible_checkbox)
                self.hide_inaccessible_checkbox.style().polish(self.hide_inaccessible_checkbox)
                if self.table.rowCount() > 0:
                    self.table.setCurrentCell(0, 0)
                    self.table.setFocus()
            event.accept()
            return
        elif key == Qt.Key_Left:
            # Navigate left between checkboxes
            if self.hide_inaccessible_checkbox.hasFocus():
                self.hide_inaccessible_checkbox.setProperty('gamepadFocus', False)
                self.hide_inaccessible_checkbox.style().unpolish(self.hide_inaccessible_checkbox)
                self.hide_inaccessible_checkbox.style().polish(self.hide_inaccessible_checkbox)
                self.hide_system_checkbox.setProperty('gamepadFocus', True)
                self.hide_system_checkbox.style().unpolish(self.hide_system_checkbox)
                self.hide_system_checkbox.style().polish(self.hide_system_checkbox)
                self.hide_system_checkbox.setFocus()
            event.accept()
            return
        elif key == Qt.Key_Right:
            # Navigate right between checkboxes
            if self.hide_system_checkbox.hasFocus():
                self.hide_system_checkbox.setProperty('gamepadFocus', False)
                self.hide_system_checkbox.style().unpolish(self.hide_system_checkbox)
                self.hide_system_checkbox.style().polish(self.hide_system_checkbox)
                self.hide_inaccessible_checkbox.setProperty('gamepadFocus', True)
                self.hide_inaccessible_checkbox.style().unpolish(self.hide_inaccessible_checkbox)
                self.hide_inaccessible_checkbox.style().polish(self.hide_inaccessible_checkbox)
                self.hide_inaccessible_checkbox.setFocus()
            event.accept()
            return
        elif key == Qt.Key_PageUp:
            current_row = self.table.currentRow()
            new_row = max(0, current_row - 10)
            self.table.setCurrentCell(new_row, 0)
            event.accept()
            return
        elif key == Qt.Key_PageDown:
            current_row = self.table.currentRow()
            new_row = min(self.table.rowCount() - 1, current_row + 10)
            self.table.setCurrentCell(new_row, 0)
            event.accept()
            return
        elif key == Qt.Key_Space:
            # Space to toggle checkboxes
            if self.hide_system_checkbox.hasFocus():
                self.hide_system_checkbox.setChecked(not self.hide_system_checkbox.isChecked())
                event.accept()
                return
            elif self.hide_inaccessible_checkbox.hasFocus():
                self.hide_inaccessible_checkbox.setChecked(not self.hide_inaccessible_checkbox.isChecked())
                event.accept()
                return
        
        # If gamepad is active and on a checkbox, don't intercept keys
        if hasattr(self, 'gamepad_focus_mode') and self.gamepad_focus_mode in ['hide_system', 'hide_inaccessible']:
            super().keyPressEvent(event)
            return
        
        # If alphanumeric key pressed and search not focused, focus it
        if text and text.isprintable() and not self.search_input.hasFocus():
            self.search_input.setFocus()
            self.search_input.setText(text)
        # If Escape is pressed, clear search
        elif key == Qt.Key_Escape:
            self.search_input.clear()
            self.table.setFocus()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        """Stop background threads cleanly on window close."""
        try:
            if hasattr(self, 'data_fetcher') and self.data_fetcher.isRunning():
                self.data_fetcher.stop()
                self.data_fetcher.wait(1000)
        except Exception:
            pass
        super().closeEvent(event)
    
    def request_data_update(self):
        """Request data update in worker thread"""
        # Wake the persistent worker to fetch immediately
        if hasattr(self, 'data_fetcher'):
            self.data_fetcher.trigger_fetch()
    
    def on_data_ready(self, mem_info, processes):
        """Handle data received from worker thread by caching and applying local filters."""
        # Cache full set of processes and last mem info for local filtering
        self._cached_processes = processes
        self._last_mem_info = mem_info

        # If change is significant and user is not scrolling, render immediately for snappy UX
        try:
            immediate = False
            if not getattr(self, '_user_scrolling', False):
                if self._is_significant_change(mem_info, processes):
                    immediate = True
        except Exception:
            immediate = False

        # Apply current search/hide filters locally for immediate responsiveness
        self._apply_search_filter()

        if immediate:
            # Flush pending UI update right away
            try:
                if self._ui_update_timer.isActive():
                    self._ui_update_timer.stop()
            except Exception:
                pass
            QTimer.singleShot(0, self._flush_ui_update)

    def _render_process_list(self, mem_info, processes, total_processes):
        """Render the provided (already filtered) processes list into the table."""
        # Save current scroll position
        scroll_value = self.table.verticalScrollBar().value()
        prev_rows = getattr(self, '_last_rendered', []) or []
        full_reload = len(prev_rows) != len(processes)

        # Temporarily disable sorting to avoid expensive resort on every update
        try:
            sorting_was_enabled = self.table.isSortingEnabled()
        except Exception:
            sorting_was_enabled = False
        try:
            self.table.setSortingEnabled(False)
        except Exception:
            pass

        # Disable updates and selection signals during refresh
        self.table.setUpdatesEnabled(False)
        try:
            self.table.itemSelectionChanged.disconnect(self.on_selection_changed)
        except Exception:
            pass
        if full_reload:
            self.table.setRowCount(0)
            self.table.setRowCount(len(processes))

        # Update memory info - only if changed to reduce flickering
        self.total_ram_label.setText(f"{mem_info['total']:.2f} GB")
        self.used_ram_label.setText(f"{mem_info['used']:.2f} GB")
        self.available_ram_label.setText(f"{mem_info['available']:.2f} GB")

        # Update progress bar
        percent = int(mem_info['percent'])
        if self.progress_bar.value() != percent:
            self.progress_bar.setValue(percent)
        self.progress_label.setText(f"{mem_info['percent']:.1f}%")

        # Color code the progress bar - cache colors
        if mem_info['percent'] < 50:
            style = "QProgressBar::chunk { background-color: #27ae60; }"
        elif mem_info['percent'] < 80:
            style = "QProgressBar::chunk { background-color: #f39c12; }"
        else:
            style = "QProgressBar::chunk { background-color: #e74c3c; }"
        self.progress_bar.setStyleSheet(style)

        # Use cached color objects
        if not hasattr(self, '_color_cache'):
            self._color_cache = {
                'high': QBrush(QColor(255, 200, 0, 50)),
                'med': QBrush(QColor(255, 200, 0, 30)),
                'none': QBrush(QColor(255, 255, 255, 0))
            }
        color_high = self._color_cache['high']
        color_med = self._color_cache['med']
        color_none = self._color_cache['none']

        # Batch insert/update items with optimized formatting and diffing
        non_editable_flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        str_func = str  # Cache built-in for faster access

        # Compute visible row range to minimize work during updates
        try:
            viewport_height = self.table.viewport().height()
            top_row = self.table.rowAt(0)
            if top_row < 0:
                top_row = 0
            bottom_row = self.table.rowAt(viewport_height - 1)
            if bottom_row < 0:
                # estimate visible rows from default row height
                try:
                    rh = self.table.rowHeight(0) if self.table.rowCount() > 0 else self.table.verticalHeader().defaultSectionSize()
                    rows_visible = max(1, int(viewport_height / max(1, rh)))
                except Exception:
                    rows_visible = 20
                bottom_row = min(len(processes) - 1, top_row + rows_visible)
        except Exception:
            top_row = 0
            bottom_row = min(len(processes) - 1, 20)

        for row, proc in enumerate(processes):
            # Skip work for rows outside the visible window to reduce UI churn
            if row < top_row or row > bottom_row:
                # still keep prev comparison and bookkeeping, but avoid creating items
                prev = prev_rows[row] if (not full_reload and row < len(prev_rows)) else None
                if (not full_reload) and prev and prev == proc:
                    continue
                # don't create items for off-screen rows
                continue
            prev = prev_rows[row] if (not full_reload and row < len(prev_rows)) else None
            if (not full_reload) and prev and prev == proc:
                # No change for this visible row; skip updates
                continue
            prev = prev_rows[row] if (not full_reload and row < len(prev_rows)) else None
            if (not full_reload) and prev and prev == proc:
                # No change for this row; skip updates
                continue

            # Always create fresh QTableWidgetItem objects to avoid ownership issues
            pid_item = QTableWidgetItem()
            pid_item.setFlags(non_editable_flags)

            user_item = QTableWidgetItem()
            user_item.setFlags(non_editable_flags)
            user_item.setTextAlignment(Qt.AlignCenter)

            name_item = QTableWidgetItem()
            name_item.setFlags(non_editable_flags)

            cpu_item = QTableWidgetItem()
            cpu_item.setFlags(non_editable_flags)

            ram_item = QTableWidgetItem()
            ram_item.setFlags(non_editable_flags)

            percent_item = QTableWidgetItem()
            percent_item.setFlags(non_editable_flags)

            disk_item = QTableWidgetItem()
            disk_item.setFlags(non_editable_flags)

            cpu_value = max(0.01, proc.get('cpu_percent', 0.0))
            pid_item.setText(str_func(proc['pid']))
            user_item.setText(proc.get('username', 'unknown'))
            name_item.setText(proc['name'])
            cpu_item.setText(f"{cpu_value:.1f}")
            ram_item.setText(f"{proc['memory_mb']:.1f}")
            percent_item.setText(f"{proc['memory_percent']:.1f}")
            disk_item.setText(f"{proc.get('disk_io_mb', 0.0):.1f}")

            # Select color based on memory usage
            if proc['memory_percent'] > 10:
                color = color_high
            elif proc['memory_percent'] > 5:
                color = color_med
            else:
                color = color_none

            if color is not color_none:
                pid_item.setBackground(color)
                user_item.setBackground(color)
                name_item.setBackground(color)
                cpu_item.setBackground(color)
                ram_item.setBackground(color)
                percent_item.setBackground(color)
                disk_item.setBackground(color)
            else:
                # Clear background if previously set
                pid_item.setBackground(color_none)
                user_item.setBackground(color_none)
                name_item.setBackground(color_none)
                cpu_item.setBackground(color_none)
                ram_item.setBackground(color_none)
                percent_item.setBackground(color_none)
                disk_item.setBackground(color_none)

            # Assign items for visible rows immediately
            if not getattr(self, '_user_scrolling', False):
                self.table.setItem(row, 0, pid_item)
                self.table.setItem(row, 1, user_item)
                self.table.setItem(row, 2, name_item)
                self.table.setItem(row, 3, cpu_item)
                self.table.setItem(row, 4, ram_item)
                self.table.setItem(row, 5, percent_item)
                self.table.setItem(row, 6, disk_item)
            else:
                # If currently scrolling, still queue visible-row items to ensure they appear
                # (this rarely happens because we skip when scrolling, but keep safe)
                try:
                    self._pending_offscreen_fill.append((row, pid_item, user_item, name_item, cpu_item, ram_item, percent_item, disk_item))
                except Exception:
                    pass

        # Re-enable updates
        self.table.setUpdatesEnabled(True)

        # Prepare background fill for off-screen rows (populate remaining rows in batches)
        try:
            # Build pending fill list for rows not currently filled
            pending = []
            for r in range(self.table.rowCount()):
                if self.table.item(r, 0) is None and r < len(processes):
                    p = processes[r]
                    pending.append((r, p))
            self._pending_offscreen_fill = pending
            if self._pending_offscreen_fill:
                if not self._bg_fill_timer.isActive():
                    self._bg_fill_timer.start()
            else:
                try:
                    if self._bg_fill_timer.isActive():
                        self._bg_fill_timer.stop()
                except Exception:
                    pass
        except Exception:
            pass

        # Restore previous sorting state
        try:
            self.table.setSortingEnabled(sorting_was_enabled)
        except Exception:
            pass
        
        # Restore selections if they still exist (without scrolling to them)
        if not getattr(self, '_user_scrolling', False):
            if self.selected_pid:
                self.table.blockSignals(True)
                for row in range(self.table.rowCount()):
                    pid_item = self.table.item(row, 0)
                    if pid_item:
                        try:
                            pid = int(pid_item.text())
                            if pid in self.selected_pid:
                                self.table.selectRow(row)
                        except ValueError:
                            pass
                self.table.blockSignals(False)
            
            # Restore scroll position only when not actively scrolling
            try:
                self.table.verticalScrollBar().setValue(scroll_value)
            except Exception:
                pass

        # Restore selections if they still exist (without scrolling to them)
        if self.selected_pid:
            self.table.blockSignals(True)
            for row in range(self.table.rowCount()):
                pid_item = self.table.item(row, 0)
                if pid_item:
                    try:
                        pid = int(pid_item.text())
                        if pid in self.selected_pid:
                            self.table.selectRow(row)
                    except ValueError:
                        pass
            self.table.blockSignals(False)

        # Restore scroll position
        self.table.verticalScrollBar().setValue(scroll_value)

        # Reconnect selection signal
        try:
            self.table.itemSelectionChanged.connect(self.on_selection_changed)
        except Exception:
            pass

        # Store a shallow copy of current rows for diffing on next refresh
        try:
            self._last_rendered = [dict(p) for p in processes]
        except Exception:
            self._last_rendered = processes

        # Update status bar with both counts
        current_time = datetime.now().strftime('%H:%M:%S')
        if self.hide_system_checkbox.isChecked() or self.hide_inaccessible_checkbox.isChecked():
            self.statusBar().showMessage(f'Ready - Last updated: {current_time} | Showing: {len(processes)} / Total Processes: {total_processes}')
        else:
            self.statusBar().showMessage(f'Ready - Last updated: {current_time} | Total Processes: {total_processes}')

    def _flush_ui_update(self):
        """Called from the UI coalescing timer to perform a single render of pending data."""
        mem_info = self._pending_render_mem_info or self._last_mem_info
        processes = self._pending_render_processes or list(self._cached_processes)
        total = self._pending_total_processes or len(self._cached_processes)
        # If the user is actively scrolling, postpone intensive render until scrolling stops
        if getattr(self, '_user_scrolling', False):
            # re-schedule the ui update slightly later to avoid stutter
            try:
                if self._ui_update_timer.isActive():
                    self._ui_update_timer.stop()
            except Exception:
                pass
            # Start a slightly longer delay while scrolling
            try:
                # give some time for scrolling to stop before attempting a render
                self._ui_update_timer.start(250)
            except Exception:
                pass
            return

        try:
            self._render_process_list(mem_info, processes, total)
        finally:
            # Clear pending values
            self._pending_render_mem_info = None
            self._pending_render_processes = None
            self._pending_total_processes = 0

    def _is_significant_change(self, mem_info, processes) -> bool:
        """Return True if the incoming data is meaningfully different from last rendered.

        Heuristics used:
        - Memory percent changed by >= 0.5%
        - Top-3 PIDs changed (different set)
        - Total process count changed by > 3
        """
        try:
            # Mem percent change
            last_mem = getattr(self, '_last_mem_info', None)
            if last_mem:
                try:
                    if abs(float(mem_info.get('percent', 0.0)) - float(last_mem.get('percent', 0.0))) >= 0.5:
                        return True
                except Exception:
                    pass

            # Top 3 pid changes
            last_rows = getattr(self, '_last_rendered', None)
            try:
                new_top = tuple(p['pid'] for p in (processes[:3] if processes else []))
            except Exception:
                new_top = ()
            try:
                old_top = tuple(p.get('pid') for p in (last_rows[:3] if last_rows else []))
            except Exception:
                old_top = ()
            if new_top and old_top and set(new_top) != set(old_top):
                return True

            # Process count delta
            if last_rows is not None and abs(len(processes) - len(last_rows)) > 3:
                return True
        except Exception:
            pass
        return False

    def _on_user_scrolled(self, value=None):
        """Called when the user moves the vertical scrollbar; mark scrolling active and debounce stop."""
        try:
            self._user_scrolling = True
            # restart inactive timer
            if self._scroll_inactive_timer.isActive():
                self._scroll_inactive_timer.stop()
            self._scroll_inactive_timer.start()
        except Exception:
            pass

    def _on_scroll_stopped(self):
        """Called when scroll activity has paused; mark not scrolling and trigger any pending UI update."""
        try:
            self._user_scrolling = False
            # If there's pending data, ensure we flush soon
            if self._pending_render_processes is not None:
                if self._ui_update_timer.isActive():
                    self._ui_update_timer.stop()
                self._ui_update_timer.start(10)
        except Exception:
            pass

    def _on_move_stopped(self):
        """Called when window movement has paused; resume previously paused UI updates."""
        try:
            self._window_moving = False

            # Re-enable updates
            try:
                self.setUpdatesEnabled(True)
                self.table.setUpdatesEnabled(True)
            except Exception:
                pass

            # Resume background filler if it was previously active or there is pending work
            try:
                if getattr(self, '_bg_fill_was_active', False) or getattr(self, '_pending_offscreen_fill', None):
                    if not self._bg_fill_timer.isActive() and getattr(self, '_pending_offscreen_fill', None):
                        self._bg_fill_timer.start()
            except Exception:
                pass

            # If there was a UI update pending or was active before move, flush now
            try:
                if getattr(self, '_ui_update_was_active', False) or self._pending_render_processes is not None:
                    # Schedule an immediate flush to update the UI
                    QTimer.singleShot(10, self._flush_ui_update)
            except Exception:
                pass

            # Reset remembered flags
            try:
                self._bg_fill_was_active = False
                self._ui_update_was_active = False
            except Exception:
                pass
        except Exception as e:
            print(f"_on_move_stopped error: {e}")

    def _bg_fill_step(self):
        """Fill a small batch of pending off-screen rows to avoid large single-frame updates.

        The pending entries may be either:
        - (row, QTableWidgetItem, QTableWidgetItem, ... ) tuples produced while scrolling,
        - or (row, proc_dict) tuples produced after a render to progressively populate off-screen rows.
        """
        try:
            if not hasattr(self, '_pending_offscreen_fill') or not self._pending_offscreen_fill:
                try:
                    if self._bg_fill_timer.isActive():
                        self._bg_fill_timer.stop()
                except Exception:
                    pass
                return

            # Number of rows to fill per tick - tuneable
            batch_size = 8

            non_editable_flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled

            # Ensure color cache exists
            if not hasattr(self, '_color_cache'):
                self._color_cache = {
                    'high': QBrush(QColor(255, 200, 0, 50)),
                    'med': QBrush(QColor(255, 200, 0, 30)),
                    'none': QBrush(QColor(255, 255, 255, 0))
                }

            filled = 0
            for _ in range(batch_size):
                if not self._pending_offscreen_fill:
                    break
                entry = self._pending_offscreen_fill.pop(0)
                # Two possible shapes: (row, pid_item, user_item, name_item, cpu_item, ram_item, percent_item, disk_item)
                # or (row, proc_dict)
                try:
                    if len(entry) >= 8 and isinstance(entry[1], QTableWidgetItem):
                        row = entry[0]
                        items = entry[1:]
                        # Ensure row exists
                        if row >= self.table.rowCount():
                            continue
                        for col, itm in enumerate(items):
                            try:
                                self.table.setItem(row, col, itm)
                            except Exception:
                                pass
                        filled += 1
                    else:
                        row, proc = entry
                        if row >= self.table.rowCount():
                            continue
                        # Create fresh items similar to rendering path
                        pid_item = QTableWidgetItem()
                        pid_item.setFlags(non_editable_flags)
                        user_item = QTableWidgetItem()
                        user_item.setFlags(non_editable_flags)
                        user_item.setTextAlignment(Qt.AlignCenter)
                        name_item = QTableWidgetItem()
                        name_item.setFlags(non_editable_flags)
                        cpu_item = QTableWidgetItem()
                        cpu_item.setFlags(non_editable_flags)
                        ram_item = QTableWidgetItem()
                        ram_item.setFlags(non_editable_flags)
                        percent_item = QTableWidgetItem()
                        percent_item.setFlags(non_editable_flags)
                        disk_item = QTableWidgetItem()
                        disk_item.setFlags(non_editable_flags)

                        cpu_value = max(0.01, proc.get('cpu_percent', 0.0))
                        pid_item.setText(str(proc.get('pid', '')))
                        user_item.setText(proc.get('username', 'unknown'))
                        name_item.setText(proc.get('name', ''))
                        cpu_item.setText(f"{cpu_value:.1f}")
                        ram_item.setText(f"{proc.get('memory_mb', 0.0):.1f}")
                        percent_item.setText(f"{proc.get('memory_percent', 0.0):.1f}")
                        disk_item.setText(f"{proc.get('disk_io_mb', 0.0):.1f}")

                        # Color selection
                        color = self._color_cache['none']
                        try:
                            if proc.get('memory_percent', 0.0) > 10:
                                color = self._color_cache['high']
                            elif proc.get('memory_percent', 0.0) > 5:
                                color = self._color_cache['med']
                        except Exception:
                            color = self._color_cache['none']

                        if color is not self._color_cache['none']:
                            for itm in (pid_item, user_item, name_item, cpu_item, ram_item, percent_item, disk_item):
                                itm.setBackground(color)
                        else:
                            for itm in (pid_item, user_item, name_item, cpu_item, ram_item, percent_item, disk_item):
                                itm.setBackground(self._color_cache['none'])

                        # Apply to table
                        try:
                            self.table.setItem(row, 0, pid_item)
                            self.table.setItem(row, 1, user_item)
                            self.table.setItem(row, 2, name_item)
                            self.table.setItem(row, 3, cpu_item)
                            self.table.setItem(row, 4, ram_item)
                            self.table.setItem(row, 5, percent_item)
                            self.table.setItem(row, 6, disk_item)
                        except Exception:
                            pass
                        filled += 1
                except Exception:
                    # Ignore malformed entries and continue
                    continue

            # If nothing left to fill, stop timer
            if not self._pending_offscreen_fill:
                try:
                    if self._bg_fill_timer.isActive():
                        self._bg_fill_timer.stop()
                except Exception:
                    pass
        except Exception as e:
            print(f"_bg_fill_step error: {e}")


def main():
    # Check if display is available
    if not os.environ.get('DISPLAY'):
        print("Warning: No display found. Setting DISPLAY to :0")
        os.environ['DISPLAY'] = ':0'
    
    # Add --no-sandbox flag for QtWebEngine when running as root
    if (hasattr(os, 'geteuid') and os.geteuid() == 0) or (os.name == 'nt' and is_windows_admin()):
        if '--no-sandbox' not in sys.argv:
            sys.argv.append('--no-sandbox')
            print("Running as root/admin: Added --no-sandbox flag for QtWebEngine")
    
    try:
        app = QApplication(sys.argv)
    except Exception as e:
        print(f"Failed to create QApplication: {e}")
        print("Trying with offscreen platform plugin...")
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        app = QApplication(sys.argv)
    
    window = TaskManagerGUI()
    window.showNormal()  # Use showNormal instead of show
    window.raise_()  # Bring window to front
    window.activateWindow()  # Ensure window is focused
    window.setWindowState(window.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
    
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
