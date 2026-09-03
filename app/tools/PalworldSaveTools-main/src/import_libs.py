import os, ssl
import sys, argparse, collections, copy, ctypes, datetime, gc, json, shutil, glob
import logging, multiprocessing, platform, re, subprocess, threading, pickle, zipfile, string, palworld_coord
import time, traceback, uuid, io, pathlib, urllib.request, tempfile, random
from multiprocessing import shared_memory
from PySide6.QtWidgets import QApplication, QWidget, QMainWindow, QDialog, QMessageBox, QFileDialog, QInputDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QComboBox, QTextEdit, QTreeWidget, QTreeWidgetItem, QProgressBar, QCheckBox, QRadioButton, QGroupBox, QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QSplitter, QScrollArea, QFrame, QMenuBar, QMenu, QStatusBar, QSystemTrayIcon, QStyle, QCommonStyle, QStylePainter, QStyleOptionButton
from PySide6.QtGui import QPixmap, QIcon, QFont, QPainter, QPen, QBrush, QColor, QAction, QFontMetrics
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QObject, QEvent, QSize, QPoint, QRect
from i18n import init_language, t, set_language, get_language, load_resources
from collections import defaultdict
class NerdBtn(QPushButton):
    def paintEvent(self, event):
        sp = QStylePainter(self)
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        opt.text = ''
        sp.drawControl(QStyle.CE_PushButton, opt)
        sp.end()
        p = QPainter(self)
        p.setRenderHint(QPainter.TextAntialiasing | QPainter.Antialiasing)
        p.setFont(self.font())
        p.setPen(self.palette().color(self.foregroundRole()))
        fm = QFontMetrics(self.font())
        br = fm.boundingRect(self.text())
        x = (self.width() - br.width()) / 2 - br.x()
        y = (self.height() - br.height()) / 2 - br.y()
        p.drawText(int(x), int(y), self.text())
        p.end()

_LAZY_SOURCE_MODULES = [
    'palsav.archive',
    'palsav.paltypes',
    'palobject',
    'palsav.gvas',
    'palsav.json_tools',
    'common',
    'loading_manager',
]
_LAZY_ALIASES = {
    'palworld_save_group': 'palsav.rawdata.group',
    'sav_to_map': ('palworld_coord', 'sav_to_map'),
    'ICON_PATH': ('common', 'ICON_PATH'),
}
_LAZY_CACHE = {}
_LAZY_ALL = None

def __getattr__(name):
    if name in _LAZY_CACHE:
        return _LAZY_CACHE[name]
    if name in _LAZY_ALIASES:
        target = _LAZY_ALIASES[name]
        import importlib
        if isinstance(target, tuple):
            mod = importlib.import_module(target[0])
            val = getattr(mod, target[1])
        else:
            val = importlib.import_module(target)
        _LAZY_CACHE[name] = val
        globals()[name] = val
        return val
    import importlib
    for mod_name in _LAZY_SOURCE_MODULES:
        try:
            mod = importlib.import_module(mod_name)
            if hasattr(mod, name):
                val = getattr(mod, name)
                _LAZY_CACHE[name] = val
                globals()[name] = val
                return val
        except Exception:
            continue
    raise AttributeError(f"module 'import_libs' has no attribute {name!r}")

def __dir__():
    names = set(dir(__import__(__name__)))
    names.update(_LAZY_ALIASES.keys())
    import importlib
    for mod_name in _LAZY_SOURCE_MODULES:
        try:
            mod = importlib.import_module(mod_name)
            names.update(n for n in dir(mod) if not n.startswith('_'))
        except Exception:
            continue
    return sorted(names)

def _compute_all():
    names = set(globals().keys())
    names.update(_LAZY_ALIASES.keys())
    import importlib
    for mod_name in _LAZY_SOURCE_MODULES:
        try:
            mod = importlib.import_module(mod_name)
            names.update(n for n in dir(mod) if not n.startswith('_'))
        except Exception:
            continue
    return sorted(names)
def backup_whole_directory(source_folder, backup_folder):
    import os, sys, shutil, datetime as dt
    from resource_resolver import get_data_base
    def get_timestamp():
        return dt.datetime.now().strftime('%Y%m%d_%H%M%S')
    source_folder = os.path.abspath(source_folder)
    if not os.path.isabs(backup_folder):
        base_path = get_data_base()
        backup_folder = os.path.abspath(os.path.join(base_path, backup_folder))
    else:
        backup_folder = os.path.abspath(backup_folder)
    if not os.path.exists(backup_folder):
        os.makedirs(backup_folder)
    print('Now backing up save files and Players folder...')
    timestamp = get_timestamp()
    backup_path = os.path.join(backup_folder, f'PalworldSave_backup_{timestamp}')
    os.makedirs(backup_path, exist_ok=True)
    for name in ('Level.sav', 'LevelMeta.sav', 'WorldOption.sav', 'LocalData.sav'):
        src = os.path.join(source_folder, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(backup_path, name))
    players_src = os.path.join(source_folder, 'Players')
    if os.path.exists(players_src):
        def _ignore_backup(dir, contents):
            return [c for c in contents if c.lower() in ('backups', 'backup', '_backups', '_backup')]
        shutil.copytree(players_src, os.path.join(backup_path, 'Players'),
                        ignore=_ignore_backup)
    print(f'Backup created at: {backup_path}')
def center_window(window):
    if hasattr(window, 'move'):
        screen = QApplication.primaryScreen().availableGeometry()
        size = window.size()
        window.move((screen.width() - size.width()) // 2, (screen.height() - size.height()) // 2)

__all__ = _compute_all()