#!/usr/bin/env python3
"""Write skills/pacman.json: the Pac-Man eye trick in the D5 trick
format (tricks/FORMAT.md). This generator is the trick's source; edit here and re-run:

    python3 sources/make_pacman.py   (from the repository folder)

The arcade jingle is original (not Namco's tune); a real recording saved as
~/vector/sounds/pacman_intro.wav is used instead when present.
"""

import json
import math
from pathlib import Path

W, H = 184, 96
EYE, PAC, DOT = "eye", "pac", "dot"
GHOST, PUPIL = "ghost", "pupil"
PALETTE = {EYE: "#f0cd1e",   # his eye colour: "Uncanny Yellow" (vic.RobotSettings eye_color 2)
           PAC: "#ffe100", DOT: "#ffc8a0", GHOST: "#ff2a2a", PUPIL: "#2a50ff"}
EYE_RGB, PAC_RGB = (240, 205, 30), (255, 225, 0)
EYE_W, EYE_H, EYE_Y = 46, 58, 48
LEFT_X, RIGHT_X = 54, 130
PAC_R = 21
DOT_R = 3
DOT_XS = list(range(LEFT_X + 30, W + 4, 15))
STEP = 4.5   # pixels per frame while gliding


def rect(cx, cy, w, h, r, fill):
    return {"rect": [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], "radius": r, "fill": fill}


def dots(xs):
    return [{"circle": [x, EYE_Y, DOT_R], "fill": DOT} for x in xs]


def pacman(cx, mouth, facing="right"):
    m = max(0.5, mouth)
    if facing == "left":
        return {"pie": [cx, EYE_Y, PAC_R], "start": 180 + m, "end": 540 - m, "fill": PAC}
    return {"pie": [cx, EYE_Y, PAC_R], "start": m, "end": 360 - m, "fill": PAC}


def ghost(gx, look):
    """A ghost centred at gx: dome, body, three-point skirt, eyes looking left (-1) or right (+1)."""
    gy = EYE_Y
    skirt = [{"polygon": [[gx + a, gy + 14], [gx + a + 6, gy + 21], [gx + a + 12, gy + 14]], "fill": GHOST}
             for a in (-18, -6, 6)]
    return ([{"circle": [gx, gy - 4, 18], "fill": GHOST},
             {"rect": [gx - 18, gy - 4, gx + 18, gy + 15], "fill": GHOST}] + skirt +
            [{"ellipse": [gx - 12, gy - 12, gx - 3, gy - 1], "fill": "white"},
             {"ellipse": [gx + 3, gy - 12, gx + 12, gy - 1], "fill": "white"},
             {"circle": [gx - 7.5 + 2.5 * look, gy - 6, 2.5], "fill": PUPIL},
             {"circle": [gx + 7.5 + 2.5 * look, gy - 6, 2.5], "fill": PUPIL}])


def hexrgb(rgb):
    return "#%02x%02x%02x" % rgb


def morph_frames():
    """Left eye rounds into Pac-Man (and turns Pac-Man yellow); right eye squashes to a bar
    that spreads into the dot row; then his mouth opens."""
    out, steps = [], 10
    for i in range(1, steps + 1):
        k = i / steps
        colour = hexrgb(tuple(int(a + (b - a) * k) for a, b in zip(EYE_RGB, PAC_RGB)))
        frame = [rect(LEFT_X, EYE_Y, EYE_W + (2 * PAC_R - EYE_W) * k, EYE_H + (2 * PAC_R - EYE_H) * k,
                      12 + (PAC_R - 12) * k, colour)]
        if k < 0.6:
            frame.append(rect(RIGHT_X, EYE_Y, EYE_W, EYE_H * (1 - k / 0.6) + 4, 6, EYE))
        else:
            spread = (k - 0.6) / 0.4
            frame += dots([RIGHT_X + (x - RIGHT_X) * spread for x in DOT_XS])
        out.append(frame)
    for mouth in (12, 25, 38):
        out.append(dots(DOT_XS) + [pacman(LEFT_X, mouth)])
    return out


def eat(x, left, upto):
    """Steps eating the dots in `left` up to (not including) index upto of DOT_XS: per dot,
    glide frames with the mouth opening, then a bite frame (mouth shut, dot gone) held while a
    full "waka" plays. Returns (steps, x, dots left)."""
    steps = []
    for dot in DOT_XS[DOT_XS.index(left[0]):upto] if left else []:
        target = dot - PAC_R * 0.35   # where his mouth reaches the dot
        n = max(1, math.ceil((target - x) / STEP))
        glide = [dots(left) + [pacman(x + (target - x) * i / n, 40 * i / n)] for i in range(1, n + 1)]
        x = target
        left = [d for d in left if d != dot]
        steps.append({"frames": glide + [dots(left) + [pacman(x, 2)]], "hold_last": 1.5})
        steps.append({"sound": "waka", "volume": 80})
    return steps, x, left


def escape(x, left):
    """Ending 1: eat the rest and chomp on off the right edge."""
    steps, x, left = eat(x, left, len(DOT_XS))
    exit_frames, n = [], 0
    while x - PAC_R < W + 2:
        x += STEP * 1.5
        n += 1
        exit_frames.append([pacman(x, 40 * abs(math.sin(n * math.pi / 4)))])
    return steps + [{"frames": exit_frames + [[], []]}, {"sound": "vanish", "volume": 80}]


def ghost_chase(x, left, caught):
    """Endings 2 and 3: a ghost floats in from the right (siren), Pac-Man spins round and flees
    left. chased: the ghost keeps pace and both leave the screen. caught: the ghost is faster,
    catches him, he collapses ("wah-wah") and the ghost drifts off to the right."""
    stop = min(W - 14, x + 62)                  # peeks in at the edge, a good way behind him
    arrive = [dots(left) + [pacman(x, 2)] + ghost(W + 22 - (W + 22 - stop) * i / 6, -1) for i in range(1, 7)]
    gx, steps = stop, []
    steps += [{"frames": arrive, "hold_last": 1.2}, {"sound": "siren", "volume": 80}]
    flee, n = [dots(left) + ghost(gx, -1) + [pacman(x, 30, "left")]], 0   # spins round
    pac_v, ghost_v = (4.0, 8.0) if caught else (6.0, 6.0)
    while True:
        x -= pac_v
        gx -= ghost_v
        n += 1
        if caught and gx - x <= 14:
            break
        flee.append(dots(left) + ghost(gx, -1) + [pacman(x, 40 * abs(math.sin(n * math.pi / 4)), "left")])
        if not caught and gx + 22 < -2:
            break
    steps.append({"frames": flee + ([[]] * 2 if not caught else []),
                  "hold_last": 0.5})
    if not caught:
        return steps + [{"sound": "vanish", "volume": 80}]
    # caught: he folds up (mouth opening all the way), then the sad sound with the ghost alone
    fold = [dots(left) + ghost(gx, -1) + [pacman(x, 40 + 140 * i / 10, "left")] for i in range(1, 11)]
    fold.append(dots(left) + ghost(gx, -1))
    steps += [{"frames": fold, "hold_last": 3.0}, {"sound": "caught", "volume": 80}]
    leave, gx2 = [dots(left) + ghost(gx, 1)], gx      # looks the other way, drifts off right
    while gx2 - 22 < W + 2:
        gx2 += 5
        leave.append(dots(left) + ghost(gx2, 1))
    return steps + [{"frames": leave + [dots(left)], "hold_last": 0.8}]


def chomp_steps():
    """The shared start (eat three dots), then one of three endings picked at random."""
    steps, x, left = eat(float(LEFT_X), list(DOT_XS), 3)
    steps.append({"choose": [
        {"label": "escape", "weight": 2, "steps": escape(x, left)},
        {"label": "chased", "weight": 1, "steps": ghost_chase(x, left, caught=False)},
        {"label": "caught", "weight": 1, "steps": ghost_chase(x, left, caught=True)},
    ]})
    return steps


# Sounds: same synthesis as make_sounds.py's arcade_intro / waka / vanish (checked in main)
LEAD = [[0, 1], [7, 1], [4, 1], [12, 1], [7, 1], [4, 1], [None, 1], [4, 1],
        [2, 1], [9, 1], [5, 1], [14, 1], [9, 1], [5, 1], [None, 1], [5, 1],
        [4, .5], [5, .5], [7, .5], [9, .5], [11, .5], [12, .5], [14, .5], [16, .5],
        [19, 2], [24, 2]]
BASS = [[-24, 2], [-17, 2], [-22, 2], [-15, 2], [-20, 2], [-17, 2], [-15, 2], [-13, 2], [-24, 8]]
SOUNDS = {
    "intro": {"library": "pacman_intro", "else": {"melody": {
        "unit_seconds": 0.2, "root_hz": 523.25, "tail_seconds": 0.15, "voices": [
            {"wave": "square", "duty": 0.25, "level": 0.55, "attack": 0.004, "release": 0.03, "notes": LEAD},
            {"wave": "triangle", "level": 0.6, "attack": 0.004, "release": 0.03, "notes": BASS}]}}},
    "waka": {"sweeps": [
        {"wave": "square", "from_hz": 260, "to_hz": 700, "seconds": 0.16, "level": 0.7, "attack": 0.004, "release": 0.02},
        {"wave": "square", "from_hz": 700, "to_hz": 260, "seconds": 0.16, "level": 0.7, "attack": 0.004, "release": 0.02}]},
    "siren": {"sweeps": [   # the ghost appears: a quick warble (original)
        {"wave": "square", "from_hz": 480 + 40 * i, "to_hz": 880 + 40 * i, "seconds": 0.11, "level": 0.5,
         "attack": 0.004, "release": 0.01} if i % 2 == 0 else
        {"wave": "square", "from_hz": 880 + 40 * i, "to_hz": 480 + 40 * i, "seconds": 0.11, "level": 0.5,
         "attack": 0.004, "release": 0.01} for i in range(6)]},
    "caught": {"sweeps": [  # a falling "wah-wah-wah-waaah" (original)
        {"wave": "triangle", "from_hz": 620, "to_hz": 500, "seconds": 0.28, "level": 0.8, "release": 0.04},
        {"wave": "triangle", "from_hz": 520, "to_hz": 410, "seconds": 0.28, "level": 0.8, "release": 0.04},
        {"wave": "triangle", "from_hz": 430, "to_hz": 330, "seconds": 0.28, "level": 0.8, "release": 0.04},
        {"wave": "triangle", "from_hz": 350, "to_hz": 110, "curve_power": 2, "seconds": 0.8, "level": 0.8,
         "release": 0.2}]},
    "vanish": {"sweeps": [
        {"wave": "square", "from_hz": 1020, "to_hz": 120, "curve_power": 2, "seconds": 0.6, "level": 0.6,
         "attack": 0.005, "release": 0.08}]},
}


def trick():
    eyes = [rect(LEFT_X, EYE_Y, EYE_W, EYE_H, 12, EYE), rect(RIGHT_X, EYE_Y, EYE_W, EYE_H, 12, EYE)]
    return {
        "format": "d5-trick", "version": 1,
        "name": "pacman",
        "title": "Pac-Man",
        "description": "An arcade jingle, then one eye becomes Pac-Man and eats the other eye's dots, "
                       "waka by waka. Usually he chomps off the screen; sometimes a ghost chases him off, "
                       "and sometimes it catches him.",
        "author": "D5 skills",
        "palette": PALETTE,
        "sounds": SOUNDS,
        "frames": {"eyes": eyes},
        "steps": [{"show": {"ref": "eyes"}, "hold": 8},   # stays up through the jingle
                  {"sound": "intro", "volume": 80},
                  {"frames": morph_frames()}] + chomp_steps(),
    }


def _rounded(data):
    """Keep the JSON readable: coordinates to 3 decimals (well under a pixel)."""
    if isinstance(data, float):
        return round(data, 3)
    if isinstance(data, list):
        return [_rounded(x) for x in data]
    if isinstance(data, dict):
        return {k: _rounded(v) for k, v in data.items()}
    return data


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "skills" / "pacman.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(_rounded(trick()), separators=(",", ":")) + "\n")
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
