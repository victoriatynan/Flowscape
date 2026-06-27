"""
Vehicle Dynamics System -- the "how" layer of the driver model.

Three-layer driver model (the structure professional traffic micro-simulators
use, so increasingly sophisticated driver logic can be added without ever
rewriting movement):

  Perception  -- "What does the vehicle know?"        vehicle_perception.py
  Decision    -- "What speed should it target?"       (FUTURE: car-following,
                 traffic lights, stop signs, yielding -> set desired_speed)
  Dynamics    -- "How does it physically reach that speed?"   THIS MODULE

Dynamics owns exactly ONE responsibility: integrating a vehicle's
current_speed toward its desired_speed over time, using its acceleration_rate
and braking_rate. (Turning that speed into distance/position is the MOVEMENT
layer's job -- Vehicle.move -- not this module's.) It is a pure function of the
speed state and dt:

  - it reads NO other vehicle, NO perception result, NO traffic control;
  - the decision layer influences motion ONLY by writing desired_speed --
    it never touches this integration.

That single contract (desired_speed in, motion out) is what keeps the layers
decoupled: a future decision pass can get arbitrarily clever about WHAT speed
to target without changing one line of HOW the target is achieved.

Design philosophy (shared with the rest of Flowscape):
  - Logical data is the source of truth: the speed STATE lives on the Vehicle
    (current/desired/accel/brake); this module only transforms it.
  - Derived values are computed, not stored: motion_state() classifies
    accelerating / cruising / braking on demand from the two speeds; it is
    never persisted onto the vehicle.
"""

# Default kinematic limits (feet, seconds). The world is in feet, so these are
# ft/s^2. Braking is firmer than acceleration, as for a real car. A vehicle may
# override either per-instance; these are only the starting values.
DEFAULT_ACCELERATION_RATE = 8.0    # ft/s^2  (~0.25 g, comfortable pull-away)
DEFAULT_BRAKING_RATE = 16.0        # ft/s^2  (~0.5 g, firmer than accel)

# Speed-match deadband (ft/s): within +/- this of desired_speed, the vehicle is
# considered to be cruising rather than accelerating/braking.
CRUISE_EPS = 1e-3

# Motion-state labels (a DERIVED classification, never stored on the vehicle).
ACCELERATING = "accelerating"
CRUISING = "cruising"
BRAKING = "braking"


def integrate_speed(current_speed, desired_speed, acceleration_rate,
                    braking_rate, dt):
    """New speed after `dt` seconds, ramping current_speed toward desired_speed.

    Below target: accelerate at acceleration_rate. Above target: decelerate at
    braking_rate. Neither ever overshoots the target within the step (the ramp
    snaps exactly to desired_speed on the frame it would cross it), so a vehicle
    settles smoothly into a steady cruise instead of oscillating. Speed never
    goes negative (vehicles do not reverse).

    Pure: depends only on its arguments; reads and mutates nothing else.
    """
    if dt <= 0:
        return current_speed
    if current_speed < desired_speed:
        return min(desired_speed, current_speed + acceleration_rate * dt)
    if current_speed > desired_speed:
        return max(desired_speed, max(0.0, current_speed - braking_rate * dt))
    return current_speed


def motion_state(current_speed, desired_speed, eps=CRUISE_EPS):
    """Classify the dynamics state for debug/inspection: ACCELERATING (below
    target), BRAKING (above target), or CRUISING (within `eps`). Pure and
    derived purely from the two speeds -- this is intentionally NOT stored on
    the vehicle, matching the project's compute-don't-store philosophy."""
    if desired_speed - current_speed > eps:
        return ACCELERATING
    if current_speed - desired_speed > eps:
        return BRAKING
    return CRUISING
