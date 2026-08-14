"""Tkinter GUI for the Vakuu STS2 agent.

A thin shell around the terminal harness: it launches ``main.py`` as a
subprocess and renders its unchanged ANSI-colored stdout as a live trace.
The colors the loop already prints are the protocol — magenta is the model's
voice, bold green is a tool call, dim is status chatter — so the harness
needs no GUI hooks and terminal behavior stays identical.

Run with:  python gui.py
"""

import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from client import GameClient

GAME_URL = "http://localhost:58232"

PROVIDERS = {
    "claude":   {"env": "ANTHROPIC_API_KEY", "model": "claude-sonnet-4-20250514"},
    "openai":   {"env": "OPENAI_API_KEY",    "model": "gpt-4o"},
    "deepseek": {"env": "DEEPSEEK_API_KEY",  "model": "deepseek-chat"},
}

EFFORT_LEVELS = {
    "low",
    "medium",
    "high",
    "xhigh",
    "max"
}

# Palette — echoes the terminal banner sprite.
BG        = "#181a26"
BG_PANEL  = "#1f2233"
BG_FIELD  = "#12141d"
BG_BTN    = "#2a2e44"
BG_BTN_HI = "#3a3f5c"
FG        = "#c9d2e8"
FG_DIM    = "#5d6785"
C_RED     = "#e86e52"
C_GREEN   = "#7ee787"
C_YELLOW  = "#ffc440"
C_MAGENTA = "#cf9bdd"
C_CYAN    = "#56c8d8"
C_HDR     = "#9d86b8"

# A thinking block longer than this (or spanning multiple lines) gets a
# collapsible widget; terse one-liners render inline like the terminal.
INLINE_THINK_MAX = 120

SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")
FG_TAGS = {31: "red", 32: "green", 33: "yellow", 35: "magenta", 36: "cyan"}


class AnsiParser:
    """Line-oriented interpreter for the agent's ANSI stream.

    Emits ("spans", [(text, tags), ...]) for ordinary lines and
    ("think", text) for each complete magenta block. SGR state persists
    across lines, so multi-line colored prints (death banner, model text)
    keep their color without per-line markers.
    """

    def __init__(self):
        self.fg = None
        self.bold = False
        self.dim = False
        self._think = None  # accumulating lines of an open magenta block

    def _apply(self, params: str):
        codes = [int(c) for c in params.split(";") if c] or [0]
        i = 0
        while i < len(codes):
            c = codes[i]
            if c == 0:
                self.fg, self.bold, self.dim = None, False, False
            elif c == 1:
                self.bold = True
            elif c == 2:
                self.dim = True
            elif c in (38, 48):  # extended color — skip its arguments
                i += 4 if i + 1 < len(codes) and codes[i + 1] == 2 else 2
                continue
            elif 30 <= c <= 37:
                self.fg = c
            i += 1

    def _tags(self):
        tags = []
        if self.fg in FG_TAGS:
            tags.append(FG_TAGS[self.fg])
        if self.bold:
            tags.append("bold")
        if self.dim:
            tags.append("dim")
        return tuple(tags)

    def feed(self, line: str) -> list[tuple]:
        # Truecolor half-block art (the banner sprite) isn't trace content.
        # Every art line ends with a reset, so clearing state keeps us honest.
        if "\x1b[38;2;" in line or "\x1b[48;2;" in line:
            self.fg, self.bold, self.dim = None, False, False
            return []

        # Model text: print(f"{MAGENTA}{text}{RESET}") — starts a line with
        # the magenta code and holds it until the closing reset.
        if self._think is None and line.startswith("\x1b[35m"):
            self._think = []
        if self._think is not None:
            self._think.append(SGR_RE.sub("", line))
            for m in SGR_RE.finditer(line):
                self._apply(m.group(1))
            if self.fg != 35:
                text = "\n".join(self._think).strip()
                self._think = None
                return [("think", text)] if text else []
            return []

        spans = []
        pos = 0
        for m in SGR_RE.finditer(line):
            if m.start() > pos:
                spans.append((line[pos:m.start()], self._tags()))
            self._apply(m.group(1))
            pos = m.end()
        if pos < len(line):
            spans.append((line[pos:], self._tags()))
        return [("spans", spans)]


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.proc = None
        self.parser = AnsiParser()
        self._q = queue.Queue()
        self._block_n = 0
        self._paused = False

        root.title("Vakuu — STS2 Agent")
        root.geometry("1120x720")
        root.minsize(1000, 480)
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        fams = set(tkfont.families())
        family = next((f for f in ("Cascadia Mono", "Consolas", "Courier New")
                       if f in fams), "TkFixedFont")
        self.mono = tkfont.Font(family=family, size=10)
        self.mono_bold = tkfont.Font(family=family, size=10, weight="bold")
        ui = next((f for f in ("Segoe UI", "Helvetica") if f in fams), "TkDefaultFont")
        self.ui_font = tkfont.Font(family=ui, size=10)

        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=BG_FIELD, background=BG_BTN,
                        foreground=FG, arrowcolor=FG, bordercolor=BG_BTN,
                        lightcolor=BG_PANEL, darkcolor=BG_PANEL,
                        selectbackground=BG_FIELD, selectforeground=FG)
        style.map("TCombobox", fieldbackground=[("readonly", BG_FIELD)],
                  foreground=[("readonly", FG)])
        root.option_add("*TCombobox*Listbox.background", BG_FIELD)
        root.option_add("*TCombobox*Listbox.foreground", FG)
        root.option_add("*TCombobox*Listbox.selectBackground", BG_BTN)
        root.option_add("*TCombobox*Listbox.selectForeground", FG)

        self._build_header()
        self._build_controls()
        self._build_trace()

        self.check_connection()
        self.root.after(60, self._poll)

    # --- UI construction ---

    def _label(self, parent, text, **kw):
        kw.setdefault("bg", BG_PANEL)
        kw.setdefault("fg", FG_DIM)
        kw.setdefault("font", self.ui_font)
        return tk.Label(parent, text=text, **kw)

    def _button(self, parent, text, command, **kw):
        kw.setdefault("bg", BG_BTN)
        kw.setdefault("fg", FG)
        return tk.Button(parent, text=text, command=command,
                         activebackground=BG_BTN_HI, activeforeground=FG,
                         disabledforeground=FG_DIM, relief="flat",
                         font=self.ui_font, padx=14, pady=2, cursor="hand2", **kw)

    def _build_header(self):
        bar = tk.Frame(self.root, bg=BG_PANEL)
        bar.pack(fill="x")
        self.conn_dot = tk.Label(bar, text="●", bg=BG_PANEL, fg=FG_DIM,
                                 font=self.ui_font)
        self.conn_dot.pack(side="left", padx=(10, 2), pady=6)
        self.conn_label = self._label(bar, "checking for game…", fg=FG)
        self.conn_label.pack(side="left")
        self._button(bar, "Refresh", self.check_connection).pack(
            side="left", padx=12)
        self.run_label = self._label(bar, "")
        self.run_label.pack(side="right", padx=12)

    def _build_controls(self):
        panel = tk.Frame(self.root, bg=BG_PANEL, padx=10, pady=6)
        panel.pack(fill="x")

        self._label(panel, "Provider").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.provider_var = tk.StringVar(value="claude")
        self.provider_box = ttk.Combobox(
            panel, textvariable=self.provider_var, state="readonly",
            values=list(PROVIDERS), width=10, font=self.ui_font)
        self.provider_box.grid(row=0, column=1, padx=(0, 12))
        self.provider_box.bind("<<ComboboxSelected>>", self._on_provider_change)

        self._label(panel, "Model").grid(row=0, column=2, sticky="w", padx=(0, 4))
        self.model_var = tk.StringVar(value=PROVIDERS["claude"]["model"])
        self.model_entry = self._entry(panel, self.model_var, width=26)
        self.model_entry.grid(row=0, column=3, padx=(0, 12))

        self._label(panel, "Effort").grid(row=0, column=4, sticky="w", padx=(0, 4))
        self.effort_var = tk.StringVar(value="medium")
        self.effort_box = ttk.Combobox(
            panel, textvariable=self.effort_var, state="readonly",
            values=list(EFFORT_LEVELS), width=10, font=self.ui_font)
        self.effort_box.grid(row=0, column=5, padx=(0, 12))
        self.effort_box.bind("<<ComboboxSelected>>", self._on_effort_change)

        self._label(panel, "API key").grid(row=1, column=0, sticky="w", padx=(0, 4), pady=(16, 16))
        self.key_var = tk.StringVar()
        self.key_entry = self._entry(panel, self.key_var, width=22, show="•")
        self.key_entry.grid(row=1, column=1, padx=(0, 8), pady=(4, 4))
        self.key_hint = self._label(panel, "")
        self.key_hint.grid(row=1, column=2, columnspan=2, sticky="w")

        toggles = tk.Frame(panel, bg=BG_PANEL)
        toggles.grid(row=2, column=0, columnspan=4, sticky="w", pady=(4, 0))
        self.tts_var = tk.BooleanVar(value=False)
        self.verbose_var = tk.BooleanVar(value=True)
        self.tts_check = self._check(
            toggles, "TTS narration", self.tts_var,
            command=lambda: self._send_toggle("tts", self.tts_var))
        self.tts_check.pack(side="left", padx=(0, 12))
        self.verbose_check = self._check(
            toggles, "Verbose", self.verbose_var,
            command=lambda: self._send_toggle("verbose", self.verbose_var))
        self.verbose_check.pack(side="left")

        btns = tk.Frame(panel, bg=BG_PANEL)
        btns.grid(row=2, column=6, sticky="e", padx=(8, 0), pady=(4, 0))
        panel.grid_columnconfigure(6, weight=1)
        self.start_btn = self._button(btns, "Start Run", self.start_run,
                                      bg="#2c4a3a", fg=C_GREEN)
        self.start_btn.pack(side="left", padx=(0, 6))
        self.pause_btn = self._button(btns, "Pause", self.pause_run,
                                      state="disabled")
        self.pause_btn.pack(side="left", padx=(0, 6))
        self.stop_btn = self._button(btns, "Stop", self.stop_run, state="disabled")
        self.stop_btn.pack(side="left")

        self._on_provider_change()

    def _entry(self, parent, var, **kw):
        return tk.Entry(parent, textvariable=var, bg=BG_FIELD, fg=FG,
                        insertbackground=FG, relief="flat",
                        highlightthickness=1, highlightbackground=BG_BTN,
                        highlightcolor=C_CYAN, font=self.ui_font,
                        disabledbackground=BG_PANEL, **kw)

    def _check(self, parent, text, var, command=None):
        return tk.Checkbutton(parent, text=text, variable=var, bg=BG_PANEL,
                              fg=FG, activebackground=BG_PANEL,
                              activeforeground=FG, selectcolor=BG_FIELD,
                              disabledforeground=FG_DIM, font=self.ui_font,
                              command=command)

    def _build_trace(self):
        frame = tk.Frame(self.root, bg=BG)
        frame.pack(fill="both", expand=True)
        self.text = tk.Text(frame, bg=BG_FIELD, fg=FG, font=self.mono,
                            relief="flat", padx=10, pady=8, wrap="word",
                            state="disabled", insertbackground=FG,
                            selectbackground="#33405e", selectforeground=FG)
        sb = tk.Scrollbar(frame, command=self.text.yview, troughcolor=BG,
                          bg=BG_BTN, activebackground=BG_BTN_HI)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)

        t = self.text
        t.tag_configure("red", foreground=C_RED)
        t.tag_configure("green", foreground=C_GREEN)
        t.tag_configure("yellow", foreground=C_YELLOW)
        t.tag_configure("magenta", foreground=C_MAGENTA)
        t.tag_configure("cyan", foreground=C_CYAN)
        t.tag_configure("bold", font=self.mono_bold)
        t.tag_configure("dim", foreground=FG_DIM)  # after colors — dim wins
        t.tag_configure("think_hdr", foreground=C_HDR)
        t.tag_configure("think_meta", foreground=FG_DIM)
        t.tag_configure("think_body", foreground=C_MAGENTA,
                        lmargin1=24, lmargin2=24)

    # --- trace rendering ---

    def _append(self, fn):
        """Run an insert function with the widget writable, then restore
        read-only state and keep the view pinned to the bottom if it was."""
        t = self.text
        at_bottom = t.yview()[1] >= 0.999
        t.config(state="normal")
        fn()
        # Cap scrollback so day-long runs don't bog the widget down.
        if int(t.index("end-1c").split(".")[0]) > 15000:
            t.delete("1.0", "3000.0")
        t.config(state="disabled")
        if at_bottom:
            t.see("end")

    def _insert_spans(self, spans):
        def go():
            for text, tags in spans:
                if text:
                    self.text.insert("end", text, tags)
            self.text.insert("end", "\n")
        self._append(go)

    def _insert_sys(self, msg, tags=("dim",)):
        self._append(lambda: self.text.insert("end", msg + "\n", tags))

    def _insert_think(self, text):
        lines = text.split("\n")
        if len(lines) == 1 and len(text) <= INLINE_THINK_MAX:
            self._insert_spans([(text, ("magenta",))])
            return
        self._block_n += 1
        hdr_tag, body_tag = f"hdr{self._block_n}", f"body{self._block_n}"
        preview = lines[0][:90] + ("…" if len(lines[0]) > 90 else "")

        def go():
            t = self.text
            t.insert("end", f"▸ {preview}", ("think_hdr", hdr_tag))
            n = len(lines)
            t.insert("end", f"  ({n} line{'s' if n != 1 else ''})\n",
                     ("think_meta", hdr_tag))
            t.insert("end", text + "\n", ("think_body", body_tag))
            t.tag_configure(body_tag, elide=True)
            t.tag_bind(hdr_tag, "<Button-1>",
                       lambda e: self._toggle_think(hdr_tag, body_tag))
            t.tag_bind(hdr_tag, "<Enter>", lambda e: t.config(cursor="hand2"))
            t.tag_bind(hdr_tag, "<Leave>", lambda e: t.config(cursor=""))
        self._append(go)

    def _toggle_think(self, hdr_tag, body_tag):
        t = self.text
        hidden = t.tag_cget(body_tag, "elide") in ("1", "true", "True")
        t.tag_configure(body_tag, elide=not hidden)
        r = t.tag_ranges(hdr_tag)
        if r:
            t.config(state="normal")
            t.delete(r[0], f"{r[0]}+1c")
            t.insert(r[0], "▾" if hidden else "▸", ("think_hdr", hdr_tag))
            t.config(state="disabled")

    # --- connection check ---

    def check_connection(self):
        self.conn_dot.config(fg=FG_DIM)
        self.conn_label.config(text="checking for game…", fg=FG_DIM)

        def work():
            try:
                client = GameClient(base_url=GAME_URL, timeout=3.0)
                client.health()
                try:
                    state = client.get_state()
                except Exception:
                    state = {}
                if state.get("error"):
                    result = (C_YELLOW, f"connected — {state['error'].lower()}")
                else:
                    screen = state.get("screen", "?")
                    floor = state.get("floor", "?")
                    result = (C_GREEN,
                              f"connected — {screen}, floor {floor}")
            except Exception:
                result = (C_RED, f"no game detected at {GAME_URL}")
            self._q.put(("conn", result))
        threading.Thread(target=work, daemon=True).start()

    # --- run control ---

    def _build_cmd(self, provider, model, effort, verbose, tts):
        cmd = [sys.executable, "-u", os.path.join(SCRIPT_DIR, "main.py"),
               "--provider", provider, "--model", model, "--effort", effort]
        if verbose:
            cmd.append("--verbose")
        if tts:
            cmd.append("--tts")
        return cmd

    def start_run(self):
        if self.proc and self.proc.poll() is None:
            return
        provider = self.provider_var.get()
        model = self.model_var.get().strip() or PROVIDERS[provider]["model"]
        effort = self.effort_var.get().strip()
        key = self.key_var.get().strip()
        env_name = PROVIDERS[provider]["env"]

        if not key and not os.environ.get(env_name):
            self.key_entry.config(highlightbackground=C_RED,
                                  highlightcolor=C_RED)
            self.key_hint.config(text=f"API key required — {env_name} is not set",
                                 fg=C_RED)
            self.key_entry.focus_set()
            return
        self.key_entry.config(highlightbackground=BG_BTN, highlightcolor=C_CYAN)

        env = dict(os.environ, PYTHONUNBUFFERED="1")
        if key:
            env[env_name] = key
        cmd = self._build_cmd(provider, model, effort,
                              self.verbose_var.get(), self.tts_var.get())
        shown = " ".join(os.path.basename(c) if os.path.sep in c else c
                         for c in cmd[2:])
        self._insert_sys(f"\n── $ {shown} ──")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            self.proc = subprocess.Popen(
                cmd, cwd=SCRIPT_DIR, env=env, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, stdin=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
                creationflags=flags)
        except OSError as e:
            self._insert_sys(f"failed to launch agent: {e}", ("red",))
            return
        self.parser = AnsiParser()
        threading.Thread(target=self._reader, args=(self.proc,),
                         daemon=True).start()
        self._set_running(True)

    def stop_run(self):
        """Hard stop — ends the agent session immediately."""
        if self.proc and self.proc.poll() is None:
            self._insert_sys("— stopping agent —")
            self.proc.terminate()

    def pause_run(self):
        """Pause/resume the loop without losing any context. Pausing takes
        effect at the agent's next loop boundary (after the current action
        settles); resuming picks up exactly where it left off."""
        if not (self.proc and self.proc.poll() is None):
            return
        self._paused = not self._paused
        self._send_cmd(f"pause {'on' if self._paused else 'off'}")
        self.pause_btn.config(text="Resume" if self._paused else "Pause")
        self.run_label.config(
            text="⏸ pausing…" if self._paused else "● running",
            fg=C_YELLOW if self._paused else C_GREEN)

    def _send_cmd(self, cmd: str) -> bool:
        """Write a line to the running agent's stdin control channel."""
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.write(cmd + "\n")
                self.proc.stdin.flush()
                return True
            except OSError:
                pass
        return False

    def _send_toggle(self, name, var):
        """Forward a toggle to the running agent over its stdin control
        channel. When idle, the checkbox just sets the next run's flags."""
        self._send_cmd(f"{name} {'on' if var.get() else 'off'}")

    def _reader(self, proc):
        for line in proc.stdout:
            self._q.put(("line", line.rstrip("\r\n")))
        self._q.put(("exit", proc.wait()))

    def _set_running(self, running: bool):
        self.start_btn.config(state="disabled" if running else "normal")
        self.stop_btn.config(state="normal" if running else "disabled")
        self.pause_btn.config(state="normal" if running else "disabled",
                              text="Pause")
        self._paused = False
        field_state = "disabled" if running else "normal"
        for w in (self.model_entry, self.key_entry):
            w.config(state=field_state)
        self.provider_box.config(state="disabled" if running else "readonly")
        if running:
            self.run_label.config(text="● running", fg=C_GREEN)

    # --- event pump ---

    def _poll(self):
        try:
            for _ in range(300):
                kind, payload = self._q.get_nowait()
                if kind == "line":
                    if self._paused and "(paused)" in payload:
                        self.run_label.config(text="⏸ paused", fg=C_YELLOW)
                    for ev, data in self.parser.feed(payload):
                        if ev == "think":
                            self._insert_think(data)
                        else:
                            self._insert_spans(data)

                elif kind == "exit":
                    self._insert_sys(f"— agent exited (code {payload}) —")
                    self.run_label.config(
                        text=f"exited ({payload})",
                        fg=FG_DIM if payload == 0 else C_RED)
                    self.proc = None
                    self._set_running(False)
                elif kind == "conn":
                    color, msg = payload
                    self.conn_dot.config(fg=color)
                    self.conn_label.config(text=msg, fg=FG)
        except queue.Empty:
            pass
        self.root.after(60, self._poll)

    # --- misc ---

    def _on_provider_change(self, event=None):
        provider = self.provider_var.get()
        defaults = {p["model"] for p in PROVIDERS.values()}
        if self.model_var.get().strip() in defaults | {""}:
            self.model_var.set(PROVIDERS[provider]["model"])
        env_name = PROVIDERS[provider]["env"]
        if os.environ.get(env_name):
            self.key_hint.config(text=f"{env_name} set", fg=FG_DIM)
        else:
            self.key_hint.config(text=f"{env_name} not set — key required",
                                 fg=C_YELLOW)

    def _on_effort_change(self, event=None):
        pass

    def _on_close(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
