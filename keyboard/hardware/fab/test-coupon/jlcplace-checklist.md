# JLC preview checklist: prettycool-keyboard-test-coupon.kicad\_pcb

CPL prettycool-keyboard-test-coupon-CPL-JLCPCB.csv, bottom reading `jlc-2022`, jlcplace 0.2.1; 1 item.

Open the order's placement preview at JLC and look at each part below. Tick it when the part sits on its pads with pin 1 / polarity where the board wants it. An item for several parts names the one to look at.

**Origin:** the Gerbers' (0, 0) is this CPL's origin, board (100, 100) (the aux (drill/place file) origin): the rows were checked from it, as JLC reads them

## Uncertain correction

- [ ] **D10** (C2286, top, rot 0): yellow db correction (manual): pin names pick rot 0 (2 agree, 0 differ), pad numbers pick rot 180; the EasyEDA footprint draws its + beside pad 1, and KiCad's positive pad is 2 (by KiCad's library convention (pad 1 = cathode)): following the pin names and the drawn +
