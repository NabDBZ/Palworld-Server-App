from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget, QListWidgetItem, QAbstractItemView, QFrame
from PySide6.QtCore import Qt, Signal, QSize
from i18n import t
from palworld_aio import constants
from palworld_aio.widgets.toggle_check import ToggleCheckBtn
from palworld_aio.ui.chrome.styles import DIALOG_STYLE as DARK_THEME_STYLE

class FixIllegalPlayerDialog(QDialog):
    fix_requested = Signal(list)
    def __init__(self, scan_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t('fix_illegal_player.title') if t else 'Fix Illegal Players')
        self.setMinimumSize(700, 450)
        self.scan_data = scan_data
        self._setup_ui()
        self._populate_players()
    def _setup_ui(self):
        self.setStyleSheet(DARK_THEME_STYLE)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        self._header = QLabel(t('fix_illegal_player.description') if t else 'Select players with illegal stats to fix:')
        self._header.setStyleSheet('color: #e2e8f0; font-size: 13px; font-weight: 600; padding: 4px 0;')
        self._header.setWordWrap(True)
        layout.addWidget(self._header)
        self.summary_label = QLabel('')
        self.summary_label.setStyleSheet('color: #fbbf24; font-size: 12px; padding: 2px 0;')
        layout.addWidget(self.summary_label)
        btn_row = QHBoxLayout()
        self.select_all_btn = QPushButton(t('player_item.select_all') if t else 'Select All')
        self.select_all_btn.clicked.connect(self._select_all)
        self.select_all_btn.setEnabled(False)
        btn_row.addWidget(self.select_all_btn)
        self.deselect_all_btn = QPushButton(t('player_item.deselect_all') if t else 'Deselect All')
        self.deselect_all_btn.clicked.connect(self._deselect_all)
        self.deselect_all_btn.setEnabled(False)
        btn_row.addWidget(self.deselect_all_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        self.player_list = QListWidget()
        self.player_list.setSelectionMode(QAbstractItemView.NoSelection)
        layout.addWidget(self.player_list)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet('color: rgba(255,255,255,0.1);')
        layout.addWidget(sep)
        action_row = QHBoxLayout()
        self.fix_btn = QPushButton(t('fix_illegal_player.fix_selected') if t else 'Fix Selected')
        self.fix_btn.setStyleSheet('QPushButton { background: rgba(251,191,36,0.15); color: #fbbf24; border: 1px solid rgba(251,191,36,0.3); border-radius: 6px; padding: 8px 24px; font-weight: 600; font-size: 13px; } QPushButton:hover { background: rgba(251,191,36,0.25); border-color: rgba(251,191,36,0.5); color: #FFFFFF; } QPushButton:disabled { background: rgba(100,100,100,0.1); color: #666; border-color: rgba(100,100,100,0.2); }')
        self.fix_btn.setCursor(Qt.PointingHandCursor)
        self.fix_btn.clicked.connect(self._on_fix)
        self.fix_btn.setEnabled(False)
        action_row.addWidget(self.fix_btn)
        action_row.addStretch()
        self._close_btn = QPushButton(t('button.close') if t else 'Close')
        self._close_btn.setStyleSheet('QPushButton { background: rgba(239,68,68,0.1); color: #ef4444; border: 1px solid rgba(239,68,68,0.2); border-radius: 6px; padding: 8px 24px; } QPushButton:hover { background: rgba(239,68,68,0.2); }')
        self._close_btn.clicked.connect(self.reject)
        action_row.addWidget(self._close_btn)
        layout.addLayout(action_row)
        self.status_label = QLabel('')
        self.status_label.setStyleSheet('color: #4ade80; font-weight: bold; padding: 5px;')
        layout.addWidget(self.status_label)
    def refresh_labels(self):
        self.setWindowTitle(t('fix_illegal_player.title') if t else 'Fix Illegal Players')
        self._header.setText(t('fix_illegal_player.description') if t else 'Select players with illegal stats to fix:')
        self.select_all_btn.setText(t('player_item.select_all') if t else 'Select All')
        self.deselect_all_btn.setText(t('player_item.deselect_all') if t else 'Deselect All')
        self.fix_btn.setText(t('fix_illegal_player.fix_selected') if t else 'Fix Selected')
        self._close_btn.setText(t('button.close') if t else 'Close')
        self._update_summary()
    def _update_summary(self):
        total_players = sum(1 for d in self.scan_data.values() if d['stat_count'] > 0)
        total_stats = sum(d['stat_count'] for d in self.scan_data.values() if d['stat_count'] > 0)
        self.summary_label.setText(t('fix_illegal_player.summary').format(players=total_players, stats=total_stats) if t else f'Found {total_players} player(s) with {total_stats} illegal stat(s)')
    def _populate_players(self):
        self.player_list.clear()
        self._player_widgets = {}
        total_players = 0
        total_stats = 0
        for uid_clean, data in sorted(self.scan_data.items(), key=lambda x: x[1].get('player_name', '')):
            if data['stat_count'] <= 0:
                continue
            total_players += 1
            total_stats += data['stat_count']
            stat_details = ', '.join([f'{k}={v}' for k, v in data['illegal_stats'].items()])
            display = f"{data['player_name']} (Lv.{data['level']}) - {data['guild_name']}"
            display += f'  [{stat_details}]'
            checkbox = ToggleCheckBtn(display)
            checkbox.setProperty('uid', uid_clean)
            checkbox.setChecked(True)
            checkbox.toggled.connect(self._on_check_toggled)
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 36))
            self.player_list.addItem(item)
            self.player_list.setItemWidget(item, checkbox)
            self._player_widgets[uid_clean] = checkbox
        self._update_summary()
        if total_players > 0:
            self.select_all_btn.setEnabled(True)
            self.deselect_all_btn.setEnabled(True)
            self.fix_btn.setEnabled(True)
    def _on_check_toggled(self, checked=False):
        any_checked = any((w.isChecked() for w in self._player_widgets.values()))
        self.fix_btn.setEnabled(any_checked)
    def _select_all(self):
        for w in self._player_widgets.values():
            w.setChecked(True)
        self.fix_btn.setEnabled(True)
    def _deselect_all(self):
        for w in self._player_widgets.values():
            w.setChecked(False)
        self.fix_btn.setEnabled(False)
    def _get_selected_uids(self):
        uids = []
        for uid, w in self._player_widgets.items():
            if w.isChecked():
                uids.append(uid)
        return uids
    def _on_fix(self):
        uids = self._get_selected_uids()
        if not uids:
            self.status_label.setText(t('fix_illegal_player.no_selection') if t else 'No players selected.')
            self.status_label.setStyleSheet('color: #ef4444; font-weight: bold; padding: 5px;')
            return
        self.accept()
        self.fix_requested.emit(uids)
