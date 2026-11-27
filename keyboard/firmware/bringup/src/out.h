/*
 * Machine-readable output lines (PROTOCOL.md): "@tb <record> key=value ...".
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#ifndef TB_OUT_H_
#define TB_OUT_H_

#include <zephyr/shell/shell.h>

#define TB_PROTO_VERSION 1

/* One record line on the shell that runs the command. */
void tbo(const struct shell *sh, const char *fmt, ...) __printf_like(2, 3);
/* The last line of every command. err may be NULL. Returns rc, for "return tb_done(...)". */
int tb_done(const struct shell *sh, const char *cmd, int rc, const char *err);
/* A short token for a negative errno. */
const char *tb_errno_str(int rc);

#endif /* TB_OUT_H_ */
