"""Windows desktop client for the Contadores de Impressoras service."""
from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import http.client
import io
import json
import os
import ssl
import tkinter as tk
from datetime import date, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from urllib.parse import urlsplit, urlencode

from PIL import Image, ImageDraw, ImageFilter, ImageTk

CLIENT_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "ContadoresImpressoras"
CONFIG_PATH = CLIENT_DIR / "cliente.json"
COLORS = {
    "bg": "#F3F6FB", "card": "#FFFFFF", "ink": "#182338", "muted": "#71809A",
    "blue": "#2E6BE6", "line": "#E1E8F2", "green": "#16845B", "red": "#C54048",
    "amber": "#B77714", "navy": "#172A46", "soft_blue": "#EAF1FF",
}


class ApiError(RuntimeError):
    pass


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_config(config: dict) -> None:
    CLIENT_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def api_request(config: dict, method: str, path: str, payload=None, token: str | None = None):
    url = urlsplit(config.get("server_url", ""))
    if url.scheme != "https" or not url.hostname:
        raise ApiError("Endereço do servidor deve começar com https://")
    host, port = url.hostname, url.port or 8765
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    connection = http.client.HTTPSConnection(host, port, context=context, timeout=7)
    try:
        connection.connect()
        cert = connection.sock.getpeercert(binary_form=True)
        actual = hashlib.sha256(cert).hexdigest().lower()
        expected = "".join(ch for ch in config.get("fingerprint", "").lower() if ch in "0123456789abcdef")
        if not expected or not hmac.compare_digest(actual, expected):
            raise ApiError("A impressão digital do certificado não confere. Verifique os dados do serviço central.")
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        else:
            body = None
        if token:
            headers["Authorization"] = "Bearer " + token
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except json.JSONDecodeError:
            data = {}
        if response.status >= 400:
            raise ApiError(data.get("error", f"Erro do servidor ({response.status})."))
        return data
    except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
        raise ApiError(f"Não foi possível acessar o serviço central: {exc}") from exc
    finally:
        connection.close()


def modal_window(parent, title: str, size="500x330") -> tk.Toplevel:
    win = tk.Toplevel(parent)
    win.title(title)
    win.geometry(size)
    win.configure(bg=COLORS["bg"])
    # The main Tk root starts withdrawn. A transient child of a withdrawn
    # owner can remain invisible on Windows, so keep dialogs independent.
    win.grab_set()
    win.lift()
    return win


def make_printer_illustration(model: str, status: str, size=(360, 178)) -> Image.Image:
    """Create a clean, model-family illustration used until a real device photo is uploaded."""
    w, h = size
    im = Image.new("RGB", size, "#F2F6FC")
    d = ImageDraw.Draw(im)
    d.ellipse((35, h-34, w-25, h-9), fill="#DDE5F0")
    is_140 = "140" in (model or "")
    accent = "#2E6BE6"
    # A production printer represented as joined paper modules and a central engine.
    base_y = h - 32
    unit_w = 57 if not is_140 else 64
    gap = 4
    x0 = 35
    units = 4 if not is_140 else 3
    for i in range(units):
        x = x0 + i * (unit_w + gap)
        top = 51 + (6 if i in (0, units-1) else 0)
        d.rounded_rectangle((x, top, x+unit_w, base_y), radius=5, fill="#E6EBF2", outline="#AEBAC9", width=2)
        d.rectangle((x+5, top+9, x+unit_w-5, top+14), fill="#C4CFDC")
        for tray in range(3):
            ty = top + 27 + tray * 24
            if ty + 18 < base_y:
                d.rounded_rectangle((x+6, ty, x+unit_w-6, ty+17), radius=2, fill="#F9FBFE", outline="#A6B3C3")
                d.line((x+10, ty+5, x+unit_w-10, ty+5), fill="#D0D9E4", width=2)
    engine_x = x0 + units * (unit_w + gap) + 2
    engine_w = max(48, w - engine_x - 28)
    d.rounded_rectangle((engine_x, 62, engine_x+engine_w, base_y), radius=6, fill="#DDE4ED", outline="#AEBAC9", width=2)
    d.rounded_rectangle((engine_x+8, 77, engine_x+engine_w-8, 104), radius=3, fill="#F9FBFE", outline="#A6B3C3")
    d.rectangle((engine_x+12, 84, engine_x+engine_w-12, 88), fill="#BBC7D5")
    # Operator panel and status light.
    panel_x = max(engine_x+8, w-80)
    d.rounded_rectangle((panel_x, 37, panel_x+44, 72), radius=4, fill="#35445A")
    d.rounded_rectangle((panel_x+5, 42, panel_x+39, 64), radius=3, fill="#B9D8F5")
    status_color = COLORS["green"] if status == "online" else (COLORS["red"] if status == "offline" else COLORS["amber"])
    d.ellipse((panel_x+18, 67, panel_x+27, 76), fill=status_color, outline="#FFFFFF", width=2)
    # Paper output stack and small screen highlights.
    d.polygon([(engine_x+engine_w-2, 108), (w-17, 108), (w-9, 118), (engine_x+engine_w+5, 118)], fill="#FFFFFF", outline="#AEBAC9")
    d.rounded_rectangle((x0+8, 29, x0+68, 53), radius=3, fill="#E8EDF4", outline="#AEBAC9")
    d.line((x0+13, 35, x0+57, 35), fill=accent, width=3)
    # Slight ground shade and small model family label.
    family = "VarioPRINT 140" if is_140 else "VarioPRINT 6330" if "6330" in (model or "") else "VarioPRINT 6000"
    d.text((16, 7), family, fill="#60718A")
    return im


class ConnectionDialog:
    def __init__(self, parent, config: dict):
        self.result = None
        self.win = modal_window(parent, "Conectar ao servidor central", "560x300")
        frame = tk.Frame(self.win, bg=COLORS["bg"], padx=24, pady=20)
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text="Conexão com o serviço central", font=("Segoe UI", 16, "bold"), fg=COLORS["ink"], bg=COLORS["bg"]).pack(anchor="w")
        tk.Label(frame, text="Use o endereço e a impressão digital exibidos no computador central.", font=("Segoe UI", 10), fg=COLORS["muted"], bg=COLORS["bg"], wraplength=500, justify="left").pack(anchor="w", pady=(5, 14))
        self.url = tk.StringVar(value=config.get("server_url", "https://"))
        self.fp = tk.StringVar(value=config.get("fingerprint", ""))
        tk.Label(frame, text="Endereço do serviço", bg=COLORS["bg"], fg=COLORS["ink"]).pack(anchor="w")
        ttk.Entry(frame, textvariable=self.url).pack(fill="x", pady=(3, 10))
        tk.Label(frame, text="Impressão digital SHA256", bg=COLORS["bg"], fg=COLORS["ink"]).pack(anchor="w")
        ttk.Entry(frame, textvariable=self.fp).pack(fill="x", pady=(3, 10))
        row = tk.Frame(frame, bg=COLORS["bg"]); row.pack(fill="x", pady=(4, 0))
        self.message = tk.Label(row, text="", fg=COLORS["red"], bg=COLORS["bg"], wraplength=340, justify="left")
        self.message.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Conectar", command=self.connect).pack(side="right")
        self.win.bind("<Return>", lambda _e: self.connect())

    def connect(self):
        candidate = {"server_url": self.url.get().strip().rstrip("/"), "fingerprint": self.fp.get().strip()}
        try:
            api_request(candidate, "GET", "/api/status")
        except Exception as exc:
            self.message.config(text=str(exc)); return
        self.result = candidate
        self.win.destroy()


class LoginDialog:
    def __init__(self, parent, config: dict, needs_setup: bool):
        self.result = None
        self.win = modal_window(parent, "Criar administrador" if needs_setup else "Entrar", "480x390" if needs_setup else "480x330")
        frame = tk.Frame(self.win, bg=COLORS["bg"], padx=26, pady=22); frame.pack(fill="both", expand=True)
        title = "Criar a primeira conta administrativa" if needs_setup else "Acesse o painel da operação"
        tk.Label(frame, text=title, font=("Segoe UI", 16, "bold"), fg=COLORS["ink"], bg=COLORS["bg"]).pack(anchor="w")
        tk.Label(frame, text="As contas individuais terão permissão administrativa.", font=("Segoe UI", 10), fg=COLORS["muted"], bg=COLORS["bg"]).pack(anchor="w", pady=(5, 14))
        self.username = tk.StringVar(); self.password = tk.StringVar(); self.confirm = tk.StringVar()
        for label, variable, show in (("Usuário", self.username, ""), ("Senha", self.password, "•")):
            tk.Label(frame, text=label, bg=COLORS["bg"], fg=COLORS["ink"]).pack(anchor="w")
            ttk.Entry(frame, textvariable=variable, show=show).pack(fill="x", pady=(3, 10))
        if needs_setup:
            tk.Label(frame, text="Confirme a senha", bg=COLORS["bg"], fg=COLORS["ink"]).pack(anchor="w")
            ttk.Entry(frame, textvariable=self.confirm, show="•").pack(fill="x", pady=(3, 10))
            tk.Label(frame, text="Use pelo menos 12 caracteres.", bg=COLORS["bg"], fg=COLORS["muted"]).pack(anchor="w")
        self.message = tk.Label(frame, text="", bg=COLORS["bg"], fg=COLORS["red"], wraplength=420, justify="left")
        self.message.pack(anchor="w", pady=(8, 0))
        ttk.Button(frame, text="Criar conta" if needs_setup else "Entrar", command=lambda: self.submit(config, needs_setup)).pack(anchor="e", pady=(8, 0))
        self.win.bind("<Return>", lambda _e: self.submit(config, needs_setup))

    def submit(self, config, needs_setup):
        if not self.username.get().strip() or not self.password.get():
            self.message.config(text="Informe usuário e senha."); return
        if needs_setup and self.password.get() != self.confirm.get():
            self.message.config(text="As senhas não conferem."); return
        try:
            result = api_request(config, "POST", "/api/setup" if needs_setup else "/api/login", {"username": self.username.get().strip(), "password": self.password.get()})
        except Exception as exc:
            self.message.config(text=str(exc)); return
        self.result = result
        self.win.destroy()


class PrinterDialog:
    def __init__(self, parent, printer: dict | None = None):
        self.result = None
        self.photo_bytes = None
        self.photo_mime = None
        self.photo_name = ""
        self.win = modal_window(parent, "Editar equipamento" if printer else "Cadastrar equipamento", "540x450")
        f = tk.Frame(self.win, bg=COLORS["bg"], padx=24, pady=18); f.pack(fill="both", expand=True)
        tk.Label(f, text="Dados do equipamento", font=("Segoe UI", 16, "bold"), fg=COLORS["ink"], bg=COLORS["bg"]).pack(anchor="w", pady=(0, 12))
        self.alias = tk.StringVar(value=(printer or {}).get("alias", "")); self.ip = tk.StringVar(value=(printer or {}).get("ip", ""))
        self.community = tk.StringVar(value=(printer or {}).get("community", "")); self.version = tk.StringVar(value=(printer or {}).get("version", "2c"))
        for label, var in (("Nome no painel", self.alias), ("Endereço IP", self.ip), ("Comunidade SNMP de leitura", self.community)):
            tk.Label(f, text=label, bg=COLORS["bg"], fg=COLORS["ink"]).pack(anchor="w")
            ttk.Entry(f, textvariable=var).pack(fill="x", pady=(2, 9))
        row = tk.Frame(f, bg=COLORS["bg"]); row.pack(fill="x", pady=(0, 9))
        tk.Label(row, text="SNMP", bg=COLORS["bg"], fg=COLORS["ink"]).pack(side="left")
        ttk.Combobox(row, textvariable=self.version, values=("2c", "1"), state="readonly", width=8).pack(side="left", padx=10)
        photo = tk.Frame(f, bg=COLORS["bg"]); photo.pack(fill="x", pady=(3, 10))
        ttk.Button(photo, text="Escolher foto desta impressora…", command=self.choose_photo).pack(side="left")
        self.photo_label = tk.Label(photo, text="Imagem padrão do modelo", bg=COLORS["bg"], fg=COLORS["muted"])
        self.photo_label.pack(side="left", padx=10)
        self.message = tk.Label(f, text="", bg=COLORS["bg"], fg=COLORS["red"], wraplength=460, justify="left"); self.message.pack(anchor="w")
        ttk.Button(f, text="Salvar", command=self.save).pack(anchor="e", pady=(8, 0))
        self.printer = printer

    def choose_photo(self):
        path = filedialog.askopenfilename(parent=self.win, title="Escolher imagem da impressora", filetypes=(("Imagens", "*.png *.jpg *.jpeg *.webp"),))
        if not path: return
        try:
            with Image.open(path) as im:
                im.thumbnail((1000, 800))
                buf = io.BytesIO()
                mime = "image/png" if path.lower().endswith(".png") else "image/webp" if path.lower().endswith(".webp") else "image/jpeg"
                fmt = "PNG" if mime == "image/png" else "WEBP" if mime == "image/webp" else "JPEG"
                if fmt == "JPEG" and im.mode not in ("RGB", "L"): im = im.convert("RGB")
                im.save(buf, format=fmt)
            self.photo_bytes = buf.getvalue(); self.photo_mime = mime; self.photo_name = Path(path).name
            self.photo_label.config(text=self.photo_name)
        except Exception as exc:
            self.message.config(text=f"Não foi possível abrir a imagem: {exc}")

    def save(self):
        if not self.alias.get().strip() or not self.ip.get().strip() or not self.community.get().strip():
            self.message.config(text="Preencha nome, IP e comunidade SNMP."); return
        self.result = {"alias": self.alias.get().strip(), "ip": self.ip.get().strip(), "community": self.community.get().strip(), "version": self.version.get(), "photo_bytes": self.photo_bytes, "photo_mime": self.photo_mime}
        self.win.destroy()


class PrinterOpsApp:
    def __init__(self, root: tk.Tk, config: dict, login: dict):
        self.root, self.config, self.token = root, config, login["token"]
        self.username = login["username"]
        self.root.deiconify()
        self.root.title("Contadores de Impressoras | Operação")
        self.root.geometry("1420x900")
        self.root.minsize(1120, 720)
        self.root.configure(bg=COLORS["bg"])
        self._style()
        self.printers = []
        self.selected_id = None
        self.photos = []
        self.image_cache = {}
        self.last_dashboard_signature = ""
        self.known_alerts: set[int] | None = None
        self.dashboard_data = {}
        self._build()
        self.refresh_all(first=True)
        self.root.after(5000, self._scheduled_refresh)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _style(self):
        style = ttk.Style()
        try: style.theme_use("clam")
        except tk.TclError: pass
        style.configure("TFrame", background=COLORS["bg"])
        style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["ink"], font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10), padding=(10, 7))
        style.configure("Treeview", rowheight=30, font=("Segoe UI", 10), background="white", fieldbackground="white")
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), background="#EAF0F8", foreground=COLORS["ink"])
        style.configure("TNotebook", background=COLORS["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", padding=(14, 9), font=("Segoe UI", 10, "bold"))

    def _build(self):
        top = tk.Frame(self.root, bg=COLORS["navy"], height=74); top.pack(fill="x"); top.pack_propagate(False)
        tk.Label(top, text="▦", font=("Segoe UI Symbol", 26), bg=COLORS["navy"], fg="#8DB5FF").pack(side="left", padx=(20, 10))
        tk.Label(top, text="CONTADORES DE IMPRESSORAS", font=("Segoe UI", 15, "bold"), bg=COLORS["navy"], fg="white").pack(side="left")
        self.top_status = tk.Label(top, text="Conectado", bg=COLORS["navy"], fg="#AEE8CB", font=("Segoe UI", 10, "bold")); self.top_status.pack(side="right", padx=18)
        tk.Label(top, text=self.username, bg=COLORS["navy"], fg="#DDE6F3", font=("Segoe UI", 10)).pack(side="right", padx=14)
        ttk.Button(top, text="Sair", command=self.logout).pack(side="right", padx=3, pady=18)
        self.note = tk.StringVar(value="Atualizando a operação…")
        self.tabs = ttk.Notebook(self.root)
        self.tabs.pack(fill="both", expand=True, padx=16, pady=(12, 5))
        self.operation_tab = ttk.Frame(self.tabs, padding=12)
        self.equipment_tab = ttk.Frame(self.tabs, padding=12)
        self.production_tab = ttk.Frame(self.tabs, padding=12)
        self.alerts_tab = ttk.Frame(self.tabs, padding=12)
        self.users_tab = ttk.Frame(self.tabs, padding=12)
        self.settings_tab = ttk.Frame(self.tabs, padding=12)
        for frame, title in ((self.operation_tab, "Visão da operação"), (self.equipment_tab, "Equipamentos"), (self.production_tab, "Produção diária"), (self.alerts_tab, "Alertas"), (self.users_tab, "Usuários"), (self.settings_tab, "Servidor e backup")):
            self.tabs.add(frame, text=title)
        self._build_operation()
        self._build_equipments()
        self._build_production()
        self._build_alerts()
        self._build_users()
        self._build_settings()
        bottom = tk.Frame(self.root, bg=COLORS["bg"]); bottom.pack(fill="x", padx=18, pady=(0, 9))
        tk.Label(bottom, textvariable=self.note, bg=COLORS["bg"], fg=COLORS["muted"], font=("Segoe UI", 9)).pack(side="left")
        ttk.Button(bottom, text="Atualizar agora", command=self.refresh_all).pack(side="right")

    def _build_operation(self):
        f = self.operation_tab
        head = tk.Frame(f, bg=COLORS["bg"]); head.pack(fill="x", pady=(0, 10))
        tk.Label(head, text="Painel da operação", font=("Segoe UI", 21, "bold"), fg=COLORS["ink"], bg=COLORS["bg"]).pack(side="left")
        tk.Label(head, text="Atualização SNMP a cada 30 segundos", font=("Segoe UI", 10), fg=COLORS["muted"], bg=COLORS["bg"]).pack(side="right", padx=4, pady=10)
        self.kpi_frame = tk.Frame(f, bg=COLORS["bg"]); self.kpi_frame.pack(fill="x", pady=(0, 12))
        self.kpis = {}
        for key, title, color in (("devices", "EQUIPAMENTOS", COLORS["blue"]), ("online", "ONLINE", COLORS["green"]), ("printing", "IMPRIMINDO", COLORS["blue"]), ("offline", "OFFLINE", COLORS["red"]), ("alerts", "ALERTAS ATIVOS", COLORS["amber"]), ("today", "IMPRESSÕES HOJE", COLORS["navy"])):
            box = tk.Frame(self.kpi_frame, bg="white", highlightbackground=COLORS["line"], highlightthickness=1)
            box.pack(side="left", fill="x", expand=True, padx=(0, 8))
            tk.Frame(box, bg=color, height=4).pack(fill="x")
            tk.Label(box, text=title, font=("Segoe UI", 8, "bold"), bg="white", fg=COLORS["muted"]).pack(anchor="w", padx=12, pady=(9, 0))
            value = tk.Label(box, text="—", font=("Segoe UI", 19, "bold"), bg="white", fg=COLORS["ink"]); value.pack(anchor="w", padx=12, pady=(1, 10))
            self.kpis[key] = value
        mid = tk.Frame(f, bg=COLORS["bg"]); mid.pack(fill="both", expand=True)
        left = tk.Frame(mid, bg=COLORS["bg"]); left.pack(side="left", fill="both", expand=True)
        tk.Label(left, text="Impressoras cadastradas", font=("Segoe UI", 14, "bold"), bg=COLORS["bg"], fg=COLORS["ink"]).pack(anchor="w", pady=(0, 8))
        canvas_wrap = tk.Frame(left, bg=COLORS["bg"]); canvas_wrap.pack(fill="both", expand=True)
        self.cards_canvas = tk.Canvas(canvas_wrap, bg=COLORS["bg"], highlightthickness=0)
        self.cards_scroll = ttk.Scrollbar(canvas_wrap, orient="vertical", command=self.cards_canvas.yview)
        self.cards_inner = tk.Frame(self.cards_canvas, bg=COLORS["bg"])
        self.cards_inner.bind("<Configure>", lambda _e: self.cards_canvas.configure(scrollregion=self.cards_canvas.bbox("all")))
        self.cards_canvas.create_window((0, 0), window=self.cards_inner, anchor="nw", tags="cards")
        self.cards_canvas.configure(yscrollcommand=self.cards_scroll.set)
        self.cards_canvas.pack(side="left", fill="both", expand=True); self.cards_scroll.pack(side="right", fill="y")
        self.cards_canvas.bind("<Configure>", lambda e: self.cards_canvas.itemconfigure("cards", width=e.width))
        self.cards_canvas.bind_all("<MouseWheel>", lambda e: self.cards_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
        right = tk.Frame(mid, bg="white", width=300, highlightbackground=COLORS["line"], highlightthickness=1)
        right.pack(side="right", fill="y", padx=(14, 0)); right.pack_propagate(False)
        tk.Label(right, text="PRODUÇÃO · 7 DIAS", font=("Segoe UI", 10, "bold"), bg="white", fg=COLORS["ink"]).pack(anchor="w", padx=14, pady=(14, 3))
        tk.Label(right, text="Impressões por dia", font=("Segoe UI", 9), bg="white", fg=COLORS["muted"]).pack(anchor="w", padx=14)
        self.chart = tk.Canvas(right, bg="white", height=210, highlightthickness=0); self.chart.pack(fill="x", padx=7, pady=8)
        tk.Label(right, text="STATUS", font=("Segoe UI", 10, "bold"), bg="white", fg=COLORS["ink"]).pack(anchor="w", padx=14, pady=(12, 5))
        self.status_summary = tk.Label(right, text="Aguardando primeira coleta…", justify="left", wraplength=260, font=("Segoe UI", 10), bg="white", fg=COLORS["muted"])
        self.status_summary.pack(anchor="w", padx=14)

    def _build_equipments(self):
        f = self.equipment_tab
        bar = tk.Frame(f, bg=COLORS["bg"]); bar.pack(fill="x", pady=(0, 10))
        tk.Label(bar, text="Inventário de equipamentos", font=("Segoe UI", 18, "bold"), bg=COLORS["bg"], fg=COLORS["ink"]).pack(side="left")
        for title, command in (("Adicionar", self.add_printer), ("Editar", self.edit_printer), ("Remover", self.remove_printer)):
            ttk.Button(bar, text=title, command=command).pack(side="right", padx=(6, 0))
        cols = ("alias", "ip", "online", "status", "model", "counter", "today", "toner", "updated")
        self.equipment_tree = ttk.Treeview(f, columns=cols, show="headings", selectmode="browse")
        headings = {"alias":"Nome", "ip":"IP", "online":"Conexão", "status":"Estado", "model":"Modelo / firmware", "counter":"Contador atual", "today":"Hoje", "toner":"Toner", "updated":"Última coleta"}
        widths = {"alias":150,"ip":120,"online":90,"status":105,"model":260,"counter":130,"today":100,"toner":150,"updated":150}
        for c in cols:
            self.equipment_tree.heading(c, text=headings[c]); self.equipment_tree.column(c, width=widths[c], anchor="w" if c in ("alias","ip","online","status","model","toner","updated") else "e")
        self.equipment_tree.pack(fill="both", expand=True)
        self.equipment_tree.bind("<Double-1>", lambda _e: self.edit_printer())
        self.equipment_tree.tag_configure("offline", foreground=COLORS["red"]); self.equipment_tree.tag_configure("unknown", foreground=COLORS["amber"])

    def _build_production(self):
        f = self.production_tab
        tk.Label(f, text="Produção por período", font=("Segoe UI", 18, "bold"), bg=COLORS["bg"], fg=COLORS["ink"]).pack(anchor="w", pady=(0, 10))
        bar = tk.Frame(f, bg=COLORS["bg"]); bar.pack(fill="x", pady=(0, 10))
        today = date.today().isoformat(); week = (date.today()-timedelta(days=6)).isoformat()
        self.report_start = tk.StringVar(value=week); self.report_end = tk.StringVar(value=today)
        tk.Label(bar, text="De", bg=COLORS["bg"]).pack(side="left")
        ttk.Entry(bar, textvariable=self.report_start, width=13).pack(side="left", padx=(5, 12))
        tk.Label(bar, text="Até", bg=COLORS["bg"]).pack(side="left")
        ttk.Entry(bar, textvariable=self.report_end, width=13).pack(side="left", padx=(5, 12))
        ttk.Button(bar, text="Consultar", command=self.load_report).pack(side="left")
        ttk.Button(bar, text="Exportar CSV / Excel", command=self.export_report).pack(side="right")
        tk.Label(f, text="As quantidades são diferenças do contador cumulativo. Períodos sem leitura podem aparecer como estimados.", bg=COLORS["bg"], fg=COLORS["muted"], font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 7))
        cols=("date","alias","ip","quantity","unit","quality")
        self.report_tree=ttk.Treeview(f,columns=cols,show="headings")
        heads={"date":"Data","alias":"Equipamento","ip":"IP","quantity":"Produção","unit":"Unidade","quality":"Leitura"}
        widths={"date":130,"alias":200,"ip":130,"quantity":140,"unit":150,"quality":140}
        for c in cols:self.report_tree.heading(c,text=heads[c]);self.report_tree.column(c,width=widths[c],anchor="e" if c=="quantity" else "w")
        self.report_tree.tag_configure("daily_total",font=("Segoe UI",10,"bold"),background="#EAF1FF")
        self.report_tree.pack(fill="both",expand=True)
        self.report_total=tk.Label(f,text="",font=("Segoe UI",12,"bold"),bg=COLORS["bg"],fg=COLORS["ink"]);self.report_total.pack(anchor="e",pady=(8,0))
        self.report_rows=[];self.report_totals=[]

    def _build_alerts(self):
        f=self.alerts_tab
        bar=tk.Frame(f,bg=COLORS["bg"]);bar.pack(fill="x",pady=(0,10))
        tk.Label(bar,text="Alertas da operação",font=("Segoe UI",18,"bold"),bg=COLORS["bg"],fg=COLORS["ink"]).pack(side="left")
        ttk.Button(bar,text="Reconhecer selecionado",command=self.ack_alert).pack(side="right")
        cols=("state","type","device","message","started","ack")
        self.alert_tree=ttk.Treeview(f,columns=cols,show="headings")
        heads={"state":"Situação","type":"Tipo","device":"Equipamento","message":"Mensagem","started":"Início","ack":"Reconhecido por"}
        widths={"state":95,"type":110,"device":200,"message":450,"started":165,"ack":150}
        for c in cols:self.alert_tree.heading(c,text=heads[c]);self.alert_tree.column(c,width=widths[c],anchor="w")
        self.alert_tree.pack(fill="both",expand=True)

    def _build_users(self):
        f=self.users_tab
        bar=tk.Frame(f,bg=COLORS["bg"]);bar.pack(fill="x",pady=(0,10))
        tk.Label(bar,text="Contas administrativas",font=("Segoe UI",18,"bold"),bg=COLORS["bg"],fg=COLORS["ink"]).pack(side="left")
        ttk.Button(bar,text="Criar conta",command=self.add_user).pack(side="right")
        ttk.Button(bar,text="Redefinir senha",command=self.reset_user_password).pack(side="right",padx=7)
        ttk.Button(bar,text="Desativar",command=self.deactivate_user).pack(side="right",padx=7)
        cols=("username","active","created")
        self.user_tree=ttk.Treeview(f,columns=cols,show="headings")
        for c,t,w in (("username","Usuário",260),("active","Acesso",150),("created","Criada em",220)):
            self.user_tree.heading(c,text=t);self.user_tree.column(c,width=w,anchor="w")
        self.user_tree.pack(fill="both",expand=True)

    def _build_settings(self):
        f=self.settings_tab
        tk.Label(f,text="Serviço central e cópias de segurança",font=("Segoe UI",18,"bold"),bg=COLORS["bg"],fg=COLORS["ink"]).pack(anchor="w",pady=(0,12))
        panel=tk.Frame(f,bg="white",padx=18,pady=16,highlightbackground=COLORS["line"],highlightthickness=1);panel.pack(fill="x")
        tk.Label(panel,text="Pasta compartilhada (caminho UNC ou pasta acessível pelo servidor)",bg="white",fg=COLORS["ink"]).pack(anchor="w")
        self.backup_path=tk.StringVar()
        ttk.Entry(panel,textvariable=self.backup_path).pack(fill="x",pady=(4,10))
        row=tk.Frame(panel,bg="white");row.pack(fill="x")
        tk.Label(row,text="Manter cópias por",bg="white").pack(side="left")
        self.retention=tk.StringVar(value="30")
        ttk.Spinbox(row,from_=1,to=3650,textvariable=self.retention,width=8).pack(side="left",padx=7)
        tk.Label(row,text="dias. O backup é compactado e executado diariamente após 02:00.",bg="white",fg=COLORS["muted"]).pack(side="left")
        actions=tk.Frame(panel,bg="white");actions.pack(fill="x",pady=(12,0))
        ttk.Button(actions,text="Testar pasta",command=self.test_backup).pack(side="left")
        ttk.Button(actions,text="Salvar configuração",command=self.save_settings).pack(side="right")
        self.backup_info=tk.Label(f,text="",bg=COLORS["bg"],fg=COLORS["muted"],justify="left",wraplength=1000);self.backup_info.pack(anchor="w",pady=12)
        tk.Label(f,text="O serviço e o banco ficam no computador central. Deixe o servidor aberto; todos os clientes usam os mesmos dados.",bg=COLORS["bg"],fg=COLORS["muted"],wraplength=900,justify="left").pack(anchor="w",pady=5)

    def _scheduled_refresh(self):
        self.refresh_all()
        self.root.after(5000, self._scheduled_refresh)

    def refresh_all(self, first=False):
        try:
            data=api_request(self.config,"GET","/api/dashboard",token=self.token)
            self.dashboard_data=data;self.printers=data.get("printers",[])
            self.top_status.config(text="● Conectado",fg="#AEE8CB")
            self.note.set(f"Última atualização do painel: {data.get('server_time','')} · SNMP é consultado pelo serviço central a cada 30 segundos")
            self.render_dashboard()
            self.render_equipment_table()
            self.refresh_alerts()
            if first:self.load_report()
        except ApiError as exc:
            self.top_status.config(text="● Sem conexão",fg="#FFC2C2")
            self.note.set(str(exc))
            if "Sessão inválida" in str(exc):
                messagebox.showwarning("Sessão encerrada","Entre novamente para continuar.")
                self.logout()
        if self.tabs.select()==str(self.users_tab):self.refresh_users()
        if self.tabs.select()==str(self.settings_tab):self.refresh_settings()

    def render_dashboard(self):
        d=self.dashboard_data;p=self.printers
        totals=d.get("daily_totals",[])
        total_text=sum(x.get("impressions",0) for x in totals) if len({x.get("unit") for x in totals})<=1 else "Várias unidades"
        formatted_total=f"{total_text:,}".replace(",",".") if isinstance(total_text,int) else total_text
        if any(x.get("estimated") for x in totals):formatted_total="≈ "+formatted_total
        values={"devices":len(p),"online":d.get("online",0),"printing":d.get("printing",0),"offline":d.get("offline",0),"alerts":d.get("active_alerts",0),"today":formatted_total}
        for k,v in values.items():self.kpis[k].config(text=str(v))
        signature=json.dumps(p,ensure_ascii=False,sort_keys=True)
        if signature!=self.last_dashboard_signature:
            self.last_dashboard_signature=signature;self.render_cards()
        self.status_summary.config(text=f"{d.get('online',0)} online  ·  {d.get('printing',0)} imprimindo\n{d.get('offline',0)} offline  ·  {d.get('active_alerts',0)} alertas ativos")
        self.draw_week_chart()

    def render_cards(self):
        for child in self.cards_inner.winfo_children():child.destroy()
        self.photos=[]
        if not self.printers:
            tk.Label(self.cards_inner,text="Nenhum equipamento cadastrado. Use a aba Equipamentos para adicionar o primeiro.",bg=COLORS["bg"],fg=COLORS["muted"],font=("Segoe UI",11)).grid(row=0,column=0,padx=15,pady=25,sticky="w")
            return
        for idx,printer in enumerate(self.printers):
            row,col=divmod(idx,2)
            self.cards_inner.grid_columnconfigure(col,weight=1,uniform="printer")
            card=tk.Frame(self.cards_inner,bg="white",highlightbackground=COLORS["line"],highlightthickness=1)
            card.grid(row=row,column=col,padx=(0,10),pady=(0,10),sticky="nsew")
            self._render_card(card,printer)

    def _render_card(self,card,printer):
        online=printer.get("online",-1)
        connection="ONLINE" if online==1 else "OFFLINE" if online==0 else "VERIFICANDO" if printer.get("failures") else "AGUARDANDO"
        status_color=COLORS["green"] if online==1 else COLORS["red"] if online==0 else COLORS["amber"]
        head=tk.Frame(card,bg="white");head.pack(fill="x",padx=13,pady=(11,5))
        tk.Label(head,text=printer["alias"],font=("Segoe UI",12,"bold"),bg="white",fg=COLORS["ink"]).pack(side="left",anchor="w")
        tk.Label(head,text=connection,font=("Segoe UI",8,"bold"),bg=status_color,fg="white",padx=8,pady=3).pack(side="right")
        model=printer.get("data",{}).get("model","") or printer.get("alias","")
        im=None
        if printer.get("has_photo"):
            try:
                response=api_request(self.config,"GET",f"/api/printers/{printer['id']}/photo",token=self.token)
                raw=base64.b64decode(response["base64"])
                with Image.open(io.BytesIO(raw)) as source:
                    source=source.convert("RGB");source.thumbnail((520,220))
                    im=Image.new("RGB",(520,220),"#F2F6FC");im.paste(source,((520-source.width)//2,(220-source.height)//2))
            except Exception:im=None
        if im is None:im=make_printer_illustration(model,status="online" if online==1 else "offline" if online==0 else "unknown",size=(520,220))
        photo=ImageTk.PhotoImage(im);self.photos.append(photo)
        tk.Label(card,image=photo,bg="white").pack(fill="x",padx=12,pady=(0,8))
        data=printer.get("data",{})
        today_rows=printer.get("today",[])
        today=sum(item.get("impressions",0) for item in today_rows)
        if any(item.get("estimated") for item in today_rows):today=f"≈ {today:,}".replace(",",".")
        today_unit=today_rows[0].get("unit",data.get("counter_unit","impressões")) if today_rows else data.get("counter_unit","impressões")
        total=printer.get("counter")
        toners=[f"{s.get('name')}: {s.get('percent')}%" for s in data.get("supplies",[]) if s.get("percent") is not None]
        toners=[t for t in toners if "toner" in t.lower()]
        lower=tk.Frame(card,bg="white");lower.pack(fill="x",padx=14,pady=(0,12))
        tk.Label(lower,text=f"{printer['ip']}   ·   {model.split(',')[0] if model else 'Modelo aguardando leitura'}",bg="white",fg=COLORS["muted"],font=("Segoe UI",9)).pack(anchor="w")
        metrics=tk.Frame(lower,bg="white");metrics.pack(fill="x",pady=(7,0))
        self._metric(metrics,"HOJE",f"{today:,}".replace(",","."),today_unit)
        self._metric(metrics,"CONTADOR",f"{total:,}".replace(",",".") if total is not None else "—",data.get("counter_unit",""))
        self._metric(metrics,"TONER","  ·  ".join(toners) if toners else "Sem leitura","")
        tk.Label(lower,text=f"Estado: {printer.get('status','—')}   ·   Última leitura: {printer.get('last_success') or '—'}",bg="white",fg=COLORS["ink"],font=("Segoe UI",9)).pack(anchor="w",pady=(8,0))
        ttk.Button(lower,text="Detalhes",command=lambda p=printer:self.show_details(p)).pack(anchor="e",pady=(5,0))

    def _metric(self,parent,title,value,sub):
        box=tk.Frame(parent,bg="#F7F9FC",padx=8,pady=6);box.pack(side="left",fill="both",expand=True,padx=(0,6))
        tk.Label(box,text=title,font=("Segoe UI",8,"bold"),bg="#F7F9FC",fg=COLORS["muted"]).pack(anchor="w")
        tk.Label(box,text=str(value),font=("Segoe UI",11,"bold"),bg="#F7F9FC",fg=COLORS["ink"],wraplength=165,justify="left").pack(anchor="w")
        if sub:tk.Label(box,text=sub,font=("Segoe UI",8),bg="#F7F9FC",fg=COLORS["muted"]).pack(anchor="w")

    def show_details(self,printer):
        data=printer.get("data",{})
        win=modal_window(self.root,printer["alias"],"650x600")
        f=tk.Frame(win,bg=COLORS["bg"],padx=18,pady=15);f.pack(fill="both",expand=True)
        tk.Label(f,text=printer["alias"],font=("Segoe UI",18,"bold"),bg=COLORS["bg"],fg=COLORS["ink"]).pack(anchor="w")
        connection="Online" if printer.get("online")==1 else "Offline" if printer.get("online")==0 else "Sem confirmação"
        error_text=", ".join(data.get("reported_errors",[])) or "Nenhum informado"
        lines=[f"Conexão: {connection}",f"Estado: {printer.get('status','—')}",f"IP: {printer['ip']}",f"Nome informado pelo equipamento: {data.get('hostname') or data.get('printer_name') or '—'}",f"Modelo / firmware: {data.get('model','—')}",f"Número de série: {data.get('serial') or '—'}",f"Identificador SNMP: {data.get('object_id') or '—'}",f"Contador: {printer.get('counter','—')} {printer.get('unit') or ''}",f"Contador desde a energização: {data.get('counter_since_power_on','—')}",f"Tempo ligado: {self.format_uptime(data.get('uptime_seconds'))}",f"Alertas informados pela impressora: {error_text}",f"Última consulta bem-sucedida: {printer.get('last_success') or '—'}"]
        tk.Label(f,text="\n".join(lines),font=("Segoe UI",10),bg=COLORS["bg"],fg=COLORS["ink"],justify="left",wraplength=600).pack(anchor="w",pady=(13,12))
        tk.Label(f,text="SUPRIMENTOS",font=("Segoe UI",10,"bold"),bg=COLORS["bg"],fg=COLORS["ink"]).pack(anchor="w")
        for s in data.get("supplies",[]):
            val=f"{s.get('percent')}%" if s.get("percent") is not None else str(s.get("level","Sem leitura"))
            tk.Label(f,text=f"• {s.get('name')}: {val}",bg=COLORS["bg"],fg=COLORS["ink"],font=("Segoe UI",10)).pack(anchor="w",pady=2)
        tk.Label(f,text="BANDEJAS",font=("Segoe UI",10,"bold"),bg=COLORS["bg"],fg=COLORS["ink"]).pack(anchor="w",pady=(10,3))
        for tray in data.get("trays",[]):
            tk.Label(f,text=f"• {tray.get('name')}: {tray.get('status')} · mídia {tray.get('media') or '—'}",bg=COLORS["bg"],fg=COLORS["ink"],font=("Segoe UI",9)).pack(anchor="w")
        if printer.get("error"):
            tk.Label(f,text=f"Último erro SNMP: {printer['error']}",bg=COLORS["bg"],fg=COLORS["red"],wraplength=600,justify="left").pack(anchor="w",pady=8)
        ttk.Button(f,text="Fechar",command=win.destroy).pack(anchor="e",pady=(10,0))

    @staticmethod
    def format_uptime(seconds):
        if not isinstance(seconds,int):return "—"
        days,rem=divmod(seconds,86400);hours,rem=divmod(rem,3600);minutes=rem//60
        return f"{days}d {hours}h {minutes}min"

    def draw_week_chart(self):
        self.chart.delete("all")
        end=date.today();start=end-timedelta(days=6)
        try:
            result=api_request(self.config,"GET",f"/api/reports/range?{urlencode({'start':start.isoformat(),'end':end.isoformat()})}",token=self.token)
        except Exception:return
        totals={}
        for row in result.get("rows",[]):totals[row["local_date"]]=totals.get(row["local_date"],0)+row.get("impressions",0)
        vals=[totals.get((start+timedelta(days=i)).isoformat(),0) for i in range(7)]
        maxval=max(vals) or 1;w=max(self.chart.winfo_width(),260);h=200;baseline=165
        self.chart.create_line(18,baseline,w-8,baseline,fill=COLORS["line"])
        bw=max(13,int((w-38)/10))
        for i,value in enumerate(vals):
            x=24+i*(bw+10);bar_h=int(110*value/maxval)
            self.chart.create_rectangle(x,baseline-bar_h,x+bw,baseline,fill=COLORS["blue"] if i==6 else "#8DB5FF",outline="")
            if value:self.chart.create_text(x+bw/2,baseline-bar_h-10,text=f"{value:,}".replace(",","."),fill=COLORS["ink"],font=("Segoe UI",8))
            self.chart.create_text(x+bw/2,baseline+14,text=(start+timedelta(days=i)).strftime("%d/%m"),fill=COLORS["muted"],font=("Segoe UI",8))
        self.chart.create_text(18,12,anchor="w",text=f"Total 7 dias: {sum(vals):,}".replace(",","."),fill=COLORS["ink"],font=("Segoe UI",9,"bold"))

    def render_equipment_table(self):
        selected=self.equipment_tree.selection()
        self.equipment_tree.delete(*self.equipment_tree.get_children())
        for p in self.printers:
            data=p.get("data",{});toner=" / ".join(f"{s.get('percent')}%" for s in data.get("supplies",[]) if s.get("percent") is not None and "toner" in s.get("name","").lower()) or "—"
            today=sum(x.get("impressions",0) for x in p.get("today",[]))
            conn="Online" if p.get("online")==1 else "Offline" if p.get("online")==0 else "Verificando" if p.get("failures") else "Aguardando"
            tag="offline" if p.get("online")==0 else "unknown" if p.get("online")!=1 else ""
            self.equipment_tree.insert("","end",iid=str(p["id"]),values=(p["alias"],p["ip"],conn,p.get("status","—"),data.get("model","—"),p.get("counter") if p.get("counter") is not None else "—",today,toner,p.get("last_success") or "—"),tags=(tag,))
        if selected and self.equipment_tree.exists(selected[0]):self.equipment_tree.selection_set(selected[0])

    def selected_printer(self):
        sel=self.equipment_tree.selection()
        return next((p for p in self.printers if sel and str(p["id"])==sel[0]),None)

    def add_printer(self):
        dialog=PrinterDialog(self.root);self.root.wait_window(dialog.win)
        if not dialog.result:return
        data=dialog.result.copy();photo=data.pop("photo_bytes",None);mime=data.pop("photo_mime",None)
        try:
            result=api_request(self.config,"POST","/api/printers",data,token=self.token)
            if photo:api_request(self.config,"PUT",f"/api/printers/{result['id']}/photo",{"mime":mime,"base64":base64.b64encode(photo).decode()},token=self.token)
            self.refresh_all()
        except Exception as exc:messagebox.showerror("Cadastro não concluído",str(exc))

    def edit_printer(self):
        p=self.selected_printer()
        if not p:messagebox.showinfo("Selecionar equipamento","Selecione uma impressora na lista para editar.");return
        dialog=PrinterDialog(self.root,p);self.root.wait_window(dialog.win)
        if not dialog.result:return
        data=dialog.result.copy();photo=data.pop("photo_bytes",None);mime=data.pop("photo_mime",None)
        try:
            api_request(self.config,"PUT",f"/api/printers/{p['id']}",data,token=self.token)
            if photo:api_request(self.config,"PUT",f"/api/printers/{p['id']}/photo",{"mime":mime,"base64":base64.b64encode(photo).decode()},token=self.token)
            self.refresh_all()
        except Exception as exc:messagebox.showerror("Edição não concluída",str(exc))

    def remove_printer(self):
        p=self.selected_printer()
        if not p:messagebox.showinfo("Selecionar equipamento","Selecione uma impressora na lista para remover.");return
        if not messagebox.askyesno("Remover equipamento",f"Remover {p['alias']} e o histórico associado?"):return
        try:api_request(self.config,"DELETE",f"/api/printers/{p['id']}",token=self.token);self.refresh_all()
        except Exception as exc:messagebox.showerror("Não foi possível remover",str(exc))

    def load_report(self):
        start,end=self.report_start.get().strip(),self.report_end.get().strip()
        try:
            response=api_request(self.config,"GET",f"/api/reports/range?{urlencode({'start':start,'end':end})}",token=self.token)
            self.report_rows=response.get("rows",[])
            self.report_totals=response.get("daily_totals",[])
            self.report_tree.delete(*self.report_tree.get_children())
            overall={}
            grouped={}
            for i,row in enumerate(self.report_rows):
                grouped.setdefault(row["local_date"],[]).append((i,row))
                overall[row["unit"]]=overall.get(row["unit"],0)+row["impressions"]
            totals_by_date={}
            for total in self.report_totals:totals_by_date.setdefault(total["local_date"],[]).append(total)
            for day in sorted(set(grouped)|set(totals_by_date)):
                for i,row in grouped.get(day,[]):
                    self.report_tree.insert("","end",iid=f"detail-{i}",values=(row["local_date"],row["alias"],row["ip"],row["impressions"],row["unit"],"Estimado" if row["estimated"] else "Coletado"))
                for j,total in enumerate(totals_by_date.get(day,[])):
                    self.report_tree.insert("","end",iid=f"total-{day}-{j}",values=(day,"TOTAL DA OPERAÇÃO","—",total["impressions"],total["unit"],"Estimado" if total["estimated"] else "Consolidado"),tags=("daily_total",))
            text="Total do período: "+" · ".join(f"{v:,} {k}".replace(",",".") for k,v in overall.items()) if overall else "Sem produção registrada no período."
            self.report_total.config(text=text)
        except Exception as exc:messagebox.showerror("Período inválido",str(exc))

    def export_report(self):
        if not self.report_rows:self.load_report()
        if not self.report_rows:return
        path=filedialog.asksaveasfilename(title="Exportar produção",defaultextension=".csv",filetypes=(("CSV compatível com Excel","*.csv"),))
        if not path:return
        with open(path,"w",newline="",encoding="utf-8-sig") as f:
            writer=csv.writer(f,delimiter=";");writer.writerow(("Tipo","Data","Equipamento","IP","Produção","Unidade","Qualidade da leitura"))
            for r in self.report_rows:writer.writerow(("Equipamento",r["local_date"],r["alias"],r["ip"],r["impressions"],r["unit"],"Estimado" if r["estimated"] else "Coletado"))
            for r in self.report_totals:writer.writerow(("Total da operação",r["local_date"],"Toda a frota","—",r["impressions"],r["unit"],"Estimado" if r["estimated"] else "Consolidado"))
        messagebox.showinfo("Exportação concluída",f"Arquivo salvo em:\n{path}")

    def refresh_alerts(self):
        try:alerts=api_request(self.config,"GET","/api/alerts",token=self.token)
        except Exception:return
        selected=self.alert_tree.selection()
        active_ids={a["id"] for a in alerts if a["active"]}
        if self.known_alerts is None:self.known_alerts=set(active_ids)
        else:
            for alert in alerts:
                if alert["active"] and alert["id"] not in self.known_alerts:
                    self.show_toast(alert["message"])
            self.known_alerts=active_ids
        self.alert_tree.delete(*self.alert_tree.get_children())
        for a in alerts:
            self.alert_tree.insert("","end",iid=str(a["id"]),values=("Ativo" if a["active"] else "Resolvido",a["alert_type"],a.get("alias") or "Sistema",a["message"],a["created_at"],a.get("acknowledged_by") or "—"))
        if selected and self.alert_tree.exists(selected[0]):self.alert_tree.selection_set(selected[0])

    def show_toast(self,message):
        toast=tk.Toplevel(self.root);toast.overrideredirect(True);toast.attributes("-topmost",True);toast.configure(bg=COLORS["navy"])
        self.root.update_idletasks();x=self.root.winfo_rootx()+self.root.winfo_width()-390;y=self.root.winfo_rooty()+self.root.winfo_height()-135
        toast.geometry(f"360x90+{x}+{y}")
        tk.Label(toast,text="ALERTA DA OPERAÇÃO",font=("Segoe UI",9,"bold"),bg=COLORS["navy"],fg="#F8C96A").pack(anchor="w",padx=14,pady=(10,2))
        tk.Label(toast,text=message,font=("Segoe UI",10),bg=COLORS["navy"],fg="white",wraplength=330,justify="left").pack(anchor="w",padx=14)
        toast.after(8500,toast.destroy)

    def ack_alert(self):
        sel=self.alert_tree.selection()
        if not sel:messagebox.showinfo("Selecionar alerta","Selecione um alerta para reconhecer.");return
        try:api_request(self.config,"PUT",f"/api/alerts/{sel[0]}/ack",{},token=self.token);self.refresh_alerts()
        except Exception as exc:messagebox.showerror("Não foi possível reconhecer",str(exc))

    def refresh_users(self):
        try:users=api_request(self.config,"GET","/api/users",token=self.token)
        except Exception:return
        selected=self.user_tree.selection()
        self.user_tree.delete(*self.user_tree.get_children())
        for u in users:self.user_tree.insert("","end",iid=str(u["id"]),values=(u["username"],"Ativa" if u["active"] else "Desativada",u["created_at"]))
        if selected and self.user_tree.exists(selected[0]):self.user_tree.selection_set(selected[0])

    def add_user(self):
        username=simpledialog.askstring("Criar conta","Nome de usuário:",parent=self.root)
        if not username:return
        password=simpledialog.askstring("Criar conta","Senha (mínimo 12 caracteres):",show="•",parent=self.root)
        if not password:return
        try:api_request(self.config,"POST","/api/users",{"username":username,"password":password},token=self.token);self.refresh_users()
        except Exception as exc:messagebox.showerror("Não foi possível criar a conta",str(exc))

    def reset_user_password(self):
        sel=self.user_tree.selection()
        if not sel:messagebox.showinfo("Selecionar conta","Selecione uma conta.");return
        password=simpledialog.askstring("Redefinir senha","Nova senha (mínimo 12 caracteres):",show="•",parent=self.root)
        if not password:return
        selected=self.user_tree.item(sel[0],"values")
        try:api_request(self.config,"PUT",f"/api/users/{sel[0]}",{"password":password,"active":selected[1]=="Ativa"},token=self.token);self.refresh_users()
        except Exception as exc:messagebox.showerror("Não foi possível redefinir",str(exc))

    def deactivate_user(self):
        sel=self.user_tree.selection()
        if not sel:messagebox.showinfo("Selecionar conta","Selecione uma conta.");return
        row=self.user_tree.item(sel[0],"values")
        if row[0]==self.username:messagebox.showwarning("Conta em uso","Entre com outra conta para desativar este usuário.");return
        if not messagebox.askyesno("Desativar conta",f"Desativar {row[0]}? A conta poderá ser reativada redefinindo a senha."):return
        try:api_request(self.config,"DELETE",f"/api/users/{sel[0]}",token=self.token);self.refresh_users()
        except Exception as exc:messagebox.showerror("Não foi possível desativar",str(exc))

    def refresh_settings(self):
        try:
            data=api_request(self.config,"GET","/api/settings",token=self.token)
            self.backup_path.set(data.get("backup_path", ""));self.retention.set(str(data.get("backup_retention_days",30)))
            self.backup_info.config(text=f"Último backup: {data.get('last_backup_at') or 'nenhum'}\n{data.get('last_backup_message','')}\nAgendamento: {data.get('backup_schedule','')}")
        except Exception:pass

    def save_settings(self):
        try:
            api_request(self.config,"PUT","/api/settings",{"backup_path":self.backup_path.get().strip(),"backup_retention_days":int(self.retention.get())},token=self.token)
            messagebox.showinfo("Configuração salva","O serviço central usará este destino na próxima rotina de backup.")
            self.refresh_settings()
        except Exception as exc:messagebox.showerror("Não foi possível salvar",str(exc))

    def test_backup(self):
        try:
            response=api_request(self.config,"POST","/api/backup/test",{"path":self.backup_path.get().strip()},token=self.token)
            messagebox.showinfo("Pasta disponível",response.get("message","Teste concluído."))
        except Exception as exc:messagebox.showerror("Falha no teste",str(exc))

    def logout(self):
        try:api_request(self.config,"POST","/api/logout",{},token=self.token)
        except Exception:pass
        self.root.destroy()
        launch()

    def close(self):
        try:api_request(self.config,"POST","/api/logout",{},token=self.token)
        except Exception:pass
        self.root.destroy()


def launch():
    root=tk.Tk();root.withdraw()
    config=load_config()
    while True:
        dialog=ConnectionDialog(root,config);root.wait_window(dialog.win)
        if not dialog.result:
            root.destroy();return
        config.update(dialog.result);save_config(config)
        try:
            status=api_request(config,"GET","/api/status")
        except Exception as exc:
            if messagebox.askretrycancel("Servidor indisponível",str(exc),parent=root):continue
            root.destroy();return
        login=LoginDialog(root,config,status.get("needs_setup",False));root.wait_window(login.win)
        if not login.result:
            root.destroy();return
        PrinterOpsApp(root,config,login.result)
        root.mainloop()
        return


if __name__ == "__main__":
    launch()
