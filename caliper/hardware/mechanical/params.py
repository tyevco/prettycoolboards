#!/usr/bin/env python3
"""Every mechanical dimension of the PrettyCool Caliper rev A, in one place.

Sources: caliper/hardware/design/SPEC.md (sections 2.1 and 7) and the datasheets
quoted next to each number.  Anything tagged ``DEV`` deviates from SPEC and is
explained in docs/mechanical.md section 3; anything tagged ``TVP`` is an
assumption to verify on the prototype.

Coordinate frame (assembly, millimetres)
----------------------------------------
* **x** runs along the beam (the measuring axis).  x = 0 is the fixed jaw's
  outside measuring face; the slider moves toward +x.  At reading R the moving
  jaw's outside measuring face is at x = R.
* **y** runs across the beam.  y = 0 is the beam's lower (jaw-side) edge, which is
  the reference edge; y = 20 is its upper edge.  This is the slider board's y
  (SPEC 2.1: "beam lower edge = board y 0").  The outside jaws hang toward -y.
* **z** runs through the thickness.  z = 0 is the beam's front face (the display
  side); the back face is at z = -4.

The slider housing is built in its own frame u = x - R (u = 0 is the moving
jaw's measuring face), so every slider number below is a u.
"""
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# General print / fit rules (Bambu P2S, 0.4 mm nozzle)
# ---------------------------------------------------------------------------
NOZZLE = 0.4
LAYER = 0.20
WALL_MIN = 1.2            # >= 3 perimeters
CLR_SLIDE = 0.15          # printed sliding fit, per side (0.15-0.20 rule)
CLR_LOOSE = 0.20
INSERT_M2_D = 3.2         # hole for an M2 x 3 heat-set insert (OD 3.6 knurl, CNC Kitchen style)
INSERT_M2_L = 3.0
INSERT_M3_D = 4.0         # M3 x 4 insert hole
INSERT_M3_L = 4.0
M2_CLR = 2.2
M2_TAP = 1.6              # rev B: tap drill for M2 x 0.4
M3_CLR = 3.4
M3_TAP = 2.5

# ---------------------------------------------------------------------------
# Beam (SPEC 7): ground flat stock 20 x 4 x 250, O1 tool steel or 1.4301
# ---------------------------------------------------------------------------
BEAM_W = 20.0             # y
BEAM_T = 4.0              # z
BEAM_L = 250.0            # x
BEAM_X0 = -16.0           # left end sits 16 mm inside the fixed jaw block
BEAM_X1 = BEAM_X0 + BEAM_L
RANGE = 150.0
OVERTRAVEL = 1.0

# Magnetic tape (AS5311, 2.0 mm pole pair = 1.0 mm pole length).
# DEV-1: SPEC says 10 mm wide centred at y = 6, but that band (y 1..11) overlaps
#        the scale-PCB band (y 10.5..17.5) by 0.5 mm.  The model slits the tape to
#        8.0 mm, keeping the centre at y = 6.0 (so the AS5311 position is unchanged).
# DEV-2: SPEC says both bands end flush with the beam face.  They cannot both be
#        flush: the AS5311 sits on the same flat board bottom as the capacitive
#        electrodes, so the tape surface must be lower than the scale surface by
#        (IC height + 0.30 magnetic gap - 0.15 capacitive gap).  The tape therefore
#        lies in a channel (TAPE_CH_DEPTH, below) and the AS5311 runs inside it.
TAPE_W = 8.0
TAPE_YC = 6.0
TAPE_T = 0.60             # TVP: magnet + backing; SPEC's 0.6 pocket implies ~0.5 + adhesive.
TAPE_T_TOL = 0.05         # TVP: per-roll tolerance of a calendered bonded-ferrite strip.
                          #      Dexter quotes +/-0.15 on its strips; then the gap must be set per unit.
TAPE_ADH = 0.05           # 3M 467MP transfer tape, 0.05 mm
TAPE_ADH_TOL = 0.01
TAPE_X0, TAPE_X1 = 28.0, 200.0   # covers the AS5311 (u 39) over 0..150 with margin
TAPE_CH_W = TAPE_W + 0.2  # channel width (y 1.9 .. 10.1)

# AS5311 TSSOP-20 (JEDEC MO-153 AC): A max 1.20, A1 0.05-0.15, A2 0.80-1.05.
AS_BODY_X = 6.5           # along the beam (long axis along X, SPEC 2.1)
AS_BODY_Y = 4.4
AS_LEAD_Y = 6.4           # tip to tip
AS_H_NOM = 1.10           # seated height, A1 0.10 + A2 1.00
AS_H_MIN = 0.85
AS_H_MAX = 1.20
SOLDER_STANDOFF_TOL = 0.03
AS_X, AS_Y = 31.0, 6.0    # board coordinates (SPEC 2.1), on the board bottom

MAG_GAP = 0.30            # SPEC 4.1: 0.3 +/- 0.1, IC top surface to tape
MAG_GAP_TOL = 0.10
CAP_GAP = 0.15            # SPEC 7: electrode face to scale face

# Scale PCB (SPEC 2.2): 200 x 7 x 0.8, in a pocket at y 10.5 .. 17.5
SCALE_L, SCALE_W, SCALE_T = 200.0, 7.0, 0.80
SCALE_T_TOL = 0.08        # FR4 +/-10 %, JLC standard (TVP: order with +/-0.05 "tight" option)
SCALE_ADH = 0.05          # 467MP
SCALE_Y0 = 10.5
SCALE_X0 = 14.0           # electrodes at u 19..59 sweep x 19..209
SCALE_POCKET_W = SCALE_W + 0.10           # y 10.45 .. 17.55
SCALE_POCKET_DEPTH = SCALE_T + SCALE_ADH  # 0.85: PCB face flush with the beam face (nominal)

# Fixed-jaw joint in the beam: 2 x M3 bolts + 2 x 3 mm dowels (h6 pins, H7 reamed holes)
FJ_BOLTS = [(-12.0, 5.0), (-12.0, 15.0)]
FJ_DOWELS = [(-5.0, 4.0), (-5.0, 16.0)]
DOWEL_D = 3.0
# End stop: a 2 mm dowel pressed through the beam, 1.5 mm proud of the front face,
# on the upper land (y 17.55..20).  The slider's right tower hits it.
STOP_D = 2.0
STOP_Y = 18.8
STOP_PROUD = 1.5

# ---------------------------------------------------------------------------
# Slider board (SPEC 2.1): 62 x 34 x 1.0, origin lower-left, y = beam y
# ---------------------------------------------------------------------------
BOARD_L, BOARD_W, BOARD_T = 62.0, 34.0, 1.0
BOARD_U0 = 8.0            # board x = 0 sits at slider u = 8
BOARD_Z0 = CAP_GAP        # board bottom = 0.15 above the beam / scale face
BOARD_Z1 = BOARD_Z0 + BOARD_T
# DEV-3: SPEC's holes at (3, 3) and (59, 3) lie over the beam, where there are 0.15 mm
# under the board -- no room for a boss, nut or screw head.  All four move into the
# band clear of the beam (y > 20), where bosses rise from the slider body.
BOARD_HOLES = [(3.0, 24.5), (3.0, 31.0), (59.0, 32.6)]   # 3 holes: USB-C, MINI-1 and the battery leave no 4th spot (TVP)
BOARD_HOLE_D = 2.2

# Top-side components (heights are datasheet maxima incl. solder).  Positions not
# fixed by SPEC are assumptions for the clash check (TVP: replaced by
# extract_board_parts.py once the layout exists).
MINI1 = dict(x0=39.2, x1=54.6, y0=13.5, y1=34.0, h=2.55)     # 15.4 x 20.5 x 2.4 (+0.15)
USBC = dict(x0=55.65, x1=63.0, y0=22.03, y1=30.97, h=3.26)    # top-mount 16p, 1 mm overhang
USBC_YC = 26.5            # DEV-4: SPEC "y ~ 26"; 26.5 keeps the plug overmold off the beam edge
USBC_ZC = BOARD_Z1 + 3.26 / 2
USB_PLUG_W, USB_PLUG_H = 12.4, 6.6     # cable overmold relief (typical USB-C cable)
FPC_CONN = dict(x0=25.0, x1=35.0, y0=3.0, y1=7.0, h=2.0)      # 13p 0.5 mm FPC, under the display
BTN_SW = (3.0, 4.0, 2.5)                                       # 3 x 4 x 2.5 top tact (e.g. XKB TS-1088)
# SPEC 2.1: ZERO x~8, HOLD/SEND x~20, MODE x~54, along the upper band.
# DEV-5: HOLD at x 18.5 so its cap clears the display glass (glass starts at x 21.2).
BUTTONS = {"ZERO": (8.0, 31.0), "HOLD": (18.5, 31.0), "MODE": (54.0, 31.0)}

# Bottom-side rules (SPEC 2.1 + DEV-2): over the beam the board is 0.15 mm off the
# scale, so the only bottom parts allowed over the beam are inside the tape channel.
BOTTOM_CHANNEL_MAX_H = None   # filled below

# ---------------------------------------------------------------------------
# Display: 1.14 in 240 x 135 IPS, ST7789, 13-pin 0.5 mm FPC.
# Outline 17.60 x 31.00 x 1.60, active area 14.86 x 24.91 (BuyDisplay / Chance
# Display 1.14" 135x240 drawings).  NOTE: the task brief's "30.0 x 13.5" glass is
# narrower than its own 14.9 mm active area, so the vendor numbers are used.
# Portrait (long axis along y), SPEC 2.1 "glass over y ~ 4..30".
# ---------------------------------------------------------------------------
DISP_W, DISP_H, DISP_T = 17.60, 31.00, 1.60
DISP_AA_W, DISP_AA_H = 14.86, 24.91
DISP_CX, DISP_CY = 30.0, 17.0           # board coordinates
DISP_AA_DY = 1.45                        # TVP: active area shifted away from the FPC end (FPC at -y)
DISP_WIN_MARGIN = 0.25                   # window = active area + 0.25 per side

# ---------------------------------------------------------------------------
# Battery 402535 (4.0 x 25 x 35, ~500 mAh); pocket off the beam, under the board's upper band
# ---------------------------------------------------------------------------
BAT_T, BAT_W, BAT_L = 4.0, 25.0, 35.0
BAT_POCKET = dict(u0=20.0, u1=56.0, y0=22.4, y1=48.0)   # 36 x 25.6: room for 1 mm swelling in length, 0.6 in width

# ---------------------------------------------------------------------------
# Slider housing (rev A printed PETG or PA-CF; rev B 6061-T6)
# ---------------------------------------------------------------------------
H_U0 = 0.5                # housing end faces stand back 0.5 from the jaw face
H_U1 = 78.0               # SPEC 7: <= 78 long
H_Y0 = -2.8               # lower rail outside face
H_Y1 = 49.2               # top face   -> 52.0 tall (SPEC 7: <= 52)
STEP_U1 = 6.4             # left "step": the housing is only STEP_Y1 tall for u < 6.4
STEP_Y1 = 23.0            # so the inside jaws sit low
Z_BACK = -7.4             # back cover outside face
Z_COVER_IN = -5.4         # back cover inside face = body back face
Z_LID_IN = 5.4            # lid underside = body front face
Z_LID = 6.8               # lid top
LID_T = Z_LID - Z_LID_IN
COVER_T = Z_COVER_IN - Z_BACK

# Beam channel through the body (with the gib allowances)
REF_STRIP_T = 1.0         # brass reference strip on the lower edge (fixed, glued)
YGIB_T = 1.0              # brass Y-gib on the upper edge (spring loaded)
CH_Y0 = -REF_STRIP_T
CH_Y1 = BEAM_W + YGIB_T + 0.2
CH_Z0 = Z_COVER_IN        # open to the back cover; the back gib floats in here
CH_Z1 = 0.10              # tower underside, 0.10 over the beam face (front pads sit in pockets)

# Back gib (preload): 1.2 thick brass, pushed onto the beam back face by 2 spring plungers
BGIB_T = 1.2
BGIB = dict(u0=7.0, u1=71.0, y0=3.0, y1=17.0)
BGIB_PLUNGERS = [(14.0, 10.0), (64.0, 10.0)]     # in the back cover, (u, y)

# Front pads (position): 4 brass pads on the beam's lands, one M2 set screw each.
# They set the board height over the beam, i.e. both sensor gaps.
FPAD_T = 1.0
FPAD_LEN = 4.0
FPADS = [  # (u centre, y0, y1, set-screw y).  The right upper screw sits at y 18.2
    (3.5, 0.20, 1.70, 0.95), (3.5, 17.80, 19.80, 18.8),   # so its insert clears the USB relief
    (74.0, 0.20, 1.70, 0.95), (74.0, 17.80, 19.80, 18.2),
]

# Y gib: brass 1.0 x 3.0 on the upper edge, two spring plungers + the locking screw
YGIB = dict(u0=9.0, u1=69.0, z0=-3.5, z1=-0.5)
YGIB_PLUNGERS_U = [16.0, 58.5]
LOCK_U = 63.0             # M3 thumb screw from the top face, clamps the Y gib
PLUNGER_BORE_D = 2.2
LOCK_BORE_D = 3.4
GIB_Z = -2.0              # bore axis height of the Y-gib adjusters

# Board bosses (body), lid screws, back-cover screws
BOSS_D = 4.5
LID_SCREWS = [(3.5, 10.0), (74.0, 10.0), (10.5, 46.0), (74.0, 44.0)]
COVER_SCREWS = [(12.0, 44.0), (67.5, 44.0)]       # plus the 4 board screws, which go through
COVER_BOSS_H = 1.2        # outside bosses on the back cover for the plunger inserts

# Thumb roller: on the beam's upper edge at the right tower, axis along z
ROLLER_D = 8.0            # over the O-ring
ROLLER_HUB_D = 6.4
ROLLER_T = 2.5
ROLLER_U = 74.6
ROLLER_Y = BEAM_W + ROLLER_D / 2 - 0.15  # 0.15 squeeze on the O-ring tyre
ROLLER_Z0, ROLLER_Z1 = -3.85, -1.35
ROLLER_AXLE_D = 2.0
ORING = "ID 6.0 x CS 0.8 NBR (stretched onto the 6.4 groove root)"

# Buttons
CAP_STEM_D = 3.5
CAP_HOLE_D = 3.9
CAP_FLANGE = (3.5, 6.0, 0.8)   # bar flange (u x y) under the lid: clears the glass and the cavity wall

# Moving / fixed jaws
JAW_Z0, JAW_Z1 = -5.4, 2.4     # outside jaws, 7.8 thick; back face flush with the body back (prints flat), centre z -1.5 (0.5 off the beam mid-plane)
JAW_L = 40.0                    # tip at y = -40
JAW_ROOT_W = 20.0              # FEA (fea_jaw.py): 16 -> 20 wide and 6 -> 8 thick cut the PETG flex at the tip contact 36 -> 15 um
JAW_TIP_W = 3.5
JAW_RELIEF = (0.5, 1.2)         # root relief notch (x depth, y height) below the rail
JAW_FORCE = 5.0                 # N, measuring force for the calcs
IJ_TIP_Y0, IJ_TIP_Y1 = 31.0, 37.0   # inside-jaw measuring zone
IJ_TIP_W = 3.0
IJ_FIXED_Z = (-4.0, -1.6)
IJ_MOVING_Z = (-1.4, 1.0)

# Fixed jaw block
FJ_X0, FJ_X1 = -18.0, -0.5
FJ_Z0, FJ_Z1 = -6.5, 2.5
FJ_Y0, FJ_Y1 = H_Y0, STEP_Y1

# Depth rod: OMITTED in rev A (see docs/mechanical.md section 7)
DEPTH_ROD = False

# ---------------------------------------------------------------------------
# Derived numbers
# ---------------------------------------------------------------------------
TAPE_TOP = BOARD_Z0 - AS_H_NOM - MAG_GAP          # tape surface, z (nominal package, nominal shim)
# Review fix: a Kapton shim under the tape can only RAISE the tape, i.e. only close the gap.
# The channel is therefore cut so that the tallest package (A max 1.20) gets 0.30 with NO
# shim; every shorter package is brought to 0.30 by shimming 0 .. (A_max - A_min) = 0.35.
# The nominal package (A 1.10) needs TAPE_SHIM_NOM = 0.10 -- the assembly shows that case.
TAPE_SHIM_NOM = AS_H_MAX - AS_H_NOM
TAPE_SHIM_MAX = AS_H_MAX - AS_H_MIN
TAPE_CH_DEPTH = -(TAPE_TOP - TAPE_T - TAPE_ADH) + TAPE_SHIM_NOM   # channel floor depth below the beam face
BOTTOM_CHANNEL_MAX_H = AS_H_NOM + MAG_GAP - 0.10  # any bottom part over the channel
HOUSING_SIZE = (H_U1 - H_U0, H_Y1 - H_Y0, Z_LID + 0.6 - (Z_BACK - COVER_BOSS_H))


def as_namespace():
    return SimpleNamespace(**{k: v for k, v in globals().items() if k.isupper()})


if __name__ == "__main__":
    print(f"tape surface z        {TAPE_TOP:+.3f}")
    print(f"tape channel depth    {TAPE_CH_DEPTH:.3f}  (beam {BEAM_T})")
    print(f"scale pocket depth    {SCALE_POCKET_DEPTH:.3f}")
    print(f"board z               {BOARD_Z0:.2f} .. {BOARD_Z1:.2f}")
    print(f"housing envelope      {HOUSING_SIZE[0]:.1f} x {HOUSING_SIZE[1]:.1f} x {HOUSING_SIZE[2]:.1f}")
