import math
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

import road_editor
from test_intersections_visual import SCENARIOS, render_scenario, _spoke_network
from road_editor import CANVAS_WIDTH, CANVAS_HEIGHT


def _polyline_self_intersects(pts):
    """True if any two non-adjacent segments of the polyline cross."""
    segs = list(zip(pts, pts[1:]))
    for i in range(len(segs)):
        for j in range(i + 2, len(segs)):
            if i == 0 and j == len(segs) - 1 and pts[0] == pts[-1]:
                continue  # closed-polyline shared endpoint, not a loop
            hit = road_editor._segment_intersection(segs[i][0], segs[i][1],
                                                     segs[j][0], segs[j][1])
            if hit is not None:
                return hit
    return None


def check_entries(entries, node_pos, label, violations):
    ordered = sorted(entries, key=lambda e: math.atan2(e["outward"][1], e["outward"][0]))
    n = len(ordered)
    for i in range(n):
        a = ordered[i]
        b = ordered[(i + 1) % n]
        fillet = road_editor._fillet_points(a["left"], a["outward"], b["right"], b["outward"],
                                             node_pos, samples=24)
        connector = [a["left"]] + fillet + [b["right"]]

        ax, ay = a["left"]
        bx, by = b["right"]
        cx, cy = bx - ax, by - ay
        clen = math.hypot(cx, cy)
        if clen < 1e-9:
            continue

        # 1. faces in: no sampled point on the far side of the chord
        node_side = cx * (node_pos[1] - ay) - cy * (node_pos[0] - ax)
        worst = 0.0
        for px, py in fillet:
            s = cx * (py - ay) - cy * (px - ax)
            dist = (s / clen) * (1.0 if node_side >= 0 else -1.0)
            worst = min(worst, dist)
        if worst < -0.05:  # > 0.6 inch outward bulge, feet units
            violations.append(f"{label} corner {i}: fillet bulges OUTWARD by {-worst:.2f} ft "
                              f"(chord {clen:.1f} ft)")

        # 2. no loop: connector polyline must not self-intersect
        hit = _polyline_self_intersects(connector)
        if hit is not None:
            violations.append(f"{label} corner {i}: connector SELF-INTERSECTS near "
                              f"({hit[0]:.1f}, {hit[1]:.1f}) (chord {clen:.1f} ft)")

    # 3. ring-level: no two corner connectors may cross each other, and no
    #    connector may cross another road's own near-end chord
    #    [right -> left] -- either crossing reads as a loop/overlap in the
    #    drawn lane lines even when each curve alone is well-formed.
    connectors = []
    for i in range(n):
        a = ordered[i]
        b = ordered[(i + 1) % n]
        fillet = road_editor._fillet_points(a["left"], a["outward"], b["right"], b["outward"],
                                             node_pos, samples=24)
        connectors.append([a["left"]] + fillet + [b["right"]])
    for i in range(n):
        for j in range(i + 1, n):
            pi, pj = connectors[i], connectors[j]
            for s in range(len(pi) - 1):
                for t in range(len(pj) - 1):
                    # consecutive connectors share no endpoints, but skip
                    # near-touching first/last segments at shared roads
                    hit = road_editor._segment_intersection(pi[s], pi[s + 1], pj[t], pj[t + 1])
                    if hit is None:
                        continue
                    # ignore contact at the connectors' own endpoints
                    if any(math.hypot(hit[0] - q[0], hit[1] - q[1]) < 1e-6
                           for q in (pi[0], pi[-1], pj[0], pj[-1])):
                        continue
                    violations.append(f"{label}: connectors {i} and {j} CROSS near "
                                      f"({hit[0]:.1f}, {hit[1]:.1f})")
                    break
                else:
                    continue
                break


# Extra stress scenarios beyond the visual-test suite: very acute wedges,
# acute pairs combined with asymmetric profiles, near-parallel double pairs.
EXTRA = [
    ("acute_20", lambda: _spoke_network([0, 20, 180], length=300.0)),
    ("acute_15", lambda: _spoke_network([0, 15, 180], length=340.0)),
    ("acute_10", lambda: _spoke_network([0, 10, 180], length=400.0)),
    ("acute_double_x", lambda: _spoke_network([0, 15, 180, 195], length=340.0)),
    ("acute_15_mixed", lambda: _spoke_network([0, 15, 180], length=340.0,
                                               presets=["highway", "residential", "expressway"])),
    ("acute_4way_mixed", lambda: _spoke_network([0, 25, 120, 250], length=300.0,
                                                 presets=["expressway", "residential",
                                                          "urban", "highway"])),
    ("acute_5way_fan", lambda: _spoke_network([0, 18, 36, 54, 200], length=380.0)),
    ("reflex_fan_340", lambda: _spoke_network([0, 10, 20], length=420.0)),
    ("acute_curved", lambda: _spoke_network([0, 25, 180], length=300.0,
                                             curve_offsets=[(0, 60), (0, -60), (0, 0)])),
    ("acute_curved_in", lambda: _spoke_network([0, 25, 180], length=300.0,
                                                curve_offsets=[(0, -50), (0, 50), (0, 0)])),
]


def main():
    pygame.init()
    pygame.display.set_mode((CANVAS_WIDTH, CANVAS_HEIGHT))
    font = pygame.font.SysFont("monospace", 13)
    surface = pygame.Surface((CANVAS_WIDTH, CANVAS_HEIGHT))

    total = 0
    all_violations = []
    for name, builder in list(SCENARIOS) + EXTRA:
        net = builder()

        captured = []
        orig = road_editor._build_junction_polygon

        def capture(entries, node_pos, _captured=captured):
            _captured.append(entries)
            return orig(entries, node_pos)

        road_editor._build_junction_polygon = capture
        try:
            render_scenario(name, net, surface, font)
        finally:
            road_editor._build_junction_polygon = orig

        violations = []
        for entries in captured:
            pts = [e["left"] for e in entries] + [e["right"] for e in entries]
            gx = sum(p[0] for p in pts) / len(pts)
            gy = sum(p[1] for p in pts) / len(pts)
            node = min(net.nodes.values(), key=lambda nd: math.hypot(nd.x - gx, nd.y - gy))
            total += len(entries)
            check_entries(entries, (node.x, node.y), f"{name}/node{node.id}", violations)

        status = "FAIL" if violations else "ok"
        print(f"[{status}] {name}: {len(captured)} junction ring(s) checked")
        for v in violations:
            print(f"       {v}")
        all_violations.extend(violations)

    pygame.quit()
    print(f"\n{total} corner fillets checked, {len(all_violations)} violation(s).")
    return 1 if all_violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
