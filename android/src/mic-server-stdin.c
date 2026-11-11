#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

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

static void make_wav_header(unsigned char *h) {
    memset(h, 0, 44);
    memcpy(h + 0, "RIFF", 4);
    uint32_t riff_size = 0xFFFFFFFFu;
    memcpy(h + 4, &riff_size, 4);
    memcpy(h + 8, "WAVEfmt ", 8);
    uint32_t fmt_size = 16;
    memcpy(h + 16, &fmt_size, 4);
    uint16_t pcm = 1;
    memcpy(h + 20, &pcm, 2);
    uint16_t channels = 5;
    memcpy(h + 22, &channels, 2);
    uint32_t rate = 16000;
    memcpy(h + 24, &rate, 4);
    uint32_t byte_rate = 16000 * 5 * 2;
    memcpy(h + 28, &byte_rate, 4);
    uint16_t align = 5 * 2;
    memcpy(h + 32, &align, 2);
    uint16_t bits = 16;
    memcpy(h + 34, &bits, 2);
    memcpy(h + 36, "data", 4);
    uint32_t data_size = 0xFFFFFFFFu;
    memcpy(h + 40, &data_size, 4);
}

int main(int argc, char **argv) {
    signal(SIGPIPE, SIG_IGN);
    int port = argc > 1 ? atoi(argv[1]) : 8091;

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
        return 1;
    }
    if (listen(s, 4) < 0) {
        perror("listen");
        return 1;
    }
    fprintf(stderr, "mic-server listening on %d (stdin raw PCM)\n", port);

    unsigned char hdr[44];
    make_wav_header(hdr);
    unsigned char buf[32768];
    int client = -1;

    for (;;) {
        struct pollfd fds[2];
        fds[0].fd = 0;
        fds[0].events = POLLIN;
        fds[1].fd = s;
        fds[1].events = POLLIN;
        int pr = poll(fds, 2, 1000);
        if (pr < 0 && errno != EINTR) break;

        if (fds[1].revents & POLLIN) {
            int c = accept(s, NULL, NULL);
            if (c >= 0) {
                if (client >= 0) close(client);
                client = c;
                if (send_all(client, "A5\n", 3) != 0 ||
                    send_all(client, hdr, 44) != 0) {
                    close(client);
                    client = -1;
                }
            }
        }

        if (fds[0].revents & POLLIN) {
            int n = read(0, buf, sizeof(buf));
            if (n <= 0) break;
            if (client >= 0) {
                if (send_all(client, buf, n) != 0) {
                    close(client);
                    client = -1;
                }
            }
        }
        if (fds[0].revents & (POLLHUP | POLLERR)) break;
    }

    if (client >= 0) close(client);
    close(s);
    return 0;
}
