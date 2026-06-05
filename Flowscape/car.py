import pygame
import math
import random


CAR_COLORS = [
    (220, 60, 60),
    (60, 140, 220),
    (60, 200, 100),
    (220, 180, 40),
    (200, 80, 200),
    (40, 200, 200),
    (240, 130, 40),
    (200, 200, 200),
]

CAR_W = 10
CAR_H = 3

LANE_OFFSET = 6

MIN_GAP = 28
BRAKE_DIST = 90
ACCEL = 60


class Car:
    _id = 0

    def __init__(self, road, direction=1, speed=None):
        Car._id += 1

        self.id = Car._id
        self.color = random.choice(CAR_COLORS)

        self.speed = speed or random.uniform(80, 160)
        self.road = road
        self.direction = direction

        lut = road.arc_lut
        total = lut[-1][0] if lut else 1.0

        self._arc_pos = 0.0 if direction == 1 else total
        self._t = 0.0 if direction == 1 else 1.0

        self._current_speed = self.speed

        self.x = 0.0
        self.y = 0.0
        self.angle = 0.0

        self._sync_position()

    # ----------------------------
    # Geometry
    # ----------------------------

    def _tangent_at(self, t):
        eps = 0.005

        t_fwd = max(0.0, min(1.0, t + eps * self.direction))
        t_bck = max(0.0, min(1.0, t - eps * self.direction))

        x1, y1 = self.road.bezier_point(t_bck)
        x2, y2 = self.road.bezier_point(t_fwd)

        dx = x2 - x1
        dy = y2 - y1

        length = math.hypot(dx, dy) or 1.0
        return dx / length, dy / length

    def _sync_position(self):
        cx, cy = self.road.bezier_point(self._t)
        tx, ty = self._tangent_at(self._t)

        self.angle = math.atan2(ty, tx)

        # lane offset (right side)
        self.x = cx + ty * LANE_OFFSET
        self.y = cy - tx * LANE_OFFSET

    # ----------------------------
    # Update
    # ----------------------------

    def update(self, dt_sec, all_roads, all_cars):

        gap, leader = self._find_leader(all_cars)

        if leader is not None and gap < BRAKE_DIST:
            if gap <= MIN_GAP:
                target_speed = 0.0
            else:
                frac = (gap - MIN_GAP) / (BRAKE_DIST - MIN_GAP)
                target_speed = leader._current_speed * frac

            if target_speed < self._current_speed:
                self._current_speed = target_speed
            else:
                self._current_speed = min(
                    self.speed,
                    self._current_speed + ACCEL * dt_sec
                )
        else:
            self._current_speed = min(
                self.speed,
                self._current_speed + ACCEL * dt_sec
            )

        dist = self._current_speed * dt_sec

        lut = self.road.arc_lut
        total = lut[-1][0] if lut else 1.0

        self._arc_pos += dist * self.direction

        if self._arc_pos >= total:
            overshoot = self._arc_pos - total
            arrive_node = self.road.node_b
            self._pick_next(arrive_node, all_roads, overshoot)

        elif self._arc_pos <= 0:
            overshoot = -self._arc_pos
            arrive_node = self.road.node_a
            self._pick_next(arrive_node, all_roads, overshoot)

        else:
            self._t = self.road.arc_to_t(self._arc_pos)
            self._sync_position()

    # ----------------------------
    # Leader detection
    # ----------------------------

    def _find_leader(self, all_cars):
        best_gap = math.inf
        best_car = None

        my_arc = self._arc_pos

        for other in all_cars:
            if other is self:
                continue

            if other.road is not self.road:
                continue

            if other.direction != self.direction:
                continue

            if self.direction == 1 and other._arc_pos > my_arc:
                gap = other._arc_pos - my_arc - CAR_W * 2

            elif self.direction == -1 and other._arc_pos < my_arc:
                gap = my_arc - other._arc_pos - CAR_W * 2

            else:
                continue

            if gap < best_gap:
                best_gap = gap
                best_car = other

        return best_gap, best_car

    # ----------------------------
    # Road switching
    # ----------------------------

    def _pick_next(self, node, all_roads, overshoot):
        options = []

        for r in all_roads:
            if r is self.road:
                continue

            if r.node_a is node:
                options.append((r, 1))
            elif r.node_b is node:
                options.append((r, -1))

        if not options:
            self.direction *= -1

            lut = self.road.arc_lut
            total = lut[-1][0] if lut else 1.0

            self._arc_pos = total - overshoot if self.direction == 1 else overshoot
            self._arc_pos = max(0.0, min(total, self._arc_pos))

            self._t = self.road.arc_to_t(self._arc_pos)

        else:
            next_road, next_dir = random.choice(options)

            self.road = next_road
            self.direction = next_dir

            lut = next_road.arc_lut
            total = lut[-1][0] if lut else 1.0

            self._arc_pos = overshoot if next_dir == 1 else total - overshoot
            self._arc_pos = max(0.0, min(total, self._arc_pos))

            self._t = next_road.arc_to_t(self._arc_pos)

        self._sync_position()

    # ----------------------------
    # Draw
    # ----------------------------

    def draw(self, screen, camera):

        sx = (self.x - camera.x) * camera.zoom
        sy = (self.y - camera.y) * camera.zoom

        hw = max(3, CAR_W * camera.zoom)
        hh = max(2, CAR_H * camera.zoom)

        cos_a = math.cos(self.angle)
        sin_a = math.sin(self.angle)

        def rot(lx, ly):
            return (
                sx + lx * cos_a - ly * sin_a,
                sy + lx * sin_a + ly * cos_a
            )

        corners = [
            rot(-hw, -hh),
            rot(hw, -hh),
            rot(hw, hh),
            rot(-hw, hh),
        ]

        pygame.draw.polygon(screen, self.color, corners)
        pygame.draw.polygon(screen, (20, 20, 20), corners, 1)

        if camera.zoom > 0.4:
            for side in (-hh * 0.6, hh * 0.6):
                hx, hy = rot(hw * 0.85, side)
                pygame.draw.circle(
                    screen,
                    (255, 255, 200),
                    (int(hx), int(hy)),
                    max(1, int(2 * camera.zoom))
                )