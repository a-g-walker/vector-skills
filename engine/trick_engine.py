#!/usr/bin/env python3
"""d5-trick engine: check, render and perform Vector "skills" (tricks) written in the
d5-trick JSON format (see FORMAT.md). A skill is data only; nothing in it runs as code.
Everything is validated and capped before the robot moves, and steps run strictly one after
another: a sound never plays while face frames are being sent (doing both at once jammed the
robot's SDK service).

Needs Pillow; performing needs the Vector SDK (`anki_vector`, e.g. the
wirepod_vector_sdk package). Command line:

    python3 trick_engine.py check skill.json [--gif preview.gif] [--variant LABEL]
    python3 trick_engine.py play skill.json --serial 00XXXXXX [--variant LABEL]

As a library:

    import trick_engine as te
    te.configure(sounds_dir=..., cache_dir=..., font=...)   # optional
    plan = te.prepare(json.load(open("skill.json")))           # raises te.TrickError
    te.perform(robot, plan)                                    # robot has behavior control

Shared by D5 (a wire-pod Vector with an MCP server) and github.com/a-g-walker/vector-skills.
"""

import base64
import hashlib
import io
import json
import math
import os
import random
import re
import struct
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path

CONFIG = {
    "sounds_dir": None,  # folder of library WAVs for {"library": name} sounds (16 kHz mono 16-bit)
    "cache_dir": Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "d5-trick",
    "font": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # for text shapes
}


def configure(**settings):
    """Change sounds_dir, cache_dir or font (see CONFIG)."""
    unknown = set(settings) - set(CONFIG)
    if unknown:
        raise ValueError(f"unknown settings: {sorted(unknown)}")
    CONFIG.update(settings)


def _font(size):
    from PIL import ImageFont
    font = CONFIG["font"]
    if font and Path(font).exists():
        return ImageFont.truetype(str(font), size)
    return ImageFont.load_default(size=size)  # Pillow 10.1+


def plain(v, limit):
    """Short plain text for showing what a skill says about itself (it comes from whoever
    wrote the file, so keep it short and free of markup)."""
    return _plain(v, limit)


FORMAT, VERSION = "d5-trick", 1
W, H = 184, 96          # face screen
RATE = 16000            # the WAV format Vector's speaker stream takes: 16 kHz, 16-bit, mono
FPS_MAX = 17            # what set_screen_with_image_data manages back to back
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
LIMITS = {
    "file_bytes": 2_000_000, "steps": 400, "frames": 900, "shapes": 200, "repeat": 50,
    "seconds": 90, "sound_seconds": 20, "say_chars": 200, "hold": 30, "wait": 10,
    "drive_mm": 200, "speed_mmps": 150, "turn_deg": 360, "text_chars": 40, "wav_bytes": 1_000_000,
}
MOVES = ("turn", "drive", "animation")  # steps that need him off the charger


class TrickError(ValueError):
    """A trick file that isn't valid; the message says what and where."""


# --- validation helpers ---------------------------------------------------------------------

def _num(v, lo, hi, where):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise TrickError(f"{where}: expected a number, got {v!r}")
    if not lo <= v <= hi:
        raise TrickError(f"{where}: {v} is outside {lo}..{hi}")
    return v


def _text(v, limit, where):
    if not isinstance(v, str):
        raise TrickError(f"{where}: expected text")
    v = " ".join(v.split())
    if len(v) > limit:
        raise TrickError(f"{where}: longer than {limit} characters")
    return v


def _plain(v, limit):
    """Short plain text for summaries (titles/descriptions come from whoever wrote the file)."""
    v = "".join(ch for ch in str(v) if ch.isprintable() and ch not in "<>`{}[]\\")
    v = " ".join(v.split())
    return v[:limit] + ("…" if len(v) > limit else "")


def _color(v, palette, where):
    from PIL import ImageColor
    if isinstance(v, str) and v in palette:
        v = palette[v]
    try:
        return ImageColor.getrgb(v)[:3]
    except (ValueError, AttributeError, TypeError):
        raise TrickError(f"{where}: unknown colour {v!r}") from None


# --- frames ---------------------------------------------------------------------------------

SHAPES = ("rect", "circle", "ellipse", "pie", "polygon", "line", "text")
COORD = (-1000, 1000)


def _coords(v, n, where):
    if not isinstance(v, list) or len(v) != n:
        raise TrickError(f"{where}: expected {n} numbers")
    return [_num(c, *COORD, where) for c in v]


def _draw_shape(draw, s, palette, where):
    if not isinstance(s, dict):
        raise TrickError(f"{where}: a shape must be an object")
    kinds = [k for k in SHAPES if k in s]
    if len(kinds) != 1:
        raise TrickError(f"{where}: a shape needs exactly one of {', '.join(SHAPES)}")
    kind = kinds[0]
    fill = _color(s.get("fill", "white"), palette, f"{where}.fill")
    if kind == "rect":
        x0, y0, x1, y1 = _coords(s["rect"], 4, f"{where}.rect")
        r = _num(s.get("radius", 0), 0, 500, f"{where}.radius")
        r = max(0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
        if x1 > x0 and y1 > y0:
            draw.rounded_rectangle((x0, y0, x1, y1), radius=r, fill=fill)
    elif kind == "circle":
        cx, cy, r = _coords(s["circle"], 3, f"{where}.circle")
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill)
    elif kind == "ellipse":
        draw.ellipse(tuple(_coords(s["ellipse"], 4, f"{where}.ellipse")), fill=fill)
    elif kind == "pie":
        cx, cy, r = _coords(s["pie"], 3, f"{where}.pie")
        start = _num(s.get("start", 0), -720, 720, f"{where}.start")
        end = _num(s.get("end", 360), -720, 720, f"{where}.end")
        draw.pieslice((cx - r, cy - r, cx + r, cy + r), start, end, fill=fill)
    elif kind == "polygon":
        pts = s["polygon"]
        if not isinstance(pts, list) or not 3 <= len(pts) <= 64:
            raise TrickError(f"{where}.polygon: 3-64 points")
        draw.polygon([tuple(_coords(p, 2, f"{where}.polygon")) for p in pts], fill=fill)
    elif kind == "line":
        width = int(_num(s.get("width", 2), 1, 40, f"{where}.width"))
        draw.line(tuple(_coords(s["line"], 4, f"{where}.line")), fill=fill, width=width)
    elif kind == "text":
        from PIL import ImageFont
        txt = _text(s["text"], LIMITS["text_chars"], f"{where}.text")
        x, y = _coords(s.get("at", [W / 2, H / 2]), 2, f"{where}.at")
        size = int(_num(s.get("size", 24), 6, 90, f"{where}.size"))
        anchor = s.get("anchor", "mm")
        if anchor not in ("mm", "lm", "rm", "mt", "mb", "lt", "rt", "lb", "rb", "ms", "ls", "rs"):
            raise TrickError(f"{where}.anchor: unknown anchor {anchor!r}")
        draw.text((x, y), txt, font=_font(size), fill=fill, anchor=anchor)


def render_frame(frame, palette, named, where):
    """A frame (shape list, {"ref": name}, or {"image_base64": png}) -> 184x96 RGB image."""
    from PIL import Image, ImageDraw
    if isinstance(frame, dict) and "ref" in frame:
        ref = frame["ref"]
        if ref not in named:
            raise TrickError(f"{where}: no frame named {ref!r} in \"frames\"")
        frame = named[ref]
    if isinstance(frame, dict) and "image_base64" in frame:
        try:
            img = Image.open(io.BytesIO(base64.b64decode(frame["image_base64"], validate=True)))
            img.load()
        except Exception:
            raise TrickError(f"{where}: image_base64 isn't a readable image") from None
        if img.size != (W, H):
            raise TrickError(f"{where}: image must be {W}x{H}, got {img.size[0]}x{img.size[1]}")
        return img.convert("RGB")
    if not isinstance(frame, list):
        raise TrickError(f"{where}: a frame is a list of shapes, {{\"ref\": name}} or {{\"image_base64\": ...}}")
    if len(frame) > LIMITS["shapes"]:
        raise TrickError(f"{where}: more than {LIMITS['shapes']} shapes")
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    for i, s in enumerate(frame):
        _draw_shape(draw, s, palette, f"{where}[{i}]")
    return img


# --- sounds ---------------------------------------------------------------------------------

def _envelope(t, length, attack, release):
    if t < attack:
        return t / attack
    if t > length - release:
        return max(0.0, (length - t) / release)
    return 1.0


def _wave(kind, duty, where):
    if kind == "square":
        return lambda p: 1.0 if (p % 1.0) < duty else -1.0
    if kind == "triangle":
        return lambda p: 4 * abs((p % 1.0) - 0.5) - 1
    if kind == "sine":
        return lambda p: math.sin(2 * math.pi * p)
    raise TrickError(f"{where}: wave must be square, triangle or sine")


def _melody(spec, where):
    unit = _num(spec.get("unit_seconds", 0.2), 0.02, 2, f"{where}.unit_seconds")
    root = _num(spec.get("root_hz", 523.25), 40, 4000, f"{where}.root_hz")
    voices = spec.get("voices")
    if not isinstance(voices, list) or not 1 <= len(voices) <= 4:
        raise TrickError(f"{where}.voices: 1-4 voices")
    lengths = []
    for vi, v in enumerate(voices):
        notes = v.get("notes") if isinstance(v, dict) else None
        if not isinstance(notes, list) or not 1 <= len(notes) <= 400:
            raise TrickError(f"{where}.voices[{vi}].notes: 1-400 [semitones or null, length] pairs")
        lengths.append(sum(_num(n[1], 0.05, 64, f"{where}.voices[{vi}].notes") for n in notes
                           if isinstance(n, list) and len(n) == 2) * unit)
    total = max(lengths)
    if total > LIMITS["sound_seconds"]:
        raise TrickError(f"{where}: longer than {LIMITS['sound_seconds']} s")
    out = [0.0] * int(total * RATE + RATE * _num(spec.get("tail_seconds", 0.15), 0, 2, f"{where}.tail_seconds"))
    for vi, v in enumerate(voices):
        w = f"{where}.voices[{vi}]"
        voice = _wave(v.get("wave", "square"), _num(v.get("duty", 0.5), 0.05, 0.95, f"{w}.duty"), f"{w}.wave")
        level = _num(v.get("level", 0.5), 0, 1, f"{w}.level")
        attack = _num(v.get("attack", 0.004), 0.001, 1, f"{w}.attack")
        release = _num(v.get("release", 0.03), 0.001, 1, f"{w}.release")
        t0 = 0.0
        for ni, n in enumerate(v["notes"]):
            if not isinstance(n, list) or len(n) != 2:
                raise TrickError(f"{w}.notes[{ni}]: expected [semitones or null, length]")
            length = n[1] * unit
            if n[0] is not None:
                f = root * 2 ** (_num(n[0], -48, 48, f"{w}.notes[{ni}]") / 12)
                ph, start = 0.0, int(t0 * RATE)
                for i in range(int(length * RATE)):
                    ph += f / RATE
                    out[start + i] += level * voice(ph) * _envelope(i / RATE, length, attack, release)
            t0 += length
    return out


def _sweeps(spec, where):
    if not isinstance(spec, list) or not 1 <= len(spec) <= 64:
        raise TrickError(f"{where}: 1-64 sweep segments")
    out = []
    for si, s in enumerate(spec):
        w = f"{where}[{si}]"
        if not isinstance(s, dict):
            raise TrickError(f"{w}: a sweep segment must be an object")
        length = _num(s.get("seconds", 0.2), 0.01, 10, f"{w}.seconds")
        f0 = _num(s.get("from_hz", 440), 20, 8000, f"{w}.from_hz")
        f1 = _num(s.get("to_hz", f0), 20, 8000, f"{w}.to_hz")
        power = _num(s.get("curve_power", 1), 0.2, 5, f"{w}.curve_power")
        level = _num(s.get("level", 0.6), 0, 1, f"{w}.level")
        attack = _num(s.get("attack", 0.005), 0.001, 1, f"{w}.attack")
        release = _num(s.get("release", 0.02), 0.001, 1, f"{w}.release")
        voice = _wave(s.get("wave", "square"), _num(s.get("duty", 0.5), 0.05, 0.95, f"{w}.duty"), f"{w}.wave")
        ph = 0.0
        for i in range(int(length * RATE)):
            t = i / RATE
            f = f1 + (f0 - f1) * (1 - t / length) ** power  # power 1 = straight line from f0 to f1
            ph += f / RATE
            out.append(voice(ph) * level * _envelope(t, length, attack, release))
    if len(out) > LIMITS["sound_seconds"] * RATE:
        raise TrickError(f"{where}: longer than {LIMITS['sound_seconds']} s")
    return out


def _wav_bytes(samples):
    peak = max((abs(s) for s in samples), default=0) or 1
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(s / peak * 0.9 * 32767)) for s in samples))
    return buf.getvalue()


def _check_wav(data, where):
    try:
        with wave.open(io.BytesIO(data)) as w:
            ok = (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, RATE)
            seconds = w.getnframes() / RATE
    except Exception:
        raise TrickError(f"{where}: not a readable WAV") from None
    if not ok:
        raise TrickError(f"{where}: WAV must be 16 kHz, 16-bit, mono")
    if seconds > LIMITS["sound_seconds"]:
        raise TrickError(f"{where}: longer than {LIMITS['sound_seconds']} s")
    return seconds


def render_sound(spec, where):
    """A sound spec -> (path to a cached WAV, seconds). Library sounds are used in place."""
    if not isinstance(spec, dict):
        raise TrickError(f"{where}: a sound must be an object")
    if "library" in spec:
        name = spec["library"]
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise TrickError(f"{where}.library: a plain sound name like \"chime\"")
        path = Path(CONFIG["sounds_dir"]) / f"{name}.wav" if CONFIG["sounds_dir"] else None
        if path is not None and path.exists():
            return path, _check_wav(path.read_bytes(), f"{where}.library")
        if "else" not in spec:
            raise TrickError(f"{where}: no library sound {name!r} here and no \"else\"")
        return render_sound(spec["else"], f"{where}.else")
    if "wav_base64" in spec:
        try:
            data = base64.b64decode(spec["wav_base64"], validate=True)
        except Exception:
            raise TrickError(f"{where}.wav_base64: not valid base64") from None
        if len(data) > LIMITS["wav_bytes"]:
            raise TrickError(f"{where}.wav_base64: bigger than {LIMITS['wav_bytes']} bytes")
        seconds = _check_wav(data, f"{where}.wav_base64")
    elif "melody" in spec:
        data = _wav_bytes(_melody(spec["melody"], f"{where}.melody"))
        seconds = (len(data) - 44) / 2 / RATE
    elif "sweeps" in spec:
        data = _wav_bytes(_sweeps(spec["sweeps"], f"{where}.sweeps"))
        seconds = (len(data) - 44) / 2 / RATE
    else:
        raise TrickError(f"{where}: a sound needs one of library, wav_base64, melody, sweeps")
    cache = Path(CONFIG["cache_dir"])
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{hashlib.sha256(data).hexdigest()[:16]}.wav"
    if not path.exists():
        path.write_bytes(data)
    return path, seconds


# --- the trick as a whole -------------------------------------------------------------------

@dataclass
class Plan:
    """A validated, pre-rendered trick: ops to run in order, and how long it should take."""
    name: str
    title: str
    ops: list = field(default_factory=list)  # (kind, value, extra)
    seconds: float = 0.0
    needs_floor: bool = False  # has moves that need him off the charger
    chosen: list = field(default_factory=list)  # labels of the "choose" branches taken


def validate(data):
    """Check a parsed trick file; returns it (raises TrickError with what's wrong)."""
    prepare(data, render=False)
    return data


def prepare(data, render=True, prefer=""):
    """Validate and (if render) pre-render a trick into a Plan, before touching the robot.
    "choose" steps pick a branch at random by weight; prefer = a branch label to pick instead
    (when it matches one). With render=False every branch is checked."""
    if not isinstance(data, dict):
        raise TrickError("a trick file is a JSON object")
    if data.get("format") != FORMAT or data.get("version") != VERSION:
        raise TrickError(f'needs "format": "{FORMAT}" and "version": {VERSION}')
    name = data.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise TrickError('"name": lowercase letters, digits, - and _, up to 40 (it becomes the file name)')
    title = _text(data.get("title", name), 60, "title")
    _text(data.get("description", ""), 300, "description")
    _text(data.get("author", ""), 60, "author")
    palette = data.get("palette", {})
    if not isinstance(palette, dict) or len(palette) > 32:
        raise TrickError('"palette": an object of up to 32 colours')
    for k, v in palette.items():
        _color(v, {}, f"palette.{k}")
    named = data.get("frames", {})
    if not isinstance(named, dict) or len(named) > 64:
        raise TrickError('"frames": an object of up to 64 named frames')
    sounds = data.get("sounds", {})
    if not isinstance(sounds, dict) or len(sounds) > 32:
        raise TrickError('"sounds": an object of up to 32 named sounds')
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise TrickError('"steps": a non-empty list')

    plan = Plan(name=name, title=title)
    sound_cache = {}
    counts = {"steps": 0, "frames": 0}

    def frame_data(frame, where):
        counts["frames"] += 1
        if counts["frames"] > LIMITS["frames"]:
            raise TrickError(f"more than {LIMITS['frames']} frames in all")
        img = render_frame(frame, palette, named, where)
        if not render:
            return None
        from anki_vector.screen import convert_image_to_screen_data
        return convert_image_to_screen_data(img)

    def sound(key, where):
        if key not in sounds:
            raise TrickError(f"{where}: no sound named {key!r} in \"sounds\"")
        if key not in sound_cache:
            sound_cache[key] = render_sound(sounds[key], f"sounds.{key}")
        return sound_cache[key]

    def walk(steps, where, depth):
        for i, st in enumerate(steps):
            w = f"{where}[{i}]"
            counts["steps"] += 1
            if counts["steps"] > LIMITS["steps"]:
                raise TrickError(f"more than {LIMITS['steps']} steps in all (repeats count)")
            if not isinstance(st, dict) or not st:
                raise TrickError(f"{w}: a step must be an object")
            if "show" in st:
                hold = _num(st.get("hold", 0.5), 0.05, LIMITS["hold"], f"{w}.hold")
                plan.ops.append(("screen", frame_data(st["show"], f"{w}.show"), hold))
                plan.seconds += 1 / FPS_MAX
            elif "frames" in st:
                frames = st["frames"]
                if not isinstance(frames, list) or not frames:
                    raise TrickError(f"{w}.frames: a non-empty list of frames")
                fps = _num(st.get("fps", FPS_MAX), 1, FPS_MAX, f"{w}.fps")
                hold_last = _num(st.get("hold_last", 0.5), 0.05, LIMITS["hold"], f"{w}.hold_last")
                for fi, fr in enumerate(frames):
                    last = fi == len(frames) - 1
                    plan.ops.append(("screen", frame_data(fr, f"{w}.frames[{fi}]"), hold_last if last else 0.5))
                    if fps < FPS_MAX and not last:
                        plan.ops.append(("wait", 1 / fps - 1 / FPS_MAX, None))
                plan.seconds += len(frames) / fps
            elif "sound" in st:
                path, secs = sound(st["sound"], f"{w}.sound")
                vol = _num(st.get("volume", 80), 0, 100, f"{w}.volume")
                plan.ops.append(("sound", path, vol))
                plan.seconds += max(secs, 0.35) + 0.15
            elif "say" in st:
                txt = _text(st["say"], LIMITS["say_chars"], f"{w}.say")
                plan.ops.append(("say", txt, None))
                plan.seconds += 1 + len(txt) * 0.09
            elif "wait" in st and "head" not in st and "lift" not in st:  # a pause (on a move it means "don't wait")
                s = _num(st["wait"], 0, LIMITS["wait"], f"{w}.wait")
                plan.ops.append(("wait", s, None))
                plan.seconds += s
            elif "head" in st or "lift" in st:
                # "wait": false starts the move and goes straight on to the next step, so a move
                # can happen together with a frame or speech (e.g. lift up as the eyes close)
                kind = "head" if "head" in st else "lift"
                value = _num(st[kind], -22, 45, f"{w}.head") if kind == "head" else _num(st[kind], 0, 1, f"{w}.lift")
                wait = st.get("wait", True)
                if not isinstance(wait, bool):
                    raise TrickError(f"{w}.wait: true or false")
                plan.ops.append((kind, value, not wait))
                plan.seconds += 0.8 if wait else 0
            elif "turn" in st:
                plan.ops.append(("turn", _num(st["turn"], -LIMITS["turn_deg"], LIMITS["turn_deg"], f"{w}.turn"), None))
                plan.seconds += 1 + abs(st["turn"]) / 90
                plan.needs_floor = True
            elif "drive" in st:
                mm = _num(st["drive"], -LIMITS["drive_mm"], LIMITS["drive_mm"], f"{w}.drive")
                speed = _num(st.get("speed", 80), 10, LIMITS["speed_mmps"], f"{w}.speed")
                plan.ops.append(("drive", mm, speed))
                plan.seconds += 1 + abs(mm) / speed
                plan.needs_floor = True
            elif "animation" in st:
                plan.ops.append(("animation", _text(st["animation"], 80, f"{w}.animation"), None))
                plan.seconds += 4
                plan.needs_floor = True
            elif "eyes" in st:
                plan.ops.append(("eyes", _color(st["eyes"], palette, f"{w}.eyes"), None))
                plan.seconds += 0.2
            elif "choose" in st:
                options = st["choose"]
                if depth >= 2 or not isinstance(options, list) or not 2 <= len(options) <= 8:
                    raise TrickError(f"{w}.choose: 2-8 options (nested at most 2 deep)")
                for oi, o in enumerate(options):
                    if not isinstance(o, dict) or not isinstance(o.get("steps"), list) or not o["steps"]:
                        raise TrickError(f"{w}.choose[{oi}]: needs \"steps\"")
                    _num(o.get("weight", 1), 0.01, 1000, f"{w}.choose[{oi}].weight")
                    _text(o.get("label", ""), 40, f"{w}.choose[{oi}].label")
                if render:
                    labels = [o.get("label", "") for o in options]
                    if prefer and prefer in labels:
                        pick = labels.index(prefer)
                    else:
                        pick = random.choices(range(len(options)), [o.get("weight", 1) for o in options])[0]
                    plan.chosen.append(labels[pick] or f"option {pick + 1}")
                    walk(options[pick]["steps"], f"{w}.choose[{pick}].steps", depth + 1)
                else:  # check every branch; the trick is as long as its longest branch
                    n_ops, secs, longest = len(plan.ops), plan.seconds, 0.0
                    for oi, o in enumerate(options):
                        walk(o["steps"], f"{w}.choose[{oi}].steps", depth + 1)
                        longest = max(longest, plan.seconds - secs)
                        del plan.ops[n_ops:]
                        plan.seconds = secs
                    plan.seconds += longest
            elif "repeat" in st:
                n = int(_num(st["repeat"], 1, LIMITS["repeat"], f"{w}.repeat"))
                if depth >= 2 or not isinstance(st.get("steps"), list):
                    raise TrickError(f"{w}: repeat needs \"steps\" (nested at most 2 deep)")
                for _ in range(n):
                    walk(st["steps"], f"{w}.steps", depth + 1)
            else:
                raise TrickError(f"{w}: unknown step {sorted(st)}; see tricks/FORMAT.md")

    walk(steps, "steps", 0)
    if plan.seconds > LIMITS["seconds"]:
        raise TrickError(f"runs about {plan.seconds:.0f} s; the limit is {LIMITS['seconds']} s")
    return plan


def perform(robot, plan, play=None, speak=None):
    """Run a prepared plan on an anki_vector.Robot that has behavior control. Returns notes
    about anything skipped (a sound that failed to play doesn't stop the trick).
    play(robot, wav_path, volume) and speak(robot, text) default to play_wav and the robot's
    own text-to-speech; pass your own to use a different voice."""
    import anki_vector.util as vu
    import colorsys
    from anki_vector.connection import ControlPriorityLevel
    play_wav = play or globals()["play_wav"]
    speak = speak or (lambda r, text: r.behavior.say_text(text))
    notes = []
    regained = 0

    def state():
        s = robot.status
        flags = {"on charger": s.is_on_charger, "picked up": s.is_picked_up, "held": s.is_being_held,
                 "cliff": s.is_cliff_detected, "moving": s.is_robot_moving, "button": s.is_button_pressed}
        return ", ".join(k for k, v in flags.items() if v) or "nothing unusual"

    def run_op(kind, value, extra):
        """One op. Returns False if D5 took control back during it (the SDK then cancels the
        command: it returns None, or the sound stream raises CancelledError)."""
        import concurrent.futures
        if kind == "screen":
            return robot.screen.set_screen_with_image_data(value, extra) is not None
        if kind == "sound":
            try:
                play_wav(robot, value, extra)
            except concurrent.futures.CancelledError:
                return False
            except Exception as e:
                notes.append(f"a sound didn't play ({type(e).__name__})")
            return True
        if kind == "wait":
            time.sleep(value)
        elif kind == "say":
            try:
                speak(robot, value)  # his chosen voice
            except concurrent.futures.CancelledError:
                return False
        elif kind in ("head", "lift"):
            finish(kind)  # one move per motor at a time
            move = (lambda **kw: robot.behavior.set_head_angle(vu.degrees(value), **kw)) if kind == "head" else \
                (lambda **kw: robot.behavior.set_lift_height(value, **kw))
            if extra:  # "wait": false: start it and carry on
                moving[kind] = move(_return_future=True)
                return True
            return move() is not None
        elif kind == "turn":
            return robot.behavior.turn_in_place(vu.degrees(value)) is not None
        elif kind == "drive":
            return robot.behavior.drive_straight(vu.distance_mm(value), vu.speed_mmps(extra)) is not None
        elif kind == "animation":
            if value in robot.anim.anim_trigger_list:
                return robot.anim.play_animation_trigger(value) is not None
            return robot.anim.play_animation(value) is not None
        elif kind == "eyes":
            hue, sat, _ = colorsys.rgb_to_hsv(*(c / 255 for c in value))
            return robot.behavior.set_eye_color(hue, sat) is not None
        return True

    moving = {}  # motor -> future of a move started with "wait": false

    def finish(kind=None):
        for k in [kind] if kind else list(moving):
            fut = moving.pop(k, None)
            if fut is not None:
                try:
                    fut.result(timeout=5)
                except Exception:
                    pass

    for i, (kind, value, extra) in enumerate(plan.ops):
        # The robot's own higher-priority reactions can take control back mid-trick (seen once,
        # on the charger, nobody touching him; two sounds were cut off). The SDK's control flags
        # don't track that in this fork, so go by the cancelled command: note what he was doing,
        # take control back and redo that step.
        if run_op(kind, value, extra):
            continue
        if regained >= 2:
            raise RuntimeError(f"D5 kept taking control back ({state()})")
        notes.append(f"D5 took control back at step {i + 1} of {len(plan.ops)} ({kind}; then: {state()}); "
                     "took it back and carried on")
        robot.conn.request_control(behavior_control_level=ControlPriorityLevel.DEFAULT_PRIORITY, timeout=10)
        regained += 1
        run_op(kind, value, extra)
    finish()  # let any move still going complete before handing the robot back
    return notes


# --- playing sounds safely ----------------------------------------------------------------

MIN_WAV_SECONDS = 0.35


def play_wav(robot, path, volume=85):
    """Play a WAV through Vector's speaker (needs behavior control; blocks until done).
    Sounds shorter than MIN_WAV_SECONDS are padded with silence first: a 0.16 s one failed
    (audio_stream_playback_failed) or hung outright, while 0.32 s played fine."""
    import concurrent.futures
    import tempfile
    import wave
    with wave.open(str(path), "rb") as w:
        params, frames = w.getparams(), w.readframes(w.getnframes())
    vol = max(0, min(100, int(volume)))
    seconds = max(params.nframes, MIN_WAV_SECONDS * params.framerate) / params.framerate

    def stream(file):
        # A stream can also just hang (2026-10-07, right after a jam): cancel it after its own
        # length plus a few seconds rather than freezing the whole routine. The first stream
        # after taking control sometimes fails at once (audio_stream_playback_failed within
        # ~0.7 s; 2026-10-07 and 2026-10-10), and the same sound then plays fine: retry that once.
        from anki_vector.exceptions import VectorExternalAudioPlaybackException
        for attempt in (1, 2):
            started = time.monotonic()
            fut = robot.audio.stream_wav_file(file, volume=vol, _return_future=True)
            try:
                fut.result(timeout=seconds + 4)
                return
            except concurrent.futures.TimeoutError:
                fut.cancel()
                raise TimeoutError(f"sound {Path(path).name} didn't finish within {seconds + 4:.0f} s")
            except VectorExternalAudioPlaybackException:
                if attempt == 2 or time.monotonic() - started > 1.5:
                    raise
                time.sleep(0.3)

    short = int(MIN_WAV_SECONDS * params.framerate) - params.nframes
    if short <= 0:
        stream(str(path))
        return
    with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
        with wave.open(tmp.name, "wb") as w:
            w.setparams(params)
            w.writeframes(frames + b"\x00" * (short * params.sampwidth * params.nchannels))
        stream(tmp.name)


def variants(data):
    """Labels of the branches of a trick's "choose" steps (what perform_trick's variant picks)."""
    found = []

    def walk(steps):
        for st in steps:
            if isinstance(st, dict) and isinstance(st.get("choose"), list):
                for o in st["choose"]:
                    if o.get("label") and o["label"] not in found:
                        found.append(o["label"])
                    walk(o.get("steps", []))
            elif isinstance(st, dict) and isinstance(st.get("steps"), list):
                walk(st["steps"])

    walk(data.get("steps", []))
    return found


def preview_gif(data, path, prefer=""):
    """An animated GIF of a trick's face frames at 3x size (sounds shown as the frame held for
    the sound's length), to check a trick without the robot. "choose" steps follow the branch
    labelled prefer, or else the first."""
    from PIL import Image
    palette, named, sounds = data.get("palette", {}), data.get("frames", {}), data.get("sounds", {})
    seq, durations = [], []

    def add(frame, ms):
        seq.append(render_frame(frame, palette, named, "preview").resize((W * 3, H * 3), Image.NEAREST))
        durations.append(int(ms))

    def walk(steps):
        for st in steps:
            if "show" in st:
                add(st["show"], 1000 / FPS_MAX)
            elif "frames" in st:
                for fr in st["frames"]:
                    add(fr, 1000 / st.get("fps", FPS_MAX))
            elif "sound" in st and durations:
                durations[-1] += max(render_sound(sounds[st["sound"]], "preview")[1], 0.35) * 1000
            elif "wait" in st and durations:
                durations[-1] += st["wait"] * 1000
            elif "repeat" in st:
                for _ in range(st["repeat"]):
                    walk(st["steps"])
            elif "choose" in st:
                opts = st["choose"]
                walk(next((o for o in opts if prefer and o.get("label") == prefer), opts[0])["steps"])

    walk(data["steps"])
    seq[0].save(path, save_all=True, append_images=seq[1:], duration=durations, loop=0)
    return len(seq)


def describe(data):
    """One plain line about a valid skill: name, title, length, moves, endings, description."""
    plan = prepare(data, render=False)
    bits = [f"{plan.name}: {plain(plan.title, 60)}", f"~{plan.seconds:.0f} s"]
    if plan.needs_floor:
        bits.append("moves (off the charger)")
    if variants(data):
        bits.append("endings: " + ", ".join(plain(v, 30) for v in variants(data)))
    if data.get("description"):
        bits.append(plain(data["description"], 140))
    return " | ".join(bits)


def _main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="trick_engine.py", description="Check or play a d5-trick skill file.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="validate (and optionally preview) without a robot")
    c.add_argument("file")
    c.add_argument("--gif", help="write an animated preview of the face frames here")
    c.add_argument("--variant", default="", help="which ending to preview")
    p = sub.add_parser("play", help="perform it on a Vector (needs the anki_vector SDK)")
    p.add_argument("file")
    p.add_argument("--serial", required=True)
    p.add_argument("--variant", default="")
    args = ap.parse_args(argv)
    try:
        data = json.loads(Path(args.file).read_text())
        if args.cmd == "check":
            print("OK  " + describe(data))
            if args.gif:
                print(f"    preview: {preview_gif(data, args.gif, args.variant)} frames -> {args.gif}")
            return 0
        plan = prepare(data, prefer=args.variant)
        import anki_vector
        with anki_vector.Robot(args.serial) as robot:
            if plan.needs_floor and robot.status.is_on_charger:
                robot.behavior.drive_off_charger()
            notes = perform(robot, plan)
        print(f"performed {plan.name}" + (f" (ending: {', '.join(plan.chosen)})" if plan.chosen else "")
              + (f"; notes: {'; '.join(notes)}" if notes else ""))
        return 0
    except (TrickError, json.JSONDecodeError, OSError) as e:
        print(f"FAIL {args.file}: {e}")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(_main(sys.argv[1:]))
