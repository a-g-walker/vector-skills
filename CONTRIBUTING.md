# Contributing a skill

Thanks for making something for Vector! A skill is one JSON file in `skills/`. Robots that use
this repository can install it once it's merged.

## 1. Write it

- Read `FORMAT.md`. A skill is data only: frames made of shapes (or a small picture), sounds
  (synthesised notes or sweeps, or an embedded WAV), and steps that run in order.
- Name the file after the skill: `skills/<name>.json`, with the same `"name"` inside
  (lowercase letters, digits, `-` and `_`).
- Look at `skills/pacman.json` (and `sources/make_pacman.py`, which generates it) for a full
  example: animation, sounds, and random endings with `choose`.
- Long animations are easier to generate with a short script than to write by hand. If you do
  that, add the script to `sources/` too.

## 2. Check it

You need Python 3 and Pillow (`pip install pillow`):

```bash
python3 engine/trick_engine.py check skills/<name>.json --gif preview.gif
```

It checks everything (every ending too) and draws a preview animation of the face screen.
Add `--variant <label>` to preview a particular ending.

If you have a Vector with the SDK set up (`pip install wirepod_vector_sdk`), you can try it on
the robot:

```bash
python3 engine/trick_engine.py play skills/<name>.json --serial <your robot's serial>
```

Then rebuild the catalogue and run the same check GitHub runs:

```bash
python3 tools/build_index.py
python3 tools/check_skills.py
```

## 3. Send it

Fork this repository, add your `skills/<name>.json` (and the updated `index.json`), and open a
pull request. The **Check skills** action runs automatically. It validates every skill, makes
sure `index.json` is up to date, and attaches preview animations (under "Artifacts" on the
check's page) so the reviewer can see what your skill does.

## What gets merged

Every skill is reviewed before merging, because robots that use this repository install
whatever is here. A skill should be:

- **Family-friendly:** no rude words, pictures or jokes. Robots read titles and speak `say`
  steps out loud in people's homes.
- **Original:** your own drawings and sounds. No copyrighted music or recordings (a tune "in
  the style of" is fine). A fan tribute to a well-known character is fine if it says it's
  unofficial.
- **Gentle:** small moves only (the format caps driving at 20 cm and turns at one circle).
  Nothing that pushes the robot near table edges or keeps it busy for long.
- **Plain in its text:** titles and descriptions describe the skill. Text that tries to give
  instructions to the robot's assistant won't be merged.
- **Free of personal information:** no names, addresses or photos of people.

Changes to `engine/`, `tools/` or `.github/` are welcome too, but they're code that runs on
people's robots and in this repository's checks, so they get a much closer review. The check
flags them automatically.

By contributing you agree that your skill is shared under this repository's MIT License.
