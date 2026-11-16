"""
app.py - Modern High-End Desktop Application for AutoTrade MT5.
Built with CustomTkinter for sleek, contemporary dark-mode UX/UI.
"""

import json
from datetime import datetime
from pathlib import Path
import queue
import subprocess
import sys
import threading
from tkinter import filedialog, messagebox

try:
    import customtkinter as ctk
except ImportError:
    print("customtkinter is required. Install via: pip install customtkinter")
    sys.exit(1)

# Set global modern theme
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

SRC_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SRC_DIR.parent
CRED_JSON_PATH = PROJECT_ROOT / "account_credentials.json"

EXNESS_SERVERS = [
    "Exness-MT5Real",
    "Exness-MT5Real2",
    "Exness-MT5Real3",
    "Exness-MT5Real4",
    "Exness-MT5Real5",
    "Exness-MT5Trial",
    "Exness-MT5Trial2",
    "MetaQuotes-Demo",  # Free built-in MT5 demo server, for testing without a broker account
]

# Symbol suffix auto-filled per server when the user picks one from the dropdown.
# Exness Standard uses "m" (XAUUSDm/BTCUSDm); MetaQuotes-Demo has no suffix (XAUUSD/BTCUSD).
SERVER_SYMBOL_SUFFIXES = {
    "MetaQuotes-Demo": "",
}
DEFAULT_SYMBOL_SUFFIX = "m"


class ModernAutoTradeApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Window Setup
        self.title("AutoTrade MT5 • Exness Production Suite")
        self.geometry("1060, 780")
        self.minsize(920, 680)

        # State Variables
        self.bot_process: subprocess.Popen = None
        self.log_queue = queue.Queue()
        self.is_bot_running = False
        self.show_pwd = False

        # Build Interface
        self.build_ui()
        self.load_account_credentials()

        # Start non-blocking log pump
        self.after(80, self.poll_log_queue)

    def build_ui(self):
        """Builds a contemporary card-based layout with clean typography and hierarchy."""
        self.configure(fg_color="#0b0f19")  # Modern obsidian dark background

        # ----------------- TOP NAVBAR -----------------
        navbar = ctk.CTkFrame(self, fg_color="#111827", corner_radius=0, height=64)
        navbar.pack(fill="x", side="top")
        navbar.pack_propagate(False)

        nav_content = ctk.CTkFrame(navbar, fg_color="transparent")
        nav_content.pack(fill="both", expand=True, padx=24)

        # Brand / Title
        brand_frame = ctk.CTkFrame(nav_content, fg_color="transparent")
        brand_frame.pack(side="left", fill="y")

        logo_label = ctk.CTkLabel(
            brand_frame,
            text="⚡ AUTOTRADE",
            font=ctk.CTkFont(family="Inter", size=18, weight="bold"),
            text_color="#38bdf8"
        )
        logo_label.pack(side="left", pady=16)

        pill_badge = ctk.CTkLabel(
            brand_frame,
            text="Exness $10.00 Micro Edition",
            font=ctk.CTkFont(family="Inter", size=11, weight="bold"),
            fg_color="#1e293b",
            text_color="#94a3b8",
            corner_radius=12,
            padx=10,
            pady=3
        )
        pill_badge.pack(side="left", padx=12, pady=18)

        # Status Badges (Right side)
        status_frame = ctk.CTkFrame(nav_content, fg_color="transparent")
        status_frame.pack(side="right", fill="y")

        self.engine_badge = ctk.CTkLabel(
            status_frame,
            text="● ENGINE STOPPED",
            font=ctk.CTkFont(family="Inter", size=11, weight="bold"),
            fg_color="#271822",
            text_color="#f43f5e",
            corner_radius=12,
            padx=12,
            pady=4
        )
        self.engine_badge.pack(side="right", pady=18)

        # ----------------- MAIN SCROLLABLE/EXPANDABLE BODY -----------------
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=16)

        # TOP ROW: 2 Cards (Credentials Card & Engine Control Card)
        top_row = ctk.CTkFrame(body, fg_color="transparent")
        top_row.pack(fill="x", pady=(0, 14))

        # CARD 1: MT5 Credentials (Left)
        cred_card = ctk.CTkFrame(top_row, fg_color="#131b2e", corner_radius=14, border_width=1, border_color="#1e293b")
        cred_card.pack(side="left", fill="both", expand=True, padx=(0, 10))

        cred_header = ctk.CTkFrame(cred_card, fg_color="transparent")
        cred_header.pack(fill="x", padx=20, pady=(16, 10))

        ctk.CTkLabel(
            cred_header,
            text="🔐 MT5 Broker Credentials",
            font=ctk.CTkFont(family="Inter", size=14, weight="bold"),
            text_color="#f8fafc"
        ).pack(anchor="w")

        ctk.CTkLabel(
            cred_header,
            text="Connect directly to your Exness Standard account",
            font=ctk.CTkFont(family="Inter", size=11),
            text_color="#64748b"
        ).pack(anchor="w")

        # Form Fields
        form_frame = ctk.CTkFrame(cred_card, fg_color="transparent")
        form_frame.pack(fill="x", padx=20, pady=(0, 14))

        # Login
        ctk.CTkLabel(form_frame, text="Account ID (Login):", font=ctk.CTkFont(size=11, weight="bold"), text_color="#cbd5e1").pack(anchor="w", pady=(2, 2))
        self.login_var = ctk.StringVar()
        self.login_entry = ctk.CTkEntry(
            form_frame, textvariable=self.login_var, placeholder_text="e.g. 12345678",
            fg_color="#0a0f1d", border_color="#334155", corner_radius=8, height=36, font=ctk.CTkFont(size=12)
        )
        self.login_entry.pack(fill="x", pady=(0, 8))

        # Password
        ctk.CTkLabel(form_frame, text="Account Password:", font=ctk.CTkFont(size=11, weight="bold"), text_color="#cbd5e1").pack(anchor="w", pady=(2, 2))
        pwd_box = ctk.CTkFrame(form_frame, fg_color="transparent")
        pwd_box.pack(fill="x", pady=(0, 8))

        self.pwd_var = ctk.StringVar()
        self.pwd_entry = ctk.CTkEntry(
            pwd_box, textvariable=self.pwd_var, show="•", placeholder_text="Exness Trading Password",
            fg_color="#0a0f1d", border_color="#334155", corner_radius=8, height=36, font=ctk.CTkFont(size=12)
        )
        self.pwd_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.eye_btn = ctk.CTkButton(
            pwd_box, text="👁", width=38, height=36, corner_radius=8, fg_color="#1e293b",
            hover_color="#334155", text_color="#f8fafc", command=self.toggle_password
        )
        self.eye_btn.pack(side="right")

        # Server
        ctk.CTkLabel(form_frame, text="Server:", font=ctk.CTkFont(size=11, weight="bold"), text_color="#cbd5e1").pack(anchor="w", pady=(2, 2))
        self.server_var = ctk.StringVar(value="Exness-MT5Real")
        self.server_combo = ctk.CTkComboBox(
            form_frame, values=EXNESS_SERVERS, variable=self.server_var,
            fg_color="#0a0f1d", border_color="#334155", button_color="#2563eb", corner_radius=8, height=36, font=ctk.CTkFont(size=12),
            command=self.on_server_selected
        )
        self.server_combo.pack(fill="x", pady=(0, 8))

        # Symbol Suffix
        ctk.CTkLabel(form_frame, text="Symbol Suffix:", font=ctk.CTkFont(size=11, weight="bold"), text_color="#cbd5e1").pack(anchor="w", pady=(2, 2))
        self.suffix_var = ctk.StringVar(value=DEFAULT_SYMBOL_SUFFIX)
        self.suffix_entry = ctk.CTkEntry(
            form_frame, textvariable=self.suffix_var,
            placeholder_text="\"m\" for Exness (XAUUSDm) • blank for MetaQuotes-Demo (XAUUSD)",
            fg_color="#0a0f1d", border_color="#334155", corner_radius=8, height=36, font=ctk.CTkFont(size=12)
        )
        self.suffix_entry.pack(fill="x", pady=(0, 8))

        # Terminal Path (Optional)
        ctk.CTkLabel(form_frame, text="Terminal Path (Optional):", font=ctk.CTkFont(size=11, weight="bold"), text_color="#cbd5e1").pack(anchor="w", pady=(2, 2))
        path_box = ctk.CTkFrame(form_frame, fg_color="transparent")
        path_box.pack(fill="x", pady=(0, 12))

        self.path_var = ctk.StringVar()
        self.path_entry = ctk.CTkEntry(
            path_box, textvariable=self.path_var, placeholder_text="Auto-detected if left blank",
            fg_color="#0a0f1d", border_color="#334155", corner_radius=8, height=36, font=ctk.CTkFont(size=11)
        )
        self.path_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        browse_btn = ctk.CTkButton(
            path_box, text="Browse", width=68, height=36, corner_radius=8, fg_color="#1e293b",
            hover_color="#334155", text_color="#f8fafc", command=self.browse_path
        )
        browse_btn.pack(side="right")

        # Action Buttons
        cred_actions = ctk.CTkFrame(form_frame, fg_color="transparent")
        cred_actions.pack(fill="x", pady=(2, 0))

        self.save_btn = ctk.CTkButton(
            cred_actions, text="💾 Save Account", height=38, corner_radius=8,
            fg_color="#2563eb", hover_color="#1d4ed8", font=ctk.CTkFont(weight="bold"),
            command=self.save_account_credentials
        )
        self.save_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.test_btn = ctk.CTkButton(
            cred_actions, text="🔌 Test Connection", height=38, corner_radius=8,
            fg_color="#0d9488", hover_color="#0f766e", font=ctk.CTkFont(weight="bold"),
            command=self.test_connection
        )
        self.test_btn.pack(side="right", fill="x", expand=True, padx=(6, 0))

        # CARD 2: Bot Engine & Risk Guard (Right)
        ctrl_card = ctk.CTkFrame(top_row, fg_color="#131b2e", corner_radius=14, border_width=1, border_color="#1e293b")
        ctrl_card.pack(side="right", fill="both", expand=True, padx=(10, 0))

        ctrl_header = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        ctrl_header.pack(fill="x", padx=20, pady=(16, 10))

        ctk.CTkLabel(
            ctrl_header,
            text="🚀 Engine & Risk Guard",
            font=ctk.CTkFont(family="Inter", size=14, weight="bold"),
            text_color="#f8fafc"
        ).pack(anchor="w")

        ctk.CTkLabel(
            ctrl_header,
            text="M5 9/21 EMA + 14 RSI on Closed Candles",
            font=ctk.CTkFont(family="Inter", size=11),
            text_color="#64748b"
        ).pack(anchor="w")

        # 4 Mini Metric Cards Grid
        grid_frame = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        grid_frame.pack(fill="x", padx=20, pady=(0, 14))
        grid_frame.columnconfigure((0, 1), weight=1)

        # Tile 1: Gold
        tile1 = ctk.CTkFrame(grid_frame, fg_color="#0d1424", corner_radius=10, border_width=1, border_color="#1e293b")
        tile1.grid(row=0, column=0, sticky="nsew", padx=(0, 5), pady=(0, 6))
        ctk.CTkLabel(tile1, text="🥇 XAUUSDm (Gold)", font=ctk.CTkFont(size=11, weight="bold"), text_color="#facc15").pack(anchor="w", padx=10, pady=(6, 0))
        ctk.CTkLabel(tile1, text="0.01 lot • SL $1.50 • TP $3.00", font=ctk.CTkFont(size=10), text_color="#94a3b8").pack(anchor="w", padx=10, pady=(0, 6))

        # Tile 2: Bitcoin
        tile2 = ctk.CTkFrame(grid_frame, fg_color="#0d1424", corner_radius=10, border_width=1, border_color="#1e293b")
        tile2.grid(row=0, column=1, sticky="nsew", padx=(5, 0), pady=(0, 6))
        ctk.CTkLabel(tile2, text="₿ BTCUSDm (Bitcoin)", font=ctk.CTkFont(size=11, weight="bold"), text_color="#fb923c").pack(anchor="w", padx=10, pady=(6, 0))
        ctk.CTkLabel(tile2, text="0.01 lot • SL $1.50 • TP $3.00", font=ctk.CTkFont(size=10), text_color="#94a3b8").pack(anchor="w", padx=10, pady=(0, 6))

        # Tile 3: Trade Lock
        tile3 = ctk.CTkFrame(grid_frame, fg_color="#0d1424", corner_radius=10, border_width=1, border_color="#1e293b")
        tile3.grid(row=1, column=0, sticky="nsew", padx=(0, 5), pady=(6, 0))
        ctk.CTkLabel(tile3, text="🔒 Single-Trade Lock", font=ctk.CTkFont(size=11, weight="bold"), text_color="#38bdf8").pack(anchor="w", padx=10, pady=(6, 0))
        ctk.CTkLabel(tile3, text="Max 1 Active Position Total", font=ctk.CTkFont(size=10), text_color="#94a3b8").pack(anchor="w", padx=10, pady=(0, 6))

        # Tile 4: Kill-Switch
        tile4 = ctk.CTkFrame(grid_frame, fg_color="#0d1424", corner_radius=10, border_width=1, border_color="#1e293b")
        tile4.grid(row=1, column=1, sticky="nsew", padx=(5, 0), pady=(6, 0))
        ctk.CTkLabel(tile4, text="🛑 Daily Loss Limit", font=ctk.CTkFont(size=11, weight="bold"), text_color="#f87171").pack(anchor="w", padx=10, pady=(6, 0))
        ctk.CTkLabel(tile4, text="Kill-Switch: -$2.00 / day", font=ctk.CTkFont(size=10), text_color="#94a3b8").pack(anchor="w", padx=10, pady=(0, 6))

        # Big CTA Action Buttons
        action_box = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        action_box.pack(fill="x", padx=20, pady=(8, 16))

        self.start_btn = ctk.CTkButton(
            action_box,
            text="▶  START BOT ENGINE",
            height=46,
            corner_radius=10,
            fg_color="#10b981",
            hover_color="#059669",
            font=ctk.CTkFont(family="Inter", size=13, weight="bold"),
            command=self.start_bot
        )
        self.start_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.stop_btn = ctk.CTkButton(
            action_box,
            text="⏹  STOP BOT",
            height=46,
            corner_radius=10,
            fg_color="#f43f5e",
            hover_color="#e11d48",
            font=ctk.CTkFont(family="Inter", size=13, weight="bold"),
            state="disabled",
            command=self.stop_bot
        )
        self.stop_btn.pack(side="right", fill="x", expand=True, padx=(6, 0))

        # ----------------- BOTTOM ROW: LIVE TERMINAL CONSOLE -----------------
        log_card = ctk.CTkFrame(body, fg_color="#131b2e", corner_radius=14, border_width=1, border_color="#1e293b")
        log_card.pack(fill="both", expand=True)

        log_header = ctk.CTkFrame(log_card, fg_color="transparent")
        log_header.pack(fill="x", padx=20, pady=(12, 8))

        ctk.CTkLabel(
            log_header,
            text="📡 Live Activity Stream & Trade Signals",
            font=ctk.CTkFont(family="Inter", size=13, weight="bold"),
            text_color="#f8fafc"
        ).pack(side="left")

        clear_btn = ctk.CTkButton(
            log_header,
            text="Clear Feed",
            width=80,
            height=28,
            corner_radius=6,
            fg_color="#1e293b",
            hover_color="#334155",
            text_color="#94a3b8",
            font=ctk.CTkFont(size=11),
            command=self.clear_logs
        )
        clear_btn.pack(side="right")

        # Terminal Text Box
        self.log_text = ctk.CTkTextbox(
            log_card,
            fg_color="#060913",
            text_color="#cbd5e1",
            font=ctk.CTkFont(family="Menlo" if sys.platform == "darwin" else "Consolas", size=11),
            corner_radius=10,
            border_width=1,
            border_color="#1e293b",
            wrap="word"
        )
        self.log_text.pack(fill="both", expand=True, padx=20, pady=(0, 16))

    def on_server_selected(self, selected_server: str):
        """Auto-fills the symbol suffix for known servers (e.g. blank for MetaQuotes-Demo)."""
        suffix = SERVER_SYMBOL_SUFFIXES.get(selected_server.strip(), DEFAULT_SYMBOL_SUFFIX)
        self.suffix_var.set(suffix)

    def toggle_password(self):
        """Toggles between hidden dots and readable password text."""
        if self.show_pwd:
            self.pwd_entry.configure(show="•")
            self.eye_btn.configure(text="👁", fg_color="#1e293b")
            self.show_pwd = False
        else:
            self.pwd_entry.configure(show="")
            self.eye_btn.configure(text="🔒", fg_color="#334155")
            self.show_pwd = True

    def browse_path(self):
        """Native file picker for terminal64.exe."""
        selected = filedialog.askopenfilename(
            title="Select MetaTrader 5 Terminal Executable",
            filetypes=[("Executable Files", "*.exe"), ("All Files", "*.*")]
        )
        if selected:
            self.path_var.set(selected)

    def load_account_credentials(self):
        """Loads account credentials from account_credentials.json, if previously saved."""
        if CRED_JSON_PATH.exists():
            try:
                with open(CRED_JSON_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("login"):
                    self.login_var.set(str(data.get("login", "")))
                if data.get("password"):
                    self.pwd_var.set(str(data.get("password", "")))
                if data.get("server"):
                    self.server_var.set(str(data.get("server", "Exness-MT5Real")))
                if data.get("path"):
                    self.path_var.set(str(data.get("path", "")))
                if "symbol_suffix" in data:
                    self.suffix_var.set(str(data.get("symbol_suffix", DEFAULT_SYMBOL_SUFFIX)))

                self.append_log("[SUCCESS] Loaded saved account credentials.\n")
                return
            except Exception as e:
                self.append_log(f"[WARNING] Could not read saved credentials: {e}\n")

        self.append_log("[SYSTEM] Ready. Enter your Account ID & Password, then click 'Save Account'.\n")

    def save_account_credentials(self, show_popup: bool = True):
        """Saves current input fields to account_credentials.json."""
        login = self.login_var.get().strip()
        pwd = self.pwd_var.get().strip()
        srv = self.server_var.get().strip()
        path = self.path_var.get().strip()
        suffix = self.suffix_var.get().strip()

        if not login or not pwd or not srv:
            if show_popup:
                messagebox.showwarning("Incomplete Fields", "Please enter your Account ID, Password, and Server.")
            return

        payload = {
            "login": login,
            "password": pwd,
            "server": srv,
            "path": path,
            "symbol_suffix": suffix,
            "updated_at": datetime.now().isoformat()
        }

        try:
            with open(CRED_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)

            self.append_log(f"[SUCCESS] ✅ Account {login} on {srv} saved successfully!\n")

            # Temporary visual confirmation on the button
            self.save_btn.configure(text="✅ Saved!", fg_color="#10b981")
            self.after(2000, lambda: self.save_btn.configure(text="💾 Save Account", fg_color="#2563eb"))

            if show_popup:
                messagebox.showinfo("Saved", "Account credentials saved successfully!")
        except Exception as e:
            self.append_log(f"[ERROR] Failed to save account: {e}\n")
            if show_popup:
                messagebox.showerror("Error", f"Failed to save account: {e}")

    def test_connection(self):
        """Tests MT5 login asynchronously without freezing the UI."""
        self.append_log("[DIAGNOSTIC] Testing MetaTrader 5 connection...\n")
        self.test_btn.configure(state="disabled", text="Testing...")

        def _worker():
            login = self.login_var.get().strip()
            pwd = self.pwd_var.get().strip()
            srv = self.server_var.get().strip()
            path = self.path_var.get().strip()

            try:
                import MetaTrader5 as mt5
                is_sim = False
            except ImportError:
                try:
                    import mock_mt5 as mt5
                    is_sim = True
                except ImportError:
                    mt5 = None
                    is_sim = False

            if mt5 is None:
                self.log_queue.put(("[ERROR] MetaTrader5 is not available.\n"))
                self.after(0, lambda: self.test_btn.configure(state="normal", text="🔌 Test Connection"))
                return

            init_args = {}
            if path:
                init_args["path"] = path

            if not mt5.initialize(**init_args):
                err = mt5.last_error()
                self.log_queue.put(f"[ERROR] MT5 initialize() failed: {err}\n")
                self.after(0, lambda: self.test_btn.configure(state="normal", text="🔌 Test Connection"))
                return

            try:
                acc_id = int(login)
            except ValueError:
                self.log_queue.put("[ERROR] Account Login must be a valid numeric ID.\n")
                mt5.shutdown()
                self.after(0, lambda: self.test_btn.configure(state="normal", text="🔌 Test Connection"))
                return

            ok = mt5.login(login=acc_id, password=pwd, server=srv)
            if not ok:
                err = mt5.last_error()
                self.log_queue.put(f"[ERROR] MT5 login failed for account {acc_id}: {err}\n")
                mt5.shutdown()
                self.after(0, lambda: self.test_btn.configure(state="normal", text="🔌 Test Connection"))
                return

            acc_info = mt5.account_info()
            mt5.shutdown()

            if acc_info is not None:
                sim_note = " (Simulated macOS Environment)" if is_sim else " (Live MT5 Terminal)"
                msg = (
                    f"==================================================\n"
                    f"✅ MT5 CONNECTION VERIFIED{sim_note}!\n"
                    f"Account:        {acc_info.login} ({acc_info.name})\n"
                    f"Server:         {acc_info.server}\n"
                    f"Currency/Bal:   {acc_info.currency} ${acc_info.balance:.2f} | Equity: ${acc_info.equity:.2f}\n"
                    f"Leverage:       1:{acc_info.leverage}\n"
                    f"Trade Allowed:  {acc_info.trade_allowed}\n"
                    f"==================================================\n"
                )
                self.log_queue.put(msg)
            else:
                self.log_queue.put("[WARNING] Authorized, but unable to retrieve account metrics.\n")

            self.after(0, lambda: self.test_btn.configure(state="normal", text="🔌 Test Connection"))

        threading.Thread(target=_worker, daemon=True).start()

    def start_bot(self):
        """Spawns bot.py in a background process and pipes output to terminal."""
        if self.is_bot_running:
            return

        # Auto-save credentials without pop-up
        self.save_account_credentials(show_popup=False)

        python_exec = sys.executable
        venv_py = PROJECT_ROOT / "venv" / "bin" / "python"
        if sys.platform == "win32":
            venv_py = PROJECT_ROOT / "venv" / "Scripts" / "python.exe"

        if venv_py.exists():
            python_exec = str(venv_py)

        bot_script = str(SRC_DIR / "bot.py")

        self.append_log(f"[SYSTEM] Launching AutoTrade engine: {python_exec}...\n")

        try:
            self.bot_process = subprocess.Popen(
                [python_exec, "-u", bot_script],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=str(PROJECT_ROOT)
            )
            self.is_bot_running = True
            self.engine_badge.configure(
                text="● ENGINE RUNNING",
                fg_color="#064e3b",
                text_color="#34d399"
            )
            self.start_btn.configure(state="disabled", fg_color="#1e293b")
            self.stop_btn.configure(state="normal", fg_color="#f43f5e")

            def _reader_thread():
                for line in self.bot_process.stdout:
                    self.log_queue.put(line)
                self.log_queue.put("[SYSTEM] Engine process terminated.\n")
                self.log_queue.put("__BOT_STOPPED__")

            threading.Thread(target=_reader_thread, daemon=True).start()

        except Exception as e:
            self.append_log(f"[ERROR] Could not start engine: {e}\n")
            messagebox.showerror("Launch Error", f"Failed to start bot engine: {e}")

    def stop_bot(self):
        """Terminates active bot subprocess cleanly."""
        if not self.is_bot_running or self.bot_process is None:
            return

        self.append_log("[SYSTEM] Requesting graceful bot shutdown...\n")
        try:
            self.bot_process.terminate()
        except Exception as e:
            self.append_log(f"[ERROR] Termination error: {e}\n")

        self.on_bot_stopped()

    def on_bot_stopped(self):
        """Restores UI controls when bot terminates."""
        self.is_bot_running = False
        self.engine_badge.configure(
            text="● ENGINE STOPPED",
            fg_color="#271822",
            text_color="#f43f5e"
        )
        self.start_btn.configure(state="normal", fg_color="#10b981")
        self.stop_btn.configure(state="disabled", fg_color="#1e293b")

    def poll_log_queue(self):
        """Polls log queue and appends text to the terminal smoothly."""
        while not self.log_queue.empty():
            try:
                line = self.log_queue.get_nowait()
                if line == "__BOT_STOPPED__":
                    self.on_bot_stopped()
                else:
                    self.append_log(line)
            except queue.Empty:
                break

        self.after(80, self.poll_log_queue)

    def append_log(self, text: str):
        """Appends timestamped/formatted text to the modern terminal view."""
        self.log_text.insert("end", text)
        self.log_text.see("end")

    def clear_logs(self):
        """Clears text console."""
        self.log_text.delete("1.0", "end")


if __name__ == "__main__":
    app = ModernAutoTradeApp()
    app.mainloop()
