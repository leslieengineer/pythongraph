# Replay Test Services (RTS)

High-speed ADC data streaming and replay module for MTR firmware.

## Quick Start

### 1. Enable the Module

Add to your project configuration:

```c
#define CONFIG_REPLAY_TEST_SERVICES
```

### 2. Initialize

```cpp
#include "replay_test_services.h"

// During startup
Status status = Rts::C_TestReplayServices::GetInstance().Initialize();
```

### 3. Call from ADC ISR

```cpp
void AdcIsrCallback(const S32 *voltage_samples)
{
    // Optional: Use simulated data instead of ADC
    #if (RTS_SIMULATOR_ENABLE == 1U)
    (void)Rts::C_Simulator::GetInstance().ApplySimulator(voltage_samples, 3U);
    #endif

    // Stream ADC data over UART
    #if (RTS_UART_MODE_ADC_PUSHER == 1U)
    (void)Rts::C_DataPusher::GetInstance().PushData(voltage_samples);
    #endif

    // Continue normal processing
    ProcessMetrology(voltage_samples);
}
```

### 4. Update Timestamp (from main task, not ISR)

```cpp
void MainTask(void)
{
    // Call periodically from non-ISR context
    Rts::C_DataPusher::GetInstance().UpdateTimestamp(minute, second, millisecond);
}
```

## Configuration

Edit `replay_test_services_configuration.h`:

```c
#define RTS_UART_MODE_ADC_PUSHER     1U   // Enable UART streaming
#define RTS_SAMPLE_RATE_RATIO        2U   // Decimation: 1 output per N inputs
#define RTS_SIMULATOR_ENABLE         1U   // Enable replay from datalog.inc
#define RTS_SIMULATOR_PHASE_COUNT    3U   // Phases per sample
```

## Features

### Data Pusher
- Streams raw ADC samples over UART DMA
- 13-byte binary frame format with sync, timestamp, checksum
- Decimation support (configurable ratio)
- Sample index tracking (0-155 wraparound)
- Optimized for ISR execution (<100 cycles per transmitted frame)

### Signal Simulator
- Replays raw ADC samples from `datalog.inc` (Flash/ROM storage)
- Automatic decimation/interpolation with configurable ratio
- Four end-of-dataset policies (LOOP, HOLD_LAST, ZERO, STOP)
- Stateless design (no data restoration needed)

## Wire Format

Binary frame transmitted at 2 Mbaud, 8N1:

```
Byte 0:    Sync (0xA5)
Bytes 1-3: Timestamp (little-endian, 22 bits):
           Bits 0-9:   milliseconds (0-1023)
           Bits 10-15: seconds (0-63)
           Bits 16-21: minutes (0-63)
Bytes 4-11: Payload (64-bit, little-endian):
           Bits 0-7:   sample index (0-155)
           Bits 8-25:  phase 1 voltage (18-bit, right-shifted 6)
           Bits 26-43: phase 2 voltage (18-bit, right-shifted 6)
           Bits 44-61: phase 3 voltage (18-bit, right-shifted 6)
Byte 12:   Checksum (XOR of bytes 1-11)
```

**Frame Interval**: ~128 µs at 15.6 ksample/s ADC with decimation ratio 2.

## Python Integration

The application expects frames matching the above format at 2 Mbaud:

```python
import serial

ser = serial.Serial('COM3', 2000000, timeout=1)

while True:
    frame = ser.read(13)
    if len(frame) == 13 and frame[0] == 0xA5:
        # Verify checksum
        checksum = 0
        for byte in frame[1:12]:
            checksum ^= byte
        if checksum == frame[12]:
            print("Valid frame received")
```

Decoded data format (internal application contract):

```python
{
    "timestamp_s": float,
    "samples": {
        "P1": int,  # Phase 1 voltage (ADC units)
        "P2": int,  # Phase 2 voltage
        "P3": int   # Phase 3 voltage
    }
}
```

## Dataset Format (datalog.inc)

Store raw 18-bit ADC samples as 2D array:

```cpp
// datalog.inc
{2048, 1024, -2048},
{2100, 1100, -2100},
{2048, 1024, -2048},
// ... continues
```

Included in simulator:

```cpp
static const S32 defaultSamples[][RTS_SIMULATOR_PHASE_COUNT] = {
#include "datalog.inc"
};
```

**Format Requirements**:
- Each row: exactly `RTS_SIMULATOR_PHASE_COUNT` values
- Each value: signed 18-bit integer
- Sample count: inferred at compile-time
- No manual sizing needed

## Data Flow

### With Simulator + Pusher

```
datalog.inc
    ↓ [Apply decimation: hold each sample N times]
Simulator::ApplySimulator()
    ↓ [Repeated samples sent to voltage buffer]
voltage[] (15.6 ksample/s)
    ↓ [Every Nth sample: encode + transmit]
DataPusher::PushData()
    ↓ [Binary frame at 7.8 kframe/s]
UART TX
    ↓
Python Application
```

### How Decimation Works

With `RTS_SAMPLE_RATE_RATIO = 2`:

```
ADC Call:   1  2  3  4  5  6  7  8  9 10 ...
Simulator:  S₀ S₀ S₁ S₁ S₂ S₂ S₃ S₃ S₄ S₄ ...  (each sample held 2x)
Pusher:     ✓        ✓        ✓        ✓         (transmit every 2nd)
Output:     S₀       S₁       S₂       S₃        (one per decimation period)
```

Simulator holds each dataset sample for 2 consecutive ADC calls.  
Pusher transmits one frame per decimation period.  
Result: Output rate = dataset rate (no data loss, no interpolation).

## End-of-Dataset Policies

| Policy | Behavior |
|---|---|
| `END_POLICY_LOOP` | Restart from first sample |
| `END_POLICY_HOLD_LAST` | Repeat last sample indefinitely |
| `END_POLICY_ZERO` | Output zeros from next call |
| `END_POLICY_STOP` | Return `STATUS_DISABLED`, halt |

Set via `Simulator::Initialize()`:

```cpp
Rts::C_Simulator::GetInstance().Initialize(
    dataset, Rts::END_POLICY_LOOP);
```

## Return Codes

```cpp
enum Status
{
    STATUS_OK = 0,              // Success
    STATUS_SKIPPED,             // Pusher: decimation pending
    STATUS_DISABLED,            // Module disabled or simulator stopped
    STATUS_INVALID_ARGUMENT,    // Null pointer or invalid count
    STATUS_NOT_INITIALIZED      // Module not initialized
};
```

## Timing

Typical execution times (ARM Cortex-M33):

| Operation | Cycles |
|---|---:|
| `PushData()` - skipped (decimation pending) | <5 |
| `PushData()` - transmitted frame | 50-100 |
| `ApplySimulator()` - sample read | ~5 |
| Checksum calculation (11 bytes) | ~15 |

Total ISR overhead: <100 cycles per ADC sample.

## Memory Usage

| Component | Size |
|---|---:|
| Data Pusher state | ~50 bytes |
| Simulator state | ~30 bytes |
| Packet buffer | 13 bytes |
| Configuration | ~100 bytes |

Dataset size: Variable (typically 100 KB - 600 KB in Flash).

## Validation Checklist

- [ ] UART captured at 2 Mbaud, 8N1
- [ ] Sync byte (0xA5) present on all frames
- [ ] Checksum valid: `XOR(bytes[1:12]) == bytes[12]`
- [ ] Sample index wraps 0→155→0
- [ ] Frame rate = (ADC sample rate / RTS_SAMPLE_RATE_RATIO)
- [ ] Timestamp packed correctly
- [ ] Python app receives valid frames
- [ ] Waveform appears smooth (no flat sections)
- [ ] All simulator end policies tested

## Troubleshooting

**Signals appear flat or have gaps**
- Verify `ApplySimulator()` and `PushData()` called exactly once per ADC sample
- Check `RTS_SAMPLE_RATE_RATIO` matches configuration
- Confirm simulator decimation counter is synchronized

**UART frames not received**
- Verify UART configuration: 2 Mbaud, 8N1
- Check DMA is configured correctly
- Validate sync byte in captured data
- Verify checksum calculation

**Sample index doesn't increment properly**
- Ensure `SAMPLE_INDEX_LIMIT = 156` in `data_pusher.cpp`
- Verify no external modifications to sample index logic

**Dataset out of memory**
- Reduce `datalog.inc` size or increase Flash allocation
- Check `LIMIT_DATA_SIZE` in simulator

## Compatibility

- **C++ Standard**: C++98
- **Memory**: Static allocation only (no dynamic allocation)
- **UART Driver**: Reuses existing `Drv_Uart_SP_Tx` without modification
- **Legacy Support**: Binary frame format compatible with previous decoder implementations

## Disabling Features

To disable UART streaming (keep simulator):

```c
#define RTS_UART_MODE_ADC_PUSHER 0U
```

To disable simulator (keep pusher):

```c
#define RTS_SIMULATOR_ENABLE 0U
```

Disabled components become stubs returning `STATUS_DISABLED`.

## References

- **Wire Protocol**: See "Wire Format" section above
- **Python App**: [voltage_signal_visualization](https://gitlab-produits.rmm.scom/g705461/voltage_signal_visualization)
- **Configuration**: `replay_test_services_configuration.h`

---

**Version**: 1.0  
**Last Updated**: 2026-09-14  
**Status**: Production Ready
