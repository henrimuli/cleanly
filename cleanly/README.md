# Cleanly

A free Windows cleaner with a simple interface, built on the BleachBit engine.
See [doc/cleanly/PLAN.md](../doc/cleanly/PLAN.md) for the design and roadmap.

## Run from source (Windows)

```bat
pip install -r requirements-cleanly.txt
python -m cleanly
```

Add `--debug` to open the WebView2 developer tools.

## Work on the UI in a browser

The front end has a mock engine with fake data, so you can design without
Windows or pywebview:

```sh
cd cleanly/frontend
python -m http.server 8765
# open http://localhost:8765/index.html?mock
```

## Test and build

```sh
python -m pytest tests/TestCleanly.py
pyinstaller --noconfirm cleanly.spec   # Windows: dist/Cleanly/Cleanly.exe
```

The `Cleanly Windows` GitHub workflow runs these on every push and uploads the
build as an artifact.
