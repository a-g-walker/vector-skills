# vector-skills

Skills (tricks) for an Anki Vector robot running on [wire-pod](https://github.com/kercre123/wire-pod):
face-screen animations, sounds, speech and small moves, each in one self-contained JSON file.

A skill is data only, with no code in it. The robot's software checks every value (motion limits,
sizes, length) before running anything, and runs the steps strictly one after another.

## What's here

| skill | what it does | endings |
|---|---|---|
| `pacman` | An arcade jingle, then one eye becomes Pac-Man and eats the other eye's dots, waka by waka. | escape, chased, caught |

- `index.json`: the catalogue a robot reads to see what's available (name, title, length, endings, SHA-256)
- `skills/<name>.json`: the skills themselves
- `FORMAT.md`: the `d5-trick` format, version 1
- `sources/`: generators for skills that are easier to write as code (`python3 sources/make_pacman.py`)

## Using these on your Vector

These were made for one wire-pod setup with a small MCP server ("D5"); its trick engine reads this
format. To use a skill elsewhere you need something that plays it: render the frames to the
184x96 face screen, synthesise the sounds, and run the steps in order (see `FORMAT.md`).
Two things learned the hard way, for anyone building a player:

- Never stream audio while sending face-screen frames: doing both at once jammed the robot's SDK
  service until it was restarted. Show a frame, then play the sound; the frame stays up meanwhile.
- Sounds under ~0.35 s can fail to play, and very long single clips (~30 s) can fail too: pad
  short sounds with silence and split long speech into sentences.

## Adding a skill

1. Write `skills/<name>.json` following `FORMAT.md` (the `name` field must match the file name).
2. Check it on the robot's Pi, then regenerate `index.json`.
3. Commit. Robots pick it up next time they browse.

## Notes

Pac-Man is a trademark of Bandai Namco Entertainment; `pacman` is an unofficial fan trick drawn from
simple shapes, and its jingle and sound effects are original, not the arcade's.

Licensed under the MIT License (see `LICENSE`).
