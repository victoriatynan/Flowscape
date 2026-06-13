"""
Road Snap Mode (editor overlay).

A pure editor-usability layer that sits ON TOP of the existing road editor.
It only influences how NEW roads are previewed and created:

  - SnapModeController : holds the current snap mode (Auto/Straight/Curved)
    and resolves the curve_offset to use for a placement preview/commit.
  - SnapModePanel      : small sidebar radio-button UI for picking the mode.

Strict scope rules (by design):
  - Never reads or mutates existing roads, nodes or zones.
  - Never changes the saved geometry format: a committed road still stores
    only node ids + curve_offset; this module only contributes the offset
    value plus a tiny optional metadata dict ({"mode", "curvature_strength"})
    placed in the road's existing free-form `data` field.
  - No camera, scaling or core-geometry math lives here.

Mode semantics (preview + creation only):
  AUTO     : if the user has manually bent the preview (scroll wheel), that
             offset is used as-is. Otherwise, when the road continues from a
             node with exactly one existing road, and the new chord deviates
             from that road's direction by more than an angle threshold, a
             tangent-continuous curve is suggested; below the threshold (or
             with no context) the preview stays straight.
  STRAIGHT : preview/creation is always a direct line (zero curve_offset).
  CURVE    : preview/creation gets a default perpendicular bezier bulge
             (midpoint control), on top of any manual wheel adjustment.

Modifier overrides (live, while previewing):
  Ctrl  -> force STRAIGHT      Shift -> force CURVE
  (Ctrl wins if both are held.)
"""

import math

import pygame

SNAP_AUTO = "AUTO"
SNAP_STRAIGHT = "STRAIGHT"
SNAP_CURVE = "CURVE"

SNAP_MODE_LABELS = {
    SNAP_AUTO: "Auto",
    SNAP_STRAIGHT: "Straight",
    SNAP_CURVE: "Curved",
}

# Preview centerline colors (visual feedback requirement):
COLOR_SNAP_STRAIGHT = (255, 255, 255)   # white line
COLOR_SNAP_CURVE = (0, 220, 255)        # cyan curve

# Default curved-mode bulge: control-point offset as a fraction of the
# chord length (perpendicular to the chord, midpoint control).
DEFAULT_CURVATURE_STRENGTH = 0.25

# Auto mode: suggest a curve only when the new chord deviates from the
# incoming road direction by more than AUTO_ANGLE_MIN (gentle continuations
# stay straight) and less than AUTO_ANGLE_MAX (sharp corners are treated as
# intentional angles, not smoothed).
AUTO_ANGLE_MIN = math.radians(12.0)
AUTO_ANGLE_MAX = math.radians(80.0)
# Control-point distance along the incoming tangent, as a chord fraction.
AUTO_CONTROL_RATIO = 0.5


def _perp(dx, dy):
    length = math.hypot(dx, dy)
    if length == 0:
        return (0.0, 0.0)
    return (-dy / length, dx / length)


class SnapModeController:
    """Snap-mode state + pure offset resolution. Holds no references to the
    network; callers pass in positions/directions, get an offset back."""

    def __init__(self):
        self.mode = SNAP_AUTO

    def set_mode(self, mode):
        if mode in SNAP_MODE_LABELS:
            self.mode = mode

    def effective_mode(self, shift_held=False, ctrl_held=False):
        """Persistent mode, overridden live by modifiers (Ctrl beats Shift)."""
        if ctrl_held:
            return SNAP_STRAIGHT
        if shift_held:
            return SNAP_CURVE
        return self.mode

    def resolve_offset(self, start, end, user_offset, incoming_dir=None,
                       shift_held=False, ctrl_held=False):
        """
        Map (mode, manual wheel offset, optional continuation context) to the
        curve_offset that the preview/commit should use.

        Returns (offset, resolved_mode) where resolved_mode is always
        SNAP_STRAIGHT or SNAP_CURVE (AUTO resolves to one of the two).
        """
        chord = (end[0] - start[0], end[1] - start[1])
        chord_len = math.hypot(chord[0], chord[1])
        if chord_len < 1e-9:
            return (0.0, 0.0), SNAP_STRAIGHT

        mode = self.effective_mode(shift_held, ctrl_held)

        if mode == SNAP_STRAIGHT:
            return (0.0, 0.0), SNAP_STRAIGHT

        if mode == SNAP_CURVE:
            px, py = _perp(chord[0], chord[1])
            bulge = chord_len * DEFAULT_CURVATURE_STRENGTH
            offset = (px * bulge + user_offset[0], py * bulge + user_offset[1])
            return offset, SNAP_CURVE

        # AUTO: a manual wheel adjustment always wins.
        if abs(user_offset[0]) > 1e-9 or abs(user_offset[1]) > 1e-9:
            return tuple(user_offset), SNAP_CURVE

        # Continuation context: bend tangent-continuously out of the single
        # incoming road when the chord deviates past the angle threshold.
        if incoming_dir is not None:
            ux, uy = chord[0] / chord_len, chord[1] / chord_len
            dot = max(-1.0, min(1.0, incoming_dir[0] * ux + incoming_dir[1] * uy))
            angle = math.acos(dot)
            if AUTO_ANGLE_MIN <= angle <= AUTO_ANGLE_MAX:
                # Quadratic bezier start tangent runs toward the control
                # point, so placing the control point along incoming_dir
                # makes the new road leave the shared node smoothly.
                d = chord_len * AUTO_CONTROL_RATIO
                control = (start[0] + incoming_dir[0] * d,
                           start[1] + incoming_dir[1] * d)
                mid = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
                return (control[0] - mid[0], control[1] - mid[1]), SNAP_CURVE

        return (0.0, 0.0), SNAP_STRAIGHT

    @staticmethod
    def metadata(start, end, offset, resolved_mode):
        """Minimal per-road metadata for the road's free-form `data` dict.
        Geometry itself is still fully regenerated from node positions +
        curve_offset; this is descriptive only."""
        meta = {"mode": resolved_mode}
        if resolved_mode == SNAP_CURVE:
            chord_len = math.hypot(end[0] - start[0], end[1] - start[1])
            if chord_len > 1e-9:
                meta["curvature_strength"] = round(
                    math.hypot(offset[0], offset[1]) / chord_len, 4)
        return meta

    @staticmethod
    def preview_color(resolved_mode):
        return COLOR_SNAP_CURVE if resolved_mode == SNAP_CURVE else COLOR_SNAP_STRAIGHT


class SnapModePanel:
    """
    Subtle sidebar widget: a "Snap Mode" header + three radio rows
    (Auto / Straight / Curved). Pure UI -- reports clicks, owns no editor
    state beyond cached hit-rects from the last draw.
    """

    ROW_HEIGHT = 22
    HEADER_HEIGHT = 20
    PADDING = 8
    SIDE_MARGIN = 16
    RADIO_RADIUS = 6

    COLOR_BG = (32, 34, 39)
    COLOR_BORDER = (55, 58, 66)
    COLOR_HEADER = (255, 210, 90)
    COLOR_TEXT = (210, 210, 210)
    COLOR_TEXT_DIM = (140, 140, 140)
    COLOR_RADIO = (160, 160, 160)
    COLOR_RADIO_ACTIVE = (80, 200, 255)

    OPTIONS = [
        (SNAP_AUTO, "Auto", "1"),
        (SNAP_STRAIGHT, "Straight", "2"),
        (SNAP_CURVE, "Curved", "3"),
    ]

    def __init__(self, font, header_font):
        self.font = font
        self.header_font = header_font
        self._row_rects = []  # [(mode, rect)], refreshed each draw

    def height(self):
        return (self.PADDING * 2 + self.HEADER_HEIGHT
                + self.ROW_HEIGHT * len(self.OPTIONS))

    def draw(self, surface, sidebar_rect, top_y, current_mode):
        """Draw the panel at top_y inside the sidebar; returns its bottom y
        and refreshes the click hit-rects."""
        x = sidebar_rect.x + self.SIDE_MARGIN
        width = sidebar_rect.width - 2 * self.SIDE_MARGIN
        panel = pygame.Rect(x, top_y, width, self.height())

        pygame.draw.rect(surface, self.COLOR_BG, panel, border_radius=4)
        pygame.draw.rect(surface, self.COLOR_BORDER, panel, 1, border_radius=4)

        header = self.header_font.render("Snap Mode", True, self.COLOR_HEADER)
        surface.blit(header, (panel.x + self.PADDING, panel.y + self.PADDING - 2))

        self._row_rects = []
        y = panel.y + self.PADDING + self.HEADER_HEIGHT
        for mode, label, key_hint in self.OPTIONS:
            row = pygame.Rect(panel.x + 2, y, panel.width - 4, self.ROW_HEIGHT)
            self._row_rects.append((mode, row))

            cx = row.x + self.PADDING + self.RADIO_RADIUS
            cy = row.centery
            active = (mode == current_mode)
            ring = self.COLOR_RADIO_ACTIVE if active else self.COLOR_RADIO
            pygame.draw.circle(surface, ring, (cx, cy), self.RADIO_RADIUS, 1)
            if active:
                pygame.draw.circle(surface, self.COLOR_RADIO_ACTIVE, (cx, cy),
                                   self.RADIO_RADIUS - 3)

            text = self.font.render(label, True, self.COLOR_TEXT)
            surface.blit(text, (cx + self.RADIO_RADIUS + 8,
                                cy - text.get_height() // 2))

            hint = self.font.render(key_hint, True, self.COLOR_TEXT_DIM)
            surface.blit(hint, (row.right - self.PADDING - hint.get_width(),
                                cy - hint.get_height() // 2))
            y += self.ROW_HEIGHT

        return panel.bottom

    def handle_click(self, screen_pos):
        """Return the clicked mode id, or None if the click missed the panel."""
        for mode, rect in self._row_rects:
            if rect.collidepoint(screen_pos):
                return mode
        return None
