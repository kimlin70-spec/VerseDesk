"""Small dialogs for folder zones, in Korean.

They are created WITHOUT a parent: a desktop widget as parent would become the dialog's
Windows owner, and showing an owned window pulls its owner (the zone) above other windows.
Button texts are set explicitly because Qt's translation files are not bundled in the exe.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QInputDialog, QLineEdit, QMessageBox

from versedesk.zones import NAME_MAX, clean_name

TITLE_NEW = "새 구역 추가"
TITLE_RENAME = "구역 이름 변경"
LABEL_NAME = "구역 이름:"
TITLE_DELETE = "구역 삭제"


def _bring_to_front(dialog) -> None:
    dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

    def activate():
        dialog.raise_()
        dialog.activateWindow()

    QTimer.singleShot(0, activate)


def ask_zone_name(title: str = TITLE_NEW, default: str = "") -> str | None:
    """The name the user typed (cleaned up), or None when cancelled."""
    dlg = QInputDialog(None)
    dlg.setWindowTitle(title)
    dlg.setLabelText(LABEL_NAME)
    dlg.setInputMode(QInputDialog.InputMode.TextInput)
    dlg.setTextValue(default)
    dlg.setOkButtonText("확인")
    dlg.setCancelButtonText("취소")
    edit = dlg.findChild(QLineEdit)
    if edit is not None:
        edit.setMaxLength(NAME_MAX)
    _bring_to_front(dlg)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    return clean_name(dlg.textValue())


def confirm_delete_zone(name: str, item_count: int) -> bool:
    box = QMessageBox(None)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(TITLE_DELETE)
    box.setText(f"'{name}' 구역을 삭제할까요?")
    box.setInformativeText(
        f"구역에 넣어 둔 폴더·파일 {item_count}개는 원래 자리에 그대로 남습니다.\n"
        "(구역의 목록에서만 사라집니다.)"
    )
    delete = box.addButton("삭제", QMessageBox.ButtonRole.AcceptRole)
    cancel = box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel)
    box.setEscapeButton(cancel)
    _bring_to_front(box)
    box.exec()
    return box.clickedButton() is delete
