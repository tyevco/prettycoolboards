/*
 * hid8k: the USB device, its descriptors and configurations.
 *
 * Follows samples/subsys/usb/common/sample_usbd_init.c (Zephyr v4.5.0), whose Kconfig options
 * are for in-tree samples only, so the VID, PID and strings here are this app's own.
 *
 * VID/PID: by default 0x1209:0x0001, the pid.codes test PID. It is reserved for private
 * testing, is not universally unique, and must not be used on any device that is
 * redistributed, sold or manufactured. This firmware is for the bench only.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/atomic.h>
#include <zephyr/sys/printk.h>
#include <zephyr/usb/usbd.h>

#include "hid8k.h"
#include "usb_device.h"

LOG_MODULE_REGISTER(hid8k_usb, LOG_LEVEL_INF);

USBD_DEVICE_DEFINE(hid8k_usbd, DEVICE_DT_GET(DT_NODELABEL(zephyr_udc0)),
		   CONFIG_HID8K_USB_VID, CONFIG_HID8K_USB_PID);

USBD_DESC_LANG_DEFINE(hid8k_lang);
USBD_DESC_MANUFACTURER_DEFINE(hid8k_mfr, CONFIG_HID8K_USB_MANUFACTURER);
USBD_DESC_PRODUCT_DEFINE(hid8k_product, CONFIG_HID8K_USB_PRODUCT);
IF_ENABLED(CONFIG_HWINFO, (USBD_DESC_SERIAL_NUMBER_DEFINE(hid8k_sn)));

USBD_DESC_CONFIG_DEFINE(hid8k_fs_cfg_desc, "FS Configuration");
USBD_DESC_CONFIG_DEFINE(hid8k_hs_cfg_desc, "HS Configuration");

/*
 * Self-powered: on the bench the Nucleo is powered through its ST-LINK USB (the power-jumper
 * setting is not checked against the board manual here), not from the device port's VBUS.
 */
USBD_CONFIGURATION_DEFINE(hid8k_fs_config, USB_SCD_SELF_POWERED, CONFIG_HID8K_USB_MAX_POWER,
			  &hid8k_fs_cfg_desc);
USBD_CONFIGURATION_DEFINE(hid8k_hs_config, USB_SCD_SELF_POWERED, CONFIG_HID8K_USB_MAX_POWER,
			  &hid8k_hs_cfg_desc);

static atomic_t usb_state;
static atomic_t usb_state_before_suspend;

/*
 * Runs in the system work queue (CONFIG_USBD_MSG_DEFERRED_MODE), after the USB stack thread
 * has handled the event, so printk() here (deferred logging) never delays the stack.
 */
static void hid8k_usbd_msg_cb(struct usbd_context *const ctx, const struct usbd_msg *const msg)
{
	switch (msg->type) {
	case USBD_MSG_CONFIGURATION:
		atomic_set(&usb_state, msg->status != 0 ? HID8K_USB_CONFIGURED : HID8K_USB_ADDRESSED);
		printk("hid8k: configuration %d, %s speed\n", msg->status,
		       usbd_bus_speed(ctx) == USBD_SPEED_HS ? "high" : "full");
		break;
	case USBD_MSG_SUSPEND:
		if (atomic_get(&usb_state) != HID8K_USB_SUSPENDED) {
			atomic_set(&usb_state_before_suspend, atomic_get(&usb_state));
		}
		atomic_set(&usb_state, HID8K_USB_SUSPENDED);
		printk("hid8k: suspended\n");
		break;
	case USBD_MSG_RESUME:
		atomic_set(&usb_state, atomic_get(&usb_state_before_suspend));
		printk("hid8k: resumed\n");
		/* Refill the HID queue if a submit was skipped or refused while suspended. */
		hid8k_kick();
		break;
	case USBD_MSG_RESET:
		atomic_set(&usb_state, HID8K_USB_DEFAULT);
		break;
	case USBD_MSG_UDC_ERROR:
	case USBD_MSG_STACK_ERROR:
		printk("hid8k: USB %s %d\n", usbd_msg_type_string(msg->type), msg->status);
		break;
	default:
		break;
	}

	if (usbd_can_detect_vbus(ctx)) {
		if (msg->type == USBD_MSG_VBUS_READY && usbd_enable(ctx) != 0) {
			LOG_ERR("Failed to enable device support");
		}

		if (msg->type == USBD_MSG_VBUS_REMOVED && usbd_disable(ctx) != 0) {
			LOG_ERR("Failed to disable device support");
		}
	}
}

struct usbd_context *hid8k_usbd_context(void)
{
	return &hid8k_usbd;
}

enum hid8k_usb_state hid8k_usb_state(void)
{
	return (enum hid8k_usb_state)atomic_get(&usb_state);
}

static int add_config(const enum usbd_speed speed, struct usbd_config_node *const cfg)
{
	int err;

	err = usbd_add_configuration(&hid8k_usbd, speed, cfg);
	if (err != 0) {
		LOG_ERR("Failed to add %s configuration (%d)", speed == USBD_SPEED_HS ? "HS" : "FS",
			err);
		return err;
	}

	/* The HID and the CDC ACM function (its two interfaces under one IAD). */
	err = usbd_register_all_classes(&hid8k_usbd, speed, 1, NULL);
	if (err != 0) {
		LOG_ERR("Failed to register classes (%d)", err);
		return err;
	}

	/* CDC ACM has an Interface Association Descriptor: use the IAD class code triple. */
	return usbd_device_set_code_triple(&hid8k_usbd, speed, USB_BCC_MISCELLANEOUS, 0x02, 0x01);
}

int hid8k_usb_init(void)
{
	int err;

	err = usbd_add_descriptor(&hid8k_usbd, &hid8k_lang);
	err = err != 0 ? err : usbd_add_descriptor(&hid8k_usbd, &hid8k_mfr);
	err = err != 0 ? err : usbd_add_descriptor(&hid8k_usbd, &hid8k_product);
	IF_ENABLED(CONFIG_HWINFO, (err = err != 0 ? err : usbd_add_descriptor(&hid8k_usbd, &hid8k_sn);))
	if (err != 0) {
		LOG_ERR("Failed to add string descriptors (%d)", err);
		return err;
	}

	/* A high-speed configuration (the one under test), and the full-speed one the stack needs. */
	if (USBD_SUPPORTS_HIGH_SPEED && usbd_caps_speed(&hid8k_usbd) == USBD_SPEED_HS) {
		err = add_config(USBD_SPEED_HS, &hid8k_hs_config);
		if (err != 0) {
			return err;
		}
	} else {
		LOG_WRN("Controller is not high-speed capable: 8 kHz is impossible");
	}

	err = add_config(USBD_SPEED_FS, &hid8k_fs_config);
	if (err != 0) {
		return err;
	}

	usbd_self_powered(&hid8k_usbd, true);

	err = usbd_msg_register_cb(&hid8k_usbd, hid8k_usbd_msg_cb);
	if (err != 0) {
		LOG_ERR("Failed to register message callback (%d)", err);
		return err;
	}

	err = usbd_init(&hid8k_usbd);
	if (err != 0) {
		LOG_ERR("Failed to initialize device support (%d)", err);
		return err;
	}

	return 0;
}

int hid8k_usb_enable(void)
{
	if (usbd_can_detect_vbus(&hid8k_usbd)) {
		/* Enabled from the message callback when VBUS is seen. */
		return 0;
	}

	return usbd_enable(&hid8k_usbd);
}
