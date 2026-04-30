"""Diagnostic: minimal PySide6 window. If this also shows BitBlt errors,
the issue is system-level (graphics driver / GDI), not our code.
"""
import sys
from PySide6.QtWidgets import QApplication, QLabel

app = QApplication(sys.argv)
w = QLabel("Hello from Qt — close to exit.")
w.resize(400, 200)
w.show()
sys.exit(app.exec())
