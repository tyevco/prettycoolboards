/*
 * The USB device (see usb.h), after hid8k's usb_device.c and Zephyr's samples/subsys/usb/common.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/atomic.h>
#include <zephyr/usb/usbd.h>

#include "service.h"
#include "tb/budget.h"
#include "usb.h"

LOG_MODULE_REGISTER(tb_usb, LOG_LEVEL_INF);

USBD_DEVICE_DEFINE(tb_usbd, DEVICE_DT_GET(DT_NODELABEL(zephyr_udc0)), CONFIG_BRINGUP_USB_VID,
		   CONFIG_BRINGUP_USB_PID);

USBD_DESC_LANG_DEFINE(tb_lang);
USBD_DESC_MANUFACTURER_DEFINE(tb_mfr, "PrettyCool Boards (bench)");
USBD_DESC_PRODUCT_DEFINE(tb_product, "kbd testbed rev A bring-up");
IF_ENABLED(CONFIG_HWINFO, (USBD_DESC_SERIAL_NUMBER_DEFINE(tb_sn)));

USBD_DESC_CONFIG_DEFINE(tb_fs_cfg_desc, "FS Configuration");
USBD_DESC_CONFIG_DEFINE(tb_hs_cfg_desc, "HS Configuration");

/* Bus-powered, bMaxPower 250 x 2 mA = 500 mA (SPEC §3.2): the budget after SET_CONFIGURATION. */
USBD_CONFIGURATION_DEFINE(tb_fs_config, 0, 250, &tb_fs_cfg_desc);
USBD_CONFIGURATION_DEFINE(tb_hs_config, 0, 250, &tb_hs_cfg_desc);

static atomic_t hs;
static atomic_t config_value;

/* Runs in the system work queue (CONFIG_USBD_MSG_DEFERRED_MODE): never block here, post to the service. */
static void msg_cb(struct usbd_context *const ctx, const struct usbd_msg *const msg)
{
	switch (msg->type) {
	case USBD_MSG_CONFIGURATION:
		atomic_set(&config_value, msg->status);
		atomic_set(&hs, usbd_bus_speed(ctx) == USBD_SPEED_HS);
		tb_service_usb(TB_USB_EV_CONFIGURED, (uint32_t)msg->status);
		break;
	case USBD_MSG_RESET:
		atomic_set(&config_value, 0);
		tb_service_usb(TB_USB_EV_RESET, 0);
		break;
	case USBD_MSG_SUSPEND:
		tb_service_usb(TB_USB_EV_SUSPEND, 0);
		break;
	case USBD_MSG_RESUME:
		tb_service_usb(TB_USB_EV_RESUME, 0);
		break;
	case USBD_MSG_VBUS_REMOVED:
		tb_service_usb(TB_USB_EV_DISCONNECTED, 0);
		break;
	case USBD_MSG_UDC_ERROR:
	case USBD_MSG_STACK_ERROR:
		LOG_WRN("USB %s %d", usbd_msg_type_string(msg->type), msg->status);
		break;
	default:
		break;
	}
}

bool tb_usb_high_speed(void)
{
	return atomic_get(&hs) != 0;
}

uint8_t tb_usb_config_value(void)
{
	return (uint8_t)atomic_get(&config_value);
}

static int add_config(enum usbd_speed speed, struct usbd_config_node *cfg)
{
	int err = usbd_add_configuration(&tb_usbd, speed, cfg);

	err = err ? err : usbd_register_all_classes(&tb_usbd, speed, 1, NULL);
	/* CDC ACM has an Interface Association Descriptor: the IAD class code triple. */
	return err ? err : usbd_device_set_code_triple(&tb_usbd, speed, USB_BCC_MISCELLANEOUS, 0x02, 0x01);
}

int tb_usb_init(void)
{
	int err;

	err = usbd_add_descriptor(&tb_usbd, &tb_lang);
	err = err ? err : usbd_add_descriptor(&tb_usbd, &tb_mfr);
	err = err ? err : usbd_add_descriptor(&tb_usbd, &tb_product);
	IF_ENABLED(CONFIG_HWINFO, (err = err ? err : usbd_add_descriptor(&tb_usbd, &tb_sn);))
	if (err != 0) {
		return err;
	}
	if (USBD_SUPPORTS_HIGH_SPEED && usbd_caps_speed(&tb_usbd) == USBD_SPEED_HS) {
		err = add_config(USBD_SPEED_HS, &tb_hs_config);
		if (err != 0) {
			return err;
		}
	}
	err = add_config(USBD_SPEED_FS, &tb_fs_config);
	if (err != 0) {
		return err;
	}
	usbd_self_powered(&tb_usbd, false);
	err = usbd_msg_register_cb(&tb_usbd, msg_cb);
	err = err ? err : usbd_init(&tb_usbd);
	if (err != 0) {
		return err;
	}
	/* This board does not sense VBUS (SPEC §5.2): it runs from it, so the bus is there. */
	return usbd_can_detect_vbus(&tb_usbd) ? 0 : usbd_enable(&tb_usbd);
}
