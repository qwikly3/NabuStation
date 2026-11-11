/* Station 1 (Android): rotary encoder + Alice button daemon.
 *
 * GPIO 32/33 = quadrature encoder, GPIO 235 = Alice button (active low).
 * Steps move an absolute volume position (0..POS_MAX) mapped to the
 * TAS5751M mixer (350..850, 0.125 dB steps). Every TCP connection to
 * :8095 returns "1" if the button was pressed since the last poll,
 * otherwise "0" (the HA voice service polls it, same as on Debian).
 *
 * This build reopens the sysfs GPIO descriptors periodically because the
 * vendor platform services can invalidate long-lived value fds, and logs
 * raw transitions to /data/voice/gpio-dial.log for diagnostics.
 */

#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>

#define GPIO_A 32
#define GPIO_B 33
#define GPIO_BTN 235
#define PORT 8095
#define PRESS_PORT 8094
#define POS_MAX_DEFAULT 336
#define AMP_MIN 350
#define AMP_MAX 850

static int pos_max = POS_MAX_DEFAULT;
static FILE *lg = NULL;

static void logmsg(const char *fmt, ...) {
    if (!lg) return;
    time_t t = time(NULL);
    struct tm tmv;
    localtime_r(&t, &tmv);
    fprintf(lg, "[%02d:%02d:%02d] ", tmv.tm_hour, tmv.tm_min, tmv.tm_sec);
    va_list ap;
    va_start(ap, fmt);
    vfprintf(lg, fmt, ap);
    va_end(ap);
    fputc('\n', lg);
    fflush(lg);
}

static long now_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000L + ts.tv_nsec / 1000000L;
}

static int gpio_export(int n) {
    char path[64];
    snprintf(path, sizeof(path), "/sys/class/gpio/gpio%d", n);
    if (access(path, F_OK) == 0) return 0;
    int fd = open("/sys/class/gpio/export", O_WRONLY);
    if (fd < 0) return -1;
    char buf[16];
    int len = snprintf(buf, sizeof(buf), "%d", n);
    (void)write(fd, buf, len);
    close(fd);
    return 0;
}

static void gpio_in(int n) {
    char path[64];
    snprintf(path, sizeof(path), "/sys/class/gpio/gpio%d/direction", n);
    int fd = open(path, O_WRONLY);
    if (fd < 0) return;
    (void)write(fd, "in", 2);
    close(fd);
}

static int gpio_open(int n) {
    char path[64];
    snprintf(path, sizeof(path), "/sys/class/gpio/gpio%d/value", n);
    return open(path, O_RDONLY);
}

/* (Re)export the pins, force input mode and open fresh value descriptors. */
static void open_gpios(int *fa, int *fb, int *fbtn) {
    int pins[3] = {GPIO_A, GPIO_B, GPIO_BTN};
    for (int i = 0; i < 3; i++) {
        gpio_export(pins[i]);
        gpio_in(pins[i]);
    }
    *fa = gpio_open(GPIO_A);
    *fb = gpio_open(GPIO_B);
    *fbtn = gpio_open(GPIO_BTN);
}

static int gpio_read(int fd) {
    char buf[8];
    if (fd < 0) return -1;
    int r = pread(fd, buf, sizeof(buf) - 1, 0);
    if (r <= 0) {
        if (lseek(fd, 0, SEEK_SET) < 0) return -1;
        r = read(fd, buf, sizeof(buf) - 1);
    }
    if (r <= 0) return -1;
    return buf[0] == '1';
}

static int amp_value(int pos) {
    return AMP_MIN + (AMP_MAX - AMP_MIN) * pos / pos_max;
}

static int last_vol = -1;

static void set_vol(int v) {
    if (v == last_vol) return;
    last_vol = v;
    char cmd[320];
    snprintf(cmd, sizeof(cmd),
             "tinymix -D 1 'Subwoofer Master Playback Volume' %d >/dev/null 2>&1; "
             "tinymix -D 1 'Tweeters Master Playback Volume' %d >/dev/null 2>&1",
             v, v);
    (void)system(cmd);
}

int main(void) {
    lg = fopen("/data/voice/gpio-dial.log", "a");
    logmsg("=== start pid=%d ===", getpid());

    int fa, fb, fbtn;
    open_gpios(&fa, &fb, &fbtn);
    if (fa < 0 || fb < 0) {
        logmsg("cannot open encoder gpios fa=%d fb=%d", fa, fb);
        fprintf(stderr, "cannot open encoder gpios\n");
        return 1;
    }
    logmsg("fds a=%d b=%d btn=%d", fa, fb, fbtn);

    int srv = socket(AF_INET, SOCK_STREAM, 0);
    int one = 1;
    setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port = htons(PORT);
    if (bind(srv, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        logmsg("bind failed errno=%d", errno);
        perror("bind");
        return 1;
    }
    listen(srv, 8);
    fcntl(srv, F_SETFL, fcntl(srv, F_GETFL) | O_NONBLOCK);

    int press_srv = socket(AF_INET, SOCK_STREAM, 0);
    setsockopt(press_srv, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    struct sockaddr_in paddr;
    memset(&paddr, 0, sizeof(paddr));
    paddr.sin_family = AF_INET;
    paddr.sin_addr.s_addr = INADDR_ANY;
    paddr.sin_port = htons(PRESS_PORT);
    if (bind(press_srv, (struct sockaddr *)&paddr, sizeof(paddr)) < 0) {
        logmsg("press bind failed errno=%d", errno);
    } else {
        listen(press_srv, 4);
        fcntl(press_srv, F_SETFL, fcntl(press_srv, F_GETFL) | O_NONBLOCK);
    }

    int pos = pos_max / 2;
    FILE *mf = fopen("/data/voice/dial_max", "r");
    if (mf) {
        int m = 0;
        if (fscanf(mf, "%d", &m) == 1 && m > 10 && m < 2000) pos_max = m;
        fclose(mf);
        pos = pos_max / 2;
    }
    FILE *pf = fopen("/data/voice/dial_pos", "r");
    if (pf) {
        if (fscanf(pf, "%d", &pos) != 1) pos = pos_max / 2;
        fclose(pf);
    }
    if (pos < 0) pos = 0;
    if (pos > pos_max) pos = pos_max;
    set_vol(amp_value(pos));
    logmsg("pos=%d max=%d vol=%d", pos, pos_max, amp_value(pos));

    static const int8_t qtab[16] = {
        0, -1, 1, 0,
        1, 0, 0, -1,
        -1, 0, 0, 1,
        0, 1, -1, 0,
    };

    int a = gpio_read(fa), b = gpio_read(fb);
    int prev = ((a > 0) << 1) | (b > 0);
    int prev_btn = fbtn >= 0 ? gpio_read(fbtn) : 1;
    int prev_btn_raw = prev_btn;
    int pressed = 0;
    long last_save = now_ms();
    long last_reopen = now_ms();
    long last_err_log = 0;

    for (;;) {
        long loop_now = now_ms();

        /* Reopen the value fds every 2 s: vendor services can invalidate
         * a long-lived sysfs fd (reads then keep returning the old value). */
        if (loop_now - last_reopen > 2000) {
            if (fa >= 0) close(fa);
            if (fb >= 0) close(fb);
            if (fbtn >= 0) close(fbtn);
            open_gpios(&fa, &fb, &fbtn);
            a = gpio_read(fa); b = gpio_read(fb);
            prev = ((a > 0) << 1) | (b > 0);
            prev_btn = gpio_read(fbtn);
            prev_btn_raw = prev_btn;
            last_reopen = loop_now;
            if (fa < 0 || fb < 0) logmsg("reopen failed a=%d b=%d btn=%d", fa, fb, fbtn);
        }

        int ca = gpio_read(fa), cb = gpio_read(fb);
        if (ca >= 0 && cb >= 0) {
            int cur = (ca << 1) | cb;
            int d = qtab[(prev << 2) | cur];
            prev = cur;
            if (d) {
                pos += d;
                if (pos < 0) pos = 0;
                if (pos > pos_max) pos = pos_max;
                set_vol(amp_value(pos));
            }
        } else {
            if (loop_now - last_err_log > 1000) {
                logmsg("encoder read error a=%d b=%d", ca, cb);
                last_err_log = loop_now;
            }
        }

        if (fbtn >= 0) {
            int bv = gpio_read(fbtn);
            if (bv >= 0) {
                if (bv != prev_btn_raw) {
                    logmsg("btn raw=%d (prev=%d)", bv, prev_btn_raw);
                    prev_btn_raw = bv;
                }
                if (prev_btn == 1 && bv == 0) {
                    pressed = 1;
                    logmsg("PRESS latched");
                }
                prev_btn = bv;
            } else {
                if (loop_now - last_err_log > 1000) {
                    logmsg("btn read error");
                    last_err_log = loop_now;
                }
            }
        }

        int c = accept(srv, NULL, NULL);
        if (c >= 0) {
            const char *msg = pressed ? "1\n" : "0\n";
            if (pressed) logmsg("poll -> 1");
            (void)write(c, msg, 2);
            pressed = 0;
            close(c);
        }

        if (press_srv >= 0) {
            int p = accept(press_srv, NULL, NULL);
            if (p >= 0) {
                char buf[32];
                memset(buf, 0, sizeof(buf));
                usleep(10000);
                int n = (int)read(p, buf, sizeof(buf) - 1);
                if (n > 0 && (strstr(buf, "press") || strstr(buf, "listen"))) {
                    pressed = 1;
                    logmsg("remote press");
                    (void)write(p, "ok\n", 3);
                }
                close(p);
            }
        }

        if (loop_now - last_save > 2000) {
            FILE *w = fopen("/data/voice/dial_pos", "w");
            if (w) {
                fprintf(w, "%d\n", pos);
                fclose(w);
            }
            last_save = loop_now;
        }

        usleep(20000);
    }
    return 0;
}
