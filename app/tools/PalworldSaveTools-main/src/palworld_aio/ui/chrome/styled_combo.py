from PySide6.QtWidgets import QWidget, QPushButton, QFrame, QVBoxLayout, QListWidget, QListWidgetItem
from PySide6.QtCore import Qt, Signal, QPoint, QEvent
from PySide6.QtGui import QColor
class StyledCombo(QWidget):
    currentIndexChanged = Signal(int)
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self._current_index = -1
        self._enabled = True
        self._max_visible_items = 12
        self._setup_ui()
        self._update_styles()
    def _setup_ui(self):
        self._button = QPushButton()
        self._button.setFixedHeight(24)
        self._button.setCursor(Qt.PointingHandCursor)
        self._button.clicked.connect(self._toggle_popup)
        self._popup = QFrame(self, Qt.Popup)
        self._popup.setFixedWidth(300)
        self._popup.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self._popup.setAttribute(Qt.WA_TranslucentBackground)
        self._popup.setFocusPolicy(Qt.NoFocus)
        popup_layout = QVBoxLayout(self._popup)
        popup_layout.setContentsMargins(0, 0, 0, 0)
        popup_layout.setSpacing(0)
        self._list = QListWidget()
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.setFocusPolicy(Qt.NoFocus)
        popup_layout.addWidget(self._list)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self._button)
        self._popup.installEventFilter(self)
    def eventFilter(self, obj, event):
        if obj == self._popup:
            if event.type() == QEvent.MouseButtonPress:
                pos = self.mapFromGlobal(event.globalPosition().toPoint())
                if not self._popup.geometry().contains(pos):
                    self._hide_popup()
                    return True
        return super().eventFilter(obj, event)
    def _update_styles(self):
        self._button.setStyleSheet('\n            QPushButton {\n                background-color: rgba(30, 35, 45, 0.8);\n                border: 1px solid rgba(255, 255, 255, 0.2);\n                border-radius: 4px;\n                padding: 4px 8px;\n                color: #e0e0e0;\n                text-align: left;\n            }\n            QPushButton::menu-indicator {\n                width: 0px;\n                subcontrol-position: right center;\n                subcontrol-origin: padding;\n            }\n            QPushButton:hover {\n                border-color: rgba(74, 144, 226, 0.5);\n            }\n            QPushButton:disabled {\n                background-color: rgba(40, 45, 55, 0.6);\n                color: #888888;\n                border-color: rgba(255, 255, 255, 0.1);\n            }\n        ')
        self._popup.setStyleSheet('\n            QFrame {\n                background-color: transparent;\n            }\n        ')
        self._list.setStyleSheet('\n            QListWidget {\n                background-color: rgba(18, 20, 24, 0.98);\n                border: 1px solid rgba(125, 211, 252, 0.3);\n                border-radius: 6px;\n                padding: 4px;\n                color: #e2e8f0;\n            }\n            QListWidget::item {\n                padding: 6px 12px;\n                border-radius: 3px;\n                height: 28px;\n            }\n            QListWidget::item:selected {\n                background-color: rgba(125, 211, 252, 0.15);\n                color: #7DD3FC;\n            }\n            QListWidget::item:hover {\n                background-color: rgba(125, 211, 252, 0.08);\n            }\n            QListWidget::item:disabled {\n                color: #666666;\n                background-color: transparent;\n            }\n        ')
    def setMaxVisibleItems(self, count):
        self._max_visible_items = count
        self._update_popup_height()
    def _update_popup_height(self):
        item_height = 28
        max_height = self._max_visible_items * item_height + 8
        self._list.setMaximumHeight(max_height)
    def _toggle_popup(self):
        if not self._enabled:
            return
        if self._popup.isVisible():
            self._hide_popup()
        else:
            self._show_popup()
    def _show_popup(self):
        self._update_popup_height()
        self._list.setMinimumWidth(self._button.width() - 8)
        pos = self._button.mapToGlobal(QPoint(0, self._button.height()))
        self._popup.move(pos)
        self._popup.show()
        self._list.setFocus()
    def _hide_popup(self):
        self._popup.hide()
    def _on_item_clicked(self, item):
        index = self._list.row(item)
        if item.flags() & Qt.ItemIsEnabled:
            self._current_index = index
            self._button.setText(item.text())
            self._hide_popup()
            self.currentIndexChanged.emit(index)
    def addItem(self, text, userData=None):
        self._items.append({'text': text, 'userData': userData, 'enabled': True})
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, userData)
        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self._list.addItem(item)
        if self._current_index == -1:
            self.setCurrentIndex(0)
    def clear(self):
        self._items = []
        self._list.clear()
        self._current_index = -1
        self._button.setText('')
    def currentIndex(self):
        return self._current_index
    def currentData(self):
        if 0 <= self._current_index < len(self._items):
            return self._items[self._current_index]['userData']
        return None
    def setCurrentIndex(self, index):
        if 0 <= index < len(self._items):
            self._current_index = index
            self._items[index]['text']
            self._button.setText(self._items[index]['text'])
            self._list.setCurrentRow(index)
            return True
        return False
    def count(self):
        return len(self._items)
    def itemData(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]['userData']
        return None
    def setEnabled(self, enabled):
        self._enabled = enabled
        self._button.setEnabled(enabled)
        if not enabled:
            self._button.setText('')
            self._current_index = -1
    def setItemEnabled(self, index, enabled):
        if 0 <= index < len(self._items):
            self._items[index]['enabled'] = enabled
            item = self._list.item(index)
            if item:
                if enabled:
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                else:
                    item.setFlags(Qt.ItemIsSelectable & ~Qt.ItemIsEnabled)
    def blockSignals(self, block):
        self._list.blockSignals(block)
    def currentText(self):
        if 0 <= self._current_index < len(self._items):
            return self._items[self._current_index]['text']
        return ''
    def setItemText(self, index, text):
        if 0 <= index < len(self._items):
            self._items[index]['text'] = text
            item = self._list.item(index)
            if item:
                item.setText(text)
    def model(self):
        return self._list.model()
from PySide6.QtWidgets import QAbstractItemView