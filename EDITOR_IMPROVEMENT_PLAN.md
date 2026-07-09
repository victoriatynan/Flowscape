> **Status (2026-07-08): items 1–4 implemented for the web client** (the
> "Editor" here is now the browser app; pygame was retired in the web
> migration's Phase 6).
> 1. Continuous road drawing: the Road tool connects to a hit node or has
>    the backend create the endpoint node + road as ONE undoable compound
>    command (`POST /api/edit/road` with `end_pos`); the anchor advances so
>    drawing continues. No confirmation modal — undo is the safety net.
> 2. Road markings are generated from the lane configuration server-side
>    (`road_style.profile_markings` → `/api/geometry`): amber center
>    boundary, dashed separators between same-direction lanes, cream edge
>    lines — never a divider through a lane center.
> 3. Map Analysis panel: read-only `GET /api/analysis` (building mix,
>    EXACT deterministic day-0 demand rather than estimates, network
>    totals, connectivity warnings) shown in the client's Analysis panel,
>    refreshed on every edit. Capacity indicators remain future work — they
>    require a road-capacity model that is a simulation feature, not a
>    panel feature.
> 4. Warnings (no road connection, disconnected from the main network,
>    residential with no destinations) are served with the analysis.
> Original text follows.

# Flowscape Editor Workflow Improvements & Map Analysis Plan

## Overview

This document outlines several quality-of-life improvements for the Flowscape editor. The primary goals are to reduce unnecessary tool switching, improve the accuracy of the road visualization, provide better feedback while building maps, and create a scalable framework for future editor features.

These systems should remain independent of the traffic simulation itself and instead enhance the editing experience.

---

# 1. Automatic Node Creation During Road Drawing

## Objective

Allow roads to be created continuously without requiring the user to manually switch between the Road Tool and the Node Tool.

## Current Workflow

Current behavior requires:

1. Switch to the Node Tool.
2. Create a new node.
3. Switch back to the Road Tool.
4. Connect the road.

This interrupts the user's workflow and slows down map creation.

## Desired Workflow

When using the Road Tool:

1. Begin drawing from an existing node.
2. Drag toward empty space.
3. If no existing node is detected, clicking should present a confirmation to create a new node.
4. Once confirmed:

   * Create the new node.
   * Connect the road automatically.
   * Keep the Road Tool active so the user can continue drawing.

The Road Tool should intelligently determine whether the destination is:

* An existing node (snap and connect)
* Empty space (offer to create a node)

Future settings may include:

* Always create endpoint automatically.
* Always ask for confirmation.
* Never automatically create nodes.

---

# 2. Road Marking Rendering Improvements

## Objective

Improve the visual representation of roads so markings accurately match the lane configuration.

## Current Issues

Current rendering shows:

* Dashed lane markings running through the center of lanes.
* No visible centerline separating opposing directions.

This causes roads to appear visually incorrect.

## Desired Behavior

Road markings should be generated from the lane configuration.

### Same-direction lanes

Use dashed white lane divider markings.

### Opposing directions

Display an appropriate centerline.

Initially support:

* Solid yellow centerline

Future support should include:

* Double solid yellow
* Double yellow with dashed passing side
* Solid white
* Dashed white
* No centerline
* Temporary construction markings

The renderer should determine markings from road properties rather than hard-coded drawing rules.

No lane divider should ever appear running through the center of a lane.

---

# 3. Map Analysis Panel

## Objective

Provide users with meaningful estimates about the network they have created before starting the simulation.

Rather than immediately running thousands of trips, users should be able to understand the expected scale of the simulation.

The panel should update automatically whenever the map changes.

---

## Initial Statistics

### Buildings

Display counts for:

* Residential
* Commercial
* Industrial
* Education
* Public Services
* Recreation

---

### Estimated Demand

Display estimates for:

* Daily trips
* Morning peak trips
* Evening peak trips
* Estimated active vehicles
* Population served
* Jobs provided

These values should come from the existing building demand generation system.

---

### Network Statistics

Display:

* Total roads
* Total nodes
* Total intersections
* Total lane length
* Average speed limit

Future additions may include:

* Average intersection spacing
* Lane density
* Network connectivity

---

### Capacity Indicators

Eventually compare demand against network capacity.

Examples:

Residential Demand
████████░░ 80%

Road Capacity
██████░░░░ 60%

Estimated Congestion
Medium

This gives users an indication of whether their road network is likely to experience congestion before running the simulation.

---

### Future Analysis

The Map Analysis panel should eventually support:

* Demand heatmaps
* Origin/Destination summaries
* Trip generation reports
* Building contribution reports
* Congestion prediction
* Connectivity warnings
* Network health indicators
* Capacity utilization
* Future transit analysis

The panel should remain informational and should not modify simulation data.

---

# 4. User Guidance & Feedback

Whenever the user edits the map, provide useful feedback.

Examples:

"Estimated Daily Trips Updated"

"Road Network Connected"

"Warning: Residential area has no commercial destinations."

"Industrial district is unreachable."

"School has no road connection."

The purpose is to help users identify issues before running the simulation.

---

# 5. Architecture

These systems should remain modular and independent.

Editor
|
├── Road Tool
|     ├── Existing Node Detection
|     ├── Automatic Node Creation
|     ├── Endpoint Confirmation
|     └── Continuous Road Placement
|
├── Road Renderer
|     ├── Centerline Generator
|     ├── Lane Divider Generator
|     ├── Road Marking Styles
|     └── Future Pavement Markings
|
├── Map Analysis
|     ├── Building Statistics
|     ├── Demand Estimation
|     ├── Network Statistics
|     ├── Capacity Indicators
|     └── Future Diagnostic Tools
|
└── Notification System
├── Status Messages
├── Warnings
├── Connectivity Checks
└── Analysis Updates

---

# Design Principles

These improvements should follow several guiding principles:

* Minimize unnecessary tool switching.
* Provide immediate visual feedback for editing actions.
* Keep rendering logic separate from simulation logic.
* Keep analysis tools read-only and informational.
* Generate road markings from lane data rather than hard-coded rules.
* Allow all systems to grow without requiring architectural redesign.
* Design with future support for larger maps, additional road types, more advanced traffic analysis, and the planned web-based version of Flowscape.

The long-term goal is to make Flowscape feel like a professional transportation planning and simulation editor, where the interface helps users build accurate networks efficiently while providing meaningful insight into the expected behavior of the simulation before it is run.
