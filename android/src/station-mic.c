#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

static const char *g_path = "/data/voice/mic/mic.wav";

static int file_size(void) {
    struct stat st;
    if (stat(g_path, &st) != 0) return -1;
    return (int)st.st_size;
}

static int send_all(int fd, const void *buf, int len) {
    const char *p = (const char *)buf;
    while (len > 0) {
        int n = send(fd, p, len, MSG_NOSIGNAL);
        if (n <= 0) return -1;
        p += n;
        len -= n;
    }
    return 0;
}

static int read_chunk(int *fd, off_t *pos, unsigned char *buf, int buflen) {
    struct stat st;
    if (stat(g_path, &st) != 0) return -1;
    if (*fd < 0 || st.st_size < *pos) {
        if (*fd >= 0) close(*fd);
        *fd = open(g_path, O_RDONLY);
        if (*fd < 0) return -1;
        *pos = 44; /* skip the WAV header */
    }
    if (st.st_size <= *pos) return 0;
    if (lseek(*fd, *pos, SEEK_SET) < 0) return -1;
    int want = (int)(st.st_size - *pos);
    if (want > buflen) want = buflen;
    int n = read(*fd, buf, want);
    if (n > 0) *pos += n;
    return n;
}

static void serve_client(int c) {
    unsigned char buf[16384];
    unsigned char hdr[44];
    int size = -1;
    for (int i = 0; i < 50; i++) {
        size = file_size();
        if (size >= 44) break;
        usleep(100000);
    }
    if (size < 44) {
        close(c);
        return;
    }
    if (send_all(c, "A5\n", 3) != 0) {
        close(c);
        return;
    }
    int fd = open(g_path, O_RDONLY);
    if (fd < 0) {
        close(c);
        return;
    }
    if (read(fd, hdr, 44) != 44) {
        close(fd);
        close(c);
        return;
    }
    if (send_all(c, hdr, 44) != 0) {
        close(fd);
        close(c);
        return;
    }
    off_t pos = file_size();
    if (pos < 44) pos = 44;

    for (;;) {
        int n = read_chunk(&fd, &pos, buf, sizeof(buf));
        if (n < 0) break;
        if (n == 0) {
            usleep(50000);
            continue;
        }
        if (send_all(c, buf, n) != 0) break;
    }
    if (fd >= 0) close(fd);
    close(c);
}

int main(int argc, char **argv) {
    signal(SIGPIPE, SIG_IGN);
    int port = argc > 1 ? atoi(argv[1]) : 8091;
    if (argc > 2) g_path = argv[2];

    int s = socket(AF_INET, SOCK_STREAM, 0);
    if (s < 0) {
        perror("socket");
        return 1;
    }
    int one = 1;
    setsockopt(s, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    struct sockaddr_in a;
    memset(&a, 0, sizeof(a));
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = htonl(INADDR_ANY);
    a.sin_port = htons(port);
    if (bind(s, (struct sockaddr *)&a, sizeof(a)) < 0) {
        perror("bind");
        close(s);
        return 1;
    }
    if (listen(s, 4) < 0) {
        perror("listen");
        close(s);
        return 1;
    }
    fprintf(stderr, "station-mic listening on %d, file %s\n", port, g_path);
    for (;;) {
        int c = accept(s, NULL, NULL);
        if (c < 0) {
            if (errno == EINTR) continue;
            perror("accept");
            sleep(1);
            continue;
        }
        serve_client(c);
    }
    return 0;
}
