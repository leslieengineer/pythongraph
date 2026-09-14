# REPLAY TEST SERVICES (RTS) - TECHNICAL INTEGRATION GUIDE

**Version:** 1.0  
**Status:** Production Ready  
**Last Updated:** 2026-09-14

---

## TABLE OF CONTENTS

1. [Overview](#overview)
2. [System Architecture](#system-architecture)
3. [Embedded Firmware Integration](#embedded-firmware-integration)
4. [PC Application Setup](#pc-application-setup)
5. [Validation & Testing](#validation--testing)
6. [Troubleshooting](#troubleshooting)

---

## OVERVIEW

**Replay Test Services (RTS)** is a high-speed ADC data streaming and simulation framework for MTR firmware testing. The system comprises two integrated components:

- **Embedded Module (Firmware):** Streams raw ADC samples over UART or replays pre-recorded datasets from Flash ROM
- **Desktop Application (Python):** Real-time waveform visualization, scenario building, and signal analysis

### Key Specifications

| Parameter | Value |
|---|---|
| UART Baud Rate | 2 Mbaud |
| UART Protocol | 8N1 (8 data bits, no parity, 1 stop bit) |
| Frame Size | 13 bytes |
| ADC Sample Rate | 15.6 ksample/s |
| Frame Rate (with decimation=2) | 7.8 kframe/s |
| Frame Interval | ~128 µs |
| ISR Overhead | <100 cycles |

---

## SYSTEM ARCHITECTURE

### Component Overview

```
┌─────────────────────────────────────────────────────────┐
│                    MTR Firmware (Embedded)              │
├─────────────────────────────────────────────────────────┤
│  ADC ISR Handler                                        │
│    ├─ Simulator: datalog.inc → voltage[]               │
│    └─ Data Pusher: voltage[] → UART DMA (13-byte frame)│
└─────────────┬───────────────────────────────────────────┘
              │ UART 2 Mbaud (Serial Port)
              ↓
┌─────────────────────────────────────────────────────────┐
│            QUAL Waveform Viewer (Python/PyQt5)          │
├─────────────────────────────────────────────────────────┤
│  • Real-time dual-plot waveform display                │
│  • History review & go-to-index seeking                │
│  • Scenario Builder (scale, sag, harmonic, flicker)    │
│  • Async CSV logging & buffer snapshots                │
└─────────────────────────────────────────────────────────┘
```

### Data Processing Pipeline

```
Dataset (datalog.inc)
    ↓ [Hold each sample for N ADC calls]
Simulator::ApplySimulator()
    ↓ [Decimation ratio applied]
voltage[] buffer (15.6 ksample/s output)
    ↓ [Every Nth sample]
DataPusher::PushData()
    ↓ [Encode 13-byte frame]
UART TX → DMA
    ↓ [2 Mbaud transmission]
PC Serial Port
    ↓ [Parse & normalize]
Python Application Queue
    ↓
Display (dual plots) / CSV Log
```

---

## EMBEDDED FIRMWARE INTEGRATION

### 1. Module Activation

Add the master enable define to your project configuration:

```c
#define CONFIG_REPLAY_TEST_SERVICES
```

### 2. Configuration Parameters

Edit `replay_test_services_configuration.h` to control module behavior:

```c
// UART Data Streaming
#define RTS_UART_MODE_ADC_PUSHER     1U

// Decimation Ratio (hold each sample N times, transmit one frame per N calls)
#define RTS_SAMPLE_RATE_RATIO        2U

// Dataset Replay from Flash
#define RTS_SIMULATOR_ENABLE         1U
#define RTS_SIMULATOR_PHASE_COUNT    3U
```

**Configuration Table:**

| Macro | Default | Description |
|---|---|---|
| `RTS_UART_MODE_ADC_PUSHER` | `1U` | Enable/disable UART ADC streaming |
| `RTS_SAMPLE_RATE_RATIO` | `2U` | Decimation: hold each sample N times |
| `RTS_SIMULATOR_ENABLE` | `1U` | Enable/disable dataset replay |
| `RTS_SIMULATOR_PHASE_COUNT` | `3U` | Phases per sample in datalog.inc |

### 3. Initialization

Call during firmware startup before ADC ISR begins:

```cpp
#include "replay_test_services.h"

void SystemInit(void)
{
    // Initialize RTS (UART driver, Data Pusher, Simulator)
    Status status = Rts::C_TestReplayServices::GetInstance().Initialize();
    
    if (status != STATUS_OK)
    {
        // Handle initialization error
        SystemHalt();
    }
}
```

### 4. ADC ISR Integration

Call exactly once per complete ADC sample (all phases):

```cpp
void AdcIsrHandler(const S32 *voltage, const S32 *current, U08 phaseCount)
{
    // STEP 1: Apply simulated data (optional)
    #if (RTS_SIMULATOR_ENABLE == 1U)
    (void)Rts::C_Simulator::GetInstance().ApplySimulator(voltage, phaseCount);
    #endif

    // STEP 2: Stream to UART
    #if (RTS_UART_MODE_ADC_PUSHER == 1U)
    (void)Rts::C_DataPusher::GetInstance().PushData(voltage);
    #endif

    // STEP 3: Continue normal metrology processing
    ProcessMetrology(voltage, current);
}
```

**Important:** Do not call `PushData()` or `ApplySimulator()` multiple times per sample or implement external decimation. RTS manages all decimation internally.

### 5. Timestamp Update

Call periodically from non-ISR context (e.g., main task):

```cpp
void MainTask(void)
{
    // Update timestamp (do NOT call from ISR to avoid blocking)
    Rts::C_DataPusher::GetInstance().UpdateTimestamp(
        minute,     // 0-63 (6 bits)
        second,     // 0-63 (6 bits)
        millisecond // 0-1023 (10 bits)
    );
}
```

### 6. Dataset Format (datalog.inc)

Store raw 18-bit signed ADC samples:

```cpp
// datalog.inc
{2048, 1024, -2048},
{2100, 1100, -2100},
{2048, 1024, -2048},
// ... continues for all samples
```

Included in simulator source:

```cpp
static const S32 defaultSamples[][RTS_SIMULATOR_PHASE_COUNT] = {
#include "datalog.inc"
};
```

**Requirements:**
- Each row: exactly `RTS_SIMULATOR_PHASE_COUNT` values (default: 3)
- Data type: signed 32-bit integer (18-bit range: -131072 to +131071)
- Sample count: inferred at compile-time via `sizeof`
- No manual array sizing required

---

## BINARY WIRE PROTOCOL

### Frame Structure (13 bytes)

```
Offset  Size  Field
──────  ────  ─────────────────────────────────────────────
0       1     Sync Byte (0xA5)
1-3     3     Packed Timestamp (Little-endian, 22 bits)
4-11    8     Payload (Sample Index + 3 Voltage Samples)
12      1     Checksum (XOR of bytes 1-11)
```

### Packed Timestamp (3 bytes)

```
Bit Range    Value
───────────  ────────────────
0-9          Milliseconds (0-1023)
10-15        Seconds (0-63)
16-21        Minutes (0-63)
```

Example: 12:34:567 ms → `0x1AA1` (hex)

### Payload (64-bit, Little-endian)

```
Bit Range    Value
───────────  ───────────────────────────────────────
0-7          Sample Index (0-155, wraps to 0)
8-25         Phase 1 Voltage (18-bit, right-shifted 6)
26-43        Phase 2 Voltage (18-bit, right-shifted 6)
44-61        Phase 3 Voltage (18-bit, right-shifted 6)
```

### Checksum Calculation

```python
checksum = 0
for byte in frame[1:12]:
    checksum ^= byte
frame[12] = checksum
```

Receiver must verify: `XOR(bytes[1:12]) == bytes[12]`

---

## PC APPLICATION SETUP

### System Requirements

| Component | Requirement |
|---|---|
| Operating System | Windows 10 or Windows 11 |
| Python Version | CPython 3.12+ or 3.13+ (official build) |
| RAM | ≥4 GB |
| Disk Space | ≥500 MB |

**⚠️ Critical Warning:** Do NOT use MSYS2, MinGW, or conda Python. Pre-built wheels for `numpy`, `PyQt5`, and `pyqtgraph` are compiled for standard CPython only. Alternative environments may cause wheel compatibility errors and force build-from-source failures.

### Installation Steps

#### 1. Download Application Source

```
Repository: https://gitlab-produits.rmm.scom/g705461/voltage_signal_visualization
```

#### 2. Install Dependencies

```bash
cd /path/to/voltage_signal_visualization
pip install -r requirements.txt
```

**Pinned Dependencies:**

```
numpy==2.4.4
PyQt5==5.15.11
pyqtgraph==0.14.0
pyserial==3.5
```

#### 3. Launch Application

```bash
python main.py
```

### Features

#### Visualization
- **Dual Plots:** Phase voltages (P1, P2, P3) and coupled voltages (P1-2, P2-3, P3-1)
- **X-Axis Units:** Cycles (based on configurable Samples/Cycle parameter)
- **Y-Axis Units:** Automatic scaling or manual Zoom multiplier
- **Fixed Baseline:** Horizontal line at 0 for reference

#### Data Modes
- **Online (COM):** Real-time UART streaming
- **Simulation:** Internal sine wave generator
- **Playback:** CSV log file replay with variable speed

#### Analysis Tools
- **Mouse Crosshair:** Snap to nearest sample, display index and all phase values
- **History Scrubber:** 10,000-step precision slider for frame-by-frame review
- **Go-to-Index:** Jump to specific sample position
- **Live Tracking:** Return to real-time when in history mode

#### Data Management
- **Async CSV Logging:** Non-blocking background logging
- **Buffer Snapshots:** Export current buffer to file
- **Scenario Builder:**
  - Scale values (voltage scaling)
  - Cut to 0 (simulate phase loss)
  - Add Harmonic (inject harmonic content)
  - Add Flicker (simulate voltage flicker)
  - Crop/Delete (trim dataset)

#### Status Bar Metrics
- RMS voltage
- Sampling frequency (fs)
- Frame rate (FPS)
- Frame count
- Dropped frame counter

---

## DECIMATION & INTERPOLATION EXPLAINED

### How It Works

With `RTS_SAMPLE_RATE_RATIO = 2`:

```
ADC Call:    1  2  3  4  5  6  7  8  9 10 ...
────────────────────────────────────────────
Simulator    S₀ S₀ S₁ S₁ S₂ S₂ S₃ S₃ S₄ S₄ ...
(output)     
────────────────────────────────────────────
Pusher       ✓        ✓        ✓        ✓
(transmit)   
────────────────────────────────────────────
Output       S₀       S₁       S₂       S₃ ...
(7.8 kf/s)
```

**Key Points:**
- Simulator holds each dataset sample for 2 consecutive ADC calls
- Data Pusher transmits one frame per decimation period (every 2nd call)
- No data loss: output rate equals original dataset rate
- No interpolation: raw samples are held, not averaged

### Resolution Reduction & Restoration

Dataset samples are stored as raw 18-bit ADC values. When transmitted:

1. **Encoding (Pusher):** Right-shift by 6 bits to fit 18-bit compressed format
2. **Transmission:** 13-byte frame sent to PC
3. **Decoding (Python):** Left-shift by 6 bits to restore original magnitude

Result: Bit-perfect reconstruction of original ADC values.

### End-of-Dataset Policies

| Policy | Behavior |
|---|---|
| `END_POLICY_LOOP` | Restart from first sample (seamless repeat) |
| `END_POLICY_HOLD_LAST` | Hold last sample indefinitely |
| `END_POLICY_ZERO` | Output zeros |
| `END_POLICY_STOP` | Return STATUS_DISABLED, halt playback |

---

## VALIDATION & TESTING

### Pre-Deployment Checklist

- [ ] **Step 1: Build Firmware**
  - Build `6-S40C1-mtr-qual-test` with `CONFIG_REPLAY_TEST_SERVICES` enabled
  - Verify compilation succeeds without warnings

- [ ] **Step 2: Capture UART Data**
  - Connect logic analyzer or USB-to-UART adapter to UART TX pin
  - Capture at 2 Mbaud, 8N1
  - Collect ≥100 frames for analysis

- [ ] **Step 3: Verify Frame Structure**
  - Confirm sync byte `0xA5` on all frames
  - Verify checksum: `XOR(bytes[1:12]) == bytes[12]`
  - Check timestamp packing format
  - Confirm sample index: 0→1→2...→155→0 (wrapping)

- [ ] **Step 4: Validate Decimation**
  - Count total frames received: should equal (ADC samples / 2)
  - Verify frame interval: ~128 µs
  - Check no dropped frames

- [ ] **Step 5: Test With Python App**
  - Connect COM port at 2 Mbaud
  - Verify waveform displays smoothly (no flat sections)
  - Check status bar metrics (RMS, fs, FPS)
  - Test all playback modes (Online, Simulation, Playback)

- [ ] **Step 6: Production Build Test**
  - Build firmware with `CONFIG_REPLAY_TEST_SERVICES` disabled
  - Verify HSTS components are completely removed (stubs only)
  - Confirm no extra Flash usage for datalog.inc
  - Validate legacy fallback operation

- [ ] **Step 7: End-Policy Testing**
  - Create small datalog.inc (10-20 samples)
  - Test each policy: LOOP, HOLD_LAST, ZERO, STOP
  - Verify expected output behavior

---

## TROUBLESHOOTING

### Issue: Garbled Characters on Serial Port

**Symptoms:** Unreadable data received, frequent frame errors

**Root Causes:**
- Incorrect UART baud rate configuration
- MCU clock running at wrong frequency
- UART clock divider miscalculated

**Solutions:**
1. Verify firmware clock configuration
2. Confirm PC serial settings: **2000000 Baud, 8 Data Bits, No Parity, 1 Stop Bit**
3. Use hardware frequency meter to measure actual MCU clock
4. Recalculate UART divider: `Divider = Clock / (16 × Baud)`

---

### Issue: High Frame Loss / Dropped Frames

**Symptoms:** Dropped frame counter increasing on status bar, gaps in waveform

**Root Causes:**
- Low-quality USB-to-UART adapter
- Serial port buffer overflow
- PC CPU overloaded
- Cable length or signal quality issues

**Solutions:**
1. Replace adapter with professional UART chip (FTDI FT232H, CP2102N)
2. Avoid CH340G or older CP2102 (unreliable at high baud rates)
3. Use short, shielded USB cable (<2 meters)
4. Check PC Task Manager: CPU and disk usage should be <50%
5. Reduce sample rate if necessary: increase `RTS_SAMPLE_RATE_RATIO` from 2 to 4

---

### Issue: Application Freezes or Low FPS

**Symptoms:** GUI becomes unresponsive, plots update slowly

**Root Causes:**
- GUI queue overloaded with too many points per frame
- PC hardware insufficient for high sample rate
- CSV logging blocking main thread
- Display resolution too high

**Solutions:**
1. Check `Samples/Cycle` parameter—reduce if >500
2. Increase decimation ratio on firmware: `RTS_SAMPLE_RATE_RATIO = 4U`
3. Enable auto-dot hiding (Dots option)
4. Reduce plot resolution or window size
5. Disable CSV logging if not needed
6. Check PC RAM availability (minimum 4 GB required)

---

### Issue: Pip Install Fails - No C++ Compiler

**Symptoms:** `error: Microsoft Visual C++ 14.0 is required` or similar

**Root Cause:** Using Python from MSYS2, MinGW, or mismatched environment

**Solution:**
1. Completely uninstall current Python version
2. Download official CPython installer from `python.org`
3. Run `.exe` installer with "Add Python to PATH" checked
4. Verify: `python --version` should show "CPython 3.13.x"
5. Retry: `pip install -r requirements.txt`

---

### Issue: Waveform Appears Flat or Has Gaps

**Symptoms:** Long sections of constant voltage, missing samples

**Root Causes:**
- Decimation counter not synchronized
- `ApplySimulator()` or `PushData()` called more than once per ADC sample
- Incorrect `RTS_SAMPLE_RATE_RATIO` configuration

**Solutions:**
1. Verify ISR calls each function exactly once: `if (IsAdcSampleReady()) { PushData(voltage); }`
2. Confirm `RTS_SAMPLE_RATE_RATIO` matches intended decimation
3. Check simulator `repeatCounter` logic in `AdvanceSample()`
4. Add debug breakpoints in ISR to verify call frequency

---

### Issue: Python App Won't Recognize COM Port

**Symptoms:** COM port list empty or frozen device listed

**Root Cause:** Driver not installed for USB-to-UART adapter

**Solution:**
1. Connect adapter and check Device Manager (Windows)
2. Look for unknown device or COM port entry
3. Download and install manufacturer drivers:
   - FTDI: `ftdichip.com/drivers`
   - CP210x: `silabs.com/developers/usb-to-uart-bridge-vcp-drivers`
4. Restart application after driver installation

---

## PERFORMANCE CHARACTERISTICS

### ISR Execution Time

| Operation | Cycles | Notes |
|---|---|---|
| `PushData()` - decimation pending | <5 | Single comparison |
| `PushData()` - frame transmitted | 50-100 | Encoding + DMA setup |
| `ApplySimulator()` - sample read | ~5 | Array indexing |
| Checksum calculation | ~15 | XOR loop (11 bytes) |

**Total:** <100 cycles per ADC sample in ISR

### Memory Usage

| Component | Size |
|---|---|
| Data Pusher state | ~50 bytes |
| Simulator state | ~30 bytes |
| Packet buffer | 13 bytes |
| Configuration | ~100 bytes |
| Dataset (typical) | 100-600 KB (Flash) |

---

## COMPATIBILITY & FALLBACK

### C++ Standard
- **Standard:** C++98 (no C++11 or later features)
- **Allocation:** Static only (no dynamic allocation, no `new`/`delete`)
- **Singleton:** Single-instance design via `GetInstance()`

### UART Driver
- **Reuses:** Existing `Drv_Uart_SP_Tx.h/.c` without modification
- **No Conflicts:** Can coexist with legacy code

### Disabling Features

To disable UART streaming (keep simulator):
```c
#define RTS_UART_MODE_ADC_PUSHER 0U
```

To disable simulator (keep UART):
```c
#define RTS_SIMULATOR_ENABLE 0U
```

Disabled components become no-op stubs returning `STATUS_DISABLED`.

### Legacy Compatibility
- Binary frame format is backward-compatible with previous decoder implementations
- Can safely integrate into existing firmware without breaking changes

---

## RETURN CODES

```cpp
enum Status
{
    STATUS_OK = 0,              // Success
    STATUS_SKIPPED,             // Decimation pending (Pusher only)
    STATUS_DISABLED,            // Feature disabled or simulator stopped
    STATUS_INVALID_ARGUMENT,    // Null pointer or invalid parameter
    STATUS_NOT_INITIALIZED      // Module not initialized
};
```

---

## REFERENCES

- **Embedded Code:** `replay_test_services.h`, `data_pusher.h`, `signal_simulator.h`
- **Configuration:** `replay_test_services_configuration.h`
- **Python Application:** [voltage_signal_visualization](https://gitlab-produits.rmm.scom/g705461/voltage_signal_visualization)
- **UART Protocol:** See "Binary Wire Protocol" section above

---

## REVISION HISTORY

| Version | Date | Changes |
|---|---|---|
| 1.0 | 2026-09-14 | Initial release: Optimized Data Pusher, corrected Simulator decimation, removed ADC restoration shifts |

---

**Document Confidentiality:** Sagemcom SA - NDA Only  
**Technical Support:** Contact Embedded Systems Team
