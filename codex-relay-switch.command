#!/bin/zsh
# ============================================================================
#  codex-relay-switch.command  ——  macOS 自动化试验脚本
#
#  用途：
#    在真实机器上反复试验「Codex 当前走哪个模型 / 厂商」的热切换，
#    并可一键还原到「官方 Codex 状态」（relay 改装前 / 出厂默认）。
#
#  设计原则：
#    · 每次写入 config.toml 前，先自动快照到 ~/.codex/codex-switch-backups/
#      （按时间戳命名），保证任何试验都可回滚 —— 绝不静默破坏。
#    · 「还原官方」是外科手术式：只移除 relay 改装写入的顶层键和
#      [model_providers.custom] 段，其余由 Codex App 自己维护的段
#      （desktop / plugins / mcp_servers / projects 等）原样保留。
#    · 默认不删除任何文件、不清空 auth.json、不触碰与 Codex relay
#      无关的 API Key / 进程。
#    · 所有 key / token 显示均脱敏（显示为 ***）。
#
#  用法：双击运行，或在终端执行
#       chmod +x codex-relay-switch.command && ./codex-relay-switch.command
# ============================================================================

CODEX_DIR="$HOME/.codex"
CONFIG="$CODEX_DIR/config.toml"
AUTH="$CODEX_DIR/auth.json"
VARS="$CODEX_DIR/_vars.sh"
GWCFG="$CODEX_DIR/gateway-config.json"
CATALOG="$CODEX_DIR/codex-relay-models.json"
BACKUP_ROOT="$CODEX_DIR/codex-switch-backups"

GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; YELLOW=$'\033[1;33m'; CYAN=$'\033[0;36m'; BOLD=$'\033[1m'; NC=$'\033[0m'

say()  { printf '%b\n' "$*"; }
info() { say "${CYAN}ℹ $*${NC}"; }
ok()   { say "${GREEN}✔ $*${NC}"; }
warn() { say "${YELLOW}⚠ $*${NC}"; }
err()  { say "${RED}✘ $*${NC}"; }

# 脱敏：把 sk-xxxx / long tokens 显示成前缀***
mask() { sed -E 's/(sk-[A-Za-z0-9]{6})[A-Za-z0-9_-]+/\1***/g'; }

# ── 环境自检 ──
[[ -f "$CONFIG" ]] || { err "找不到 $CONFIG"; exit 1; }

# ── 读取当前状态 ──
cur_field() { grep "^$1 *=" "$CONFIG" 2>/dev/null | head -1 | sed -E 's/^[^=]*=[[:space:]]*"?([^"]*)"?.*/\1/'; }
cur_model_provider=$(cur_field model_provider)
cur_model=$(cur_field model)
cur_effort=$(cur_field model_reasoning_effort)
cur_catalog=$(cur_field model_catalog_json)

# ── 备份（写入前调用）──
snapshot() {
  mkdir -p "$BACKUP_ROOT"
  local ts; ts=$(date +%Y%m%d-%H%M%S)
  local d="$BACKUP_ROOT/$ts"
  mkdir -p "$d"
  cp -p "$CONFIG" "$d/config.toml" 2>/dev/null
  [[ -f "$AUTH" ]]    && cp -p "$AUTH"    "$d/auth.json"    2>/dev/null
  [[ -f "$VARS" ]]    && cp -p "$VARS"    "$d/_vars.sh"     2>/dev/null
  [[ -f "$GWCFG" ]]   && cp -p "$GWCFG"   "$d/gateway-config.json" 2>/dev/null
  [[ -f "$CATALOG" ]] && cp -p "$CATALOG" "$d/codex-relay-models.json" 2>/dev/null
  echo "$ts"
}

# ── 用 python 对 config.toml 做安全的行级编辑 ──
# $1 = python 源（在 python 里通过 CONFIG_PATH / jsonfile 变量可用）
edit_config() {
  local code="$1"
  CONFIG_PATH="$CONFIG" AUTH_PATH="$AUTH" GW_PATH="$GWCFG" /usr/bin/python3 - "$code" <<'PYEOF'
import os, json, sys
cfg = os.environ.get("CONFIG_PATH","")
auth = os.environ.get("AUTH_PATH","")
gw   = os.environ.get("GW_PATH","")
exec(sys.argv[1])
PYEOF
}

# ── 列出可用的模型 slug（来自网关配置；不在网关里也允许自定义）──
list_models() {
  if [[ -f "$GWCFG" ]]; then
    /usr/bin/python3 -c "
import json,sys
g=json.load(open('$GWCFG'))
m=g.get('models',{})
pv=g.get('providers',{})
for slug,prov in m.items():
    print('%s  <-- %s' % (slug, prov))
" 2>/dev/null
  fi
}

# ============================================================
#  试验：热切换 Codex 当前 model
# ============================================================
do_experiment() {
  echo ""
  echo "  ┌────────────────────────────────────────────────┐"
  echo "  │  试验模式：切换 Codex 当前走哪个模型/厂商         │"
  echo "  │  每次都会先自动备份，可随时从菜单还原              │"
  echo "  └────────────────────────────────────────────────┘"
  echo ""

  if [[ -f "$GWCFG" ]]; then
    echo "  网关当前可用模型（slug  <--  厂商）："
    list_models | sed 's/^/      /'
  fi
  echo ""
  printf "  输入要切换到的 model slug (直接回车=取消): "
  read -r NEWMODEL
  [[ -z "$NEWMODEL" ]] && { warn "已取消"; wait_key; return; }

  # 校验网关里是否有这个模型
  local in_gw=0
  if [[ -f "$GWCFG" ]]; then
    in_gw=$(/usr/bin/python3 -c "
import json
g=json.load(open('$GWCFG'))
print('1' if '$NEWMODEL' in g.get('models',{}) else '0')
" 2>/dev/null)
    in_gw=${in_gw:-0}
  fi
  if [[ "$in_gw" != "1" ]]; then
    warn "「$NEWMODEL」不在网关 models 表里。仍要强制写入试验吗？(y/N)"
    printf "  → "; read -r yn
    [[ "$yn" != "y" && "$yn" != "Y" ]] && { warn "已取消"; wait_key; return; }
  fi

  local ts; ts=$(snapshot)
  edit_config '
import re
txt = open(cfg, "r", encoding="utf-8").read()
model = sys.argv[1] if len(sys.argv)>1 else None
# 统一把顶层 key 规整到文件头区域
# 设 model 与 model_reasoning_effort
def set_top_key(body, key, val):
    pat = re.compile(r"^" + re.escape(key) + r"\s*=.*$", re.M)
    line = key + " = \"" + val + "\""
    if pat.search(body):
        return pat.sub(line, body, count=1)
    return line + "\n" + body
# model_provider 切到 custom，确保 custom provider 指向本地 relay
txt = set_top_key(txt, "model_provider", "custom")
txt = set_top_key(txt, "model", model)
open(cfg, "w", encoding="utf-8").write(txt)
' "$NEWMODEL" 2>/dev/null

  # 确保存在 custom provider 段（以现有 auth.json 内 deepseek 之类 inline key 兜底；没有就留空)
  if ! grep -q '^\[model_providers.custom\]' "$CONFIG"; then
    local ik
    ik=$(/usr/bin/python3 -c "import json,os;d=json.load(open('$AUTH')) if os.path.exists('$AUTH') else {}; print(d.get('DEEPSEEK_API_KEY',''))" 2>/dev/null)
    {
      echo ""
      echo "[model_providers.custom]"
      echo "name = \"relay\""
      echo "base_url = \"http://127.0.0.1:4446/v1\""
      echo "wire_api = \"responses\""
      echo "requires_openai_auth = false"
      echo "api_key = \"$ik\""
    } >> "$CONFIG"
  fi

  ok "已切换到 model=$NEWMODEL（备份: $BACKUP_ROOT/$ts）"
  echo ""
  info "提示：Codex 桌面 App 需要重启（或新建会话）才会应用新 model。"
  wait_key
}

# ============================================================
#  还原官方 Codex 状态（出厂 / 改装前）
#  只移除 relay 顶块 + [model_providers.custom]，其余段保留
# ============================================================
do_restore_official() {
  echo ""
  echo "  ╔══════════════════════════════════════════════════╗"
  echo "  ║  还原到官方 Codex 状态                           ║"
  echo "  ║  将移除 relay 改装写入的：                       ║"
  echo "  ║    model_provider=custom / model / effort / catalog ║"
  echo "  ║    model_catalog_json                            ║"
  echo "  ║    [model_providers.custom] 段                    ║"
  echo "  ║  并写回 model_provider = \"openai\"               ║"
  echo "  ║                                                 ║"
  echo "  ║  保留(不删)：desktop/plugins/mcp_servers/projects║"
  echo "  ║  保留(不删)：auth.json 内全部账号与国内 key        ║"
  echo "  ║  保留(不删)：历史会话、relay 二进制与网关配置       ║"
  echo "  ║  只动 config.toml 一个文件，且先备份              ║"
  echo "  ╚══════════════════════════════════════════════════╝"
  echo ""
  printf "  输入 yes 确认 (其他任意取消): "
  read -r confirm
  [[ "$confirm" != "yes" ]] && { warn "已取消"; wait_key; return; }

  local ts; ts=$(snapshot)
  edit_config '
import re
body = open(cfg, "r", encoding="utf-8").read()

# 1) 移除顶层 relay 键：model_provider / model / model_reasoning_effort
#    / model_catalog_json / model_verbosity（前 60 行内的顶层行）
lines = body.split("\n")
top_keys = {"model_provider", "model", "model_reasoning_effort",
            "model_catalog_json", "model_verbosity"}
out = []
in_custom = False
custom_done = False
i = 0
# 处理表格边界，手动切
result_lines = []
skip_next_blank_after_custom = False
cur = lines
idx = 0
while idx < len(cur):
    ln = cur[idx]
    stripped = ln.strip()
    # 判断是否正在 custom provider 段内
    if not in_custom and re.match(r"^\[model_providers\.custom\]\s*$", stripped):
        in_custom = True
        # 跳过该段所有内容直到下一个 [section]（不含）之前的空行也跳过
        idx += 1
        while idx < len(cur):
            s = cur[idx].strip()
            if s == "" :
                idx += 1
                continue
            if s.startswith("["):
                break
            idx += 1
        # 现在 idx 指向下一段标题，保留段标题前的单个空行即可
        continue
    # 顶层 key 删除（仅当不在任何 table 内 —— 用是否以'['开头切换状态判断）
    if not stripped.startswith("[") and not in_custom:
        key = ln.split("=",1)[0].strip() if "=" in ln else ""
        if key in top_keys:
            idx += 1
            # 吃掉紧随其后的空行
            if idx < len(cur) and cur[idx].strip() == "":
                idx += 1
            continue
    result_lines.append(ln)
    idx += 1

body = "\n".join(result_lines)
# 规整多余连续空行
while "\n\n\n" in body:
    body = body.replace("\n\n\n", "\n\n")
body = body.rstrip("\n") + "\n"
# 2) 顶部写回官方默认头
head = "# Codex default configuration\n" \
       "model = \"gpt-5.6-luna\"\n" \
       "model_provider = \"openai\"\n" \
       "model_reasoning_effort = \"medium\"\n"
# 若 body 已以 head 开头避免重复
if not body.lstrip().startswith("# Codex default"):
    body = head + body
open(cfg, "w", encoding="utf-8").write(body)
'
  ok "config.toml 已还原为官方 Codex 状态"
  info "当前 model_provider=$(grep '^model_provider' "$CONFIG" | sed -E 's/.*"([^"]*)".*/\1/')"
  info "备份: $BACKUP_ROOT/$ts"
  echo ""
  info "提示：Codex 桌面 App 需重启才会回到官方后端。"
  wait_key
}

# ============================================================
#  还原到某次快照
# ============================================================
do_restore_snapshot() {
  echo ""
  if [[ ! -d "$BACKUP_ROOT" ]] || [[ -z "$(ls -A "$BACKUP_ROOT" 2>/dev/null)" ]]; then
    warn "还没有任何备份。先做一次试验才会产生备份。"
    wait_key; return
  fi
  echo "  可选备份："
  local snaps; snaps=($(ls -1 "$BACKUP_ROOT" | sort -r))
  local i=1
  for s in "${snaps[@]}"; do
    printf '    [%d] %s\n' "$i" "$s"
    i=$((i+1))
  done
  printf "  选择要还原的备份编号 (回车=取消): "
  read -r n
  [[ -z "$n" ]] && { warn "已取消"; wait_key; return; }
  local pick; pick=$(ls -1 "$BACKUP_ROOT" | sort -r | sed -n "${n}p")
  [[ -z "$pick" ]] && { err "无效编号"; wait_key; return; }
  if [[ -f "$BACKUP_ROOT/$pick/config.toml" ]]; then
    # 先给当前状态留个反向快照
    local ts; ts=$(snapshot)
    cp -p "$BACKUP_ROOT/$pick/config.toml" "$CONFIG"
    ok "已从备份 $pick 还原 config.toml（改动前又自动留了份 $ts）"
  else
    err "该备份里没有 config.toml"
  fi
  wait_key
}

# ============================================================
#  查看当前状态（脱敏）
# ============================================================
do_status() {
  echo ""
  echo "  ── 当前 Codex 后端指向 ──"
  printf "  model_provider        = %s\n" "$cur_model_provider"
  printf "  model                 = %s\n" "$cur_model"
  printf "  model_reasoning_effort= %s\n" "$cur_effort"
  printf "  model_catalog_json    = %s\n" "${cur_catalog:-<无>}"
  if grep -q '^\[model_providers.custom\]' "$CONFIG"; then
    echo "  [model_providers.custom] 存在："
    grep -A6 '^\[model_providers.custom\]' "$CONFIG" | sed -E 's/(sk-[A-Za-z0-9]{6})[A-Za-z0-9_-]+/\1***/g; s/(api_key[[:space:]]*=[[:space:]]*")[^"]+/\1***/' | sed 's/^/      /'
  else
    echo "  [model_providers.custom] 不存在 → 走官方 openai 后端"
  fi
  echo ""
  echo "  ── 相关进程 ──"
  /usr/sbin/lsof -nP -iTCP:4446 -iTCP:4447 -sTCP:LISTEN 2>/dev/null | awk '{print "     " $1, $2, $9}' || true
  [[ -z "$(/usr/sbin/lsof -ti :4446 2>/dev/null)" ]] && echo "     (4446 未监听)"
  echo ""
  wait_key
}

wait_key() {
  echo ""
  printf "  按回车返回菜单..."; read -r _
}

# ── 主菜单 ──
menu() {
  while true; do
    clear 2>/dev/null || true
    echo "  =============================================="
    echo "   Codex relay 热切换试验器  (macOS)"
    echo "  =============================================="
    printf "   当前 model_provider = %s\n" "$cur_model_provider"
    printf "   当前 model          = %s\n" "$cur_model"
    echo "  ----------------------------------------------"
    echo "   [1] 试验：热切换当前 model（换厂商/换档）"
    echo "   [2] 还原：切回官方 Codex 状态"
    echo "   [3] 还原：回滚到某次自动快照"
    echo "   [4] 查看当前状态（脱敏）"
    echo "   [5] 退出"
    echo "  ----------------------------------------------"
    printf "  选择: "
    read -r act
    case "$act" in
      1) do_experiment ;;
      2) do_restore_official ;;
      3) do_restore_snapshot ;;
      4) do_status ;;
      5) echo "  再见～"; exit 0 ;;
      *) warn "无效选择" ;;
    esac
    # 每次改动后刷新当前值
    cur_model_provider=$(cur_field model_provider)
    cur_model=$(cur_field model)
    cur_effort=$(cur_field model_reasoning_effort)
    cur_catalog=$(cur_field model_catalog_json)
  done
}

menu
