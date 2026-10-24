# Cleanly: redesign plan

Cleanly is a free Windows cleaner with a simple interface, built on the
BleachBit cleaning engine. This document records the decisions, the
architecture and the roadmap.

## Decisions

| Topic | Decision |
|---|---|
| Platform | Windows 10 and 11 only |
| UI technology | [pywebview](https://pywebview.flowrl.com/) on Microsoft Edge WebView2, with an HTML/CSS/JavaScript front end |
| Front-end tooling | Plain ES modules with no build step for now. Move to a bundler (Vite) only if the UI outgrows it. |
| Packaging | PyInstaller, one folder (`cleanly.spec`), later wrapped in an installer |
| Price | Free. No paid tier, upsells, surveys or nagging. |
| Licence | GPL-3.0-or-later, the same as BleachBit. Keep the copyright notices and credit BleachBit in About. |
| Inspiration | Avast Cleanup's flow (scan, review, clean), used as inspiration only. No Avast assets, names, icons or exact layouts. |

## Brand

Logo: `cleanly/frontend/assets/logo.svg` (Windows icon: `cleanly.ico`). It is a
mint squircle holding an open white "C" ring with a sparkle in the opening.

| Token | Dark | Light | Use |
|---|---|---|---|
| `--bg` | `#0D1714` | `#F3F7F5` | Window background |
| `--surface` | `#13211D` | `#FFFFFF` | Cards, tables |
| `--border` | `#233832` | `#DCE6E2` | Dividers |
| `--text` | `#E9F3EF` | `#10201B` | Main text |
| `--text-muted` | `#8FA89F` | `#52675F` | Secondary text |
| `--primary` | `#3BE0A0` | `#0E9F6A` | Buttons, numbers, selection |
| `--info` | `#7CC7FF` | `#1F7BC2` | "Coming soon" labels |
| `--warning` | `#F2B84B` | `#B7790B` | App is running, cautions |
| `--danger` | `#FF7A6B` | `#C9412F` | Errors |

Type: Segoe UI Variable, which ships with Windows 11. Older systems fall back to Segoe UI.
The theme follows Windows (light or dark) and can be overridden in Settings.

## Architecture

```
cleanly/
  app.py              pywebview window and startup
  bridge/api.py       Python API exposed to JavaScript as window.pywebview.api
  core/
    categories.json   engine options -> friendly categories (Basic/Full mode)
    categories.py     builds categories from the registered cleaners
    engine.py         threaded scan (preview) and clean through bleachbit.Worker
    stats.py          lifetime totals and history (%APPDATA%\Cleanly\stats.json)
  frontend/           index.html, styles.css, js/, assets/
bleachbit/            the engine, mostly unchanged
```

- **A scan is the engine's preview**, so nothing is deleted until the user cleans.
- `bleachbit/Worker.py` reports each command result through an optional
  `ui.on_command_result(operation_option, ret)` hook. That gives exact item
  counts per option, and file lists for the review drawer.
- Jobs run on a background thread, one at a time. Progress and results reach
  the UI as events (`scan-progress`, `scan-done`, `clean-progress`, `clean-done`).
- **Categories.** Options that carry an engine warning, passwords and
  deep scan are never offered for one-click cleaning. Every option is
  scanned, and the mode only decides which rows are pre-checked.
  - *Basic*: temp files, logs, caches, crash reports, and browser cache.
  - *Full*: adds history, cookies, sessions, recent activity and system caches.
  - *Custom*: any manual change.
- Before cleaning, Cleanly warns about sign-outs (cookies, sessions), the
  Recycle Bin, and browsers that are open (those are skipped).

## Screens

1. **Home.** The scan summary ("671 MB ready to clean"), Clean now and Review
   items buttons, tiles for Junk files, Browsers, Apps and Disks, lifetime
   stats, and recent cleanings.
2. **Clean junk.**
   - Disk cleaner and Browser cleaner tabs, with a Basic/Full/Custom selector.
   - Rows show the item count and size.
   - A review drawer lists the files found.
   - A fixed footer shows the total and the Clean button.
3. **Result.** Space freed, skipped apps and errors.
4. **Apps** and **Disks.** Placeholders until their phases land.
5. **Settings.** Theme and About. Scheduling comes later.

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| 0 | pywebview shell, PyInstaller spec, Windows CI build | Done |
| 1 | Core: threaded scan/clean, counts, categories, stats, tests | Done |
| 2 | Home, Disk cleaner, Browser cleaner, review drawer, result screen | First version done. Needs a test run on real Windows. |
| 3 | Scheduled scans (Task Scheduler, `--background-scan`), notifications, history page, exclusions UI, cookie allowlist UI | Next |
| 4 | Broken shortcuts (IShellLink, sent to the Recycle Bin). Conservative registry scan (missing-file references only, `reg export` backup, undo). | |
| 5 | Apps: installed list (Uninstall keys and Store apps), "unused" from Prefetch and UserAssist, uninstall, leftover review, startup apps | |
| 6 | Disks: HDD/SSD detection, `defrag /A` and `/O`, SMART health, large files | |
| 7 | Rebrand remaining BleachBit paths (settings dir, update check), translations, accessibility, installer, code signing, auto-update | |

## Safety rules

- Preview before every clean. Never delete anything the user has not seen in a scan.
- The Recycle Bin is unchecked by default.
- Registry and shortcut fixes must be undoable. Offer a restore point before
  registry changes or uninstalls.
- Never inflate numbers or invent "issues".
