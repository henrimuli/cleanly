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

The `Cleanly Windows` GitHub workflow runs these on every push, checks that
`Cleanly.exe --self-check` starts, and uploads the build as an artifact.

Windows marks files extracted from a downloaded zip as coming from the
internet, and .NET will not load marked DLLs. Cleanly removes the mark from
its own files at startup and ships `Cleanly.exe.config` to allow them. If an
old build fails with "Failed to resolve Python.Runtime.Loader.Initialize",
right-click the zip, choose Properties, tick Unblock, then extract it again.
