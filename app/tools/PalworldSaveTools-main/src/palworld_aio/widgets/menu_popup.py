from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QFrame, QGraphicsDropShadowEffect, QMenu, QLabel, QScrollArea
from PySide6.QtCore import Qt, QPoint, Signal, QTimer, QEvent, QRect
from PySide6.QtGui import QFont, QColor, QCursor, QEnterEvent, QGuiApplication, QIcon
class nf:
    icons = {'nf-md-file': '📁', 'nf-md-function': '⚙️', 'nf-md-map': '🗺️', 'nf-md-playlist_remove': '🚫', 'nf-md-translate': '🌐', 'nf-md-cog': '⚙️', 'nf-md-chevron_right': '▶️', 'nf-md-update': '⬇️'}
from i18n import t
from palworld_aio import constants
class ScrollableMenu(QWidget):
    def __init__(self, parent=None, is_dark=True):
        super().__init__(parent)
        self.is_dark = True
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMaximumHeight(600)
        self.setMinimumWidth(220)
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setWidgetResizable(True)
        self.content_widget = QWidget()
        self.layout = QVBoxLayout(self.content_widget)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.scroll_area.setWidget(self.content_widget)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.scroll_area)
        self._update_theme()
    def _update_theme(self):
        bg = 'rgba(18,20,24,0.95)'
        border = 'rgba(125,211,252,0.2)'
        text_color = '#A6B8C8'
        hover_bg = 'rgba(125,211,252,0.1)'
        hover_color = '#7DD3FC'
        self.setStyleSheet(f'QWidget {{ background: {bg}; border: 1px solid {border}; border-radius: 10px; }} QPushButton {{ background: transparent; border: none; padding: 8px 12px; text-align: left; color: {text_color}; }} QPushButton:hover {{ background: {hover_bg}; color: {hover_color}; }}')
    def add_item(self, item):
        if isinstance(item, str) and item == 'separator_after':
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setFrameShadow(QFrame.Sunken)
            self.layout.addWidget(sep)
        elif len(item) >= 3 and item[2] == 'separator':
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setFrameShadow(QFrame.Sunken)
            self.layout.addWidget(sep)
        else:
            text, callback = (item[0], item[1])
            btn = QPushButton(text)
            btn.clicked.connect(lambda checked, cb=callback: self._on_menu_action(cb))
            self.layout.addWidget(btn)
    def _on_menu_action(self, callback):
        self.parent().close()
        callback()
    def hideEvent(self, event):
        self.parent()._on_menu_hidden()
        super().hideEvent(event)
class HoverMenuButton(QWidget):
    clicked = Signal()
    def __init__(self, category, icon_key, label, parent=None, is_dark=True):
        super().__init__(parent)
        self.category = category
        self.is_dark = is_dark
        try:
            icon = nf.icons.get(icon_key, '')
        except:
            icon = ''
        self.setObjectName('menuPopupButton')
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setMinimumWidth(180)
        self.setMinimumHeight(36)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        self.icon_label = QLabel(f'  {icon}')
        self.icon_label.setFont(QFont(constants.FONT_FAMILY, 11))
        layout.addWidget(self.icon_label)
        self.text_label = QLabel(label)
        self.text_label.setFont(QFont(constants.FONT_FAMILY, 11))
        layout.addWidget(self.text_label)
        layout.addStretch()
        self.chevron_label = QLabel('▶')
        self.chevron_label.setFont(QFont(constants.FONT_FAMILY, 11))
        layout.addWidget(self.chevron_label)
        self._update_theme()
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._on_clicked()
        super().mousePressEvent(event)
    def _on_clicked(self):
        self._show_submenu()
    def setText(self, text):
        self.text_label.setText(text)
    def text(self):
        return self.text_label.text()
    def _update_theme(self):
        color = '#A6B8C8'
        hover_bg = 'rgba(125,211,252,0.1)'
        hover_color = '#7DD3FC'
        active_bg = 'rgba(125,211,252,0.15)'
        active_color = '#7DD3FC'
        active_border = '#7DD3FC'
        pressed_bg = 'rgba(125,211,252,0.2)'
        self.setStyleSheet(f'\n            QWidget#menuPopupButton {{\n                background: transparent;\n                border: none;\n                border-radius: 6px;\n            }}\n            QWidget#menuPopupButton[hovered="true"] {{\n                background: {hover_bg};\n            }}\n            QWidget#menuPopupButton[active="true"] {{\n                background: {active_bg};\n                border-left: 3px solid {active_border};\n            }}\n            QLabel {{\n                color: {color};\n                background: transparent;\n                border: none;\n            }}\n            QWidget#menuPopupButton[hovered="true"] QLabel {{\n                color: {hover_color};\n            }}\n            QWidget#menuPopupButton[active="true"] QLabel {{\n                color: {active_color};\n            }}\n            ')
    def _show_submenu(self):
        parent_popup = self.parent()
        while parent_popup and (not isinstance(parent_popup, MenuPopup)):
            parent_popup = parent_popup.parent()
        if parent_popup and isinstance(parent_popup, MenuPopup):
            parent_popup._show_submenu(self.category, self)
class MenuPopup(QWidget):
    popup_closed = Signal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_dark = True
        self.setObjectName('menuPopup')
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._menu_actions = {}
        self._current_menu = None
        self._current_category = None
        self._cursor_timer = QTimer(self)
        self._cursor_timer.timeout.connect(self._check_cursor_position)
        self._setup_ui()
    def _is_point_in_widget(self, point, widget):
        if not widget.isVisible():
            return False
        global_pos = widget.mapToGlobal(QPoint(0, 0))
        rect = widget.rect()
        global_rect = QRect(global_pos, rect.size())
        return global_rect.contains(point)
    def _check_cursor_position(self):
        cursor_pos = QGuiApplication.primaryScreen().availableGeometry().topLeft() + QCursor.pos()
        cursor_pos = QCursor.pos()
        over_button = None
        for category, btn in self.menu_buttons.items():
            is_hovered = self._is_point_in_widget(cursor_pos, btn)
            btn.setProperty('hovered', is_hovered)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            if is_hovered:
                over_button = category
        over_popup = self._is_point_in_widget(cursor_pos, self)
        over_submenu = False
        if self._current_menu:
            over_submenu = self._is_point_in_widget(cursor_pos, self._current_menu)
            if not over_submenu:
                for child in self._current_menu.findChildren(QMenu):
                    if child.isVisible() and self._is_point_in_widget(cursor_pos, child):
                        over_submenu = True
                        break
        if over_button and over_button != self._current_category:
            self._show_submenu(over_button, self.menu_buttons[over_button])
        elif not over_button and (not over_popup) and (not over_submenu):
            self._close_current_menu()
    def _close_current_menu(self):
        if self._current_menu:
            self._current_menu.hide()
            self._current_menu = None
        old_category = self._current_category
        self._current_category = None
        if old_category:
            self._update_button_highlight(old_category, False)
    def _setup_ui(self):
        self.container = QFrame(self)
        self.container.setObjectName('menuPopupContainer')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.container)
        inner_layout = QVBoxLayout(self.container)
        inner_layout.setContentsMargins(8, 8, 8, 8)
        inner_layout.setSpacing(4)
        self.menu_buttons = {}
        categories = [('file', 'nf-md-file', t('deletion.menu.file') if t else 'File'), ('functions', 'nf-md-function', t('deletion.menu.delete') if t else 'Functions'), ('maps', 'nf-md-map', t('deletion.menu.view') if t else 'Maps'), ('exclusions', 'nf-md-playlist_remove', t('deletion.menu.exclusions') if t else 'Exclusions'), ('languages', 'nf-md-translate', t('lang.label') if t else 'Languages'), ('configs', 'nf-md-cog', t('deletion.menu.configs') if t else 'Configs')]
        for key, icon_key, label in categories:
            btn = self._create_menu_button(key, icon_key, label)
            inner_layout.addWidget(btn)
            self.menu_buttons[key] = btn
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setOffset(3, 3)
        shadow.setColor(QColor(0, 0, 0, 120))
        self.container.setGraphicsEffect(shadow)
        self._update_theme()
    def _create_menu_button(self, key, icon_key, label):
        btn = HoverMenuButton(key, icon_key, label, self.container, self.is_dark)
        return btn
    def set_menu_actions(self, actions_dict):
        self._menu_actions = actions_dict
    def _show_submenu(self, category, button):
        self._close_current_menu()
        if category not in self._menu_actions:
            return
        actions = self._menu_actions.get(category, [])
        if not actions:
            return
        self._clear_all_highlights()
        menu = QMenu(self)
        menu.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        menu.setAttribute(Qt.WA_TranslucentBackground)
        qmenu_style = 'QMenu { background: rgba(18,20,24,0.95); border: 1px solid rgba(125,211,252,0.2); color: #A6B8C8; min-width: 220px; font: 10pt "Segoe UI"; } QMenu::item:selected { background: rgba(125,211,252,0.1); color: #7DD3FC; } QMenu::item { padding: 8px 12px; min-width: 180px; }'
        menu.setStyleSheet(qmenu_style)
        for item in actions:
            if len(item) >= 3 and item[2] == 'separator':
                menu.addSeparator()
                continue
            text, callback = (item[0], item[1])
            if isinstance(callback, (list, tuple)):
                sub = menu.addMenu(text)
                sub.setStyleSheet(qmenu_style)
                for sub_text, sub_cb in callback:
                    a = sub.addAction(sub_text)
                    a.triggered.connect(lambda checked=False, cb=sub_cb: self._on_menu_action(cb))
            else:
                action = menu.addAction(text)
                if len(item) >= 3 and item[2] != 'separator':
                    action.setIcon(QIcon(item[2]))
                action.triggered.connect(lambda checked, cb=callback: self._on_menu_action(cb))
        btn_pos = button.mapToGlobal(QPoint(button.width(), 0))
        self._current_menu = menu
        self._current_submenu = None
        self._current_category = category
        self._update_button_highlight(category, True)
        menu.aboutToHide.connect(self._on_menu_hidden)
        menu.show()
        menu.move(btn_pos)
        menu.raise_()
    def _show_submenu_abs(self, sub, parent_menu):
        if sub.isVisible():
            return
        self._close_current_submenu()
        self._current_submenu = sub
        pos = parent_menu.mapToGlobal(QPoint(parent_menu.width(), 0))
        sub.aboutToHide.connect(self._on_submenu_hidden)
        sub.show()
        sub.move(pos)
        sub.raise_()
    def _clear_all_highlights(self):
        for category, btn in self.menu_buttons.items():
            btn.setProperty('active', False)
            btn.setProperty('hovered', False)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
    def _update_button_highlight(self, category, active):
        if category in self.menu_buttons:
            btn = self.menu_buttons[category]
            btn.setProperty('active', active)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
    def _on_menu_action(self, callback):
        self.close()
        callback()
    def _on_menu_hidden(self):
        self._current_menu = None
    def hideEvent(self, event):
        self._cursor_timer.stop()
        self._close_current_menu()
        self._clear_all_highlights()
        super().hideEvent(event)
    def refresh_labels(self):
        labels = {'file': t('deletion.menu.file') if t else 'File', 'functions': t('deletion.menu.delete') if t else 'Functions', 'maps': t('deletion.menu.view') if t else 'Maps', 'exclusions': t('deletion.menu.exclusions') if t else 'Exclusions', 'languages': t('lang.label') if t else 'Languages', 'configs': t('deletion.menu.configs') if t else 'Configs'}
        icon_map = {'file': 'nf-md-file', 'functions': 'nf-md-function', 'maps': 'nf-md-map', 'exclusions': 'nf-md-playlist_remove', 'languages': 'nf-md-translate', 'configs': 'nf-md-cog'}
        for category, btn in self.menu_buttons.items():
            if category in labels:
                try:
                    icon = nf.icons.get(icon_map.get(category, ''), '')
                except:
                    icon = ''
                btn.icon_label.setText(f'  {icon}')
                btn.text_label.setText(labels[category])
    def update_theme(self, is_dark):
        self.is_dark = is_dark
        self._update_theme()
        for btn in self.menu_buttons.values():
            btn.is_dark = is_dark
            btn._update_theme()
        if self._current_menu and hasattr(self._current_menu, '_update_theme'):
            self._current_menu.is_dark = is_dark
            self._current_menu._update_theme()
    def _update_theme(self):
        bg = 'rgba(18,20,24,0.95)'
        border = 'rgba(125,211,252,0.2)'
        self.container.setStyleSheet(f'\n            QFrame#menuPopupContainer {{\n                background: {bg};\n                border: 1px solid {border};\n                border-radius: 10px;\n            }}\n        ')
    def show_at(self, global_pos):
        self.adjustSize()
        self.move(global_pos)
        self.show()
        self.raise_()
        self._cursor_timer.start(10)