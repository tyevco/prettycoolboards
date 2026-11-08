# JLC preview checklist: prettycool-caliper-slider.kicad\_pcb

CPL prettycool-caliper-slider-CPL-JLCPCB.csv, bottom reading `jlc-2022`, jlcplace 0.2.1; 2 items.

Open the order's placement preview at JLC and look at each part below. Tick it when the part sits on its pads with pin 1 / polarity where the board wants it. An item for several parts names the one to look at.

**Origin:** the Gerbers' (0, 0) is this CPL's origin, board (100, 100) (the aux (drill/place file) origin): the rows were checked from it, as JLC reads them

## Uncertain correction

- [ ] **BZ50** (C910763, top, rot 0): yellow db correction (auto): polarity decided by pad numbers only (rot 180 also lands both pads, and no pin names or drawn + confirm it): check the polarity mark in JLC's preview

## Bottom reading

- [ ] **U30** (C22459687, bottom, rot 0): if JLC read the bottom rotation another way: as ccw-from-top+180 or jlc-2022+180, pin 1 would sit on pad 11 (20 pins move)
