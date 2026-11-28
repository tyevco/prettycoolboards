"""tbbench: the bring-up bench harness for the PrettyCool Keyboard rev A testbed (keyboard/tools/bench/README.md).

It drives the bring-up firmware's shell protocol (keyboard/firmware/bringup/PROTOCOL.md, version 1) through SPEC
section 10's bring-up order, judges every reading against limits taken from SPEC and nets.py, stops safely on the
first dangerous failure, and writes a JSON and a Markdown report per run.

It walks stage A1 (the owner's decision D1 of 2026-11-27): the motherboard, then the test coupon in every slot,
then the Hall-effect coupon.

Status (2026-11-28): written and tested against simulated boards only (tbbench.simdev, and the firmware itself on
native_sim when that build is present). No testbed exists yet, so no run of this harness has touched hardware.
"""

__version__ = "0.2.0"
PROTOCOL_VERSION = 1
