package ru.station.remote;

import android.app.Activity;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.Gravity;
import android.view.HapticFeedbackConstants;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.view.inputmethod.InputMethodManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.net.HttpURLConnection;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.net.URL;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;

import org.json.JSONObject;

public class MainActivity extends Activity {
    private static final String DEFAULT_HOST = "192.168.1.10";
    private static final String DEFAULT_MEDIA_HOST = "192.168.1.20";
    private static final int PORT = 8096;

    private static final int BG = 0xFF0B0B0F;
    private static final int BTN = 0xFF1C1C24;
    private static final int BTN_DOWN = 0xFF343442;
    private static final int ACCENT = 0xFFFF5A3C;
    private static final int TEXT = 0xFFFFFFFF;
    private static final int MUTED = 0xFF9E9EA8;

    private final Handler ui = new Handler(Looper.getMainLooper());
    private RemoteClient client;
    private RemoteClient mouseClient;
    private TextView status;
    private TextView volStatus;
    private TextView sysStatus;
    private TextView musicNow;
    private LinearLayout musicSection;
    private LinearLayout youtubeSection;
    private LinearLayout tvSection;
    private Button modeYoutube;
    private Button modeMusic;
    private Button modeTv;
    private String mode = "music";
    private EditText hostField;
    private EditText mediaField;
    private LinearLayout settingsRow;
    private LinearLayout textRow;
    private EditText textField;
    private Thread volPoll;
    private Thread mediaPoll;
    private volatile boolean running = true;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        buildUi();
        SharedPreferences prefs = getSharedPreferences("remote", MODE_PRIVATE);
        String host = prefs.getString("host", DEFAULT_HOST);
        hostField.setText(host);
        client = new RemoteClient(host, new RemoteClient.Listener() {
            public void onStatus(final boolean connected) {
                ui.post(new Runnable() {
                    public void run() {
                        status.setText(connected ? "\u25CF ONLINE" : "\u25CF OFFLINE");
                        status.setTextColor(connected ? 0xFF39D98A : 0xFFFF5A5A);
                    }
                });
            }
        }, 8096);
        client.start();
        mouseClient = new RemoteClient(host, null, 8097);
        mouseClient.start();
        startVolumePoll();
        startMediaPoll();
    }

    private void startVolumePoll() {
        volPoll = new Thread(new Runnable() {
            @Override
            public void run() {
                int tick = 0;
                while (running) {
                    String host = hostField.getText().toString().trim();
                    final String media = query(host, "volget");
                    final String notif = query(host, "notifget");
                    final String mem = (tick % 5 == 0) ? query(host, "mem") : null;
                    final String temp = (tick % 5 == 0) ? query(host, "temp") : null;
                    final String net = (tick % 5 == 0) ? query(host, "net") : null;
                    ui.post(new Runnable() {
                        @Override
                        public void run() {
                            volStatus.setText("Медиа " + media + "%   Уведомления " + notif + "%");
                            if (mem != null) {
                                String[] m = mem.split(" ");
                                String ram = m.length >= 2 ? m[0] + "/" + m[1] + " МБ" : "—";
                                sysStatus.setText("CPU " + temp + "°C · RAM " + ram + " · Wi-Fi " + net);
                            }
                        }
                    });
                    tick++;
                    try {
                        Thread.sleep(1000);
                    } catch (InterruptedException e) {
                        return;
                    }
                }
            }
        }, "volume-poll");
        volPoll.start();
    }

    private String query(String host, String cmd) {
        Socket s = null;
        try {
            s = new Socket();
            s.connect(new InetSocketAddress(host, PORT), 1500);
            s.setSoTimeout(1200);
            BufferedWriter out = new BufferedWriter(new OutputStreamWriter(s.getOutputStream(), "UTF-8"));
            BufferedReader in = new BufferedReader(new InputStreamReader(s.getInputStream(), "UTF-8"));
            out.write(cmd);
            out.newLine();
            out.flush();
            String line = in.readLine();
            if (line != null) {
                int sp = line.indexOf(' ');
                if (sp > 0) return line.substring(sp + 1).trim();
            }
        } catch (Exception ignored) {
        } finally {
            if (s != null) {
                try { s.close(); } catch (Exception ignored) { }
            }
        }
        return "—";
    }

    private String mediaBase() {
        String h = getSharedPreferences("remote", MODE_PRIVATE)
                .getString("media_host", DEFAULT_MEDIA_HOST);
        return "http://" + h + ":8099";
    }

    private void startMediaPoll() {
        mediaPoll = new Thread(new Runnable() {
            @Override
            public void run() {
                while (running) {
                    String json = httpGet(mediaBase() + "/api/now");
                    if (json != null) {
                        try {
                            JSONObject o = new JSONObject(json);
                            String state = o.optString("state", "");
                            String title = o.optString("title", "");
                            String artist = o.optString("artist", "");
                            if ("unavailable".equals(state) || "off".equals(state)) {
                                title = "";
                                artist = "";
                            }
                            String line;
                            if (title.length() == 0) {
                                line = "—";
                            } else if (artist.length() == 0) {
                                line = title;
                            } else {
                                line = title + " — " + artist;
                            }
                            if (title.length() > 0 && !"playing".equals(state)) {
                                line = "⏸ " + line;
                            }
                            final String shown = line;
                            ui.post(new Runnable() {
                                @Override
                                public void run() {
                                    musicNow.setText(shown);
                                }
                            });
                        } catch (Exception ignored) {
                        }
                    }
                    try {
                        Thread.sleep(2000);
                    } catch (InterruptedException e) {
                        return;
                    }
                }
            }
        }, "media-poll");
        mediaPoll.start();
    }

    private String httpGet(String url) {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(url).openConnection();
            c.setConnectTimeout(2500);
            c.setReadTimeout(4000);
            if (c.getResponseCode() != 200) return null;
            InputStream in = c.getInputStream();
            BufferedReader r = new BufferedReader(new InputStreamReader(in, "UTF-8"));
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = r.readLine()) != null) sb.append(line);
            r.close();
            in.close();
            return sb.toString();
        } catch (Exception e) {
            return null;
        } finally {
            if (c != null) c.disconnect();
        }
    }

    private void musicAction(final String action) {
        new Thread(new Runnable() {
            @Override
            public void run() {
                httpGet(mediaBase() + "/api/music?action=" + action);
            }
        }, "music-action").start();
    }

    @Override
    protected void onDestroy() {
        running = false;
        if (volPoll != null) volPoll.interrupt();
        if (mediaPoll != null) mediaPoll.interrupt();
        if (client != null) client.stop();
        if (mouseClient != null) mouseClient.stop();
        super.onDestroy();
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    private GradientDrawable bg(int color, int radius) {
        GradientDrawable d = new GradientDrawable();
        d.setColor(color);
        d.setCornerRadius(dp(radius));
        return d;
    }

    private StateListDrawable buttonBg(int normal, int pressed) {
        StateListDrawable s = new StateListDrawable();
        s.addState(new int[]{android.R.attr.state_pressed}, bg(pressed, 12));
        s.addState(new int[]{}, bg(normal, 12));
        return s;
    }

    private Button makeButton(String label, int color, int textColor, int heightDp, int textSp) {
        Button b = new Button(this);
        b.setText(label);
        b.setTextSize(textSp);
        b.setTextColor(textColor);
        b.setTypeface(null, android.graphics.Typeface.BOLD);
        b.setBackground(buttonBg(color, BTN_DOWN));
        b.setPadding(0, 0, 0, 0);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, dp(heightDp), 1f);
        lp.setMargins(dp(4), dp(4), dp(4), dp(4));
        b.setLayoutParams(lp);
        return b;
    }

    private void addSpacer(LinearLayout row) {
        View v = new View(this);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, 1, 1f);
        lp.setMargins(dp(4), 0, dp(4), 0);
        v.setLayoutParams(lp);
        row.addView(v);
    }

    private void click(View v, final String cmd) {
        v.setOnClickListener(new View.OnClickListener() {
            public void onClick(View view) {
                view.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY);
                send(cmd);
            }
        });
    }

    private void musicClick(View v, final String action) {
        v.setOnClickListener(new View.OnClickListener() {
            public void onClick(View view) {
                view.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY);
                musicAction(action);
            }
        });
    }

    private void repeat(View v, final String cmd) {
        v.setOnTouchListener(new View.OnTouchListener() {
            private final Handler h = new Handler(Looper.getMainLooper());
            private final Runnable r = new Runnable() {
                public void run() {
                    send(cmd);
                    h.postDelayed(this, 80);
                }
            };
            public boolean onTouch(View view, MotionEvent e) {
                int a = e.getActionMasked();
                if (a == MotionEvent.ACTION_DOWN) {
                    view.setPressed(true);
                    view.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY);
                    send(cmd);
                    h.postDelayed(r, 350);
                    return true;
                }
                if (a == MotionEvent.ACTION_UP || a == MotionEvent.ACTION_CANCEL) {
                    view.setPressed(false);
                    h.removeCallbacks(r);
                    return true;
                }
                return false;
            }
        });
    }

    private LinearLayout row() {
        LinearLayout r = new LinearLayout(this);
        r.setOrientation(LinearLayout.HORIZONTAL);
        r.setLayoutParams(new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        return r;
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(BG);
        root.setPadding(dp(12), dp(10), dp(12), dp(10));

        LinearLayout header = row();
        header.setGravity(Gravity.CENTER_VERTICAL);
        TextView title = new TextView(this);
        title.setText("STATION REMOTE");
        title.setTextColor(TEXT);
        title.setTextSize(22);
        title.setTypeface(null, android.graphics.Typeface.BOLD);
        title.setLayoutParams(new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        header.addView(title);

        status = new TextView(this);
        status.setText("\u25CF OFFLINE");
        status.setTextColor(0xFFFF5A5A);
        status.setTextSize(12);
        header.addView(status);

        Button gear = new Button(this);
        gear.setText("SET");
        gear.setTextSize(11);
        gear.setTextColor(MUTED);
        gear.setBackground(buttonBg(0xFF17171E, BTN_DOWN));
        LinearLayout.LayoutParams glp = new LinearLayout.LayoutParams(dp(54), dp(36));
        glp.setMargins(dp(8), 0, 0, 0);
        gear.setLayoutParams(glp);
        gear.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                settingsRow.setVisibility(settingsRow.getVisibility() == View.VISIBLE ? View.GONE : View.VISIBLE);
            }
        });
        header.addView(gear);
        root.addView(header);

        LinearLayout ptt = row();
        Button talk = makeButton("PUSH TO TALK", ACCENT, 0xFF141418, 50, 14);
        talk.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                v.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY);
                sendVoice();
            }
        });
        ptt.addView(talk);
        root.addView(ptt);

        LinearLayout modes = row();
        modeYoutube = makeButton("YOUTUBE", BTN, TEXT, 42, 11);
        modeMusic = makeButton("MUSIC", ACCENT, 0xFF141418, 42, 12);
        modeTv = makeButton("TV", BTN, TEXT, 42, 11);
        modes.addView(modeYoutube);
        modes.addView(modeMusic);
        modes.addView(modeTv);
        root.addView(modes);
        modeYoutube.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                v.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY);
                setMode("youtube");
            }
        });
        modeMusic.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                v.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY);
                setMode("music");
            }
        });
        modeTv.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                v.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY);
                setMode("tv");
            }
        });

        textRow = row();
        textRow.setVisibility(View.GONE);
        textField = new EditText(this);
        textField.setHint("Text / search");
        textField.setTextColor(TEXT);
        textField.setHintTextColor(MUTED);
        textField.setTextSize(15);
        textField.setSingleLine(true);
        textField.setInputType(InputType.TYPE_CLASS_TEXT);
        textField.setLayoutParams(new LinearLayout.LayoutParams(0, dp(48), 1f));
        textRow.addView(textField);
        Button send = makeButton("SEND", 0xFF2A2A35, TEXT, 48, 13);
        send.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                String t = textField.getText().toString();
                if (t.length() > 0) {
                    send("text:" + t);
                    textField.setText("");
                }
            }
        });
        textRow.addView(send);
        Button hideText = new Button(this);
        hideText.setText("HIDE");
        hideText.setTextSize(11);
        hideText.setTextColor(MUTED);
        hideText.setBackground(buttonBg(0xFF17171E, BTN_DOWN));
        LinearLayout.LayoutParams hlp = new LinearLayout.LayoutParams(dp(64), dp(44));
        hlp.setMargins(dp(4), dp(4), dp(4), dp(4));
        hideText.setLayoutParams(hlp);
        hideText.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                InputMethodManager imm = (InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
                if (imm != null) imm.hideSoftInputFromWindow(textField.getWindowToken(), 0);
                textRow.setVisibility(View.GONE);
            }
        });
        textRow.addView(hideText);
        root.addView(textRow);

        youtubeSection = new LinearLayout(this);
        youtubeSection.setOrientation(LinearLayout.VERTICAL);
        LinearLayout ytSeek = row();
        Button ytBack10 = makeButton("-10s", BTN, TEXT, 46, 13);
        click(ytBack10, "key:89");
        ytSeek.addView(ytBack10);
        Button ytFwd10 = makeButton("+10s", BTN, TEXT, 46, 13);
        click(ytFwd10, "key:90");
        ytSeek.addView(ytFwd10);
        youtubeSection.addView(ytSeek);
        addDpad(youtubeSection);
        LinearLayout ytNav = row();
        Button ytBack = makeButton("BACK", BTN, TEXT, 48, 14);
        click(ytBack, "back");
        ytNav.addView(ytBack);
        Button ytHome = makeButton("HOME", BTN, TEXT, 48, 14);
        click(ytHome, "home");
        ytNav.addView(ytHome);
        Button ytPlay = makeButton("PLAY/PAUSE", BTN, TEXT, 48, 10);
        click(ytPlay, "play");
        ytNav.addView(ytPlay);
        youtubeSection.addView(ytNav);
        LinearLayout ytSearch = row();
        ytSearch.addView(makeSearchButton());
        youtubeSection.addView(ytSearch);
        LinearLayout ytApps = row();
        Button ytLaunch = makeButton("YOUTUBE", ACCENT, 0xFF141418, 50, 13);
        ytLaunch.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                send("app:youtube");
                setMode("youtube");
            }
        });
        ytApps.addView(ytLaunch);
        youtubeSection.addView(ytApps);
        root.addView(youtubeSection);

        musicSection = new LinearLayout(this);
        musicSection.setOrientation(LinearLayout.VERTICAL);
        musicNow = new TextView(this);
        musicNow.setText("—");
        musicNow.setTextColor(TEXT);
        musicNow.setTextSize(14);
        musicNow.setSingleLine(true);
        musicNow.setEllipsize(android.text.TextUtils.TruncateAt.END);
        musicNow.setPadding(dp(8), dp(2), dp(8), dp(4));
        musicSection.addView(musicNow);
        LinearLayout musicBtns = row();
        Button prev = makeButton("PREV", BTN, TEXT, 44, 11);
        musicClick(prev, "previous");
        musicBtns.addView(prev);
        Button playPause = makeButton("PLAY/PAUSE", BTN, TEXT, 44, 9);
        musicClick(playPause, "playpause");
        musicBtns.addView(playPause);
        Button next = makeButton("NEXT", BTN, TEXT, 44, 11);
        musicClick(next, "next");
        musicBtns.addView(next);
        Button liked = makeButton("LIKED", ACCENT, 0xFF141418, 44, 10);
        musicClick(liked, "liked");
        musicBtns.addView(liked);
        Button stop = makeButton("STOP", BTN, TEXT, 44, 10);
        musicClick(stop, "stop");
        musicBtns.addView(stop);
        musicSection.addView(musicBtns);
        LinearLayout musicSeek = row();
        Button musicBack10 = makeButton("-10s", BTN, TEXT, 44, 13);
        musicClick(musicBack10, "seekback");
        musicSeek.addView(musicBack10);
        Button musicFwd10 = makeButton("+10s", BTN, TEXT, 44, 13);
        musicClick(musicFwd10, "seekfwd");
        musicSeek.addView(musicFwd10);
        musicSection.addView(musicSeek);
        root.addView(musicSection);

        tvSection = new LinearLayout(this);
        tvSection.setOrientation(LinearLayout.VERTICAL);
        addDpad(tvSection);
        LinearLayout tvNav = row();
        Button tvBack = makeButton("BACK", BTN, TEXT, 48, 14);
        click(tvBack, "back");
        tvNav.addView(tvBack);
        Button tvHome = makeButton("HOME", BTN, TEXT, 48, 14);
        click(tvHome, "home");
        tvNav.addView(tvHome);
        Button tvRecents = makeButton("RECENTS", BTN, TEXT, 48, 12);
        click(tvRecents, "recents");
        tvNav.addView(tvRecents);
        tvSection.addView(tvNav);
        LinearLayout tvApps = row();
        Button tvLaunch = makeButton("TV", ACCENT, 0xFF141418, 50, 14);
        tvLaunch.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                send("app:tv");
                setMode("tv");
            }
        });
        tvApps.addView(tvLaunch);
        Button tvSettings = makeButton("SETTINGS", BTN, TEXT, 50, 12);
        click(tvSettings, "app:settings");
        tvApps.addView(tvSettings);
        tvSection.addView(tvApps);

        LinearLayout tpHdr = row();
        TextView tpTitle = new TextView(this);
        tpTitle.setText("TOUCHPAD");
        tpTitle.setTextColor(MUTED);
        tpTitle.setTextSize(12);
        tpTitle.setTypeface(null, android.graphics.Typeface.BOLD);
        tpTitle.setLayoutParams(new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        tpHdr.addView(tpTitle);
        final Button tpHide = new Button(this);
        tpHide.setTextSize(11);
        tpHide.setTextColor(TEXT);
        tpHide.setBackground(buttonBg(0xFF2A2A35, BTN_DOWN));
        tpHide.setLayoutParams(new LinearLayout.LayoutParams(dp(120), dp(36)));
        tpHdr.addView(tpHide);
        tvSection.addView(tpHdr);

        final TouchpadView touchpad = new TouchpadView(this);
        touchpad.setBackground(bg(0xFF121218, 16));
        LinearLayout.LayoutParams tpLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(190));
        tpLp.setMargins(dp(4), dp(4), dp(4), dp(8));
        touchpad.setLayoutParams(tpLp);
        tvSection.addView(touchpad);
        final SharedPreferences tpPrefs = getSharedPreferences("remote", MODE_PRIVATE);
        boolean tpVisible = tpPrefs.getBoolean("touchpad_visible", true);
        touchpad.setVisibility(tpVisible ? View.VISIBLE : View.GONE);
        tpHide.setText(tpVisible ? "СКРЫТЬ" : "ПОКАЗАТЬ");
        tpHide.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                boolean vis = touchpad.getVisibility() != View.VISIBLE;
                touchpad.setVisibility(vis ? View.VISIBLE : View.GONE);
                tpHide.setText(vis ? "СКРЫТЬ" : "ПОКАЗАТЬ");
                tpPrefs.edit().putBoolean("touchpad_visible", vis).apply();
            }
        });
        root.addView(tvSection);

        LinearLayout vol = row();
        Button voldown = makeButton("VOL-", BTN, TEXT, 48, 14);
        repeat(voldown, "voldown");
        vol.addView(voldown);
        Button mute = makeButton("MUTE", BTN, TEXT, 48, 14);
        click(mute, "mute");
        vol.addView(mute);
        Button volup = makeButton("VOL+", BTN, TEXT, 48, 14);
        repeat(volup, "volup");
        vol.addView(volup);
        root.addView(vol);

        LinearLayout notif = row();
        Button notifdown = makeButton("NOTIF-", BTN, TEXT, 44, 13);
        repeat(notifdown, "notifdown");
        notif.addView(notifdown);
        Button notifmute = makeButton("NOTIF MUTE", BTN, TEXT, 44, 11);
        click(notifmute, "notifmute");
        notif.addView(notifmute);
        Button notifup = makeButton("NOTIF+", BTN, TEXT, 44, 13);
        repeat(notifup, "notifup");
        notif.addView(notifup);
        root.addView(notif);

        volStatus = new TextView(this);
        volStatus.setText("Медиа —   Уведомления —");
        volStatus.setTextColor(MUTED);
        volStatus.setTextSize(12);
        volStatus.setPadding(dp(8), dp(2), dp(8), dp(6));
        root.addView(volStatus);

        LinearLayout sys = row();
        sysStatus = new TextView(this);
        sysStatus.setText("CPU — · RAM — · Wi-Fi —");
        sysStatus.setTextColor(MUTED);
        sysStatus.setTextSize(12);
        sysStatus.setPadding(dp(8), dp(2), dp(4), dp(6));
        sysStatus.setLayoutParams(new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        sys.addView(sysStatus);
        Button clean = makeButton("CLEAN RAM", BTN, TEXT, 40, 11);
        click(clean, "clean");
        sys.addView(clean);
        root.addView(sys);

        settingsRow = new LinearLayout(this);
        settingsRow.setOrientation(LinearLayout.VERTICAL);
        settingsRow.setVisibility(View.GONE);
        hostField = new EditText(this);
        hostField.setHint("station ip");
        hostField.setTextColor(TEXT);
        hostField.setHintTextColor(MUTED);
        hostField.setTextSize(15);
        hostField.setSingleLine(true);
        hostField.setInputType(InputType.TYPE_CLASS_TEXT);
        hostField.setLayoutParams(new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(48)));
        hostField.setText(getSharedPreferences("remote", MODE_PRIVATE)
                .getString("host", DEFAULT_HOST));
        settingsRow.addView(hostField);

        mediaField = new EditText(this);
        mediaField.setHint("media server ip (visualizer)");
        mediaField.setTextColor(TEXT);
        mediaField.setHintTextColor(MUTED);
        mediaField.setTextSize(15);
        mediaField.setSingleLine(true);
        mediaField.setInputType(InputType.TYPE_CLASS_TEXT);
        mediaField.setLayoutParams(new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(48)));
        mediaField.setText(getSharedPreferences("remote", MODE_PRIVATE)
                .getString("media_host", DEFAULT_MEDIA_HOST));
        settingsRow.addView(mediaField);

        Button save = makeButton("SAVE", 0xFF2A2A35, TEXT, 48, 13);
        save.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                String h = hostField.getText().toString().trim();
                if (h.length() == 0) h = DEFAULT_HOST;
                String m = mediaField.getText().toString().trim();
                if (m.length() == 0) m = DEFAULT_MEDIA_HOST;
                getSharedPreferences("remote", MODE_PRIVATE).edit()
                        .putString("host", h)
                        .putString("media_host", m)
                        .apply();
                if (client != null) client.setHost(h);
                if (mouseClient != null) mouseClient.setHost(h);
                settingsRow.setVisibility(View.GONE);
                Toast.makeText(MainActivity.this,
                        "Station: " + h + "  Media: " + m,
                        Toast.LENGTH_SHORT).show();
            }
        });
        settingsRow.addView(save);
        root.addView(settingsRow);

        root.setLayoutParams(new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(BG);
        scroll.addView(root);
        setContentView(scroll);

        setMode(getSharedPreferences("remote", MODE_PRIVATE).getString("mode", "music"));
    }

    private void styleMode(Button b, boolean active) {
        b.setBackground(buttonBg(active ? ACCENT : BTN, BTN_DOWN));
        b.setTextColor(active ? 0xFF141418 : TEXT);
    }

    private void setMode(String m) {
        if (!"youtube".equals(m) && !"tv".equals(m)) m = "music";
        mode = m;
        youtubeSection.setVisibility("youtube".equals(m) ? View.VISIBLE : View.GONE);
        musicSection.setVisibility("music".equals(m) ? View.VISIBLE : View.GONE);
        tvSection.setVisibility("tv".equals(m) ? View.VISIBLE : View.GONE);
        styleMode(modeYoutube, "youtube".equals(m));
        styleMode(modeMusic, "music".equals(m));
        styleMode(modeTv, "tv".equals(m));
        getSharedPreferences("remote", MODE_PRIVATE).edit().putString("mode", m).apply();
    }

    private void addDpad(LinearLayout parent) {
        LinearLayout r1 = row();
        addSpacer(r1);
        Button up = makeButton("\u25B2", BTN, TEXT, 56, 20);
        repeat(up, "up");
        r1.addView(up);
        addSpacer(r1);
        parent.addView(r1);

        LinearLayout r2 = row();
        Button left = makeButton("\u25C0", BTN, TEXT, 56, 20);
        repeat(left, "left");
        r2.addView(left);
        Button ok = makeButton("OK", ACCENT, 0xFF141418, 56, 18);
        click(ok, "ok");
        r2.addView(ok);
        Button right = makeButton("\u25B6", BTN, TEXT, 56, 20);
        repeat(right, "right");
        r2.addView(right);
        parent.addView(r2);

        LinearLayout r3 = row();
        addSpacer(r3);
        Button down = makeButton("\u25BC", BTN, TEXT, 56, 20);
        repeat(down, "down");
        r3.addView(down);
        addSpacer(r3);
        parent.addView(r3);
    }

    private Button makeSearchButton() {
        Button keyboard = makeButton("SEARCH / KEYBOARD", ACCENT, 0xFF141418, 48, 11);
        keyboard.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                send("key:84");
                textRow.setVisibility(View.VISIBLE);
                textField.requestFocus();
                InputMethodManager imm = (InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
                if (imm != null) imm.showSoftInput(textField, InputMethodManager.SHOW_IMPLICIT);
            }
        });
        return keyboard;
    }

    private void send(String cmd) {
        if (client != null) client.send(cmd);
    }

    private void sendMouse(String cmd) {
        if (mouseClient != null) mouseClient.send(cmd);
    }

    private void sendVoice() {
        final String host = hostField.getText().toString().trim();
        new Thread(new Runnable() {
            @Override
            public void run() {
                Socket s = null;
                try {
                    s = new Socket();
                    s.connect(new InetSocketAddress(host, 8094), 1500);
                    s.getOutputStream().write("press\n".getBytes("UTF-8"));
                    s.getOutputStream().flush();
                } catch (Exception ignored) {
                } finally {
                    if (s != null) try { s.close(); } catch (Exception ignored) { }
                }
            }
        }, "push-to-talk").start();
    }

    private class TouchpadView extends View {
        private final android.graphics.Paint paint =
                new android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG);
        private float lastX, lastY, total;
        private long downAt;
        private final float sens = 1.6f;

        TouchpadView(android.content.Context context) {
            super(context);
            setClickable(true);
        }

        @Override
        protected void onDraw(android.graphics.Canvas canvas) {
            super.onDraw(canvas);
            paint.setStyle(android.graphics.Paint.Style.STROKE);
            paint.setStrokeWidth(dp(1));
            paint.setColor(0xFF2A2A35);
            canvas.drawRoundRect(new android.graphics.RectF(
                    dp(1), dp(1), getWidth() - dp(1), getHeight() - dp(1)),
                    dp(15), dp(15), paint);
            paint.setStyle(android.graphics.Paint.Style.FILL);
            paint.setColor(MUTED);
            paint.setTextSize(dp(13));
            paint.setTextAlign(android.graphics.Paint.Align.CENTER);
            canvas.drawText("Двигай курсор · тап = клик",
                    getWidth() / 2f, getHeight() / 2f, paint);
        }

        @Override
        public boolean onTouchEvent(MotionEvent e) {
            int a = e.getActionMasked();
            if (a == MotionEvent.ACTION_DOWN) {
                lastX = e.getX();
                lastY = e.getY();
                total = 0;
                downAt = System.currentTimeMillis();
                getParent().requestDisallowInterceptTouchEvent(true);
                return true;
            }
            if (a == MotionEvent.ACTION_MOVE) {
                float dx = e.getX() - lastX;
                float dy = e.getY() - lastY;
                lastX = e.getX();
                lastY = e.getY();
                total += Math.abs(dx) + Math.abs(dy);
                if (Math.abs(dx) >= 0.5f || Math.abs(dy) >= 0.5f) {
                    sendMouse("m:" + Math.round(dx * sens) + "," + Math.round(dy * sens));
                }
                return true;
            }
            if (a == MotionEvent.ACTION_UP || a == MotionEvent.ACTION_CANCEL) {
                getParent().requestDisallowInterceptTouchEvent(false);
                if (a == MotionEvent.ACTION_UP && total < dp(10)
                        && System.currentTimeMillis() - downAt < 350) {
                    sendMouse("click");
                    performClick();
                }
                return true;
            }
            return super.onTouchEvent(e);
        }

        @Override
        public boolean performClick() {
            return super.performClick();
        }
    }

    /** Single TCP connection to the station; commands are queued and written as fast as possible. */
    static class RemoteClient implements Runnable {
        interface Listener {
            void onStatus(boolean connected);
        }

        private final LinkedBlockingQueue<String> queue = new LinkedBlockingQueue<String>();
        private final Listener listener;
        private final int port;
        private volatile String host;
        private volatile boolean running = true;
        private volatile Socket socket;
        private Thread thread;
        private BufferedWriter out;
        private BufferedReader in;

        RemoteClient(String host, Listener listener, int port) {
            this.host = host;
            this.listener = listener;
            this.port = port;
        }

        void start() {
            thread = new Thread(this, "station-remote");
            thread.setDaemon(true);
            thread.start();
        }

        void stop() {
            running = false;
            close();
        }

        void setHost(String h) {
            host = h;
            close();
        }

        void send(String cmd) {
            queue.offer(cmd);
        }

        private synchronized void close() {
            try { if (socket != null) socket.close(); } catch (Exception e) { }
            socket = null;
            out = null;
            in = null;
        }

        private synchronized void connect() throws Exception {
            Socket s = new Socket();
            s.connect(new InetSocketAddress(host, port), 3000);
            s.setTcpNoDelay(true);
            socket = s;
            out = new BufferedWriter(new OutputStreamWriter(s.getOutputStream(), "UTF-8"));
            in = new BufferedReader(new InputStreamReader(s.getInputStream(), "UTF-8"));
            if (listener != null) listener.onStatus(true);
        }

        public void run() {
            while (running) {
                try {
                    if (socket == null) connect();
                    String cmd = queue.poll(5, TimeUnit.SECONDS);
                    if (cmd == null) cmd = "ping";
                    try {
                        out.write(cmd);
                        out.newLine();
                        out.flush();
                        while (in != null && in.ready()) {
                            String line = in.readLine();
                            if (line == null) throw new java.io.IOException("eof");
                        }
                    } catch (Exception e) {
                        close();
                        if (listener != null) listener.onStatus(false);
                        if (!"ping".equals(cmd) && queue.size() < 8) queue.offer(cmd);
                        Thread.sleep(300);
                    }
                } catch (InterruptedException ie) {
                    break;
                } catch (Exception e) {
                    close();
                    if (listener != null) listener.onStatus(false);
                    try { Thread.sleep(500); } catch (InterruptedException ie) { break; }
                }
            }
        }
    }
}
