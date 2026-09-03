from import_libs import *
from loading_manager import show_warning, show_critical
from palworld_aio.ui.chrome.styles import ThemeManager
import nerdfont as nf
from palworld_aio import constants
def convert_steam_id():
    def do_convert(steam_input=None):
        steam_input = steam_entry.text().strip() if steam_input is None else steam_input
        if not steam_input:
            show_warning(dialog, t('Warning'), t('steamid.warn.enter_id'))
            return
        if 'steamcommunity.com/profiles/' in steam_input:
            steam_input = steam_input.split('steamcommunity.com/profiles/')[1].split('/')[0]
        elif steam_input.startswith('steam_'):
            steam_input = steam_input[6:]
        try:
            steam_id = int(steam_input)
            palworld_uid = steamIdToPlayerUid(steam_id)
            nosteam_uid = PlayerUid2NoSteam(int.from_bytes(toUUID(palworld_uid).raw_bytes[0:4], byteorder='little')) + '-0000-0000-0000-000000000000'
            result_label.setText(t('steamid.result', pal=str(palworld_uid).upper(), nosteam=nosteam_uid.upper()))
        except ValueError:
            show_critical(dialog, t('Error'), t('steamid.err.invalid'))
    dialog = QDialog()
    dialog.setWindowTitle(t('steamid.title'))
    try:
        dialog.setWindowIcon(QIcon(ICON_PATH))
    except:
        pass
    ThemeManager.load_styles(dialog)
    main_layout = QVBoxLayout(dialog)
    main_layout.setContentsMargins(14, 14, 14, 14)
    main_layout.setSpacing(12)
    glass_frame = QFrame()
    glass_frame.setObjectName('glass')
    glass_layout = QVBoxLayout(glass_frame)
    glass_layout.setContentsMargins(12, 12, 12, 12)
    glass_layout.setSpacing(12)
    main_layout.addWidget(glass_frame)
    glass_layout.addStretch(1)
    tip_label = QLabel(t('steamid.tip'))
    tip_label.setFont(QFont(constants.FONT_FAMILY, 10))
    tip_label.setAlignment(Qt.AlignCenter)
    glass_layout.addWidget(tip_label)
    hint_label = QLabel(t('steamid.local_hint'))
    hint_label.setFont(QFont(constants.FONT_FAMILY, 10))
    hint_label.setAlignment(Qt.AlignCenter)
    glass_layout.addWidget(hint_label)
    entry_layout = QHBoxLayout()
    entry_layout.addStretch()
    steam_entry = QLineEdit()
    steam_entry.setFont(QFont(constants.FONT_FAMILY, 10))
    steam_entry.setFixedWidth(300)
    entry_layout.addWidget(steam_entry)
    entry_layout.addStretch()
    glass_layout.addLayout(entry_layout)
    button_layout = QHBoxLayout()
    button_layout.addStretch()
    convert_button = QPushButton(t('steamid.btn.convert'))
    convert_button.setMinimumWidth(120)
    convert_button.setMaximumWidth(120)
    button_layout.addWidget(convert_button)
    button_layout.addStretch()
    glass_layout.addLayout(button_layout)
    result_label = QLabel()
    result_label.setFont(QFont(constants.FONT_FAMILY, 10))
    result_label.setWordWrap(True)
    result_label.setAlignment(Qt.AlignCenter)
    glass_layout.addWidget(result_label)
    copy_layout = QHBoxLayout()
    copy_layout.addStretch()
    copy_button = NerdBtn(f"{nf.icons['nf-cod-copy']}")
    copy_button.setFont(QFont(constants.FONT_FAMILY_NERD, 13))
    copy_button.setFixedSize(40, 40)
    copy_button.setStyleSheet('QPushButton { padding: 0px; border-radius: 6px; }')
    copy_layout.addWidget(copy_button)
    copy_layout.addStretch()
    glass_layout.addLayout(copy_layout)
    glass_layout.addStretch(1)
    convert_button.clicked.connect(lambda: do_convert())
    def copy_result():
        clipboard = QApplication.clipboard()
        clipboard.setText(result_label.text())
        copy_button.setText(f"{nf.icons['nf-md-checkbox_marked_circle']}")
        QTimer.singleShot(2000, lambda: copy_button.setText(f"{nf.icons['nf-cod-copy']}"))
    copy_button.clicked.connect(copy_result)
    dialog.adjustSize()
    center_window(dialog)
    dialog.setModal(True)
    return dialog
def center_window(win):
    screen = QApplication.primaryScreen().availableGeometry()
    size = win.sizeHint()
    if not size.isValid():
        win.adjustSize()
        size = win.size()
    win.move((screen.width() - size.width()) // 2, (screen.height() - size.height()) // 2)
def main():
    convert_steam_id()
if __name__ == '__main__':
    main()