# vector-skills

Skills (tricks) for an Anki Vector robot running on [wire-pod](https://github.com/kercre123/wire-pod):
face-screen animations, sounds, speech and small moves, each in one self-contained JSON file.

A skill is data only, with no code in it. The robot's software checks every value (motion limits,
sizes, length) before running anything, and runs the steps strictly one after another.

## What's here

| skill | what it does | endings |
|---|---|---|
| `pacman` | An arcade jingle, then one eye becomes Pac-Man and eats the other eye's dots, waka by waka. | escape, chased, caught |
| `peekaboo` | He hides behind his lift with his eyes shut, then drops it, pops his eyes wide open and says "Peekaboo!" | once, twice |

- `index.json`: the catalogue a robot reads to see what's available (name, title, length, endings, SHA-256)
- `skills/<name>.json`: the skills themselves
- `FORMAT.md`: the `d5-trick` format, version 1
- `engine/trick_engine.py`: checks, previews and performs skills (Python; Pillow, plus the Vector SDK to perform)
- `tools/`: `build_index.py` (rebuild the catalogue) and `check_skills.py` (what the pull-request check runs)
- `sources/`: generators for skills that are easier to write as code (`python3 sources/make_pacman.py`)

## Using these on your Vector

With Python 3, Pillow and the Vector SDK (`pip install pillow wirepod_vector_sdk`, set up for your
robot as the SDK describes):

```bash
python3 engine/trick_engine.py check skills/pacman.json --gif pacman.gif   # no robot needed
python3 engine/trick_engine.py play skills/pacman.json --serial <your robot's serial>
```

The engine came from one wire-pod setup with an MCP server ("D5"), which installs skills from this
repository by itself. Two things learned the hard way, for anyone building their own player:

- Never stream audio while sending face-screen frames: doing both at once jammed the robot's SDK
  service until it was restarted. Show a frame, then play the sound; the frame stays up meanwhile.
- Sounds under ~0.35 s can fail to play, and very long single clips (~30 s) can fail too: pad
  short sounds with silence and split long speech into sentences.

## Adding a skill

Contributions are welcome: see `CONTRIBUTING.md`. In short: write `skills/<name>.json`, check it with
`python3 engine/trick_engine.py check`, rebuild `index.json`, and open a pull request. An automatic
check validates it and attaches preview animations, and every skill is reviewed before it's merged.

## Notes

Pac-Man is a trademark of Bandai Namco Entertainment; `pacman` is an unofficial fan trick drawn from
simple shapes, and its jingle and sound effects are original, not the arcade's.

Licensed under the MIT License (see `LICENSE`).
