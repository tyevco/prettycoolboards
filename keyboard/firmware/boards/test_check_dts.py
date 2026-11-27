"""Fault injection for check_dts.py: the generated board devicetree passes, and each mutation of it fails.

    source /root/zephyrproject/ENV.sh
    PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider keyboard/firmware/boards

Each mutation is one plausible generator or hand-edit mistake, applied to a copy of the committed
kbd_testbed_a.dts in a temporary directory; check_dts.py must exit 1 and name the problem. One more case breaks
gen_board.py itself in a scratch tree (the decimal ADC unit address it once had): gen_board.py --check still
passes there, because the files agree with the broken generator, and check_dts.py must fail.
"""
import os
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
DTS = HERE / "prettycool" / "kbd_testbed_a" / "kbd_testbed_a.dts"
CHECK = HERE / "check_dts.py"

pytestmark = pytest.mark.skipif(not os.environ.get("ZEPHYR_BASE"), reason="needs ZEPHYR_BASE (dtlib, SoC dtsi)")


def run_check(*args):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, str(CHECK), *map(str, args)], capture_output=True, text=True, env=env)


def test_generated_board_and_sim_pass():
    r = run_check("--sim")
    assert r.returncode == 0, r.stdout + r.stderr
    assert re.search(r"board: \d+ checks pass, 0 fail", r.stdout)
    assert re.search(r"sim: \d+ checks pass, 0 fail", r.stdout)


# (name, old text, new text, a substring the FAIL line must contain)
MUTATIONS = [
    ("decimal ADC unit address", "channel@10 {  /* PB1", "channel@16 {  /* PB1", "unit address is hex"),
    ("CS0/CS1 swapped", "cs-gpios = <&gpioe 6 GPIO_ACTIVE_LOW>, <&gpioe 1 GPIO_ACTIVE_LOW>",
     "cs-gpios = <&gpioe 1 GPIO_ACTIVE_LOW>, <&gpioe 6 GPIO_ACTIVE_LOW>", "nets.py says S1_CS0_N"),
    ("bus-switch polarity", "busen-gpios = <&u_exp1 10 GPIO_ACTIVE_LOW>",
     "busen-gpios = <&u_exp1 10 GPIO_ACTIVE_HIGH>", "expected active-low"),
    ("10 uA LSB on a slot monitor", "current-lsb-microamps = <11>", "current-lsb-microamps = <10>", "CAL 2133"),
    ("PLL1 N", "mul-n = <80>", "mul-n = <81>", "SPEC §8.1"),
    ("LSE enabled", "&clk_hsi48 {", '&clk_lse { status = "okay"; };\n&clk_hsi48 {', "clk_lse not enabled"),
    ("SPI2 cs-gpios", "&spi2 {", "&spi2 {\n\tcs-gpios = <&gpioe 6 GPIO_ACTIVE_LOW>;", "no cs-gpios"),
    ("enable rail on the wrong expander pin", "en-3v3-gpios = <&u_exp1 1 GPIO_ACTIVE_HIGH>",
     "en-3v3-gpios = <&u_exp1 6 GPIO_ACTIVE_HIGH>", "EN_5V_S2, nets.py says EN_3V3_S2"),
    ("alternate ADC channel", "3 2 12  3 4 20>", "3 2 12  3 4 19>", "alt-adc-channels"),
    ("USART1 TX on a slot-bus pin", "&usart1_tx_pa9 &usart1_rx_pa10", "&usart1_tx_pb6 &usart1_rx_pa10",
     "MCU_FUNC[PB6]"),
    ("expander address", "reg = <0x21>;", "reg = <0x23>;", "unknown to nets.EXPANDER_I2C"),
    ("INA226 shunt", "rshunt-micro-ohms = <240000>;", "rshunt-micro-ohms = <250000>;", "rshunt"),
    ("push-pull bus-recovery pin", "sda-gpios = <&gpiob 9 (GPIO_ACTIVE_HIGH | GPIO_OPEN_DRAIN)>",
     "sda-gpios = <&gpiob 9 GPIO_ACTIVE_HIGH>", "sda-gpios open drain"),
    ("lane on the wrong ADC channel", "io-channels = <&adc1 5>, <&adc1 6>", "io-channels = <&adc1 6>, <&adc1 5>",
     "nets.SLOT_MCU"),
]


@pytest.mark.parametrize("name,old,new,needle", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_mutation_fails(tmp_path, name, old, new, needle):
    text = DTS.read_text()
    assert old in text, f"mutation {name!r} no longer applies to the generated dts"
    bad = tmp_path / "mutated.dts"
    bad.write_text(text.replace(old, new, 1))
    r = run_check("--src", bad)
    assert r.returncode == 1, r.stdout + r.stderr
    fails = [line for line in r.stdout.splitlines() if "FAIL" in line]
    assert any(needle in line for line in fails), "\n".join(fails)


def test_timer_enabled_on_slot_lines(tmp_path):
    text = DTS.read_text()
    m = re.search(r"&timers1 \{.*?\n\};", text, re.S)
    bad = tmp_path / "mutated.dts"
    bad.write_text(text.replace(m.group(0), m.group(0).replace('status = "disabled"', 'status = "okay"')))
    r = run_check("--src", bad)
    assert r.returncode == 1
    assert "enabled node does not drive the direct slot line PE9" in r.stdout


def test_generator_bug_passes_its_own_check_but_not_this_one(tmp_path):
    tree = tmp_path / "repo"
    (tree / "keyboard" / "firmware").mkdir(parents=True)
    (tree / "keyboard" / "hardware" / "design").mkdir(parents=True)
    shutil.copytree(HERE, tree / "keyboard" / "firmware" / "boards")
    shutil.copy(REPO / "keyboard" / "hardware" / "design" / "nets.py", tree / "keyboard" / "hardware" / "design")
    gen = tree / "keyboard" / "firmware" / "boards" / "gen_board.py"
    src = gen.read_text()
    bug = src.replace('w(f"\\tchannel@{ch:x} {{  /* {pin} {net} */")', 'w(f"\\tchannel@{ch} {{  /* {pin} {net} */")')
    assert bug != src, "the injected generator bug no longer applies"
    gen.write_text(bug)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    assert subprocess.run([sys.executable, str(gen)], capture_output=True, env=env).returncode == 0
    own = subprocess.run([sys.executable, str(gen), "--check"], capture_output=True, text=True, env=env)
    assert own.returncode == 0, own.stderr      # the generator agrees with itself
    r = run_check("--src", tree / "keyboard" / "firmware" / "boards" / "prettycool" / "kbd_testbed_a" /
                  "kbd_testbed_a.dts")
    assert r.returncode == 1 and "unit address is hex" in r.stdout
