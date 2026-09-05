#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
Codex 助手（原生桌面版） — relay v0.5.8 + 国产大模型 for Codex (macOS)
=====================================================================
把原 codex-setup-macos.command 的全部功能做成原生 Tkinter 桌面 App：
不弹 Terminal，所有 6 组菜单逻辑原生重实现。

打包结构 (Codex Setup-Native.app):
  Contents/MacOS/Codex-Setup-Native      <- 可执行壳 (shebang 运行本文件)
  Contents/Resources/codex_setup_gui.py  <- 本文件
  Contents/Resources/codex-relay.bin     <- 从原脚本解出的 relay 二进制
  Contents/Resources/relay-gateway.bin   <- 从原脚本解出的网关二进制

开发目录运行（未打包）时，本文件会尝试从同目录的 codex-relay.bin /
relay-gateway.bin，或上级 codex-setup-macos.command 的 #B64/#GWB64 区解码。
"""
import os, sys, json, base64, gzip, re, glob, shutil, sqlite3, time, subprocess, threading, shlex

PY = sys.executable or "/usr/bin/python3"

HOME = os.path.expanduser("~")
CODEX_DIR = os.path.join(HOME, ".codex")
CONFIG = os.path.join(CODEX_DIR, "config.toml")
AUTH = os.path.join(CODEX_DIR, "auth.json")
VARS = os.path.join(CODEX_DIR, "_vars.sh")
RS = os.path.join(CODEX_DIR, "restart-relay.sh")
LA_DIR = os.path.join(HOME, "Library", "LaunchAgents")
LA = os.path.join(LA_DIR, "com.codex.relay.plist")
BIN_DIR = os.path.join(HOME, ".local", "bin")
RELAY_BIN = os.path.join(BIN_DIR, "codex-relay")
GW_BIN = os.path.join(BIN_DIR, "relay-gateway")
GW_CFG = os.path.join(CODEX_DIR, "gateway-config.json")
GW_LOG = "/tmp/relay-gateway.log"
CATALOG = os.path.join(CODEX_DIR, "codex-relay-models.json")
KEEP_LOG = "/tmp/codex-relay-keepalive.log"
# 每模型上下文窗口档位记忆（json，隔离于 _vars.sh，避免污染 shell 变量）
CTX_FILE = os.path.join(CODEX_DIR, "_ctxov.json")
# 磁盘历史目录：relay 用磁盘持久化历史（重启不丢 reasoning_content，规避 400）
HIST_DIR = os.path.join(CODEX_DIR, "codex-relay-history")
RLPORT = 4446
GWPORT = 4447

# ── 模型数据库（与原脚本逐项一致）──
CODES = ["D1","D2","D3","Q1","Q2","K1","K2","G1","G2","G3","G4","M1","M2","M3","M4","X1","X2","X3","X4","T1","T2"]
NAMES = ["deepseek-v4-pro","deepseek-v4-flash","deepseek-v4-flash-vision-exp","qwen3.8-max","qwen3.7-max","kimi-k3","kimi-k2.7-code","glm-5.3","glm-5.3","glm-5.3-flash","glm-5.3-flash","MiniMax-M3","MiniMax-M2.7","MiniMax-M3","MiniMax-M2.7","mimo-v2.5-pro","mimo-v2.5","mimo-v2.5-pro","mimo-v2.5","hy3","hy4-preview"]
PROVIDERS = ["DeepSeek","DeepSeek","DeepSeek","Qwen","Qwen","Kimi","Kimi","GLM-TP","GLM","GLM-TP","GLM","MiniMax","MiniMax","MiniMax-TP","MiniMax-TP","Xiaomi","Xiaomi","Xiaomi-TP","Xiaomi-TP","Tencent","Tencent"]
URLS = ["https://api.deepseek.com/v1"]*3 + ["https://dashscope.aliyuncs.com/compatible-mode/v1"]*2 + ["https://api.moonshot.cn/v1"]*2 + ["https://open.bigmodel.cn/api/coding/paas/v4","https://open.bigmodel.cn/api/paas/v4","https://open.bigmodel.cn/api/coding/paas/v4","https://open.bigmodel.cn/api/paas/v4"] + ["https://api.minimaxi.com/v1"]*4 + ["https://api.xiaomimimo.com/v1"]*2 + ["https://token-plan-cn.xiaomimimo.com/v1"]*2 + ["https://api.lkeap.cloud.tencent.com/plan/v3"]*2
KEYS = ["DEEPSEEK_API_KEY"]*3 + ["DASHSCOPE_API_KEY"]*2 + ["MOONSHOT_API_KEY"]*2 + ["GLM_TOKENPLAN_API_KEY","ZHIPU_API_KEY","GLM_TOKENPLAN_API_KEY","ZHIPU_API_KEY"] + ["MINIMAX_API_KEY"]*2 + ["MINIMAX_TOKENPLAN_API_KEY"]*2 + ["XIAOMI_API_KEY"]*2 + ["XIAOMI_TOKENPLAN_API_KEY"]*2 + ["TENCENT_API_KEY"]*2
NOTES = ["旗舰","次旗舰","视觉理解","旗舰","次旗舰","旗舰","代码专精","旗舰·套餐","旗舰","多模态·套餐","多模态·标准","旗舰","次旗舰","旗舰·TP","次旗舰·TP","旗舰","次旗舰","旗舰·TP","次旗舰·TP","旗舰","预览版"]
DESC = {
 "deepseek-v4-pro":"DeepSeek 最新旗舰，复杂任务强",
 "deepseek-v4-flash":"DeepSeek 次旗舰，轻量快速省 token",
 "deepseek-v4-flash-vision-exp":"DeepSeek 视觉理解模型，支持图片输入（实验版）",
 "qwen3.8-max":"通义最新旗舰，1M 上下文",
 "qwen3.7-max":"通义次旗舰，综合均衡",
 "kimi-k3":"Kimi 最新旗舰，2.8T 参数 1M 上下文",
 "kimi-k2.7-code":"Kimi 代码专精，次旗舰",
 "glm-5.3":"智谱最新旗舰，1M 上下文（标准/套餐视所选）",
 "glm-5.3-flash":"智谱多模态轻量，1M 上下文、支持图片",
 "MiniMax-M3":"MiniMax 最新旗舰 M3，1M 上下文",
 "MiniMax-M2.7":"MiniMax 次旗舰 M2.7",
 "mimo-v2.5-pro":"小米最新旗舰 MiMo-V2.5-Pro，1M 上下文",
 "mimo-v2.5":"小米旗舰 MiMo-V2.5，1M 上下文",
 "hy3":"腾讯混元 Hy3 旗舰（Token Plan）",
 "hy4-preview":"腾讯混元 Hy4 预览版，与 hy3 同一 Token Plan",
}

# ── 上下文窗口（CW/MCW）每模型独立档位 ──
CTX_AUTO  = '自动（按官方规格）'
CTX_SMALL = '128K · 256K'
CTX_BIG   = '256K · 1M'
CTX_BIG2  = '512K · 1M'
CTX_OPTS  = [CTX_AUTO, CTX_SMALL, CTX_BIG, CTX_BIG2]
# 每模型官方真实窗口：slug -> (CW, MCW)；「自动」档即按此表取值。key 即模型名（无 -TP）。
SPEC_CTX = {
 'deepseek-v4-pro':(262144,1048576),
 'deepseek-v4-flash':(262144,1048576),
 'deepseek-v4-flash-vision-exp':(262144,1048576),
 'qwen3.8-max':(262144,1048576),
 'qwen3.7-max':(262144,1048576),
 'kimi-k3':(262144,1048576),
 'kimi-k2.7-code':(131072,262144),      # 官方仅 128K/256K，勿标 1M
 'glm-5.3':(262144,1048576),
 'glm-5.3-flash':(131072,262144),       # 多模态轻量保守 128K/256K
 'MiniMax-M3':(262144,1048576),
 'MiniMax-M2.7':(131072,209920),        # 官方 ~205K，勿标 1M
 'mimo-v2.5-pro':(262144,1048576),
 'mimo-v2.5':(262144,1048576),
 'hy3':(131072,262144),                 # 官方仅 128K/256K，勿标 1M
 'hy4-preview':(262144,1048576),
}
N = len(CODES)
MODELS = [dict(code=CODES[i], name=NAMES[i], provider=PROVIDERS[i],
               url=URLS[i], key=KEYS[i], note=NOTES[i]) for i in range(N)]

VENDOR_BASE = ["DeepSeek","Qwen","Kimi","GLM","MiniMax","Xiaomi","Tencent"]
# 每厂商基础 API key 变量
KEYVAR = {"DeepSeek":"DEEPSEEK_API_KEY","Qwen":"DASHSCOPE_API_KEY","Kimi":"MOONSHOT_API_KEY",
          "GLM":"ZHIPU_API_KEY","MiniMax":"MINIMAX_API_KEY","Xiaomi":"XIAOMI_API_KEY","Tencent":"TENCENT_API_KEY"}
# 支持套餐订阅的厂商（额外 key 槽位）
KEYVAR_TP = {"GLM":"GLM_TOKENPLAN_API_KEY","MiniMax":"MINIMAX_TOKENPLAN_API_KEY","Xiaomi":"XIAOMI_TOKENPLAN_API_KEY"}
# 网关向上游鉴权时可能用到的全部厂商 key 环境变量名（对应 gateway-config.json 的 api_key_env）
ALL_KEY_VARS = sorted(set(list(KEYVAR.values()) + list(KEYVAR_TP.values())))
GUIDES = {"DeepSeek":"https://platform.deepseek.com/api_keys",
          "Qwen":"https://bailian.console.aliyun.com/",
          "Kimi":"https://platform.moonshot.cn/console/api-keys",
          "GLM":"https://bigmodel.cn/apikey/platform",
          "MiniMax":"https://platform.minimaxi.com/user-center/payment/token-plan",
          "Xiaomi":"https://platform.xiaomimimo.com/",
          "Tencent":"https://console.cloud.tencent.com/tokenhub/tokenplan?regionId=1"}

def base_of(p):
    return p[:-3] if p.endswith("-TP") else p

def find_index_by_code(code):
    for i, m in enumerate(MODELS):
        if m["code"] == code:
            return i
    return -1

# ── 小工具 ──
def run(argv, timeout=None, env=None):
    try:
        e = os.environ.copy()
        if env: e.update(env)
        return subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=timeout, text=True, env=e)
    except Exception:
        return None

def lsof_port(port):
    r = run(["/usr/sbin/lsof", "-ti", ":%d" % port])
    return r is not None and r.returncode == 0

def pkillf(pat):
    run(["pkill", "-f", pat])

def read_auth():
    try:
        if os.path.exists(AUTH):
            with open(AUTH, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def write_auth(kv):
    try:
        os.makedirs(CODEX_DIR, exist_ok=True)
        d = read_auth()
        d.update(kv)
        with open(AUTH, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

def _auth_env_override():
    """收集 auth.json 里已填写的各厂商 key 环境变量（只取非空槽位）。
    仅用于拉起网关时覆盖其可能继承到的旧值；不改动用户本机 shell 环境。"""
    out = {}
    try:
        auth = read_auth()
        for k in ALL_KEY_VARS:
            v = (auth.get(k) or "").strip()
            if v:
                out[k] = v
    except Exception:
        pass
    return out

def _gateway_env():
    """网关子进程环境 = 当前环境 + auth.json 中最新的各厂商 key。
    这样『管理 API Key』里新填的 key 一『应用并启动』就生效。"""
    env = os.environ.copy()
    env.update(_auth_env_override())
    return env

def find_avail_port(start=RLPORT):
    for port in range(start, 50000):
        if not lsof_port(port):
            return port
    return RLPORT

def close_codex():
    pkillf("Codex.app/Contents/MacOS/Codex")
    time.sleep(2)

def find_codex_cli():
    """在受限 PATH（Finder 启动）下也能定位 codex CLI。"""
    cands = [shutil.which("codex")]
    for base in (BIN_DIR, os.path.join(HOME, ".codex", "bin"),
                 "/opt/homebrew/bin", "/usr/local/bin"):
        cands.append(os.path.join(base, "codex"))
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None

def migrate(model, provider):
    """遍历 ~/.codex/*.sqlite，把 threads 迁移到新 provider/model。"""
    out = []
    try:
        for f in glob.glob(os.path.join(CODEX_DIR, "*.sqlite")):
            try:
                conn = sqlite3.connect(f)
                tbl = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='threads'").fetchone()
                if not tbl:
                    conn.close(); continue
                before = conn.execute("SELECT id, model_provider, model FROM threads").fetchall()
                needs = any(r[1] != provider or r[2] != model for r in before)
                if needs:
                    conn.close()
                    backup = f + ".before-model-migration-" + time.strftime("%Y%m%d-%H%M%S")
                    shutil.copy2(f, backup)
                    out.append("  备份会话库 → " + os.path.basename(backup))
                    conn = sqlite3.connect(f)
                cur = conn.execute("UPDATE threads SET model_provider=?, model=?", (provider, model))
                out.append("  已迁移 %d 条会话 → %s / %s" % (cur.rowcount, provider, model))
                conn.commit(); conn.close()
            except Exception as e:
                out.append("  跳过 %s: %s" % (os.path.basename(f), e))
    except Exception as e:
        out.append("  migrate err: %s" % e)
    return out

# ── 二进制解包 ──
def _script_path():
    """定位打包用源脚本（开发目录上级 codex-setup-macos.command）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "codex-setup-macos.command"),
                 os.path.join(os.path.dirname(here), "codex-setup-macos.command"),
                 os.path.join(os.path.dirname(here), "MAC-codex辅助安装", "codex-setup-macos.command")):
        if os.path.isfile(cand):
            return cand
    return None

def _res_binary(kind):
    """在 Resources/同目录找已解出的二进制；kind in ('relay','gateway')。"""
    here = os.path.dirname(os.path.abspath(__file__))
    names = {"relay": ["codex-relay", "codex-relay.bin"],
             "gateway": ["relay-gateway", "relay-gateway.bin", "relay-gateway"]}
    for root in (here, os.path.join(here, "..", "Resources"),
                 os.path.join(HOME, ".local", "bin")):
        for nm in names[kind]:
            p = os.path.normpath(os.path.join(root, nm))
            if os.path.isfile(p) and os.path.getsize(p) > 1048576:
                return p
    return None

def _decode_marker(start, end):
    """从原脚本里按 marker 解出 gzip+base64 二进制。"""
    sp = _script_path()
    if not sp:
        return None
    parts = []
    inside = False
    try:
        with open(sp, encoding="utf-8", errors="replace") as f:
            for line in f:
                s = line.rstrip("\n").rstrip("\r")
                if s == end:
                    inside = False
                elif s == start:
                    inside = True
                elif inside and s:
                    parts.append(s)
    except Exception:
        return None
    if not parts:
        return None
    try:
        data = base64.b64decode("".join(parts))
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        return data
    except Exception:
        return None

def deploy_binary(kind):
    """把 relay/gateway 二进制部署到 ~/.local/bin，返回路径或 None。"""
    target = RELAY_BIN if kind == "relay" else GW_BIN
    os.makedirs(BIN_DIR, exist_ok=True)
    # 1) 已解出的资源
    src = _res_binary(kind)
    data = None
    if src:
        try:
            data = open(src, "rb").read()
        except Exception:
            data = None
    # 2) 从原脚本解码
    if not data:
        start, end = ("#B64", "#B64END") if kind == "relay" else ("#GWB64", "#GWB64END")
        data = _decode_marker(start, end)
    if not data or len(data) < 1048576:
        return None
    try:
        open(target, "wb").write(data)
        os.chmod(target, 0o755)
        return target
    except Exception:
        return None

def extract_bundled_relay():
    return deploy_binary("relay")
def extract_bundled_gateway():
    return deploy_binary("gateway")

# ── 汇聚网关 ──
def gen_gateway_config():
    """生成 gateway-config.json：处理同名普通/-TP 冲突的计费偏好路由。"""
    auth = read_auth()
    billing = {}
    for v in VENDOR_BASE:
        bp = auth.get("BILLING_PREF_" + v, "")
        if bp:
            billing[v] = bp
    cands = {}
    for n, p in zip(NAMES, PROVIDERS):
        cands.setdefault(n, []).append(p)
    def pick_prov(ps):
        if len(ps) == 1:
            return ps[0]
        b0 = base_of(ps[0])
        pref = billing.get(b0, "")
        want = pref == "tp"
        same = [p for p in ps if p.endswith("-TP") == want]
        return same[0] if same else ps[0]
    providers, models = {}, {}
    for n, p, u, k in zip(NAMES, PROVIDERS, URLS, KEYS):
        chosen = pick_prov(cands[n])
        if p != chosen:
            continue
        providers.setdefault(p, {"base_url": u, "api_key_env": k})
        models[n] = p
    cfg = {"port": GWPORT, "providers": providers, "models": models}
    os.makedirs(CODEX_DIR, exist_ok=True)
    with open(GW_CFG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return "%d models, %d providers" % (len(models), len(providers))

def start_gateway():
    pkillf("relay-gateway"); time.sleep(1)
    gp = extract_bundled_gateway()
    if not gp:
        return False, "网关二进制提取失败"
    gen_gateway_config()
    logf = open(GW_LOG, "w")
    subprocess.Popen([gp, GW_CFG], stdout=logf, stderr=subprocess.STDOUT, env=_gateway_env())
    for _ in range(12):
        if lsof_port(GWPORT):
            return True, "网关已启动 127.0.0.1:%d" % GWPORT
        try:
            if re.search(r"fail|error|invalid", open(GW_LOG, errors="replace").read()):
                break
        except Exception:
            pass
        time.sleep(0.5)
    return False, "网关启动失败，看 %s" % GW_LOG

# ── relay 启动/重启 ──
def _do_start_relay(re_extract=True):
    """启动 relay。返回 (ok, lines)。"""
    lines = []
    pkillf("codex-relay")
    agg = os.environ.get("GUI_AGG", "0") == "1"
    if agg:
        if not lsof_port(GWPORT):
            gp = extract_bundled_gateway()
            if gp:
                logf = open(GW_LOG, "w")
                subprocess.Popen([gp, GW_CFG], stdout=logf, stderr=subprocess.STDOUT,
                                 env=_gateway_env())
                time.sleep(2)
    else:
        pkillf("relay-gateway")
    time.sleep(2)
    upstream = _upstream_of(agg)
    port = find_avail_port()
    _STATE["PORT"] = str(port)          # 记录 relay 实际监听端口，供 write_config 复用
    rp = extract_bundled_relay() if re_extract else _existing_relay()
    if not rp:
        return False, lines + ["relay 二进制缺失，先点一次『应用设置』完整安装"]
    auth = read_auth()
    relay_key = auth.get(_model_key(), "") or ""
    if not relay_key:
        return False, lines + ["API Key 还没填，补一下就能用"]
    lines.append("relay port: %d   upstream: %s" % (port, upstream))
    if _launch_relay(rp, port, upstream, relay_key, lines):
        return True, lines
    return False, lines

def _upstream_of(agg):
    return "http://127.0.0.1:%d/v1" % GWPORT if agg else _model_url()

def _model_key():
    # 由当前 M 决定 key 槽位；默认 DeepSeek
    i = find_index_by_code(_STATE.get("M_code", "D1"))
    if i < 0:
        i = 0
    return MODELS[i]["key"]

def _model_url():
    i = find_index_by_code(_STATE.get("M_code", "D1"))
    if i < 0:
        i = 0
    return MODELS[i]["url"]

def _existing_relay():
    rp = shutil.which("codex-relay")
    if rp and os.access(rp, os.X_OK):
        return rp
    for c in (RELAY_BIN, os.path.join(os.path.dirname(sys.executable), "codex-relay")):
        if os.access(c, os.X_OK):
            return c
    return extract_bundled_relay()

def _launch_relay(rp, port, upstream, key, lines):
    # 磁盘历史模式：重启不丢 reasoning_content（规避上游 400）
    try:
        os.makedirs(HIST_DIR, exist_ok=True)
    except Exception:
        pass
    args = [rp, "--port", str(port), "--upstream", upstream,
            "--api-key", key, "--history-store", "disk", "--history-dir", HIST_DIR]
    proc = subprocess.Popen(args,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    if lsof_port(port):
        lines.append("✔ relay 已启动")
        return True
    lines.append("relay 未响应，重试…")
    proc.kill()
    pkillf("codex-relay"); time.sleep(2)
    subprocess.Popen(args,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(4)
    if lsof_port(port):
        lines.append("✔ relay 已启动")
        return True
    lines.append("relay 在端口 %d 没起来" % port)
    return False

def start_relay():
    return _do_start_relay(re_extract=True)

def relay_restart():
    return _do_start_relay(re_extract=False)

# ── 配置写入（config 等价）──
def write_config(log, port=None):
    st = _STATE
    # 优先复用 relay 实际监听端口（_do_start_relay 已写入 _STATE["PORT"]），
    # 避免重复 find_avail_port() 因 relay 已占用而跳到下一个端口，导致 base_url 与 relay 不一致。
    port = port or int(str(st.get("PORT") or RLPORT))
    os.makedirs(CODEX_DIR, exist_ok=True)
    # 从 auth 读 inline key
    inline_key = read_auth().get(st["K"], "")
    vendor_models = _catalog_slugs(st)
    if not vendor_models:
        vendor_models = [st["M"]]
    _gen_catalog(st, vendor_models, log)
    account = read_auth().get("ACCOUNT_NAME", "") or base_of(st["P"])
    catalog_line = ""
    if os.path.isfile(CATALOG):
        catalog_line = 'model_catalog_json = "%s"' % CATALOG
    content = (
        'model_provider = "custom"\n\n'
        'model = "%s"\n\n'
        'model_reasoning_effort = "%s"\n\n'
        '%s\n\n'
        '[model_providers.custom]\n'
        'name = "%s"\n'
        'base_url = "http://127.0.0.1:%d/v1"\n'
        'wire_api = "responses"\n'
        'requires_openai_auth = false\n'
        'api_key = "%s"\n'
        % (st["M"], st["RE"], catalog_line, account, port, inline_key))
    try:
        with open(CONFIG, "w", encoding="utf-8") as f:
            f.write(content)
        log.append("✔ 配置已写入")
    except Exception as e:
        log.append("配置写不进去: %s" % e)
        return
    save_state()
    for l in migrate(st["M"], "custom"):
        log.append(l)

def _catalog_slugs(st):
    agg = st["agg"]
    slugs = []
    if agg:
        for n in NAMES:
            if n not in slugs:
                slugs.append(n)
    else:
        pbase = base_of(st["P"])
        for i, p in enumerate(PROVIDERS):
            if base_of(p) == pbase:
                n = NAMES[i]
                if n not in slugs:
                    slugs.append(n)
    return slugs

def _gen_catalog(st, slugs, log):
    codex = find_codex_cli()
    bundled = []
    template = None
    if codex:
        r = run([codex, "debug", "models", "--bundled"], timeout=15)
        if r and r.returncode == 0:
            try:
                data = json.loads(r.stdout)
                bundled = data.get("models") or []
            except Exception:
                bundled = []
        if bundled:
            template = next((m for m in bundled if m.get("visibility") == "list"),
                            bundled[0])
    srs = st["srs"] in ("1", "true", "yes", True)
    re_eff = st["re"]

    def override(e, slug):
        # 每模型独立 CW/MCW：手动档优先，否则自动按官方规格表
        ctx, mctx = CtxFor(slug)
        e["slug"] = slug; e["display_name"] = slug
        e["description"] = "%s via %s" % (slug, st["P"])
        e["visibility"] = "list"; e["supported_in_api"] = True
        e["context_window"] = ctx; e["max_context_window"] = mctx
        e["supports_parallel_tool_calls"] = True
        if "supports_reasoning_summaries" in e: e["supports_reasoning_summaries"] = srs
        if "supports_reasoning_summary_parameter" in e: e["supports_reasoning_summary_parameter"] = srs
        e["input_modalities"] = ["text"]
        if "prefer_websockets" in e: e["prefer_websockets"] = False
        # 推理强度档位：界面保留丰富档位，由 relay 负责按各上游合法值翻译
        e["supported_reasoning_levels"] = [
            {"effort": "none", "description": "关闭思考，最快响应"},
            {"effort": "low", "description": "轻量，快速"},
            {"effort": "medium", "description": "均衡"},
            {"effort": "high", "description": "深度推理"},
            {"effort": "xhigh", "description": "极高深度"},
            {"effort": "max", "description": "满血（max）"}]
        allowed = {lvl.get("effort") for lvl in e["supported_reasoning_levels"]}
        e["default_reasoning_level"] = re_eff if re_eff in allowed else "medium"
        if "default_reasoning_summary" in e: e["default_reasoning_summary"] = "concise"
        if "supports_image_detail_original" in e: e["supports_image_detail_original"] = False
        e["supports_search_tool"] = False; e["use_responses_lite"] = False
        e["tool_mode"] = None; e["multi_agent_version"] = None
        e["experimental_supported_tools"] = []
        e["additional_speed_tiers"] = []; e["service_tiers"] = []
        e["default_service_tier"] = None; e["availability_nux"] = None
        e["upgrade"] = None; e["auto_review_model_override"] = None
        e["auto_compact_token_limit"] = None; e["comp_hash"] = None
        e.pop("minimal_client_version", None); e.pop("available_in_plans", None)
        return e

    models = [m for m in bundled if m.get("slug") in set(slugs)]
    for i, slug in enumerate(slugs):
        if template is not None:
            entry = json.loads(json.dumps(template))
        else:
            _c, _m = CtxFor(slug)
            entry = {"slug": slug, "display_name": slug,
                     "description": "%s via %s" % (slug, st["P"]),
                     "visibility": "list", "supported_in_api": True, "priority": 10000 + i,
                     "default_reasoning_level": "low", "supported_reasoning_levels": [],
                     "default_reasoning_summary": "none", "support_verbosity": False,
                     "default_verbosity": None, "shell_type": "shell_command",
                     "apply_patch_tool_type": "freeform", "web_search_tool_type": "text_and_image",
                     "truncation_policy": {"mode": "tokens", "limit": 10000},
                     "supports_parallel_tool_calls": True,
                     "supports_image_detail_original": False,
                     "context_window": _c, "max_context_window": _m, "comp_hash": None,
                     "effective_context_window_percent": 95,
                     "experimental_supported_tools": [],
                     "input_modalities": ["text"], "supports_search_tool": False,
                     "use_responses_lite": False, "tool_mode": None,
                     "multi_agent_version": None, "include_skills_usage_instructions": False,
                     "base_instructions": "You are Codex, an agent that collaborates with the user to complete software engineering tasks.",
                     "model_messages": {"instructions_template": "You are Codex, an agent that collaborates with the user to complete software engineering tasks."},
                     "supports_reasoning_summaries": srs,
                     "supports_reasoning_summary_parameter": srs,
                     "additional_speed_tiers": [], "service_tiers": [],
                     "default_service_tier": None, "availability_nux": None,
                     "upgrade": None, "auto_review_model_override": None,
                     "auto_compact_token_limit": None}
        entry = override(entry, slug)
        entry["priority"] = 10000 + i
        if slug in ("deepseek-v4-flash-vision-exp", "glm-5.3-flash"):
            entry["input_modalities"] = ["text", "image"]
            entry["supports_image_detail_original"] = True
        idx = next((k for k, m in enumerate(models) if m.get("slug") == slug), None)
        if idx is not None:
            models[idx] = entry
        else:
            models.append(entry)
    try:
        os.makedirs(CODEX_DIR, exist_ok=True)
        with open(CATALOG, "w", encoding="utf-8") as f:
            json.dump({"models": models}, f, ensure_ascii=False, indent=2)
        log.append("模型目录: %d 个模型" % len(models))
    except Exception as e:
        log.append("目录写入失败: %s" % e)

def _to_int(v, dflt):
    try:
        return int(v)
    except Exception:
        return dflt

# ── 自动保活（重启脚本 + LaunchAgent）──
def _relay_finder_py():
    """重启脚本定位 relay 用的 python 片段。"""
    return ("import os,sys,shutil\np=shutil.which('codex-relay')\n"
            "if p and os.access(p,os.X_OK): print(p); sys.exit(0)\n"
            "home=os.path.expanduser('~')\n"
            "for c in (os.path.join(home,'.local','bin','codex-relay'),"
            "os.path.join(os.path.dirname(sys.executable),'codex-relay')):\n"
            "    if os.access(c,os.X_OK): print(c); sys.exit(0)\n")

def write_keepalive(log):
    os.makedirs(CODEX_DIR, exist_ok=True)
    agg = _STATE["agg"]
    rp_py = _relay_finder_py()
    script = (
        "#!/bin/zsh\n"
        'CODEX_DIR="$HOME/.codex"\n'
        'AUTH="$CODEX_DIR/auth.json"\n'
        'VARS="$CODEX_DIR/_vars.sh"\n\n'
        "# relay 活着就退出\n"
        "if /usr/sbin/lsof -ti :4446 >/dev/null 2>&1; then exit 0; fi\n"
        'source "$VARS" 2>/dev/null || exit 1\n'
        'RELAY_KEY=$("%s" -c "import json; d=json.load(open(%s)); print(d.get(%s,%s))" 2>/dev/null)\n'
        '[[ -z "$RELAY_KEY" ]] && exit 1\n'
        % (PY, json.dumps(AUTH), json.dumps(_STATE["K"]), json.dumps("")))
    # 网关按 gateway-config.json 的 api_key_env 读它自己的进程环境鉴权；
    # 这里把 auth.json 里最新的各厂商 key export 出来，保活重启网关时也能带上新 key。
    auth_now = read_auth()
    exports = "".join(
        "export %s=%s\n" % (k, shlex.quote((auth_now.get(k) or "").strip()))
        for k in ALL_KEY_VARS if (auth_now.get(k) or "").strip())
    if exports:
        script += "# 厂商 key（来自 auth.json，随『应用并启动』更新）\n" + exports + "\n"
    if agg == 1:
        script += ("# 汇聚模式先保证网关\n"
                   "if ! /usr/sbin/lsof -ti :4447 >/dev/null 2>&1; then\n"
                   '  GPBIN="$HOME/.local/bin/relay-gateway"\n'
                   '  if [[ -x "$GPBIN" ]]; then\n'
                   '    nohup "$GPBIN" "$HOME/.codex/gateway-config.json" > /tmp/relay-gateway.log 2>&1 &\n'
                   "    sleep 2\n  fi\nfi\n\n")
    script += (
        "pkill -f codex-relay 2>/dev/null || true\nsleep 2\n"
        'rp=$("%s" -c "%s" 2>/dev/null)\n'
        '[[ -z "$rp" ]] && exit 1\n'
        'up="%s"\n'
        '[ "%s" = "1" ] && up="http://127.0.0.1:4447/v1"\n'
        'nohup "$rp" --port 4446 --upstream "$up" --api-key "$RELAY_KEY" --history-store disk --history-dir "$HOME/.codex/codex-relay-history" >/dev/null 2>&1 &\nexit 0\n'
        % (PY, rp_py.replace('"', '\\"'), _STATE["U"], "1" if agg == 1 else "0"))
    try:
        with open(RS, "w", encoding="utf-8") as f:
            f.write(script)
        os.chmod(RS, 0o755)
    except Exception as e:
        log.append("重启脚本写入失败: %s" % e)
    # LaunchAgent plist
    try:
        os.makedirs(LA_DIR, exist_ok=True)
        plist = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.codex.relay</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/zsh</string>
        <string>%s</string>
    </array>
    <key>StartInterval</key>
    <integer>60</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>AbandonProcessGroup</key>
    <true/>
    <key>StandardOutPath</key>
    <string>%s</string>
    <key>StandardErrorPath</key>
    <string>%s</string>
</dict>
</plist>
""" % (RS, KEEP_LOG, KEEP_LOG)
        with open(LA, "w", encoding="utf-8") as f:
            f.write(plist)
    except Exception as e:
        log.append("plist 写入失败: %s" % e)
    # 重新加载
    uid = str(os.getuid())
    run(["launchctl", "bootout", "gui/%s/com.codex.relay" % uid])
    if run(["launchctl", "bootstrap", "gui/%s" % uid, LA]) and \
       run(["launchctl", "bootstrap", "gui/%s" % uid, LA]).returncode == 0:
        log.append("✔ 自动保活已开启（LaunchAgent，每 60 秒）")
    else:
        # crontab 降级
        run(["crontab", "-l"])
        cronjob = "*/5 * * * * %s" % RS
        _crontab_filter_out(RS)
        cr = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        current = cr.stdout if cr.returncode == 0 else ""
        subprocess.run(["crontab", "-"], input=(current + cronjob + "\n"), text=True)
        log.append("✔ 自动保活已开启（crontab，每 5 分钟）")

def _crontab_filter_out(needle):
    cr = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if cr.returncode != 0:
        return
    lines = [l for l in cr.stdout.splitlines() if needle not in l]
    subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True)

# ── 停止 ──
def stop_relay(log):
    close_codex()
    pkillf("codex-relay")
    uid = str(os.getuid())
    run(["launchctl", "bootout", "gui/%s/com.codex.relay" % uid])
    try:
        if os.path.exists(LA): os.remove(LA)
    except Exception:
        pass
    _crontab_filter_out(RS)
    log.append("✔ relay 已停止，自动保活已关闭")

# ── 恢复出厂 ──
def uninstall(log):
    log.append("开始恢复出厂设置…")
    close_codex()
    pkillf("codex-relay"); log.append("  relay 已终止")
    pkillf("relay-gateway")
    for f in (GW_CFG,):
        if os.path.exists(f):
            try: os.remove(f)
            except Exception: pass
    log.append("  汇聚网关已停止、配置已清理")
    uid = str(os.getuid())
    run(["launchctl", "bootout", "gui/%s/com.codex.relay" % uid])
    for f in (LA,):
        if os.path.exists(f):
            try: os.remove(f)
            except Exception: pass
    log.append("  LaunchAgent 自动保活已移除")
    _crontab_filter_out(RS)
    for prof in ("~/.zshenv", "~/.bash_profile", "~/.profile", "~/.zshrc"):
        p = os.path.expanduser(prof)
        if not os.path.isfile(p): continue
        try:
            s = open(p, encoding="utf-8", errors="replace").read()
            new = re.sub(r"(?m)^export (%s)=.*\n"
                         % "|".join(list(KEYVAR.values()) + list(KEYVAR_TP.values())), "", s)
            if new != s:
                open(p, "w", encoding="utf-8").write(new)
        except Exception: pass
    log.append("  API Key 环境变量已清除")
    for l in migrate("gpt-5.6-luna", "openai"):
        log.append("  " + l)
    try:
        with open(CONFIG, "w", encoding="utf-8") as f:
            f.write('# Codex default configuration\nmodel = "gpt-5.6-luna"\nmodel_provider = "openai"\nmodel_reasoning_effort = "medium"\nmodel_verbosity = "medium"\napproval_policy = "on-request"\nsandbox_mode = "workspace-write"\nweb_search = "cached"\n')
        log.append("  配置已恢复默认")
    except Exception: pass
    try:
        with open(AUTH, "w", encoding="utf-8") as f:
            f.write("{}")
        log.append("  API Key 已清空")
    except Exception: pass
    for f in (RS, os.path.join(CODEX_DIR, "config.toml.bak"),
              os.path.join(CODEX_DIR, "backup_auth.json"), VARS):
        if os.path.exists(f):
            try: os.remove(f)
            except Exception: pass
    log.append("  辅助文件已清理")
    for pat in (os.path.join(CODEX_DIR, "logs_*.sqlite"),
                os.path.join(CODEX_DIR, "goals_*.sqlite")):
        for m in glob.glob(pat):
            try: os.remove(m)
            except Exception: pass
    for d in ("logs", "cache", ".tmp", ".sandbox", ".sandbox-bin", ".sandbox-secrets"):
        p = os.path.join(CODEX_DIR, d)
        if os.path.isdir(p):
            try: shutil.rmtree(p)
            except Exception: pass
    log.append("  缓存已清理")
    log.append("  全清了～ Codex 回到出厂状态")

def _status_text():
    st = _STATE
    agg = st["agg"]
    lines = ["—— 当前状态 ——"]
    lines.append("模式: %s" % ("汇聚模式（7 厂商一个端口）" if agg else "普通模式（单厂商直连）"))
    lines.append("relay(4446): %s" % ("✔ 运行中" if lsof_port(RLPORT) else "未启动"))
    if agg:
        lines.append("网关(4447): %s" % ("✔ 运行中" if lsof_port(GWPORT) else "未运行"))
    if os.path.isfile(CONFIG):
        m = read_config_model()
        lines.append("当前模型: %s" % (m or "还没设置"))
    else:
        lines.append("配置: 还没初始化")
    return lines

# ── 状态持久化 ──
_STATE = dict(M="deepseek-v4-pro", P="DeepSeek", U=URLS[0], K=KEYS[0],
              RE="high", SRS="true", CW="262144", MCW="1048576",
              PORT=str(RLPORT), AGG="0", GWPORT=str(GWPORT),
              ACCOUNT_NAME="", M_code="D1", agg=0,
              re="high", srs="true", cw="262144", mcw="1048576", m="deepseek-v4-pro")

def load_state():
    d = _STATE
    if os.path.exists(VARS):
        try:
            for line in open(VARS, encoding="utf-8", errors="replace"):
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    v = v.strip().strip('"').strip("'")
                    if k in ("M","P","U","K","RE","SRS","CW","MCW","PORT","AGG","GWPORT","ACCOUNT_NAME"):
                        d[k] = v
        except Exception:
            pass
    if not d.get("M"):
        d["M"] = read_config_model() or "deepseek-v4-pro"
    _sync_state()

def save_state():
    d = _STATE
    _sync_state()
    os.makedirs(CODEX_DIR, exist_ok=True)
    def q(v):
        v = str(v)
        return '"%s"' % v if re.search(r"\s", v) else v
    lines = ["PY=%s" % PY,
             "M=%s" % q(d["M"]), "P=%s" % q(d["P"]), "U=%s" % q(d["U"]),
             "K=%s" % q(d["K"]), "RE=%s" % q(d["RE"]), "SRS=%s" % q(d["SRS"]),
             "CW=%s" % q(d["CW"]), "MCW=%s" % q(d["MCW"]),
             "PORT=%s" % q(d["PORT"]), "AGG=%s" % d["AGG"],
             "GWPORT=%s" % q(d["GWPORT"]), "ACCOUNT_NAME=%s" % q(d["ACCOUNT_NAME"])]
    try:
        with open(VARS, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        pass

def _sync_state():
    d = _STATE
    d["agg"] = 1 if d.get("AGG") == "1" else 0
    d["re"] = d.get("RE", "high"); d["srs"] = d.get("SRS", "true")
    d["cw"] = d.get("CW", "262144"); d["mcw"] = d.get("MCW", "1048576")
    d["m"] = d.get("M", ""); d["p"] = d.get("P", ""); d["u"] = d.get("U", "")
    d["k"] = d.get("K", "")

def _set_state(k, v):
    _STATE[k] = str(v)

# ── 每模型上下文窗口档位（persist to _ctxov.json）──
_CTXOV = {}   # 模型名(slug) -> 档位；缺省/留空 = 自动按官方规格

def _ctx_dump():
    try:
        with open(CTX_FILE, "w", encoding="utf-8") as f:
            json.dump(_CTXOV, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _ctx_load():
    global _CTXOV
    try:
        if os.path.exists(CTX_FILE):
            with open(CTX_FILE, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                _CTXOV = {str(a): str(b) for a, b in d.items()}
    except Exception:
        _CTXOV = {}

def GetCtxLabel(slug):
    return _CTXOV.get(slug, CTX_AUTO)

def SetCtxLabel(slug, label):
    _CTXOV[slug] = label
    _ctx_dump()

def CtxFor(slug):
    """某模型实际 (CW, MCW)：手动档优先，否则自动按官方规格表。"""
    label = _CTXOV.get(slug, CTX_AUTO)
    if label == CTX_SMALL: return (131072, 262144)
    if label == CTX_BIG:   return (262144, 1048576)
    if label == CTX_BIG2:  return (524288, 1048576)
    return SPEC_CTX.get(slug, (262144, 1048576))

def CtxOptionsFor(slug):
    """某模型可选的档位：官方最大窗口不足 1M 的不开放 1M 档，避免虚高触发超限。"""
    _cw, _mctx = SPEC_CTX.get(slug, (262144, 1048576))
    opts = [CTX_AUTO, CTX_SMALL]
    if _mctx >= 1048576:
        opts += [CTX_BIG, CTX_BIG2]
    return opts

def set_model_by_code(code):
    i = find_index_by_code(code)
    if i < 0: return False
    m = MODELS[i]
    _STATE.update(M=m["name"], P=m["provider"], U=m["url"], K=m["key"], M_code=code,
                  RE="high", SRS="true", CW="262144", MCW="1048576",
                  re="high", srs="true", cw="262144", mcw="1048576", m=m["name"])
    return True

def set_mode(agg):
    _STATE["agg"] = 1 if agg else 0
    _STATE["AGG"] = "1" if agg else "0"
    os.environ["GUI_AGG"] = _STATE["AGG"]

def read_config_model():
    try:
        for line in open(CONFIG, encoding="utf-8"):
            if line.startswith("model = "):
                m = re.search(r'"([^"]*)"', line)
                if m: return m.group(1)
    except Exception:
        pass
    return ""

# ═══════════════════════ GUI 层（tkinter，无 Terminal） ═══════════════════════
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

def selfcheck():
    """无 GUI 自检：校验数据表与逻辑函数可导入、可运行。"""
    from tkinter import Tk  # noqa: F401  仅验证能导入
    assert len(MODELS) == len(CODES) == 21
    assert len(set(PROVIDERS)) == 10
    load_state()
    _ctx_load()
    # 全厂商目录（汇聚）生成一次
    st = _STATE
    st["agg"] = 1
    slugs = _catalog_slugs(st)
    assert "deepseek-v4-pro" in slugs and "MiniMax-M2.7" in slugs
    # 单厂商目录
    st["agg"] = 0; set_model_by_code("D1")
    slugs2 = _catalog_slugs(st)
    assert set(slugs2) <= {"deepseek-v4-pro", "deepseek-v4-flash", "deepseek-v4-flash-vision-exp"}
    set_mode(0)
    print("selfcheck OK: 21 模型 / 7 厂商 / 目录逻辑正常")
    return 0

# 颜色
_BG = "#f6f6f6"
_ACCENT = "#1668dc"

class App:
    def __init__(self, root):
        self.root = root
        root.title("Codex 助手 — 国产大模型接入")
        root.geometry("1020x700")
        root.minsize(900, 620)
        root.configure(bg=_BG)
        load_state()
        _ctx_load()
        self._build()
        self._refresh_from_state()
        self._log("就绪。选择模型/模式 → 填 Key → 点『应用并启动』。")

    # ---------- 布局 ----------
    def _build(self):
        top = tk.Frame(self.root, bg=_BG)
        top.pack(fill="x", padx=10, pady=(8, 2))
        tk.Label(top, text="Codex 助手", font=("PingFang SC", 17, "bold"),
                 bg=_BG, fg="#111").pack(side="left")
        tk.Label(top, text="relay v0.5.8 · 原生桌面 · 不弹终端", font=("PingFang SC", 10),
                 bg=_BG, fg="#888").pack(side="left", padx=8)

        mid = tk.Frame(self.root, bg=_BG)
        mid.pack(fill="both", expand=True, padx=10, pady=4)

        # 左：模型列表
        left = tk.Frame(mid, bg="#fff", highlightthickness=1,
                        highlightbackground="#ddd", bd=0)
        left.pack(side="left", fill="both", expand=True)
        tk.Label(left, text="选择默认模型（双击 / 选中后点“设为当前”）",
                 font=("PingFang SC", 11, "bold"), bg="#fff").pack(anchor="w", padx=8, pady=6)
        treef = tk.Frame(left, bg="#fff"); treef.pack(fill="both", expand=True, padx=6, pady=(0,6))
        self.tree = ttk.Treeview(treef, columns=("code", "note"), show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="模型 / 厂商")
        self.tree.column("#0", width=250)
        self.tree.heading("code", text="码"); self.tree.column("code", width=46, anchor="center")
        self.tree.heading("note", text="说明"); self.tree.column("note", width=150)
        ys = ttk.Scrollbar(treef, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ys.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self._pick_selected())
        for v in VENDOR_BASE:
            node = self.tree.insert("", "end", text="▪ " + v, open=True,
                                    tags=("vendor",), values=("", ""))
            for i, m in enumerate(MODELS):
                if base_of(m["provider"]) == v:
                    label = "[%s] %s" % (m["code"], m["name"])
                    if m["provider"].endswith("-TP"):
                        label += " (TP)"
                    self.tree.insert(node, "end", text=label, values=(m["code"], m["note"]))
        self.tree.tag_configure("vendor", font=("PingFang SC", 11, "bold"), foreground=_ACCENT)

        # 右：设置面板
        right = tk.Frame(mid, bg=_BG, width=430)
        right.pack(side="right", fill="y", padx=(10,0))
        right.pack_propagate(False)

        # 模式
        mf = tk.LabelFrame(right, text="模式", bg=_BG, font=("PingFang SC", 11, "bold"))
        mf.pack(fill="x", pady=(0,6))
        self.mode_var = tk.IntVar(value=0)
        tk.Radiobutton(mf, text="普通模式（单厂商直连）", variable=self.mode_var, value=0,
                       bg=_BG, command=self._on_mode).pack(anchor="w", padx=8, pady=2)
        tk.Radiobutton(mf, text="汇聚模式（7 厂商一端口）", variable=self.mode_var, value=1,
                       bg=_BG, command=self._on_mode).pack(anchor="w", padx=8, pady=2)

        # 当前模型
        cf = tk.LabelFrame(right, text="当前选择", bg=_BG, font=("PingFang SC", 11, "bold"))
        cf.pack(fill="x", pady=(0,6))
        self.cur_lbl = tk.Label(cf, text="", justify="left", anchor="w", bg=_BG, fg="#333",
                                font=("PingFang SC", 11))
        self.cur_lbl.pack(fill="x", padx=8, pady=4)
        self.desc_lbl = tk.Label(cf, text="", justify="left", anchor="w", bg=_BG, fg="#888", wraplength=400)
        self.desc_lbl.pack(fill="x", padx=8, pady=(0,4))
        bf = tk.Frame(cf, bg=_BG); bf.pack(anchor="w", padx=8, pady=(0,6))
        tk.Button(bf, text="设为当前模型", command=self._pick_selected,
                  bg=_ACCENT, fg="white", relief="flat", padx=10).pack(side="left")
        tk.Button(bf, text="打开 Key 官网", command=self._open_guide,
                  relief="flat", padx=10).pack(side="left", padx=6)

        # 账户名
        af = tk.LabelFrame(right, text="账户显示名（Codex 界面可见）", bg=_BG, font=("PingFang SC", 11, "bold"))
        af.pack(fill="x", pady=(0,6))
        self.acct_var = tk.StringVar()
        tk.Entry(af, textvariable=self.acct_var).pack(fill="x", padx=8, pady=4)

        # 高级参数（简）
        pr = tk.LabelFrame(right, text="高级（默认即可）", bg=_BG, font=("PingFang SC", 11, "bold"))
        pr.pack(fill="x", pady=(0,6))
        row = tk.Frame(pr, bg=_BG); row.pack(fill="x", padx=8, pady=4)
        tk.Label(row, text="推理强度", bg=_BG).pack(side="left")
        self.re_var = tk.StringVar(value="high")
        cb = ttk.Combobox(row, textvariable=self.re_var, state="readonly", width=10,
                          values=["none", "low", "medium", "high", "xhigh", "max"])
        cb.pack(side="left", padx=6)
        # 上下文窗口（每模型独立档位）
        row2 = tk.Frame(pr, bg=_BG); row2.pack(fill="x", padx=8, pady=4)
        tk.Label(row2, text="上下文窗口", bg=_BG).pack(side="left")
        self.ctx_var = tk.StringVar(value=CTX_AUTO)
        self.ctx_cb = ttk.Combobox(row2, textvariable=self.ctx_var, state="readonly",
                                   width=16, values=CTX_OPTS)
        self.ctx_cb.pack(side="left", padx=6)

        # 操作按钮
        act = tk.LabelFrame(right, text="操作", bg=_BG, font=("PingFang SC", 11, "bold"))
        act.pack(fill="x", pady=(0,6))
        g = tk.Frame(act, bg=_BG); g.pack(fill="x", padx=8, pady=6)
        tk.Button(g, text="应用并启动", command=self._apply, bg="#1aab52", fg="white",
                  relief="flat", font=("PingFang SC", 12, "bold"), padx=14).pack(side="left", fill="x", expand=True)
        g2 = tk.Frame(act, bg=_BG); g2.pack(fill="x", padx=8, pady=(0,6))
        tk.Button(g2, text="仅重启服务", command=self._restart, bg=_ACCENT, fg="white",
                  relief="flat", padx=8).pack(side="left", expand=True, fill="x", padx=(0,3))
        tk.Button(g2, text="停止服务", command=self._stop, bg="#b06000", fg="white",
                  relief="flat", padx=8).pack(side="left", expand=True, fill="x", padx=3)
        tk.Button(g2, text="查看状态", command=self._status, bg="#555", fg="white",
                  relief="flat", padx=8).pack(side="left", expand=True, fill="x", padx=(3,0))
        tk.Button(act, text="恢复出厂设置", command=self._uninstall, bg="#c0392b", fg="white",
                  relief="flat", font=("PingFang SC", 10)).pack(fill="x", padx=8, pady=(0,6))
        tk.Button(act, text="管理 API Key（逐家填写）", command=self._keys_dialog, bg="#333", fg="white",
                  relief="flat", font=("PingFang SC", 10)).pack(fill="x", padx=8, pady=(0,6))

        # 日志
        lf = tk.LabelFrame(self.root, text="日志", bg=_BG, font=("PingFang SC", 10, "bold"))
        lf.pack(fill="both", expand=True, padx=10, pady=(2,8))
        self.logbox = scrolledtext.ScrolledText(lf, height=9, bg="#1e1e1e", fg="#d8d8d8",
                                                 font=("Menlo", 10), state="disabled",
                                                 wrap="word")
        self.logbox.pack(fill="both", expand=True, padx=4, pady=4)

        # 窗口关闭：服务由 KeepAlive 保活，询问
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- 交互 ----------
    def _log(self, msg, end="\n"):
        self.logbox.configure(state="normal")
        self.logbox.insert("end", time.strftime("[%H:%M:%S] ") + str(msg) + end)
        self.logbox.see("end")
        self.logbox.configure(state="disabled")
        self.root.update_idletasks()

    def _refresh_from_state(self):
        d = _STATE
        self.mode_var.set(1 if d["agg"] else 0)
        self.re_var.set(d.get("re", "high"))
        self.acct_var.set(read_auth().get("ACCOUNT_NAME", d.get("account", "")))
        m = next((x for x in MODELS if x["name"] == d["M"]), MODELS[0])
        self._show_model(m)

    def _show_model(self, m):
        prov = m["provider"]
        note = m["note"]
        self.cur_lbl.configure(text="%s  %s  [%s]  %s" % (prov, m["name"], m["code"], note))
        desc = DESC.get(m["name"], "")
        if prov.endswith("-TP"):
            desc += "（套餐计费，走 %s）" % m["url"]
        else:
            desc += "\nURL: " + m["url"]
        self.desc_lbl.configure(text=desc)
        # 按当前模型刷新「上下文窗口」可选档位并回显
        opts = CtxOptionsFor(m["name"])
        self.ctx_cb.configure(values=opts)
        l = GetCtxLabel(m["name"])
        self.ctx_var.set(l if l in opts else CTX_AUTO)

    def _selected_model(self):
        sel = self.tree.selection()
        if sel:
            vals = self.tree.item(sel[0], "values")
            if vals and vals[0]:
                code = vals[0]
                i = find_index_by_code(code)
                if i >= 0:
                    return MODELS[i]
        # 回退当前
        m = next((x for x in MODELS if x["name"] == _STATE["M"]), MODELS[0])
        return m

    def _pick_selected(self):
        m = self._selected_model()
        set_model_by_code(m["code"])
        self._show_model(m)
        self._log("已选: %s / %s (%s)" % (m["provider"], m["name"], m["code"]))

    def _open_guide(self):
        m = self._selected_model()
        base = base_of(m["provider"])
        url = GUIDES.get(base, "")
        if url:
            self._open_browser(url)
            self._toast("已打开官网", "已在浏览器为你打开 %s 的 Key 官网页面。" % base, "info")
        else:
            self._toast("暂无官网", "该模型暂时没有配置官网链接。", "warn")

    def _on_mode(self):
        set_mode(self.mode_var.get() == 1)
        self._log("模式: " + ("汇聚模式" if _STATE["agg"] else "普通模式"))
        if _STATE["agg"]:
            self._log("提示：汇聚模式下建议在“应用并启动”前把各厂商 Key 填全（通过 Key 官网逐家获取）。")

    def _open_browser(self, url):
        # 用 open 打开浏览器，不弹终端
        subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _confirm(self, title, msg):
        return messagebox.askyesno(title, msg, parent=self.root)

    def _on_close(self):
        if self._confirm("退出", "服务由 LaunchAgent 自动保活，可后台常驻。\n确定关闭窗口吗？（服务不会停止）"):
            self.root.destroy()

    # ---------- 操作（后台线程跑逻辑，避免卡 UI） ----------
    _KIND_STYLE = {
        "ok":   ("#1aab52", "✔", "成功"),
        "err":  ("#c0392b", "✕", "出错"),
        "warn": ("#e67e22", "!",  "请注意"),
        "info": (_ACCENT,    "ℹ", "提示"),
    }

    def _busy(self, fn, done=None):
        """起后台线程执行；完成后回到主线程并（可选）弹总结。
        done: callable(lines)->dict{kind,title,msg}，用于按钮成功后给用户直观反馈。"""
        self.root.configure(cursor="watch")
        self.root.update_idletasks()
        res = {}
        def work():
            try:
                lines = fn() or []
                res["lines"] = list(lines)
                if done:
                    try:
                        res["done"] = done(list(lines))
                    except Exception as e:
                        res["done"] = {"kind": "err", "title": "出错", "msg": "%s" % e}
            except Exception as e:
                res["lines"] = ["出错: %s" % e]
                res["done"] = {"kind": "err", "title": "操作出错", "msg": "%s" % e}
            finally:
                self.root.after(0, self._busy_done, res)
        threading.Thread(target=work, daemon=True).start()

    def _busy_done(self, res):
        self.root.configure(cursor="")
        for l in res.get("lines", []):
            self._log(l)
        d = res.get("done")
        if d:
            self.root.after(80, lambda: self._toast(
                d.get("title", "结果"), d.get("msg", ""), d.get("kind", "info")))
        self.root.update_idletasks()

    def _result(self, lines, ok_title, ok_msg, ok_substr):
        """把动作日志归纳成一句用户友好的弹窗结果。"""
        joined = "\n".join(lines or [])
        for bad in ("出错", "失败", "错误", "✘", "没起来", "未响应", "启动失败", "提取失败"):
            for l in lines or []:
                if bad in l:
                    return {"kind": "err", "title": "操作失败",
                            "msg": l.strip().lstrip("✘ ")}
        if ok_substr and ok_substr in joined:
            return {"kind": "ok", "title": ok_title, "msg": ok_msg}
        if lines:
            last = (lines[-1] or "").strip().lstrip("✔ ")
            if last:
                return {"kind": "info", "title": ok_title, "msg": last}
        return {"kind": "ok", "title": ok_title, "msg": ok_msg}

    def _toast(self, title, message, kind="info", ok_text="知道了"):
        """点击按钮后弹出的精美结果卡片（非日志放大版）。"""
        color, glyph, _ = self._KIND_STYLE.get(kind, self._KIND_STYLE["info"])
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)          # 无系统边框，做轻量卡片
        win.configure(bg="#ffffff")
        win.attributes("-topmost", True)
        win.transient(self.root)
        head = tk.Frame(win, bg=color, height=6); head.pack(fill="x")
        body = tk.Frame(win, bg="#ffffff"); body.pack(fill="both", expand=True, padx=22, pady=16)
        trow = tk.Frame(body, bg="#ffffff"); trow.pack(fill="x")
        tk.Label(trow, text=glyph, bg="#ffffff", fg=color,
                 font=("PingFang SC", 26, "bold")).pack(side="left")
        tk.Label(trow, text=title, bg="#ffffff", fg="#111",
                 font=("PingFang SC", 15, "bold")).pack(side="left", padx=(10, 0))
        def _close():
            try:
                win.grab_release()
            except Exception:
                pass
            win.destroy()
        tk.Button(trow, text="✕", command=_close, relief="flat", bd=0,
                  bg="#ffffff", fg="#999", font=("PingFang SC", 12),
                  activebackground="#fff", cursor="hand2").pack(side="right")
        tk.Label(body, text=message, bg="#ffffff", fg="#444", justify="left",
                 anchor="w", wraplength=380, font=("PingFang SC", 12)).pack(fill="x", pady=(12, 18))
        brow = tk.Frame(body, bg="#ffffff"); brow.pack(anchor="e")
        tk.Button(brow, text=ok_text, command=_close, bg=color, fg="white",
                  relief="flat", padx=22, pady=4, font=("PingFang SC", 12, "bold"),
                  cursor="hand2", activebackground=color).pack()
        win.bind("<Return>", lambda e: _close())
        win.bind("<Escape>", lambda e: _close())
        win.update_idletasks()
        w, h = 460, win.winfo_reqheight()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - w) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - h) // 2
        win.geometry("%dx%d+%d+%d" % (w, h, max(x, 0), max(y, 0)))
        try:
            win.grab_set()
        except Exception:
            pass
        win.focus_force()

    def _save_keys_from_ui(self):
        """把 GUI 收集到的键位写入 auth.json。此处由各动作调用。"""
        pass  # 本版 key 由 apply 流程从 auth 读取既有值；预留扩展

    def _apply(self):
        m = self._selected_model()
        set_model_by_code(m["code"])
        set_mode(self.mode_var.get() == 1)
        d = _STATE
        d["re"] = self.re_var.get(); d["RE"] = d["re"]
        acc = self.acct_var.get().strip()
        if acc:
            write_auth({"ACCOUNT_NAME": acc})
        self._show_model(m)
        if not read_auth().get(m["key"]):
            tip = "该模型需要 %s，先点左下角“管理 API Key”填写，或点“打开 Key 官网”获取。" % m["key"]
            self._log(tip)
            self._toast("缺少 API Key", tip, "warn")
            return
        if self.ctx_var.get() in CtxOptionsFor(m["name"]):
            SetCtxLabel(m["name"], self.ctx_var.get())
        if d["agg"]:
            self._log("汇聚模式：启动网关 + relay + 全量模型目录…")
        self._busy(self._do_apply, lambda lines: self._result(
            lines, "应用并启动", "服务已启动，配置与自动保活已就绪，可以开始使用了。", "✔ 全部就绪"))

    def _do_apply(self):
        d = _STATE
        lines = []
        close_codex()
        agg = d["agg"]
        if agg:
            ok, msg = start_gateway()
            lines.append(msg)
            if not ok:
                return lines
            os.environ["GUI_AGG"] = "1"
        else:
            pkillf("relay-gateway")
        ok, rlines = start_relay()
        lines += rlines
        if not ok:
            return lines
        write_config(lines)
        write_keepalive(lines)
        lines.append("✔ 全部就绪")
        return lines

    def _restart(self):
        set_mode(self.mode_var.get() == 1)
        d = _STATE
        d["re"] = self.re_var.get(); d["RE"] = d["re"]
        m = self._selected_model()
        if self.ctx_var.get() in CtxOptionsFor(m["name"]):
            SetCtxLabel(m["name"], self.ctx_var.get())
        self._busy(self._do_restart, lambda lines: self._result(
            lines, "重启服务", "relay 服务已重启完成，新的配置已生效。", "✔ 已重启"))

    def _do_restart(self):
        d = _STATE
        lines = []
        close_codex()
        ok, rlines = relay_restart()
        lines += rlines
        write_config(lines)
        write_keepalive(lines)
        lines.append("✔ 已重启")
        return lines

    def _stop(self):
        def _do_stop():
            lines = []
            stop_relay(lines)
            lines.append("已停止 relay（网关若在汇聚模式仍在运行）")
            return lines
        self._busy(_do_stop, lambda lines: self._result(
            lines, "停止服务", "relay 已停止；如处汇聚模式，本地网关仍会保持运行。", "✔"))

    def _status(self):
        """查看状态：打开图文并茂的状态面板，而不是只把日志打一遍。"""
        data = self._collect_status()
        self._log("已打开服务状态面板：" + data["headline"])
        self._status_dialog(data)

    def _collect_status(self):
        """采集当前运行态，返回结构化 dict，供状态面板渲染。"""
        d = _STATE
        agg = bool(d.get("agg")) or d.get("AGG") == "1"
        relay_ok = lsof_port(RLPORT)
        gw_ok = lsof_port(GWPORT) if agg else None
        auth = read_auth()
        cfg_model = read_config_model()
        model = cfg_model or (d.get("M") or "deepseek-v4-pro")
        m = next((x for x in MODELS if x["name"] == model), MODELS[0])
        key_var = m["key"]
        key_set = bool((auth.get(key_var) or "").strip())
        cfg_ok = os.path.isfile(CONFIG)
        if relay_ok and (gw_ok if agg else True) and cfg_ok:
            headline = "服务运行中"
            health = "ok" if key_set else "warn"
        elif relay_ok:
            headline = "relay 运行中，配置未就绪"
            health = "warn"
        else:
            headline = "服务当前未运行"
            health = "err"
        return dict(agg=agg, relay_ok=relay_ok, gw_ok=gw_ok, cfg_ok=cfg_ok,
                    model=model, m=m, key_var=key_var, key_set=key_set,
                    headline=headline, health=health)

    def _status_dialog(self, data):
        """状态面板：按“运行模式 / relay / 网关 / 配置 / 模型 / Key”逐项着色展示。"""
        agg = data["agg"]
        kind = data["health"]
        color = {"ok": "#1aab52", "warn": "#e67e22", "err": "#c0392b"}.get(kind, "#1668dc")

        win = tk.Toplevel(self.root)
        win.title("服务状态")
        win.overrideredirect(True)
        win.configure(bg="#ffffff")
        win.attributes("-topmost", True)
        win.transient(self.root)

        head = tk.Frame(win, bg=color)
        head.pack(fill="x")
        tk.Label(head, text="服务状态", bg=color, fg="white",
                 font=("PingFang SC", 14, "bold")).pack(side="left", padx=16, pady=12)
        def _close():
            try: win.grab_release()
            except Exception: pass
            win.destroy()
        tk.Button(head, text="✕", command=_close, relief="flat", bd=0,
                  bg=color, fg="white", font=("PingFang SC", 12),
                  activebackground=color, cursor="hand2").pack(side="right", padx=10)

        body = tk.Frame(win, bg="#ffffff"); body.pack(fill="both", expand=True, padx=18, pady=14)

        tk.Label(body, text=data["headline"], bg="#ffffff",
                 fg=color, font=("PingFang SC", 17, "bold"),
                 anchor="w").pack(fill="x", pady=(0, 4))
        tk.Label(body, text="各组件运行情况（lsof 实测）：", bg="#ffffff",
                 fg="#999", font=("PingFang SC", 10), anchor="w").pack(fill="x", pady=(0, 8))

        def row(parent, label, value, ok_state):
            """ok_state: True 绿 / False 红 / None 灰(不适用)"""
            fr = tk.Frame(parent, bg="#ffffff"); fr.pack(fill="x", pady=2)
            if ok_state is None:
                dot = "#c9c9c9"; val_fg = "#888"; mark = "—"
            elif ok_state:
                dot = "#1aab52"; val_fg = "#166833"; mark = "✔"
            else:
                dot = "#c0392b"; val_fg = "#b0301e"; mark = "✕"
            tk.Label(fr, text="●", bg="#ffffff", fg=dot,
                     font=("PingFang SC", 10)).pack(side="left")
            tk.Label(fr, text=label, bg="#ffffff", fg="#333",
                     width=15, anchor="w", font=("PingFang SC", 12)).pack(side="left")
            tk.Label(fr, text=mark, bg="#ffffff", fg=dot,
                     font=("PingFang SC", 11, "bold")).pack(side="left")
            tk.Label(fr, text=value, bg="#ffffff", fg=val_fg, anchor="w",
                     font=("PingFang SC", 12)).pack(side="left", padx=(4, 0))
            return fr

        row(body, "运行模式",
            "汇聚模式 · 7 厂商共用一个入口" if agg else "普通模式 · 单厂商直连",
            True if data["cfg_ok"] else None)
        row(body, "relay · %d" % RLPORT,
            "运行中（127.0.0.1:%d/v1）" % RLPORT if data["relay_ok"] else "未运行",
            data["relay_ok"])
        if agg:
            row(body, "网关 · %d" % GWPORT,
                "运行中" if data["gw_ok"] else "未运行",
                data["gw_ok"])
        else:
            row(body, "网关 · %d" % GWPORT, "普通模式不使用", None)
        row(body, "配置文件", "已生成（config.toml）" if data["cfg_ok"] else "尚未初始化", data["cfg_ok"])

        tk.Frame(body, bg="#eeeeee", height=1).pack(fill="x", pady=(10, 8))
        tk.Label(body, text="当前模型", bg="#ffffff", fg="#111",
                 font=("PingFang SC", 13, "bold"), anchor="w").pack(fill="x")
        tk.Label(body, text="%s · %s [%s]" % (data["m"]["provider"], data["m"]["name"], data["m"]["code"]),
                 bg="#ffffff", fg="#333", anchor="w", wraplength=480,
                 font=("PingFang SC", 12)).pack(fill="x", pady=(2, 6))
        kf = tk.Frame(body, bg="#ffffff"); kf.pack(fill="x")
        tk.Label(kf, text="●", bg="#ffffff",
                 fg="#1aab52" if data["key_set"] else "#c0392b",
                 font=("PingFang SC", 10)).pack(side="left")
        tk.Label(kf, text="API Key（%s）" % data["key_var"], bg="#ffffff", fg="#333",
                 width=15, anchor="w", font=("PingFang SC", 12)).pack(side="left")
        tk.Label(kf, text="✔ 已填写" if data["key_set"] else "✕ 缺失 —— 请到“管理 API Key”填写",
                 bg="#ffffff",
                 fg="#166833" if data["key_set"] else "#b0301e",
                 anchor="w", font=("PingFang SC", 12)).pack(side="left", padx=(4, 0))

        tip = ""
        if not data["relay_ok"]:
            tip = "relay 未运行，请点『应用并启动』。"
        elif data["cfg_ok"] and not data["key_set"]:
            tip = "当前模型缺少 %s，填好 Key 后点『应用并启动』。" % data["key_var"]
        elif agg and not data["gw_ok"]:
            tip = "汇聚网关未运行，请点『应用并启动』重建。"
        if tip:
            tk.Label(body, text=tip, bg="#fff8ec", fg="#a05a00", anchor="w",
                     wraplength=470, justify="left", padx=8, pady=6,
                     font=("PingFang SC", 11)).pack(fill="x", pady=(10, 4))

        brow = tk.Frame(body, bg="#ffffff"); brow.pack(anchor="e", pady=(10, 0))
        tk.Button(brow, text="知道了", command=_close, bg=color, fg="white",
                  relief="flat", padx=24, pady=5,
                  font=("PingFang SC", 12, "bold"), cursor="hand2",
                  activebackground=color).pack()
        win.bind("<Return>", lambda e: _close())
        win.bind("<Escape>", lambda e: _close())
        win.update_idletasks()
        w, h = 540, win.winfo_reqheight()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - w) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - h) // 2
        win.geometry("%dx%d+%d+%d" % (w, h, max(x, 0), max(y, 0)))
        try: win.grab_set()
        except Exception: pass
        win.focus_force()

    def _uninstall(self):
        if not self._confirm("恢复出厂设置",
                             "将终止 relay/网关、移除自动保活、清空 Key 与配置，\n并把历史会话迁回 OpenAI / gpt-5.6-luna。\n不会删除你的会话数据或 Codex。\n确认继续？"):
            self._log("已取消")
            return
        self._busy(lambda: (uninstall([]), ["✔ 已恢复出厂设置"])[1],
                   lambda lines: self._result(
                       lines, "恢复出厂设置", "已恢复出厂状态：服务停止、自动保活移除、Key 与配置已清空。", "✔ 已恢复出厂设置"))
    # ---------- API Key 管理对话框 ----------
    def _keys_dialog(self):
        auth = read_auth()
        win = tk.Toplevel(self.root)
        win.title("管理 API Key")
        win.geometry("620x600")
        win.configure(bg=_BG)
        win.transient(self.root)
        box = tk.Frame(win, bg=_BG); box.pack(fill="both", expand=True, padx=10, pady=8)
        tk.Label(box, text="逐家填写 API Key（留空＝保持不变）。普通与套餐 Key 相互独立。",
                 bg=_BG, fg="#666", font=("PingFang SC", 10)).pack(anchor="w", pady=(0,6))

        canvas = tk.Canvas(box, bg=_BG, highlightthickness=0)
        vsb = ttk.Scrollbar(box, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=_BG)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0,0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True); vsb.pack(side="right", fill="y")

        entries = {}   # keyvar -> Entry
        billing = {}   # vendor -> StringVar
        def row(parent, label_txt, url):
            fr = tk.LabelFrame(parent, text=label_txt, bg=_BG, font=("PingFang SC", 10, "bold"))
            fr.pack(fill="x", pady=3)
            e = tk.Entry(fr, show="*", width=60)
            e.pack(side="left", fill="x", expand=True, padx=6, pady=4)
            tk.Button(fr, text="官网", command=lambda u=url: self._open_browser(u),
                      relief="flat", padx=6).pack(side="right", padx=6)
            return fr, e
        for v in VENDOR_BASE:
            kv = KEYVAR[v]
            _, e = row(inner, "%s  ·  %s" % (v, kv), GUIDES.get(v,""))
            e.insert(0, auth.get(kv, ""))
            entries[kv] = e
            if v in KEYVAR_TP:
                kvt = KEYVAR_TP[v]
                _, e2 = row(inner, "%s 套餐/TokenPlan  ·  %s" % (v, kvt), GUIDES.get(v,""))
                e2.insert(0, auth.get(kvt, ""))
                entries[kvt] = e2
                # 计费偏好
                bf = tk.Frame(inner, bg=_BG); bf.pack(fill="x", padx=4)
                tk.Label(bf, text="  默认计费:", bg=_BG).pack(side="left")
                var = tk.StringVar(value="tp" if auth.get("BILLING_PREF_"+v)=="tp" else "regular")
                cbox = ttk.Combobox(bf, textvariable=var, state="readonly", width=16,
                                    values=["regular","tp"])
                cbox.pack(side="left", padx=4)
                tk.Label(bf, text="regular=按量 · tp=套餐", bg=_BG, fg="#999").pack(side="left")
                billing[v] = var

        def save():
            kv = {}
            for k, e in entries.items():
                val = e.get().strip()
                if val:
                    kv[k] = val
            if kv:
                write_auth(kv)
            for v, var in billing.items():
                write_auth({"BILLING_PREF_"+v: var.get()})
            win.destroy()
            self._log("API Key 已保存")
            n = sum(1 for k in entries if k in kv and kv[k])
            self._toast("已保存", "已保存 %d 家厂商的 API Key，可直接“应用并启动”。" % max(n, 0), "ok")
        tk.Button(box, text="保存全部", command=save, bg=_ACCENT, fg="white", relief="flat",
                  padx=16, font=("PingFang SC", 11, "bold")).pack(anchor="e", padx=4, pady=6)



def main():
    root = tk.Tk()
    try:
        if sys.platform == "darwin":
            try:
                from tkinter import font as tkfont
                # 提升 HiDPI
            except Exception:
                pass
    except Exception:
        pass
    App(root)
    root.mainloop()

if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        sys.exit(selfcheck())
    main()
