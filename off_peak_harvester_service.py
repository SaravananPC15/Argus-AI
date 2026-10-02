#!/usr/bin/env python3
"""off_peak_harvester_service.py — launch.py entry point for Protocol
Off-Peak Data Harvesting. See off_peak_harvester.py for the actual
scheduling/fetching logic; configure targets via harvest_targets.json
(off_peak_harvester.add_target(), documented in SETUP.md)."""
import off_peak_harvester

if __name__ == "__main__":
    off_peak_harvester.run_scheduler()
