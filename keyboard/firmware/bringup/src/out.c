/*
 * Machine-readable output lines (PROTOCOL.md).
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <errno.h>
#include <stdarg.h>
#include <stdio.h>

#include "out.h"

void tbo(const struct shell *sh, const char *fmt, ...)
{
	char line[200];
	va_list ap;

	va_start(ap, fmt);
	vsnprintf(line, sizeof(line), fmt, ap);
	va_end(ap);
	shell_fprintf(sh, SHELL_NORMAL, "@tb %s\n", line);
}

const char *tb_errno_str(int rc)
{
	switch (rc) {
	case 0: return "ok";
	case -EIO: return "io";
	case -EINVAL: return "inval";
	case -EPERM: return "perm";
	case -ENODEV: return "nodev";
	case -EBUSY: return "busy";
	case -EACCES: return "acces";
	case -ENOENT: return "noent";
	case -ETIMEDOUT: return "timedout";
	case -EAGAIN: return "again";
	case -ENOTSUP: return "notsup";
	case -ENOSPC: return "nospc";
	case -EEXIST: return "exist";
	case -EALREADY: return "already";
	default: return "error";
	}
}

int tb_done(const struct shell *sh, const char *cmd, int rc, const char *err)
{
	if (err == NULL && rc < 0) {
		err = tb_errno_str(rc);
	}
	if (err != NULL) {
		shell_fprintf(sh, SHELL_NORMAL, "@tb done cmd=%s rc=%d err=%s\n", cmd, rc, err);
	} else {
		shell_fprintf(sh, SHELL_NORMAL, "@tb done cmd=%s rc=%d\n", cmd, rc);
	}
	return rc;
}
