/* Station 1 (Android): uinput touchpad daemon.
 *
 * Creates a virtual relative mouse (/dev/uinput) and exposes a tiny TCP
 * protocol on :8097:
 *   m:dx,dy   - move the system cursor by dx,dy pixels
 *   click     - left click
 *   rclick    - right click
 *   scroll:N  - vertical wheel
 *   ping      - pong
 * Every command is answered with "ok\n" (or "pong\n").
 */
#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <linux/uinput.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>

#define PORT 8097

static int ufd = -1;

static void emit(int type, int code, int value) {
    struct input_event ev;
    memset(&ev, 0, sizeof(ev));
    ev.type = type;
    ev.code = code;
    ev.value = value;
    if (ufd >= 0) {
        (void)write(ufd, &ev, sizeof(ev));
    }
}

static void syn(void) {
    emit(EV_SYN, SYN_REPORT, 0);
}

static int create_mouse(void) {
    ufd = open("/dev/uinput", O_WRONLY | O_NONBLOCK);
    if (ufd < 0) {
        perror("open /dev/uinput");
        return -1;
    }
    ioctl(ufd, UI_SET_EVBIT, EV_KEY);
    ioctl(ufd, UI_SET_EVBIT, EV_REL);
    ioctl(ufd, UI_SET_EVBIT, EV_SYN);
    ioctl(ufd, UI_SET_KEYBIT, BTN_LEFT);
    ioctl(ufd, UI_SET_KEYBIT, BTN_RIGHT);
    ioctl(ufd, UI_SET_RELBIT, REL_X);
    ioctl(ufd, UI_SET_RELBIT, REL_Y);
    ioctl(ufd, UI_SET_RELBIT, REL_WHEEL);

    struct uinput_user_dev uidev;
    memset(&uidev, 0, sizeof(uidev));
    snprintf(uidev.name, UINPUT_MAX_NAME_SIZE, "Station Touchpad");
    uidev.id.bustype = BUS_USB;
    uidev.id.vendor = 0x1234;
    uidev.id.product = 0x567d;
    uidev.id.version = 1;
    if (write(ufd, &uidev, sizeof(uidev)) < 0) {
        perror("write uidev");
        return -1;
    }
    if (ioctl(ufd, UI_DEV_CREATE) < 0) {
        perror("UI_DEV_CREATE");
        return -1;
    }
    fprintf(stderr, "touchpad: virtual mouse created\n");
    return 0;
}

static void answer(int fd, const char *text) {
    (void)write(fd, text, strlen(text));
}

static void handle_line(int fd, const char *line) {
    int dx, dy, n;
    if (strcmp(line, "ping") == 0) {
        answer(fd, "pong\n");
    } else if (sscanf(line, "m:%d,%d", &dx, &dy) == 2) {
        if (dx) emit(EV_REL, REL_X, dx);
        if (dy) emit(EV_REL, REL_Y, dy);
        syn();
        answer(fd, "ok\n");
    } else if (strcmp(line, "click") == 0) {
        emit(EV_KEY, BTN_LEFT, 1);
        syn();
        emit(EV_KEY, BTN_LEFT, 0);
        syn();
        answer(fd, "ok\n");
    } else if (strcmp(line, "rclick") == 0) {
        emit(EV_KEY, BTN_RIGHT, 1);
        syn();
        emit(EV_KEY, BTN_RIGHT, 0);
        syn();
        answer(fd, "ok\n");
    } else if (sscanf(line, "scroll:%d", &n) == 1) {
        emit(EV_REL, REL_WHEEL, n);
        syn();
        answer(fd, "ok\n");
    } else {
        answer(fd, "ok\n");
    }
}

int main(void) {
    if (create_mouse() < 0) {
        return 1;
    }

    int srv = socket(AF_INET, SOCK_STREAM, 0);
    int one = 1;
    setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port = htons(PORT);
    if (bind(srv, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("bind");
        return 1;
    }
    listen(srv, 8);
    fprintf(stderr, "touchpad: listening on %d\n", PORT);

    for (;;) {
        int c = accept(srv, NULL, NULL);
        if (c < 0) {
            continue;
        }
        char buf[2048];
        size_t used = 0;
        for (;;) {
            ssize_t r = read(c, buf + used, sizeof(buf) - used - 1);
            if (r <= 0) {
                break;
            }
            used += (size_t)r;
            buf[used] = 0;
            char *start = buf;
            char *nl;
            while ((nl = strchr(start, '\n')) != NULL) {
                *nl = 0;
                if (*start) {
                    handle_line(c, start);
                }
                start = nl + 1;
            }
            size_t left = strlen(start);
            memmove(buf, start, left);
            used = left;
            if (used >= sizeof(buf) - 2) {
                used = 0;
            }
        }
        close(c);
    }
    return 0;
}
