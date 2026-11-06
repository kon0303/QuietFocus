# Changelog

All notable changes to QuietFocus are documented here.

## [1.0.2] - 2026-11-07

### Fixed

- Pressing `Win` and opening the Start menu, or opening Windows Search, now
  counts as leaving the current application and mutes controlled apps. Tray
  overflow and quick-settings flyouts remain ignored so opening the hidden-icon
  panel does not silence the current app.
- Exiting QuietFocus now restores default sound by unmuting every session it
  controlled, including sessions that were already muted before being
  controlled. The old original-mute restoration can be selected with the
  "退出时恢复默认声音" setting.
- The tray menu now explicitly says "退出并恢复声音".

### Added

- `restore_on_exit` setting (default: on).
- Unit coverage for Start-menu foreground handling and forced unmute on exit.

## [1.0.1] - 2026-11-03

### Fixed

- Opening the Windows hidden-icon overflow, taskbar, IME, or the QuietFocus
  window itself no longer makes the previously active application look like it
  moved to the background.
- QuietFocus now waits for a real foreground application before changing any
  mute state at startup.
- Launching `QuietFocus.exe` again now brings the existing hidden window to the
  front instead of silently exiting.
- Replaced the PyInstaller one-file `%TEMP%` extraction with a small launcher
  that extracts the portable runtime next to the executable. This fixes
  `Could not create temporary directory!` on systems with a restricted temporary
  directory or sandbox.
- Added a `version.txt` marker and a read-only-location fallback to
  `%LOCALAPPDATA%\QuietFocus\app`.

### Added

- UWP sessions hosted by `ApplicationFrameHost.exe` are grouped by display name
  instead of being merged into one row.
- Mouse-wheel scrolling in the application list.
- Build artifacts for the portable folder, portable ZIP, and single-file
  launcher.
- GitHub Actions build workflow.

## [1.0.0] - 2026-11-03

### Added

- Enumerate Windows audio sessions on the default playback device.
- Automatic per-app mute when the app is not foreground.
- Per-app checkboxes, select all / clear all.
- Auto-select current and newly appearing audio applications.
- Master pause switch with original mute-state restoration.
- Crash-safe restore journal.
- System tray, autostart, configurable scan interval.
- Chinese interface with high-DPI layout.
