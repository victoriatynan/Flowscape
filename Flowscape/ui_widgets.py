"""
Reusable immediate-mode UI widgets.

A small, engine-agnostic toolkit so editor panels stop hand-rolling their own
controls. Every widget follows the codebase's existing panel idiom: `draw()`
paints and caches its hit rects; `handle_click(pos)` / `handle_wheel()` /
`handle_motion()` hit-test those cached rects and report what the user did. No
widget imports the editor, the road network, or the simulation -- they take
plain values and return plain results, so any panel (or future tool) can reuse
them without coupling.

Components:
  - ScrollContainer : clip a tall column of content into a viewport with a
                      draggable scrollbar + wheel; any overflowing panel becomes
                      scrollable by wrapping its body in begin()/end().
  - Dropdown        : a compact labeled selector that expands to a popup list,
                      with disabled (placeholder) items.
  - Stepper         : a labeled numeric value with -/+ buttons (min/max/step).
  - Button          : a one-shot clickable.
  - ConfirmDialog   : a centered modal (title + message + Confirm/Cancel) over a
                      dimming overlay, for destructive actions.

Children drawn inside a ScrollContainer are painted at SCREEN coordinates (using
the origin begin() returns), so their cached rects are already screen-space and
hit-test directly -- callers just gate clicks to the viewport.
"""

import pygame

# --- Shared theme (mirrors road_editor's COLOR_* so widgets blend in) --------
WIDGET_BG = (45, 48, 54)
WIDGET_FILL = (50, 53, 60)
WIDGET_FILL_HOVER = (68, 72, 82)
WIDGET_ACCENT = (80, 130, 200)
WIDGET_TEXT = (230, 230, 230)
WIDGET_TEXT_DIM = (110, 110, 110)
WIDGET_BORDER = (90, 130, 180)
WIDGET_HEADER = (255, 210, 90)
WIDGET_DANGER = (200, 70, 70)
WIDGET_DANGER_HOVER = (225, 95, 95)

WHEEL_STEP_PX = 28


def _draw_text(surface, font, text, color, pos):
    surface.blit(font.render(text, True, color), pos)


def _centered_text(surface, font, text, color, rect):
    s = font.render(text, True, color)
    surface.blit(s, s.get_rect(center=rect.center))


# ----------------------------------------------------------------------
class ScrollContainer:
    """Vertical scroll viewport. Usage per frame:

        ox, oy = sc.begin(surface, viewport_rect)
        # draw content starting at (ox, oy); track its total height
        sc.end(surface, content_height)

    Content height drives clamping and the scrollbar; if it fits, no bar is
    drawn and scroll stays 0."""

    BAR_W = 6

    def __init__(self):
        self.scroll = 0.0
        self._vp = None
        self._content_h = 0
        self._prev_clip = None
        self._thumb = None
        self._dragging = False
        self._drag_offset = 0

    def _max_scroll(self):
        if self._vp is None:
            return 0.0
        return max(0.0, self._content_h - self._vp.height)

    def begin(self, surface, viewport_rect):
        self._vp = viewport_rect
        self._prev_clip = surface.get_clip()
        surface.set_clip(viewport_rect)
        return viewport_rect.x, viewport_rect.y - int(self.scroll)

    def end(self, surface, content_height):
        self._content_h = content_height
        self.scroll = max(0.0, min(self.scroll, self._max_scroll()))
        surface.set_clip(self._prev_clip)
        self._thumb = None
        if self._content_h > self._vp.height:
            track_x = self._vp.right - self.BAR_W - 2
            ratio = self._vp.height / self._content_h
            thumb_h = max(24, int(self._vp.height * ratio))
            travel = self._vp.height - thumb_h
            t = (self.scroll / self._max_scroll()) if self._max_scroll() else 0.0
            thumb_y = self._vp.y + int(t * travel)
            self._thumb = pygame.Rect(track_x, thumb_y, self.BAR_W, thumb_h)
            pygame.draw.rect(surface, WIDGET_FILL,
                             pygame.Rect(track_x, self._vp.y, self.BAR_W, self._vp.height),
                             border_radius=3)
            pygame.draw.rect(surface, WIDGET_ACCENT, self._thumb, border_radius=3)

    def contains(self, pos):
        return self._vp is not None and self._vp.collidepoint(pos)

    def handle_wheel(self, dy):
        """Scroll by wheel notches (dy>0 = up). Returns True if it consumed
        the scroll (there was anything to scroll)."""
        if self._max_scroll() <= 0:
            return False
        self.scroll = max(0.0, min(self.scroll - dy * WHEEL_STEP_PX, self._max_scroll()))
        return True

    def handle_click(self, pos):
        """Begin a scrollbar drag if the thumb was grabbed. Returns True if the
        click landed on the scrollbar (caller should treat it as consumed)."""
        if self._thumb and self._thumb.collidepoint(pos):
            self._dragging = True
            self._drag_offset = pos[1] - self._thumb.y
            return True
        return False

    def handle_motion(self, pos):
        if not self._dragging or self._thumb is None:
            return False
        thumb_h = self._thumb.height
        travel = max(1, self._vp.height - thumb_h)
        new_y = pos[1] - self._drag_offset - self._vp.y
        t = max(0.0, min(1.0, new_y / travel))
        self.scroll = t * self._max_scroll()
        return True

    def release(self):
        self._dragging = False

    @property
    def dragging(self):
        return self._dragging


# ----------------------------------------------------------------------
class Dropdown:
    """Compact selector that expands to a popup list. `options` is an ordered
    list of (value, label, enabled). The popup is drawn separately via
    draw_popup() so the owner can paint it LAST (on top of everything)."""

    ROW_H = 24

    def __init__(self, options, value):
        self.options = list(options)
        self.value = value
        self.is_open = False
        self._box = None
        self._item_rects = []     # [(value, rect, enabled), ...]

    def set_options(self, options, value):
        self.options = list(options)
        self.value = value

    def _label_for(self, value):
        for v, label, _en in self.options:
            if v == value:
                return label
        return str(value)

    def draw_box(self, surface, rect, font):
        self._box = rect
        pygame.draw.rect(surface, WIDGET_FILL, rect, border_radius=4)
        pygame.draw.rect(surface, WIDGET_BORDER, rect, 1, border_radius=4)
        _draw_text(surface, font, self._label_for(self.value), WIDGET_TEXT,
                   (rect.x + 8, rect.y + (rect.height - font.get_height()) // 2))
        # caret
        cx, cy = rect.right - 14, rect.centery
        pygame.draw.polygon(surface, WIDGET_TEXT,
                            [(cx - 4, cy - 2), (cx + 4, cy - 2), (cx, cy + 3)])

    def popup_rect(self):
        if self._box is None:
            return None
        h = self.ROW_H * len(self.options)
        return pygame.Rect(self._box.x, self._box.bottom + 2, self._box.width, h)

    def draw_popup(self, surface, font, mouse_pos=None):
        """Draw the expanded list (only when open). Call after all other panel
        content so it sits on top."""
        self._item_rects = []
        if not self.is_open or self._box is None:
            return
        panel = self.popup_rect()
        pygame.draw.rect(surface, WIDGET_BG, panel)
        pygame.draw.rect(surface, WIDGET_BORDER, panel, 1)
        for i, (value, label, enabled) in enumerate(self.options):
            r = pygame.Rect(panel.x, panel.y + i * self.ROW_H, panel.width, self.ROW_H)
            hovered = enabled and mouse_pos is not None and r.collidepoint(mouse_pos)
            if value == self.value:
                pygame.draw.rect(surface, WIDGET_ACCENT, r)
            elif hovered:
                pygame.draw.rect(surface, WIDGET_FILL_HOVER, r)
            color = WIDGET_TEXT if enabled else WIDGET_TEXT_DIM
            text = label if enabled else f"{label}  (soon)"
            _draw_text(surface, font, text, color,
                       (r.x + 8, r.y + (r.height - font.get_height()) // 2))
            self._item_rects.append((value, r, enabled))

    def handle_click(self, pos):
        """Returns ("select", value) when a new value is chosen; ("consumed",
        None) for any other click that the dropdown owns (toggling open/closed,
        clicking a disabled row, or dismissing); None if the click missed it."""
        if self.is_open:
            for value, r, enabled in self._item_rects:
                if r.collidepoint(pos):
                    if not enabled:
                        return ("consumed", None)
                    self.is_open = False
                    if value != self.value:
                        self.value = value
                        return ("select", value)
                    return ("consumed", None)
            # click outside the open popup -> dismiss
            self.is_open = False
            if self._box and self._box.collidepoint(pos):
                return ("consumed", None)
            return ("consumed", None)
        if self._box and self._box.collidepoint(pos):
            self.is_open = True
            return ("consumed", None)
        return None


# ----------------------------------------------------------------------
class Stepper:
    """Labeled numeric value with -/+ buttons. Stateless about the value (the
    owner stores it); reports a step direction on click."""

    BTN = 22

    def __init__(self, label):
        self.label = label
        self._minus = None
        self._plus = None

    def draw(self, surface, rect, font, value, value_text=None):
        self._minus = None
        self._plus = None
        text = value_text if value_text is not None else str(value)
        _draw_text(surface, font, f"{self.label}: {text}", WIDGET_TEXT,
                   (rect.x, rect.y + (rect.height - font.get_height()) // 2))
        self._plus = pygame.Rect(rect.right - self.BTN, rect.y, self.BTN, rect.height)
        self._minus = pygame.Rect(rect.right - 2 * self.BTN - 6, rect.y, self.BTN, rect.height)
        for r, glyph in ((self._minus, "-"), (self._plus, "+")):
            pygame.draw.rect(surface, WIDGET_FILL, r, border_radius=4)
            pygame.draw.rect(surface, WIDGET_BORDER, r, 1, border_radius=4)
            _centered_text(surface, font, glyph, WIDGET_TEXT, r)

    def handle_click(self, pos):
        if self._minus and self._minus.collidepoint(pos):
            return -1
        if self._plus and self._plus.collidepoint(pos):
            return 1
        return None


# ----------------------------------------------------------------------
class Button:
    """A one-shot clickable button."""

    def __init__(self, label, danger=False):
        self.label = label
        self.danger = danger
        self._rect = None

    def draw(self, surface, rect, font, mouse_pos=None):
        self._rect = rect
        hovered = mouse_pos is not None and rect.collidepoint(mouse_pos)
        if self.danger:
            color = WIDGET_DANGER_HOVER if hovered else WIDGET_DANGER
        else:
            color = WIDGET_FILL_HOVER if hovered else WIDGET_FILL
        pygame.draw.rect(surface, color, rect, border_radius=4)
        pygame.draw.rect(surface, WIDGET_BORDER, rect, 1, border_radius=4)
        _centered_text(surface, font, self.label, WIDGET_TEXT, rect)

    def handle_click(self, pos):
        return self._rect is not None and self._rect.collidepoint(pos)


# ----------------------------------------------------------------------
class ConfirmDialog:
    """Centered modal for destructive actions. While active the owner should
    route ALL clicks here and draw it last. Returns 'confirm'/'cancel'."""

    W = 380
    H = 150
    PAD = 18
    BTN_W = 110
    BTN_H = 34

    def __init__(self, title, message, confirm_label="Delete", cancel_label="Cancel",
                 danger=True):
        self.title = title
        self.message = message
        self._confirm = Button(confirm_label, danger=danger)
        self._cancel = Button(cancel_label, danger=False)
        self._panel = None

    def draw(self, surface, screen_rect, font, header_font, mouse_pos=None):
        overlay = pygame.Surface(screen_rect.size, pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 130))
        surface.blit(overlay, screen_rect.topleft)

        panel = pygame.Rect(0, 0, self.W, self.H)
        panel.center = screen_rect.center
        self._panel = panel
        pygame.draw.rect(surface, WIDGET_BG, panel, border_radius=6)
        pygame.draw.rect(surface, WIDGET_BORDER, panel, 1, border_radius=6)

        _draw_text(surface, header_font, self.title, WIDGET_HEADER,
                   (panel.x + self.PAD, panel.y + self.PAD))
        for i, line in enumerate(self._wrap(self.message, font, panel.width - 2 * self.PAD)):
            _draw_text(surface, font, line, WIDGET_TEXT,
                       (panel.x + self.PAD, panel.y + self.PAD + 30 + i * 20))

        cy = panel.bottom - self.PAD - self.BTN_H
        self._cancel.draw(surface, pygame.Rect(panel.x + self.PAD, cy, self.BTN_W, self.BTN_H),
                          font, mouse_pos)
        self._confirm.draw(surface, pygame.Rect(panel.right - self.PAD - self.BTN_W, cy,
                                                self.BTN_W, self.BTN_H), font, mouse_pos)

    @staticmethod
    def _wrap(text, font, max_w):
        words = text.split()
        lines, cur = [], ""
        for w in words:
            trial = (cur + " " + w).strip()
            if font.size(trial)[0] <= max_w:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

    def handle_click(self, pos):
        if self._confirm.handle_click(pos):
            return "confirm"
        if self._cancel.handle_click(pos):
            return "cancel"
        return None
