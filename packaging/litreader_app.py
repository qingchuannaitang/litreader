"""Entry point of Litreader.app (PyInstaller). Same as `litreader gui`; the config is found as usual
($LITREADER_CONFIG, else ~/litreader/config.local.toml — a bundle's working directory is '/')."""
import sys

from litreader.gui.app import main

if __name__ == "__main__":
    sys.exit(main())
