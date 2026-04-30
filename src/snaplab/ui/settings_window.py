"""Tabbed settings dialog."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import autostart
from ..hotkeys import HOTKEY_KEYS
from ..settings import DEFAULTS, get_settings
from ..tray import app_icon
from .hotkey_edit import HotkeyEdit


HOTKEY_LABELS = {
    "hotkey_area": "영역 캡처",
    "hotkey_fullscreen": "전체 화면",
    "hotkey_window": "활성 창",
    "hotkey_scroll": "브라우저 스크롤 (전체 페이지)",
    "hotkey_color_picker": "컬러 피커",
    "hotkey_delay": "딜레이 캡처",
}


class SettingsWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("snaplab — 설정")
        self.setWindowIcon(app_icon())
        self.resize(560, 540)
        self._settings = get_settings()

        tabs = QTabWidget()
        tabs.addTab(self._build_general_tab(), "일반")
        tabs.addTab(self._build_hotkeys_tab(), "단축키")
        tabs.addTab(self._build_browser_tab(), "브라우저 캡처")
        tabs.addTab(self._build_about_tab(), "정보")
        self.setCentralWidget(tabs)

    # --- tabs --------------------------------------------------------------

    def _build_general_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        startup = QGroupBox("시작 / 트레이")
        form = QFormLayout(startup)
        self._cb_autostart = QCheckBox("로그인 시 자동 시작")
        self._cb_autostart.setChecked(bool(self._settings.get("autostart")) and autostart.is_enabled())
        self._cb_autostart.stateChanged.connect(self._on_autostart_changed)
        form.addRow(self._cb_autostart)

        self._cb_tray = QCheckBox("시스템 트레이에 상주")
        self._cb_tray.setChecked(bool(self._settings.get("tray_enabled")))
        self._cb_tray.stateChanged.connect(
            lambda s: self._settings.set("tray_enabled", bool(s))
        )
        form.addRow(self._cb_tray)
        layout.addWidget(startup)

        save_box = QGroupBox("저장")
        sf = QFormLayout(save_box)
        path_row = QHBoxLayout()
        self._save_dir_edit = QLineEdit(self._settings.get("save_dir") or "")
        self._save_dir_edit.editingFinished.connect(
            lambda: self._settings.set("save_dir", self._save_dir_edit.text())
        )
        browse_btn = QPushButton("…")
        browse_btn.setFixedWidth(36)
        browse_btn.clicked.connect(self._pick_save_dir)
        path_row.addWidget(self._save_dir_edit)
        path_row.addWidget(browse_btn)
        sf.addRow("저장 폴더:", path_row)

        self._pattern_edit = QLineEdit(self._settings.get("filename_pattern") or "")
        self._pattern_edit.setPlaceholderText("예: snaplab_{date}_{time}")
        self._pattern_edit.editingFinished.connect(
            lambda: self._settings.set("filename_pattern", self._pattern_edit.text())
        )
        sf.addRow("파일명 패턴:", self._pattern_edit)
        sf.addRow(QLabel("플레이스홀더: {date}, {time}, {datetime}"))
        layout.addWidget(save_box)

        flow_box = QGroupBox("캡처 후 동작")
        ff = QFormLayout(flow_box)
        self._cb_open_editor = QCheckBox("편집기 열기")
        self._cb_open_editor.setChecked(bool(self._settings.get("open_editor_after_capture")))
        self._cb_open_editor.stateChanged.connect(
            lambda s: self._settings.set("open_editor_after_capture", bool(s))
        )
        ff.addRow(self._cb_open_editor)

        self._cb_clipboard = QCheckBox("자동으로 클립보드에 복사")
        self._cb_clipboard.setChecked(bool(self._settings.get("copy_to_clipboard_after_capture")))
        self._cb_clipboard.stateChanged.connect(
            lambda s: self._settings.set("copy_to_clipboard_after_capture", bool(s))
        )
        ff.addRow(self._cb_clipboard)

        self._cb_autosave = QCheckBox("자동 저장 (편집기 없이 바로 저장)")
        self._cb_autosave.setChecked(bool(self._settings.get("auto_save_after_capture")))
        self._cb_autosave.stateChanged.connect(
            lambda s: self._settings.set("auto_save_after_capture", bool(s))
        )
        ff.addRow(self._cb_autosave)

        self._delay_spin = QSpinBox()
        self._delay_spin.setRange(1, 30)
        self._delay_spin.setValue(int(self._settings.get("delay_seconds") or 3))
        self._delay_spin.setSuffix(" 초")
        self._delay_spin.valueChanged.connect(
            lambda v: self._settings.set("delay_seconds", int(v))
        )
        ff.addRow("딜레이 캡처 시간:", self._delay_spin)

        self._hist_spin = QSpinBox()
        self._hist_spin.setRange(10, 10)
        self._hist_spin.setValue(10)
        self._hist_spin.setEnabled(False)
        ff.addRow("히스토리 보관 수:", self._hist_spin)

        layout.addWidget(flow_box)
        layout.addStretch(1)
        return w

    def _build_hotkeys_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        intro = QLabel(
            "각 항목을 클릭한 뒤 원하는 키 조합을 입력하세요.\n"
            "Backspace로 비울 수 있고, Esc로 입력을 취소합니다.\n"
            "수정 후 자동 저장되며 글로벌 단축키가 즉시 갱신됩니다."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self._hotkey_edits: dict[str, HotkeyEdit] = {}
        for key in HOTKEY_KEYS.keys():
            edit = HotkeyEdit(self._settings.get(key) or "")
            edit.hotkey_changed.connect(lambda val, k=key: self._settings.set(k, val))
            form.addRow(HOTKEY_LABELS.get(key, key), edit)
            self._hotkey_edits[key] = edit
        layout.addLayout(form)

        reset_btn = QPushButton("기본값으로 복원")
        reset_btn.clicked.connect(self._restore_default_hotkeys)
        layout.addWidget(reset_btn, alignment=Qt.AlignRight)

        layout.addStretch(1)
        return w

    def _build_browser_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        info = QLabel(
            "브라우저 스크롤 캡처는 Chrome / Edge의 DevTools Protocol을 사용해\n"
            "현재 탭의 전체 페이지를 한 번에 저장합니다.\n\n"
            "사용하려면 브라우저를 디버그 포트와 함께 실행해야 합니다.\n"
            "(평소에 쓰는 브라우저 프로필이 잠겨 있으면 별도 단축아이콘을 만들어 사용)"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        self._port_spin = QSpinBox()
        self._port_spin.setRange(1024, 65535)
        self._port_spin.setValue(int(self._settings.get("browser_debug_port") or 9222))
        self._port_spin.valueChanged.connect(
            lambda v: self._settings.set("browser_debug_port", int(v))
        )
        form.addRow("디버그 포트:", self._port_spin)
        layout.addLayout(form)

        cmd = QLabel(
            "<b>Windows</b> — 시작 옵션 예시:<br>"
            "<code>chrome.exe --remote-debugging-port=9222 "
            "--user-data-dir=\"%LOCALAPPDATA%\\snaplab\\chrome\"</code><br><br>"
            "<b>macOS</b>:<br>"
            "<code>open -na \"Google Chrome\" --args --remote-debugging-port=9222 "
            "--user-data-dir=\"$HOME/Library/Application Support/snaplab/chrome\"</code><br><br>"
            "별도 user-data-dir을 쓰면 평소 프로필과 분리되어 안전합니다."
        )
        cmd.setTextFormat(Qt.RichText)
        cmd.setWordWrap(True)
        cmd.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(cmd)

        layout.addStretch(1)
        return w

    def _build_about_tab(self) -> QWidget:
        from .. import __version__

        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(QLabel(f"<h2>snaplab</h2>버전 {__version__}"))
        layout.addWidget(QLabel("가볍지만 강력한 화면 캡처 도구."))
        layout.addStretch(1)
        return w

    # --- handlers ----------------------------------------------------------

    def _on_autostart_changed(self, state) -> None:
        enabled = bool(state)
        ok = autostart.set_enabled(enabled)
        self._settings.set("autostart", enabled and ok)
        if not ok:
            # Revert UI if OS write failed.
            self._cb_autostart.blockSignals(True)
            self._cb_autostart.setChecked(autostart.is_enabled())
            self._cb_autostart.blockSignals(False)

    def _pick_save_dir(self) -> None:
        current = self._save_dir_edit.text() or str(Path.home())
        d = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", current)
        if d:
            self._save_dir_edit.setText(d)
            self._settings.set("save_dir", d)

    def _restore_default_hotkeys(self) -> None:
        for key in HOTKEY_KEYS.keys():
            value = DEFAULTS.get(key) or ""
            edit = self._hotkey_edits.get(key)
            if edit is not None:
                edit.set_hotkey(str(value))
            self._settings.set(key, value)
