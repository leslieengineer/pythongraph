## Comprehensive User Manual

This section provides a detailed breakdown of the application's interface, its operating modes, and practical workflows for testing and validating grid anomalies.

### 1. Global Configuration
Before starting any mode, you must define the hardware and electrical parameters. These settings govern how the application decodes binary packets and renders the time axis.

*   **Samples/Cycle**: The number of data points captured in a single 360-degree electrical cycle (Default: `312`). This dynamically adjusts the binary unpacker's bit-mask.
*   **Grid Freq (Hz)**: The standard frequency of the power grid (Default: `50.0`). Used alongside *Samples/Cycle* to map raw indexes to real-world time.
*   **ADC Scale (÷)**: The divider used to convert raw 24-bit ADC values into physical units (mV, V, etc.). 
    *   *Tip:* If you input `1.0`, the system automatically changes the UI labels to **[ADC]** and displays the raw unscaled ADC values. If you input your hardware's divider ratio, it will display real **[mV]**.

### 2. Operating Modes Breakdown

The application is divided into three distinct modes, strictly isolating their respective features to prevent UI clutter.

#### A. Online (COM) Mode
Used for real-time data acquisition directly from the hardware via UART.
*   **Port**: Dropdown to select the active COM port. You can manually type a port or select `Auto` to let the app pick the first available active port.
*   **Baud**: UART baud rate. Select `Auto` to invoke the auto-baud detection algorithm, or manually set it (e.g., `2000000`). 
*   **Log to CSV (Checkbox)**: Appears only in this mode. When checked, all incoming live data is asynchronously streamed into a CSV file without blocking the GUI.
*   *Use case:* Connecting to the meter/board to view live voltage streams and recording baseline data.

#### B. Simulation Mode
Used for testing the application interface, verifying performance, or generating pure, mathematically perfect sine waves.
*   **V_rms (mV)**: The Root Mean Square voltage of the generated sine waves.
*   **φ (°)**: Phase shift offset to rotate the entire 3-phase system.
*   *Use case:* Sanity-checking the graphing engine or demonstrating the software without physical hardware connected.

#### C. Playback (log) Mode
Used for replaying, analyzing, and mutating previously recorded CSV log files.
*   **Log... (Button)**: Opens a file dialog to load your target CSV file.
*   **Speed**: A multiplier for playback speed (e.g., `2.0` plays twice as fast).
*   **Scenario Builder**: A powerful offline editor to inject anomalies into your log file (detailed in the Workflow section below).
*   *Use case:* Reviewing field logs or creating complex error scenarios (sags, flickers) to feed back into firmware testing algorithms.

### 3. Display & Navigation Settings

These controls adjust *how* you view the data, but do not alter the underlying data itself.

*   **Window (cycles)**: Defines the X-axis width based on electrical cycles. If set to `4`, the graph displays exactly 4 waveforms regardless of the `Samples/Cycle` setting.
*   **Y zoom (×)**: A manual multiplier to stretch the Y-axis. The graph automatically scales *up* to fit large spikes, but never automatically scales *down*. This ensures that when a voltage drop occurs, the graph doesn't violently resize. Use this spinner to manually zoom into low-voltage signals.
*   **Sample dots**: Toggles the visibility of individual data points. Automatically turns off if the visible point count exceeds performance thresholds.
*   **History Controls (Go to index / Slider)**: Allows you to scrub back in time through the 120-second rolling RAM buffer while live data continues to flow in the background.

---

### 4. Typical Testing Workflow (The Scenario Lifecycle)

The true power of this application lies in the ability to capture real-world data, modify it to simulate extreme grid faults, and use that modified data for validation.

**Phase 1: Capturing the Baseline (Online Mode)**
1. Connect your measurement board via USB/UART.
2. Set the Mode to **Online (COM)**.
3. Check the **Log to CSV** box and select a destination file (e.g., `baseline_grid.csv`).
4. Click **▶ Start**. Let the application record clean, normal grid voltages for a few minutes.
5. Click **■ Stop**. You now have a raw, mathematically accurate representation of your local grid.

**Phase 2: Reviewing the Data (Playback Mode)**
1. Switch the Mode to **Playback (log)**.
2. Click **Log...** and load your `baseline_grid.csv`.
3. Click **▶ Start** to watch the replay. If you spot a natural anomaly (like a slight voltage dip), click **❚❚ Freeze** and hover your mouse over the anomaly.
4. Note the `index` shown on the bottom right of the status bar (e.g., `idx=15000`).

**Phase 3: Building a Fault Scenario (Scenario Builder)**
Instead of writing complex C code to simulate hardware faults on the microcontroller, you can inject mathematical faults directly into your CSV.
1. Ensure the app is in **Playback (log)** mode and `baseline_grid.csv` is loaded.
2. Locate the **Scenario Builder** group.
3. Assume you want to simulate a severe voltage sag (drop to 20% amplitude) on Phase 1 between index `15000` and `18000`.
4. Enter `Start Index`: `15000`, `End Index`: `18000`.
5. Select `Phase`: `U1`.
6. Select `Action`: `Scale (%)` and enter `Value 1`: `20`.
7. Click **➕ Add Rule**.
8. (Optional) Add another rule: Select `Action`: `Add Harmonic`, `Phase`: `All`, `Value 1` (Amp %): `10`, `Value 2` (Order): `3`. Click **➕ Add Rule**.

**Phase 4: Exporting and Validating**
1. Click the yellow **▶ Build & Load Scenario CSV** button.
2. The software will process your baseline file, inject the 20% sag on U1, superimpose a 3rd-order harmonic across all phases, and accurately recalculate the Zero-Crossing RMS values.
3. Save the new file as `scenario_fault_test.csv`.
4. The app will automatically load this new file. Click **▶ Start** to visually verify your newly created grid anomalies. 
5. You can now use this `scenario_fault_test.csv` file to feed your embedded validation scripts or replay it through an arbitrary waveform generator.