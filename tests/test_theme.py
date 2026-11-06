"""Тема и статусы применяются без падений."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QWidget  # noqa: E402
from qfluentwidgets import PrimaryPushButton, TableWidget  # noqa: E402

from ui.theme import apply_theme, polish_table, set_status  # noqa: E402


def test_theme_helpers(tmp_path):
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    assert app.styleSheet()
    lbl = QLabel()
    set_status(lbl, "готово", "ok")
    assert "E6F4EA" in lbl.styleSheet() and lbl.text() == "готово"
    set_status(lbl, "плохо", "block")
    assert "FDE7E9" in lbl.styleSheet()
    tbl = TableWidget()
    tbl.setColumnCount(1)
    tbl.setRowCount(1)
    polish_table(tbl)
    assert not tbl.verticalHeader().isVisibleTo(tbl)
    btn = PrimaryPushButton("Тест")
    assert btn.text() == "Тест"
    from PySide6.QtWidgets import QVBoxLayout  # noqa: E402
    from ui.theme import wrap_in_scroll  # noqa: E402
    host = QWidget()
    lay = QVBoxLayout(host)
    lay.addWidget(QLabel("x"))
    wrap_in_scroll(host)
    from PySide6.QtWidgets import QScrollArea  # noqa: E402
    inner = host.findChild(QScrollArea)
    assert inner is not None and inner.viewport().autoFillBackground()
    from ui.theme import _scroll_bg  # noqa: E402
    assert _scroll_bg() in inner.widget().styleSheet()


def test_theme_qss_and_settings(tmp_path):
    from ui.settings_screen import SettingsScreen  # noqa: E402
    from ui.theme import app_qss, saved_native_frame, saved_theme  # noqa: E402
    assert "TableWidget::item" in app_qss() and "QHeaderView::section" in app_qss()
    assert "TableWidget::item" in app_qss(dark=True)
    from ui.theme import _scroll_bg  # noqa: E402
    assert _scroll_bg() in ("#14161A", "#F2F4F7")
    assert "QLabel { color" in app_qss(dark=True)
    assert "QLabel { color" not in app_qss()
    assert saved_theme() in ("light", "dark", "auto")
    assert isinstance(saved_native_frame(), bool)
    from qfluentwidgets import qconfig  # noqa: E402
    from ui.theme import ACCENT, GRAPHITE_BG  # noqa: E402
    assert ACCENT.lower() == "#f5a524"
    assert qconfig.themeColor.value.name().lower() == ACCENT.lower()
    assert GRAPHITE_BG.startswith("#")
    QApplication.instance() or QApplication([])
    w = SettingsScreen(str(tmp_path / "ws.sqlite"))
    assert w.cmb_theme.count() == 3
    w.close()


def test_main_window(tmp_path):
    from ui.app import MainWindow, center_on_screen  # noqa: E402
    QApplication.instance() or QApplication([])
    w = MainWindow(str(tmp_path / "ws.sqlite"))
    assert w.stackedWidget.count() == 5
    names = [w.stackedWidget.widget(i).objectName() for i in range(5)]
    assert names[1].startswith("1 ·") and names[2].startswith("2 ·")
    assert names[3].startswith("3 ·")
    center_on_screen(w)
    assert w.width() > 0 and w.height() > 0
    w.close()
    w2 = MainWindow(str(tmp_path / "ws.sqlite"), native_frame=True)
    assert not w2.titleBar.isVisible()
    w2.close()
