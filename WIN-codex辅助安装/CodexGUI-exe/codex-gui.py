# -*- coding: utf-8 -*-
# ============================================================
# Codex 助手（Windows 图形版）— 纯 Python + Tkinter
# 零第三方依赖：只用 Python 标准库 + tkinter。
# 与 Mac 原生版 / PowerShell 版功能对齐：选模型→填Key→开聊，支持汇聚模式。
# 运行：python codex-gui.py   （或用 启动Codex图形助手.bat）
# ============================================================
import os, sys, json, time, socket, subprocess, threading, ctypes, sqlite3, glob, webbrowser, queue
from datetime import datetime

# winreg 仅存在于 Windows；非 Windows（如本机仅作开发/编译校验）时置空，避免导入即崩。
try:
    import winreg
except Exception:
    winreg = None

# ---------- tkinter（本机缺 tk 时给出友好提示）----------
try:
    import tkinter as tk
    from tkinter import ttk, messagebox, simpledialog, font
    HAVE_TK = True
except Exception as _e:
    HAVE_TK = False
    _TK_ERR = _e

# ---------- 常量 ----------
C      = os.path.join(os.environ.get('USERPROFILE', os.path.expanduser('~')), '.codex')
CFG    = os.path.join(C, 'config.toml')
AUTH   = os.path.join(C, 'auth.json')
GW_CFG = os.path.join(C, 'gateway-config.json')
CATALOG= os.path.join(C, 'codex-relay-models.json')
GW_BIN = os.path.join(C, 'relay-gateway.exe')
RL_BIN = os.path.join(C, 'codex-relay.exe')
HIST   = os.path.join(C, 'codex-relay-history')
RL_LOG = os.path.join(os.environ.get('TEMP', C), 'codex-relay.log')
GW_LOG = os.path.join(os.environ.get('TEMP', C), 'relay-gateway.log')
RL_ERR = RL_LOG + '.err'   # _start_hidden 会把 stderr 写到 logfile+'.err'
RLPORT = 4446
GWPORT = 4447
# resources 目录：源码运行时位于脚本旁；用 PyInstaller 打成单文件 exe 时，
# --add-data 打包的 resources 会被释放到 sys._MEIPASS 下，需据此定位。
if getattr(sys, 'frozen', False):
    ResDir = os.path.join(getattr(sys, '_MEIPASS', os.path.dirname(sys.executable)), 'resources')
else:
    ResDir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources')

# ---------- 模型库（与 Mac / 原版完全一致，共 21 个）----------
CODES    = ['D1','D2','D3','Q1','Q2','K1','K2','G1','G2','G3','G4','M1','M2','M3','M4','X1','X2','X3','X4','T1','T2']
NAMES    = ['deepseek-v4-pro','deepseek-v4-flash','deepseek-v4-flash-vision-exp','qwen3.8-max','qwen3.7-max','kimi-k3','kimi-k2.7-code','glm-5.3','glm-5.3','glm-5.3-flash','glm-5.3-flash','MiniMax-M3','MiniMax-M2.7','MiniMax-M3','MiniMax-M2.7','mimo-v2.5-pro','mimo-v2.5','mimo-v2.5-pro','mimo-v2.5','hy3','hy4-preview']
PROVIDERS = ['DeepSeek','DeepSeek','DeepSeek','Qwen','Qwen','Kimi','Kimi','GLM-TP','GLM','GLM-TP','GLM','MiniMax','MiniMax','MiniMax-TP','MiniMax-TP','Xiaomi','Xiaomi','Xiaomi-TP','Xiaomi-TP','Tencent','Tencent']
URLS     = ['https://api.deepseek.com/v1','https://api.deepseek.com/v1','https://api.deepseek.com/v1','https://dashscope.aliyuncs.com/compatible-mode/v1','https://dashscope.aliyuncs.com/compatible-mode/v1','https://api.moonshot.cn/v1','https://api.moonshot.cn/v1','https://open.bigmodel.cn/api/coding/paas/v4','https://open.bigmodel.cn/api/paas/v4','https://open.bigmodel.cn/api/coding/paas/v4','https://open.bigmodel.cn/api/paas/v4','https://api.minimaxi.com/v1','https://api.minimaxi.com/v1','https://api.minimaxi.com/v1','https://api.minimaxi.com/v1','https://api.xiaomimimo.com/v1','https://api.xiaomimimo.com/v1','https://token-plan-cn.xiaomimimo.com/v1','https://token-plan-cn.xiaomimimo.com/v1','https://api.lkeap.cloud.tencent.com/plan/v3','https://api.lkeap.cloud.tencent.com/plan/v3']
KEYS     = ['DEEPSEEK_API_KEY','DEEPSEEK_API_KEY','DEEPSEEK_API_KEY','DASHSCOPE_API_KEY','DASHSCOPE_API_KEY','MOONSHOT_API_KEY','MOONSHOT_API_KEY','GLM_TOKENPLAN_API_KEY','ZHIPU_API_KEY','GLM_TOKENPLAN_API_KEY','ZHIPU_API_KEY','MINIMAX_API_KEY','MINIMAX_API_KEY','MINIMAX_TOKENPLAN_API_KEY','MINIMAX_TOKENPLAN_API_KEY','XIAOMI_API_KEY','XIAOMI_API_KEY','XIAOMI_TOKENPLAN_API_KEY','XIAOMI_TOKENPLAN_API_KEY','TENCENT_API_KEY','TENCENT_API_KEY']
NOTES    = ['旗舰','次旗舰','视觉理解','旗舰','次旗舰','旗舰','代码专精','旗舰·套餐','旗舰','多模态·套餐','多模态·标准','旗舰','次旗舰','旗舰·TP','次旗舰·TP','旗舰','次旗舰','旗舰·TP','次旗舰·TP','旗舰','预览版']
VENDOR_BASE = ['DeepSeek','Qwen','Kimi','GLM','MiniMax','Xiaomi','Tencent']
KEYVAR = {'DeepSeek':'DEEPSEEK_API_KEY','Qwen':'DASHSCOPE_API_KEY','Kimi':'MOONSHOT_API_KEY','GLM':'ZHIPU_API_KEY','MiniMax':'MINIMAX_API_KEY','Xiaomi':'XIAOMI_API_KEY','Tencent':'TENCENT_API_KEY'}
KEYVAR_TP = {'GLM':'GLM_TOKENPLAN_API_KEY','MiniMax':'MINIMAX_TOKENPLAN_API_KEY','Xiaomi':'XIAOMI_TOKENPLAN_API_KEY'}
GUIDE = {
 'DeepSeek':'https://platform.deepseek.com/api_keys',
 'Qwen':'https://bailian.console.aliyun.com/',
 'Kimi':'https://platform.moonshot.cn/console/api-keys',
 'GLM':'https://bigmodel.cn/apikey/platform',
 'MiniMax':'https://platform.minimaxi.com/user-center/basic-information/interface-key',
 'Xiaomi':'https://platform.xiaomimimo.com/',
 'Tencent':'https://console.cloud.tencent.com/tokenhub/tokenplan?regionId=1',
}
DESC = {
 'deepseek-v4-pro':'DeepSeek 最新旗舰，复杂任务强',
 'deepseek-v4-flash':'DeepSeek 次旗舰，轻量快速省 token',
 'deepseek-v4-flash-vision-exp':'DeepSeek 视觉理解模型，支持图片输入（实验版）',
 'qwen3.8-max':'通义最新旗舰，1M 上下文',
 'qwen3.7-max':'通义次旗舰，综合均衡',
 'kimi-k3':'Kimi 最新旗舰，2.8T 参数 1M 上下文',
 'kimi-k2.7-code':'Kimi 代码专精，次旗舰',
 'glm-5.3':'智谱最新旗舰，1M 上下文（标准/套餐视所选）',
 'glm-5.3-flash':'智谱多模态轻量，1M 上下文、支持图片',
 'MiniMax-M3':'MiniMax 最新旗舰 M3，1M 上下文',
 'MiniMax-M2.7':'MiniMax 次旗舰 M2.7',
 'mimo-v2.5-pro':'小米最新旗舰 MiMo-V2.5-Pro，1M 上下文',
 'mimo-v2.5':'小米旗舰 MiMo-V2.5，1M 上下文',
 'hy3':'腾讯混元 Hy3 旗舰（Token Plan）',
 'hy4-preview':'腾讯混元 Hy4 预览版，与 hy3 同一 Token Plan',
}

# ---- 上下文窗口档位（CW / MCW）----
# CW=context_window（决定何时压缩）；MCW=max_context_window（会话硬顶）。
# 铁律：MCW 切勿超过上游模型真实窗口，否则长会话触发 context 超限 / reasoning_content 类报错。
CTX_AUTO  = '自动（按官方规格）'
CTX_SMALL = '128K · 256K'
CTX_BIG   = '256K · 1M'
CTX_BIG2  = '512K · 1M'
CTX_OPTS  = [CTX_AUTO, CTX_SMALL, CTX_BIG, CTX_BIG2]
# 每模型官方真实窗口：slug -> (CW, MCW)；「自动」档即按此表取值。key 用去 -TP 后的模型名。
SPEC_CTX = {
 'deepseek-v4-pro':(262144,1048576),
 'deepseek-v4-flash':(262144,1048576),
 'deepseek-v4-flash-vision-exp':(262144,1048576),
 'qwen3.8-max':(262144,1048576),
 'qwen3.7-max':(262144,1048576),
 'kimi-k3':(262144,1048576),
 'kimi-k2.7-code':(131072,262144),      # 官方仅 128K/256K，勿标 1M
 'glm-5.3':(262144,1048576),
 'glm-5.3-flash':(131072,262144),       # 轻量保守 128K/256K
 'MiniMax-M3':(262144,1048576),
 'MiniMax-M2.7':(131072,209920),        # 官方 ~205K，勿标 1M
 'mimo-v2.5-pro':(262144,1048576),
 'mimo-v2.5':(262144,1048576),
 'hy3':(131072,262144),                 # 官方仅 128K/256K，勿标 1M
 'hy4-preview':(262144,1048576),
}

# ============================================================
#  会话状态
# ============================================================
class State:
    M='deepseek-v4-pro'; P='DeepSeek'; U=URLS[0]; K=KEYS[0]; M_code='D1'
    RE='high'; SRS='true'; CW='262144'; MCW='1048576'; AGG='0'; PORT='4446'; Account=''
    CTXOV = {}      # slug -> 上下文档位；留空/缺省=自动按官方规格
StateFile = os.path.join(C, 'gui-state.json')

def BaseOf(p):
    if p.endswith('-TP'): return p[:-3]
    return p

def IdxByCode(code):
    if code in CODES: return CODES.index(code)
    return 0

def SetModelByCode(code):
    i = IdxByCode(code)
    State.M=NAMES[i]; State.P=PROVIDERS[i]; State.U=URLS[i]; State.K=KEYS[i]; State.M_code=code

def _ctx_ov():
    d = State.CTXOV
    return d if isinstance(d, dict) else {}

def GetCtxLabel(name):
    return _ctx_ov().get(BaseOf(name), CTX_AUTO)

def SetCtxLabel(name, label):
    d = _ctx_ov(); d[BaseOf(name)] = label; State.CTXOV = d

def CtxFor(slug):
    """返回某模型实际 (CW, MCW)：手动档优先，否则自动按官方规格表。"""
    label = _ctx_ov().get(BaseOf(slug), CTX_AUTO)
    if label == CTX_SMALL: return (131072, 262144)
    if label == CTX_BIG:   return (262144, 1048576)
    if label == CTX_BIG2:  return (524288, 1048576)
    return SPEC_CTX.get(BaseOf(slug), (262144, 1048576))

def CtxOptionsFor(slug):
    """某模型可选的上下文档位：官方最大窗口不足 1M 的，不开放 1M 档，避免虚高触发 context 超限。"""
    _cw,_mctx = SPEC_CTX.get(BaseOf(slug), (262144, 1048576))
    opts = [CTX_AUTO, CTX_SMALL]
    if _mctx >= 1048576:
        opts += [CTX_BIG, CTX_BIG2]
    return opts

def CurModelIdx(): return IdxByCode(State.M_code)
def CurModelUrl(): return URLS[CurModelIdx()]
def CurKeySlot():  return KEYS[CurModelIdx()]
def IsAgg():       return State.AGG == '1'

def _json_no_bom(path, obj):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def _read_json(path, default=None):
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except Exception:
        return default

def SaveState():
    try:
        _json_no_bom(StateFile, {'M':State.M,'P':State.P,'U':State.U,'K':State.K,'M_code':State.M_code,
            'RE':State.RE,'SRS':State.SRS,'CW':State.CW,'MCW':State.MCW,'AGG':State.AGG,
            'PORT':State.PORT,'Account':State.Account,'CTXOV':_ctx_ov()})
    except Exception: pass

def LoadState():
    try:
        d = _read_json(StateFile)
        if isinstance(d, dict):
            for k in ('M','P','U','K','M_code','RE','SRS','CW','MCW','AGG','PORT','Account'):
                if k in d and d[k] is not None: setattr(State, k, str(d[k]))
            ov = d.get('CTXOV')
            if isinstance(ov, dict):
                State.CTXOV = {str(a):str(b) for a,b in ov.items()}
    except Exception: pass
    # 保证三件套一致
    i = IdxByCode(State.M_code)
    State.M=NAMES[i]; State.P=PROVIDERS[i]; State.U=URLS[i]; State.K=KEYS[i]

# ---------- auth.json ----------
def ReadAuthJson(): return _read_json(AUTH, None)
def WriteAuthJson(obj): _json_no_bom(AUTH, obj)
def ReadAuthVal(name):
    d = ReadAuthJson()
    if isinstance(d, dict) and d.get(name) is not None: return str(d[name])
    return ''
def SetAuthVal(name, val):
    d = ReadAuthJson()
    if not isinstance(d, dict): d = {}
    d[name] = val
    WriteAuthJson(d)

# ---------- 用户环境变量（注册表 + 广播）----------
def _broadcast_env():
    try:
        HWND_BROADCAST=0xFFFF; WM_SETTINGCHANGE=0x001A; SMTO_ABORTIFHUNG=0x0002
        res=ctypes.c_uint(); p=ctypes.c_wchar_p('Environment')
        ctypes.windll.user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, p, SMTO_ABORTIFHUNG, 5000, ctypes.byref(res))
    except Exception: pass

def SetUserEnv(name, val):
    if winreg is None: return
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment', 0, winreg.KEY_SET_VALUE)
        try:
            if val: winreg.SetValueEx(key, name, 0, winreg.REG_SZ, val)
            else:
                try: winreg.DeleteValue(key, name)
                except FileNotFoundError: pass
        finally:
            winreg.CloseKey(key)
        _broadcast_env()
    except Exception: pass

def DelUserEnv(name): SetUserEnv(name, '')

# ---------- 进程 / 端口 ----------
def _run(cmd):
    try:
        si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW; si.wShowWindow=0
        subprocess.run(cmd, startupinfo=si, capture_output=True, shell=False)
    except Exception: pass

def KillProc(name):
    try:
        si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW; si.wShowWindow=0
        subprocess.run(['taskkill','/F','/IM',name], startupinfo=si, capture_output=True)
    except Exception: pass

def _proc_alive(name):
    try:
        si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW; si.wShowWindow=0
        out = subprocess.run(['tasklist','/FI','IMAGENAME eq '+name],
                             capture_output=True, startupinfo=si)
        txt = out.stdout.decode('utf-8','replace')
        return name.lower() in txt.lower() and '没有运行' not in txt
    except Exception:
        return True

def KillProcWait(name, timeout=4.0):
    # 结束旧进程并等待其真正退出，以便释放 .exe 文件占用（否则覆盖会失败）
    KillProc(name)
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not _proc_alive(name): return
        time.sleep(0.25)

def _port_pids(port):
    pids=set()
    try:
        si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW; si.wShowWindow=0
        out = subprocess.run(['netstat','-ano'], capture_output=True, startupinfo=si).stdout.decode('utf-8','replace').splitlines()
        for line in out:
            parts=line.split()
            if len(parts)>=5:
                local=parts[1]
                if local.endswith(':%d'%port) and parts[3]=='LISTENING':
                    try: pids.add(int(parts[4]))
                    except: pass
    except Exception: pass
    return pids

def KillPortProc(port):
    for pid in _port_pids(port):
        try:
            si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW; si.wShowWindow=0
            subprocess.run(['taskkill','/F','/PID',str(pid)], startupinfo=si, capture_output=True)
        except Exception: pass

def TestPort(port):
    s=socket.socket(socket.AF_INET,socket.SOCK_STREAM); s.settimeout(0.3)
    try:
        s.connect(('127.0.0.1',port)); return True
    except Exception:
        return False
    finally:
        s.close()

def FindRelayPort():
    for p in (4446,4447,4448):
        if not TestPort(p): return p
    return 4446

def EnsureBin(name):
    dst = os.path.join(C, name); src = os.path.join(ResDir, name)
    if os.path.exists(src):
        want = os.path.getsize(src)
        if os.path.exists(dst) and os.path.getsize(dst) == want and want > 1048576:
            return dst
        # 部署区(~/.codex)里是旧版(大小不一致)：先用自带版本覆盖。
        # 若旧进程正占用 .exe，先结束并等待退出，再重试复制。
        os.makedirs(C, exist_ok=True)
        import shutil
        for _ in range(8):
            try:
                shutil.copyfile(src, dst)
                return dst
            except Exception:
                KillProcWait(name)
                time.sleep(0.4)
        # 覆盖最终失败：退回已存在的可用文件
        if os.path.exists(dst) and os.path.getsize(dst) > 1048576: return dst
        return None
    # 无自带文件时退回到部署区已有文件
    if os.path.exists(dst) and os.path.getsize(dst) > 1048576: return dst
    return None

# ---------- 弹窗 / 日志（线程安全，交由主线程执行）----------
_POP_QUEUE=[]
def PopupInfo(msg, title='Codex 助手'):
    _POP_QUEUE.append(('info',title,msg))
def PopupWarn(msg, title='Codex 助手'):
    _POP_QUEUE.append(('warn',title,msg))
def ConfirmAsk(msg, title='请确认'):
    return messagebox.askyesno(title, msg)   # 须在主线程

# ---------- 汇聚网关 ----------
def GenGatewayConfig():
    auth = ReadAuthJson()
    billing={}
    if isinstance(auth, dict):
        for v in VENDOR_BASE:
            bv = auth.get('BILLING_PREF_'+v)
            if bv: billing[v]=str(bv)
    # 同名模型归并（如 glm-5.3 同时有 GLM-TP/GLM）
    cands={}
    for i,n in enumerate(NAMES):
        cands.setdefault(n,[]).append(PROVIDERS[i])
    def pick_prov(ps):
        if len(ps)==1: return ps[0]
        b0=BaseOf(ps[0])
        want_tp = (b0 in billing and billing[b0]=='tp')
        sel=[p for p in ps if p.endswith('-TP')==want_tp]
        return sel[0] if sel else ps[0]
    providers={}; models={}
    for i,n in enumerate(NAMES):
        p=PROVIDERS[i]; u=URLS[i]; k=KEYS[i]
        chosen=pick_prov(cands[n])
        if p!=chosen: continue
        if p not in providers: providers[p]={'base_url':u,'api_key_env':k}
        models[n]=p
    cfg={'port':int(GWPORT),'providers':providers,'models':models}
    _json_no_bom(GW_CFG, cfg)
    return '网关路由：%d 个模型 / %d 个服务商'%(len(models),len(providers))

def StartGateway():
    KillProcWait('relay-gateway.exe')
    gw = EnsureBin('relay-gateway.exe')
    if not gw: return False,'找不到网关二进制（resources\\relay-gateway.exe 缺失）'
    summary = GenGatewayConfig()
    _start_hidden([gw, GW_CFG], GW_LOG)
    for _ in range(12):
        if TestPort(GWPORT): return True,'网关已启动 127.0.0.1:%d\n%s'%(GWPORT,summary)
        time.sleep(0.5)
    return False,'网关启动失败，看 \n'+GW_LOG

def StopGateway(): KillProc('relay-gateway.exe')

def _auth_env():
    """把 auth.json 里已填的 key 变量收集成注入 dict（只读用户配置，不改机器、不落盘）。
    网关/relay 启动时用这些覆盖子进程环境，保证「新填的 key 立即生效」，
    不依赖注册表用户环境变量（改了只对新登录进程生效，本进程里旧进程拿不到新 key）。"""
    env = {}
    try:
        d = ReadAuthJson()
        if isinstance(d, dict):
            for k in set(KEYS):
                v = d.get(k)
                if v:
                    env[k] = str(v)
    except Exception:
        pass
    return env

def _start_hidden(args, logfile):
    # 隐藏窗口 + 重定向输出
    import io
    flags = 0
    if os.name=='nt':
        flags = getattr(subprocess,'CREATE_NO_WINDOW',0) | 0x00000008  # DETACHED? use NO_WINDOW
        flags = getattr(subprocess,'CREATE_NO_WINDOW',0)
    # 关键修复：把 auth.json 里当前已填的 key 注入子进程环境。
    # 否则网关/relay 只继承本进程启动时的旧环境，新填的 key 不会被上游使用。
    env = os.environ.copy()
    env.update(_auth_env())
    try:
        o = open(logfile,'w',encoding='utf-8'); e = open(logfile+'.err','w',encoding='utf-8')
    except Exception:
        o = subprocess.DEVNULL; e = subprocess.DEVNULL
    try:
        si=None
        if os.name=='nt':
            si=subprocess.STARTUPINFO(); si.dwFlags|=subprocess.STARTF_USESHOWWINDOW; si.wShowWindow=0
        return subprocess.Popen(args, stdout=o, stderr=e, startupinfo=si,
                                env=env,
                                creationflags=flags, cwd=os.path.dirname(args[0]) if len(args)>0 else None)
    except Exception:
        return None

# ---------- relay ----------
def RelayUpstream(): return 'http://127.0.0.1:%d/v1'%GWPORT if IsAgg() else CurModelUrl()

def StartRelay():
    # 先结束旧 relay / 网关并等待退出，再重新拉起，避免旧进程占用端口或 .exe
    KillProcWait('codex-relay.exe'); KillProcWait('relay-gateway.exe')
    KillPortProc(4446); KillPortProc(4447); KillPortProc(4448)
    if IsAgg():
        if not TestPort(GWPORT):
            ok,msg = StartGateway()
            if not ok: return (False,msg)
    else:
        StopGateway()
    port = FindRelayPort(); State.PORT=str(port)
    up = RelayUpstream()
    rp = EnsureBin('codex-relay.exe')
    if not rp: return (False,'找不到 relay 二进制（resources\\codex-relay.exe 缺失）')
    rkey = ReadAuthVal(State.K)
    if not rkey.strip():
        if IsAgg(): rkey='agg-local-gateway'
        else: return (False,'还没有 %s 的 API Key，请先填 Key'%State.P)
    os.makedirs(HIST, exist_ok=True)
    args=['--port',str(port),'--upstream',up,'--api-key',rkey,
          '--history-store','disk','--history-dir',HIST]
    okMsg = 'relay 端口 %s   上游 %s'%(port,up)
    _start_hidden([rp]+args, RL_LOG)
    for _ in range(6):
        if TestPort(port): return (True,'relay 已启动\n'+okMsg)
        time.sleep(0.5)
    # 一次重试
    KillProc('codex-relay.exe'); KillPortProc(port); time.sleep(0.8)
    _start_hidden([rp]+args, RL_LOG)
    for _ in range(8):
        if TestPort(port): return (True,'relay 已启动（重试）\n'+okMsg)
        time.sleep(0.5)
    return (False,'relay 在端口 %s 没起来\n诊断见 %s'%(port,RL_ERR))

def StopRelay():
    KillProc('codex-relay.exe'); KillPortProc(4446); StopGateway()

# ---------- 模型目录 JSON ----------
def SlugSet():
    slugs=[]
    if IsAgg():
        for n in NAMES:
            if n not in slugs: slugs.append(n)
    else:
        pbase = BaseOf(State.P)
        for i,p in enumerate(PROVIDERS):
            if BaseOf(p)==pbase:
                n=NAMES[i]
                if n not in slugs: slugs.append(n)
    return slugs

def GenCatalog():
    slugs=SlugSet()
    reEff = State.RE if State.RE in ('none','low','medium','high','xhigh','max') else 'high'
    levels=[{'effort':'none','description':'关闭思考，最快'},
            {'effort':'low','description':'轻量，快速'},
            {'effort':'medium','description':'均衡'},
            {'effort':'high','description':'深度推理'},
            {'effort':'xhigh','description':'极高深度'},
            {'effort':'max','description':'满血（max）'}]
    models=[]; pri=0
    base_inst='You are Codex, an agent that collaborates with the user to complete software engineering tasks.'
    for slug in slugs:
        ctx,mctx = CtxFor(slug)      # 每模型独立 CW/MCW（自动=官方规格表，或手动档覆盖）
        entry={
            'slug':slug,'display_name':slug,'description':'%s via %s'%(slug,State.P),
            'visibility':'list','supported_in_api':True,'priority':10000+pri,
            'default_reasoning_level':reEff,'supported_reasoning_levels':levels,
            'default_reasoning_summary':'none','support_verbosity':False,'default_verbosity':None,
            'shell_type':'shell_command','apply_patch_tool_type':'freeform',
            'web_search_tool_type':'text_and_image','truncation_policy':{'mode':'tokens','limit':10000},
            'supports_parallel_tool_calls':True,'supports_image_detail_original':False,
            'context_window':ctx,'max_context_window':mctx,'comp_hash':None,
            'effective_context_window_percent':95,'experimental_supported_tools':[],
            'input_modalities':['text'],'supports_search_tool':False,'use_responses_lite':False,
            'tool_mode':None,'multi_agent_version':None,'include_skills_usage_instructions':False,
            'base_instructions':base_inst,
            'model_messages':{'instructions_template':base_inst},
            'supports_reasoning_summaries':True,'supports_reasoning_summary_parameter':True,
            'additional_speed_tiers':[],'service_tiers':[],'default_service_tier':None,
            'availability_nux':None,'upgrade':None,'auto_review_model_override':None,
            'auto_compact_token_limit':None,
        }
        if slug in ('deepseek-v4-flash-vision-exp','glm-5.3-flash'):
            entry['input_modalities']=['text','image']; entry['supports_image_detail_original']=True
        models.append(entry); pri+=1
    catalog={'models':models}
    _json_no_bom(CATALOG, catalog)
    return len(models)

# ---------- config.toml ----------
def KillCodex(): KillProc('Codex.exe')

def WriteConfig():
    KillCodex(); time.sleep(0.8); KillProc('Codex.exe')
    os.makedirs(C, exist_ok=True)
    mcount = GenCatalog()
    catToml = (C.replace('\\','/')) + '/codex-relay-models.json'
    inlineKey = ReadAuthVal(State.K)
    if inlineKey: SetUserEnv(State.K, inlineKey)
    account = ReadAuthVal('ACCOUNT_NAME')
    if not account.strip(): account = BaseOf(State.P)
    sb=[]
    sb.append('model_provider = "codex-relay"')
    sb.append('')
    sb.append('model = "%s"'%State.M)
    sb.append('')
    sb.append('model_reasoning_effort = "%s"'%State.RE)
    sb.append('')
    if os.path.exists(CATALOG): sb.append('model_catalog_json = "%s"'%catToml)
    sb.append('')
    sb.append('[model_providers.codex-relay]')
    sb.append('name = "%s"'%account)
    sb.append('base_url = "http://127.0.0.1:%s/v1"'%State.PORT)
    sb.append('wire_api = "responses"')
    sb.append('requires_openai_auth = false')
    sb.append('api_key = "%s"'%inlineKey)
    with open(CFG,'w',encoding='utf-8',newline='\n') as f: f.write('\n'.join(sb))
    return '配置已写入：%s  →  127.0.0.1:%s\n模型目录 %d 个'%(State.M,State.PORT,mcount)

def ReadCfgModel():
    try:
        if os.path.exists(CFG):
            for line in open(CFG,encoding='utf-8'):
                import re
                m=re.match(r'^\s*model\s*=\s*"([^"]+)"',line)
                if m: return m.group(1)
    except Exception: pass
    return ''

def ReadCfgProvider():
    try:
        if os.path.exists(CFG):
            for line in open(CFG,encoding='utf-8'):
                import re
                m=re.match(r'^\s*model_provider\s*=\s*"([^"]+)"',line)
                if m: return m.group(1)
    except Exception: pass
    return ''

# ---------- 会话库迁移（python 自带 sqlite3，尽力而为）----------
def TryMigrate(model):
    msgs=[]
    try:
        files = glob.glob(os.path.join(C,'*.sqlite')) + glob.glob(os.path.join(C,'*.sqlite3'))
        found=False
        for f in files:
            found=True
            try:
                con=sqlite3.connect(f); cur=con.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='threads'")
                if cur.fetchone():
                    cur.execute("UPDATE threads SET model_provider='codex-relay', model=?",(model,))
                    con.commit(); n=cur.rowcount
                    msgs.append('  迁移 %s  %d 条会话 → %s'%(os.path.basename(f),n,model))
                con.close()
            except Exception as ex:
                msgs.append('  跳过 %s: %s'%(os.path.basename(f),str(ex)))
        if not found: msgs.append('  （没有需要迁移的会话库）')
    except Exception as ex:
        msgs.append('  迁移失败：%s'%str(ex))
    if not msgs: msgs.append('  （没有需要迁移的会话库）')
    return msgs

# ---------- 应用并启动 ----------
def ApplyAndStart():
    logLines=['模式：%s'%('汇聚（全部厂商一个端口）' if IsAgg() else '普通（单服务商直连）')]
    relay=StartRelay()
    if not relay[0]: return relay
    logLines.append(relay[1])
    time.sleep(0.5)
    logLines.append(WriteConfig())
    SaveState()
    logLines += TryMigrate(State.M)
    return (True,'\n'.join(logLines))

# ---------- 恢复出厂 ----------
def ResetFactory():
    KillCodex(); time.sleep(0.8)
    KillProc('codex-relay.exe'); KillProc('relay-gateway.exe'); KillPortProc(4446); KillPortProc(4447)
    for k in KEYS: DelUserEnv(k)
    DelUserEnv('ACCOUNT_NAME')
    if os.path.exists(CFG):
        import shutil
        try: shutil.copyfile(CFG, CFG+'.bak')
        except Exception: pass
        default=('model = "gpt-5.6-luna"\nmodel_provider = "openai"\n'
                 'model_reasoning_effort = "medium"\nmodel_verbosity = "medium"\n'
                 'approval_policy = "on-request"\nsandbox_mode = "workspace-write"\nweb_search = "cached"\n')
        with open(CFG,'w',encoding='utf-8',newline='\n') as f: f.write(default)
    WriteAuthJson({})
    for fname in ('codex-relay.exe','relay-gateway.exe','gateway-config.json','codex-relay-models.json',
                  'gui-state.json','restart-relay.bat','_vars.bat'):
        p=os.path.join(C,fname)
        if os.path.exists(p):
            try: os.remove(p)
            except Exception: pass
    for d in ('logs','cache','.tmp','.sandbox','.sandbox-bin','.sandbox-secrets'):
        p=os.path.join(C,d)
        if os.path.isdir(p):
            import shutil; shutil.rmtree(p, ignore_errors=True)
    for line in TryMigrate('gpt-5.6-luna'): log(line)
    SetModelByCode('D1'); State.RE='high'; State.AGG='0'; State.PORT='4446'
    return True

def log(s):
    # 由 UI 层注入；在此仅为占位，避免无 UI 时崩溃
    try:
        if _LOG_HOOK: _LOG_HOOK(s)
    except Exception: pass
_LOG_HOOK=None
def set_log_hook(fn): global _LOG_HOOK; _LOG_HOOK=fn

# ============================================================
#  图形界面层（Tkinter）
# ============================================================
LOG_BOX=None
LAST_OWNER=None
_ROOT=None

def add_log(s):
    # 线程安全：工作线程调 log() 时经由 root.after 回到主线程再写入 Text。
    box=LOG_BOX
    if box is None: return
    def _ins():
        try:
            ts=datetime.now().strftime('%H:%M:%S')
            box.insert('end','[%s] %s\n'%(ts,s)); box.see('end')
        except Exception: pass
    try:
        if _ROOT is not None: _ROOT.after(0,_ins)
        else: _ins()
    except Exception:
        try: _ins()
        except Exception: pass

def clear_log():
    if LOG_BOX: LOG_BOX.delete('1.0','end')

def refresh_top_status(root):
    # 顶栏只放状态点（占位小），模型等详细信息点 logo 弹出的状态窗里看
    s='relay ○'
    if TestPort(int(State.PORT)): s='relay ●'
    if IsAgg():
        s += '   网关 ●' if TestPort(GWPORT) else '   网关 ○'
    try:
        _top_status_label.config(text=s)
    except Exception: pass

def status_lines():
    m=ReadCfgModel() or State.M
    acc=ReadAuthVal('ACCOUNT_NAME') or BaseOf(State.P)
    L=[]
    L.append('Codex 图形助手   ·   模式: %s  ·  账号: %s'%('汇聚（网关路由）' if IsAgg() else '单服务商直连', acc))
    L.append('')
    L.append('当前模型   : '+m)
    L.append('当前档位   : '+State.RE)
    L.append('供应商     : '+State.P)
    L.append('relay 端口 : '+State.PORT)
    L.append('')
    L.append('relay      : '+('● 运行中' if TestPort(int(State.PORT)) else '○ 未启动'))
    L.append('汇聚网关   : '+('● 运行中 (127.0.0.1:%d)'%GWPORT if TestPort(GWPORT) else '○ 未启动'))
    L.append('配置文件   : '+('已生成' if os.path.exists(CFG) else '未生成'))
    L.append('当前 Key   : '+('已填写 ✓' if ReadAuthVal(State.K).strip() else '未填写 ✗'))
    return L

def test_keyset(slot): return bool(ReadAuthVal(slot).strip())

# ---- 主窗口类 ----
class Gui:
    def __init__(self, root):
        self.root=root
        self.tv=None; self.uiRE=None; self.uiAcct=None; self.uiAgg=None
        self.uiCTX=None
        self.uiAggVar=None; self.split=None
        self.valModel=None; self.valDesc=None; self.valProv=None; self.valKey=None
        self.descLabel=None; self.lnk=None
        self.worker=None
        self._acctLast=None   # 记录上次填进账号框的值，避免每次刷新都 delete+insert

    # ---------- UI 构建 ----------
    def build(self):
        root=self.root
        root.title('Codex 图形助手')
        root.geometry('900x640'); root.minsize(800,580)
        root.configure(bg='#F3F6FA')
        # 顶栏
        global _top_status_label
        top=tk.Frame(root, bg='#1C48A0', height=64); top.pack(side='top', fill='x'); top.pack_propagate(False)
        # logo (canvas 渐变圆 + C)
        logo=tk.Canvas(top, width=40, height=40, bg='#1C48A0', highlightthickness=0, cursor='hand2')
        logo.create_oval(2,2,38,38, fill='#4096FF', outline='')
        logo.create_text(20,20,text='C',fill='white',font=('Segoe UI',22,'bold'))
        logo.place(x=16,y=11)
        logo.bind('<Button-1>', lambda e: self.show_status())
        tk.Label(top,text='Codex 图形助手',bg='#1C48A0',fg='white',
                 font=('Microsoft YaHei UI',15,'bold')).place(x=64,y=16)
        _top_status_label=tk.Label(top,text='加载中…',bg='#1C48A0',fg='#DCE6FF',font=('Microsoft YaHei UI',9))
        _top_status_label.pack(side='right',padx=14)

        # 主分栏
        split=tk.PanedWindow(root, orient='horizontal', sashwidth=6, bg='#E6ECF5')
        split.pack(side='top',fill='both',expand=True,padx=0,pady=(8,6))
        self.split=split

        # 左：模型树
        left=tk.Frame(split, bg='white', width=250); left.pack_propagate(False)
        tk.Label(left,text='选择模型',bg='white',fg='#78829A',font=('Microsoft YaHei UI',9)).pack(anchor='w',padx=10,pady=(8,4))
        tv=ttk.Treeview(left, show='tree')
        vsb=ttk.Scrollbar(left,orient='vertical',command=tv.yview); tv.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right',fill='y'); tv.pack(fill='both',expand=True)
        self.tv=tv
        # 分组
        group_order=['DeepSeek','Qwen','Kimi','GLM-TP','GLM','MiniMax','MiniMax-TP','Xiaomi','Xiaomi-TP','Tencent']
        groups={}
        for g in group_order:
            groups[g]=tv.insert('','end',text=g,open=True)
        for i,p in enumerate(PROVIDERS):
            node_id=tv.insert(groups[p],'end',text='[%s]  %s    %s'%(CODES[i],NAMES[i],NOTES[i]),values=(CODES[i],))
            tv.item(node_id, tags=('model',))
        tv.tag_configure('model', font=('Microsoft YaHei UI',9))
        tv.tag_bind('model','<<TreeviewSelect>>',self.on_select)
        split.add(left, minsize=210)

        # 右：详情 + 按钮
        right=tk.Frame(split, bg='white')
        split.add(right, minsize=430)
        self._build_right(right)
        # 底部日志
        self._build_log(root)
        self.root.after(80, self._place_sash)

        # 定时刷新
        self.tick()
        self.refresh_detail()

    def _place_sash(self):
        try:
            if self.split is None: return
            self.split.update_idletasks()
            w=self.split.winfo_width()
            if w>260: self.split.sash_place(0, 252, 0)
        except Exception:
            pass

    def _row(self,parent,cap,y):
        tk.Label(parent,text=cap,bg='white',fg='#78829A',font=('Microsoft YaHei UI',9)).place(x=24,y=y,anchor='nw')
    def _val(self,parent,y,big=False,w=0):
        l=tk.Label(parent,bg='white',fg='#23272E',anchor='w',justify='left',font=('Microsoft YaHei UI',12,'bold') if big else ('Microsoft YaHei UI',10))
        if w: l.config(width=w)
        l.place(x=150,y=y,anchor='nw'); return l

    def _build_right(self,right):
        # right 容器：横向画布 + 纵向滚动条，内容放入 body。
        # 右侧面板只有 ~420px 高而内容约 540px，必须可滚动，否则底部按钮被裁切。
        wrap = tk.Frame(right, bg='white')
        wrap.pack(side='left', fill='both', expand=True)
        cv  = tk.Canvas(wrap, bg='white', highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(wrap, orient='vertical', command=cv.yview)
        cv.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y'); cv.pack(side='left', fill='both', expand=True)
        body = tk.Frame(cv, bg='white')
        wid = cv.create_window((0,0), window=body, anchor='nw')
        def _on_cv(e):
            try:
                cv.itemconfigure(wid, width=e.width)
                if self.valDesc is not None:
                    self.valDesc.configure(wraplength=max(240, e.width-185))
            except Exception: pass
            try: cv.configure(scrollregion=cv.bbox('all'))
            except Exception: pass
        def _on_body(e):
            try: cv.configure(scrollregion=cv.bbox('all'))
            except Exception: pass
        def _wheel(e):
            try:
                d = getattr(e,'delta',0)
                if d==0: return
                cv.yview_scroll(int(-d/120), 'units')
            except Exception: pass
        cv.bind('<Configure>', _on_cv); body.bind('<Configure>', _on_body)
        cv.bind('<MouseWheel>', _wheel); body.bind('<MouseWheel>', _wheel)
        self._body=body; self._cv=cv

        y=14
        self._row(body,'当前模型',y); self.valModel=self._val(body,y,big=True); y+=32
        self._row(body,'说明',y)
        self.valDesc=tk.Label(body,bg='white',fg='#6E7380',justify='left',wraplength=440,anchor='w',font=('Microsoft YaHei UI',9))
        self.valDesc.place(x=150,y=y,anchor='nw'); y+=34
        self._row(body,'供应商',y); self.valProv=self._val(body,y); y+=30
        self._row(body,'API Key',y); self.valKey=self._val(body,y); y+=34
        # 推理档位
        self._row(body,'推理档位',y)
        self.uiRE=ttk.Combobox(body,values=['none','low','medium','high','xhigh','max'],state='readonly',width=18)
        self.uiRE.set('high'); self.uiRE.place(x=150,y=y,anchor='nw'); y+=34
        # 上下文窗口（CW/MCW）
        self._row(body,'上下文窗口',y)
        self.uiCTX=ttk.Combobox(body,values=CTX_OPTS,state='readonly',width=22)
        self.uiCTX.set(CTX_AUTO); self.uiCTX.place(x=150,y=y,anchor='nw'); y+=34
        # 账号名
        self._row(body,'账号名',y)
        self.uiAcct=tk.Entry(body,width=26,bd=1,relief='solid',font=('Microsoft YaHei UI',10))
        self.uiAcct.place(x=150,y=y,anchor='nw'); y+=34
        # 汇聚
        self.uiAggVar=tk.StringVar(value=State.AGG)
        self.uiAgg=tk.Checkbutton(body,text='汇聚模式：一个端口（4446→4447）通吃全部厂商，Codex 内可随意切换模型',
                                  bg='white',anchor='w',font=('Microsoft YaHei UI',9),variable=self.uiAggVar,onvalue='1',offvalue='0')
        self.uiAgg.place(x=150,y=y,anchor='nw'); y+=34
        # 官网链接
        self._row(body,'官网',y)
        bv=BaseOf(State.P)
        self.lnk=tk.Label(body,text=GUIDE[bv],bg='white',fg='#1C48A0',cursor='hand2',font=('Microsoft YaHei UI',9,'underline'))
        self.lnk.place(x=150,y=y,anchor='nw')
        self.lnk.bind('<Button-1>', lambda e: webbrowser.open(GUIDE[BaseOf(State.P)]))
        y+=44

        x=24; bw=320; bh=38
        b=tk.Button(body,text='管理 API Key / 上下文窗口',command=self.manage_key,
                    bg='white',fg='#23272E',bd=1,relief='solid',font=('Microsoft YaHei UI',9))
        b.place(x=x,y=y,width=bw,height=bh); y+=48
        b=tk.Button(body,text='应用并启动（写配置 + 起 relay）',command=self.apply_start,
                    bg='#1C48A0',fg='white',bd=0,activebackground='#2A5AC8',activeforeground='white',
                    font=('Microsoft YaHei UI',10,'bold'))
        b.place(x=x,y=y,width=bw,height=bh); y+=52
        b=tk.Button(body,text='查看状态',command=lambda:(self.show_status(),add_log('查看状态')),
                    bg='white',fg='#23272E',bd=1,relief='solid',font=('Microsoft YaHei UI',9))
        b.place(x=x,y=y,width=bw,height=bh); y+=48
        b=tk.Button(body,text='恢复出厂设置',command=self.reset_factory,
                    bg='#E65A5A',fg='white',bd=0,activebackground='#C84A4A',activeforeground='white',
                    font=('Microsoft YaHei UI',10,'bold'))
        b.place(x=x,y=y,width=bw,height=bh); y+=54
        # 提示行
        tk.Label(body,text='选择模型仅在列表预览，点「应用并启动」才会真正生效并写入配置。',bg='white',fg='#9AA3B5',
                 font=('Microsoft YaHei UI',8)).place(x=x,y=y)
        # 内容有固定高度；让 body 撑高以形成可滚动区域
        body.configure(height=y+60, width=700)
        body.after(10, _on_body)

    def _build_log(self,root):
        bottom=tk.Frame(root,bg='white',height=196); bottom.pack(side='bottom',fill='x'); bottom.pack_propagate(False)
        # 底部状态栏（始终可见，不依赖系统托盘）：relay/网关状态圆点 + 手动启动
        bar=tk.Frame(bottom,bg='#EDF1F8'); bar.pack(side='top',fill='x')
        self.stRelay=tk.Label(bar,text='relay ○',bg='#EDF1F8',fg='#C23B3B',
                              font=('Microsoft YaHei UI',9,'bold'))
        self.stRelay.pack(side='left',padx=(12,16),pady=5)
        self.stGW=tk.Label(bar,text='网关 ○',bg='#EDF1F8',fg='#C23B3B',
                           font=('Microsoft YaHei UI',9,'bold'))
        self.stGW.pack(side='left',pady=5)
        tk.Label(bar,text='  服务常驻后台 · 关窗最小化到托盘',bg='#EDF1F8',fg='#93A0B8',
                 font=('Microsoft YaHei UI',8)).pack(side='left',pady=5)
        tk.Button(bar,text='启动 汇聚网关',command=lambda:self._start_act('gateway'),
                  bg='#5B6C8A',fg='white',bd=0,activebackground='#4A5A76',
                  font=('Microsoft YaHei UI',9)).pack(side='right',padx=6,pady=3)
        tk.Button(bar,text='启动 Relay（含网关）',command=lambda:self._start_act('relay'),
                  bg='#1C7E3B',fg='white',bd=0,activebackground='#176632',
                  font=('Microsoft YaHei UI',9,'bold')).pack(side='right',padx=3,pady=3)
        tk.Button(bar,text='查看状态',command=lambda:(self.show_status(),add_log('查看状态')),
                  bg='white',fg='#23272E',bd=1,relief='solid',
                  font=('Microsoft YaHei UI',9)).pack(side='right',padx=8,pady=3)
        # 日志区
        boxf=tk.Frame(bottom,bg='#10141C'); boxf.pack(side='bottom',fill='both',expand=True)
        global LOG_BOX
        LOG_BOX=tk.Text(boxf,bg='#10141C',fg='#DFE6F2',insertbackground='#DFE6F2',
                        font=('Consolas',9),bd=0,wrap='none')
        sb=tk.Scrollbar(boxf,command=LOG_BOX.yview); LOG_BOX.configure(yscrollcommand=sb.set)
        sb.pack(side='right',fill='y'); LOG_BOX.pack(side='left',fill='both',expand=True)
        tk.Button(boxf,text='清空日志',command=clear_log,bg='#F0F3F8',bd=1,relief='solid',
                  font=('Microsoft YaHei UI',9)).pack(side='right',padx=6,pady=4)

    def _refresh_statusbar(self):
        # 刷新底部状态栏的状态圆点
        try:
            ron=TestPort(int(State.PORT))
            self.stRelay.config(text='relay ●' if ron else 'relay ○',
                                fg=('#1C7E3B' if ron else '#C23B3B'))
            gon=IsAgg() and TestPort(GWPORT)
            self.stGW.config(text='网关 ●' if gon else '网关 ○',
                             fg=('#1C7E3B' if gon else '#C23B3B'))
        except Exception: pass

    def _start_act(self, which):
        fn,label=(StartGateway,'汇聚网关') if which=='gateway' else (StartRelay,'relay')
        add_log('正在启动 %s ...'%label)
        def _bg():
            try:
                ok,msg=fn()
            except Exception as e:
                ok,msg=False,'异常：%s'%e
            def _done():
                self._refresh_statusbar()
                try: refresh_top_status(self.root); self.refresh_detail()
                except Exception: pass
                for ln in str(msg).split('\n'): add_log(ln)
                try:
                    (messagebox.showinfo if ok else messagebox.showwarning)(
                        ('%s 已启动'%label) if ok else ('%s 启动失败'%label),
                        msg, parent=self.root)
                except Exception: pass
            try: self.root.after(0,_done)
            except Exception: pass
        threading.Thread(target=_bg,daemon=True).start()

    # ---------- 刷新 ----------
    def refresh_detail(self):
        if self.valModel: self.valModel.config(text=State.M)
        if self.valDesc:
            self.valDesc.config(text=DESC.get(State.M,'') or (State.M+' via '+State.P))
        if self.valProv: self.valProv.config(text=State.P)
        if self.valKey:
            has=test_keyset(State.K)
            self.valKey.config(text='已填写 ✓' if has else '未填写 ✗',
                               fg=('#28A050' if has else '#DC4646'))
        if self.uiRE:
            if State.RE in ('none','low','medium','high','xhigh','max'): self.uiRE.set(State.RE)
        if self.uiCTX:
            opts=CtxOptionsFor(State.M)
            self.uiCTX.configure(values=opts)
            l=GetCtxLabel(State.M)
            self.uiCTX.set(l if l in opts else CTX_AUTO)
        if self.uiAcct:
            a=ReadAuthVal('ACCOUNT_NAME') or BaseOf(State.P)
            # 只在：值变化 且 用户当前没有正在编辑该框 时写入，避免打字被打断
            if self._acctLast!=a:
                focused=False
                try:
                    focused=(str(self.root.focus_get())==str(self.uiAcct))
                except Exception: focused=False
                if not focused:
                    try:
                        self.uiAcct.delete(0,'end'); self.uiAcct.insert(0,a); self._acctLast=a
                    except Exception: pass
        if self.uiAggVar:
            self.uiAggVar.set(State.AGG)
        if self.lnk: self.lnk.config(text=GUIDE[BaseOf(State.P)])

    def on_select(self,event=None):
        sel=self.tv.selection()
        if not sel: return
        vals=self.tv.item(sel[0],'values')
        if vals and vals[0] in CODES:
            SetModelByCode(vals[0]); self.refresh_detail()
            add_log('已选中: %s  (%s)'%(State.M,State.P))

    # ---------- 权威模型来源 ----------
    # 应用时一律以「当前在树上高亮的那一行」为准，实时刷新 State，
    # 避免开机被 gui-state.json 残留旧 M_code(qwen 等) 覆盖 State，
    # 造成「界面选 deepseek，写入 config 却是 qwen」的状态漂移。
    def _active_model_code(self):
        code = State.M_code
        try:
            for sid in self.tv.selection():
                v = self.tv.item(sid, 'values')
                if v and v[0] in CODES:
                    code = v[0]
                    break
        except Exception:
            pass
        return code

    # ---------- 保存偏好 ----------
    def save_prefs(self):
        State.RE=self.uiRE.get() if self.uiRE else State.RE
        if self.uiCTX:
            l=self.uiCTX.get()
            if l in CtxOptionsFor(State.M): SetCtxLabel(State.M, l)
        acct=self.uiAcct.get().strip() if self.uiAcct else ''
        if acct: SetAuthVal('ACCOUNT_NAME',acct)
        if self.uiAcct: self._acctLast=acct   # 记住当前框内内容，防止后续刷新覆盖
        if self.uiAggVar: State.AGG=self.uiAggVar.get()
        SaveState()

    # ---------- 动作 ----------
    def manage_key(self):
        # 单窗口同时管理「某模型的 API Key」和「该模型的上下文档位」：
        # 二者在一次「保存」里一并落盘，避免模态弹窗与主面板来回切换造成状态错乱。
        active = self._active_model_code()
        dlg = tk.Toplevel(self.root)
        dlg.title('管理 Key + 上下文窗口')
        dlg.configure(bg='white')
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()
        try:
            dlg.update_idletasks()
            x = self.root.winfo_rootx() + max((self.root.winfo_width() - 660)//2, 0)
            y = self.root.winfo_rooty() + max((self.root.winfo_height() - 600)//3, 20)
            dlg.geometry('660x600+%d+%d' % (x, y))
        except Exception:
            try: dlg.geometry('660x600')
            except Exception: pass

        pad = tk.Frame(dlg, bg='white')
        pad.pack(fill='both', expand=True, padx=22, pady=16)
        tk.Label(pad, text='管理 API Key 与上下文窗口', bg='white', fg='#1C48A0',
                 font=('Microsoft YaHei UI', 14, 'bold')).pack(anchor='w')
        tk.Label(pad, text='先在上方挑一个模型：填它的 Key，同时为它选上下文档位，点一次「保存」两者一起生效。',
                 bg='white', fg='#6E7380', justify='left', wraplength=600, anchor='w',
                 font=('Microsoft YaHei UI', 9)).pack(anchor='w', pady=(3, 12))

        # ---- 模型选择（覆盖全部 21 个模型/计费档位）----
        fmodel = tk.Frame(pad, bg='white'); fmodel.pack(fill='x')
        tk.Label(fmodel, text='模型：', bg='white', fg='#78829A',
                 font=('Microsoft YaHei UI', 10)).pack(side='left')
        labels = ['[%s] %s · %s %s' % (CODES[i], PROVIDERS[i], NAMES[i], NOTES[i])
                  for i in range(len(CODES))]
        modelvar = tk.StringVar()
        modelcb = ttk.Combobox(fmodel, textvariable=modelvar, values=labels,
                               state='readonly', width=68)
        modelcb.pack(side='left', fill='x', expand=True)

        # ---- 信息卡（随所选模型刷新）----
        info = tk.Label(pad, text='', bg='#F4F8FF', fg='#23272E', anchor='w', justify='left',
                        font=('Microsoft YaHei UI', 10), padx=12, pady=10)
        info.pack(fill='x', pady=(12, 4))

        # ---- Key 输入 ----
        fkey = tk.Frame(pad, bg='white'); fkey.pack(fill='x', pady=(10, 0))
        tk.Label(fkey, text='API Key：', bg='white', fg='#78829A',
                 font=('Microsoft YaHei UI', 10)).pack(side='left')
        keyvar = tk.StringVar()
        keyent = tk.Entry(fkey, textvariable=keyvar, width=60, bd=1, relief='solid',
                          font=('Microsoft YaHei UI', 9))
        keyent.pack(side='left', fill='x', expand=True, padx=(0, 6))
        def _paste():
            try:
                keyvar.set((self.root.clipboard_get() or '').strip())
            except Exception:
                pass
        tk.Button(fkey, text='粘贴', command=_paste, bg='#EEF3FB', bd=1, relief='solid',
                  font=('Microsoft YaHei UI', 9)).pack(side='left')
        tk.Label(pad, text='留空并保存 = 清除该模型（及同厂商）已填的 Key；只想改上下文时保留原 Key 即可。',
                 bg='white', fg='#9AA3B5', anchor='w', font=('Microsoft YaHei UI', 8)).pack(anchor='w', pady=(2, 8))

        # ---- 上下文档位 ----
        fctx = tk.Frame(pad, bg='white'); fctx.pack(fill='x', pady=(2, 0))
        tk.Label(fctx, text='上下文窗口：', bg='white', fg='#78829A',
                 font=('Microsoft YaHei UI', 10)).pack(side='left')
        ctxvar = tk.StringVar()
        ctxcb = ttk.Combobox(fctx, textvariable=ctxvar, values=CTX_OPTS,
                             state='readonly', width=24)
        ctxcb.pack(side='left')
        tk.Label(pad, text='CW=何时压缩 / MCW=会话硬顶。超过该模型真实窗口的档位（如不支 1M）不会出现。',
                 bg='white', fg='#9AA3B5', anchor='w', font=('Microsoft YaHei UI', 8)).pack(anchor='w', pady=(2, 10))

        holder = {'code': active}
        def _code():
            s = modelvar.get()
            for c in CODES:
                if s.startswith('[%s]' % c): return c
            return holder['code']
        def _load(code):
            holder['code'] = code
            i = IdxByCode(code)
            prov = PROVIDERS[i]; slug = NAMES[i]
            base = BaseOf(prov); slot = KEYS[i]; tp = prov.endswith('-TP')
            k = ReadAuthVal(slot)
            keyvar.set(k or '')
            mode = 'TokenPlan 套餐' if tp else '按量 API'
            have = bool(k.strip())
            info.config(text='供应商：%s\n计费：%s      当前 Key：%s\n官网：%s' % (
                base, mode, '已填写 ✓' if have else '未填写 ✗', GUIDE.get(base, '')))
            opts = CtxOptionsFor(slug)
            ctxcb.configure(values=opts)
            l = GetCtxLabel(slug)
            ctxvar.set(l if l in opts else CTX_AUTO)
            for j, lab in enumerate(labels):
                if lab.startswith('[%s]' % code):
                    modelcb.current(j); break
        modelcb.bind('<<ComboboxSelected>>', lambda e: _load(_code()))

        def _save(also_apply):
            code = holder['code']
            i = IdxByCode(code); slug = NAMES[i]; prov = PROVIDERS[i]
            base = BaseOf(prov); slot = KEYS[i]; tp = prov.endswith('-TP')
            mode = 'TokenPlan 套餐' if tp else '按量 API'
            trim = keyvar.get().strip()
            prior = ReadAuthVal(slot).strip()
            write_key = True
            if not trim and prior:
                if not messagebox.askyesno('请确认',
                        '输入框留空。要清除「%s」当前已填的 Key 吗？\n选「否」则保留原样（仅保存上下文）。' % base,
                        parent=dlg):
                    add_log('[Key] 已取消清除（保留原 Key，仅保存上下文）')
                    write_key = False
            if write_key:
                siblings = [slot]
                if base == 'GLM':      siblings += ['GLM_TOKENPLAN_API_KEY'] if not tp else ['ZHIPU_API_KEY']
                elif base == 'MiniMax': siblings += ['MINIMAX_TOKENPLAN_API_KEY'] if not tp else ['MINIMAX_API_KEY']
                elif base == 'Xiaomi':  siblings += ['XIAOMI_TOKENPLAN_API_KEY'] if not tp else ['XIAOMI_API_KEY']
                for s in siblings:
                    SetAuthVal(s, trim)
                    SetUserEnv(s, trim)
                SetAuthVal('BILLING_PREF_' + base, 'tp' if tp else 'regular')
            # 上下文：始终一并保存
            l = ctxvar.get()
            SetCtxLabel(slug, l if l in CTX_OPTS else CTX_AUTO)
            SetModelByCode(code)
            SaveState()
            self.refresh_detail()
            self._select_code(code)
            if trim:
                add_log('[Key] %s (%s) 已更新；上下文 → %s' % (base, mode, GetCtxLabel(slug)))
            elif prior:
                add_log('[Key] %s (%s) 已清除；上下文 → %s' % (base, mode, GetCtxLabel(slug)))
            else:
                add_log('[配置] %s 未填 Key，仅更新上下文 → %s' % (slug, GetCtxLabel(slug)))
            if also_apply:
                try: dlg.grab_release()
                except Exception: pass
                dlg.destroy()
                self.apply_start()
            else:
                messagebox.showinfo('Codex 助手',
                    '「%s」的 API Key 与上下文档位已一并保存。\n如 relay 尚未启动，请点主界面「应用并启动」生效。' % base,
                    parent=dlg)

        btns = tk.Frame(pad, bg='white'); btns.pack(fill='x', pady=(12, 0))
        tk.Button(btns, text='保存（Key + 上下文）', command=lambda: _save(False),
                  bg='#1C48A0', fg='white', bd=0, activebackground='#2A5AC8', activeforeground='white',
                  font=('Microsoft YaHei UI', 10, 'bold')).pack(side='left', padx=(0, 10))
        tk.Button(btns, text='保存并应用启动', command=lambda: _save(True),
                  bg='#23272E', fg='white', bd=0, activebackground='#3A3F4A', activeforeground='white',
                  font=('Microsoft YaHei UI', 10, 'bold')).pack(side='left', padx=(0, 10))
        tk.Button(btns, text='关闭', command=lambda: (dlg.grab_release(), dlg.destroy()),
                  bg='#EEF3FB', bd=1, relief='solid', font=('Microsoft YaHei UI', 10)).pack(side='left')

        _load(active)   # 初始显示当前高亮模型

    def _select_code(self, code):
        """把左侧模型树的高亮切到指定 code（纯 UI，不改写 State）。"""
        try:
            for item in self.tv.get_children():
                for child in self.tv.get_children(item):
                    v = self.tv.item(child, 'values')
                    if v and v[0] == code:
                        self.tv.selection_set(child)
                        self.tv.focus(child)
                        return True
        except Exception:
            pass
        return False

    def apply_start(self):
        # 以用户此刻在树上高亮的模型为唯一事实来源，先落定 State 再应用
        active = self._active_model_code()
        if active != State.M_code:
            SetModelByCode(active)
            self.refresh_detail()
            add_log('按当前勾选模型应用: %s  (%s)'%(State.M, State.P))
        self.save_prefs()
        aggNow=IsAgg()
        if not aggNow and not test_keyset(State.K):
            messagebox.showwarning('Codex 助手','还没有 %s 的 API Key。\n请先点「管理 Key」填写后再应用。'%State.P,parent=self.root)
            return
        add_log('正在应用并启动（%s, 推理 %s, 上下文 %s, %s）...'%(
            State.M,State.RE,GetCtxLabel(State.M),'汇聚' if aggNow else '单服务商'))
        self.root.config(cursor='watch')
        self.worker=threading.Thread(target=self._apply_bg,daemon=True); self.worker.start()

    def _apply_bg(self):
        try:
            ok,res=ApplyAndStart()
            self.root.after(0, lambda: self._apply_done(ok,res))
        except Exception as e:
            self.root.after(0, lambda: self._apply_done(False,'异常：%s'%e))

    def _apply_done(self,ok,res):
        self.root.config(cursor='')
        self.root.update_idletasks()
        if ok:
            add_log('relay 已就绪 ✓')
            for line in res.split('\n'): add_log(line)
            messagebox.showinfo('已启动','应用成功。\n\n'+res,parent=self.root)
        else:
            add_log('[错误] '+res)
            messagebox.showwarning('未启动','应用失败：\n'+res,parent=self.root)
        self.refresh_detail()

    def show_status(self):
        lines=status_lines()
        top=tk.Toplevel(self.root); top.title('状态总览'); top.geometry('460x360')
        top.resizable(False,False); top.configure(bg='white')
        tk.Label(top,text='\n'.join(lines),bg='white',fg='#23272E',justify='left',anchor='nw',
                 font=('Microsoft YaHei UI',11)).pack(fill='both',expand=True,padx=22,pady=18)
        tk.Button(top,text='知道了',command=top.destroy,bg='#1C48A0',fg='white',bd=0,
                  font=('Microsoft YaHei UI',10)).pack(pady=(0,14))

    def reset_factory(self):
        if not messagebox.askyesno('恢复出厂设置？',
            '恢复出厂会：\n · 终止 relay / 网关 / Codex 进程\n · 清除全部 API Key 环境变量 与 auth.json\n'
            ' · 重置 config.toml 为 OpenAI 默认\n · 卸载 codex-relay / relay-gateway 及配置\n'
            ' · 把历史会话迁回 OpenAI\n\n不会删除你的历史会话数据。',parent=self.root):
            add_log('已取消恢复出厂'); return
        add_log('开始恢复出厂设置...')
        self.root.config(cursor='watch')
        self.worker=threading.Thread(target=self._reset_bg,daemon=True); self.worker.start()

    def _reset_bg(self):
        try:
            ResetFactory()
            self.root.after(0, self._reset_done)
        except Exception as e:
            self.root.after(0, lambda: self._reset_done(('err',str(e))))

    def _reset_done(self,info=None):
        self.root.config(cursor='')
        if isinstance(info,tuple):
            add_log('[错误] '+info[1]); messagebox.showwarning('恢复失败',info[1],parent=self.root)
        else:
            self.refresh_detail()
            add_log('恢复出厂完成 → 回到 OpenAI 默认配置')
            messagebox.showinfo('恢复完成','已恢复出厂设置，回到 OpenAI 默认配置。',parent=self.root)

    def tick(self):
        refresh_top_status(self.root)
        try: self._refresh_statusbar()
        except Exception: pass
        self.root.after(3000,self.tick)


# ============================================================
#  系统托盘图标（纯 ctypes + Shell_NotifyIcon，零第三方依赖）
# ============================================================
_TRAY_AVAILABLE = False
if os.name == 'nt':
    try:
        from ctypes import wintypes
        _user32 = ctypes.windll.user32
        _shell32 = ctypes.windll.shell32
        # 关键：显式声明返回类型，避免 64 位下句柄被截断为 32 位
        _user32.LoadImageW.restype = wintypes.HANDLE
        _user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR,
                                       wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        _shell32.ExtractIconExW.restype = wintypes.UINT
        _user32.CreatePopupMenu.restype = wintypes.HMENU
        _user32.AppendMenuW.restype = wintypes.BOOL
        _user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT,
                                        ctypes.c_ssize_t, wintypes.LPCWSTR]
        _user32.GetModuleHandleW.restype = wintypes.HMODULE
        _user32.RegisterClassW.restype = wintypes.ATOM
        _user32.CreateWindowExW.restype = wintypes.HWND
        _shell32.Shell_NotifyIconW.restype = wintypes.BOOL
        _user32.GetMessageW.restype = wintypes.BOOL
        _user32.TranslateMessage.restype = wintypes.BOOL
        _user32.DispatchMessageW.restype = ctypes.c_ssize_t
        _user32.DefWindowProcW.restype = ctypes.c_ssize_t
        _user32.PostQuitMessage.restype = None
        _user32.PostMessageW.restype = wintypes.BOOL
        _user32.DestroyWindow.restype = wintypes.BOOL
        _user32.GetCursorPos.restype = wintypes.BOOL
        _user32.SetForegroundWindow.restype = wintypes.BOOL
        _user32.TrackPopupMenu.restype = ctypes.c_int
        _TRAY_AVAILABLE = True
    except Exception:
        _TRAY_AVAILABLE = False

class _GUID(ctypes.Structure):
    _fields_ = [('Data1', ctypes.c_ulong), ('Data2', ctypes.c_ushort),
                ('Data3', ctypes.c_ushort), ('Data4', ctypes.c_ubyte * 8)]

class _NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ('cbSize', ctypes.c_ulong), ('hWnd', ctypes.c_void_p), ('uID', ctypes.c_uint),
        ('uFlags', ctypes.c_uint), ('uCallbackMessage', ctypes.c_uint),
        ('hIcon', ctypes.c_void_p), ('szTip', ctypes.c_wchar * 128),
        ('dwState', ctypes.c_ulong), ('dwStateMask', ctypes.c_ulong),
        ('szInfo', ctypes.c_wchar * 256), ('uTimeout', ctypes.c_uint),
        ('szInfoTitle', ctypes.c_wchar * 64), ('dwInfoFlags', ctypes.c_ulong),
        ('guidItem', _GUID), ('hBalloonIcon', ctypes.c_void_p),
    ]

class _WNDCLASSW(ctypes.Structure):
    _fields_ = [('style', ctypes.c_uint), ('lpfnWndProc', ctypes.c_void_p),
                ('cbClsExtra', ctypes.c_int), ('cbWndExtra', ctypes.c_int),
                ('hInstance', ctypes.c_void_p), ('hIcon', ctypes.c_void_p),
                ('hCursor', ctypes.c_void_p), ('hbrBackground', ctypes.c_void_p),
                ('lpszMenuName', ctypes.c_wchar_p), ('lpszClassName', ctypes.c_wchar_p)]

class _POINT(ctypes.Structure):
    _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]

_WNDPROC_T = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint,
                                ctypes.c_size_t, ctypes.c_ssize_t)

WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_APP = 0x8000

class TrayIcon:
    """托盘图标：左键/双击=打开主界面，右键=菜单(打开/状态/退出)。"""
    def __init__(self, title, on_show=None, on_status=None, on_exit=None,
                 on_relay=None, on_gateway=None):
        self.title = title
        self.on_show = on_show
        self.on_status = on_status
        self.on_exit = on_exit
        self.on_relay = on_relay
        self.on_gateway = on_gateway
        self._q = queue.Queue()
        self._cb_msg = WM_APP + 1
        self._hwnd = None
        self._nid = None
        self._hicon = None
        self._hmenu = None
        self._proc = None
        self._thread = None

    def start(self):
        if not _TRAY_AVAILABLE:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _load_icon(self):
        h = None
        try:
            if getattr(sys, 'frozen', False):
                big = ctypes.c_void_p(); small = ctypes.c_void_p()
                n = _shell32.ExtractIconExW(sys.executable, 0,
                                            ctypes.byref(big), ctypes.byref(small), 1)
                if n > 0:
                    h = small.value if small.value else big.value
            if not h:
                p = os.path.join(ResDir, 'app.ico')
                if os.path.exists(p):
                    h = _user32.LoadImageW(None, p, 1, 0, 0, 0x10)  # IMAGE_ICON | LR_LOADFROMFILE
        except Exception:
            h = None
        return h

    def _run(self):
        try:
            self._create()
        except Exception:
            return
        msg = wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))

    def _make_proc(self):
        tray = self
        def wndproc(hwnd, msg, wparam, lparam):
            if msg == WM_CLOSE:
                _user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                _user32.PostQuitMessage(0)
                return 0
            if msg == tray._cb_msg:
                evt = int(lparam)
                if evt in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                    tray._q.put('show')
                elif evt == WM_RBUTTONUP:
                    tray._show_menu()
                return 0
            return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)
        return _WNDPROC_T(wndproc)

    def _create(self):
        self._hicon = self._load_icon()
        self._hmenu = _user32.CreatePopupMenu()
        _user32.AppendMenuW(self._hmenu, 0x0000, 1001, '打开 Codex 助手')
        _user32.AppendMenuW(self._hmenu, 0x0000, 1002, '查看状态')
        _user32.AppendMenuW(self._hmenu, 0x0800, 0, '')
        _user32.AppendMenuW(self._hmenu, 0x0000, 1003, '启动 Relay（含汇聚网关）')
        _user32.AppendMenuW(self._hmenu, 0x0000, 1004, '启动 汇聚网关')
        _user32.AppendMenuW(self._hmenu, 0x0800, 0, '')
        _user32.AppendMenuW(self._hmenu, 0x0000, 1005, '退出')

        cls_name = 'CodexTrayWnd'
        proc = self._make_proc()
        self._proc = proc  # 防止被 GC
        wc = _WNDCLASSW()
        wc.lpfnWndProc = ctypes.cast(proc, ctypes.c_void_p)
        wc.hInstance = _user32.GetModuleHandleW(None)
        wc.lpszClassName = cls_name
        _user32.RegisterClassW(ctypes.byref(wc))
        # HWND_MESSAGE = -3（消息专用隐藏窗口）
        self._hwnd = _user32.CreateWindowExW(0, cls_name, cls_name, 0, 0, 0, 0, 0,
                                             ctypes.c_void_p(-3), None, wc.hInstance, None)
        if not self._hwnd:
            return
        nid = _NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = 0x01 | 0x02 | 0x04  # NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = self._cb_msg
        nid.hIcon = self._hicon
        nid.szTip = self.title
        _shell32.Shell_NotifyIconW(0, ctypes.byref(nid))  # NIM_ADD
        self._nid = nid

    def _show_menu(self):
        pt = _POINT()
        _user32.GetCursorPos(ctypes.byref(pt))
        _user32.SetForegroundWindow(self._hwnd)
        cmd = _user32.TrackPopupMenu(self._hmenu, 0x0100 | 0x0002 | 0x0080,
                                     pt.x, pt.y, 0, self._hwnd, None)
        _user32.PostMessageW(self._hwnd, 0x0000, 0, 0)  # 让菜单正常关闭
        if cmd == 1001:
            self._q.put('show')
        elif cmd == 1002:
            self._q.put('status')
        elif cmd == 1003:
            self._q.put('relay')
        elif cmd == 1004:
            self._q.put('gateway')
        elif cmd == 1005:
            self._q.put('exit')

    def stop(self):
        if self._nid is not None and _TRAY_AVAILABLE:
            try:
                _shell32.Shell_NotifyIconW(2, ctypes.byref(self._nid))  # NIM_DELETE
            except Exception:
                pass
        if self._hwnd and _TRAY_AVAILABLE:
            try:
                _user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
            except Exception:
                pass

    def poll(self):
        """主线程调用：处理托盘事件，返回 True 表示已请求退出。"""
        try:
            while True:
                evt = self._q.get_nowait()
                if evt == 'show' and self.on_show:
                    self.on_show()
                elif evt == 'status' and self.on_status:
                    self.on_status()
                elif evt == 'relay' and self.on_relay:
                    self.on_relay()
                elif evt == 'gateway' and self.on_gateway:
                    self.on_gateway()
                elif evt == 'exit' and self.on_exit:
                    self.on_exit()
                    return True
        except queue.Empty:
            pass
        return False


def main():
    global _ROOT
    LoadState()
    # 清理旧版计划任务（自动重启/保活功能已移除；只删除不重建）。
    if os.name == 'nt':
        try:
            _run(['schtasks', '/Delete', '/F', '/TN', 'CodexRelayKeepAlive'])
        except Exception:
            pass
    root=tk.Tk()
    _ROOT=root
    set_log_hook(add_log)
    g=Gui(root); g.build()
    # 选中当前模型节点
    for item in g.tv.get_children():
        for child in g.tv.get_children(item):
            v=g.tv.item(child,'values')
            if v and v[0]==State.M_code: g.tv.selection_set(child)
    add_log('欢迎使用 Codex 图形助手（Windows Python 版，零依赖）')
    add_log('默认模型: %s   档位: %s'%(State.M,State.RE))

    # 系统托盘：关闭主窗口=最小化到托盘（relay/网关继续跑），右键菜单可手动启动 relay/网关，退出才真正结束。
    _quitting = False
    def _real_quit():
        nonlocal _quitting
        if _quitting:
            return
        _quitting = True
        try: tray.stop()
        except Exception: pass
        try: g.save_prefs()
        except Exception: pass
        try: root.destroy()
        except Exception: pass

    def _tray_start(fn, label):
        add_log('正在启动 %s ...' % label)
        def _bg():
            try:
                ok, msg = fn()
            except Exception as e:
                ok, msg = False, '异常：%s' % e
            def _done():
                try: refresh_top_status(root)
                except Exception: pass
                try: g.refresh_detail()
                except Exception: pass
                for ln in str(msg).split('\n'): add_log(ln)
                try:
                    (messagebox.showinfo if ok else messagebox.showwarning)(
                        ('%s 已启动' % label) if ok else ('%s 启动失败' % label),
                        msg, parent=root)
                except Exception: pass
            try: root.after(0, _done)
            except Exception:
                try: _done()
                except Exception: pass
        threading.Thread(target=_bg, daemon=True).start()

    tray = TrayIcon(
        'Codex 助手',
        on_show=lambda: (root.deiconify(), root.lift()),
        on_status=lambda: g.show_status(),
        on_exit=_real_quit,
        on_relay=lambda: _tray_start(StartRelay, 'relay'),
        on_gateway=lambda: _tray_start(StartGateway, '汇聚网关'),
    )
    try:
        tray.start()
    except Exception:
        pass

    def _poll_tray():
        if _quitting:
            return
        try:
            if tray.poll():
                return
        except Exception:
            pass
        try:
            root.after(200, _poll_tray)
        except Exception:
            pass

    def on_close():
        # 关闭=最小化到托盘，服务继续跑
        try:
            root.withdraw()
            add_log('已最小化到系统托盘；右键托盘图标可退出。')
        except Exception:
            try: _real_quit()
            except Exception: pass
    root.protocol('WM_DELETE_WINDOW',on_close)
    try:
        root.after(200, _poll_tray)
    except Exception:
        pass
    root.mainloop()

if __name__=='__main__':
    try:
        if not HAVE_TK:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, '缺少 Python tkinter 支持。请安装完整版 Python（含 tcl/tk）后重试。\n\n' + str(_TK_ERR), 'Codex 助手', 0x10)
            sys.exit(1)
        main()
    except SystemExit:
        raise
    except Exception as _top_exc:
        # 兜底：无论是否 pythonw，都写出日志并弹窗提示，避免无声崩溃。
        import traceback
        _tb = traceback.format_exc()
        try:
            if getattr(sys, 'frozen', False):
                # 单文件 exe：__file__ 位于只读的临时释放目录，错误日志改写到用户目录
                os.makedirs(C, exist_ok=True)
                _elog = os.path.join(C, 'codex-gui-error.log')
            else:
                _elog = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'codex-gui-error.log')
            with open(_elog, 'w', encoding='utf-8') as _f:
                _f.write(_tb)
        except Exception: pass
        try:
            ctypes.windll.user32.MessageBoxW(0, 'Codex 助手 运行出错：\n\n' + _tb[-1800:], 'Codex 助手', 0x10)
        except Exception:
            try:
                sys.stderr.write(_tb)
            except Exception: pass
        sys.exit(1)
