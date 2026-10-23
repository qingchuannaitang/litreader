"""Entry point of the packaged app (Litreader.app on macOS, Litreader.exe on Windows; PyInstaller).
Same as `litreader gui`; the config is found as usual ($LITREADER_CONFIG, else ~/litreader/config.local.toml).

`--smoke [REPORT_FILE]`: packaging self-test (used by CI). Imports the app, creates the main window
offscreen, prints the keyring backend, and exits 0. It reads no keys and makes no network calls.
A windowed (no-console) exe has no stdout, so the report also goes to REPORT_FILE if given."""
import os
import sys


def _smoke(report: str | None) -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    lines = []
    try:
        import keyring
        from PySide6.QtWidgets import QApplication

        import litreader
        from litreader.gui.app import MainWindow
        lines.append(f"litreader {litreader.__version__}")
        kr = keyring.get_keyring()
        lines.append(f"keyring backend: {type(kr).__module__}.{type(kr).__name__}")
        app = QApplication.instance() or QApplication([sys.argv[0]])
        w = MainWindow()
        w.show()
        app.processEvents()
        w.close()
        app.processEvents()
        lines.append("main window: ok")
        lines.append("SMOKE OK")
        code = 0
    except BaseException as e:  # noqa: BLE001 - report anything
        import traceback
        lines.append("SMOKE FAILED: " + "".join(traceback.format_exception(e)))
        code = 1
    text = "\n".join(lines) + "\n"
    if report:
        with open(report, "w", encoding="utf-8") as f:
            f.write(text)
    if sys.stdout is not None:
        sys.stdout.write(text)
        sys.stdout.flush()
    return code


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--smoke":
        os._exit(_smoke(sys.argv[2] if len(sys.argv) > 2 else None))
    from litreader.gui.app import main
    sys.exit(main())
