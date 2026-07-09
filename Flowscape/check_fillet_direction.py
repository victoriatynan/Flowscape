"""Diagnostic: junction corner-fillet geometry across the stress scenarios.

For every junction ring build_node_surfaces() assembles (inner asphalt AND
outer sidewalk/shoulder rings), re-derives each corner's fillet at high
sample count and checks:
  1. FACES IN: convex corners (< 180 deg) never bulge outward past their
     chord; reflex gaps are supposed to bow outward and are exempt.
  2. NO LOOP: no connector polyline self-intersects.
  3. RING-LEVEL: no two corner connectors cross each other.

Pure geometry -- no rendering (re-based from the pygame renderer per
WEB_MIGRATION_PLAN.md Phase 6; the ring capture now hooks
build_node_surfaces' junction_builder instead of monkey-patching the
renderer). Known pre-existing violations are reported, not asserted:
run and compare the final count.

Run:  python check_fillet_direction.py    (exit 1 if any violations)
"""

import math

from junction_scenarios import SCENARIOS, EXTRA
from road_geometry import (build_node_surfaces, _build_junction_polygon,
                           _fillet_points, _segment_intersection)


def _polyline_self_intersects(pts):
    """True if any two non-adjacent segments of the polyline cross."""
    segs = list(zip(pts, pts[1:]))
    for i in range(len(segs)):
        for j in range(i + 2, len(segs)):
            if i == 0 and j == len(segs) - 1 and pts[0] == pts[-1]:
                continue  # closed-polyline shared endpoint, not a loop
            hit = _segment_intersection(segs[i][0], segs[i][1],
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
        ang_a = math.atan2(a["outward"][1], a["outward"][0])
        ang_b = math.atan2(b["outward"][1], b["outward"][0])
        sector = (ang_b - ang_a) % (2 * math.pi)
        fillet = _fillet_points(a["left"], b["right"], node_pos, sector, samples=24)
        connector = [a["left"]] + fillet + [b["right"]]

        ax, ay = a["left"]
        bx, by = b["right"]
        cx, cy = bx - ax, by - ay
        clen = math.hypot(cx, cy)
        if clen < 1e-9:
            continue

        # 1. faces in: convex corners (sector < 180 deg) must not bulge past
        #    the chord on the far side. Reflex gaps (sector > 180 deg) are
        #    SUPPOSED to bow outward now, so they're exempt.
        node_side = cx * (node_pos[1] - ay) - cy * (node_pos[0] - ax)
        worst = 0.0
        for px, py in fillet:
            s = cx * (py - ay) - cy * (px - ax)
            dist = (s / clen) * (1.0 if node_side >= 0 else -1.0)
            worst = min(worst, dist)
        if sector < math.pi - 1e-3 and worst < -0.05:  # > 0.6 inch outward bulge, feet units
            violations.append(f"{label} corner {i}: convex fillet bulges OUTWARD by {-worst:.2f} ft "
                              f"(chord {clen:.1f} ft)")

        # 2. no loop: connector polyline must not self-intersect
        hit = _polyline_self_intersects(connector)
        if hit is not None:
            violations.append(f"{label} corner {i}: connector SELF-INTERSECTS near "
                              f"({hit[0]:.1f}, {hit[1]:.1f}) (chord {clen:.1f} ft)")

    # 3. ring-level: no two corner connectors may cross each other; either
    #    crossing reads as a loop/overlap in the drawn lane lines even when
    #    each curve alone is well-formed.
    connectors = []
    for i in range(n):
        a = ordered[i]
        b = ordered[(i + 1) % n]
        ang_a = math.atan2(a["outward"][1], a["outward"][0])
        ang_b = math.atan2(b["outward"][1], b["outward"][0])
        sector = (ang_b - ang_a) % (2 * math.pi)
        fillet = _fillet_points(a["left"], b["right"], node_pos, sector, samples=24)
        connectors.append([a["left"]] + fillet + [b["right"]])
    for i in range(n):
        for j in range(i + 1, n):
            pi, pj = connectors[i], connectors[j]
            for s in range(len(pi) - 1):
                for t in range(len(pj) - 1):
                    hit = _segment_intersection(pi[s], pi[s + 1], pj[t], pj[t + 1])
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


def main():
    total = 0
    all_violations = []
    for name, builder in list(SCENARIOS) + list(EXTRA):
        net = builder()

        # Capture every junction ring (inner asphalt + outer shoulder) the
        # assembly pass builds, with its exact node position.
        captured = []

        def capture(entries, node_pos, _captured=captured):
            _captured.append((entries, node_pos))
            return _build_junction_polygon(entries, node_pos)

        build_node_surfaces(net, junction_builder=capture)

        violations = []
        for entries, node_pos in captured:
            node = min(net.nodes.values(),
                       key=lambda nd: math.hypot(nd.x - node_pos[0],
                                                 nd.y - node_pos[1]))
            total += len(entries)
            check_entries(entries, node_pos, f"{name}/node{node.id}", violations)

        status = "FAIL" if violations else "ok"
        print(f"[{status}] {name}: {len(captured)} junction ring(s) checked")
        for v in violations:
            print(f"       {v}")
        all_violations.extend(violations)

    print(f"\n{total} corner fillets checked, {len(all_violations)} violation(s).")
    return 1 if all_violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
