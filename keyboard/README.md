# PrettyCool Keyboard (working name)

A planned analog keyboard designed as code: one layout file in, a gated, JLC-assembled board, case and firmware out.
The plan: keys that also point, and controls that change how they feel to suit what you are doing.

> **Status (2026-11-26): concept.** Nothing is designed, built or measured. This folder holds the research, the
> feature roadmap the owner chose on 2026-11-25, and the rev A MCU the owner chose on 2026-11-26
> ([decision record](docs/mcu.md)). There are no schematics, boards or firmware yet; the testbed's
> [SPEC](hardware/design/SPEC.md) is a draft on paper. Every part, figure and claim on these pages is a candidate from
> desk research, to be checked on the rev A testbed.

## Concept renders

Concept sketches from rough build123d models, with illustrative geometry: they show the ideas, not a design, and each
one carries a CONCEPT SKETCH stamp. The [concept renders page](hardware/concept/README.md) has every render and
figure, and the **[3D gallery](https://tyevco.github.io/prettycoolboards/keyboard/gallery/)** has the models to
rotate.

| | |
|---|---|
| ![Two keyboard halves seen from the front at an angle, each with a concave, tented keywell of six columns by three rows and a curved thumb arc; the F, J and thumb home keys are blue, and an orange thumb roller sits beside the left thumb keys](hardware/concept/renders/keyboard_assembly.png) | ![Concept sketch of a green motherboard on standoffs with coupon boards plugged in: Hall-effect and TMR coupons with four keys each, a shear coupon with two blue keys, a coil coupon with copper spirals, a haptics coupon with a roller and coin LRA, and a translucent optional KVM coupon](hardware/concept/renders/testbed_assembly.png) |
| *Rev B as sketched: a generated keywell per half (the sketch tents it about 18°, an illustrative constant), a thumb arc, and one haptic thumb wheel (drawn on the left half; which half is not decided). Blue: the shear keys* | *Rev A, the testbed: one motherboard and a plug-in coupon per sensing method. Board size, connector and layout are illustrative; the optional KVM coupon is drawn as a ghost* |
| ![Half-section of a custom key switch with a blue keycap: an orange carrier cup hangs from the housing roof on slender posts, and the stem and its magnet slide inside it over a TMAG5170 sensor on the PCB; arrows mark the press and the two sideways pushes](hardware/concept/renders/mech_shear_key_cutaway.png) | ![Left half exploded into labelled layers: keycaps, magnetic switches (Hall-effect or TMR: rev A decides), the printed top shell, bent column boards and a thumb board, the wheel module, the main board, a battery and coin LRA, and the floor](hardware/concept/renders/keyboard_half_exploded.png) |
| *A shear key, one way it could work: the stem slides inside a carrier hung on flexure posts, so a sideways push moves its magnet over a TMAG5170 3-axis Hall sensor* | *The left half's parts stack. Sizes are placeholders, and the switches are drawn socketless, though hot-swap is still an open question ([concept §9](docs/concept.md#_9-open-questions))* |

## The idea in one table

| | |
|---|---|
| What it is not | Another Hall-effect gaming board. Adjustable actuation, rapid trigger, 8 kHz polling, SOCD and browser configurators are now table stakes ([research](docs/research.md#what-no-longer-differentiates)) |
| What it is | A planned integration that the desk research found in no single product or project (four of the five sceptics could not search the web): keys that point (shear keys), a profile-driven haptic thumb wheel, two wired hosts at once, a firmware that explains and tunes its own tap/hold decisions, and a layout compiler whose releases are gated on wiring, DRC, placement, latency and battery life |
| Priorities | All four, by owner decision: daily driver (programming), gaming / performance, ergonomics, and a showcase for the toolchain |
| Form factor | Open: the features decide. The roadmap points to a split with a generated keywell |
| Ambition | Moonshot: novel sensing and mechanics that may take several revisions, but it must end up a usable daily driver |

## Decisions so far (owner, 2026-11-25 and 2026-11-26)

| Question | Decision |
|---|---|
| Form factor | Open, let the features decide |
| Priorities | Daily driver, gaming, ergonomics, toolchain showcase (all four) |
| Switch technology | Undecided: the rev A testbed compares Hall-effect, TMR, 3-axis Hall and printed inductive coils |
| Ambition | Moonshot |
| Headline hardware | Shear keys, a generated keywell, a haptic thumb wheel, analog sensing from stock switches (all four) |
| Daily-driver features | Two-host KVM, tap/hold flight recorder and tuner, context-aware feel, per-finger analog tuning (all four) |
| Showcase features | Keyboard compiler, latency and battery gates, sensing testbed, fit to your hand (all four) |
| Staging | **Testbed first**: rev A proves the sensing and the compiler on coupons; the keyboard is rev B |
| Firmware | **Custom firmware on Zephyr**, with ZMK-compatible keymap files where possible |
| Platform (MCU) | Rev A: chosen (the next row). Rev B: **the testbed decides.** Rev A measures the sensors' real current; a battery-budget gate picks the rev B chip |
| Rev A MCU: STM32U5A5 (2026-11-26) | **STM32U5A5** (STM32U5A5VJT6, LQFP100, JLC C22455480) on the motherboard, with bring-up on the NUCLEO-U5A5ZJ-Q: of the stocked parts found with a high-speed USB PHY on chip and upstream Zephyr support for it, the one with the strongest analog. Fallback: the NXP i.MX RT1021. The AT32F405, the candidate until then, was dropped for having no upstream Zephyr. Before the schematic: reserve the MCUs, and prove 8 kHz HID on the Nucleo ([decision record](docs/mcu.md)) |
| Rev B side track (2026-11-26) | An nRF54LM20 dev kit (XIAO nRF54LM20A or nRF54LM20 DK) measures 8 kHz HID together with BLE, and the radio current, for the battery gate. The nRF54LM20A is the rev B front-runner; the gate still decides |
| Testbed form | **A motherboard plus plug-in coupons**, each coupon generated by the compiler |

The twelve chosen features in the three groups above:

```mermaid
---
config:
  # the docs theme sets p { line-height: 28px }, which would clip the labels mermaid measured at 1.5;
  # mermaid only colours the root's and the third branch's HTML labels, so the other branches would take the
  # page's text colour, which is light grey on these pastel fills in dark mode
  themeCSS: "p { line-height: inherit; } .mindmap-node .nodeLabel { color: #1a1a1a; }"
  themeVariables:
    git0: "#c3cbf2"
    gitBranchLabel0: "#1a1a1a"
    cScale1: "#a8dcc8"
    cScaleLabel1: "#1a1a1a"
    cScale2: "#f5c9a0"
    cScaleLabel2: "#1a1a1a"
    cScale3: "#cfc2f2"
    cScaleLabel3: "#1a1a1a"
---
mindmap
  root((The 12 chosen<br/>features))
    Headline hardware
      Shear keys
      Generated keywell
      Haptic thumb wheel
      Analog from stock switches
    Daily driver
      Two-host KVM
      Tap/hold flight recorder
      Context-aware feel
      Per-finger analog tuning
    Showcase
      Keyboard compiler
      Latency and battery gates
      Sensing testbed
      Fit to your hand
```

*The twelve features the owner chose on 2026-11-25: headline hardware, daily driver and showcase. It is a plan; none
of them is built.*

## Roadmap

| Rev | What | Proves |
|---|---|---|
| **A: testbed** | Motherboard (STM32U5A5 with high-speed USB, power, the latency rig's hooks) plus plug-in coupons: Hall-effect, TMR, 3-axis shear sites, printed coils, compliant-stop aftertouch, haptic wheel driver and LRA. A key-injector rig for latency. Compiler v0, which generates the coupons | Which sensing to build on, the sensors' real current, shear signal on a centring stem, whether coils can read a stock MX spring, the wheel's power, and the compiler's first gated boards |
| **B: keyboard** | A compiler-generated split with rigid column boards in a generated keywell case, fitted from S/M/L presets or measurements. The winning sensing, shear on 2–4 keys, the thumb wheel, two-host KVM, and the firmware features | A daily driver |
| **C** | A flex keywell, a phone-photo fit, and analog from stock switches if the rev A coil coupon shows a usable signal | The moonshots that survive rev A |

The same staging with its go/no-go points:

```mermaid
---
config:
  # the docs theme sets p { line-height: 28px }, which would clip the labels mermaid measured at 1.5
  themeCSS: "p { line-height: inherit; }"
  flowchart:
    wrappingWidth: 400
---
flowchart TB
  A["Rev A: testbed<br/>STM32U5A5 motherboard<br/>+ plug-in coupons<br/>latency rig, compiler v0"]
  GA{"Gate A<br/>rev A done?"}
  CK["Rev A is done when:<br/>- each coupon: measured current and noise<br/>- coil coupon: yes or no on stock springs<br/>- shear coupon: can a centring stem point?<br/>- wheel: measured peak and average current<br/>- battery gate picks the rev B chip<br/>- compiler generated and gated every coupon"]:::note
  B["Rev B: keyboard<br/>generated split, rigid column boards<br/>winning sensing, shear on 2–4 keys<br/>thumb wheel, two-host KVM"]
  CX["coils dropped"]
  GB{"Gate B<br/>daily driver?"}
  FLEX["flex only after the<br/>bent-state gate works"]:::note
  C["Rev C: the moonshots that survive<br/>flex keywell, phone-photo fit,<br/>analog from stock switches"]

  A --> GA
  CK -.- GA
  GA -->|"go"| B
  GA -->|"coil coupon: no"| CX
  GA -->|"coil coupon: yes"| C
  B --> GB
  GB -->|"go"| C
  FLEX -.- C

  classDef note text-align:left,stroke-dasharray:4 3
```

*Concept sketch of the staging. Rev A must meet every "done when" item in [concept §7](docs/concept.md#_7-rev-a-testbed)
before rev B starts, and the coil coupon alone decides whether analog from stock switches reaches rev C. Rev B has no
written exit criteria yet, so the B gate only restates the roadmap's "a daily driver" and §8's rule that flex waits
for the bent-state gate.*

And where each chosen feature would land, rev by rev:

```mermaid
---
config:
  # the docs theme sets p { line-height: 28px }, which would clip the labels mermaid measured at 1.5
  themeCSS: "p { line-height: inherit; }"
---
flowchart LR
  subgraph RA["Rev A: testbed"]
    direction TB
    a1["shear coupon"]
    a2["wheel + LRA coupon"]
    a3["coil coupon"]
    a4["KVM coupon, if it fits"]
    a5["compiler v0"]
    a6["latency + battery gates"]
    a7["recorder, tuning data"]
  end
  subgraph RB["Rev B: keyboard"]
    direction TB
    b1["shear on 2–4 keys"]
    b2["thumb wheel, profiles"]
    b3["rigid-column keywell"]
    b4["two-host KVM"]
    b5["full compiler"]
    b6["gates on every release"]
    b7["firmware features"]
    b8["S/M/L fit presets"]
  end
  subgraph RC["Rev C"]
    direction TB
    c1["analog from<br/>stock switches"]
    c2["flex keywell"]
    c3["phone-photo fit"]
  end
  a1 --> b1
  a2 --> b2
  a4 --> b4
  a5 --> b5
  a6 --> b6
  a7 --> b7
  a3 -->|"if usable"| c1
  b3 --> c2
  b8 --> c3
```

*Concept sketch of how each chosen feature moves from a rev A coupon to rev B and rev C, following the Stage lines in
[concept.md](docs/concept.md). Nothing here is built.*

## Documentation

| Document | Contents |
|---|---|
| [docs/concept.md](docs/concept.md) | The chosen features: what each one is, what already exists, the risks, and where it lands in the roadmap. The platform and firmware decisions, the conflicts between features, the rev A testbed |
| [docs/mcu.md](docs/mcu.md) | The rev A MCU decision record (2026-11-26): the requirements, the ranked candidates, why the AT32F405 was dropped, the conditions before the schematic, the bring-up risks, the rev B side track, sources |
| [hardware/design/SPEC.md](hardware/design/SPEC.md) | The rev A testbed's draft architecture of record, on paper |
| [docs/research.md](docs/research.md) | The landscape (late 2026), what no longer differentiates, the ideas the owner did not pick, with the sceptic's score and case, the method and its caveats, sources; an addendum on the MCU research of 2026-11-26 |
| [hardware/concept/README.md](hardware/concept/README.md) | Concept renders: every concept sketch, model-estimate plot and research figure in one place, with captions and the commands that regenerate them |
