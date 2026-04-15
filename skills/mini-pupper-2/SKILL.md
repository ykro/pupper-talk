---
name: mini-pupper-2
description: Use when writing code for Mini Pupper 2 robot dog — servo control, LCD display, audio I2S, MangDang HardwareInterface, Pi deployment, mock mode, or any physical robot interaction
---

# Mini Pupper 2 — Robot Control Reference

## Overview

Mini Pupper 2 is a 12-DOF quadruped robot (MangDang) running Ubuntu 22.04 on Raspberry Pi. Control it via the MangDang Python SDK — never use HTTP bridge, always use `HardwareInterface` directly.

## Hardware Quick Reference

| Component | Spec |
|-----------|------|
| Compute | Raspberry Pi 4 / CM4 + ESP32 |
| Servos | 12 DOF (3/leg: abduction, hip, knee) |
| LCD | ST7789, 320x240, SPI |
| Audio | I2S at 48kHz native (mic + speaker) |
| Camera | MIPI (RPi v1.3/v2 compatible) |
| LiDAR | LDROBOT STL-06P (optional) |
| IMU | 6-axis (inverted mount) |
| Battery | 1000mAh, ~200g payload |
| Python | 3.10 only (BSP compiled) |

## Control Approach: HardwareInterface vs Bridge vs ROS2

Three ways to control the robot. Choose based on your use case:

| Approach | When to Use | Latency | Complexity |
|----------|-------------|---------|------------|
| **HardwareInterface** (direct) | Demos, custom apps, Gemini integration | ~1ms | Low |
| **HTTP Bridge** (FastAPI on Pi) | Laptop-driven apps that can't run on Pi | ~50-100ms | Medium |
| **ROS2 Humble** | SLAM, navigation, multi-node robotics | Variable | High |

### HardwareInterface (RECOMMENDED for demos)

Direct Python control on the Pi. No middleware, no network latency. Import `MangDang.mini_pupper.HardwareInterface`, set joint angles as numpy arrays. Proven approach for all Gemini Live demos.

```python
from MangDang.mini_pupper.HardwareInterface import HardwareInterface
hw = HardwareInterface()
hw.set_actuator_postions(pose_array)  # immediate, <1ms
```

**Pros:** Minimal latency, no dependencies beyond BSP, runs offline, simple debugging.
**Cons:** Must run on the Pi (Python 3.10, ARM64), no access to SLAM/nav stack.

### HTTP Bridge (pupper-bridge — DEPRECATED for demos)

FastAPI server on Pi (:9090) that translates HTTP POST to servo commands. The laptop sends `POST /pose {"pose": "stand"}`. Adds network latency and a failure point.

```
Laptop → HTTP POST → Pi :9090 → FastAPI → HardwareInterface → servos
```

**Pros:** Laptop can drive the robot (useful if your app can't run on Pi).
**Cons:** 50-100ms round-trip latency, requires bridge process running, network dependency, extra failure point. Not suitable for real-time voice demos where Gemini audio and servo reactions need to be synchronized.

### ROS2 Humble (for robotics features)

Full robotics stack: SLAM navigation, teleoperation, Gazebo simulation. Based on Champ quadruped framework + ldlidar_stl_ros2.

```bash
# On Pi — bringup
export ROS_DOMAIN_ID=42
ros2 launch mini_pupper_bringup bringup.launch.py

# On PC — teleoperation
ros2 run teleop_twist_keyboard teleop_twist_keyboard

# On PC — SLAM mapping
ros2 launch mini_pupper_slam slam.launch.py
ros2 run nav2_map_server map_saver_cli -f ~/map

# On PC — autonomous navigation
ros2 launch mini_pupper_navigation navigation.launch.py map:=$HOME/map.yaml
```

**Pros:** Full SLAM, Nav2, LiDAR mapping, Gazebo sim, community packages.
**Cons:** Heavy setup (ROS2 workspace, colcon build), high resource usage on Pi, latency through ROS topics not ideal for real-time voice sync. ROS2 and HardwareInterface conflict — don't run both simultaneously (both try to own the servo bus via ESP32 socket).

### Decision Rule

```
Need SLAM/navigation/LiDAR mapping?  → ROS2
App must run on laptop, not Pi?       → HTTP Bridge
Everything else (especially demos)?   → HardwareInterface (direct)
```

## Servo Control (MangDang HardwareInterface)

```python
from MangDang.mini_pupper.HardwareInterface import HardwareInterface
import numpy as np

hw = HardwareInterface()

# Poses: 3x4 numpy array (radians)
# Rows: [abduction, hip, knee]
# Cols: [FL, FR, BL, BR]
stand = np.array([
    [0.0, 0.0, 0.0, 0.0],       # abduction
    [0.88, 0.88, 0.88, 0.88],   # hip
    [-0.70, -0.70, -0.70, -0.70] # knee
])
hw.set_actuator_postions(stand)  # note: typo is in the API
```

### Proven Poses

```python
POSES = {
    "stand":   [[0.0]*4,  [0.88]*4,         [-0.70]*4],
    "sit":     [[0.0]*4,  [0.5,0.5,1.2,1.2], [-0.3,-0.3,-1.4,-1.4]],
    "greet":   [[0.0]*4,  [1.5,0.88,0.88,0.88], [0.0,-0.70,-0.70,-0.70]],
    "excited": [[0.15,-0.15,0.15,-0.15], [1.0]*4, [-0.5]*4],
    "sad":     [[0.0]*4,  [0.4]*4,         [-0.2]*4],
}
```

### Dance Sequences

```python
DANCES = {
    "default": [("stand",0.6), ("sit",0.6), ("stand",0.6), ("greet",0.6), ("stand",0.6)],
    "wiggle":  [("stand",0.4), ("excited",0.4), ("stand",0.4), ("excited",0.4), ("stand",0.4)],
}
```

## LCD Display

Two approaches proven in production:

**1. Eyes animation (Pygame + ST7789)**
```python
# Uses sidikalamini/eyes-animation vendored library
# 6 moods mapped to MoodState + ColorScheme
# Pi: SDL_VIDEODRIVER=dummy, background thread
# Mock: Pygame on main thread (SDL requirement on macOS)
```

**2. Custom renderer (pure Pygame)**
```python
# pupper-bumblebee: Autobot-style optics
# pupper-characters: animated GIF via Pillow
```

**3. MangDang Display API**
```python
from MangDang.mini_pupper.display import Display, BehaviorState
disp = Display()
disp.show_image('/path/to/image.png')  # resized to 320x240
disp.show_state(BehaviorState.REST)
```

## Audio on Pi (I2S)

Pi hardware runs at 48kHz only. Must resample for Gemini (16kHz in, 24kHz out).

```python
PI_HW_RATE = 48000
GEMINI_INPUT_RATE = 16000
GEMINI_OUTPUT_RATE = 24000

def _resample(data: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    ratio = dst_rate / src_rate
    n_out = int(len(data) * ratio)
    indices = np.arange(n_out) / ratio
    indices = np.clip(indices, 0, len(data) - 1)
    left = np.floor(indices).astype(int)
    right = np.clip(left + 1, 0, len(data) - 1)
    frac = indices - left
    return (data[left] * (1 - frac) + data[right] * frac).astype(data.dtype)
```

## Threading Model

```
Mock (macOS):  Pygame MAIN thread  |  asyncio BACKGROUND thread
Pi:            asyncio MAIN thread |  Pygame BACKGROUND thread (SDL_VIDEODRIVER=dummy)
```

This is mandatory — SDL requires main thread on macOS, asyncio needs main thread on Pi for signal handling.

## Pi Deployment

```bash
# SSH to Pi
ssh ubuntu@192.168.86.20  # password: mangdang

# Setup
sudo apt install -y libportaudio2 python3.10-venv
uv venv --python 3.10 --system-site-packages  # CRITICAL: system-site-packages for MangDang
uv sync
cp .env.example .env  # add GEMINI_API_KEY

# Run
uv run python -m src.main

# Eyes library (if using sidikalamini eyes)
git clone https://github.com/sidikalamini/eyes-animation.git vendor/eyes-animation
```

## Mock Mode

All projects support `--mock` for laptop testing without hardware:
- Pygame window instead of SPI LCD
- Direct audio rates (no resample)
- `RobotMotion(mock=True)` logs commands instead of moving servos
- Camera returns synthetic frames with "MOCK CAMERA" text

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Using HTTP bridge for robot control | Use `HardwareInterface` directly |
| Python 3.11+ on Pi | Must use 3.10 (BSP compiled for it) |
| Missing `--system-site-packages` | MangDang, spidev, RPi.GPIO need system packages |
| Pygame on background thread (macOS) | SDL requires main thread on macOS |
| Not resampling audio on Pi | 48kHz hardware vs 16/24kHz Gemini |
| `set_actuator_positions` (correct spelling) | API has typo: `set_actuator_postions` |
