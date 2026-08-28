# QUAL Waveform Viewer

A desktop application for real-time visualization of QUAL phase voltages and coupled voltages via UART, internal simulation, or log file playback.

This is a streamlined release focusing on core visualization and scenario-building features. The repository no longer contains experimental code or old validation scripts.

## Release Scope

- Displays 3 primary phase channels (`P1/P2/P3`) and 3 coupled voltage channels (`P1-2/P2-3/P3-1`).
- Uses dual plots to separate phase and coupled voltages.
- Features a highly configurable rolling buffer for reviewing recent history.
- Includes an integrated **Scenario Builder** to modify and manipulate log data (simulate voltage sags, harmonics, flicker, etc.) during playback.
- Includes asynchronous CSV logging and buffer snapshot export using `index` tracking.
- Provides a history review mode with `Go to (index)`, a 10,000-step precision full-width scrub slider, and a `⬤ Live` tracking return.

## Key Features

- Real-time display of voltages across dual interactive plots.
- **Dynamic Units**: Automatically switches between scaled standard units and `ADC` based on the configured ADC Scale.
- Supports 3 modes:
    - `Online (COM)`: Reads from UART.
    - `Simulation`: Generates an internal 3-phase sine wave.
    - `Playback (log)`: Replays from a saved log file with custom playback speeds.
- **Integrated Scenario Builder**: Apply rules (Scale, Cut to 0, Add Harmonic, Add Flicker, Crop/Delete) to specific sample indexes and phases, and build new custom scenario CSV logs.
- X-axis window is explicitly defined in `cycles` based on a configurable `Samples/Cycle` setting.
- **Global Y-Zoom**: The Y-axis automatically scales up to fit data but does not automatically scale down, preventing erratic zooming. A manual Zoom multiplier is provided for inspection.
- Mouse-tracking crosshair that snaps to the nearest sample, displaying `index`, `P1`, `P2`, `P3`, `P1-2`, `P2-3`, `P3-1` on the status bar.
- Fixed horizontal baseline at `0` for easy observation.
- Dedicated vertical marker for the `Go to` point, indicating the exact viewing position in the history window.
- `Dots` option to display individual samples when data point density is low. Automatically disabled when the rendered point count is too high, preserving FPS.
- Displays `RMS`, `fs`, `fps`, frame/line count, and dropped frames if the GUI queue is overloaded.
- Fully asynchronous CSV logging to file.

## Release Components

- `main.py`: PyQt5 interface, system configuration, scenario builder, rolling buffer, rendering, history review, status bar, and application entry point.
- `providers.py`: Serial provider, Simulation provider, Playback provider, and binary input protocol parsing.
- `logger.py`: Background CSV logger and buffer snapshot exporter.
- `requirements.txt`: Dependencies with pinned versions for this release.
- `Manual.md` & `Readme.md`: Documentation and execution instructions.

## Environment Requirements

- Recommended OS: Windows 10 or Windows 11.
- Recommended Python: **official CPython 3.12+ or 3.13+**.
- This release has been installed and smoke-tested with **official CPython 3.13.5 on Windows**.

Important Notes:
- Avoid using MSYS2 / MinGW Python to install via `pip install -r requirements.txt`. Standard wheels for `numpy`, `PyQt5`, and `pyqtgraph` on Windows are typically built for standard CPython Windows, not the MinGW/UCRT tag. Using them might cause `pip` to fallback to building from source, which can fail.

## Tested Dependencies

- `numpy==2.4.4`
- `PyQt5==5.15.11`
- `pyqtgraph==0.14.0`
- `pyserial==3.5`

## Supported Input Data & Formats

### Internal Application Data Contract
All data sources are strictly normalized to an internal dictionary frame before entering the application queue:

```python
{"t_s": float, "u": [p1, p2, p3]}