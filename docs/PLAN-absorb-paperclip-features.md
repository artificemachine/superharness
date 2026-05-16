# PLAN: Absorb Paperclip Features

**Status:** Proposed  
**Author:** gemini-cli  
**Context:** Feature gap analysis between paperclip and superharness (2026-05-14)  
**Goal:** Enhance the superharness protocol with high-value architectural primitives discovered in the paperclip ecosystem, specifically optimized for Morpheme UI consumption.

---

## 1. Heartbeat-Based Adapter Discovery

**The Paperclip Feature:** A "heartbeat" model where agents/services register themselves dynamically.

**Implementation in superharness:**
- Expand the existing `.superharness/agent-pulse.yaml` into a first-class `heartbeat` table in SQLite.
- Agents (or their wrappers) call `shux heartbeat --status <status> --task <id>` every 30s.
- Stale heartbeats (> 2 min) are automatically flagged as `zombie` by the watcher.

**Morpheme UI Benefit:**
- Real-time "Liveliness" indicators on task nodes and a dedicated "Active Agents" panel.

---

## 2. Structured Artifact & Work Product Management

**The Paperclip Feature:** Treating files/outputs as "Work Products" linked to tickets.

**Implementation in superharness:**
- Add an `artifacts` array to the `report` handoff schema.
- Each artifact includes `path`, `type` (code|image|test_report|binary), and `hash`.
- Add a command: `shux artifact add --task <id> --type <type> <path>`.

**Morpheme UI Benefit:**
- A dedicated "Artifacts" tab in the task inspector, allowing one-click preview of generated code or images.

---

## 3. Unified Session Model (Option C)

**The Paperclip Feature:** Every unit of work (tasks, discussions, loops) flows through one queue.

**Implementation in superharness:**
- Refactor `shux discuss` to write a "shadow" task to the `inbox` table.
- Discussion rounds get a `type: discussion` field in the protocol.
- The watcher handles `auto_dispatch` for discussions just like regular tasks.

**Morpheme UI Benefit:**
- Eliminates the "invisible work" bug where active discussions don't show in the queue.

---

## 4. Portable "Company" Exports (Secret-Scrubbed)

**The Paperclip Feature:** Portability of the entire org with mandatory secret scrubbing.

**Implementation in superharness:**
- Implement `shux export --scrub`.
- Logic: Iterate through SQLite state and handoff YAMLs, applying regex-based redaction (API keys, SSH keys, `.env` patterns) before bundling into a `.shpack` (ZIP).
- Add `shux import <path>` to restore a project from a scrubbed bundle.

**Morpheme UI Benefit:**
- "Clone Project" or "Export Snapshot" buttons in the dashboard.

---

## 5. Visual Context / Screenshot Support

**The Paperclip Feature:** Support for visual context and UI artifacts (E2B/screenshots).

**Implementation in superharness:**
- Add `visual_context` (list of image paths) to the Handoff schema.
- Update `shux adapter-payload` to include base64-encoded thumbnails or local paths for these images.

**Morpheme UI Benefit:**
- Inline rendering of screenshots in the activity log—critical for debugging UI/Browser-based agent tasks.
