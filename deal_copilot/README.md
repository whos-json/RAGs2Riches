# Deal Intelligence & Sales Copilot

A local Windows app. Enter a deal and get a scorecard: fit score, win probability, expected value, timeframe, effort tier and a closing playbook built from the closest past deals.

## Run

Double-click `dist\DealCopilot.exe` (in this folder).
A console window opens and your browser goes to `http://127.0.0.1:8765/`. Close the console window to stop it.

Options: `DealCopilot.exe --port 9000` picks a different first port. `--no-browser` skips opening the browser.

## Data

Scores come from a rule engine run over 25 **sample** historical deals in `data\historical_deals.json`. This is not live CRM data. The weights and thresholds in `engine.py` are placeholders and have not been calibrated against real outcomes.

## Build

```
build_exe.bat
```

Uses `..\.venv` if present, installs PyInstaller if missing, runs the unit tests, then builds `dist\DealCopilot.exe` as one file.

## Develop

```
python server.py            # run from source
python -m unittest test_engine
```

The UI is plain HTML, CSS and JS in `web\`, with no external fonts or libraries, so it works offline. Motion respects the system "reduce motion" setting. Sound effects are off by default.

Design notes are in `..\design\`.
