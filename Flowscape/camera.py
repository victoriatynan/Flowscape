class Camera:
    ZOOM_MIN = 0.1
    ZOOM_MAX = 5.0

    def __init__(self, world_width, world_height):
        self.x = -world_width / 2   # world coords of top-left screen corner
        self.y = -world_height / 2
        self.zoom = 1.0

    def screen_to_world(self, sx, sy):
        wx = sx / self.zoom + self.x
        wy = sy / self.zoom + self.y
        return wx, wy

    def pan(self, dx_screen, dy_screen):
        self.x -= dx_screen / self.zoom
        self.y -= dy_screen / self.zoom

    def zoom_at(self, sx, sy, factor):
        """Zoom keeping screen point (sx, sy) fixed in world space."""
        wx, wy = self.screen_to_world(sx, sy)
        self.zoom = max(self.ZOOM_MIN, min(self.ZOOM_MAX, self.zoom * factor))
        # Recompute offset so the world point stays under cursor
        self.x = wx - sx / self.zoom
        self.y = wy - sy / self.zoom
