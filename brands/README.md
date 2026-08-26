# The logo submission — card 94

Home Assistant keeps every integration's icon and logo in **its own separate
project**, not in the integration. These four files are prepared and verified
against its published requirements, ready to submit.

| File | Size | Requirement |
|---|---|---|
| `intelleta/icon.png` | 256×256 | square, transparent |
| `intelleta/icon@2x.png` | 512×512 | square, transparent |
| `intelleta/logo.png` | 256×170 | longest side 256 |
| `intelleta/logo@2x.png` | 512×341 | longest side 512 |

Generated from `Technology-Spirits/brand` → `v33-master`, the single source of
truth. ⛔ Any Intelleta mark found anywhere else is out of date — two copies of
a logo is how the wrong one shipped once already.

## What was done to them, and what was not

⛔ **Padding is not adapting.** Our mark is 256×304 — taller than it is wide —
and Home Assistant requires a square icon. So the mark sits centred on a
transparent square with a small margin, at its own proportions, with its own
pixels untouched. Nothing was recoloured, cropped or redrawn.

## ⛔ One question that is not ours to answer

**Home Assistant shows one icon on both light and dark backgrounds.** The brand
has two greys for exactly this reason — charcoal `#333338` for light grounds and
light grey `#D3D1D8` for dark — and the identity spec goes further, naming a
band of mid-greys where *neither* clears contrast and the ground must take a
plate instead.

There is no theme variant in Home Assistant's brands project. One file serves
both. So one of these is true and somebody has to decide which:

1. The charcoal mark is acceptable on Home Assistant's dark surface as well as
   its light one.
2. It is not, and the icon needs a treatment the identity spec does not yet
   describe.

The assets above use the mark as it exists. **That is a placeholder for the
answer, not the answer** — this is Raye's and Thomas's call, per the rule that
if Home Assistant's requirements cannot be met by the existing mark, it is a
question for them rather than a licence to adapt it.

## ⚠ And it cannot be submitted yet

Home Assistant's brands project expects an integration that exists publicly.
This repository is private until launch (owner ruling 2026-08-25), so the
submission waits for that step — which is on card 96's checklist.

**The point of preparing them now is the calendar, not the work.** The
submission is reviewed by Home Assistant's own maintainers on their timetable,
so it is the one item in stage one whose finish date is not ours to decide. With
the assets ready, going public and submitting are the same afternoon rather than
two.
