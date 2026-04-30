"""Editor window: toolbar + canvas + save/copy actions."""
from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QCursor, QFont, QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QColorDialog,
    QFileDialog,
    QFontComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QToolBar,
    QToolButton,
    QWidget,
    QComboBox,
)

from ..paths import default_save_dir
from ..settings import get_settings
from ..tray import app_icon
from ..utils.clipboard import copy_image
from ..utils.image import expand_filename, save_png
from .canvas import Canvas
from .. import __version__


TOOLS = [
    ("rect", "사각형", "R"),
    ("ellipse", "원", "E"),
    ("arrow", "화살표", "A"),
    ("pen", "라인", "L"),
    ("highlight", "형광펜", "H"),
    ("text", "텍스트", "T"),
    ("mosaic", "모자이크", "M"),
]

class EditorWindow(QMainWindow):
    saved = Signal(Path)

    def __init__(self, image: Image.Image) -> None:
        super().__init__()
        self.setWindowTitle(f"snaplab v{__version__} — 편집")
        self.setWindowIcon(app_icon())
        self._settings = get_settings()

        self._canvas = Canvas(image)
        self._canvas.set_zoom(self._initial_zoom(image))
        self._updating_text_panel = False
        self._apply_theme()

        self.setCentralWidget(self._canvas)

        self._build_toolbar()
        self._build_text_toolbar()
        self._build_action_bar()
        self._wire_shortcuts()
        self._canvas.text_selection_changed.connect(self._on_text_selection_changed)
        # Zoom percentage indicator at the bottom-right of the status bar.
        self._zoom_label = QLabel()
        self._zoom_label.setToolTip("Ctrl + 마우스 휠로 확대/축소")
        self._zoom_label.setStyleSheet(
            "QLabel { padding: 0 10px; color: #cbd5e1; }"
        )
        self.statusBar().addPermanentWidget(self._zoom_label)
        self._canvas.zoom_changed.connect(self._update_zoom_label)
        self._update_zoom_label(self._canvas.zoom())
        self._on_tool("rect")

        # Bind to the target screen via Qt's official setter. Avoids touching
        # the native handle ourselves and is the supported way to make a
        # not-yet-shown widget appear on a specific monitor with the right DPR.
        target_screen = self._screen_for_editor()
        if target_screen is not None:
            try:
                self.setScreen(target_screen)
            except Exception:
                pass

        target_size = self._initial_window_size(image)
        self.resize(target_size)
        if target_screen is not None:
            avail = target_screen.availableGeometry()
            self.setMaximumSize(
                max(target_size.width(), avail.width()),
                avail.height(),
            )
            # Position on the target screen so Qt doesn't drop the window on
            # the primary first and migrate it (which is what causes the
            # mixed-DPI resize quirk).
            self.move(avail.left() + 40, avail.top() + 40)

    def _screen_for_editor(self):
        screen = QGuiApplication.screenAt(QCursor.pos())
        return screen or QGuiApplication.primaryScreen()

    def _initial_zoom(self, image: Image.Image) -> float:
        screen = self._screen_for_editor()
        dpr = screen.devicePixelRatio() if screen else 1.0
        available = screen.availableGeometry() if screen else None
        if available is None:
            return min(1.0, 1.0 / max(1.0, dpr))

        max_canvas_w = max(640, available.width() - 120)
        max_canvas_h = max(420, available.height() - 220)
        fit_zoom = min(max_canvas_w / max(1, image.width), max_canvas_h / max(1, image.height))
        return max(0.08, min(1.0, 1.0 / max(1.0, dpr), fit_zoom))

    # Editor window initial size will never exceed this fraction of the user's
    # available screen. Save/copy still operates on the full-resolution capture;
    # the user can Ctrl+Wheel zoom inside the editor to inspect at 100%.
    MAX_SCREEN_FRACTION = 0.9

    def _initial_window_size(self, image: Image.Image) -> QSize:
        screen = self._screen_for_editor()
        available = screen.availableGeometry() if screen else None
        zoom = self._canvas.zoom()
        target_w = int(round(image.width * zoom)) + 72
        target_h = int(round(image.height * zoom)) + 190
        if available is not None:
            cap_w = max(760, int(available.width() * self.MAX_SCREEN_FRACTION))
            cap_h = max(560, int(available.height() * self.MAX_SCREEN_FRACTION))
            target_w = min(target_w, cap_w)
            target_h = min(target_h, cap_h)
        return QSize(max(760, target_w), max(560, target_h))

    # --- UI ----------------------------------------------------------------

    def _build_toolbar(self) -> None:
        bar = QToolBar("도구")
        bar.setMovable(False)
        bar.setIconSize(QSize(20, 20))
        self.addToolBar(Qt.TopToolBarArea, bar)

        self._tool_buttons: dict[str, QToolButton] = {}
        for key, label, shortcut in TOOLS:
            btn = QToolButton()
            btn.setText(label)
            btn.setToolTip(f"{label} ({shortcut})")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, k=key: self._on_tool(k))
            bar.addWidget(btn)
            self._tool_buttons[key] = btn
        bar.addSeparator()

        bar.addWidget(QLabel(" 색상: "))
        self._color_btn = QPushButton()
        self._color_btn.setFixedSize(28, 22)
        self._color_btn.clicked.connect(self._pick_color)
        self._set_color_button(QColor(232, 60, 60))
        bar.addWidget(self._color_btn)

        bar.addWidget(QLabel("  굵기: "))
        self._width_spin = QSpinBox()
        self._width_spin.setRange(1, 30)
        self._width_spin.setValue(3)
        self._width_spin.valueChanged.connect(self._canvas.set_width)
        bar.addWidget(self._width_spin)

        bar.addSeparator()
        undo = QAction("↶ Undo", self)
        undo.setShortcut(QKeySequence.Undo)
        undo.triggered.connect(self._canvas.undo)
        bar.addAction(undo)

        redo = QAction("↷ Redo", self)
        redo.setShortcut(QKeySequence.Redo)
        redo.triggered.connect(self._canvas.redo)
        bar.addAction(redo)

        clear = QAction("모두 지우기", self)
        clear.triggered.connect(self._canvas.clear_annotations)
        bar.addAction(clear)

    def _build_text_toolbar(self) -> None:
        bar = QToolBar("텍스트")
        self._text_bar = bar
        bar.setMovable(False)
        bar.setIconSize(QSize(20, 20))
        self.addToolBarBreak(Qt.TopToolBarArea)
        self.addToolBar(Qt.TopToolBarArea, bar)

        bar.addWidget(QLabel("텍스트 내용: "))
        self._text_edit = QLineEdit()
        self._text_edit.setFixedWidth(320)
        self._text_edit.textChanged.connect(self._on_text_panel_changed)
        bar.addWidget(self._text_edit)

        bar.addWidget(QLabel("  폰트: "))
        self._font_combo = QFontComboBox()
        self._font_combo.setFixedWidth(180)
        self._font_combo.currentFontChanged.connect(self._on_text_panel_changed)
        bar.addWidget(self._font_combo)

        bar.addWidget(QLabel("  크기: "))
        self._font_size_spin = QSpinBox()
        self._font_size_spin.setRange(6, 180)
        self._font_size_spin.setValue(24)
        self._font_size_spin.valueChanged.connect(self._on_text_panel_changed)
        bar.addWidget(self._font_size_spin)

        bar.addWidget(QLabel("  정렬: "))
        self._align_combo = QComboBox()
        self._align_combo.addItem("왼쪽", "left")
        self._align_combo.addItem("가운데", "center")
        self._align_combo.addItem("오른쪽", "right")
        self._align_combo.currentIndexChanged.connect(self._on_text_panel_changed)
        bar.addWidget(self._align_combo)
        for w in (self._text_edit, self._font_combo, self._font_size_spin, self._align_combo):
            w.setEnabled(False)
        bar.hide()

    def _build_action_bar(self) -> None:
        bar = QToolBar("액션")
        bar.setMovable(False)
        self.addToolBar(Qt.BottomToolBarArea, bar)

        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().horizontalPolicy(), spacer.sizePolicy().verticalPolicy())
        bar.addWidget(spacer)

        copy_btn = QPushButton("📋 복사 (Ctrl+C)")
        copy_btn.clicked.connect(self.copy_to_clipboard)
        bar.addWidget(copy_btn)

        save_btn = QPushButton("💾 저장 (Ctrl+S)")
        save_btn.clicked.connect(self.save_default)
        bar.addWidget(save_btn)

        save_as_btn = QPushButton("다른 이름으로 저장…")
        save_as_btn.clicked.connect(self.save_as)
        bar.addWidget(save_as_btn)

        pin_btn = QPushButton("📌 핀")
        pin_btn.clicked.connect(self.pin_to_screen)
        bar.addWidget(pin_btn)

    def _wire_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.save_default)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self, activated=self.save_as)
        QShortcut(QKeySequence("Ctrl+C"), self, activated=self.copy_to_clipboard)
        for key, _label, shortcut in TOOLS:
            QShortcut(QKeySequence(shortcut), self, activated=lambda k=key: self._on_tool(k))
        QShortcut(QKeySequence("Delete"), self, activated=self._canvas.clear_annotations)

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow {
                background: #101318;
                color: #E8EEF7;
            }
            QGraphicsView, QScrollArea {
                background: #0B0E13;
                border: 0;
            }
            QToolBar {
                background: #171B22;
                border: 0;
                border-bottom: 1px solid #2A3340;
                spacing: 6px;
                padding: 8px;
            }
            QToolBar QLabel {
                color: #AEB8C6;
                font-weight: 600;
            }
            QToolButton, QPushButton {
                background: #222936;
                color: #E8EEF7;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 6px 10px;
                font-weight: 600;
            }
            QToolButton:hover, QPushButton:hover {
                background: #2B3545;
                border-color: #3B82F6;
            }
            QToolButton:checked {
                background: #2563EB;
                border-color: #60A5FA;
                color: white;
            }
            QLineEdit, QSpinBox, QComboBox, QFontComboBox {
                background: #0F1722;
                color: #E8EEF7;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 5px 8px;
                min-height: 24px;
            }
            QMenu {
                background: #171B22;
                color: #E8EEF7;
                border: 1px solid #334155;
            }
            QStatusBar {
                background: #101318;
                color: #AEB8C6;
                border-top: 1px solid #2A3340;
            }
            QScrollBar:vertical, QScrollBar:horizontal {
                background: #111827;
                border: 0;
                margin: 0;
            }
            QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
                background: #334155;
                border-radius: 4px;
                min-height: 36px;
                min-width: 36px;
            }
            QScrollBar::handle:hover {
                background: #475569;
            }
            """
        )

    # --- handlers ----------------------------------------------------------

    def _on_tool(self, key: str) -> None:
        for k, btn in self._tool_buttons.items():
            btn.setChecked(k == key)
        self._text_bar.setVisible(key == "text")
        self._canvas.set_tool(key)  # type: ignore[arg-type]

    def _pick_color(self) -> None:
        col = QColorDialog.getColor(self._color_btn.palette().button().color(), self, "색상")
        if col.isValid():
            self._set_color_button(col)
            self._canvas.set_color(col)

    def _set_color_button(self, col: QColor) -> None:
        self._color_btn.setStyleSheet(
            f"background-color: {col.name()}; border: 1px solid #888; border-radius: 4px;"
        )
        self._canvas.set_color(col)
        self._canvas.update_selected_text(color=col)

    def _update_zoom_label(self, zoom: float) -> None:
        self._zoom_label.setText(f"{int(round(zoom * 100))}%")

    def _on_text_selection_changed(self, ann) -> None:
        self._updating_text_panel = True
        enabled = ann is not None
        for w in (self._text_edit, self._font_combo, self._font_size_spin, self._align_combo):
            w.setEnabled(enabled)
        if ann is not None:
            self._text_edit.setText(ann.text)
            self._font_combo.setCurrentFont(QFont(ann.font_family))
            self._font_size_spin.setValue(ann.font_size)
            idx = self._align_combo.findData(ann.text_align)
            self._align_combo.setCurrentIndex(max(0, idx))
            self._set_color_button_no_canvas(ann.style.color)
        self._updating_text_panel = False

    def _set_color_button_no_canvas(self, col: QColor) -> None:
        self._color_btn.setStyleSheet(
            f"background-color: {col.name()}; border: 1px solid #888; border-radius: 4px;"
        )

    def _on_text_panel_changed(self, *_) -> None:
        if self._updating_text_panel:
            return
        self._canvas.update_selected_text(
            text=self._text_edit.text(),
            font_family=self._font_combo.currentFont().family(),
            font_size=self._font_size_spin.value(),
            align=self._align_combo.currentData() or "left",
        )

    def copy_to_clipboard(self) -> None:
        copy_image(self._canvas.render_pil())
        self.statusBar().showMessage("클립보드에 복사됨", 1800)

    def save_default(self) -> None:
        save_dir = Path(self._settings.get("save_dir") or default_save_dir())
        pattern = self._settings.get("filename_pattern") or "snaplab_{datetime}"
        name = expand_filename(pattern) + ".png"
        path = save_dir / name
        try:
            save_png(self._canvas.render_pil(), path)
            self.saved.emit(path)
            self.statusBar().showMessage(f"저장됨: {path}", 3000)
        except OSError as e:
            QMessageBox.warning(self, "저장 실패", str(e))

    def save_as(self) -> None:
        save_dir = self._settings.get("save_dir") or str(default_save_dir())
        suggested = str(Path(save_dir) / (expand_filename(self._settings.get("filename_pattern") or "snaplab_{datetime}") + ".png"))
        path, _ = QFileDialog.getSaveFileName(self, "다른 이름으로 저장", suggested, "PNG Image (*.png);;JPEG (*.jpg *.jpeg)")
        if not path:
            return
        try:
            img = self._canvas.render_pil()
            if path.lower().endswith((".jpg", ".jpeg")):
                img.convert("RGB").save(path, "JPEG", quality=92)
            else:
                if not path.lower().endswith(".png"):
                    path += ".png"
                img.save(path, "PNG")
            self.saved.emit(Path(path))
            self.statusBar().showMessage(f"저장됨: {path}", 3000)
        except OSError as e:
            QMessageBox.warning(self, "저장 실패", str(e))

    def run_ocr(self) -> None:
        from ..features.ocr import extract_text, OcrError

        try:
            langs = self._settings.get("ocr_languages") or "eng"
            text = extract_text(self._canvas.render_pil(), langs)
        except OcrError as e:
            QMessageBox.information(self, "OCR 사용 불가", str(e))
            return
        if not text.strip():
            self.statusBar().showMessage("추출된 텍스트가 없습니다", 2500)
            return
        from ..utils.clipboard import copy_text

        copy_text(text)
        QMessageBox.information(self, "OCR 결과 (클립보드 복사됨)", text)

    def pin_to_screen(self) -> None:
        from ..features.pin import PinWindow

        pin = PinWindow(self._canvas.render_pil())
        pin.show()
        # Keep a reference on the QApplication so it isn't GC'd.
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            pins = getattr(app, "_pins", None)
            if pins is None:
                pins = []
                app._pins = pins  # type: ignore[attr-defined]
            pins.append(pin)
