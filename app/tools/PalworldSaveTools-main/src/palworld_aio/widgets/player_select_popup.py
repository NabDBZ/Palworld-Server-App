from PySide6.QtWidgets import QWidget, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QApplication
from PySide6.QtCore import Qt, QThread, QPoint
from i18n import t
from palworld_aio.ui.chrome.styles import PICKER_SEARCH_STYLE, PICKER_LIST_STYLE, PICKER_BG_STYLE


def show_player_select_popup(anchor_btn, player_list, current_uid=None):
    popup = QWidget()
    popup.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
    popup.setStyleSheet(PICKER_BG_STYLE)
    layout = QVBoxLayout(popup)
    layout.setContentsMargins(4, 4, 4, 4)
    layout.setSpacing(2)

    search = QLineEdit()
    search.setPlaceholderText(t('inventory.search_players', default='Search players...'))
    search.setStyleSheet(PICKER_SEARCH_STYLE)
    layout.addWidget(search)

    lst = QListWidget()
    lst.setStyleSheet(PICKER_LIST_STYLE)
    lst.setMaximumHeight(300)
    lst.setMinimumWidth(220)
    clear_item = QListWidgetItem(t('common.clear') if t else '-- clear --')
    lst.addItem(clear_item)
    for player in player_list:
        if current_uid and str(player['uid']) == str(current_uid):
            continue
        item = QListWidgetItem(player['display'])
        item.setData(Qt.UserRole, player)
        lst.addItem(item)
    search.textChanged.connect(lambda t, l=lst: [l.item(i).setHidden(t.lower() not in l.item(i).text().lower()) for i in range(l.count())])
    layout.addWidget(lst)

    popup.setFixedWidth(anchor_btn.width())
    popup.move(anchor_btn.mapToGlobal(QPoint(0, anchor_btn.height())))
    screen = QApplication.primaryScreen()
    if screen:
        screen_geo = screen.availableGeometry()
        popup.adjustSize()
        ph = popup.sizeHint().height()
        if popup.y() + ph > screen_geo.bottom() and popup.y() - ph > screen_geo.top():
            popup.move(popup.x(), popup.y() - ph - anchor_btn.height())
    popup.show()
    search.setFocus()

    result = {'value': None}

    def on_select():
        sel = lst.currentItem()
        if sel:
            if sel is clear_item:
                result['value'] = '__clear__'
            elif sel.data(Qt.UserRole):
                result['value'] = sel.data(Qt.UserRole)
        popup.hide()

    lst.itemClicked.connect(on_select)
    search.returnPressed.connect(on_select)

    while popup.isVisible():
        QApplication.processEvents()
        QThread.msleep(5)

    return result['value']
