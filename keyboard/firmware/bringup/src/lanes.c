/*
 * Lane reads (see lanes.h).
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <zephyr/devicetree.h>
#include <zephyr/drivers/adc.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/logging/log.h>

#include "board.h"
#include "lanes.h"

LOG_MODULE_REGISTER(tb_lanes, LOG_LEVEL_INF);

static const struct device *const adcs[5] = {
	[1] = DEVICE_DT_GET(DT_NODELABEL(adc1)),
	[2] = DEVICE_DT_GET(DT_NODELABEL(adc2)),
	[4] = DEVICE_DT_GET(DT_NODELABEL(adc4)),
};

static int setup(uint8_t adc, uint8_t ch)
{
	struct adc_channel_cfg c = {
		.gain = ADC_GAIN_1,
		.reference = ADC_REF_INTERNAL,
		.acquisition_time = ADC_ACQ_TIME(ADC_ACQ_TIME_TICKS,
						 adc == 4 ? TB_ADC4_ACQ_TICKS : TB_ADC12_ACQ_TICKS),
		.channel_id = ch,
	};

	if (adc >= ARRAY_SIZE(adcs) || adcs[adc] == NULL || !device_is_ready(adcs[adc])) {
		return -ENODEV;
	}
	return adc_channel_setup(adcs[adc], &c);
}

int tb_lanes_init(void)
{
	int err = 0;

	for (int s = 1; s <= TB_SLOTS; s++) {
		uint8_t lane, adc, ch;

		for (int k = 0; k < 4; k++) {
			int e = adc_channel_setup_dt(&tb_slots[s - 1].lane[k]);

			if (e != 0) {
				LOG_ERR("S%d AN%d: channel setup %d", s, k, e);
				err = e;
			}
		}
		for (int i = 0; tb_slot_alt(s, i, &lane, &adc, &ch) == 0; i++) {
			int e = setup(adc, ch);

			if (e != 0) {
				LOG_ERR("S%d AN%u on ADC%u IN%u: channel setup %d", s, lane, adc, ch, e);
				err = e;
			}
		}
	}
	return err;
}

int tb_adc_read(uint8_t adc, uint8_t ch, int32_t *code, unsigned *bits)
{
	int16_t sample = 0;
	struct adc_sequence seq = {
		.channels = BIT(ch),
		.buffer = &sample,
		.buffer_size = sizeof(sample),
		.resolution = TB_ADC_RES_BITS(adc),
	};
	int err;

	if (adc >= ARRAY_SIZE(adcs) || adcs[adc] == NULL) {
		return -ENODEV;
	}
	err = setup(adc, ch);
	err = err ? err : adc_read(adcs[adc], &seq);
	*code = (uint16_t)sample;
	*bits = TB_ADC_RES_BITS(adc);
	return err;
}

int tb_lane_read(int slot, int lane, int32_t *code, unsigned *bits, uint8_t *adc, uint8_t *ch)
{
	const struct tb_slot_hw *h = tb_slot_hw(slot);
	const struct adc_dt_spec *spec;
	int16_t sample = 0;
	struct adc_sequence seq = {.buffer = &sample, .buffer_size = sizeof(sample)};
	int err;

	if (h == NULL || lane < 0 || lane > 3) {
		return -EINVAL;
	}
	spec = &h->lane[lane];
	err = adc_channel_setup_dt(spec);
	err = err ? err : adc_sequence_init_dt(spec, &seq);
	err = err ? err : adc_read_dt(spec, &seq);
	*code = (uint16_t)sample;
	*bits = spec->resolution;
	*adc = spec->dev == adcs[4] ? 4 : spec->dev == adcs[2] ? 2 : 1;
	*ch = spec->channel_id;
	return err;
}

int tb_vdda_mv(int32_t *mv)
{
#if DT_NODE_HAS_STATUS_OKAY(DT_NODELABEL(vref1))
	const struct device *dev = DEVICE_DT_GET(DT_NODELABEL(vref1));
	struct sensor_value v;
	int err;

	if (!device_is_ready(dev)) {
		return -ENODEV;
	}
	err = sensor_sample_fetch(dev);
	err = err ? err : sensor_channel_get(dev, SENSOR_CHAN_VOLTAGE, &v);
	*mv = v.val1 * 1000 + v.val2 / 1000;
	return err;
#elif defined(CONFIG_BRINGUP_SIM)
	*mv = TB_ADC_VREF_MV; /* the simulated board's VREF+ */
	return 0;
#else
	*mv = 0;
	return -ENODEV;
#endif
}

int tb_die_temp_mc(int32_t *mc)
{
#if DT_NODE_HAS_STATUS_OKAY(DT_NODELABEL(die_temp))
	const struct device *dev = DEVICE_DT_GET(DT_NODELABEL(die_temp));
	struct sensor_value v;
	int err;

	if (!device_is_ready(dev)) {
		return -ENODEV;
	}
	err = sensor_sample_fetch(dev);
	err = err ? err : sensor_channel_get(dev, SENSOR_CHAN_DIE_TEMP, &v);
	*mc = v.val1 * 1000 + v.val2 / 1000;
	return err;
#else
	*mc = 0;
	return -ENODEV;
#endif
}
