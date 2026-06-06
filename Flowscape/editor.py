import pygame
import sys
import math
import random

from camera import Camera
from node import Node
from road_segment import RoadSegment
from toolbar import Toolbar
from car import Car


GRID_SIZE = 40
CARS_PER_SPAWN = 1   # cars added per Space press


class Editor:
    BG_COLOR     = (28, 32, 38)
    GRID_COLOR   = (38, 43, 52)
    STATUS_COLOR = (160, 170, 190)

    def __init__(self, width=1280, height=800):
        pygame.init()
        self.width = width
        self.height = height
        self.screen = pygame.display.set_mode((width, height), pygame.RESIZABLE)
        pygame.display.set_caption("TrafficLab — Editor")
        self.clock = pygame.time.Clock()

        self.camera  = Camera(width, height)
        self.toolbar = Toolbar()

        self.nodes: list[Node]        = []
        self.roads: list[RoadSegment] = []
        self.cars:  list[Car]         = []

        # Simulation
        self.sim_running = False

        # Pan state
        self._panning  = False
        self._pan_last = (0, 0)

        # Road drawing state
        self._road_start_node: Node | None = None

        # Drag state
        self._dragging_ctrl = None
        self._dragging_node: Node | None = None
        self._drag_offset   = (0.0, 0.0)

        self.snap = True
        self._font = pygame.font.SysFont("segoeui", 13)

    # ------------------------------------------------------------------ #
    #  Main loop                                                           #
    # ------------------------------------------------------------------ #

    def run(self):
        while True:
            dt_ms = self.clock.tick(60)
            dt    = dt_ms / 1000.0
            self._handle_events()
            if self.sim_running:
                self._update_sim(dt)
            self._draw()

    # ------------------------------------------------------------------ #
    #  Simulation                                                          #
    # ------------------------------------------------------------------ #

    def _update_sim(self, dt):
        for road in self.roads:
            road._build_lut()

        for car in self.cars:
            car.update(dt, self.roads, self.cars)

        # --- Flow tracking ---
        # Gather cars per road, compute average speed ratio
        from collections import defaultdict
        road_cars = defaultdict(list)
        for car in self.cars:
            road_cars[id(car.road)].append(car)

        for road in self.roads:
            cars_here = road_cars.get(id(road), [])
            if not cars_here:
                # Decay toward None (no data) over time
                if road.flow is not None:
                    road.flow = road.flow * 0.97   # slow fade
                    if road.flow > 0.98:
                        road.flow = None
            else:
                avg_ratio = sum(c._current_speed / c.speed for c in cars_here) / len(cars_here)
                # Smooth update so colors don't flicker
                if road.flow is None:
                    road.flow = avg_ratio
                else:
                    road.flow = road.flow * 0.85 + avg_ratio * 0.15

    def _spawn_car(self):
        """Spawn a car on a random road."""
        if not self.roads:
            return
        road = random.choice(self.roads)
        direction = random.choice([1, -1])
        self.cars.append(Car(road, direction))

    def _clear_cars(self):
        self.cars.clear()
        for road in self.roads:
            road.flow = None

    # ------------------------------------------------------------------ #
    #  Events                                                              #
    # ------------------------------------------------------------------ #

    def _handle_events(self):
        mx, my = pygame.mouse.get_pos()

        for road in self.roads:
            road.ctrl.hovered = road.ctrl.hit_test(mx, my, self.camera)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()

            if event.type == pygame.VIDEORESIZE:
                self.width, self.height = event.w, event.h

            if self.toolbar.handle_event(event):
                if self.toolbar.active_tool != "road":
                    self._road_start_node = None
                continue

            if event.type == pygame.KEYDOWN:
                self._handle_key(event)
            elif event.type == pygame.MOUSEBUTTONDOWN:
                self._handle_mouse_down(event)
            elif event.type == pygame.MOUSEBUTTONUP:
                self._handle_mouse_up(event)
            elif event.type == pygame.MOUSEMOTION:
                self._handle_mouse_motion(event)
            elif event.type == pygame.MOUSEWHEEL:
                factor = 1.1 if event.y > 0 else 1 / 1.1
                self.camera.zoom_at(mx, my, factor)

    def _handle_key(self, event):
        if event.key == pygame.K_ESCAPE:
            self._road_start_node = None
            self.toolbar.active_tool = "select"

        elif event.key == pygame.K_g:
            self.snap = not self.snap

        elif event.key in (pygame.K_DELETE, pygame.K_BACKSPACE):
            self._delete_selected()

        elif event.key == pygame.K_SPACE:
            if self.roads:
                self.sim_running = not self.sim_running
                if self.sim_running and not self.cars:
                    for _ in range(3):
                        self._spawn_car()
                if not self.sim_running:
                    for road in self.roads:
                        road.flow = None

        elif event.key == pygame.K_c:
            # Spawn one more car
            self._spawn_car()

        elif event.key == pygame.K_x:
            # Clear all cars
            self._clear_cars()

    def _handle_mouse_down(self, event):
        mx, my = event.pos

        if event.button in (2, 3):
            self._panning  = True
            self._pan_last = (mx, my)
            return

        if event.button != 1:
            return

        tool = self.toolbar.active_tool
        wx, wy = self.camera.screen_to_world(mx, my)
        if self.snap:
            wx = round(wx / GRID_SIZE) * GRID_SIZE
            wy = round(wy / GRID_SIZE) * GRID_SIZE

        if tool == "select":
            for n in self.nodes:
                n.selected = False
            for r in self.roads:
                r.selected = False
                r.ctrl.selected = False

            ctrl_hit = self._ctrl_node_at(mx, my)
            if ctrl_hit:
                ctrl_hit.selected   = True
                self._dragging_ctrl = ctrl_hit
                raw_wx, raw_wy = self.camera.screen_to_world(mx, my)
                self._drag_offset = (ctrl_hit.x - raw_wx, ctrl_hit.y - raw_wy)
                return

            hit_node = self._node_at(mx, my)
            if hit_node:
                hit_node.selected   = True
                self._dragging_node = hit_node
                raw_wx, raw_wy = self.camera.screen_to_world(mx, my)
                self._drag_offset = (hit_node.x - raw_wx, hit_node.y - raw_wy)
                return

            hit_road = self._road_at(mx, my)
            if hit_road:
                hit_road.selected = True

        elif tool == "node":
            node = Node(wx, wy, self.toolbar.active_node_type)
            self.nodes.append(node)

        elif tool == "road":
            hit = self._node_at(mx, my)
            if hit is None:
                hit = Node(wx, wy, "junction")
                self.nodes.append(hit)
            if self._road_start_node is None:
                self._road_start_node = hit
            else:
                if self._road_start_node is not hit:
                    exists = any(
                        (r.node_a is self._road_start_node and r.node_b is hit) or
                        (r.node_b is self._road_start_node and r.node_a is hit)
                        for r in self.roads
                    )
                    if not exists:
                        self.roads.append(RoadSegment(self._road_start_node, hit))
                self._road_start_node = hit

        elif tool == "delete":
            ctrl_hit = self._ctrl_node_at(mx, my)
            if ctrl_hit:
                for r in self.roads:
                    if r.ctrl is ctrl_hit:
                        r._reset_ctrl()
                return
            hit_node = self._node_at(mx, my)
            if hit_node:
                self._remove_node(hit_node)
            else:
                hit_road = self._road_at(mx, my)
                if hit_road:
                    self.roads.remove(hit_road)
                    self.cars = [c for c in self.cars if c.road is not hit_road]

    def _handle_mouse_up(self, event):
        if event.button in (2, 3):
            self._panning = False
        if event.button == 1:
            self._dragging_ctrl = None
            self._dragging_node = None

    def _handle_mouse_motion(self, event):
        mx, my = event.pos

        if self._panning:
            dx = mx - self._pan_last[0]
            dy = my - self._pan_last[1]
            self.camera.pan(dx, dy)
            self._pan_last = (mx, my)
            return

        if self._dragging_ctrl is not None:
            raw_wx, raw_wy = self.camera.screen_to_world(mx, my)
            wx = raw_wx + self._drag_offset[0]
            wy = raw_wy + self._drag_offset[1]
            if self.snap:
                wx = round(wx / GRID_SIZE) * GRID_SIZE
                wy = round(wy / GRID_SIZE) * GRID_SIZE
            self._dragging_ctrl.x = wx
            self._dragging_ctrl.y = wy
            return

        if self._dragging_node is not None:
            raw_wx, raw_wy = self.camera.screen_to_world(mx, my)
            wx = raw_wx + self._drag_offset[0]
            wy = raw_wy + self._drag_offset[1]
            if self.snap:
                wx = round(wx / GRID_SIZE) * GRID_SIZE
                wy = round(wy / GRID_SIZE) * GRID_SIZE
            self._dragging_node.x = wx
            self._dragging_node.y = wy

    # ------------------------------------------------------------------ #
    #  Hit testing                                                         #
    # ------------------------------------------------------------------ #

    def _ctrl_node_at(self, sx, sy):
        for r in reversed(self.roads):
            if r.ctrl.hit_test(sx, sy, self.camera):
                return r.ctrl
        return None

    def _node_at(self, sx, sy) -> "Node | None":
        for n in reversed(self.nodes):
            if n.hit_test(sx, sy, self.camera):
                return n
        return None

    def _road_at(self, sx, sy) -> "RoadSegment | None":
        for r in reversed(self.roads):
            if r.hit_test(sx, sy, self.camera):
                return r
        return None

    # ------------------------------------------------------------------ #
    #  Deletion                                                            #
    # ------------------------------------------------------------------ #

    def _delete_selected(self):
        for n in [n for n in self.nodes if n.selected]:
            self._remove_node(n)
        removed = {r for r in self.roads if r.selected}
        self.roads = [r for r in self.roads if r not in removed]
        self.cars  = [c for c in self.cars  if c.road not in removed]

    def _remove_node(self, node):
        removed = {r for r in self.roads if r.node_a is node or r.node_b is node}
        self.roads = [r for r in self.roads if r not in removed]
        self.cars  = [c for c in self.cars  if c.road not in removed]
        self.nodes.remove(node)
        if self._road_start_node is node:
            self._road_start_node = None

    # ------------------------------------------------------------------ #
    #  Drawing                                                             #
    # ------------------------------------------------------------------ #

    def _draw(self):
        self.screen.fill(self.BG_COLOR)
        self._draw_grid()
        self._draw_roads()
        self._draw_road_preview()
        self._draw_cars()
        self._draw_nodes()
        self.toolbar.draw(self.screen)
        self._draw_sim_overlay()
        self._draw_status()
        pygame.display.flip()

    def _draw_grid(self):
        cam = self.camera
        x0, y0 = cam.screen_to_world(0, 0)
        x1, y1 = cam.screen_to_world(self.width, self.height)
        sx = math.floor(x0 / GRID_SIZE) * GRID_SIZE
        sy = math.floor(y0 / GRID_SIZE) * GRID_SIZE
        x = sx
        while x <= x1:
            px = int((x - cam.x) * cam.zoom)
            pygame.draw.line(self.screen, self.GRID_COLOR, (px, 0), (px, self.height))
            x += GRID_SIZE
        y = sy
        while y <= y1:
            py = int((y - cam.y) * cam.zoom)
            pygame.draw.line(self.screen, self.GRID_COLOR, (0, py), (self.width, py))
            y += GRID_SIZE

    def _draw_roads(self):
        for road in self.roads:
            road.draw(self.screen, self.camera)

    def _draw_road_preview(self):
        if self._road_start_node is None or self.toolbar.active_tool != "road":
            return
        mx, my = pygame.mouse.get_pos()
        sx, sy = self._road_start_node.screen_pos(self.camera)
        wx, wy = self.camera.screen_to_world(mx, my)
        if self.snap:
            wx = round(wx / GRID_SIZE) * GRID_SIZE
            wy = round(wy / GRID_SIZE) * GRID_SIZE
        ex = int((wx - self.camera.x) * self.camera.zoom)
        ey = int((wy - self.camera.y) * self.camera.zoom)
        pygame.draw.line(self.screen, (100, 180, 255), (sx, sy), (ex, ey),
                         max(2, int(8 * self.camera.zoom)))

    def _draw_cars(self):
        for car in self.cars:
            car.draw_haze(self.screen, self.camera)
            car.draw(self.screen, self.camera)

    def _draw_nodes(self):
        for node in self.nodes:
            node.draw(self.screen, self.camera)

    def _draw_sim_overlay(self):
        """Top-right sim status badge + flow legend."""
        if self.sim_running:
            label = f"▶  SIMULATING   {len(self.cars)} car{'s' if len(self.cars) != 1 else ''}   [SPACE] pause  [C] add car  [X] clear"
            color = (80, 220, 120)
        else:
            if self.roads:
                label = "[SPACE] start simulation"
            else:
                label = "Draw some roads first, then press [SPACE]"
            color = (160, 170, 190)

        font = pygame.font.SysFont("segoeui", 14, bold=self.sim_running)
        surf = font.render(label, True, color)
        pad  = 8
        bg   = pygame.Surface((surf.get_width() + pad * 2, surf.get_height() + pad * 2), pygame.SRCALPHA)
        bg.fill((20, 22, 28, 180))
        bx = self.width - bg.get_width() - 10
        by = 10
        self.screen.blit(bg, (bx, by))
        self.screen.blit(surf, (bx + pad, by + pad))

        # Flow legend (only while sim running or roads have flow data)
        has_flow = any(r.flow is not None for r in self.roads)
        if self.sim_running or has_flow:
            self._draw_flow_legend(by + bg.get_height() + 6, bx)

    def _draw_flow_legend(self, by, bx):
        from road_segment import _flow_color
        font   = pygame.font.SysFont("segoeui", 12)
        bar_w  = 120
        bar_h  = 10
        pad    = 8
        labels = [("Stop", 0), ("Slow", 0.5), ("Free", 1.0)]

        total_w = bar_w + pad * 2
        total_h = bar_h + 22 + pad * 2
        bg = pygame.Surface((total_w, total_h), pygame.SRCALPHA)
        bg.fill((20, 22, 28, 180))
        self.screen.blit(bg, (bx, by))

        # Gradient bar
        for i in range(bar_w):
            f = i / (bar_w - 1)
            c = _flow_color(f)
            pygame.draw.line(self.screen, c,
                             (bx + pad + i, by + pad + 12),
                             (bx + pad + i, by + pad + 12 + bar_h))

        # Label ticks
        for txt, f in labels:
            x = bx + pad + int(f * (bar_w - 1))
            pygame.draw.line(self.screen, (200, 200, 200),
                             (x, by + pad + 10), (x, by + pad + 12))
            s = font.render(txt, True, (190, 190, 190))
            self.screen.blit(s, (x - s.get_width() // 2, by + pad))

    def _draw_status(self):
        tool   = self.toolbar.active_tool
        snap_s = "SNAP ON [G]" if self.snap else "SNAP OFF [G]"
        zoom_s = f"Zoom {self.camera.zoom:.2f}x"
        hints  = {
            "select": "Click/drag nodes & curve handles  •  Del to delete selected",
            "node":   "Click to place node  •  Choose type in panel",
            "road":   "Click node to start  •  Click again to connect  •  ESC to cancel",
            "delete": "Click node or road to delete",
        }
        status = f"[{tool.upper()}]  {hints.get(tool, '')}    |    {snap_s}    |    {zoom_s}"
        surf = self._font.render(status, True, self.STATUS_COLOR)
        self.screen.blit(surf, (self.width - surf.get_width() - 12, self.height - surf.get_height() - 10))