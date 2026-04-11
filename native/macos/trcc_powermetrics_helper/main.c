/*
 * Privileged helper: listens on a Unix socket, validates the client with
 * getpeereid(2), runs /usr/bin/powermetrics (no shell), returns framed stdout.
 *
 * Build (macOS): clang -O2 -Wall -Wextra -o trcc-powermetrics-helper main.c
 * Install binary to e.g. /Library/PrivilegedHelperTools/ and load the plist
 * from LaunchDaemons (see com.thermalright.trcc.powermetrics.plist).
 */
#include <arpa/inet.h>
#include <ctype.h>
#include <errno.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <unistd.h>

#define SOCK_PATH "/var/run/trcc-powermetrics.sock"
#define MAGIC "TRC1"
#define SAMPLERS_MAX 256
#define OUTPUT_MAX (2 * 1024 * 1024)

static void die(const char *fmt, ...) {
	va_list ap;
	va_start(ap, fmt);
	vfprintf(stderr, fmt, ap);
	va_end(ap);
	fputc('\n', stderr);
	exit(1);
}

static int valid_samplers(const char *s) {
	size_t i, n = strlen(s);
	if (n == 0 || n > SAMPLERS_MAX) {
		return 0;
	}
	for (i = 0; i < n; i++) {
		char c = s[i];
		if (!(isalnum((unsigned char)c) || c == ',' || c == '_')) {
			return 0;
		}
	}
	return 1;
}

static int write_all(int fd, const void *buf, size_t len) {
	const char *p = buf;
	while (len > 0) {
		ssize_t n = write(fd, p, len);
		if (n <= 0) {
			return -1;
		}
		p += n;
		len -= (size_t)n;
	}
	return 0;
}

#define SEND_ERR(fd, code, msg)                                               \
	do {                                                                  \
		const char *_em = (msg);                                      \
		(void)send_frame((fd), (code), _em, (uint32_t)strlen(_em));   \
	} while (0)

static int send_frame(int fd, uint32_t status, const void *body, uint32_t bodylen) {
	unsigned char hdr[12];
	memcpy(hdr, MAGIC, 4);
	uint32_t be_st = htonl(status);
	uint32_t be_ln = htonl(bodylen);
	memcpy(hdr + 4, &be_st, 4);
	memcpy(hdr + 8, &be_ln, 4);
	if (write_all(fd, hdr, 12) != 0) {
		return -1;
	}
	if (bodylen > 0 && write_all(fd, body, bodylen) != 0) {
		return -1;
	}
	return 0;
}

/* Allow normal login users (convention: UID >= 500). */
static int peer_allowed(int cfd) {
	uid_t uid = (uid_t)-1;
	gid_t gid = (gid_t)-1;
	if (getpeereid(cfd, &uid, &gid) != 0) {
		return 0;
	}
	return (uid_t)uid >= 500 && uid != (uid_t)-1;
}

static int read_line(int cfd, char *buf, size_t cap) {
	size_t i = 0;
	while (i + 1 < cap) {
		char ch;
		ssize_t r = read(cfd, &ch, 1);
		if (r <= 0) {
			return -1;
		}
		if (ch == '\n') {
			buf[i] = '\0';
			return 0;
		}
		buf[i++] = ch;
	}
	return -1;
}

static int run_powermetrics(const char *samplers, unsigned char **out, size_t *outlen) {
	int pipefd[2];
	if (pipe(pipefd) != 0) {
		return -1;
	}
	pid_t pid = fork();
	if (pid < 0) {
		close(pipefd[0]);
		close(pipefd[1]);
		return -1;
	}
	if (pid == 0) {
		close(pipefd[0]);
		if (dup2(pipefd[1], STDOUT_FILENO) < 0) {
			_exit(126);
		}
		close(pipefd[1]);
		execl("/usr/bin/powermetrics", "powermetrics",
		      "--samplers", samplers, "-n", "1", "-i", "100", "-f", "plist",
		      (char *)NULL);
		_exit(127);
	}
	close(pipefd[1]);
	unsigned char *buf = malloc(OUTPUT_MAX + 1);
	if (!buf) {
		close(pipefd[0]);
		waitpid(pid, NULL, 0);
		return -1;
	}
	size_t total = 0;
	for (;;) {
		ssize_t n = read(pipefd[0], buf + total, OUTPUT_MAX - total);
		if (n <= 0) {
			break;
		}
		total += (size_t)n;
		if (total > OUTPUT_MAX) {
			free(buf);
			close(pipefd[0]);
			waitpid(pid, NULL, 0);
			return -1;
		}
	}
	close(pipefd[0]);
	int st = 0;
	waitpid(pid, &st, 0);
	if (!WIFEXITED(st) || WEXITSTATUS(st) != 0) {
		free(buf);
		return -1;
	}
	*out = buf;
	*outlen = total;
	return 0;
}

static void handle_client(int cfd) {
	char samplers[SAMPLERS_MAX + 2];

	if (!peer_allowed(cfd)) {
		SEND_ERR(cfd, 1, "peer not authorized");
		return;
	}
	if (read_line(cfd, samplers, sizeof samplers) != 0) {
		SEND_ERR(cfd, 2, "bad request line");
		return;
	}
	if (!valid_samplers(samplers)) {
		SEND_ERR(cfd, 3, "invalid samplers");
		return;
	}
	unsigned char *raw = NULL;
	size_t rawlen = 0;
	if (run_powermetrics(samplers, &raw, &rawlen) != 0) {
		SEND_ERR(cfd, 4, "powermetrics failed");
		return;
	}
	(void)send_frame(cfd, 0, raw, (uint32_t)rawlen);
	free(raw);
}

int main(void) {
	struct sockaddr_un addr;
	int srv;

	(void)signal(SIGPIPE, SIG_IGN);

	unlink(SOCK_PATH);
	srv = socket(AF_UNIX, SOCK_STREAM, 0);
	if (srv < 0) {
		die("socket: %s", strerror(errno));
	}
	memset(&addr, 0, sizeof addr);
	addr.sun_family = AF_UNIX;
	strncpy(addr.sun_path, SOCK_PATH, sizeof addr.sun_path - 1);
	if (bind(srv, (struct sockaddr *)&addr, sizeof addr) != 0) {
		die("bind %s: %s", SOCK_PATH, strerror(errno));
	}
	(void)chmod(SOCK_PATH, 0666);
	if (listen(srv, 8) != 0) {
		die("listen: %s", strerror(errno));
	}

	for (;;) {
		int c = accept(srv, NULL, NULL);
		if (c < 0) {
			if (errno == EINTR) {
				continue;
			}
			sleep(1);
			continue;
		}
		handle_client(c);
		close(c);
	}
	/* not reached */
}
