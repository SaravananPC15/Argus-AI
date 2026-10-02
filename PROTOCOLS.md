# Argus Protocols

This document explains the key protocol groups inside Argus and what each one is designed to do.

## Overview

Argus is built as a local-first AI assistant with a layered architecture:

- voice and wake-word entry points
- a routing brain
- an executor layer that performs system actions safely
- optional background services and monitoring
- local semantic memory and document retrieval
- remote control entry points for phone/browser interaction

Argus intentionally mixes small fast models, local LLMs, and selective larger-model escalation for tasks that clearly need more reasoning power.

## Core Protocols

### 1. Protocol Lazarus
A self-healing safety layer that restarts failed workers or services intelligently instead of letting a single issue take the entire stack down.

Typical use cases:
- service crashes
- dropped socket connections
- microphone failures
- degraded background watchers

### 2. Protocol Round Table
A multi-agent system with specialist personas that debate or analyze complex tasks together before a plan is selected.

Example roles:
- Architect
- Debugger
- Security Analyst
- Data Engineer
- Systems Engineer
- Researcher
- Tutor
- Pragmatist

This is useful for tricky architecture or debugging problems that benefit from more than one perspective.

### 3. Protocol No Slop
A filtering layer that strips filler, fake confidence, and generic AI-style repetition while preserving the authentic tone of the assistant.

Purpose:
- cleaner day-to-day answers
- better readability
- less robotic output

### 4. Protocol Smart Dictation
Converts spoken input into structured text and allows dictation flows with better usability than raw speech capture alone.

### 5. Protocol Voice ID
Uses speaker verification to confirm that a voice command comes from the owner before allowing sensitive actions.

Sensitive actions may include:
- system lock
- shutdown/restart
- destructive commands
- git push or automation steps that affect the system

### 6. Protocol Safety Confirmation
Prompts for confirmation before high-risk actions are executed.

Examples:
- git push
- script execution
- emptying recycle bin
- lock/workstation actions

## Research & Planning Protocols

### 7. Deep Research
A reasoning flow for web research, summarization, and synthesis using relevant sources rather than a single pass of shallow retrieval.

### 8. Semantic Context Compaction
Compresses long or noisy context before it is fed into a model, helping keep conversation memory useful without flooding the prompt.

### 9. Dynamic Sequence Sharding
Breaks large logs or long sequences into manageable chunks before analysis.

### 10. Big-O Complexity Auditor
Estimates algorithmic complexity and auditability of functions, scripts, or data-processing paths.

### 11. Database Indexing Optimizer
Reviews databases for patterns that suggest missing indexes or slow queries.

### 12. Relational-to-NoSQL Transpiler
Converts schema ideas or relational patterns into an appropriate NoSQL structure or document-oriented model.

### 13. Synthetic Anchor
Searches and organizes personal notes or local content for a conceptual match without requiring a cloud service.

## Vision & Perception Protocols

### 14. Room Awareness
Uses camera data and object recognition to understand what is happening in a room and react to it.

### 15. Zero-G Visual Controls
Uses gesture recognition to allow physical motion to trigger commands.

### 16. Mirage Cam
Uses a webcam and local processing for visual monitoring tasks.

### 17. Smart Log Digest
Summarizes logs and action traces into a smaller, readable overview.

## Remote Access Protocols

### 18. Remote Cursor Control
Allows a phone or browser to mirror the screen and drag the cursor around the computer.

### 19. Wireless Launcher
Lets a phone trigger a local launcher or startup action on the laptop.

### 20. Screen Feed
Provides a view of the current screen over a local connection.

### 21. Macro Deck
Saves reusable commands or actions as quick tap buttons in a touch-friendly interface.

## Automation & Execution Protocols

### 22. Git Archeologist
Explains the repo history, specific commits, and how code evolved over time.

### 23. Dataset Synth
Creates synthetic data for testing, prototyping, or modeling.

### 24. Auto-Documentation
Builds documentation scaffolding or docstrings without overwriting the original code.

### 25. Mind Map Exporter
Converts structured thoughts or analysis into map-like outputs.

### 26. Smart Power Throttling
Adjusts power usage and performance profiles according to workload and battery conditions.

### 27. Off-Peak Data Harvesting
Runs scheduled or delayed data capturing based on non-peak periods.

### 28. Graph Sync
Facilitates local peer sync between devices and metadata graphs.

### 29. MCP Tool Bridge
Allows Argus to talk to MCP-compatible tool servers in a controlled way when explicitly configured.

### 30. Ghost Type / Virtual Terminal Extension
Allows actions to be performed through simulated typing or macro-driven terminal flows.

## Monitoring & Security Protocols

### 31. Overwatch
Monitors network and system patterns for anomalies.

### 32. Security Warden
Observes sensitive files and flags tampering or unauthorized changes.

### 33. Aegis
Tracks system health, power, and performance health indicators.

### 34. Sentinel
Detects syntax errors and code issues during development.

### 35. Gatekeeper MFA
Adds second-factor style verification for dashboard or remote login access.

### 36. Castellan
Uses Bluetooth proximity or presence as an access condition.

### 37. Radio Silence
Provides a quiet, minimal communication or isolation mode.

### 38. Acoustic Data Link
Uses sound-based signaling for a low-bandwidth communication channel.

## Developer Workflows

### 39. Syntax Guardian
Checks code quality and syntax before running or applying certain automation-heavy actions.

### 40. Auto-Documentation
Adds documentation to code or project files during analysis and review sessions.

### 41. Browser Automation
Performs web operations in a local browser, useful for research, utility tasks, and page interaction.

### 42. Research Task Scheduler
Schedules or prioritizes research actions and repeated background tasks.

### 43. Workspace Intelligence
Keeps track of files, activity, and relevant context during day-to-day prompting.

## Frontier / Escalation

### 44. Frontier Escalation
A deliberate opt-in escalation path for a larger or remote model when a task is beyond the local model’s comfort zone.

This is intentionally explicit and gated to avoid accidental cloud actions.

## Summary

Argus is not a single monolithic app. It is a suite of protocols designed to behave like a personal AI operating layer for a laptop or workstation:

- voice-first interaction
- local research and reasoning
- system and file automation
- remote and phone access
- security-first execution
- selective escalation to stronger models when needed

That combination is what makes it more than a chatbot and closer to a local AI control layer.

---

If you want to make this repo more searchable, also keep the README tightly written and feature-focused, because GitHub search favors strong titles, obvious keywords, and clean docs structure.

