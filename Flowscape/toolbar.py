import pygame


TOOLS = ["select", "node", "road", "delete"]
TOOL_ICONS = {
    "select": "↖",
    "node":   "●",
    "road":   "━",
    "delete": "✕",
}
TOOL_KEYS = {
    pygame.K_s: "select",
    pygame.K_n: "node",
    pygame.K_r: "road",
    pygame.K_d: "delete",
}

NODE_TYPES_ORDER = ["junction", "endpoint", "city", "parking"]
NODE_TYPE_COLORS = {
    "junction": (120, 200, 120),
    "endpoint": (220, 80, 80),
    "city":     (80, 140, 220),
    "parking":  (220, 180, 60),
}


class Toolbar:
    PAD = 8
    BTN_W = 90
    BTN_H = 36
    SECTION_GAP = 14

    def __init__(self):
        self.active_tool = "select"
        self.active_node_type = "junction"
        self._font = None
        self._small_font = None
        self._buttons = []   # (rect, action_type, value)

    def _init_fonts(self):
        if self._font is None:
            self._font = pygame.font.SysFont("segoeui", 15, bold=True)
            self._small_font = pygame.font.SysFont("segoeui", 12)

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key in TOOL_KEYS:
                self.active_tool = TOOL_KEYS[event.key]
                return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            for rect, atype, val in self._buttons:
                if rect.collidepoint(mx, my):
                    if atype == "tool":
                        self.active_tool = val
                    elif atype == "nodetype":
                        self.active_node_type = val
                    return True
        return False

    def draw(self, screen):
        self._init_fonts()
        self._buttons.clear()

        x = self.PAD
        y = self.PAD

        # Background panel — measure total height first
        panel_w = self.BTN_W + self.PAD * 2
        total_h = (self.BTN_H + 4) * len(TOOLS) + self.SECTION_GAP + (self.BTN_H + 4) * len(NODE_TYPES_ORDER) + self.PAD * 2 + 28
        panel_rect = pygame.Rect(x, y, panel_w, total_h)
        panel_surf = pygame.Surface((panel_w, total_h), pygame.SRCALPHA)
        panel_surf.fill((20, 22, 28, 210))
        screen.blit(panel_surf, (x, y))
        pygame.draw.rect(screen, (60, 65, 80), panel_rect, 1, border_radius=6)

        x += self.PAD
        y += self.PAD

        # Section: Tools
        lbl = self._small_font.render("TOOLS  [S/N/R/D]", True, (130, 140, 160))
        screen.blit(lbl, (x, y))
        y += 18

        for tool in TOOLS:
            active = self.active_tool == tool
            btn_rect = pygame.Rect(x, y, self.BTN_W, self.BTN_H)
            bg = (50, 110, 200) if active else (38, 42, 55)
            pygame.draw.rect(screen, bg, btn_rect, border_radius=5)
            if active:
                pygame.draw.rect(screen, (100, 160, 255), btn_rect, 2, border_radius=5)
            icon = TOOL_ICONS[tool]
            text = self._font.render(f"{icon}  {tool.capitalize()}", True, (240, 240, 240))
            screen.blit(text, (btn_rect.x + 10, btn_rect.y + (self.BTN_H - text.get_height()) // 2))
            self._buttons.append((btn_rect, "tool", tool))
            y += self.BTN_H + 4

        y += self.SECTION_GAP

        # Section: Node types (only relevant when node tool active)
        alpha = 255 if self.active_tool == "node" else 100
        lbl = self._small_font.render("NODE TYPE", True, (130, 140, 160))
        lbl.set_alpha(alpha)
        screen.blit(lbl, (x, y))
        y += 18

        for nt in NODE_TYPES_ORDER:
            active = self.active_node_type == nt and self.active_tool == "node"
            btn_rect = pygame.Rect(x, y, self.BTN_W, self.BTN_H)
            dot_color = NODE_TYPE_COLORS[nt]
            bg = (38, 42, 55)
            pygame.draw.rect(screen, bg, btn_rect, border_radius=5)
            if active:
                pygame.draw.rect(screen, dot_color, btn_rect, 2, border_radius=5)
            pygame.draw.circle(screen, dot_color, (btn_rect.x + 14, btn_rect.y + self.BTN_H // 2), 6)
            text_surf = self._font.render(nt.capitalize(), True, (240, 240, 240) if alpha == 255 else (120, 120, 120))
            screen.blit(text_surf, (btn_rect.x + 26, btn_rect.y + (self.BTN_H - text_surf.get_height()) // 2))
            self._buttons.append((btn_rect, "nodetype", nt))
            y += self.BTN_H + 4
