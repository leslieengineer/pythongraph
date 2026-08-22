# QUAL Waveform Viewer

A desktop application for real-time visualization of QUAL voltage waveforms (`U1/U2/U3` and compound voltages) via UART, internal simulation, or log file playback.

This is a streamlined release focusing on core visualization and scenario-building features. The repository no longer contains experimental code or old validation scripts.

## Release Scope

- Displays 3 phase voltage channels (`U1/U2/U3`) and 3 compound voltage channels (`U12/U23/U31`).
- Uses dual plots to separate phase and compound voltages.
- Features a highly configurable rolling buffer for reviewing recent history.
- Includes an integrated **Scenario Builder** to modify and manipulate log data (simulate voltage sags, harmonics, flicker, etc.) during playback.
- Includes asynchronous CSV logging and buffer snapshot export using `index` tracking.
- Provides a history review mode with `Go to (index)`, a scrub slider, and `Back to live`.

## Key Features

- Real-time display of voltages across dual interactive plots.
- **Dynamic Units**: Automatically switches between `mV` and `ADC` based on the configured ADC Scale.
- Supports 3 modes:
    - `Online (COM)`: Reads from UART.
    - `Simulation`: Generates an internal 3-phase sine wave.
    - `Playback (log)`: Replays from a saved log file with custom playback speeds.
- Auto-detects 2 data formats in Online mode:
    - Legacy ASCII: `$Q,<u32_sec>,<u16_ms>,<U1>,<U2>,<U3>[,<I1>,<I2>,<I3>]`
    - Binary frame with a dynamic layout: `sync + packed payload + checksum`.
- **Integrated Scenario Builder**: Apply rules (Scale, Cut to 0, Add Harmonic, Add Flicker, Crop/Delete) to specific sample indexes and phases, and build new custom scenario CSV logs.
- X-axis window is defined in `cycles` based on a configurable `Samples/Cycle` setting.
- **Global Y-Zoom**: The Y-axis automatically scales up to fit data but does not automatically scale down, preventing erratic zooming. A manual Y-zoom multiplier is provided for inspection.
- Mouse-tracking crosshair that snaps to the nearest sample, displaying `index`, `U1`, `U2`, `U3`, `U12`, `U23`, `U31` on the status bar.
- Fixed horizontal baseline at `0` for easy observation.
- Dedicated vertical marker for the `Go to` point, indicating the exact viewing position in the history window.
- `Sample dots` option to display individual samples when data point density is low.
- Automatically disables sample markers when the rendered point count is too high, preserving FPS.
- Displays `RMS`, `fs`, `fps`, frame/line count, and dropped frames if the GUI queue is overloaded.
- Asynchronous CSV logging to file.

## Release Components

- `main.py`: PyQt5 interface, system configuration, scenario builder, rolling buffer, rendering, history review, status bar, and application entry point.
- `providers.py`: Serial provider, Simulation provider, Playback provider, and dynamic input protocol parsing.
- `logger.py`: Background CSV logger and buffer snapshot exporter.
- `requirements.txt`: Dependencies with pinned versions for this release.
- `Readme.md`: Release documentation and execution instructions.

## Environment Requirements

- Recommended OS: Windows 10 or Windows 11.
- Recommended Python: **official CPython 3.12+ or 3.13+**.
- This release has been installed and smoke-tested with **official CPython 3.13.5 on Windows**.

Important Notes:

- Avoid using MSYS2 / MinGW Python to install via `pip install -r requirements.txt`.
- Reason: Standard wheels for `numpy`, `PyQt5`, and `pyqtgraph` on Windows are typically built for standard CPython Windows, not the MinGW/UCRT tag. Using them might cause `pip` to fallback to building from source, which can fail.

## Tested Dependencies

The current contents of `requirements.txt` are versions that have been successfully installed and smoke-tested:

- `numpy==2.4.4`
- `PyQt5==5.15.11`
- `pyqtgraph==0.14.0`
- `pyserial==3.5`

## Installation and Execution on Windows

### Recommended Method: PowerShell + official CPython

Open PowerShell in the project directory and run:

```powershell
py -3.13 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

If your machine uses CPython 3.12 instead of 3.13, replace `py -3.13` with `py -3.12`.

### If the `py` command is unavailable

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

### Running from Command Prompt

```bat
py -3.13 -m venv .venv
.\.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

### Running without activating venv

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

## Execution Workflow

### Step 1. Open the application

After installing the dependencies:

```powershell
python main.py
```

The application will launch a PyQt5 window with:

- A `Configuration` group for defining fundamental signal parameters.
- A `Connection & Logging` group.
- A `Scenario Builder (Playback Only)` group.
- A `Display Settings` group containing window cycles, Y-zoom, and channel toggles.
- Dual plots for Phase and Compound voltages.
- A status bar at the bottom.

### Step 2. System Configuration

Before starting, set up the **Configuration** parameters:

- **Samples/Cycle**: Number of samples per electrical cycle (Default: `312`).
- **Grid Freq (Hz)**: The power grid frequency (Default: `50.0`).
- **ADC Scale (÷)**: Divider to convert raw ADC to actual voltage. Entering `1.0` will automatically configure the GUI to display Raw ADC values instead of `mV`.

### Step 3. Select a Data Mode

The application offers 3 modes:

#### 1. Online (COM)

- Select `Mode = Online (COM)`.
- Select a `Port` from the list (or manually type `Auto`).
- If a device was just plugged in, click the refresh button `⟳`.
- Select the `Baud` rate (or type `Auto`).
- Click `Start` to begin reading data.

While running Online:

- `Stop` will halt the provider and pause live updates.
- `Freeze` will pause screen rendering, but the app will continue to pull data into the background rolling buffer.

#### 2. Simulation

- Select `Mode = Simulation`.
- Configure `V_rms (mV)` to change the RMS voltage amplitude.
- Configure `φ (°)` to apply a phase shift.
- Click `Start` to run the simulated data source based on your configured `Samples/Cycle`.

This mode is ideal for testing the UI, history review, markers, and logging without requiring actual hardware.

#### 3. Playback (log) & Scenario Builder

- Select `Mode = Playback (log)`.
- Click `Log…` in the `Connection` group to choose a source playback file.
- **Scenario Builder**:
    - Specify a `Start Index` and `End Index`.
    - Select the target `Phase` (All, U1, U2, U1+U2, etc.).
    - Choose an `Action` (Scale %, Cut to 0, Add Harmonic, Add Flicker, Crop/Delete).
    - Provide `Value 1` and `Value 2` as required by the action.
    - Click `+ Add Rule` to append to the rule list.
    - Click `▶ Build & Load Scenario CSV` to generate a manipulated log file and automatically load it into playback.
- Adjust the `Speed` to fast-forward or slow down playback.
- Click `Start` to replay.

## Display Controls

- `Window (cycles)`: Number of electrical cycles displayed on the X-axis.
- `Y zoom (x)`: A manual multiplier to scale the Y-axis visually. The plot expands automatically to fit larger data but relies on this zoom factor for inspecting smaller values. It does not modify original data.
- `Show Phase` / `Compound Phase`: Toggle individual voltage traces on or off.
- `Sample dots`: Toggle markers for individual sample points.

Sample markers only appear when the number of rendered points is below an internal threshold. In long viewing windows, the app automatically reverts to line-only mode to prevent FPS drops.

## Rolling Buffer History Review

The `History` section operates on a rolling buffer derived from the configured maximum samples.

- `Go to (index)`: Enter the exact sample index you want to view.
- `Go`: Jump to the entered index.
- Horizontal slider: Drag to scrub through the history buffer.
- `Back to live`: Return to tracking live data at the end of the buffer.

Important rules:

- While in history view, live data continues to flow into the rolling buffer.
- The yellow vertical line represents the current `Go to` point.
- The light blue horizontal baseline indicates the permanent `0` level.
- The white crosshair indicates the current mouse position.
- The cursor readout in the status bar displays `index`, `U1`, `U2`, `U3` and compound equivalents of the nearest sample being pointed at.

## CSV Logging

- Tick `Log to CSV` to arm background logging (Automatically hidden during Playback mode).
- Select the destination file using the button displaying the CSV filename.
- If the app is stopped, selecting a CSV file will immediately export a snapshot of the current buffer.
- If the app is running and logging is enabled, new data will be asynchronously logged to the CSV.

CSV format written by the app:

```text
index,fw_min,fw_sec,fw_ms,U1_mV,U2_mV,U3_mV,...
```

Logging behaviors retained for this release:

- Logger appends across multiple sessions.
- The header is written only when the file is empty or when the user explicitly chooses to overwrite.
- If logging is enabled but no provider is running, the CSV file may only contain the header.

## Supported Input Data

### Internal Application Data Contract

All data sources are normalized to an internal frame:

```python
{"t_s": float, "u": [u1, u2, u3]}
```

*(Note: `t_s` strictly maps to the sample index).*

- `t_s` (index): Monotonically increasing sample counter.
- `u`: List of 3 analog channel values currently displayed.

### Legacy ASCII

`$Q,<u32_sec>,<u16_ms>,<U1>,<U2>,<U3>[,<I1>,<I2>,<I3>]`

The current release only utilizes the first 3 voltage values.

### Dynamic Binary Frame (`sync` + `payload` + `checksum`)

To maintain high data throughput, the application supports a strictly structured 10-byte binary packet over UART.

#### 1. Frame Byte Layout

Every transmitted frame must be exactly 10 bytes long. The layout is as follows:

| Byte Offset | Size | Name | Data Type | Description |
| :--- | :--- | :--- | :--- | :--- |
| `0` | 1 byte | `sync` | Unsigned Int (8-bit) | Synchronization byte. Must exactly be `0xA5`. |
| `1..8` | 8 bytes | `payload` | Unsigned Int (64-bit) | Packed data payload, transmitted in **Little-Endian** byte order. |
| `9` | 1 byte | `checksum` | Unsigned Int (8-bit) | XOR checksum of the 8 `payload` bytes (`payload[0] ^ ... ^ payload[7]`). |

*The app only accepts the packet if the `sync` byte is correct, the length is exactly 10 bytes, and the `checksum` evaluates successfully.*

#### 2. Payload Bit Layout (Dynamic based on Configuration)

The 64-bit `payload` is dynamically unpacked based on the `Samples/Cycle` setting in the UI. The parser calculates the bit-width required to store the sample index (e.g., 312 samples requires 9 bits, 128 samples requires 8 bits).

**Example: Assuming a configuration of 312 Samples/Cycle (9-bit index)**

| Bits | Width | Name | Data Type | Description |
| :--- | :--- | :--- | :--- | :--- |
| `0..8` | 9 bits | `sample_pos` | Unsigned Int | Index of the sample within the cycle (`0` to `311`). |
| `9..26` | 18 bits | `U1_raw` | Signed Int (2's comp) | Phase 1 Raw ADC value. |
| `27..44` | 18 bits | `U2_raw` | Signed Int (2's comp) | Phase 2 Raw ADC value. |
| `45..62` | 18 bits | `U3_raw` | Signed Int (2's comp) | Phase 3 Raw ADC value. |
| `63` | 1 bit | `reserved` | Unsigned Int | Unused/Reserved bit. Transmit as `0`. |

**Decoding rules:**
- The dynamic `sample_pos` bits are extracted first. If `sample_pos` exceeds the configured samples per cycle, the packet is discarded.
- Each `U*_raw` field is extracted and decoded as a signed-18 two's complement value.
- The raw value is then mathematically shifted (`<< 6` equivalent to `* 64`) to restore 24-bit resolution, and subsequently divided by the configured `ADC Scale`.

#### 3. UART Baudrate Calculation for Real-Time Logging

When transmitting binary frames over standard UART (1 Start bit, 8 Data bits, No Parity, 1 Stop bit), each byte requires **10 bits** of transmission overhead. 

- **Bits per Frame:** 10 bytes/frame * 10 bits/byte = **100 bits/frame**.

To stream real-time data smoothly without buffering delays on the hardware side, the minimum UART baudrate must exceed `(Samples per Second) * 100`.

| Frequency | Samples/Cycle | Total Samples/Second | Minimum Baudrate (bps) | Recommended Standard Baudrate |
| :--- | :--- | :--- | :--- | :--- |
| 50 Hz | 128 | **6,400** | **640,000** | `921,600` or `1,000,000` |
| 50 Hz | 156 | **7,800** | **780,000** | `921,600` or `1,000,000` |
| 50 Hz | 312 | **15,600** | **1,560,000** | `2,000,000` |

*Note: For the default 312 Samples/Cycle setting, a baudrate of at least `2,000,000` (2 Mbps) is strictly required to prevent frame dropping at the hardware transmission level.*

### Playback files

The app supports playback from:

- Legacy ASCII lines starting with `$Q,`
- CSV files exported by the app with the `index` header.

## Troubleshooting

### 1. `pip install -r requirements.txt` fails when using MSYS2 / MinGW Python

The cause is usually that the `numpy` or `PyQt5` wheel does not match the interpreter tag.

Correct solution:

- Install the official CPython for Windows.
- Create a new venv using official CPython.
- Reinstall using `pip install -r requirements.txt`.

### 2. COM port not visible

- Check if the device is recognized by Windows.
- Click the refresh button `⟳`.
- Ensure the serial driver is correctly installed.

### 3. Playback reports no valid frames

Check if the playback file matches one of these two formats:

- Lines starting with `$Q,...`
- CSV with header `index,fw_min,fw_sec,...`

### 4. Status bar indicates 'dropped'

This means the GUI queue became full while receiving data. The app continues to run, but some frames were discarded to keep the application near real-time.

## Current Limitations

- Playback currently loads the entire file into memory before replaying.
- A full release test suite is no longer included in the repo; current validation relies on smoke tests and static analysis.

## Audit Results for this Release

Points reviewed and finalized for the current release:

- `requirements.txt` has pinned versions to ensure reproducible installations.
- Added `.gitignore` to block `__pycache__`, `*.pyc`, and local venvs.
- Smoke-tested history review and scenario builder features:
    - Input `Go to (index)`
    - Scrub slider
    - Cursor readout in history mode
    - Vertical marker line for the `Go to` point
    - Horizontal baseline at `0`

## Release Packaging Suggestions

For internal release, minimally include:

- `main.py`
- `providers.py`
- `logger.py`
- `requirements.txt`
- `Readme.md`

Do not package:

- `__pycache__`
- local virtual environments (`.venv`, `.venv-cpython`)
- CSV logs generated during manual testing

## Packaging as simulation.exe

This app can be packaged into a single `simulation.exe` file to run on other Windows machines without requiring a separate Python installation on the target machine.

Clarifications:

- This practically means `Windows build -> runs on other Windows machines`.
- It does not mean the same `simulation.exe` will run on macOS or Linux.
- The build should be generated on a machine with the same architecture as the target machine, currently `Windows x64`.

The repository currently provides build configurations:

- `simulation.spec`: PyInstaller configuration.
- `build_simulation.ps1`: PowerShell script to rebuild the executable.

### Build Instructions

From the project directory, using PowerShell:

```powershell
.\build_simulation.ps1
```

This script will use the tested interpreter `.venv-cpython\Scripts\python.exe` and invoke PyInstaller using the `simulation.spec` file.

If you prefer running manual commands instead of the script:

```powershell
.\.venv-cpython\Scripts\python.exe -m PyInstaller --noconfirm --clean simulation.spec
```

### Build Output

After building, the executable will be located at:

```text
dist\simulation.exe
```

On the current machine, the one-file build was successful with a size of approximately `49.65 MB`.

### Distributing to other machines

- Copy the `dist\simulation.exe` file to the target Windows machine.
- Run the executable directly.
- The target machine no longer needs Python installed or `pip install -r requirements.txt` executed.

### Practical Notes for Executable Distribution

- The initial startup might be slower because it is a `one-file` build.
- Windows SmartScreen or antivirus software might show warnings since the executable is self-packaged internally and lacks a digital signature.
- If the recipient uses Windows with a different architecture or stricter security policies, it should be tested beforehand in the exact target environment.
- There is a warning related to `OpenGL` during the build; this does not block the current app because this release does not use `pyqtgraph.opengl`.