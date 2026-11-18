"""
Desktop Application Entry Point for Vitocal 111-S & BTicino Remote Manager.
Run with: python app.py
"""
import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("Vitocal Remote")
    app.setOrganizationName("Antigravity")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
