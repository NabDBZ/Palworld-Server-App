from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QWidget, QFrame, QSplitter
from PySide6.QtCore import Qt, Signal
from i18n import t
from palworld_aio.widgets.toggle_check import ToggleCheckBtn
from palworld_aio.ui.chrome.styles import DIALOG_STYLE as DARK_THEME_STYLE
from palworld_aio.editor.pal_editor.icons import _get_pal_icon_path, _get_cached_pixmap

class PalRowWidget(QFrame):
    def __init__(self, pal_data, parent=None):
        super().__init__(parent)
        self.pal_data = pal_data
        self._setup_ui()
    def _setup_ui(self):
        self.setStyleSheet('PalRowWidget { background: rgba(255,255,255,0.03); border-radius: 4px; margin: 1px 0; } PalRowWidget:hover { background: rgba(125,211,252,0.06); }')
        main = QVBoxLayout(self)
        main.setContentsMargins(6, 3, 6, 3)
        main.setSpacing(2)
        top_row = QHBoxLayout()
        top_row.setSpacing(6)
        icon_path = _get_pal_icon_path(self.pal_data.get('cid', ''))
        icon_lbl = QLabel()
        icon_lbl.setFixedSize(22, 22)
        if icon_path:
            pix = _get_cached_pixmap(icon_path, 22)
            if pix and not pix.isNull():
                icon_lbl.setPixmap(pix)
        top_row.addWidget(icon_lbl)
        nick = self.pal_data.get('nickname', '')
        name_text = nick if nick else self.pal_data.get('name', 'Unknown')
        lvl = self.pal_data.get('level', 1)
        rank = self.pal_data.get('rank', 1)
        stars = rank - 1 if rank > 1 else 0
        info_parts = [f'Lv.{lvl}']
        if stars:
            info_parts.append(f'{stars}★')
        info_text = ' '.join(info_parts)
        ivs = f"IVs {self.pal_data.get('talent_hp', 0)}/{self.pal_data.get('talent_shot', 0)}/{self.pal_data.get('talent_defense', 0)}"
        souls = f"Souls {self.pal_data.get('rank_hp', 0)}/{self.pal_data.get('rank_attack', 0)}/{self.pal_data.get('rank_defense', 0)}/{self.pal_data.get('rank_craftspeed', 0)}"
        detail = f'{info_text} | {ivs} | {souls} | {self.pal_data.get("location", "")}'
        line_label = QLabel(f'{name_text} — {detail}')
        line_label.setStyleSheet('color: #e2e8f0; font-size: 11px;')
        top_row.addWidget(line_label, 1)
        main.addLayout(top_row)
        markers = self.pal_data.get('illegal_markers', [])
        if markers:
            marker_text = '  '.join(f'[{m}]' for m in markers)
            marker_lbl = QLabel(marker_text)
            marker_lbl.setStyleSheet('color: #f97316; font-size: 10px; font-weight: 700; padding: 1px 8px; background: rgba(249,115,22,0.15); border: 1px solid rgba(249,115,22,0.3); border-radius: 4px;')
            marker_lbl.setWordWrap(True)
            main.addWidget(marker_lbl)
class PlayerCardWidget(QFrame):
    clicked = Signal(str)
    def __init__(self, uid, data, parent=None):
        super().__init__(parent)
        self.uid = uid
        self.data = data
        self._selected = False
        self._setup_ui()
    def _setup_ui(self):
        self.setFixedHeight(48)
        self._update_style()
        self.setCursor(Qt.PointingHandCursor)
        card = QHBoxLayout(self)
        card.setContentsMargins(8, 4, 8, 4)
        card.setSpacing(6)
        self.checkbox = ToggleCheckBtn('')
        self.checkbox.setChecked(True)
        card.addWidget(self.checkbox)
        text_w = QWidget()
        text_l = QVBoxLayout(text_w)
        text_l.setContentsMargins(0, 0, 0, 0)
        text_l.setSpacing(1)
        name = self.data.get('player_name', 'Unknown')
        guild = self.data.get('guild_name', 'Unknown')
        level = self.data.get('level', 1)
        count = self.data['pal_count']
        name_lbl = QLabel(f'{name} (Lv.{level})')
        name_lbl.setStyleSheet('color: #e2e8f0; font-size: 12px; font-weight: 600;')
        text_l.addWidget(name_lbl)
        extra_lbl = QLabel(f'{guild}  [{count} illegal]')
        extra_lbl.setStyleSheet('color: #94a3b8; font-size: 10px;')
        text_l.addWidget(extra_lbl)
        card.addWidget(text_w, 1)
    def _update_style(self):
        if self._selected:
            self.setStyleSheet('PlayerCardWidget { background: rgba(125,211,252,0.15); border: 1px solid rgba(125,211,252,0.5); border-radius: 4px; margin: 1px 0; } PlayerCardWidget:hover { background: rgba(125,211,252,0.2); }')
        else:
            self.setStyleSheet('PlayerCardWidget { background: rgba(255,255,255,0.03); border: 1px solid transparent; border-radius: 4px; margin: 1px 0; } PlayerCardWidget:hover { background: rgba(125,211,252,0.06); }')
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.uid)
        super().mousePressEvent(event)
    def set_selected(self, selected):
        self._selected = selected
        self._update_style()
    def is_checked(self):
        return self.checkbox.isChecked()
    def set_checked(self, checked):
        self.checkbox.setChecked(checked)

class FixIllegalPalDialog(QDialog):
    def __init__(self, scan_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t('fix_illegal_pal.title') if t else 'Fix Illegal Pals')
        self.setMinimumSize(1000, 550)
        self.scan_data = scan_data
        self._player_cards = {}
        self._player_pal_rows = {}
        self._selected_uid = None
        self._setup_ui()
        self._populate_players()
        self._populate_all_pal_rows()
        self._select_first_player()
    def _setup_ui(self):
        self.setStyleSheet(DARK_THEME_STYLE)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        self._header = QLabel(t('fix_illegal_pal.description') if t else 'Players to fix:')
        self._header.setStyleSheet('color: #e2e8f0; font-size: 13px; font-weight: 600; padding: 4px 0;')
        layout.addWidget(self._header)
        self.summary_label = QLabel('')
        self.summary_label.setStyleSheet('color: #fbbf24; font-size: 12px; padding: 2px 0;')
        layout.addWidget(self.summary_label)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        left_panel = QFrame()
        left_panel.setStyleSheet('QFrame { background: rgba(0,0,0,0.15); border-radius: 6px; }')
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(6, 6, 6, 6)
        left_layout.setSpacing(4)
        left_header = QLabel(t('fix_illegal_pal.players_header') if t else 'Players')
        left_header.setStyleSheet('color: #93c5fd; font-size: 12px; font-weight: 700; padding: 2px 4px;')
        left_layout.addWidget(left_header)
        left_btn_row = QHBoxLayout()
        left_sel_all = QPushButton(t('player_item.select_all') if t else 'All')
        left_sel_all.setFixedHeight(22)
        left_sel_all.setStyleSheet('QPushButton { background: rgba(74,222,128,0.12); color: #4ade80; border: 1px solid rgba(74,222,128,0.2); border-radius: 4px; padding: 2px 8px; font-weight: 600; font-size: 9px; } QPushButton:hover { background: rgba(74,222,128,0.2); }')
        left_sel_all.clicked.connect(lambda: self._set_all_players(True))
        left_btn_row.addWidget(left_sel_all)
        left_sel_none = QPushButton(t('player_item.deselect_all') if t else 'None')
        left_sel_none.setFixedHeight(22)
        left_sel_none.setStyleSheet('QPushButton { background: rgba(251,113,133,0.12); color: #FB7185; border: 1px solid rgba(251,113,133,0.2); border-radius: 4px; padding: 2px 8px; font-weight: 600; font-size: 9px; } QPushButton:hover { background: rgba(251,113,133,0.2); }')
        left_sel_none.clicked.connect(lambda: self._set_all_players(False))
        left_btn_row.addWidget(left_sel_none)
        left_btn_row.addStretch()
        left_layout.addLayout(left_btn_row)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setStyleSheet('QScrollArea { border: none; background: transparent; }')
        self.left_content = QWidget()
        self.left_layout_inner = QVBoxLayout(self.left_content)
        self.left_layout_inner.setContentsMargins(0, 0, 0, 0)
        self.left_layout_inner.setSpacing(2)
        left_scroll.setWidget(self.left_content)
        left_layout.addWidget(left_scroll, 1)
        right_panel = QFrame()
        right_panel.setStyleSheet('QFrame { background: rgba(0,0,0,0.15); border-radius: 6px; }')
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(6, 6, 6, 6)
        right_layout.setSpacing(4)
        self.right_header = QLabel(t('fix_illegal_pal.pals_header') if t else 'Illegal Pals')
        self.right_header.setStyleSheet('color: #93c5fd; font-size: 12px; font-weight: 700; padding: 2px 4px;')
        right_layout.addWidget(self.right_header)
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setStyleSheet('QScrollArea { border: none; background: transparent; }')
        self.right_content = QWidget()
        self.right_layout_inner = QVBoxLayout(self.right_content)
        self.right_layout_inner.setContentsMargins(0, 0, 0, 0)
        self.right_layout_inner.setSpacing(2)
        right_scroll.setWidget(self.right_content)
        right_layout.addWidget(right_scroll, 1)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([350, 650])
        layout.addWidget(splitter, 1)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet('color: rgba(255,255,255,0.1);')
        layout.addWidget(sep)
        action_row = QHBoxLayout()
        self.fix_btn = QPushButton(t('fix_illegal_pal.fix_selected') if t else 'Fix Selected')
        self.fix_btn.setStyleSheet('QPushButton { background: rgba(251,191,36,0.15); color: #fbbf24; border: 1px solid rgba(251,191,36,0.3); border-radius: 6px; padding: 8px 24px; font-weight: 600; font-size: 13px; } QPushButton:hover { background: rgba(251,191,36,0.25); border-color: rgba(251,191,36,0.5); color: #FFFFFF; } QPushButton:disabled { background: rgba(100,100,100,0.1); color: #666; border-color: rgba(100,100,100,0.2); }')
        self.fix_btn.setCursor(Qt.PointingHandCursor)
        self.fix_btn.clicked.connect(self._on_fix)
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
    def _update_summary(self):
        total_players = sum(1 for d in self.scan_data.values() if d['pal_count'] > 0)
        total_illegals = sum(d['pal_count'] for d in self.scan_data.values() if d['pal_count'] > 0)
        self.summary_label.setText(t('fix_illegal_pal.summary').format(players=total_players, pals=total_illegals) if t else f'Found {total_players} player(s) with {total_illegals} illegal pal(s)')
    def _select_first_player(self):
        for uid in sorted(self._player_cards.keys()):
            self._select_player(uid)
            return
    def _populate_players(self):
        self._player_cards = {}
        for uid_clean, data in sorted(self.scan_data.items(), key=lambda x: x[1].get('player_name', '')):
            if data['pal_count'] <= 0:
                continue
            card = PlayerCardWidget(uid_clean, data)
            card.clicked.connect(self._select_player)
            self.left_layout_inner.addWidget(card)
            self._player_cards[uid_clean] = card
        self.left_layout_inner.addStretch(1)
        self._update_summary()
        if self._player_cards:
            self.fix_btn.setEnabled(True)
    def _populate_all_pal_rows(self):
        for uid_clean, data in self.scan_data.items():
            u_rows = []
            for pal in data.get('illegals', []):
                row = PalRowWidget(pal)
                row.setVisible(False)
                self.right_layout_inner.addWidget(row)
                u_rows.append(row)
            self._player_pal_rows[uid_clean] = u_rows
        self.right_layout_inner.addStretch(1)
    def _select_player(self, uid):
        if self._selected_uid == uid:
            return
        if self._selected_uid and self._selected_uid in self._player_cards:
            self._player_cards[self._selected_uid].set_selected(False)
        for old_uid, rows in self._player_pal_rows.items():
            for r in rows:
                r.setVisible(False)
        self._selected_uid = uid
        if uid in self._player_cards:
            self._player_cards[uid].set_selected(True)
        data = self.scan_data.get(uid, {})
        pname = data.get('player_name', uid)
        self.right_header.setText(t('fix_illegal_pal.pals_for_header', name=pname) if t else f'Illegal Pals — {pname}')
        for r in self._player_pal_rows.get(uid, []):
            r.setVisible(True)
    def _set_all_players(self, checked):
        for card in self._player_cards.values():
            card.set_checked(checked)
    def _get_selected_uids(self):
        return [uid for uid, card in self._player_cards.items() if card.is_checked()]
    def _on_fix(self):
        uids = self._get_selected_uids()
        if not uids:
            self.status_label.setText(t('fix_illegal_pal.no_selection') if t else 'No players checked for fixing.')
            self.status_label.setStyleSheet('color: #ef4444; font-weight: bold; padding: 5px;')
            return
        self.accept()
