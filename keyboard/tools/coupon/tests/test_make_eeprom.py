"""make_eeprom.py: images for every shipped descriptor, the Intel HEX and shell outputs, and its refusals."""

import json
import os

import pytest

import coupon_fixtures as F
import descriptor as D
import make_eeprom as ME
import rules as R
from coupon_fixtures import good_desc


def test_every_descriptor_makes_an_image(tmp_path):
    """Every shipped descriptor encodes into a valid image (the descriptor rules only; the generated boards are
    checked against their descriptors below)."""
    assert ME.main(["--out", str(tmp_path), "--serial", "1-2", "--git", "0123456789abcdef", "--no-board-check"]) == 0
    bins = sorted(p for p in os.listdir(tmp_path) if p.endswith(".bin"))
    boards = sorted(f[:-5] for f in os.listdir(ME.DESC_DIR) if f.endswith(".json"))
    assert bins == sorted(f"{b}-s{s:04d}.bin" for b in boards for s in (1, 2))
    for b in bins:
        img = (tmp_path / b).read_bytes()
        k = D.decode(img)
        assert k["serial"] == int(b[-8:-4]) and k["git"] == "0123456789abcdef"
        assert json.loads((tmp_path / b.replace(".bin", ".json")).read_text()) == k
        assert ME.read_intel_hex((tmp_path / b.replace(".bin", ".hex")).read_text()) == img
    assert ME.main(["--check", *[str(tmp_path / b) for b in bins]]) == 0


@pytest.mark.parametrize("board", R.generated_coupons())
def test_generated_board_agrees_with_its_descriptor(tmp_path, board):
    """make_eeprom.py with the board rules: a coupon's image is written only if its generated board agrees with its
    descriptor. A board generated before the key (D2 of 2026-11-27) or with a placeholder descriptor is an expected
    failure, named; it runs as an ordinary test once the board is rebuilt and the descriptor written."""
    if F.predates_the_key(board):
        pytest.xfail(f"{board} was generated before D2 of 2026-11-27 (J1 still has pin 39): rebuild it with "
                     "build.py and layout.py")
    if F.excused(board) and D.load_json(os.path.join(ME.DESC_DIR, f"{board}.json")).get("placeholder"):
        pytest.xfail(f"descriptors/{board}.json is still a placeholder: write it from the captured design")
    assert ME.main([board, "--out", str(tmp_path), "--git", "none"]) == 0


def test_placeholder_flag_and_refusal(tmp_path):
    assert ME.main(["coupon-tmr", "--out", str(tmp_path), "--git", "none"]) == 0
    assert "placeholder" in D.decode((tmp_path / "coupon-tmr-s0000.bin").read_bytes())["flags"]
    assert ME.main(["coupon-tmr", "--out", str(tmp_path), "--no-placeholder"]) == 1
    assert ME.main(["test-coupon", "--out", str(tmp_path), "--no-placeholder", "--git", "none"]) == 0


def test_no_placeholder_also_reads_the_flags(tmp_path):
    """`"flags": ["placeholder"]` marks a placeholder as well as `"placeholder": true` does."""
    ddir = tmp_path / "d"
    ddir.mkdir()
    d = good_desc() | {"board": "ph", "flags": ["placeholder"]}
    (ddir / "ph.json").write_text(json.dumps(d))
    args = ["--desc-dir", str(ddir), "--out", str(tmp_path), "--kicad-dir", str(tmp_path / "none")]
    assert ME.main(args) == 0
    assert ME.main(args + ["--no-placeholder"]) == 1


def test_refuses_a_descriptor_its_generated_board_contradicts(tmp_path):
    """With the board generated, the netlist rules run too: a descriptor whose `uses` the netlist contradicts is
    refused, although the descriptor-only rules pass it."""
    import coupon_fixtures as F
    import coupon_model as M
    kdir, ddir = tmp_path / "kicad", tmp_path / "d"
    (kdir / "fx").mkdir(parents=True)
    ddir.mkdir()
    F.write_net(M.board_files("fx", str(kdir))[0], F.good_spec())
    d = good_desc() | {"board": "fx"}
    d["uses"] = [u for u in d["uses"] if u != "IRQ_N"]
    d["devices"][0]["irq"] = "none"
    (ddir / "fx.json").write_text(json.dumps(d))
    base = ["--desc-dir", str(ddir), "--out", str(tmp_path / "o"), "--git", "none"]
    assert ME.main(base + ["--kicad-dir", str(tmp_path / "none")]) == 0     # descriptor rules alone pass it
    assert ME.main(base + ["--kicad-dir", str(kdir)]) == 1                  # the netlist does not
    assert ME.main(base + ["--kicad-dir", str(kdir), "--no-board-check"]) == 0


def test_refuses_a_descriptor_that_breaks_the_rules(tmp_path):
    ddir = tmp_path / "d"
    ddir.mkdir()
    d = good_desc()
    d["board"] = "bad"
    d["rails"]["+3V3"]["max_ma"] = 260                        # above the 250 mA rule, at the 256 mA trip
    (ddir / "bad.json").write_text(json.dumps(d))
    assert ME.main(["--desc-dir", str(ddir), "--out", str(tmp_path)]) == 1
    assert not (tmp_path / "bad-s0000.bin").exists()


def test_git_auto_resolves_or_marks_dirty():
    img, used = ME.build(good_desc() | {"git": "auto"}, "test-coupon")
    k = D.decode(img)
    assert len(used["git"]) in (0, 40)
    if used["git"]:
        assert k["git"] == used["git"][:16]


def test_shell_script_writes_whole_pages(tmp_path):
    img = D.encode(good_desc())
    lines = ME.shell_script(img, "coupon-s1").splitlines()
    writes = [ln.split() for ln in lines if ln.startswith("eeprom write")]
    assert len(writes) == 16
    for i, w in enumerate(writes):
        assert w[2] == "coupon-s1" and int(w[3], 16) == 16 * i and len(w) == 4 + 16
        # 3 arguments + 16 bytes = 19 <= CONFIG_SHELL_ARGC_MAX's default 20 (Zephyr v4.5.0 subsys/shell/Kconfig)
        assert len(w) - 1 <= 20
        assert bytes(int(b, 16) for b in w[4:]) == img[16 * i:16 * i + 16]


def test_intel_hex_checksums():
    text = ME.intel_hex(bytes(range(32)))
    assert text.splitlines()[-1] == ":00000001FF"
    assert ME.read_intel_hex(text) == bytes(range(32))


def test_parse_serials():
    assert ME.parse_serials("7") == [7]
    assert ME.parse_serials("1-3,9") == [1, 2, 3, 9]
    assert ME.parse_serials("0x10") == [16]
