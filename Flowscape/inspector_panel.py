"""
Inspector / Properties panel.

Shows editable properties for the currently selected object and reports user
actions back to the controller (it never mutates the network or controllers
itself -- same contract as every other panel). Built entirely from the reusable
ui_widgets toolkit and from data (the intersection-control catalog + settings
schema), so adding a property section or a new control type needs no changes
here.

Today it renders one section -- Intersection Control, for junction nodes -- plus
a Delete action. Road/building property sections slot in the same way later.

All content is laid out inside a ScrollContainer, so the panel automatically
scrolls when it outgrows the available sidebar height; no control is ever lost
off-screen.
"""

import pygame

from ui_widgets import (ScrollContainer, Dropdown, Stepper, Button,
                        WIDGET_TEXT, WIDGET_HEADER, WIDGET_TEXT_DIM)
from intersection_control import (CONTROL_TYPE_ORDER, CONTROL_TYPE_LABELS,
                                  CONTROL_TYPE_IMPLEMENTED, control_settings_schema,
                                  DEFAULT_INTERSECTION_CONTROL)


def _format_value(spec, value):
    return str(int(round(value))) if spec.type == "int" else f"{value:.1f}"


class InspectorPanel:
    """Properties panel for the selected object. Stateful only in the widgets
    it owns (dropdown open-state, scroll position); the values it shows are read
    fresh from the object each frame."""

    PAD = 14
    ROW_H = 26
    GAP = 8

    def __init__(self, font, header_font):
        self.font = font
        self.header_font = header_font
        self.scroll = ScrollContainer()
        self.control_dd = Dropdown(self._control_options(), DEFAULT_INTERSECTION_CONTROL)
        self._steppers = {}                 # field.key -> Stepper
        self._delete_btn = Button("Delete", danger=True)
        # Per-frame context captured in draw(), used by handle_click().
        self._node = None
        self._kind = None
        self._schema = ()

    @staticmethod
    def _control_options():
        return [(k, CONTROL_TYPE_LABELS[k], k in CONTROL_TYPE_IMPLEMENTED)
                for k in CONTROL_TYPE_ORDER]

    def _stepper(self, key, label):
        st = self._steppers.get(key)
        if st is None:
            st = Stepper(label)
            self._steppers[key] = st
        return st

    # ------------------------------------------------------------------
    def draw(self, surface, viewport_rect, network, node, mouse_pos=None):
        """Render the inspector for `node` into `viewport_rect`. Returns the
        viewport bottom (so the sidebar can place anything beneath it)."""
        self._node = node
        is_intersection = node is not None and network.is_intersection(node.id)

        ox, oy = self.scroll.begin(surface, viewport_rect)
        x = ox + self.PAD
        w = viewport_rect.width - 2 * self.PAD - self.scroll.BAR_W
        y = oy + self.PAD

        surface.blit(self.header_font.render("Inspector", True, WIDGET_HEADER), (x, y))
        y += self.header_font.get_height() + self.GAP

        if node is None:
            surface.blit(self.font.render("Nothing selected.", True, WIDGET_TEXT_DIM), (x, y))
            y += self.ROW_H
            self.scroll.end(surface, (y - oy) + self.PAD)
            return viewport_rect.bottom

        surface.blit(self.font.render(f"Node #{node.id}", True, WIDGET_TEXT), (x, y))
        y += self.ROW_H

        if is_intersection:
            y = self._draw_control_section(surface, x, y, w, node, mouse_pos)
        else:
            surface.blit(self.font.render("(not a junction)", True, WIDGET_TEXT_DIM), (x, y))
            y += self.ROW_H

        # Object actions.
        y += self.GAP
        self._delete_btn.draw(surface, pygame.Rect(x, y, w, self.ROW_H + 6),
                              self.font, mouse_pos)
        y += self.ROW_H + 6

        content_h = (y - oy) + self.PAD
        self.scroll.end(surface, content_h)

        # The open dropdown popup is drawn LAST and UN-clipped so it overlays
        # everything (and isn't cut off by the scroll viewport).
        self.control_dd.draw_popup(surface, self.font, mouse_pos)
        return viewport_rect.bottom

    def _draw_control_section(self, surface, x, y, w, node, mouse_pos):
        self._kind = node.data.get("control", DEFAULT_INTERSECTION_CONTROL)
        surface.blit(self.header_font.render("Intersection Control", True, WIDGET_HEADER), (x, y))
        y += self.header_font.get_height() + self.GAP

        surface.blit(self.font.render("Control Type", True, WIDGET_TEXT), (x, y))
        y += self.font.get_height() + 4
        self.control_dd.set_options(self._control_options(), self._kind)
        self.control_dd.draw_box(surface, pygame.Rect(x, y, w, self.ROW_H), self.font)
        y += self.ROW_H + self.GAP

        self._schema = control_settings_schema(self._kind)
        for spec in self._schema:
            value = node.data.get(spec.key, spec.default)
            st = self._stepper(spec.key, spec.label)
            st.draw(surface, pygame.Rect(x, y, w, self.ROW_H), self.font,
                    value, value_text=_format_value(spec, value))
            y += self.ROW_H + self.GAP
        if not self._schema:
            surface.blit(self.font.render("No settings for this type.", True,
                                          WIDGET_TEXT_DIM), (x, y))
            y += self.ROW_H
        return y

    # ------------------------------------------------------------------
    def handle_click(self, pos):
        """Returns an action for the controller to apply:
          ("set_control", kind) | ("set_setting", key, value) |
          ("delete", None) | ("consumed", None) | None.
        'consumed' = the inspector handled the click (block other panels)."""
        # An open dropdown popup can extend past the viewport, so it gets first
        # crack regardless of where the click landed.
        if self.control_dd.is_open:
            res = self.control_dd.handle_click(pos)
            if res is not None:
                action, value = res
                return ("set_control", value) if action == "select" else ("consumed", None)

        if not self.scroll.contains(pos):
            return None
        if self.scroll.handle_click(pos):
            return ("consumed", None)

        if self.control_dd.handle_click(pos) is not None:     # opened the box
            return ("consumed", None)

        for key, st in self._steppers.items():
            direction = st.handle_click(pos)
            if direction is not None:
                return self._stepped_setting(key, direction)

        if self._delete_btn.handle_click(pos):
            return ("delete", None)
        return None

    def _stepped_setting(self, key, direction):
        """Compute the new clamped value for a settings stepper click."""
        spec = next((s for s in self._schema if s.key == key), None)
        if spec is None or self._node is None:
            return ("consumed", None)
        current = self._node.data.get(spec.key, spec.default)
        value = current + direction * spec.step
        value = max(spec.minimum, min(spec.maximum, value))
        if spec.type == "int":
            value = int(round(value))
        return ("set_setting", key, value)

    def handle_wheel(self, dy):
        return self.scroll.handle_wheel(dy)

    def handle_motion(self, pos):
        return self.scroll.handle_motion(pos)

    def release(self):
        self.scroll.release()

    @property
    def dragging(self):
        return self.scroll.dragging

    def close_popups(self):
        self.control_dd.is_open = False
