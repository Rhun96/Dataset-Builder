"""Диалог авто-подбора: объяснение рекомендации и утверждение пользователем."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QTextEdit,
    QVBoxLayout,
)


class ProposalDialog(QDialog):
    def __init__(self, explanation: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Авто-подбор объёма")
        self.resize(520, 380)
        layout = QVBoxLayout(self)
        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setText("\n\n".join(f"• {line}" for line in explanation))
        layout.addWidget(txt)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("Применить")
        btns.button(QDialogButtonBox.Cancel).setText("Отмена")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
