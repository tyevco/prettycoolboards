/*
 * hid8k: the USB device.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#ifndef HID8K_USB_DEVICE_H_
#define HID8K_USB_DEVICE_H_

#include <zephyr/usb/usbd.h>

enum hid8k_usb_state {
	HID8K_USB_DEFAULT = 0,
	HID8K_USB_ADDRESSED,
	HID8K_USB_CONFIGURED,
	HID8K_USB_SUSPENDED,
};

/* The device context, available before hid8k_usb_init() (it is statically defined). */
struct usbd_context *hid8k_usbd_context(void);

/* Add descriptors and configurations, register the classes, and initialize the stack. */
int hid8k_usb_init(void);

/* Connect to the bus (or wait for VBUS, if the controller reports it). */
int hid8k_usb_enable(void);

enum hid8k_usb_state hid8k_usb_state(void);

#endif /* HID8K_USB_DEVICE_H_ */
