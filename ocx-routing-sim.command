#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opencodex routing + combo-failover 仿真器 (macOS 终端)

这是一个把 opencodex (v2.42.0 / commit 48f8186) 源码逻辑移植成可交互实验的
教学/验证脚本，用于理解并反复试验：
   1) 路由解析 —— routeModelInternal 的九级优先级判定 (src/router.ts:595)
   2) combo 切换 —— pickComboTarget 的 4 种策略 (src/combos/resolve.ts:141)
   3) failover —— advanceComboAfterFailure / noteComboSuccess (resolve.ts:232/272)

不是真实网关，是"逐行翻译成 Python 的模型"：决策顺序、粘性、冷却、
配额耗尽、排重集合、NoAvailable 判定都按源码保留，可用来验证"能不能热切换"。

用法：
   ./ocx-routing-sim.command            # 进入交互 REPL
   ./ocx-routing-sim.command resolve deepseek/deepseek-chat
   ./ocx-routing-sim.command resolve gpt-5.1-codex
   ./ocx-routing-sim.command sim fs-test

macOS：也可以直接双击运行（会打开终端）。
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

# --------------------------------------------------------------------------
# 常量 / 编码器（与 src/providers/slug-codec.ts 对应）
# --------------------------------------------------------------------------
SLUG_ALIAS_SEPARATOR = "-"
OPENAI_CODEX_PROVIDER_ID = "openai"


def encode_routed_model_id(rid: str) -> str:
    """原生 id 里的 '/' 替换成 '-'（对外只有单一斜杠）。"""
    return rid.replace("/", SLUG_ALIAS_SEPARATOR) if "/" in rid else rid


def routed_slug(provider: str, rid: str) -> str:
    return f"{provider}/{encode_routed_model_id(rid)}"


def decode_routed_model_id(requested: str, known: list[str]) -> str:
    """原生精确命中 > 唯一别名命中 > 透传。永不盲替换。"""
    alias_match = None
    for rid in known:
        if rid == requested:
            return rid
        if "/" in rid and encode_routed_model_id(rid) == requested:
            if alias_match is not None and alias_match != rid:
                return requested
            alias_match = rid
    return alias_match if alias_match is not None else requested


def decode_routed_model_id_or_throw(requested: str, known: list[str]) -> str:
    matches = set()
    enc = encode_routed_model_id(requested)
    for rid in known:
        if rid == requested or encode_routed_model_id(rid) == enc:
            matches.add(rid)
    if len(matches) > 1:
        raise ModelRouteError(f'ambiguous model id "{requested}"')
    return decode_routed_model_id(requested, known)


class ModelRouteError(Exception):
    pass


class NoAvailableComboTargetsError(Exception):
    def __init__(self, combo_id):
        super().__init__(f"No available combo target for combo '{combo_id}'")


class NoEnabledOpenAiProviderError(Exception):
    pass


# --------------------------------------------------------------------------
# 默认实验配置（opencodex config.toml + catalog 的简化镜像）
# --------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "default_provider": "deepseek",
    "providers": {
        "openai": {
            "alias": "openai",
            "disabled": False,
            "default_model": "gpt-5.1-codex",
            "models": ["gpt-5.1-codex", "gpt-5", "o4-mini", "orcarouter/codex"],
        },
        "deepseek": {
            "alias": "deepseek",
            "disabled": False,
            "default_model": "deepseek-chat",
            "models": ["deepseek-chat", "deepseek-reasoner"],
            "aliases": {"ds-chat": "deepseek-chat", "ds-reason": "deepseek-reasoner"},
        },
        "openrouter": {
            "alias": "openrouter",
            "disabled": False,
            "default_model": "anthropic/claude-sonnet-4",
            # 原生 id 自带斜杠（如 anthropic/claude-...）会被编码成 - 对外
            "models": ["anthropic/claude-sonnet-4", "openai/gpt-5", "deepseek/deepseek-chat"],
            "aliases": {"claude-sonnet": "anthropic/claude-sonnet-4"},
        },
        "anthropic": {
            "alias": "anthropic",
            "disabled": True,
            "models": ["claude-sonnet-4", "claude-opus-4"],
        },
        "groq": {
            "alias": "groq",
            "disabled": False,
            "models": ["llama-3.3-70b", "mixtral-8x7b"],
        },
    },
    # 前缀模式路由（src/router.ts MODEL_PROVIDER_PATTERNS）
    "model_provider_patterns": [
        {"providers": ["anthropic"], "prefixes": ["claude-sonnet-", "claude-opus-", "claude-haiku-", "claude-"]},
        {"providers": ["groq"], "prefixes": ["llama-", "mixtral-", "gemma-"]},
    ],
    "combos": {
        "fs-combo": {
            "strategy": "round-robin",      # round-robin|random|least-used|reset-window|order
            "sticky_limit": 2,
            "cooldown_seconds": 8,
            "targets": [
                {"provider": "deepseek",   "model": "deepseek-chat",               "weight": 2},
                {"provider": "openrouter", "model": "anthropic/claude-sonnet-4",   "weight": 1},
                {"provider": "groq",       "model": "llama-3.3-70b",               "weight": 1},
            ],
        },
        "ds-alternate": {
            "strategy": "random",
            "sticky_limit": 1,
            "cooldown_seconds": 5,
            "targets": [
                {"provider": "deepseek",   "model": "deepseek-chat",     "weight": 3},
                {"provider": "deepseek",   "model": "deepseek-reasoner", "weight": 1},
                {"provider": "openrouter", "model": "deepseek/deepseek-chat", "weight": 1},
            ],
        },
    },
    # 模型名 -> combo：路由层"名字命中 combo"就进入组合（对应 tryPickComboModel）
    "combo_aliases": {
        "fs-test": "fs-combo",
        "ds-alternate": "ds-alternate",
    },
}


# --------------------------------------------------------------------------
# 会话状态（进程内，跑一次有效）
# --------------------------------------------------------------------------
class Sim:
    def __init__(self, config):
        self.config = config
        # 每个 combo 的选择状态：successes / active_key / current_weights / successful_uses
        self.selection = {}
        # 每个 combo 的冷却表：key -> 解除时刻
        self.cooldown = {}
        # 每个 provider 的模拟配额快照：{provider: exhausted(bool)}
        self.quota_exhausted = {}
        self.time = time.time

    # ---- 基础辅助 ----------------------------------------------------------
    def now(self):
        return self.time()

    def provider(self, name):
        return self.config["providers"].get(name)

    def active_providers(self):
        return [(n, p) for n, p in self.config["providers"].items() if p.get("disabled") is not True]

    def known_model_ids(self, prov_name):
        prov = self.provider(prov_name)
        if not prov:
            return []
        ids = set(prov.get("models", []))
        if prov.get("default_model"):
            ids.add(prov["default_model"])
        ids.update((prov.get("aliases") or {}).values())
        return list(ids)

    def get_combo(self, combo_id):
        return self.config["combos"].get(combo_id)

    def resolve_combo_id(self, model_id):
        return self.config["combo_aliases"].get(model_id)

    # ---- slug / 别名 -------------------------------------------------------
    def resolve_model_alias(self, prov_name, prov, requested):
        aliases = prov.get("aliases") or {}
        if requested in aliases:
            return aliases[requested]
        return None

    # -----------------------------------------------------------------------
    # combo 核心（与 src/combos/resolve.ts 对应）
    # -----------------------------------------------------------------------
    def combo_state(self, combo_id):
        st = self.selection.get(combo_id)
        if st is None:
            st = {"successes": 0, "active_key": None,
                  "current_weights": {}, "successful_uses": {}}
            self.selection[combo_id] = st
        return st

    def combo_key(self, t):
        return f"{t['provider']}/{t['model']}"

    def target_provider_is_usable(self, t):
        p = self.provider(t["provider"])
        return p is not None and p.get("disabled") is not True

    def provider_quota_exhausted(self, prov):
        return bool(self.quota_exhausted.get(prov))

    def in_cooldown(self, combo_id, key, now=None):
        until = self.cooldown.get((combo_id, key))
        return until is not None and until > (now if now is not None else self.now())

    def smooth_weighted_index(self, combo, state, eligible):
        """round-robin 平滑加权（对应 smoothWeightedIndex）。"""
        targets = combo["targets"]
        best, best_score, total = -1, -math.inf, 0.0
        for i, t in enumerate(targets):
            if not eligible(t):
                continue
            key = self.combo_key(t)
            score = state["current_weights"].get(key, 0) + t.get("weight", 1)
            state["current_weights"][key] = score
            total += t.get("weight", 1)
            if score > best_score:
                best, best_score = i, score
        if best >= 0:
            key = self.combo_key(targets[best])
            state["current_weights"][key] = state["current_weights"].get(key, 0) - total
        return best

    def reset_window_index(self, combo, eligible):
        """选配额重置时间最近的一个；无快照时按配置顺序兜底。"""
        selected, smallest = -1, math.inf
        for i, t in enumerate(combo["targets"]):
            if not eligible(t):
                continue
            rem = 0.0 if self.provider_quota_exhausted(t["provider"]) else math.inf
            if selected < 0 or rem < smallest:
                selected, smallest = i, rem
        return selected

    def pick_combo_target(self, combo_id, options=None):
        """对应 pickComboTarget(resolve.ts:141)。返回 ComboPick 或 None。"""
        options = options or {}
        combo = self.get_combo(combo_id)
        if not combo:
            raise KeyError(f"unknown combo {combo_id}")
        excluded = set(options.get("exclude", []))
        extra_eligible = options.get("eligible")
        now = options.get("now", self.now())

        def eligible(t):
            return (self.target_provider_is_usable(t)
                    and not self.provider_quota_exhausted(t["provider"])
                    and self.combo_key(t) not in excluded
                    and not self.in_cooldown(combo_id, self.combo_key(t), now)
                    and (extra_eligible(t) if extra_eligible else True))

        targets = combo["targets"]
        strategy = combo.get("strategy", "order")
        index = -1

        if strategy == "round-robin":
            state = self.combo_state(combo_id)
            if state["active_key"]:
                idx = next((i for i, t in enumerate(targets)
                            if self.combo_key(t) == state["active_key"] and eligible(t)), -1)
                if idx < 0:
                    state["active_key"] = None
                    state["successes"] = 0
                else:
                    index = idx
            if index < 0:
                index = self.smooth_weighted_index(combo, state, eligible)
                if index >= 0:
                    state["active_key"] = self.combo_key(targets[index])
                    state["successes"] = 0
        elif strategy == "random":
            pool = [i for i, t in enumerate(targets) if eligible(t)]
            if pool:
                total_w = sum(targets[i].get("weight", 1) for i in pool)
                r = self._rand() * total_w
                for i in pool:
                    r -= targets[i].get("weight", 1)
                    if r <= 0:
                        index = i
                        break
                if index < 0:
                    index = pool[-1]
        elif strategy == "least-used":
            state = self.combo_state(combo_id)
            fewest = math.inf
            for i, t in enumerate(targets):
                if not eligible(t):
                    continue
                uses = state["successful_uses"].get(self.combo_key(t), 0)
                if index < 0 or uses < fewest:
                    index, fewest = i, uses
        elif strategy == "reset-window":
            index = self.reset_window_index(combo, eligible)
        else:
            index = next((i for i, t in enumerate(targets) if eligible(t)), -1)

        if index < 0:
            return None
        t = targets[index]
        return {
            "combo_id": combo_id,
            "target": t,
            "target_index": index,
            "attempted": list(excluded) + [self.combo_key(t)],
            "strategy": strategy,
        }

    def note_combo_success(self, pick):
        combo = self.get_combo(pick["combo_id"])
        state = self.combo_state(pick["combo_id"])
        key = self.combo_key(pick["target"])
        if combo.get("strategy") == "least-used":
            state["successful_uses"][key] = state["successful_uses"].get(key, 0) + 1
            return
        if combo.get("strategy") != "round-robin":
            return
        if state["active_key"] != key:
            return
        state["successes"] += 1
        if state["successes"] >= combo.get("sticky_limit", 1):
            state["active_key"] = None
            state["successes"] = 0

    def note_combo_failure(self, pick):
        state = self.combo_state(pick["combo_id"])
        key = self.combo_key(pick["target"])
        if state["active_key"] == key:
            state["active_key"] = None
            state["successes"] = 0

    def cool_combo_target(self, combo_id, target, seconds=None):
        combo = self.get_combo(combo_id)
        dur = seconds if seconds is not None else combo.get("cooldown_seconds", 0)
        self.cooldown[(combo_id, self.combo_key(target))] = self.now() + dur

    def advance_combo_after_failure(self, pick, cooldown_scope=None):
        """对应 advanceComboAfterFailure(resolve.ts:272)。返回下一 ComboPick 或 None。"""
        self.note_combo_failure(pick)
        combo = self.get_combo(pick["combo_id"])
        if cooldown_scope == "provider" and combo:
            affected = [t for t in combo["targets"] if t["provider"] == pick["target"]["provider"]]
        else:
            affected = [pick["target"]]
        for t in affected:
            self.cool_combo_target(pick["combo_id"], t)
        return self.pick_combo_target(pick["combo_id"], {
            "exclude": pick["attempted"],
        })

    def try_pick_combo_model(self, model_id):
        combo_id = self.resolve_combo_id(model_id)
        if not combo_id:
            return None
        if not self.get_combo(combo_id):
            raise KeyError(f"unknown combo {combo_id}")
        picked = self.pick_combo_target(combo_id)
        if not picked:
            raise NoAvailableComboTargetsError(combo_id)
        return picked

    @staticmethod
    def _rand():
        # 便于可控复现：默认用内置随机；在脚本里测试时可 monkeypatch
        import random
        return random.random()

    # -----------------------------------------------------------------------
    # 路由核心（与 src/router.ts routeModelInternal 对应）
    # -----------------------------------------------------------------------
    def is_bare_openai_family(self, model_id):
        if "/" in model_id:
            return False
        if model_id in self.known_model_ids(OPENAI_CODEX_PROVIDER_ID):
            return True
        return (model_id.startswith("gpt-") or model_id.startswith("o1")
                or model_id.startswith("o3") or model_id.startswith("o4")
                or model_id.startswith("o5") or model_id.startswith("chatgpt-"))

    def route_by_pattern(self, model_id):
        for pat in self.config["model_provider_patterns"]:
            if any(model_id.startswith(p) for p in pat["prefixes"]):
                for name, prov in self.active_providers():
                    if name in pat["providers"] or any(
                            name.startswith(pn + "-") for pn in pat["providers"]):
                        return name
                return None
        return None

    def route(self, model_id, bypass_combos=False):
        """routeModelInternal：返回 {provider, model, reason, kind, combo?, trace}。"""
        trace = []
        slash = model_id.find("/")

        # 0) 显式 provider/model —— 前缀匹配到已配置 provider（或其 alias）才触发
        if slash > 0:
            head, rest = model_id[:slash], model_id[slash + 1:]
            prov_name = head if head in self.provider_self() else None
            if prov_name is None:
                for n, p in self.config["providers"].items():
                    if isinstance(p.get("alias"), str) and p["alias"].lower() == head.lower():
                        prov_name = n
                        break
            if prov_name is not None and self.provider(prov_name) is not None:
                prov = self.provider(prov_name)
                if prov.get("disabled") is True:
                    trace.append(f"1. 显式 provider/model: '{prov_name}' 已禁用 -> 抛错")
                    raise ModelRouteError(f"Provider is disabled: {prov_name}")
                known = self.known_model_ids(prov_name)
                if model_id in known:
                    trace.append(f"1. 显式 provider/model: 整串 '{model_id}' 本身是已知模型 -> 原样路由")
                    return {"provider": prov_name, "model": model_id,
                            "reason": "explicit-provider-namespace", "kind": "explicit", "trace": trace}
                requested = rest
                try:
                    decoded = decode_routed_model_id_or_throw(requested, known)
                except ModelRouteError as e:
                    trace.append(f"1. 显式 provider/model: 解码冲突 {e}")
                    raise
                native = decoded if decoded in known else (
                    self.resolve_model_alias(prov_name, prov, requested) or decoded)
                trace.append(f"1. 显式 provider/model: 前缀'{head}'匹配 provider '{prov_name}', "
                             f"解码 '{requested}' -> 原生 '{native}'")
                return {"provider": prov_name, "model": native,
                        "reason": "explicit-provider-namespace", "kind": "explicit", "trace": trace}

        # combo 别名（在 provider 之前；开 preservesPhysical 则跳过）
        if not bypass_combos:
            combo_id = self.resolve_combo_id(model_id)
            if combo_id:
                picked = self.pick_combo_target(combo_id)
                if not picked:
                    raise NoAvailableComboTargetsError(combo_id)
                concrete = routed_slug(picked["target"]["provider"], picked["target"]["model"])
                trace.append(f"2. combo: '{model_id}' -> combo '{combo_id}' "
                             f"({picked['strategy']}) 选中 index {picked['target_index']} "
                             f"{picked['target']['provider']}/{picked['target']['model']}; "
                             f"active_key={self.combo_state(combo_id)['active_key']}")
                inner = self.route(concrete, bypass_combos=True)
                inner = dict(inner)
                inner["combo"] = picked
                inner["kind"] = "combo"
                inner["reason"] = "combo-pick"
                inner["trace"] = trace + inner.get("trace", [])
                return inner

        # 裸 OpenAI 家族模型 -> 固定 openai
        if self.is_bare_openai_family(model_id):
            p = self.provider(OPENAI_CODEX_PROVIDER_ID)
            if p and p.get("disabled") is not True:
                trace.append(f"3. 裸 OpenAI 家族: '{model_id}' -> openai (native-family)，不可被第三方劫持")
                return {"provider": OPENAI_CODEX_PROVIDER_ID, "model": model_id,
                        "reason": "native-family", "kind": "native", "trace": trace}
            raise NoEnabledOpenAiProviderError(model_id)

        # 各 provider defaultModel
        for n, prov in self.active_providers():
            dm = prov.get("default_model")
            if dm and (dm == model_id or encode_routed_model_id(dm) == model_id):
                trace.append(f"4. defaultModel 命中: '{model_id}' == {n}.default_model")
                return {"provider": n, "model": dm,
                        "reason": "configured-default-model", "kind": "explicit", "trace": trace}

        # 前缀模式
        pat_prov = self.route_by_pattern(model_id)
        if pat_prov:
            trace.append(f"5. 前缀模式命中 '{model_id}' -> provider '{pat_prov}'")
            return {"provider": pat_prov, "model": model_id,
                    "reason": "model-pattern", "kind": "explicit", "trace": trace}

        # models 列表
        for n, prov in self.active_providers():
            for mid in prov.get("models", []):
                if mid == model_id or encode_routed_model_id(mid) == model_id:
                    trace.append(f"6. models 列表命中: '{model_id}' 在 {n}.models")
                    return {"provider": n, "model": mid,
                            "reason": "configured-model-list", "kind": "explicit", "trace": trace}

        # 别名（ambiguity 抛错）
        alias_matches = []
        for n, prov in self.active_providers():
            known = self.known_model_ids(n)
            native = self.resolve_model_alias(n, prov, model_id)
            if native:
                alias_matches.append((n, native))
        if len(alias_matches) > 1:
            raise ModelRouteError(f"model alias '{model_id}' is ambiguous")
        if alias_matches:
            n, native = alias_matches[0]
            trace.append(f"7. 别名命中 '{model_id}' -> {n}.{native}")
            return {"provider": n, "model": native,
                    "reason": "model-alias", "kind": "explicit", "trace": trace}

        # 兜底 default_provider
        dp = self.config.get("default_provider")
        prov = self.provider(dp)
        if prov and prov.get("disabled") is not True:
            trace.append(f"8. 兜底 default_provider: '{model_id}' -> {dp}")
            return {"provider": dp, "model": model_id,
                    "reason": "default-provider", "kind": "default", "trace": trace}
        raise ModelRouteError(f"No provider configured for model: {model_id}")

    def provider_self(self):
        return set(self.config["providers"].keys())


# --------------------------------------------------------------------------
# 交互层
# --------------------------------------------------------------------------
HELP = """
命令（大小写不敏感）：
  providers                         列出所有 provider（含 disabled 状态）
  models                            列出各 provider 的已知模型 / 别名
  combos                            列出 combo 及目标、当前 active/成功计数
  resolve <modelId>                 走一遍路由判定，打印命中路径 (不会消耗 combo)
  disable <provider>                禁用 provider（观察其退出候选）
  enable <provider>                 启用 provider
  exhaust <provider>                把 provider 配额标记为"耗尽"（测试配额型 failover）
  credit <provider>                 取消其配额耗尽标记
  sim <comboAlias>                  对某个 combo 做逐步 failover 演练
  run <comboAlias> <n> [failEvery]  连续请求 n 次；每 failEvery 次强制失败一次
  cooldown                          显示当前冷却表
  dump                              打印当前进程内状态(JSON)
  help / quit / exit
"""


def pretty_route(res):
    kind = res.get("kind")
    combo = res.get("combo")
    lines = ["[ 决策链 ]"]
    lines += [f"  {t}" for t in res["trace"]]
    if combo:
        lines.append(f"[ 结果 ] combo={combo['combo_id']} strategy={combo['strategy']} "
                     f"target={combo['target']['provider']}/{combo['target']['model']} "
                     f"(index={combo['target_index']})")
    lines.append(f"[ 落地 ] {res['provider']} / {res['model']}   "
                 f"reason={res.get('reason')} kind={kind}")
    return "\n".join(lines)


def do_sim(sim, combo_id):
    combo = sim.get_combo(combo_id)
    if not combo:
        print(f"未知 combo: {combo_id}")
        return
    print(f"演练 combo '{combo_id}'  (strategy={combo['strategy']}, "
          f"sticky_limit={combo.get('sticky_limit')}, cooldown={combo.get('cooldown_seconds')}s)")
    print("对每个选中目标，输入:  succ | fail | fail-provider | quota | exit")
    step = 0
    while True:
        step += 1
        try:
            pick = sim.pick_combo_target(combo_id)
        except Exception as e:
            print(f"  -> 无可选目标（冷却/配额/禁用全部排除后）: {e}")
            break
        if not pick:
            print(f"  step{step}: NoAvailableComboTargets —— 所有 target 都不可用/被冷却")
            break
        st = sim.combo_state(combo_id)
        state_str = (f"active={st['active_key'] or '-'} successes={st['successes']}"
                     f" weights={ {k: round(v,2) for k,v in st['current_weights'].items()} }")
        print(f"  step{step}: 选中 -> {pick['target']['provider']}/{pick['target']['model']}   [{state_str}]")
        # 展示候选资格
        for i, t in enumerate(combo["targets"]):
            usable = sim.target_provider_is_usable(t)
            quota = not sim.provider_quota_exhausted(t["provider"])
            cd = not sim.in_cooldown(combo_id, sim.combo_key(t))
            mark = "" if (usable and quota and cd) else "  <-- 排除"
            print(f"        target{i}: {t['provider']}/{t['model']} "
                  f"(usable={usable}, quota={quota}, cooldown_ok={cd}){mark}")
        act = input("  succ / fail / fail-provider / quota / exit > ").strip().lower()
        if act in ("q", "quit", "exit"):
            break
        elif act in ("succ", "s"):
            sim.note_combo_success(pick)
            print(f"    记成功 -> {state_str}")
        elif act in ("fail", "f"):
            nxt = sim.advance_combo_after_failure(pick)
            print(f"    记失败 -> 冷却 {pick['target']['provider']}, 排重后重选:")
            if nxt:
                print(f"      切到 {nxt['target']['provider']}/{nxt['target']['model']} "
                      f"(attempted={nxt['attempted']})")
            else:
                print("      无可切换目标")
        elif act == "fail-provider":
            nxt = sim.advance_combo_after_failure(pick, cooldown_scope="provider")
            print(f"    记失败(provider 级冷却) -> 冷却该 provider 全部目标:")
            print(f"      {[t['provider']+'/'+t['model'] for t in combo['targets'] if t['provider']==pick['target']['provider']]}")
            if nxt:
                print(f"      切到 {nxt['target']['provider']}/{nxt['target']['model']}")
            else:
                print("      无可切换目标")
        elif act in ("quota", "q2"):
            sim.quota_exhausted[pick["target"]["provider"]] = True
            nxt = sim.pick_combo_target(combo_id)
            print(f"    标记 {pick['target']['provider']} 配额耗尽, 重新 pick:")
            if nxt:
                print(f"      切到 {nxt['target']['provider']}/{nxt['target']['model']}")
            else:
                print("      无可切换目标")
        else:
            print("    未识别，忽略")


def do_run(sim, combo_id, n, fail_every=0):
    combo = sim.get_combo(combo_id)
    if not combo:
        print(f"未知 combo: {combo_id}")
        return
    cur = None
    for i in range(1, n + 1):
        if cur is None:
            try:
                cur = sim.pick_combo_target(combo_id)
            except NoAvailableComboTargetsError as e:
                print(f"req{i}: NoAvailableComboTargets {e}")
                return
        if not cur:
            print(f"req{i}: 无可选目标")
            return
        t = cur["target"]
        force_fail = fail_every and (i % fail_every == 0)
        if force_fail:
            print(f"req{i}: [强制失败] {t['provider']}/{t['model']}", end=" -> ")
            cur = sim.advance_combo_after_failure(cur)
            print(f"切换 -> {cur['target']['provider']}/{cur['target']['model']}" if cur else "无目标")
        else:
            print(f"req{i}: [成功] {t['provider']}/{t['model']}")
            sim.note_combo_success(cur)
            if sim.combo_state(combo_id)["active_key"] is None and combo.get("strategy") == "round-robin":
                # sticky 达标后释放，下轮重新轮询
                cur = None
            else:
                cur = cur


def repl(sim):
    print("opencodex 路由/combo 仿真器 —— 输入 help 查看命令。")
    while True:
        try:
            raw = input("ocx-sim> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not raw:
            continue
        parts = raw.split()
        cmd, args = parts[0].lower(), parts[1:]
        try:
            if cmd in ("help", "h", "?"):
                print(HELP)
            elif cmd in ("quit", "exit", "q"):
                break
            elif cmd == "providers":
                for n, p in sim.config["providers"].items():
                    print(f"  {n:12} disabled={p.get('disabled') is True}  "
                          f"alias={p.get('alias')}  default={p.get('default_model')}")
            elif cmd == "models":
                for n, p in sim.config["providers"].items():
                    print(f"[{n}] disabled={p.get('disabled') is True}")
                    for m in sim.known_model_ids(n):
                        print(f"    {m}")
                    if p.get("aliases"):
                        print(f"    aliases: {p['aliases']}")
            elif cmd == "combos":
                for cid, c in sim.config["combos"].items():
                    st = sim.combo_state(cid)
                    print(f"[{cid}] strategy={c['strategy']} sticky={c.get('sticky_limit')} "
                          f"cooldown={c.get('cooldown_seconds')}s")
                    print(f"    active={st['active_key'] or '-'} successes={st['successes']}")
                    for i, t in enumerate(c["targets"]):
                        print(f"    target{i}: {t['provider']}/{t['model']} weight={t.get('weight',1)}")
                aliases = sim.config.get("combo_aliases", {})
                if aliases:
                    print("  aliases:", json.dumps(aliases))
            elif cmd == "resolve":
                if not args:
                    print("用法: resolve <modelId>")
                    continue
                r = sim.route(args[0])
                print(pretty_route(r))
            elif cmd == "disable":
                if args and args[0] in sim.config["providers"]:
                    sim.config["providers"][args[0]]["disabled"] = True
                    print(f"已禁用 {args[0]}")
                else:
                    print(f"未知 provider: {args[0] if args else ''}")
            elif cmd == "enable":
                if args and args[0] in sim.config["providers"]:
                    sim.config["providers"][args[0]]["disabled"] = False
                    print(f"已启用 {args[0]}")
            elif cmd == "exhaust":
                if args and args[0] in sim.config["providers"]:
                    sim.quota_exhausted[args[0]] = True
                    print(f"{args[0]} 配额标记为耗尽")
            elif cmd == "credit":
                sim.quota_exhausted.pop(args[0], None) if args else None
                print(f"{args[0]} 配额恢复" if args else "")
            elif cmd in ("sim", "run"):
                if not args:
                    print("用法: sim <comboAlias>   或   run <comboAlias> <n> [failEvery]")
                    continue
                combo_id = sim.config["combo_aliases"].get(args[0], args[0])
                if cmd == "sim":
                    do_sim(sim, combo_id)
                else:
                    n = int(args[1]) if len(args) > 1 else 5
                    fe = int(args[2]) if len(args) > 2 else 0
                    do_run(sim, combo_id, n, fe)
            elif cmd == "cooldown":
                if not sim.cooldown:
                    print("  (无冷却项)")
                for (cid, key), until in sim.cooldown.items():
                    left = max(0, until - sim.now())
                    print(f"  combo={cid} target={key} 剩余 {left:.0f}s")
            elif cmd == "dump":
                print(json.dumps({
                    "selection": {k: {kk: vv for kk, vv in v.items()
                                      if kk != "current_weights"}
                                  for k, v in sim.selection.items()},
                    "quota_exhausted": sim.quota_exhausted,
                    "cooldown_keys": list(sim.cooldown.keys()),
                }, ensure_ascii=False, indent=2))
            else:
                print(f"未知命令: {cmd}  (help)")
        except (ModelRouteError, NoAvailableComboTargetsError,
                NoEnabledOpenAiProviderError, KeyError) as e:
            print(f"  !! {e}")


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main(argv):
    cfg_path = None
    args = list(argv)
    if args and args[0] == "--config":
        cfg_path = args[1]
        args = args[2:]
    config = load_config(cfg_path) if cfg_path else json.loads(json.dumps(DEFAULT_CONFIG))
    sim = Sim(config)

    # 支持脚本式的确定性随机（用于 run 复现；默认无需）
    def _rand():
        import random
        return random.random()
    sim._rand = _rand

    if not args:
        repl(sim)
        return
    cmd = args[0].lower()
    if cmd == "resolve" and len(args) > 1:
        print(pretty_route(sim.route(args[1])))
    elif cmd in ("sim", "run") and len(args) > 1:
        combo_id = sim.config["combo_aliases"].get(args[1], args[1])
        if cmd == "sim":
            do_sim(sim, combo_id)
        else:
            n = int(args[2]) if len(args) > 2 else 5
            fe = int(args[3]) if len(args) > 3 else 0
            do_run(sim, combo_id, n, fe)
    elif cmd == "dump":
        print(json.dumps(config, ensure_ascii=False, indent=2))
    else:
        print(HELP)


if __name__ == "__main__":
    # 让交互输入在双击(LaunchServices)时也有行缓冲
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        main(sys.argv[1:])
    except KeyboardInterrupt:
        print("\nbye")
