"""Post-fix layout verification (v3 — precise card-level).

Checks only what actually matters:
1. Each layer-module MDCard has height >= minimum_height (not squeezed).
2. Within each card, sibling BoxLayout rows do NOT overlap (row1 and row2 separated).
3. Within each row, sibling UnitInputs do NOT overlap.
4. All UnitInputs are touchable (>= 40dp wide, >= 36dp tall).

Uses local widget coordinates (row is container, UnitInputs are siblings) —
immune to ScrollView window-coordinate weirdness.

Exit 0 = pass, 1 = fail.
"""
import os
import sys

os.environ.setdefault("KIVY_NO_ARGS", "1")
os.environ.setdefault("KIVY_WINDOW", "sdl2")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kivy.metrics import dp
from kivy.base import EventLoop
from kivy.clock import Clock
from kivy.core.window import Window

import main as m

TOUCH_MIN_W = dp(40)
TOUCH_MIN_H = dp(36)


def overlaps(a, b):
    aw, ah = a.width, a.height
    bw, bh = b.width, b.height
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return False
    return not (a.x + aw <= b.x or b.x + bw <= a.x or
                a.y + ah <= b.y or b.y + bh <= a.y)


def check_width(width_dp):
    Window.size = (dp(width_dp), dp(800))
    root = m.KilnApp()
    Window.add_widget(root)
    for _ in range(10):
        Clock.tick()

    ins = root.input_screen
    sc = ins.children[0].children[1]
    # scroll to bottom so all cards are laid out
    sc.scroll_y = 0.0
    for _ in range(4):
        Clock.tick()

    layer_cards = []

    def walk(w):
        for c in getattr(w, "children", []):
            walk(c)
        if w.__class__.__name__ == "MDCard":
            # Identify as layer card: has children that are UnitInputs
            uis = []
            def deep(c2):
                for c3 in getattr(c2, "children", []):
                    deep(c3)
                    if c3.__class__.__name__ == "UnitInput":
                        uis.append(c3)
            deep(w)
            labels = set()
            for u in uis:
                for ch in getattr(u, "children", []):
                    if ch.__class__.__name__ == "MdLabel":
                        labels.add(ch.text)
            # A layer card has UnitInputs labeled a, b, c, Rc
            if labels >= {"a", "b", "c", "Rc"}:
                layer_cards.append(w)

    walk(ins)

    problems = []

    for ci, card in enumerate(layer_cards):
        # 1) height >= minimum_height
        if card.height < card.minimum_height:
            problems.append(f"[{width_dp}dp] layer-card[{ci}] squeezed: h={card.height:.0f} < min_h={card.minimum_height:.0f} (overflow={card.height - card.minimum_height:.0f})")

        # 2) sibling rows don't overlap
        rows = [c for c in card.children if c.__class__.__name__ == "BoxLayout"]
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                if overlaps(rows[i], rows[j]):
                    problems.append(f"[{width_dp}dp] layer-card[{ci}] rows overlap: row[{i}]@{rows[i].x:.0f},{rows[i].y:.0f} <-> row[{j}]@{rows[j].x:.0f},{rows[j].y:.0f}")

        # 3) within each row, sibling UnitInputs don't overlap
        for ri, row in enumerate(rows):
            uis = [c for c in row.children if c.__class__.__name__ == "UnitInput"]
            for ii in range(len(uis)):
                for jj in range(ii + 1, len(uis)):
                    if overlaps(uis[ii], uis[jj]):
                        labels_ii = [ch.text for ch in uis[ii].children if ch.__class__.__name__ == "MdLabel"]
                        labels_jj = [ch.text for ch in uis[jj].children if ch.__class__.__name__ == "MdLabel"]
                        problems.append(f"[{width_dp}dp] layer-card[{ci}] row[{ri}] UnitInputs overlap: {labels_ii} {uis[ii].x:.0f},{uis[ii].y:.0f} <-> {labels_jj} {uis[jj].x:.0f},{uis[jj].y:.0f}")

        # 4) UnitInput touchable
        unit_inputs = []
        def deep_uis(w2):
            for c in getattr(w2, "children", []):
                deep_uis(c)
                if c.__class__.__name__ == "UnitInput":
                    unit_inputs.append(c)
        deep_uis(card)
        for u in unit_inputs:
            if u.width < TOUCH_MIN_W or u.height < TOUCH_MIN_H:
                labels = [ch.text for ch in u.children if ch.__class__.__name__ == "MdLabel"]
                problems.append(f"[{width_dp}dp] layer-card[{ci}] UnitInput {labels} too small: {u.width:.0f}x{u.height:.0f}")

    Window.remove_widget(root)
    return problems


def main():
    total_fail = 0
    for w in (320, 360, 411):
        probs = check_width(w)
        if probs:
            total_fail += 1
            print(f"=== {w}dp FAIL ===")
            for p in probs:
                print("   ", p)
        else:
            print(f"=== {w}dp OK ===")
    print("RESULT:", "FAIL" if total_fail else "PASS — no overlap/touchability issues")
    return 1 if total_fail else 0


if __name__ == "__main__":
    sys.exit(main())