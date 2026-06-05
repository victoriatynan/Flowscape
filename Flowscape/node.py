import pygame


NODE_TYPES = {
    "endpoint": {"color": (220, 80, 80),   "radius": 12, "label": "Endpoint"},
    "city":     {"color": (80, 140, 220),  "radius": 18, "label": "City"},
    "parking":  {"color": (220, 180, 60),  "radius": 14, "label": "Parking"},
    "junction": {"color": (120, 200, 120), "radius": 10, "label": "Junction"},
}


class Node:
    _id_counter = 0

    def __init__(self, x, y, node_type="junction"):
        Node._id_counter += 1
        self.id = Node._id_counter
        self.x = x
        self.y = y
        self.node_type = node_type
        self.selected = False

    @property
    def info(self):
        return NODE_TYPES.get(self.node_type, NODE_TYPES["junction"])

    def screen_pos(self, camera):
        sx = (self.x - camera.x) * camera.zoom
        sy = (self.y - camera.y) * camera.zoom
        return int(sx), int(sy)

    def draw(self, screen, camera):
        sx, sy = self.screen_pos(camera)
        info = self.info
        r = max(4, int(info["radius"] * camera.zoom))

        # Shadow
        pygame.draw.circle(screen, (0, 0, 0, 80), (sx + 2, sy + 2), r)

        # Fill
        color = (255, 255, 255) if self.selected else info["color"]
        pygame.draw.circle(screen, color, (sx, sy), r)

        # Border
        border_color = (255, 255, 100) if self.selected else (30, 30, 30)
        pygame.draw.circle(screen, border_color, (sx, sy), r, max(1, int(2 * camera.zoom)))

        # Label (only when zoomed in enough)
        if camera.zoom > 0.6:
            font = pygame.font.SysFont("segoeui", max(10, int(11 * camera.zoom)))
            label = font.render(info["label"], True, (240, 240, 240))
            screen.blit(label, (sx - label.get_width() // 2, sy + r + 2))

    def hit_test(self, sx, sy, camera):
        nx, ny = self.screen_pos(camera)
        r = max(8, int(self.info["radius"] * camera.zoom)) + 4
        return (sx - nx) ** 2 + (sy - ny) ** 2 <= r ** 2
