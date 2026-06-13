import pygame
import math


def _lerp_color(a, b, t):
    t = max(0.0, min(1.0, t))
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def _flow_color(flow: float) -> tuple:
    """0.0 = red, 0.5 = yellow, 1.0 = green."""
    if flow <= 0.5:
        return _lerp_color((200, 40, 40), (210, 180, 20), flow * 2)
    else:
        return _lerp_color((210, 180, 20), (40, 190, 80), (flow - 0.5) * 2)


class ControlNode:
    """The draggable midpoint handle on a Bézier road. Not added to the main nodes list."""

    RADIUS = 7
    COLOR = (160, 120, 255)
    COLOR_HOVER = (200, 170, 255)
    COLOR_SELECTED = (255, 255, 255)

    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.selected = False
        self.hovered = False

    def screen_pos(self, camera):
        sx = (self.x - camera.x) * camera.zoom
        sy = (self.y - camera.y) * camera.zoom
        return int(sx), int(sy)

    def draw(self, screen, camera):
        sx, sy = self.screen_pos(camera)
        r = max(4, int(self.RADIUS * camera.zoom))

        if self.selected:
            color = self.COLOR_SELECTED
        elif self.hovered:
            color = self.COLOR_HOVER
        else:
            color = self.COLOR

        # Diamond shape
        pts = [
            (sx, sy - r),
            (sx + r, sy),
            (sx, sy + r),
            (sx - r, sy),
        ]
        pygame.draw.polygon(screen, color, pts)
        pygame.draw.polygon(
            screen,
            (30, 30, 30),
            pts,
            max(1, int(1.5 * camera.zoom)),
        )

    def hit_test(self, sx, sy, camera):
        cx, cy = self.screen_pos(camera)
        r = max(8, int(self.RADIUS * camera.zoom)) + 4
        return abs(sx - cx) + abs(sy - cy) <= r


class RoadSegment:
    """A quadratic Bézier road between two endpoint Nodes with a draggable control node."""

    ROAD_COLOR = (70, 75, 85)
    ROAD_SELECTED_COLOR = (255, 200, 60)
    LANE_COLOR = (110, 115, 125)
    ROAD_WIDTH_WORLD = 12
    CURVE_STEPS = 60
    ARC_SAMPLES = 100

    def __init__(self, node_a, node_b):
        self.node_a = node_a
        self.node_b = node_b
        self.selected = False

        mx = (node_a.x + node_b.x) / 2
        my = (node_a.y + node_b.y) / 2
        dx = node_b.x - node_a.x
        dy = node_b.y - node_a.y
        length = math.hypot(dx, dy) or 1
        nudge = min(length * 0.05, 20)

        self.ctrl = ControlNode(
            mx - dy / length * nudge,
            my + dx / length * nudge,
        )

        self.arc_lut = []
        self._build_lut()

        # Flow: None = no cars, 0.0 = full stop, 1.0 = full speed
        self.flow: float | None = None

    # ------------------------------------------------------------------
    # Bézier helpers
    # ------------------------------------------------------------------

    def bezier_point(self, t):
        ax, ay = self.node_a.x, self.node_a.y
        bx, by = self.ctrl.x, self.ctrl.y
        cx, cy = self.node_b.x, self.node_b.y

        mt = 1 - t
        x = mt * mt * ax + 2 * mt * t * bx + t * t * cx
        y = mt * mt * ay + 2 * mt * t * by + t * t * cy
        return x, y

    # ------------------------------------------------------------------
    # Arc-length LUT
    # ------------------------------------------------------------------

    def _build_lut(self):
        n = self.ARC_SAMPLES
        lut = [(0.0, 0.0)]

        prev = self.bezier_point(0.0)
        total = 0.0

        for i in range(1, n + 1):
            t = i / n
            pt = self.bezier_point(t)
            total += math.hypot(pt[0] - prev[0], pt[1] - prev[1])
            lut.append((total, t))
            prev = pt

        self.arc_lut = lut

    def arc_to_t(self, arc: float) -> float:
        lut = self.arc_lut
        if not lut:
            return 0.0

        total = lut[-1][0]
        arc = max(0.0, min(total, arc))

        lo, hi = 0, len(lut) - 1

        while lo + 1 < hi:
            mid = (lo + hi) // 2
            if lut[mid][0] <= arc:
                lo = mid
            else:
                hi = mid

        d0, t0 = lut[lo]
        d1, t1 = lut[hi]

        if d1 == d0:
            return t0

        frac = (arc - d0) / (d1 - d0)
        return t0 + frac * (t1 - t0)

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _screen_polyline(self, camera, steps=None):
        n = steps or self.CURVE_STEPS
        pts = []

        for i in range(n + 1):
            wx, wy = self.bezier_point(i / n)
            sx = int((wx - camera.x) * camera.zoom)
            sy = int((wy - camera.y) * camera.zoom)
            pts.append((sx, sy))

        return pts
def update_flow(self, cars):
    speeds = []
    count = 0

    for c in cars:
        if c.road is self:
            speeds.append(c._current_speed)
            count += 1

    if not speeds:
        self.flow = None
        return

    avg_speed = sum(speeds) / len(speeds)

    speed_factor = avg_speed / 160.0
    density_factor = 1.0 - min(count / 12.0, 1.0)

    self.flow = max(0.0, min(1.0, 0.6 * speed_factor + 0.4 * density_factor))
    def draw(self, screen, camera):
        pts = self._screen_polyline(camera)

        if len(pts) < 2:
            return

        width = max(2, int(self.ROAD_WIDTH_WORLD * camera.zoom * 2))

        if self.selected:
            road_color = self.ROAD_SELECTED_COLOR
            lane_color = (255, 230, 100)
        elif self.flow is None:
            road_color = self.ROAD_COLOR
            lane_color = self.LANE_COLOR
        else:
            road_color = _flow_color(self.flow)
            lane_color = _lerp_color((60, 60, 60), (200, 230, 200), self.flow)

        pygame.draw.lines(screen, road_color, False, pts, width)

        if camera.zoom > 0.3:
            self._draw_dashed_curve(
                screen,
                pts,
                lane_color,
                max(1, int(2 * camera.zoom)),
            )

        if self.selected or self.ctrl.hovered or self.ctrl.selected:
            self._draw_ctrl_guides(screen, camera)

        self.ctrl.draw(screen, camera)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _draw_ctrl_guides(self, screen, camera):
        ax = int((self.node_a.x - camera.x) * camera.zoom)
        ay = int((self.node_a.y - camera.y) * camera.zoom)
        bx = int((self.node_b.x - camera.x) * camera.zoom)
        by = int((self.node_b.y - camera.y) * camera.zoom)
        cx, cy = self.ctrl.screen_pos(camera)

        pygame.draw.line(screen, (100, 80, 160), (ax, ay), (cx, cy), 1)
        pygame.draw.line(screen, (100, 80, 160), (bx, by), (cx, cy), 1)

    def _draw_dashed_curve(self, screen, pts, color, thickness):
        dash = 20
        gap = 14
        pos = 0.0
        drawing = True

        for i in range(1, len(pts)):
            p0 = pts[i - 1]
            p1 = pts[i]

            seg_len = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            if seg_len == 0:
                continue

            remaining = seg_len
            t0 = 0.0

            while remaining > 0:
                budget = (dash if drawing else gap) - pos
                step = min(budget, remaining)

                t1 = t0 + step / seg_len

                if drawing:
                    sx0 = int(p0[0] + (p1[0] - p0[0]) * t0)
                    sy0 = int(p0[1] + (p1[1] - p0[1]) * t0)
                    sx1 = int(p0[0] + (p1[0] - p0[0]) * t1)
                    sy1 = int(p0[1] + (p1[1] - p0[1]) * t1)

                    pygame.draw.line(
                        screen,
                        color,
                        (sx0, sy0),
                        (sx1, sy1),
                        thickness,
                    )

                pos += step
                remaining -= step
                t0 = t1

                if pos >= (dash if drawing else gap):
                    pos = 0.0
                    drawing = not drawing