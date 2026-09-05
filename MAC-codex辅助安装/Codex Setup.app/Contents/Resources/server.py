#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
Codex 助手 —— 本地 HTTP 后端 + 网页 UI。

由原生 Swift 外壳 (Codex SetServer) 无终端启动：
    /usr/bin/python3 -E server.py
监听 127.0.0.1:<port>（port=0 由系统分配），stdout 打印一行 "READY <port>"，
Swift 读取后把 WKWebView 指向该地址。

所有真实逻辑复用 codex_setup_gui.py（与原 .command 一致的数据层），
仅剥离 tkinter GUI；本文件负责渲染 + 把按钮动作翻译成逻辑调用。
"""
import os, sys, json, time, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 让本文件与 codex_setup_gui.py 同目录可被导入
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
os.chdir(_HERE)

import codex_setup_gui as G            # 数据表 + 全部逻辑

_LINES = []       # 动作日志（全局），前端 append
_LOCK = threading.Lock()


def _now():
    return time.strftime("%H:%M:%S")


def _run(op, payload):
    """在锁内同步执行一个动作，返回 (ok, lines)。与 Tk 的 _do_* 语义一致。"""
    lines = []
    try:
        if op == "apply":
            _apply(lines)
        elif op == "restart":
            _restart(lines)
        elif op == "stop":
            lines.append("停止服务…")
            G.stop_relay([])
            if G._STATE["agg"]:
                G.pkillf("relay-gateway")
                lines.append("网关(汇聚)也已停止")
            lines.append("✔ 已停止")
        elif op == "uninstall":
            G.uninstall([])
            lines.append("✔ 已恢复出厂设置")
        elif op == "status":
            lines = G._status_text()
        elif op == "relay":
            ok, rl = G.start_relay()
            lines += rl
            if ok:
                lines.append("✔ relay 已启动")
        else:
            lines.append("未知操作: %s" % op)
        return True, lines
    except Exception as e:
        return False, lines + ["出错: %s" % e]


def _apply(lines):
    d = G._STATE
    m = G.MODELS[G.find_index_by_code(d.get("M_code", "D1"))]
    if not G.read_auth().get(m["key"]):
        lines.append("该模型需要 %s，先在「管理 Key」填写再应用" % m["key"])
        return
    G.close_codex()
    agg = d["agg"]
    if agg:
        lines.append("汇聚模式：启动网关 + relay + 全量模型目录…")
        ok, msg = G.start_gateway()
        lines.append(msg)
        if not ok:
            return
        os.environ["GUI_AGG"] = "1"
    else:
        G.pkillf("relay-gateway")
    ok, rl = G.start_relay()
    lines += rl
    if not ok:
        return
    G.write_config(lines)
    G.write_keepalive(lines)
    lines.append("✔ 全部就绪")


def _restart(lines):
    d = G._STATE
    G.close_codex()
    ok, rl = G.relay_restart()
    lines += rl
    if not ok:
        return
    G.write_config(lines)
    G.write_keepalive(lines)
    lines.append("✔ 已重启")


# ── JSON / 渲染 ──
def _model_view(m):
    base = G.base_of(m["provider"])
    return {"code": m["code"], "name": m["name"], "provider": m["provider"],
            "note": m["note"], "desc": G.DESC.get(m["name"], ""),
            "key": m["key"], "tp": m["provider"].endswith("-TP"),
            "guide": G.GUIDES.get(base, ""),
            "slug": m["name"],
            "ctx": G.GetCtxLabel(m["name"]),
            "ctx_opts": G.CtxOptionsFor(m["name"])}


def _init_payload():
    G.load_state()
    d = G._STATE
    auth = G.read_auth()
    idx = G.find_index_by_code(d.get("M_code", "D1"))
    idx = idx if idx >= 0 else 0
    cur = _model_view(G.MODELS[idx])
    vendors = []
    for v in G.VENDOR_BASE:
        ms = [_model_view(m) for m in G.MODELS if G.base_of(m["provider"]) == v]
        vendors.append({"name": v, "guide": G.GUIDES.get(v, ""), "models": ms})
    billing = {}
    for v in G.VENDOR_BASE:
        if v in G.KEYVAR_TP:
            billing[v] = auth.get("BILLING_PREF_" + v, "regular")
    # 每个 Key 槽（厂商基础 / 套餐）挂上使用它的模型清单，含每模型上下文档位，
    # 使「Key + 上下文窗口」能在同一弹窗里一起填、一起保存。
    keys = []
    for v in G.VENDOR_BASE:
        kv = G.KEYVAR[v]
        base_ms = [_model_view(m) for m in G.MODELS if m["key"] == kv]
        keys.append({"keyvar": kv, "vendor": v, "label": "%s · %s" % (v, kv),
                     "guide": G.GUIDES.get(v, ""), "tp": False,
                     "set": bool(auth.get(kv)), "bill": None, "models": base_ms})
        if v in G.KEYVAR_TP:
            kvt = G.KEYVAR_TP[v]
            tp_ms = [_model_view(m) for m in G.MODELS if m["key"] == kvt]
            keys.append({"keyvar": kvt, "vendor": v,
                         "label": "%s 套餐/TokenPlan · %s" % (v, kvt),
                         "guide": G.GUIDES.get(v, ""), "tp": True,
                         "set": bool(auth.get(kvt)), "bill": billing.get(v),
                         "models": tp_ms})
    return {"vendors": vendors, "cur": cur,
            "agg": bool(d["agg"]), "re": d.get("re", "high"),
            "account": auth.get("ACCOUNT_NAME", ""),
            "port": d.get("PORT", "4446"), "gwport": d.get("GWPORT", "4447"),
            "keys": keys, "billing": billing, "lines": _LINES[:]}


def _status_payload():
    """供顶部状态栏轮询的轻量状态（不写任何配置）。"""
    G.load_state()
    d = G._STATE
    idx = G.find_index_by_code(d.get("M_code", "D1"))
    idx = idx if idx >= 0 else 0
    m = G.MODELS[idx]
    agg = bool(d["agg"])
    relay = G.lsof_port(G.RLPORT)
    gateway = G.lsof_port(G.GWPORT) if agg else False
    return {"model": m["name"], "agg": agg,
            "relay": relay, "gateway": gateway,
            "port": G.RLPORT, "gwport": G.GWPORT}


def _cur_model_name():
    G.load_state()
    d = G._STATE
    idx = G.find_index_by_code(d.get("M_code", "D1"))
    if idx < 0:
        idx = 0
    return G.MODELS[idx]["name"]


def _status_panel():
    """「查看状态」弹窗的结构化数据（只读，不写任何配置）。
    返回面板需要的各项，前端据此上色。"""
    G.load_state()
    d = G._STATE
    auth = G.read_auth()
    idx = G.find_index_by_code(d.get("M_code", "D1"))
    if idx < 0:
        idx = 0
    m = G.MODELS[idx]
    agg = bool(d["agg"])
    relay = G.lsof_port(G.RLPORT)
    gateway = G.lsof_port(G.GWPORT) if agg else None
    cfg = os.path.isfile(G.CONFIG)
    cfg_model = G.read_config_model() if cfg else ""
    key_set = bool(auth.get(m["key"]))
    return {
        "ts": _now(),
        "mode": "汇聚模式（7 厂商一个端口）" if agg else "普通模式（单厂商直连）",
        "agg": agg,
        "relay": relay,
        "gateway": gateway,
        "cfg": cfg,
        "cfg_model": cfg_model,
        "model": m["name"],
        "code": m["code"],
        "provider": m["provider"],
        "key_set": key_set,
        "key_var": m["key"],
        "account": auth.get("ACCOUNT_NAME", "") or m["provider"],
        "port": G.RLPORT,
        "gwport": G.GWPORT,
    }


def _toast_for(op, ok, lines):
    """把一次按钮动作翻译成『一句话、看得懂的反馈』，而不是甩一整屏日志。
    返回 {kind,title,msg}；kind ∈ ok/err/warn/info。"""
    text = "\n".join(lines)
    has = lambda *ks: any(k in text for k in ks)

    if op == "apply":
        if has("该模型需要", "先在「管理 Key」", "还没填"):
            return {"kind": "warn", "title": "还需填写 API Key",
                    "msg": "当前模型需要对应的 API Key。点「管理 API Key」粘贴后，再点一次「应用并启动」。Key 只存本机，不会被上传。"}
        if has("relay 二进制缺失", "提取失败"):
            return {"kind": "err", "title": "缺少组件",
                    "msg": "relay 组件未就绪。请确认本机已完整安装过一遍，再重试。"}
        if has("✔ 全部就绪"):
            return {"kind": "ok", "title": "应用成功，服务已启动",
                    "msg": "配置已写入 Codex，自动保活已开启，现在就可以使用了。"}
        if has("启动失败", "没起来", "未响应", "出错"):
            return {"kind": "err", "title": "服务启动失败",
                    "msg": "relay 没有正常起来。请打开下方日志看具体原因，或稍后重试。"}
        if ok:
            return {"kind": "info", "title": "应用完成",
                    "msg": "已执行完成，详细过程见下方日志。"}
        return {"kind": "err", "title": "操作未完成",
                "msg": "执行时遇到错误，请查看下方日志后重试。"}

    if op == "restart":
        if has("✔ 已重启"):
            return {"kind": "ok", "title": "已重启完成",
                    "msg": "relay 服务已重启，新配置已生效。"}
        return {"kind": "err", "title": "重启未完成",
                "msg": "请查看下方日志了解原因后重试。"}

    if op == "stop":
        if has("✔ 已停止"):
            return {"kind": "ok", "title": "已停止",
                    "msg": "relay 服务已停止，自动保活已关闭。再次点「应用并启动」即可恢复。"}
        return {"kind": "err", "title": "停止未完成",
                "msg": "请查看下方日志了解原因后重试。"}

    if op == "relay":
        return {"kind": "ok" if ok else "err",
                "title": "relay 已启动" if ok else "relay 启动失败",
                "msg": "relay 已在本地端口正常监听。" if ok else "请打开下方日志查看原因。"}

    if op == "uninstall":
        if has("✔ 已恢复出厂设置"):
            return {"kind": "ok", "title": "已恢复出厂设置",
                    "msg": "服务已停止、自动保活已移除、API Key 与配置已清空。会话数据与 Codex 本身没有动。"}
        if has("已取消"):
            return {"kind": "info", "title": "已取消",
                    "msg": "没有做任何更改。"}
        return {"kind": "err", "title": "未完成",
                "msg": "请查看下方日志了解原因后重试。"}

    if op == "status":
        G.load_state()
        relay_on = G.lsof_port(G.RLPORT)
        agg = bool(G._STATE.get("agg"))
        gw_on = G.lsof_port(G.GWPORT) if agg else None
        parts = ["relay(%s)：%s" % (G.RLPORT, "运行中" if relay_on else "未启动")]
        if gw_on is not None:
            parts.append("网关(%s)：%s" % (G.GWPORT, "运行中" if gw_on else "未运行"))
        parts.append("模式：" + ("汇聚（7 厂商一端口）" if agg else "普通（单厂商直连）"))
        parts.append("当前模型：" + _cur_model_name())
        all_ok = relay_on and (not agg or gw_on)
        return {"kind": "ok" if all_ok else "warn",
                "title": "服务运行正常" if all_ok else "服务未全部就绪",
                "msg": " · ".join(parts)}

    if not ok:
        return {"kind": "err", "title": "操作未完成",
                "msg": "执行时遇到错误，请查看下方日志后重试。"}
    return {"kind": "ok", "title": "完成",
            "msg": "操作已执行，详情见下方日志。"}


PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Codex 助手</title>
<style>
  :root{--acc:#1668dc;--ok:#1aab52;--warn:#b06000;--bad:#c0392b;--ink:#1a1a1a;--mut:#777;--line:rgba(120,130,160,.22);--panel:rgba(255,255,255,.55);--glass-line:rgba(255,255,255,.65)}
  *{box-sizing:border-box}
  body{margin:0;font-family:-apple-system,"PingFang SC","Helvetica Neue",Arial,sans-serif;
       color:var(--ink);font-size:13px;
       background:
         radial-gradient(1100px 760px at 12% 6%, rgba(22,104,220,.16), transparent 60%),
         radial-gradient(900px 640px at 92% 10%, rgba(26,171,82,.13), transparent 55%),
         radial-gradient(860px 760px at 50% 100%, rgba(176,96,0,.11), transparent 60%),
         radial-gradient(700px 520px at 82% 72%, rgba(120,80,220,.09), transparent 55%),
         #eef1f8;
       background-attachment:fixed}
  .wrap{display:flex;flex-direction:column;height:100vh;padding:10px 12px;gap:8px}
  header{display:flex;align-items:baseline;gap:10px;padding:2px 2px 6px}
  header h1{font-size:17px;margin:0;font-weight:700}
  header .tag{color:var(--mut);font-size:11px}
  .cols{flex:1;display:flex;gap:10px;min-height:0}
  /* Apple 毛玻璃面板：半透明白 + backdrop blur */
  .glass{ -webkit-backdrop-filter:blur(22px) saturate(170%);backdrop-filter:blur(22px) saturate(170%);
          background:var(--panel);border:1px solid var(--glass-line);
          box-shadow:0 6px 22px rgba(24,30,60,.08),0 1px 2px rgba(24,30,60,.04)}
  .left{flex:1;min-width:0;display:flex;flex-direction:column;border-radius:14px;padding:8px;
        -webkit-backdrop-filter:blur(22px) saturate(170%);backdrop-filter:blur(22px) saturate(170%);
        background:var(--panel);border:1px solid var(--glass-line);
        box-shadow:0 6px 22px rgba(24,30,60,.08),0 1px 2px rgba(24,30,60,.04)}
  .right{width:400px;display:flex;flex-direction:column;gap:8px;overflow:auto}
  h2{font-size:12px;margin:2px 4px 6px;color:var(--acc);font-weight:700;letter-spacing:.3px}
  .modellist{flex:1;overflow:auto;border:1px solid rgba(255,255,255,.5);border-radius:10px;
             background:rgba(255,255,255,.18)}
  .grp-title{font-weight:700;color:var(--acc);padding:6px 8px 2px}
  .row{padding:5px 8px;cursor:pointer;border-radius:7px;margin:0 4px;display:flex;justify-content:space-between;gap:8px;outline:none}
  .row:hover{background:rgba(22,104,220,.10)}
  .row:focus-visible{background:rgba(22,104,220,.14);outline:2px solid var(--acc);outline-offset:-1px}
  .row.sel{background:rgba(22,104,220,.18)}
  .row .nm{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .row .note{color:var(--mut);font-size:11px;white-space:nowrap}
  .row .tp{background:#fff2d6;color:#8a5a00;border-radius:3px;font-size:10px;padding:0 4px}
  .card{border-radius:14px;padding:8px;
        -webkit-backdrop-filter:blur(22px) saturate(170%);backdrop-filter:blur(22px) saturate(170%);
        background:var(--panel);border:1px solid var(--glass-line);
        box-shadow:0 6px 22px rgba(24,30,60,.08),0 1px 2px rgba(24,30,60,.04)}
  .card h3{margin:0 0 6px;font-size:11px;color:var(--acc);font-weight:700}
  label{display:block;margin:6px 2px 2px;color:#444;font-size:12px}
  input[type=text],select{width:100%;padding:5px 7px;border:1px solid #ccc;border-radius:5px;font-size:12px}
  input[type=text]:focus,select:focus{outline:2px solid var(--acc);border-color:var(--acc)}
  .mode{display:flex;flex-direction:column;gap:2px}
  .mode label{margin:0}
  .mode input{margin-right:5px}
  .cur{background:rgba(240,247,255,.6);border:1px solid rgba(150,200,255,.5);border-radius:9px;padding:6px 8px;font-size:12px;line-height:1.5}
  .cur b{color:#0b4fb0}
  .desc{color:var(--mut);font-size:11px}
  .btnrow{display:flex;gap:6px;flex-wrap:wrap}
  button{border:none;border-radius:6px;padding:8px 10px;cursor:pointer;font-size:13px;font-weight:600;color:#fff}
  button:disabled{opacity:.55;cursor:not-allowed}
  .b-apply{background:var(--ok);flex:1}
  .b-acc{background:var(--acc)}
  .b-warn{background:var(--warn)}
  .b-gray{background:#555}
  .b-bad{background:var(--bad);width:100%}
  .b-dark{background:#333;width:100%}
  .logbox{height:150px;background:rgba(24,24,30,.80);color:#d8d8d8;border-radius:12px;overflow:auto;
          font-family:"SF Mono",Menlo,monospace;font-size:11.5px;padding:8px 10px;white-space:pre-wrap;word-break:break-all}
  .modal{position:fixed;inset:0;background:rgba(24,28,44,.32);display:none;align-items:center;justify-content:center;z-index:50;
         -webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px)}
  .modal.open{display:flex}
  .sheet{background:rgba(255,255,255,.78);border-radius:16px;width:640px;max-width:94vw;max-height:86vh;
         -webkit-backdrop-filter:blur(26px) saturate(170%);backdrop-filter:blur(26px) saturate(170%);
         border:1px solid rgba(255,255,255,.7);box-shadow:0 18px 50px rgba(20,24,45,.18);
         display:flex;flex-direction:column;overflow:hidden}
  .sheet h2{margin:0;padding:12px 14px;border-bottom:1px solid var(--line)}
  .keys{overflow:auto;padding:6px 14px}
  .krow{border:1px solid rgba(120,130,160,.16);border-radius:11px;padding:6px 8px;margin:6px 0;
        background:rgba(255,255,255,.34)}
  .khead{display:flex;justify-content:space-between;align-items:center;font-size:12px;font-weight:600}
  .khead .guide{color:var(--acc);font-size:11px;cursor:pointer;text-decoration:underline}
  .krow .wrap2{display:flex;gap:6px;margin-top:5px}
  .stat{font-size:11px;color:var(--ok)}
  .stat.no{color:var(--warn)}
  .bill{display:flex;align-items:center;gap:6px;margin-top:4px;font-size:12px}
  .bill select{width:auto}
  .kg-models{margin-top:6px;border-top:1px dashed rgba(120,130,160,.28);padding-top:5px}
  .kg-sub{font-size:11px;color:var(--mut);margin:0 2px 4px;font-weight:600}
  .kmrow{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:3px 2px;font-size:12px}
  .kmname{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .kmrow select{width:230px;flex:none}
  .kmrow .hint{color:var(--mut);font-size:11px;margin-left:auto;padding-right:4px}
  .foot{padding:10px 14px;border-top:1px solid var(--line);display:flex;justify-content:flex-end;gap:8px}
  .spin{display:inline-block;width:12px;height:12px;border:2px solid rgba(0,0,0,.2);
        border-top-color:#fff;border-radius:50%;animation:sp 1s linear infinite;vertical-align:-2px}
  @keyframes sp{to{transform:rotate(360deg)}}
  #busy{position:fixed;right:14px;bottom:12px;background:#111;color:#fff;padding:6px 10px;
        border-radius:6px;display:none;font-size:12px;z-index:60}
  /* —— 结果反馈弹窗（不是日志放大版） —— */
  #toast{position:fixed;left:50%;top:26px;transform:translate(-50%,-18px);
         z-index:120;display:none;min-width:330px;max-width:min(560px,92vw)}
  #toast.show{display:block;animation:td .22s ease-out forwards}
  @keyframes td{from{transform:translate(-50%,-18px);opacity:0}to{transform:translate(-50%,0);opacity:1}}
  .tcard{display:flex;gap:12px;align-items:flex-start;background:rgba(255,255,255,.88);border-radius:16px;
         box-shadow:0 12px 34px rgba(20,20,40,.22),0 2px 8px rgba(20,20,40,.10);
         border:1px solid #ececf2;overflow:hidden;
         -webkit-backdrop-filter:blur(20px) saturate(160%);backdrop-filter:blur(20px) saturate(160%)}
  .tbar{width:6px;align-self:stretch;flex:none}
  .tcard.ok .tbar{background:#1aab52}.tcard.ok .tic{color:#1aab52;background:#e5f6ec}
  .tcard.err .tbar{background:#d43b2f}.tcard.err .tic{color:#d43b2f;background:#fdecea}
  .tcard.warn .tbar{background:#b06000}.tcard.warn .tic{color:#b06000;background:#fff1d6}
  .tcard.info .tbar{background:#1668dc}.tcard.info .tic{color:#1668dc;background:#e8f0fe}
  .tic{width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;
       font-weight:800;flex:none;font-size:15px;margin-top:2px}
  .tbody{flex:1;padding:12px 12px 12px 0}
  .tt{font-size:14px;font-weight:700;color:#16161d;margin-bottom:3px;padding-right:22px}
  .tm{font-size:12.5px;line-height:1.55;color:#4a4a55}
  .tx{position:absolute;top:9px;right:12px;border:none;background:none;color:#9a9aa5;
      font-size:16px;cursor:pointer;line-height:1;padding:2px}
  .tx:hover{color:#333}
  .tcard{position:relative}
  .tb{color:#fff;border:none;border-radius:7px;padding:7px 14px;font-size:12.5px;
      font-weight:600;cursor:pointer;margin-top:10px}
  .tcard.ok .tb{background:#1aab52}.tcard.err .tb{background:#d43b2f}
  .tcard.warn .tb{background:#b06000}.tcard.info .tb{background:#1668dc}

  /* —— 查看状态彩色面板 —— */
  .st-head{position:relative;color:#fff;padding:16px 18px 14px;
           background:linear-gradient(135deg,#1668dc,#3b86e6);flex:none}
  .st-head h2{margin:0;font-size:16px;font-weight:800;letter-spacing:.3px}
  .st-sub{margin-top:5px;font-size:12px;opacity:.94;font-weight:500}
  .st-close{position:absolute;top:12px;right:16px;background:none;border:none;color:rgba(255,255,255,.9);
            font-size:22px;cursor:pointer;line-height:1;padding:2px}
  .st-close:hover{color:#fff}
  .st-body{padding:2px 18px 12px;overflow:auto;flex:1}
  .st-sum{display:flex;align-items:center;gap:10px;border:1px solid #ececf2;border-radius:12px;
          margin:12px 0 6px;padding:9px 12px;font-weight:800;font-size:13.5px;color:#222}
  .st-sum .ic{width:26px;height:26px;border-radius:50%;display:inline-flex;align-items:center;
              justify-content:center;font-weight:800;flex:none;font-size:14px}
  .st-row{display:flex;align-items:center;gap:10px;padding:8px 2px;border-bottom:1px solid #f0f0f4}
  .st-row:last-child{border-bottom:none}
  .st-dot{width:9px;height:9px;border-radius:50%;flex:none}
  .st-key{width:196px;flex:none;color:#5a5a66;font-size:12.5px}
  .st-val{flex:1;font-size:13px;font-weight:700;color:#20202a;min-width:0}
  .st-note{font-size:11px;color:#999;text-align:right;max-width:150px}
  .st-refresh{color:#fff;border:none;border-radius:7px;padding:7px 16px;font-size:12.5px;
              font-weight:600;cursor:pointer}
  .st-foot{padding:10px 18px;border-top:1px solid var(--line);display:flex;justify-content:flex-end;gap:8px}
</style>
</head>
<body>
<div id="toast"></div>
<div class="wrap">
  <header><h1>Codex 助手</h1><span class="tag">relay v0.5.8 · 原生桌面 · 不弹终端</span></header>

  <div class="cols">
    <div class="left">
      <h2>选择模型（设为当前后生效）</h2>
      <div class="modellist" id="mlist"></div>
    </div>

    <div class="right">
      <div class="card">
        <h3>模式</h3>
        <div class="mode">
          <label><input type="radio" name="mode" value="0" onchange="setMode(0)"> 普通模式（单厂商直连）</label>
          <label><input type="radio" name="mode" value="1" onchange="setMode(1)"> 汇聚模式（7 厂商一端口）</label>
        </div>
      </div>
      <div class="card">
        <h3>当前选择</h3>
        <div class="cur" id="cur"></div>
        <div class="desc" id="desc"></div>
        <div class="btnrow" style="margin-top:8px">
          <button class="b-acc" onclick="pickSel()">设为当前模型</button>
          <button class="b-gray" onclick="openGuide()">打开 Key 官网</button>
        </div>
      </div>
      <div class="card">
        <h3>账户显示名（Codex 界面可见）</h3>
        <input type="text" id="acct" placeholder="留空自动用厂商名">
      </div>
      <div class="card">
        <h3>推理强度</h3>
        <select id="re">
          <option value="none">none · 关闭思考</option>
          <option value="low">low · 轻量</option>
          <option value="medium">medium · 均衡</option>
          <option value="high" selected>high · 深入</option>
          <option value="xhigh">xhigh · 极深</option>
          <option value="max">max · 满血</option>
        </select>
      </div>
      <div class="card">
        <h3>操作</h3>
        <button class="b-dark" onclick="openKeys()">管理 Key 与上下文窗口</button>
        <div class="btnrow" style="margin-top:6px">
          <button class="b-apply" onclick="run('apply')">应用并启动</button>
        </div>
        <div class="btnrow" style="margin-top:6px">
          <button class="b-gray" onclick="openStatus()">查看状态</button>
        </div>
        <button class="b-bad" style="margin-top:6px" onclick="confirmUninstall()">恢复出厂设置</button>
      </div>
    </div>
  </div>

  <div style="display:flex;align-items:center;justify-content:space-between">
    <label style="margin:0">运行日志</label>
    <button class="b-gray" onclick="copyLog()" style="padding:3px 10px;font-size:11px">复制日志</button>
  </div>
  <div class="logbox" id="log"></div>
</div>

<div class="modal" id="keysModal"><div class="sheet">
  <h2>各厂商 Key 与各模型上下文窗口</h2>
  <div class="desc" style="padding:6px 16px 0;color:var(--mut)">
    每行「Key 槽」填所属厂商/套餐的 API Key；下方模型各自选上下文档位，一起保存生效。
  </div>
  <div class="keys" id="keysBody"></div>
  <div class="foot">
    <button class="b-gray" onclick="closeKeys()">取消</button>
    <button class="b-acc" onclick="saveKeys()">保存全部</button>
  </div>
</div></div>

<div class="modal" id="statusModal"><div class="sheet" style="width:560px">
  <div class="st-head" id="stHead">
    <h2>服务状态</h2>
    <div class="st-sub" id="stSub">正在检测…</div>
    <button class="st-close" onclick="closeStatus()" title="关闭">×</button>
  </div>
  <div class="st-body">
    <div class="st-sum" id="stSum"></div>
    <div id="stRows"></div>
  </div>
  <div class="st-foot">
    <button class="b-gray" onclick="closeStatus()">关闭</button>
    <button class="st-refresh" onclick="refreshStatusPanel()">↻ 刷新</button>
  </div>
</div></div>

<div id="busy"><span class="spin"></span> 处理中…</div>

<script>
let S={cur:null,agg:0,keys:[],billing:{},guide:"",vendors:[]};
let lastId=0, startId=0;

const $=id=>document.getElementById(id);

/* 结果反馈弹窗：给用户一句话总结，而不是甩日志 */
let toastTimer=null;
function toast(kind,title,msg){
  const host=$('toast');clearTimeout(toastTimer);
  const ic={ok:'✔',err:'✕',warn:'!',info:'i'}[kind]||'i';
  host.innerHTML='<div class="tcard '+kind+'"><div class="tbar"></div>'
    +'<div style="padding:12px 0 12px 14px"><div class="tic">'+ic+'</div></div>'
    +'<div class="tbody"><div class="tt"></div><div class="tm"></div>'
    +'<button class="tb">知道了</button></div>'
    +'<button class="tx" onclick="hideToast()">×</button></div>';
  host.querySelector('.tt').textContent=title||'';
  host.querySelector('.tm').textContent=msg||'';
  host.querySelector('.tb').onclick=()=>hideToast();
  host.classList.add('show');
  toastTimer=setTimeout(hideToast, kind==='err'?8000:4200);
}
function hideToast(){const h=$('toast');if(h)h.classList.remove('show');}

function log(t){
  lastId++;
  const line=(new Date().toTimeString().slice(0,8))+' '+t+'\n';
  $('log').textContent+=line;$('log').scrollTop=1e9;
}
function copyLog(){
  const t=$('log').textContent;
  if(navigator.clipboard&&navigator.clipboard.writeText){
    navigator.clipboard.writeText(t).then(()=>toast('ok','日志已复制','完整运行日志已复制到剪贴板。'));
  }else toast('err','复制失败','当前环境不支持剪贴板，请手动复制下方日志。');
}

async function api(path,body){let r=await fetch('/api/'+path,{method:body?'POST':'GET',
  headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});
  return r.json();}

function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function keyState(v){return v?'已设置':'未设置';}

function renderModels(){
  const box=$('mlist');box.innerHTML='';
  for(const v of S.vendors){
    const t=document.createElement('div');t.className='grp-title';t.textContent='▪ '+v.name;box.appendChild(t);
    for(const m of v.models){
      const r=document.createElement('div');r.className='row'+(S.cur&&S.cur.code===m.code?' sel':'');
      const nm=document.createElement('div');nm.className='nm';
      nm.innerHTML='['+esc(m.code)+'] '+esc(m.name)+(m.tp?' <span class="tp">TP</span>':'');
      const note=document.createElement('div');note.className='note';note.textContent=m.note;
      r.appendChild(nm);r.appendChild(note);
      r.tabIndex=0;r.setAttribute('role','option');r.dataset.code=m.code;
      r.onclick=()=>pick(m.code);
      r.onkeydown=(e)=>{
        if(e.key==='Enter'||e.key===' '){e.preventDefault();pick(m.code);}
        else if(e.key==='Escape'){e.preventDefault();document.activeElement&&document.activeElement.blur();}
      };
      box.appendChild(r);
    }
  }
}
function renderCur(){
  const c=S.cur;if(!c)return;
  $('cur').innerHTML='<b>'+esc(c.provider)+'</b> &nbsp;'+esc(c.name)+' &nbsp;['+esc(c.code)+'] &nbsp;'+esc(c.note);
  $('desc').textContent=c.desc;
  const radios=document.querySelectorAll('input[name=mode]');
  radios.forEach(x=>x.checked=(Number(x.value)===S.agg));
  $('re').value=S.re;$('acct').value=S.account;
}

async function pick(code){
  const d=await api('pick',{code});
  if(d.err){log(d.err);toast('err','选择失败',d.err);return;}
  S.cur=d.cur;S.agg=d.agg;renderModels();renderCur();
  if(!d.hasKey){log('该模型需要 '+d.cur.key+'：先去「管理 Key」填写');
    toast('warn','需要填写 API Key','模型 '+d.cur.name+' 需要 '+d.cur.key+'。请点「管理 API Key」粘贴后保存，再应用。');}
  else {log('已选择 '+d.cur.name);
    toast('ok','已设为当前模型',d.cur.provider+' · '+d.cur.name+' ['+d.cur.code+']，点「应用并启动」即可生效。');}
}
function pickSel(){if(S.cur)pick(S.cur.code);}

async function setMode(agg){
  S.agg=agg;const d=await api('mode',{agg:!!agg});
  if(d.err){log(d.err);toast('err','切换模式失败',d.err);}
  else log(agg?'已切换为汇聚模式':'已切换为普通模式');
}

async function run(op){
    setBusy(true);
  try{
    // 提交当前偏好
    await api('prefs',{re:$('re').value,account:$('acct').value.trim()});
    const r=await api('run',{op});
    (r.lines||[]).forEach(l=>log(l));
    if(r.toast)toast(r.toast.kind,r.toast.title,r.toast.msg);
    if(op==='status'||op==='uninstall'){S=await api('init');renderAll();}
  }catch(e){log('请求失败: '+e);toast('err','操作失败',String(e));}
  setBusy(false);
}

function setBusy(on){$('busy').style.display=on?'block':'none';}
function openExternal(url){if(url){window.location.href=url;}}
function openGuide(){
  if(S.cur&&S.cur.guide)openExternal(S.cur.guide);
  else toast('warn','暂无官网可打开','请先点选一家厂商的模型，再点「打开 Key 官网」。');
}

function confirmUninstall(){
  if(confirm('恢复出厂设置\n将终止 relay/网关、移除自动保活、清空 Key 与配置，\n并把历史会话迁回 OpenAI / gpt-5.6-luna。\n不会删除你的会话数据或 Codex。确认继续？')) run('uninstall');
  else {log('已取消');toast('info','已取消','没有做任何更改。');}
}

async function openKeys(){
  S=await api('init');
  const b=$('keysBody');b.innerHTML='';
  for(const k of S.keys){
    const row=document.createElement('div');row.className='krow';
    const head=document.createElement('div');head.className='khead';
    const lbl=document.createElement('span');lbl.textContent=k.label;
    const s=document.createElement('span');s.className='stat'+(k.set?'':' no');s.textContent=keyState(k.set);
    const guide=document.createElement('a');guide.className='guide';guide.textContent='打开官网';
    guide.onclick=()=>openExternal(k.guide||'');
    const hs=document.createElement('span');hs.append(s);hs.appendChild(guide);
    head.append(lbl);head.appendChild(hs);
    row.append(head);
    const wrap=document.createElement('div');wrap.className='wrap2';
    const inp=document.createElement('input');inp.type='text';inp.dataset.kv=k.keyvar;
    inp.placeholder=k.set?'留空保持不变':'粘贴 '+k.keyvar;
    const off=document.createElement('button');off.className='b-gray';off.textContent='清除';off.style.padding='2px 8px';
    off.onclick=()=>{inp.value='__CLEAR__';inp.placeholder='保存后将删除该 Key';}
    wrap.append(inp);wrap.appendChild(off);
    row.appendChild(wrap);
    if(k.tp&&k.bill){
      const bill=document.createElement('div');bill.className='bill';
      bill.appendChild(document.createTextNode('默认计费: '));
      const sel=document.createElement('select');sel.dataset.v=k.vendor;
      for(const opt of ['regular','tp']){const o=document.createElement('option');o.value=opt;o.text=opt==='regular'?'regular·按量':'tp·套餐';sel.appendChild(o);}
      sel.value=k.bill;
      bill.appendChild(sel);bill.appendChild(document.createTextNode('regular=按量 · tp=套餐'));
      row.appendChild(bill);
    }
    const models=(k.models||[]);
    if(models.length){
      const sub=document.createElement('div');sub.className='kg-models';
      const title=document.createElement('div');title.className='kg-sub';title.textContent='使用此 Key 的模型 — 上下文档位：';
      sub.appendChild(title);
      for(const m of models){
        const r=document.createElement('div');r.className='kmrow';
        const nm=document.createElement('span');nm.className='kmname';
        nm.innerHTML='['+esc(m.code)+'] '+esc(m.name)+(m.tp?' <span class="tp">TP</span>':'');
        const sl=document.createElement('select');sl.dataset.ctxslug=m.slug;
        const opts=(m.ctx_opts||[]);
        if(opts.length){
          sl.innerHTML=opts.map(o=>'<option value="'+esc(o)+'"'+(o===m.ctx?' selected':'')+'>'+esc(o)+'</option>').join('');
        }else{
          const o=document.createElement('option');o.value='';o.text='— 无配置 —';sl.appendChild(o);
        }
        r.append(nm);r.appendChild(sl);sub.appendChild(r);
      }
      row.appendChild(sub);
    }
    b.appendChild(row);
  }
  $('keysModal').classList.add('open');
}
function closeKeys(){$('keysModal').classList.remove('open');}
async function saveKeys(){
  const fields={},billing={},ctx={};
  document.querySelectorAll('input[data-kv]').forEach(i=>{const val=i.value.trim();if(val)fields[i.dataset.kv]=val;});
  document.querySelectorAll('select[data-v]').forEach(s=>billing[s.dataset.v]=s.value);
  document.querySelectorAll('select[data-ctxslug]').forEach(s=>{if(s.value)ctx[s.dataset.ctxslug]=s.value;});
  const d=await api('keys',{fields,billing,ctx});
  if(d.err){log(d.err);toast('err','保存失败',d.err);}
  else{const n=Object.keys(fields).length,cn=Object.keys(ctx).length;
    log('已保存：Key 与上下文窗口');
    toast('ok','已保存',(n||cn)?('已更新 '+n+' 项 Key、'+cn+' 个模型上下文档位，点「应用并启动」即可生效。'):'本次没有填写任何 Key 或档位。');}
  closeKeys();S=await api('init');renderAll();
}


/* —— 「查看状态」彩色面板 —— */
function statusDot(ok,na){return '<span class="st-dot" style="background:'+(na?'#c9c9cf':ok?'#1aab52':'#d43b2f')+'"></span>';}
function statusRow(dotHtml,key,val,note){
  return '<div class="st-row">'+dotHtml
    +'<div class="st-key">'+esc(key)+'</div>'
    +'<div class="st-val">'+esc(val)+'</div>'
    +'<div class="st-note">'+esc(note||'')+'</div></div>';
}
async function refreshStatusPanel(){
  const head=$('stHead'),sub=$('stSub'),sum=$('stSum'),rows=$('stRows');
  sub.textContent='正在检测…';
  const d=await api('status_panel');
  if(!d||d.err){rows.innerHTML='';sum.innerHTML='';
    sum.innerHTML='<div class="ic" style="background:#d43b2f;color:#fff">✕</div><div>无法读取状态'+(d&&d.err?'：'+esc(d.err):'')+'</div>';
    head.style.background='linear-gradient(135deg,#c0392b,#e0552f)';return;}
  const agg=d.agg, relayOk=!!d.relay,
        gwOk=(!agg||!!d.gateway),
        cfgOk=!!d.cfg, keyOk=!!d.key_set;
  const fatal=!relayOk||(agg&&!gwOk);
  const allOk=relayOk&&gwOk&&cfgOk&&keyOk;
  head.style.background= allOk?'linear-gradient(135deg,#1aab52,#4cc46f)'
     :(fatal?'linear-gradient(135deg,#c0392b,#e0552f)':'linear-gradient(135deg,#b06000,#d98a2b)');
  sub.textContent=d.mode+'　·　检测于 '+d.ts;
  const icBg=allOk?'#1aab52':(fatal?'#d43b2f':'#b06000');
  const icCh=allOk?'✔':(fatal?'✕':'!');
  sum.innerHTML='<div class="ic" style="background:'+icBg+';color:#fff">'+icCh+'</div>'
    +'<div>'+(allOk?'服务运行正常':(fatal?'服务未运行':'部分未就绪，请留意下方红/橙项'))+'</div>';
  let html='';
  html+=statusRow(statusDot(relayOk),'relay 服务',relayOk?'运行中':'未启动','端口 '+d.port);
  if(agg) html+=statusRow(statusDot(gwOk),'聚合网关',gwOk?'运行中':'未运行','端口 '+d.gwport);
  else    html+=statusRow(statusDot(true,true),'聚合网关','普通模式未启用','单厂商直连');
  html+=statusRow(statusDot(cfgOk),'Codex 配置',cfgOk?'已写入':'尚未写入',cfgOk?('当前 '+d.cfg_model):'点「应用并启动」生成');
  html+=statusRow(statusDot(true),'运行模式',d.mode,'');
  html+=statusRow(statusDot(true),'当前模型',d.provider+' · '+d.model,'['+d.code+']');
  html+=statusRow(statusDot(keyOk),'API Key（'+d.key_var+'）',keyOk?'已设置':'未设置',keyOk?'':'点「管理 Key」填写');
  html+=statusRow(statusDot(true),'账号','',d.account||'');
  rows.innerHTML=html;
}
async function openStatus(){
  $('statusModal').classList.add('open');
  log('已打开服务状态面板');
  await refreshStatusPanel();
}
function closeStatus(){$('statusModal').classList.remove('open');}

/* 键盘增强：Esc 关闭任何弹层，Escape 也可在行内取消聚焦 */
window.addEventListener('keydown',(e)=>{
  if(e.key!=='Escape')return;
  ['statusModal','keysModal'].forEach(id=>{const el=$(id);if(el&&el.classList.contains('open')){el.classList.remove('open');}});
  const t=$('toast');if(t&&t.style.display!=='none')hideToast();
});

async function renderAll(){S=await api('init');renderModels();renderCur();if(!S.lines.length)log('就绪。选模型/模式 → 填 Key → 点「应用并启动」。');}

window.addEventListener('load',async()=>{renderAll();});
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json")

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._send(200, PAGE, "text/html")
            return
        if path == "/api/init":
            try:
                self._json(_init_payload())
            except Exception as e:
                self._json({"err": str(e)}, 500)
            return
        if path == "/api/status":
            try:
                self._json(_status_payload())
            except Exception as e:
                self._json({"err": str(e)}, 500)
            return
        if path == "/api/status_panel":
            try:
                self._json(_status_panel())
            except Exception as e:
                self._json({"err": str(e)}, 500)
            return
        self._json({"err": "not found"}, 404)

    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            n = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(n) or b"{}") if n else {}
        except Exception:
            payload = {}
        try:
            with _LOCK:
                if path == "/api/pick":
                    code = payload.get("code")
                    ok = G.set_model_by_code(code)
                    if ok:
                        G.save_state()
                        idx = G.find_index_by_code(code)
                    else:
                        idx = G.find_index_by_code(G._STATE.get("M_code", "D1"))
                        if idx < 0:
                            idx = 0
                    m = _model_view(G.MODELS[idx])
                    has = bool(G.read_auth().get(m["key"]))
                    self._json({"cur": m, "agg": bool(G._STATE["agg"]),
                                "hasKey": has, "err": None if ok else "未知模型码"})
                elif path == "/api/mode":
                    G.set_mode(bool(payload.get("agg")))
                    G.save_state()
                    self._json({"agg": bool(payload.get("agg"))})
                elif path == "/api/prefs":
                    re_ = payload.get("re")
                    acc = str(payload.get("account", "")).strip()
                    if re_ in ("none", "low", "medium", "high", "xhigh", "max"):
                        G._STATE["re"] = re_; G._STATE["RE"] = re_
                    if acc:
                        G.write_auth({"ACCOUNT_NAME": acc})
                    ctx = payload.get("ctx")
                    ctx_slug = str(payload.get("ctx_slug") or "").strip()
                    if ctx_slug and ctx in G.CTX_OPTS:
                        G.SetCtxLabel(ctx_slug, ctx)
                    G.save_state()
                    self._json({"ok": True})
                elif path == "/api/keys":
                    fields = payload.get("fields") or {}
                    billing = payload.get("billing") or {}
                    ctx_map = payload.get("ctx") or {}
                    kv = {}
                    for k, v in fields.items():
                        if v == "__CLEAR__":
                            a = G.read_auth()
                            if k in a:
                                del a[k]
                                try:
                                    with open(G.AUTH, "w", encoding="utf-8") as f:
                                        json.dump(a, f, ensure_ascii=False, indent=2)
                                except Exception:
                                    pass
                        elif v:
                            kv[k] = v
                    if kv:
                        G.write_auth(kv)
                    for v, pref in billing.items():
                        if pref in ("regular", "tp"):
                            G.write_auth({"BILLING_PREF_" + v: pref})
                    # 上下文档位：按模型 slug 一起保存，只接受该模型可选档位
                    if isinstance(ctx_map, dict):
                        for slug, label in ctx_map.items():
                            slug = str(slug).strip()
                            if not slug:
                                continue
                            opts = G.CtxOptionsFor(slug)
                            if label in opts:
                                G.SetCtxLabel(slug, label)
                    self._json({"ok": True})
                elif path == "/api/run":
                    op = payload.get("op")
                    ok, lines = _run(op, payload)
                    _LINES.extend(lines)
                    self._json({"ok": ok, "lines": lines,
                                "toast": _toast_for(op, ok, lines)})
                else:
                    self._json({"err": "not found"}, 404)
        except Exception as e:
            self._json({"err": str(e)}, 500)


def main():
    G._ctx_load()      # 加载每模型上下文档位（_ctxov.json），供 _model_view / pick 使用
    # port=0 → 系统分配；stdout 输出 READY <port> 供 Swift 读取
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    sys.stdout.write("READY %d\n" % port)
    sys.stdout.flush()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
