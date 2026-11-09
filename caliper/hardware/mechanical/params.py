#!/usr/bin/env python3
"""Every mechanical dimension of the PrettyCool Caliper rev A, in one place.

Sources: caliper/hardware/design/SPEC.md (sections 2.1, 2.2, 7 and the decisions
D2-D5 in section 10), nets.py (SLIDER_OUTLINE / SLIDER_HOLES / SLIDER_KEEPOUTS) and
the datasheets quoted next to each number.  Anything tagged ``TVP`` is an
assumption to verify on the prototype; ``DEV`` deviates from SPEC and is explained
in docs/mechanical.md section 3.

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
jaw's measuring face), so every slider number below is a u.  Board x = u - 8.
"""
import math
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# General print / fit rules (Bambu P2S, 0.4 mm nozzle)
# ---------------------------------------------------------------------------
NOZZLE = 0.4
LAYER = 0.20
WALL_MIN = 1.2            # >= 3 perimeters
WALL_LOCAL_MIN = 0.4      # local web between two cut features (one perimeter pair); tests flag anything thinner
CLR_SLIDE = 0.15          # printed sliding fit, per side (0.15-0.20 rule)
CLR_LOOSE = 0.20
INSERT_M2_D = 3.2         # hole for an M2 x 3 heat-set insert (OD 3.6 knurl, CNC Kitchen style)
INSERT_M2_L = 3.0
INSERT_M3_D = 4.0         # M3 x 4 insert hole
INSERT_M3_L = 4.0
PT_PILOT_D = 1.7          # pilot for an M2-class thread-forming screw for plastics (WN 1452 / PT K20, 2.2 x L)
M2_CLR = 2.2
M2_TAP = 1.6              # rev B: tap drill for M2 x 0.4; rev A: printed hole tapped M2 (nylon H1 screw)
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

# Magnetic tape (AS5311, 2.0 mm pole pair = 1.0 mm pole length).  SPEC D2 / 7:
# 8.0 mm wide (slit), centred y 6, in a 2.00 mm channel cut so the TALLEST package
# gets the 0.30 gap with no shim; shorter packages get a 0-0.35 Kapton shim.
TAPE_W = 8.0
TAPE_YC = 6.0
TAPE_T = 0.60             # TVP: magnet + backing; SPEC's 0.6 pocket implies ~0.5 + adhesive.
TAPE_T_TOL = 0.05         # TVP: per-roll tolerance of a calendered bonded-ferrite strip.
TAPE_ADH = 0.05           # 3M 467MP transfer tape, 0.05 mm
TAPE_ADH_TOL = 0.01
TAPE_X0, TAPE_X1 = 28.0, 200.0   # SPEC 7: beam x 28..200
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

# Scale PCB (SPEC 2.2): 200 x 7 x 0.8, bonded (no screws) in a pocket at y 10.45 .. 17.55
SCALE_L, SCALE_W, SCALE_T = 200.0, 7.0, 0.80
SCALE_T_TOL = 0.08        # FR4 +/-10 %, JLC standard (TVP: order with +/-0.05 "tight" option)
SCALE_ADH = 0.05          # 467MP
SCALE_Y0 = 10.5
SCALE_X0 = 14.5           # SPEC D5: pattern centred on the electrode sweep (was 14.0)
SCALE_POCKET_W = SCALE_W + 0.10           # y 10.45 .. 17.55
SCALE_POCKET_DEPTH = SCALE_T + SCALE_ADH  # 0.85: PCB face flush with the beam face (nominal)

# Fixed-jaw joint in the beam: 2 x M3 bolts + 2 x 3 mm dowels (h6 pins, H7 reamed holes)
FJ_BOLTS = [(-12.0, 5.0), (-12.0, 15.0)]
FJ_DOWELS = [(-5.0, 4.0), (-5.0, 16.0)]
# Bolts: M3 x 10 (ISO 4762 socket head, or ISO 7380 button head) from the front face into an
# ISO 4032 hex nut (5.5 AF, m 2.15-2.40) in a hex trap on the back.  The block is 11.1 thick, so a
# 2.5 deep trap left the screw ~1.4 mm into the nut; the trap is now 3.6 deep, so the screw end
# reaches 0.1 past the nut's far face and stays 1.1 below the back face (an M3 x 12 would stand
# 0.9 proud).  0.95 of PA-CF is left between the trap floor and the beam slot; it is loaded in
# compression against the beam's back face only.
FJ_SCREW_L = 10.0
NUT_M3_AF, NUT_M3_M = 5.5, 2.4
FJ_NUT_TRAP_AF = 5.6
FJ_NUT_TRAP_DEPTH = 3.6
DOWEL_D = 3.0
# End stop (review fix e): an M2 x 6 socket-head cap screw (ISO 4762) in an M2 tapped hole
# through the beam; its head (3.8 x 2.0) stands proud of the front face on the upper land and
# the slider's right end face hits it.  Unscrew it and the slider comes off the beam end.
STOP_D = 3.8              # head diameter (the contact)
STOP_THREAD_D = 2.0
STOP_Y = 18.8
STOP_PROUD = 2.0          # head height

# ---------------------------------------------------------------------------
# Slider board (SPEC 2 / 2.1 / D3): 62 x 34 x 1.0 body + two 6 x 14 end tabs
# ---------------------------------------------------------------------------
BOARD_L, BOARD_W, BOARD_T = 62.0, 34.0, 1.0
BOARD_TABS = [(-6.0, 2.5, 0.0, 16.5), (62.0, 2.5, 68.0, 16.5)]   # (x0, y0, x1, y1), board coordinates
BOARD_U0 = 8.0            # board x = 0 sits at slider u = 8
BOARD_Z0 = CAP_GAP        # board bottom = 0.15 above the beam / scale face
BOARD_Z1 = BOARD_Z0 + BOARD_T
BOARD_FLATNESS = 0.03     # SPEC D3 fab note: over y 0..20, x -6..68, every board inspected
# Holes (SPEC 2.1 / nets.SLIDER_HOLES): H1 is a support (nylon screw), H2-H5 carry the SMT M2
# standoffs and are the Z datum.  The mechanics' three upper-band holes of the first model are gone.
H1 = (18.75, 24.0)
TAB_HOLES = [(-3.5, 5.5), (-3.5, 14.0), (65.5, 5.5), (65.5, 14.0)]   # H2, H3, H4, H5
BOARD_HOLES = [H1] + TAB_HOLES
BOARD_HOLE_D = 2.2
ANTENNA = (0.15, 29.5, 15.55, 34.0)     # the module's PCB antenna (board x0, y0, x1, y1) as placed: U10 origin
                                        # x 7.85 on the routed board (SPEC 2.1 table: 8.3 -> x 0.6..16.0)
ANTENNA_KEEPOUT = (0.0, 29.0, 21.0, 34.0)
RF_CLEAR = 5.0            # SPEC D4: nothing metal / carbon-filled within 5 mm (plan) of the antenna area
UNDER_GLASS = (16.15, 1.2, 49.85, 20.15)  # top parts <= 2.6 here, <= 4.2 elsewhere (SPEC 2.1)
H_UNDER_GLASS, H_ELSEWHERE = 2.6, 4.2
BOTTOM_WINDOW = (20.0, 2.4, 41.0, 9.6)  # bottom parts over y 0..20 only here, <= 1.30 tall (SPEC D2)
BOTTOM_WINDOW_H = 1.30

# Tab clamps (SPEC D3; review fix b).  An SMT M2 standoff (PEM SMTSO-M2-2ET class, 2.0 tall,
# OD <= 4.0) is reflowed on each tab hole's top pad.  An M2 x 4 low-head screw from the tower's
# front face pulls it up against a 2.2 x 4.0 x 0.3 shim washer that is BEDDED IN EPOXY in the
# tower pocket while the board lies on 0.15 mm shim foil on the beam (liquid shim): the four
# clamp faces are then coplanar with the beam face, not with a bridged printed surface.
STANDOFF_OD, STANDOFF_H = 4.0, 2.0
STANDOFF_POCKET_D = 4.4
CLAMP_WASHER_T = 0.30
EPOXY_GAP = 0.20          # nominal bedding gap (0.05..0.35 with the print / tower-height tolerance)
CLAMP_CEIL_Z = BOARD_Z1 + STANDOFF_H + CLAMP_WASHER_T + EPOXY_GAP     # 3.65
CLAMP_HEAD_D, CLAMP_HEAD_K = 3.8, 1.0      # M2 low head (DIN 921 / ISO 7380-class, k <= 1.0)
CLAMP_CBORE_Z = 5.0       # the head seats 0.4 below the body front face ...
LID_HEAD_POCKET = 0.7     # ... and 0.6 of it sits in a pocket in the lid underside
TAB_POCKET_CLR_Y, TAB_POCKET_CLR_U = 0.2, 0.2    # u: keeps the right end wall at 1.2 (77.4 - 76.2)
TAB_POCKET_Z1 = BOARD_Z1 + 0.3

# Top-side components: used only by the placeholder envelope (board_envelope.py) when
# board_parts.json is missing.  Positions are the SPEC 2.1 placement table (D4).
MINI1 = dict(x0=0.6, x1=16.0, y0=13.5, y1=34.0, h=2.55)        # 15.4 x 20.5 x 2.4 (+0.15)
USBC = dict(x0=55.65, x1=63.0, y0=22.03, y1=30.97, h=3.26)     # HRO TYPE-C-31-M-12, 1 mm overhang
USBC_YC = 26.5            # SPEC 2.1 (was the mechanics' DEV-4)
USBC_ZC = BOARD_Z1 + 3.26 / 2
# Cable overmold relief.  Review fix: the first relief (12.4 x 6.6) cut the right tower's front
# part loose above the beam; a slim cable (overmold <= 10.4 x 5.8, TVP: check the cable) keeps the
# relief above the channel (y >= 21.2).
USB_PLUG_W, USB_PLUG_H = 10.6, 6.0
FPC_CONN = dict(x0=19.5, x1=23.5, y0=4.5, y1=12.5, h=2.0)      # J50 FH12-13S, under the glass's -x end
BTN_SW = (3.9, 2.9, 2.0)                                       # TS-1088-xR020 3.9 x 2.9 x 2.0 (SPEC 2.1)
BUTTONS = {"ZERO": (31.0, 31.0), "HOLD": (38.5, 31.0), "MODE": (46.0, 31.0)}   # SPEC D4
J_BAT = dict(x=24.5, y=31.4)       # JST-SH 2p side entry, mouth +y (the board's top edge)
PIEZO_PORT = (40.0, 24.3)          # BZ50 sound port in the lid (board x, y)
LED_PIPE = (51.5, 32.0)            # D50 light pipe in the lid (board x, y)
LED_PIPE_D = 2.0
PIEZO_PORT_D = 1.5

# ---------------------------------------------------------------------------
# Display: 1.14 in 240 x 135 IPS, ST7789, 13-pin 0.5 mm FPC.
# Outline 31.00 x 17.60 x 1.60, active area 24.91 x 14.86 (BuyDisplay / Chance Display drawings).
# Landscape (SPEC D4): 31.0 along x, FPC at the -x end; glass x 17.5..48.5, y 1.2..18.8.
# ---------------------------------------------------------------------------
DISP_W, DISP_H, DISP_T = 31.00, 17.60, 1.60     # x, y, z
DISP_AA_W, DISP_AA_H = 24.91, 14.86
DISP_CX, DISP_CY = 33.0, 10.0           # board coordinates
DISP_AA_DX = 1.45                        # TVP: active area shifted away from the FPC end (+x)
DISP_WIN_MARGIN = 0.25                   # window = active area + 0.25 per side
DISP_RIB = 1.35                          # lid end ribs x 16.15..17.5 and 48.5..49.85 (SPEC 2.1)

# ---------------------------------------------------------------------------
# Battery 402535 (4.0 x 25 x 35, ~500 mAh); pocket behind the board's upper band, moved to
# u 29.5..65.5 (board x >= 21.5) for the antenna (SPEC D4).  Closed by a battery door.
# ---------------------------------------------------------------------------
BAT_T, BAT_W, BAT_L = 4.0, 25.0, 35.0
BAT_POCKET = dict(u0=29.5, u1=65.5, y0=22.4, y1=48.0)   # 36 x 25.6: 1 mm swelling in length, 0.6 in width
BAT_DOOR = dict(u0=26.5, u1=69.0, y0=22.4, y1=None)     # rebate in the body back face; y1 = H_Y1 (open top)
DOOR_SCREWS = [(27.9, 44.0), (67.25, 44.0)]             # PT screws through the door ledges (>= 5 mm from the antenna)
PLUG_RELIEF = dict(u0=29.5, u1=36.5, y0=33.6, y1=41.0)  # JST plug + battery leads past the board top edge

# ---------------------------------------------------------------------------
# Slider housing (rev A printed PA-CF / PETG; rev B 6061-T6)
# ---------------------------------------------------------------------------
H_U0 = 0.5                # housing end faces stand back 0.5 from the jaw face
H_U1 = 77.4               # review fix e: roller rim at u 78.0 = SPEC 7's 78 including the roller
H_Y0 = -2.8               # lower rail outside face
H_Y1 = 49.2               # top face   -> 52.0 tall (SPEC 7: <= 52)
STEP_U1 = 6.4             # left "step": the housing is only STEP_Y1 tall for u < 6.4
STEP_Y1 = 23.0            # so the inside jaws sit low
# Review fix a: the body now closes behind the beam.  Its back face (the print bed) is at
# Z_BACK, the plane of the old cover's plunger bosses, so the z envelope is unchanged; a 3.2
# back web behind the beam channel carries the back-gib plungers; the old full-size back cover
# is replaced by a battery door (2.0 flange + 1.2 plug) inset in the back face.
Z_BACK = -8.6             # body back face = battery-door outside face (print bed)
Z_WEB_IN = -5.4           # back web inside face = channel back = battery-pocket floor
Z_LID_IN = 5.4            # lid underside = body front face
Z_LID = 6.8               # lid top
LID_T = Z_LID - Z_LID_IN
WEB_T = Z_WEB_IN - Z_BACK
DOOR_T = 2.0              # door flange; its plug fills the remaining 1.2 inside the pocket outline

# Beam channel through the body (with the gib allowances): a closed tunnel now
REF_STRIP_T = 1.0         # brass reference strip on the lower edge (fixed, glued)
YGIB_T = 1.0              # brass Y-gib on the upper edge (spring loaded)
CH_Y0 = -REF_STRIP_T
CH_Y1 = BEAM_W + YGIB_T + 0.2
CH_Z0 = Z_WEB_IN
CH_Z1 = 0.10              # tower underside, 0.10 over the beam face (front pads sit in pockets)
CAV_FLOOR = BOARD_Z0 - 0.75   # cavity floor under the board's upper band

# Back gib (Z preload): 1.2 brass on the beam back face, pushed by 2 spring plungers in the
# back web.  Review fix c: plungers moved to y 5 (lever 13.8 to the upper pad line, was 8.8)
# and the preload cut from 4 to 2.5 N each.
BGIB_T = 1.2
BGIB = dict(u0=7.0, u1=71.0, y0=3.0, y1=17.0)
BGIB_PLUNGERS = [(14.0, 5.0), (64.0, 5.0)]     # in the back web, (u, y)
P_BACK = 2.5              # N each (spring rate TVP)

# Front pads (position): 4 brass pads on the beam's lands, one M2 set screw each.
FPAD_T = 1.0
FPAD_LEN = 4.0
FPADS = [  # (u centre, y0, y1, set-screw y)
    (3.5, 0.20, 1.70, 0.95), (3.5, 17.80, 19.80, 18.8),
    (74.0, 0.20, 1.70, 0.95), (74.0, 17.80, 19.80, 18.8),
]

# Y gib: brass 1.0 x 3.0 on the upper edge.  Review fix c/D4: both spring plungers and the lock
# now sit LEFT of the battery pocket (u 29.5..65.5), where they also have the best lever
# against the measuring-force couple.  They pass under the antenna, so each is pushed through a
# non-metallic GFRP rod (Dia 2) from a spring / set screw / thumb screw at y >= 41 (>= 5 mm
# from the antenna area, SPEC D4).
YGIB = dict(u0=9.0, u1=69.0, z0=-3.5, z1=-0.5)
YGIB_PLUNGERS_U = [14.0, 24.0]
LOCK_U = 19.0             # M3 thumb screw at the top face, pushes a GFRP rod onto the Y gib
P_Y = 4.0                 # N each (spring rate TVP)
PUSHER_D = 2.0            # GFRP (glass-fibre) rod
PLUNGER_BORE_D = 2.2
LOCK_BORE_D = 2.2
GIB_Z = -2.3              # review fix e: bore top -1.2, 0.6 below the cavity floor (was 0.3 into it)
PUSHER_TOP_Y = 41.0       # metal (spring, screws, inserts) only above this y

# Board support H1 (nylon M2 x 5) into a boss printed 0.1 low and shimmed; tapped in the print.
BOSS_D = 4.5
H1_BOSS_LOW = 0.10
# Button-band ledge (open item from the contract review): HOLD and MODE sit over the battery pocket
# with no body under the board.  A 1.8 mm ledge cantilevered from the cavity wall at y 34.4 runs
# under the board's top edge (bottom side there: solder mask only), printed 0.05 low and shimmed to
# contact with Kapton like H1, so it supports the board without pulling it out of the tab plane.
BTN_LEDGE = dict(u0=37.0, u1=65.5, y0=32.6, low=0.05)

# Lid screws: (u, y, kind).  The two tower screws are thread-forming (no insert room between
# the tab clamps); the two upper ones use heat-set inserts.
LID_SCREWS = [(4.5, 9.75, "pt"), (73.5, 9.75, "pt"), (10.5, 46.0, "insert"), (74.0, 44.0, "insert")]

# Thumb roller: on the beam's upper edge at the right tower, axis along z.  Review fix e:
# the roller drops 0.5 so the slot roof keeps >= 1.2 of material under the USB relief.
ROLLER_D = 8.0            # over the O-ring
ROLLER_HUB_D = 6.4
ROLLER_T = 2.5
ROLLER_U = H_U1 + 0.6 - ROLLER_D / 2       # rim 0.6 proud of the end face, at u 78.0
ROLLER_Y = BEAM_W + ROLLER_D / 2 - 0.15    # 0.15 squeeze on the O-ring tyre
ROLLER_Z0, ROLLER_Z1 = -4.35, -1.85
ROLLER_AXLE_D = 2.0
ROLLER_SLOT_CLR = 0.35
ORING = "ID 6.0 x CS 0.8 NBR (stretched onto the 6.4 groove root)"

# Buttons
CAP_STEM_D = 3.5
CAP_HOLE_D = 3.9
CAP_FLANGE = (3.5, 5.0, 0.8)   # bar flange (u x y) under the lid

# Moving / fixed jaws
JAW_Z0, JAW_Z1 = Z_BACK, 2.4    # outside jaws, 11.0 thick; back face on the print bed, centre z -3.1 (1.1 off the beam mid-plane)
JAW_L = 40.0                    # tip at y = -40
JAW_ROOT_W = 20.0
JAW_TIP_W = 3.5
JAW_RELIEF = (0.5, 1.2)         # root relief notch (x depth, y height) below the rail
JAW_FORCE = 5.0                 # N, measuring force for the calcs
IJ_TIP_Y0, IJ_TIP_Y1 = 31.0, 37.0   # inside-jaw measuring zone
IJ_TIP_W = 3.0
# Review fix d: each inside jaw now starts on its own part's print bed, so neither needs
# support.  The slider prints back face down (z -7.4 on the bed), the fixed jaw front face down
# (z +2.5 on the bed); the tips cross 0.2 apart in z.
IJ_MOVING_Z = (Z_BACK, Z_BACK + 2.4)
# RF relief (2026-11-08, first pass).  The module moved 0.45 mm toward the jaw in layout, which put the moving
# inside jaw's root flank 4.70 mm (plan) from the antenna corner (SPEC D4: >= 5 for carbon fill).  The 2.4
# plate's flank was then stepped round that corner on an arc of RF_CLEAR + IJ_RF_MARGIN and its root started at
# u 0.5 (moving_inside_jaw_outline(), kept for the FEA comparison).  The stiffened jaw below replaced that
# outline: its PA-CF keeps the same RF_CLEAR + IJ_RF_MARGIN, the rest of it prints in unfilled PA.
IJ_RF_MARGIN = 0.15
IJ_ROOT_U0 = H_U0
IJ_ROOT_U0_OLD = 1.5
IJ_FLANK = ((0.0, IJ_TIP_Y0), (STEP_U1, 24.6))   # root flank, from the tip's measuring edge to the step
IJ_FIXED_Z = (Z_BACK + 2.6, 2.5)
# The fixed inside jaw's right flank (x 3 at the tip's lower corner down to x -0.6 at y 24.2): the
# moving jaw may only grow above IJ_MOVING_Z where it stays right of this line at every R >= 0.
FIXED_IJ_FLANK = ((IJ_TIP_W, IJ_TIP_Y0), (-0.6, 24.2))
# Stiffening (2026-11-08, second pass).  The RF-relieved 2.4 plate deflected 8.0 um/N (PA-CF) at the
# measuring face, ~48 um over a 2-8 N thumb spread.  The measuring face (u 0, y 31..37), the tip's z
# (-8.6..-6.2: the 0.2 crossing gap and the crossed tips' z stack) and its 3.0 width at the end (y 37) are
# unchanged.  Below and beside it:
#  * the tip's back (left) edge tapers from 3.0 wide at y 37 to IJ_TIP_BASE_W at y 31, so a gap or bore
#    narrower than IJ_TIP_BASE_W takes less than the full 6 mm of tip (3.0 at the very end, as before);
#  * the plate fills a shoulder block u -IJ_TIP_BASE_W..6.4 under the tip, its top level with the face's
#    lower end (y 31; was a 45 deg flank from there and a left edge sloping in to u 0.5).  Its left part
#    (u < 0.5) hangs IJ_LEFT_Y0 - STEP_Y1 over the fixed block's top at R = 0 and passes under the fixed
#    inside jaw 0.2 apart in z, as the tip does;
#  * a full-height gusset (z Z_BACK..IJ_GUSSET_Z1) fills the part of the block that the fixed inside jaw
#    can never reach: right of FIXED_IJ_FLANK offset by IJ_FIXED_CLR (perpendicular).  It sits on the
#    step top (y 22.9) and against the full-height housing's left face (u 6.4) up to y 31;
#  * the block and gusset within RF_CLEAR + IJ_RF_MARGIN of the antenna area print in unfilled PA (the
#    slicer modifier, models.rf_modifier), so the PA-CF keeps >= 5.15 mm (plan) from it as before.
# Nothing is added above y 31 right of the face, so a bore still takes the full 6 mm tip.
# fea_inside_jaw.py compares it with the 2.4 plate.
IJ_TIP_BASE_W = 4.0
IJ_LEFT_Y0 = STEP_Y1 + 0.4
IJ_FIXED_CLR = 0.4
IJ_GUSSET_Z1 = 2.4

# Fixed jaw block
FJ_X0, FJ_X1 = -18.0, -0.5
FJ_Z0, FJ_Z1 = Z_BACK, 2.5
FJ_Y0, FJ_Y1 = H_Y0, STEP_Y1

# Depth rod: OMITTED in rev A (see docs/mechanical.md section 7)
DEPTH_ROD = False

# ---------------------------------------------------------------------------
# Derived numbers
# ---------------------------------------------------------------------------
TAPE_TOP = BOARD_Z0 - AS_H_NOM - MAG_GAP          # tape surface, z (nominal package, nominal shim)
# A Kapton shim under the tape can only RAISE the tape, i.e. only close the gap.  The channel is
# cut so the tallest package (A max 1.20) gets 0.30 with NO shim; every shorter package is
# brought to 0.30 by shimming 0 .. (A_max - A_min) = 0.35.
TAPE_SHIM_NOM = AS_H_MAX - AS_H_NOM
TAPE_SHIM_MAX = AS_H_MAX - AS_H_MIN
TAPE_CH_DEPTH = -(TAPE_TOP - TAPE_T - TAPE_ADH) + TAPE_SHIM_NOM   # channel floor depth below the beam face
BOTTOM_CHANNEL_MAX_H = AS_H_NOM + MAG_GAP - 0.10  # any bottom part over the channel
BAT_DOOR["y1"] = H_Y1
HOUSING_SIZE = (H_U1 - H_U0, H_Y1 - H_Y0, Z_LID + 0.6 - Z_BACK)
ROLLER_RIM_U = ROLLER_U + ROLLER_D / 2


def bu(bx):
    """Board x -> slider u."""
    return BOARD_U0 + bx


def _rf_arc(p0, p1, n=10):
    """Vertices replacing the part of segment p0-p1 closer than RF_CLEAR + IJ_RF_MARGIN to the antenna's
    corner nearest the jaw (u = bu(ANTENNA[0]), y = ANTENNA[1]).  The vertices sit on a circle of radius
    r / cos(dt / 2) (dt = the angle per chord), so every chord stays >= r from the corner.
    [] when the segment already clears."""
    cx, cy = bu(ANTENNA[0]), ANTENNA[1]
    r = RF_CLEAR + IJ_RF_MARGIN
    L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    ex, ey = (p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L
    t_f = (cx - p0[0]) * ex + (cy - p0[1]) * ey
    fx, fy = p0[0] + t_f * ex, p0[1] + t_f * ey
    d = math.hypot(fx - cx, fy - cy)
    if d >= r:
        return []
    rv = r
    for _ in range(20):
        h = math.sqrt(rv * rv - d * d)
        a0 = math.atan2(fy - h * ey - cy, fx - h * ex - cx)   # end toward p0
        a1 = math.atan2(fy + h * ey - cy, fx + h * ex - cx)   # end toward p1
        span = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi  # the short way, through the foot direction
        rv = r / math.cos(abs(span) / n / 2)
    if not (0.0 < t_f - h and t_f + h < L):
        raise ValueError("RF relief arc runs off the root flank: widen the flank or move the jaw")
    return [(cx + rv * math.cos(a0 + span * i / n), cy + rv * math.sin(a0 + span * i / n)) for i in range(n + 1)]


def fixed_flank_offset_u(y, clr=None):
    """u of FIXED_IJ_FLANK at height y, moved IJ_FIXED_CLR perpendicular toward +u (the slider side)."""
    clr = IJ_FIXED_CLR if clr is None else clr
    (xb, yb_), (xa, ya) = FIXED_IJ_FLANK
    L = math.hypot(xb - xa, yb_ - ya)
    nx, ny = (yb_ - ya) / L, -(xb - xa) / L          # unit normal toward +u
    x0, y0 = xa + clr * nx, ya + clr * ny
    return x0 + (xb - xa) / (yb_ - ya) * (y - y0)


def moving_inside_jaw_block_outline():
    """Plan outline (u, y) of the moving inside jaw's 2.4 plate as built: the tip (face u 0, y 31..37; 3.0
    wide at y 37, IJ_TIP_BASE_W at y 31) on a shoulder block u -IJ_TIP_BASE_W..STEP_U1, y IJ_LEFT_Y0 (left
    part) / 22.9 (root on the step) .. 31."""
    t0, t1, w, wb = IJ_TIP_Y0, IJ_TIP_Y1, IJ_TIP_W, IJ_TIP_BASE_W
    yb = STEP_Y1 - 0.1
    return [(-w, t1), (0.0, t1), (0.0, t0), (STEP_U1, t0), (STEP_U1, yb),
            (IJ_ROOT_U0, yb), (IJ_ROOT_U0, IJ_LEFT_Y0), (-wb, IJ_LEFT_Y0), (-wb, t0)]


def moving_inside_jaw_gusset_outline():
    """Plan outline (u, y) of the full-height gusset (z Z_BACK..IJ_GUSSET_Z1): the block right of the fixed
    inside jaw's right flank + IJ_FIXED_CLR, so the fixed jaw never reaches it at any R >= 0."""
    yb, s = STEP_Y1 - 0.1, IJ_TIP_Y0
    (xb, yb_), (xa, ya) = FIXED_IJ_FLANK
    u_low = xa + IJ_FIXED_CLR                          # beside the fixed jaw's vertical root side (x -0.6)
    # where the offset flank meets u = u_low
    y_low = ya + (u_low - fixed_flank_offset_u(ya)) * (yb_ - ya) / (xb - xa)
    return [(IJ_ROOT_U0, yb), (STEP_U1, yb), (STEP_U1, s), (fixed_flank_offset_u(s), s),
            (u_low, y_low), (u_low, IJ_LEFT_Y0), (IJ_ROOT_U0, IJ_LEFT_Y0)]


def moving_inside_jaw_outline(rf_relief=True, root_u0=None):
    """Plan outline (u, y) of the moving inside jaw's 2.4 plate BEFORE the stiffening (fea_inside_jaw.py
    compares them): rf_relief=True the RF-relieved outline (R 5.15 arc, root from u 0.5); rf_relief=False
    the phase-3 outline (straight root flank, root from u 1.5); root_u0 overrides the root's left end."""
    t1, w = IJ_TIP_Y1, IJ_TIP_W
    yb = STEP_Y1 - 0.1
    (u0, y0), (u1, y1) = IJ_FLANK
    arc = _rf_arc(IJ_FLANK[0], IJ_FLANK[1]) if rf_relief else []
    if root_u0 is None:
        root_u0 = IJ_ROOT_U0 if rf_relief else IJ_ROOT_U0_OLD
    return [(-w, t1), (0, t1), (u0, y0)] + arc + [(u1, y1), (STEP_U1, yb), (root_u0, yb), (-w, IJ_TIP_Y0)]


def as_namespace():
    return SimpleNamespace(**{k: v for k, v in globals().items() if k.isupper()})


if __name__ == "__main__":
    print(f"tape surface z        {TAPE_TOP:+.3f}")
    print(f"tape channel depth    {TAPE_CH_DEPTH:.3f}  (beam {BEAM_T})")
    print(f"scale pocket depth    {SCALE_POCKET_DEPTH:.3f}")
    print(f"board z               {BOARD_Z0:.2f} .. {BOARD_Z1:.2f}")
    print(f"tab clamp ceiling z   {CLAMP_CEIL_Z:.2f}  (standoff {STANDOFF_H} + washer {CLAMP_WASHER_T} + epoxy {EPOXY_GAP})")
    print(f"housing envelope      {HOUSING_SIZE[0]:.1f} x {HOUSING_SIZE[1]:.1f} x {HOUSING_SIZE[2]:.1f}"
          f"  (roller rim at u {ROLLER_RIM_U:.1f})")
