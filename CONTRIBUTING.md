# Contributing

Thanks for improving QuietFocus.

## Development setup

```powershell
python -m pip install -r requirements-dev.txt
python app.py --debug
```

Use `QUIETFOCUS_DATA_DIR` to keep development settings out of the real
`%APPDATA%\QuietFocus` directory:

```powershell
$env:QUIETFOCUS_DATA_DIR = "$PWD\.data-dev"
python app.py
```

## Tests

```powershell
$env:PYTHONPATH = "$PWD\.vendor"
python -m unittest discover -s tests -v
python tools\integration_audio_test.py
```

The integration test creates a silent WAV session and verifies real Core Audio
mute/unmute behavior. It requires Windows and an audio output device.

## Pull requests

- Keep changes focused and explain the user-visible behavior.
- Add or update tests for the mute state machine and settings logic.
- Do not commit `.vendor`, `dist`, build output, logs, or user data.
- Run `python -m unittest discover -s tests -v` before opening a PR.
- For UI changes, include a screenshot if possible.

## Code map

- `quietfocus/audio.py` — Core Audio sessions, mute state machine, recovery journal
- `quietfocus/foreground.py` — foreground window and shell-surface detection
- `quietfocus/ui/main_window.py` — main window, settings dialog, controller wiring
- `quietfocus/ui/widgets.py` — custom Tk widgets
- `launcher/Program.cs` — single-file launcher that unpacks the portable runtime

## License

By contributing, you agree that your contributions are licensed under the MIT
License.
