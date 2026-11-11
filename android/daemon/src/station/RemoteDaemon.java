package station;

import android.content.Context;
import android.hardware.input.InputManager;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioTrack;
import android.os.Looper;
import android.os.SystemClock;
import android.view.InputDevice;
import android.view.InputEvent;
import android.view.KeyEvent;
import android.view.MotionEvent;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.PrintWriter;
import java.lang.reflect.Method;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.net.ServerSocket;
import java.net.Socket;
import java.util.Collections;

/**
 * Persistent remote-control daemon for the Yandex Station (Android 6).
 * Listens on TCP 8096, newline-separated commands, injects keys through
 * InputManager (the same path as the stock "input" command, but without
 * paying the app_process startup cost on every key press).
 */
public class RemoteDaemon {
    private static final int PORT = 8096;
    private static final int PLAY_PORT = 8092;
    private static final int MODE_WAIT = 1;
    private static final int MODE_ASYNC = 0;
    private static final int VOL_STEP_PERCENT = 5;
    private static final Object LOCK = new Object();
    private static final Object PLAY_LOCK = new Object();
    private static volatile int sPlayGen = 0;
    private static volatile AudioTrack sPlayTrack;
    private static final float SCREEN_W = 1920f;
    private static final float SCREEN_H = 1080f;
    private static float sMouseX = SCREEN_W / 2f;
    private static float sMouseY = SCREEN_H / 2f;

    private static InputManager sInputManager;
    private static Method sInject;
    private static Method sSetButtonState;
    private static AudioManager sAudioManager;

    public static void main(String[] args) {
        try {
            Method getInstance = InputManager.class.getDeclaredMethod("getInstance");
            getInstance.setAccessible(true);
            sInputManager = (InputManager) getInstance.invoke(null);
            sInject = InputManager.class.getMethod("injectInputEvent", InputEvent.class, int.class);
            try {
                sSetButtonState = MotionEvent.class.getDeclaredMethod("setButtonState", int.class);
                sSetButtonState.setAccessible(true);
            } catch (Throwable ignored) {
                sSetButtonState = null;
            }
            System.out.println("remote daemon: input manager ready");
        } catch (Throwable t) {
            System.out.println("remote daemon: cannot get InputManager: " + t);
            t.printStackTrace();
            return;
        }

        initAudioManager();
        startPlaybackServer();

        ServerSocket server = null;
        try {
            server = new ServerSocket();
            server.setReuseAddress(true);
            server.bind(new java.net.InetSocketAddress(PORT));
            System.out.println("remote daemon: listening on " + PORT);
            while (true) {
                final Socket client = server.accept();
                Thread t = new Thread(new Runnable() {
                    public void run() {
                        handle(client);
                    }
                });
                t.setDaemon(true);
                t.start();
            }
        } catch (Throwable t) {
            System.out.println("remote daemon: server error: " + t);
            t.printStackTrace();
        } finally {
            if (server != null) {
                try { server.close(); } catch (Exception e) { }
            }
        }
    }

    private static void initAudioManager() {
        try {
            Looper.prepare();
            Class<?> activityThread = Class.forName("android.app.ActivityThread");
            Object thread = activityThread.getMethod("systemMain").invoke(null);
            Method getContext = activityThread.getDeclaredMethod("getSystemContext");
            getContext.setAccessible(true);
            Context context = (Context) getContext.invoke(thread);
            sAudioManager = (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
            System.out.println("remote daemon: media volume ready, max="
                    + sAudioManager.getStreamMaxVolume(AudioManager.STREAM_MUSIC));
        } catch (Throwable t) {
            System.out.println("remote daemon: audio manager unavailable: " + t);
            sAudioManager = null;
        }
    }

    private static void startPlaybackServer() {
        Thread t = new Thread(new Runnable() {
            public void run() {
                playbackServerLoop();
            }
        }, "tts-playback");
        t.setDaemon(true);
        t.start();
    }

    private static void playbackServerLoop() {
        ServerSocket server = null;
        try {
            server = new ServerSocket();
            server.setReuseAddress(true);
            server.bind(new java.net.InetSocketAddress(PLAY_PORT));
            System.out.println("remote daemon: tts playback on " + PLAY_PORT);
            while (true) {
                final Socket client = server.accept();
                Thread t = new Thread(new Runnable() {
                    public void run() {
                        handlePlayback(client);
                    }
                });
                t.setDaemon(true);
                t.start();
            }
        } catch (Throwable t) {
            System.out.println("remote daemon: playback server error: " + t);
            t.printStackTrace();
        } finally {
            if (server != null) {
                try { server.close(); } catch (Exception e) { }
            }
        }
    }

    /**
     * Abort the current TTS playback.  Called by the voice service on
     * barge-in so the assistant's tail is not fed back into STT.
     */
    private static void stopPlayback() {
        sPlayGen++;
        AudioTrack track = sPlayTrack;
        sPlayTrack = null;
        if (track != null) {
            try { track.pause(); } catch (Exception e) { }
            try { track.flush(); } catch (Exception e) { }
            try { track.stop(); } catch (Exception e) { }
            try { track.release(); } catch (Exception e) { }
        }
        System.out.println("tts: stopped");
    }

    private static void handlePlayback(Socket client) {
        try {
            int gen = sPlayGen;
            InputStream in = client.getInputStream();
            ByteArrayOutputStream buf = new ByteArrayOutputStream();
            byte[] chunk = new byte[8192];
            int n;
            while ((n = in.read(chunk)) > 0) {
                buf.write(chunk, 0, n);
                if (buf.size() > 8 * 1024 * 1024) break;
            }
            byte[] data = buf.toByteArray();
            if (data.length > 44 && gen == sPlayGen) {
                synchronized (PLAY_LOCK) {
                    playWav(data, gen);
                }
            }
        } catch (Throwable t) {
            System.out.println("remote daemon: playback error: " + t);
        } finally {
            try { client.close(); } catch (Exception e) { }
        }
    }

    private static int le16(byte[] b, int off) {
        return (b[off] & 0xff) | ((b[off + 1] & 0xff) << 8);
    }

    private static int le32(byte[] b, int off) {
        return (b[off] & 0xff) | ((b[off + 1] & 0xff) << 8)
                | ((b[off + 2] & 0xff) << 16) | ((b[off + 3] & 0xff) << 24);
    }

    /**
     * Play a 16-bit PCM WAV through AudioFlinger.  Snapcast uses Oboe and
     * keeps the ALSA device busy, so tinyplay (direct ALSA) would block here;
     * STREAM_MUSIC mixes with Snapcast and follows the media volume.
     */
    private static void playWav(byte[] wav, int gen) {
        if (gen != sPlayGen) return;
        if (wav.length < 44
                || wav[0] != 'R' || wav[1] != 'I' || wav[2] != 'F' || wav[3] != 'F'
                || wav[8] != 'W' || wav[9] != 'A' || wav[10] != 'V' || wav[11] != 'E') {
            System.out.println("tts: not a wav (" + wav.length + " bytes)");
            return;
        }
        int rate = 0;
        int channels = 0;
        int bits = 0;
        int dataOff = -1;
        int dataLen = 0;
        int pos = 12;
        while (pos + 8 <= wav.length) {
            String id = new String(wav, pos, 4);
            int size = le32(wav, pos + 4);
            int body = pos + 8;
            if (size < 0 || body + size > wav.length) break;
            if (id.equals("fmt ")) {
                channels = le16(wav, body + 2);
                rate = le32(wav, body + 4);
                bits = le16(wav, body + 14);
            } else if (id.equals("data")) {
                dataOff = body;
                dataLen = Math.min(size, wav.length - body);
                break;
            }
            pos = body + size + (size & 1);
        }
        if (dataOff < 0 || dataLen <= 0 || rate <= 0 || channels <= 0 || bits != 16) {
            System.out.println("tts: unsupported wav rate=" + rate + " ch=" + channels
                    + " bits=" + bits + " data=" + dataLen);
            return;
        }
        int channelMask = channels == 1
                ? AudioFormat.CHANNEL_OUT_MONO : AudioFormat.CHANNEL_OUT_STEREO;
        int frameBytes = channels * 2;
        int minBuf = AudioTrack.getMinBufferSize(rate, channelMask,
                AudioFormat.ENCODING_PCM_16BIT);
        int bufSize = Math.max(minBuf, Math.min(dataLen, 262144));
        int totalFrames = dataLen / frameBytes;
        long durationMs = totalFrames * 1000L / rate;
        AudioTrack track = null;
        try {
            track = new AudioTrack(AudioManager.STREAM_MUSIC, rate, channelMask,
                    AudioFormat.ENCODING_PCM_16BIT, bufSize, AudioTrack.MODE_STREAM);
            if (gen != sPlayGen) return;
            sPlayTrack = track;
            track.play();
            int off = dataOff;
            int end = dataOff + dataLen;
            int writtenFrames = 0;
            while (off < end && gen == sPlayGen) {
                int count = Math.min(8192, end - off);
                int wrote = track.write(wav, off, count);
                if (wrote <= 0) break;
                off += wrote;
                writtenFrames += wrote / frameBytes;
            }
            long deadline = System.currentTimeMillis() + durationMs + 3000L;
            while (gen == sPlayGen && track.getPlaybackHeadPosition() < writtenFrames
                    && System.currentTimeMillis() < deadline) {
                try { Thread.sleep(20L); } catch (InterruptedException ie) { break; }
            }
            if (gen == sPlayGen) {
                System.out.println("tts: played " + dataLen + " bytes " + rate + "Hz "
                        + channels + "ch " + durationMs + "ms");
            }
        } catch (Throwable t) {
            System.out.println("tts: play failed: " + t);
        } finally {
            if (sPlayTrack == track) sPlayTrack = null;
            if (track != null) {
                try { track.stop(); } catch (Exception e) { }
                try { track.release(); } catch (Exception e) { }
            }
        }
    }

    private static void adjustMediaVolume(int direction) throws Exception {
        if (sAudioManager != null) {
            sAudioManager.adjustStreamVolume(AudioManager.STREAM_MUSIC, direction,
                    AudioManager.FLAG_SHOW_UI);
        } else {
            injectKey(direction == AudioManager.ADJUST_RAISE
                    ? KeyEvent.KEYCODE_VOLUME_UP : KeyEvent.KEYCODE_VOLUME_DOWN);
        }
    }

    /** Returns the resulting volume percentage, or -1 if only a key fallback was possible. */
    private static int setMediaVolume(int percent, boolean relative) throws Exception {
        if (sAudioManager == null) {
            if (!relative && percent <= 0) {
                injectKey(KeyEvent.KEYCODE_MUTE);
            } else {
                adjustMediaVolume(percent >= 0 ? AudioManager.ADJUST_RAISE : AudioManager.ADJUST_LOWER);
            }
            return -1;
        }
        int max = sAudioManager.getStreamMaxVolume(AudioManager.STREAM_MUSIC);
        int current = sAudioManager.getStreamVolume(AudioManager.STREAM_MUSIC);
        int currentUser = rawToUserPercent(Math.round(current * 100f / max));
        int targetUser = relative ? currentUser + percent : percent;
        if (targetUser < 0) targetUser = 0;
        if (targetUser > 100) targetUser = 100;
        int target = Math.round(userToRawPercent(targetUser) * max / 100f);
        if (target < 0) target = 0;
        if (target > max) target = max;
        sAudioManager.setStreamVolume(AudioManager.STREAM_MUSIC, target, 0);
        return targetUser;
    }

    /**
     * The stock Android curve on this TV is extremely steep: 40% is -29 dB,
     * while 70% is -13 dB.  Keep the number the user asks for (40) but map it
     * to an index that actually sounds like 40% loudness.  40 -> 70,
     * 100 -> 100; below 40 the mapping is linear in index, above 40 linear in
     * the remaining range.
     */
    private static int userToRawPercent(int percent) {
        if (percent <= 0) return 0;
        if (percent >= 100) return 100;
        double raw;
        if (percent <= 40) {
            raw = percent * 70.0 / 40.0;
        } else {
            raw = 70.0 + (percent - 40) * 30.0 / 60.0;
        }
        return (int) Math.round(raw);
    }

    private static int rawToUserPercent(int raw) {
        if (raw <= 0) return 0;
        if (raw >= 100) return 100;
        double user;
        if (raw <= 70) {
            user = raw * 40.0 / 70.0;
        } else {
            user = 40.0 + (raw - 70) * 60.0 / 30.0;
        }
        return (int) Math.round(user);
    }

    private static void toggleMediaMute() throws Exception {
        if (sAudioManager != null) {
            sAudioManager.adjustStreamVolume(AudioManager.STREAM_MUSIC,
                    AudioManager.ADJUST_TOGGLE_MUTE, AudioManager.FLAG_SHOW_UI);
        } else {
            injectKey(KeyEvent.KEYCODE_MUTE);
        }
    }

    private static String notificationVolume() {
        if (sAudioManager == null) return "notif -1";
        int max = sAudioManager.getStreamMaxVolume(AudioManager.STREAM_NOTIFICATION);
        int cur = sAudioManager.getStreamVolume(AudioManager.STREAM_NOTIFICATION);
        if (max <= 0) return "notif -1";
        return "notif " + Math.round(cur * 100f / max);
    }

    private static String adjustNotification(int direction) {
        if (sAudioManager == null) return "notif -1";
        try {
            sAudioManager.adjustStreamVolume(AudioManager.STREAM_NOTIFICATION,
                    direction, 0);
        } catch (Exception e) {
            return "notif -1";
        }
        return notificationVolume();
    }

    private static String readFile(String path) {
        BufferedReader r = null;
        try {
            r = new BufferedReader(new java.io.FileReader(path));
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = r.readLine()) != null) sb.append(line).append('\n');
            return sb.toString().trim();
        } catch (Exception e) {
            return "";
        } finally {
            if (r != null) try { r.close(); } catch (Exception e) { }
        }
    }

    private static long memKb(String line) {
        try {
            String[] p = line.trim().split("\\s+");
            return Long.parseLong(p[1]);
        } catch (Exception e) {
            return 0;
        }
    }

    private static String memInfo() {
        long total = 0, free = 0, cached = 0;
        String all = readFile("/proc/meminfo");
        for (String line : all.split("\n")) {
            if (line.startsWith("MemTotal:")) total = memKb(line);
            else if (line.startsWith("MemFree:")) free = memKb(line);
            else if (line.startsWith("Cached:")) cached = memKb(line);
        }
        long avail = (free + cached) / 1024;
        return "mem " + avail + " " + (total / 1024);
    }

    private static String tempInfo() {
        String raw = readFile("/sys/class/thermal/thermal_zone0/temp");
        try {
            int v = Integer.parseInt(raw.trim());
            if (v > 1000) v /= 1000;
            return "temp " + v;
        } catch (Exception e) {
            return "temp -1";
        }
    }

    private static String execOutput(String cmd) {
        try {
            Process p = Runtime.getRuntime().exec(new String[]{"sh", "-c", cmd});
            BufferedReader r = new BufferedReader(new InputStreamReader(p.getInputStream()));
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = r.readLine()) != null) sb.append(line);
            p.waitFor();
            return sb.toString().trim();
        } catch (Exception e) {
            return "";
        }
    }

    private static String netInfo() {
        try {
            NetworkInterface ni = NetworkInterface.getByName("wlan0");
            if (ni != null) {
                for (InetAddress a : Collections.list(ni.getInetAddresses())) {
                    if (a instanceof Inet4Address && !a.isLoopbackAddress()) {
                        return "net " + a.getHostAddress();
                    }
                }
            }
        } catch (Exception e) {
        }
        String ip = execOutput("getprop dhcp.wlan0.ipaddress");
        if (ip.length() == 0) ip = "0.0.0.0";
        return "net " + ip;
    }

    private static String cleanMemory() {
        try {
            Runtime.getRuntime().exec(new String[]{"am", "kill-all"}).waitFor();
        } catch (Exception e) {
        }
        return memInfo();
    }

    private static void handle(Socket client) {
        try {
            BufferedReader in = new BufferedReader(new InputStreamReader(client.getInputStream(), "UTF-8"));
            PrintWriter out = new PrintWriter(client.getOutputStream(), true);
            String line;
            while ((line = in.readLine()) != null) {
                line = line.trim();
                if (line.length() == 0) continue;
                try {
                    String result = dispatch(line);
                    if (result != null) out.println(result);
                } catch (Throwable t) {
                    out.println("err " + t);
                }
            }
        } catch (Throwable t) {
            // client went away
        } finally {
            try { client.close(); } catch (Exception e) { }
        }
    }

    private static String dispatch(String cmd) throws Exception {
        if (cmd.equals("ping")) return "pong";

        if (cmd.startsWith("m:")) {
            String[] p = cmd.substring(2).split(",");
            if (p.length == 2) {
                moveMouse(Float.parseFloat(p[0]), Float.parseFloat(p[1]));
                return "ok";
            }
            return "bad mouse";
        }
        if (cmd.equals("click")) {
            clickMouse();
            return "ok";
        }

        if (cmd.startsWith("key:")) {
            injectKey(Integer.parseInt(cmd.substring(4)));
            return "ok";
        }

        if (cmd.startsWith("text:")) {
            exec(new String[]{"input", "text", cmd.substring(5)});
            return "ok";
        }

        if (cmd.startsWith("app:")) {
            launch(cmd.substring(4));
            return "ok";
        }

        // Media volume only: never let the remote change notification/ring volume.
        if (cmd.equals("volup")) {
            int out = setMediaVolume(VOL_STEP_PERCENT, true);
            return out < 0 ? "ok" : "vol " + out;
        }
        if (cmd.equals("voldown")) {
            int out = setMediaVolume(-VOL_STEP_PERCENT, true);
            return out < 0 ? "ok" : "vol " + out;
        }
        if (cmd.equals("mute")) {
            toggleMediaMute();
            return "ok";
        }
        if (cmd.equals("notifup")) {
            return adjustNotification(AudioManager.ADJUST_RAISE);
        }
        if (cmd.equals("notifdown")) {
            return adjustNotification(AudioManager.ADJUST_LOWER);
        }
        if (cmd.equals("notifmute")) {
            if (sAudioManager == null) return "notif -1";
            sAudioManager.adjustStreamVolume(AudioManager.STREAM_NOTIFICATION,
                    AudioManager.ADJUST_TOGGLE_MUTE, 0);
            return notificationVolume();
        }
        if (cmd.equals("notifget")) {
            return notificationVolume();
        }
        if (cmd.equals("mem")) {
            return memInfo();
        }
        if (cmd.equals("temp")) {
            return tempInfo();
        }
        if (cmd.equals("net")) {
            return netInfo();
        }
        if (cmd.equals("clean")) {
            return cleanMemory();
        }
        if (cmd.equals("ttsstop")) {
            stopPlayback();
            return "ok";
        }
        if (cmd.equals("recents")) {
            // Android TV ignores KEYCODE_APP_SWITCH and RecentsActivity isn't
            // exported; root can start it directly.
            exec(new String[]{"am", "start", "-n",
                    "com.android.systemui/com.android.systemui.recents.RecentsActivity"});
            return "ok";
        }
        if (cmd.equals("volget")) {
            if (sAudioManager == null) return "vol -1";
            int max = sAudioManager.getStreamMaxVolume(AudioManager.STREAM_MUSIC);
            int cur = sAudioManager.getStreamVolume(AudioManager.STREAM_MUSIC);
            return "vol " + rawToUserPercent(Math.round(cur * 100f / max));
        }
        if (cmd.equals("volraw")) {
            if (sAudioManager == null) return "vol -1";
            int max = sAudioManager.getStreamMaxVolume(AudioManager.STREAM_MUSIC);
            int cur = sAudioManager.getStreamVolume(AudioManager.STREAM_MUSIC);
            return "vol " + Math.round(cur * 100f / max);
        }
        if (cmd.startsWith("vol:")) {
            int out = setMediaVolume(Integer.parseInt(cmd.substring(4).trim()), false);
            return out < 0 ? "ok" : "vol " + out;
        }
        if (cmd.startsWith("volr:")) {
            int out = setMediaVolume(Integer.parseInt(cmd.substring(5).trim()), true);
            return out < 0 ? "ok" : "vol " + out;
        }

        int code = keyCode(cmd);
        if (code < 0) return "unknown " + cmd;
        injectKey(code);
        return "ok";
    }

    private static int keyCode(String cmd) {
        if (cmd.equals("up")) return KeyEvent.KEYCODE_DPAD_UP;
        if (cmd.equals("down")) return KeyEvent.KEYCODE_DPAD_DOWN;
        if (cmd.equals("left")) return KeyEvent.KEYCODE_DPAD_LEFT;
        if (cmd.equals("right")) return KeyEvent.KEYCODE_DPAD_RIGHT;
        if (cmd.equals("ok") || cmd.equals("enter")) return KeyEvent.KEYCODE_DPAD_CENTER;
        if (cmd.equals("back")) return KeyEvent.KEYCODE_BACK;
        if (cmd.equals("home")) return KeyEvent.KEYCODE_HOME;
        if (cmd.equals("play")) return KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE;
        if (cmd.equals("power")) return KeyEvent.KEYCODE_POWER;
        if (cmd.equals("menu")) return KeyEvent.KEYCODE_MENU;
        if (cmd.equals("wake")) return KeyEvent.KEYCODE_WAKEUP;
        if (cmd.equals("search")) return KeyEvent.KEYCODE_SEARCH;
        return -1;
    }

    private static void moveMouse(float dx, float dy) throws Exception {
        sMouseX = Math.max(0f, Math.min(SCREEN_W - 1f, sMouseX + dx));
        sMouseY = Math.max(0f, Math.min(SCREEN_H - 1f, sMouseY + dy));
        long now = SystemClock.uptimeMillis();
        MotionEvent ev = MotionEvent.obtain(now, now, MotionEvent.ACTION_HOVER_MOVE, sMouseX, sMouseY, 0);
        ev.setSource(InputDevice.SOURCE_MOUSE);
        synchronized (LOCK) {
            sInject.invoke(sInputManager, ev, MODE_ASYNC);
        }
        ev.recycle();
    }

    private static void clickMouse() throws Exception {
        long now = SystemClock.uptimeMillis();
        MotionEvent down = MotionEvent.obtain(now, now, MotionEvent.ACTION_DOWN, sMouseX, sMouseY, 0);
        down.setSource(InputDevice.SOURCE_MOUSE);
        if (sSetButtonState != null) {
            sSetButtonState.invoke(down, MotionEvent.BUTTON_PRIMARY);
        }
        MotionEvent up = MotionEvent.obtain(now, now + 20, MotionEvent.ACTION_UP, sMouseX, sMouseY, 0);
        up.setSource(InputDevice.SOURCE_MOUSE);
        if (sSetButtonState != null) {
            sSetButtonState.invoke(up, 0);
        }
        synchronized (LOCK) {
            sInject.invoke(sInputManager, down, MODE_WAIT);
            sInject.invoke(sInputManager, up, MODE_WAIT);
        }
        down.recycle();
        up.recycle();
    }

    private static void injectKey(int code) throws Exception {
        long now = SystemClock.uptimeMillis();
        KeyEvent down = new KeyEvent(now, now, KeyEvent.ACTION_DOWN, code, 0);
        KeyEvent up = new KeyEvent(now, now, KeyEvent.ACTION_UP, code, 0);
        synchronized (LOCK) {
            sInject.invoke(sInputManager, down, MODE_WAIT);
            sInject.invoke(sInputManager, up, MODE_WAIT);
        }
    }

    private static void launch(String name) {
        if (name.equals("youtube")) {
            exec(new String[]{"monkey", "-p", "org.smarttube.stable", "-c", "android.intent.category.LAUNCHER", "1"});
        } else if (name.equals("tv")) {
            exec(new String[]{"am", "start", "-n", "com.tvlauncher/.MainActivity"});
        } else if (name.equals("couchy")) {
            exec(new String[]{"am", "start", "-n", "com.conreo.couchytv/com.conreo.couchytv.MainActivity"});
        } else if (name.equals("ha")) {
            exec(new String[]{"am", "start", "-n", "io.homeassistant.companion.android.minimal/io.homeassistant.companion.android.launch.LaunchActivity"});
        } else if (name.equals("settings")) {
            exec(new String[]{"am", "start", "-a", "android.settings.SETTINGS"});
        }
    }

    private static void exec(String[] cmd) {
        try {
            Process p = Runtime.getRuntime().exec(cmd);
            p.waitFor();
        } catch (Throwable t) {
            // ignore
        }
    }
}
