"""Cross-check of the behavioural TPS2553 model against TI's own PSpice transient model (SLVM425B).

TI's model is not in this repository (its header reserves all rights). `python keyboard/sim/vendor.py fetch` puts
a patched copy in ~/.cache/kbdsim (or $KBDSIM_CACHE); without it this test is skipped.
"""

import pytest

import bench_slot
import vendor


@pytest.mark.skipif(not vendor.available(), reason="TI's TPS2553 model not fetched (python keyboard/sim/vendor.py fetch)")
def test_tps2553_model_agrees_with_ti_model():
    """Enable into 47 uF with a constant 250 mA load (the slow case): TI's model at its own typical limit, and the
    behavioural model given that limit, spend about the same time in current limit (within 25 %)."""
    w = vendor.enable_into(47e-6, "cc", 0.25)
    i_ti, t_ti = vendor.limit_time(w)
    assert 0.27 < i_ti < 0.31                    # TI's model sits near Eq. 2's 292 mA at R_ILIM 90.9 k
    mine = bench_slot.tps2553_enable("3v3", "cc", soft="typ", i_os_a=i_ti, r_on="typ")
    assert mine["t_lim"] == pytest.approx(t_ti, rel=0.25)
    # and TI's model does not assert FAULT in this case (about 2.6 ms in limit, under its 7.5 ms typical deglitch)
    assert w["v(fault)"][w.scale > 0.2e-3].min() > 1.0
