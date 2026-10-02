#!/usr/bin/env python3
"""power_throttle_service.py — launch.py entry point for Protocol Smart
Power Throttling. See power_throttle.py for the actual logic."""
import power_throttle

if __name__ == "__main__":
    power_throttle.run_monitor()
