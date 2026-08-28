## Comprehensive User Manual

This section provides a detailed breakdown of the application's interface, its operating modes, and practical workflows for testing and validating grid anomalies.

### 1. Global Configuration (Hidden Mechanics & Impacts)
Before starting any mode, you must define the hardware and electrical parameters. These settings act as the master mathematical reference for the entire application, controlling everything from buffer allocation to the physical time-mapping of the graphs.

*   **Samples/Cycle**: The number of data points captured in a single 360-degree electrical cycle (Default: `312`).
    *   *The Hidden Subsampling Mechanic:* Due to UART bandwidth limitations, the firmware transmits data at half-resolution (dropping every alternating sample). You should input the full hardware rate here (e.g., 312), and the software internally calculates an `Effective SPC` (e.g., 156 samples). This hidden division governs the X-axis mapping, precisely regulates the playback speed in offline mode, and dictates the point density when generating simulated waves.
*   **Grid Freq (Hz)**: The standard frequency of the power grid (Default: `50.0`). 
    *   *System Impact:* Used alongside the effective sample rate to map raw indexes to real-world time in seconds. It also strictly defines the maximum RAM capacity for the 120-second rolling buffer and acts as the base frequency for the Scenario Builder's Flicker modulation algorithm.
*   **Scale (ADC->Unit)**: The divider used to convert raw 24-bit ADC values into physical units (mV, V, etc.). 
    *   *Dynamic UI Impact:* If you input `1.0`, the system automatically changes the UI labels, graph titles, and cursor readouts to **[ADC]** and displays the raw unscaled values. Inputting your actual hardware ratio converts all UI elements to real **[mV]** or your desired unit.

### 2. Operating Modes Breakdown

The application is divided into three distinct modes, strictly isolating their respective features to prevent UI clutter.

#### A. Online (COM) Mode
Used for real-time data acquisition directly from the hardware via UART.
*   **Port & Baud**: Select your active COM port (defaults to `COM1`) and baud rate (defaults to `2000000`). The port list features a quick-refresh (`⟳`) button.
*   **Log to CSV (Checkbox)**: Appears only in this mode. When checked, all incoming live data is asynchronously streamed into a CSV file without blocking the GUI.
*   *Use case:* Connecting to the meter/board to view live voltage streams and recording baseline data.

#### B. Simulation Mode
Used for testing the application interface, verifying performance, or generating pure, mathematically perfect sine waves.
*   **V_rms (mV)**: The Root Mean Square voltage of the generated sine waves.
*   **φ (°)**: Phase shift offset to rotate the entire 3-phase system.
*   *Use case:* Sanity-checking the graphing engine or demonstrating the software without physical hardware connected.

#### C. Playback (log) Mode
Used for replaying, analyzing, and mutating previously recorded CSV log files.
*   **📁 Choose File...**: Opens a file dialog to explicitly load your target CSV file.
*   **Speed**: A multiplier for playback speed (e.g., `2.0` plays twice as fast).
*   **Scenario Builder**: A powerful offline editor to inject anomalies into your log file (detailed in the Workflow section below).
*   *Use case:* Reviewing field logs or creating complex error scenarios (sags, flickers) to feed back into firmware testing algorithms.

### 3. Display Settings & Timeline

These controls adjust *how* you view the data, but do not alter the underlying data itself.

*   **Window (cyc)**: Defines the X-axis width based on electrical cycles. If set to `4`, the graph displays exactly 4 waveforms regardless of the `Samples/Cycle` setting.
*   **Zoom (×)**: A manual multiplier to stretch the Y-axis. The graph automatically scales *up* to fit large spikes, but never automatically scales *down*. This ensures that when a voltage drop occurs, the graph doesn't violently resize. Use this spinner to manually zoom into low-voltage signals.
*   **Dots (Checkbox)**: Toggles the visibility of individual data points. Automatically turns off if the visible point count exceeds performance thresholds.
*   **History Index & Timeline Slider**: Allows you to scrub back in time through the 120-second rolling RAM buffer while live data continues to flow in the background. 
    *   *Precision UX:* The horizontal slider is engineered with 10,000 discrete steps and stretches across the entire window to guarantee ultra-smooth dragging across millions of data points without erratic view jumping.

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
2. Click **📁 Choose File...** and load your `baseline_grid.csv`.
3. Click **▶ Start** to watch the replay. If you spot a natural anomaly (like a slight voltage dip), click **❚❚ Freeze** and hover your mouse over the anomaly.
4. Note the `idx` shown on the bottom right of the status bar.

**Phase 3: Building a Fault Scenario (Scenario Builder)**
Instead of writing complex C code to simulate hardware faults on the microcontroller, you can inject mathematical faults directly into your CSV.
1. Ensure the app is in **Playback (log)** mode and `baseline_grid.csv` is loaded.
2. Locate the **Scenario Builder** group.
3. Assume you want to simulate a severe voltage sag (drop to 20% amplitude) on Phase 1 between index `15000` and `18000`.
4. Enter `Start Index`: `15000`, `End Index`: `18000`.
5. Select `Phase`: `Phase 1`.
6. Select `Action`: `Scale (%)` and enter `Val 1`: `20`.
7. Click **➕**.
8. (Optional) Add another rule: Select `Action`: `Add Harmonic`, `Phase`: `All`, `Val 1` (Amp %): `10`, `Val 2` (Order): `3`. Click **➕**.

**Phase 4: Exporting and Validating**
1. Click the yellow **▶ Build Scenario** button.
2. The software will process your baseline file, inject the 20% sag on Phase 1, superimpose a 3rd-order harmonic across all phases, and accurately recalculate the Zero-Crossing RMS values.
3. Save the new file as `scenario_fault_test.csv`.
4. The app will automatically load this new file. Click **▶ Start** to visually verify your newly created grid anomalies. 
5. You can now use this `scenario_fault_test.csv` file to feed your embedded validation scripts or replay it through an arbitrary waveform generator.