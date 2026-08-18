#!/usr/bin/env python3
"""Claude Code statusline — две строки, разбитые на колонки.

  📁 kad_reserv_v2        ⏳ 5h █░░░░░░░░░ 8% (2h 17m)         🧠 ctx █████████░░░░░░░░░░░░░░░░░░░░░ 45% (134k/300k)   💰 $1.23
  ⚡ Opus 5 (1M · high)   (cache 99% · in 0% · out 1%)         | base 10% · 30k | hist 35% · 104k | free 55% · 166k

Колонка = пара «сверху/снизу», обе строки выравниваются по ширине колонки:

  проект   / модель (окно модели · effort)
  лимит 5h / из чего состоял последний запрос
  контекст / разбор контекстного бара
  деньги   / —

Бар контекста — общий на весь порог автокомпакта, разбитый по цветам:

  base (синий)  — несжимаемое: системный промпт, инструменты, CLAUDE.md, скиллы
  hist (зелёный → жёлтый → красный по мере заполнения) — сам диалог
  free (серый)  — сколько осталось до автокомпакта

«base» оценивается по первому ответу модели в текущем транскрипте.
Цвет бара и процента: зелёный < 50%, жёлтый 50–79%, красный ≥ 80%.
Время до сброса — голубым, чтобы отличалось от процентов.
"""
import json
import os
import re
import sys
import time
import unicodedata

ANSI_RE = re.compile(r"\033\[[0-9;]*m")

R = "\033[0m"
BOLD = "\033[1m"


def fg(r, g, b):
    return f"\033[38;2;{r};{g};{b}m"


C_PROJECT = fg(97, 175, 239)   # синий — имя проекта
C_MODEL = fg(198, 120, 221)    # фиолетовый — модель
C_GREY = fg(110, 115, 125)     # подписи и второстепенное
C_TIME = fg(86, 182, 194)      # голубой — время до сброса
C_COST = fg(229, 192, 123)     # янтарный — деньги
C_OK = fg(152, 195, 121)
C_WARN = fg(229, 192, 123)
C_BAD = fg(224, 108, 117)

C_BASE = fg(97, 175, 239)      # синий — несжимаемая база контекста
C_FREE = fg(75, 80, 90)        # тёмно-серый — свободное место

BAR_W = 20                     # бары лимитов 5h / 7d
CTX_BAR_W = 30                 # бар контекста
SEP = "     "

CACHE_DIR = os.path.expanduser("~/.claude/cache")
SETTINGS = os.path.expanduser("~/.claude/settings.json")


# --------------------------------------------------------------------------- #
#  утилиты
# --------------------------------------------------------------------------- #

def vis_width(s):
    """Ширина строки в колонках терминала: без ANSI, эмодзи считаем за две."""
    s = ANSI_RE.sub("", s)
    w = 0
    for ch in s:
        if unicodedata.combining(ch):
            continue
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def pad_to(s, width):
    return s + " " * max(width - vis_width(s), 0)


def justify(items, width):
    """Растягиваем пункты до нужной ширины, раздвигая разделители «|»."""
    if not items:
        return ""
    gaps = len(items) - 1
    if gaps <= 0:
        return items[0]
    plain = sum(vis_width(i) for i in items)
    extra = max(width - plain - gaps * 3, 0)        # 3 = " | " минимальный зазор
    out = items[0]
    for idx, item in enumerate(items[1:]):
        add = extra // gaps + (1 if idx < extra % gaps else 0)
        left, right = 1 + (add + 1) // 2, 1 + add // 2
        out += " " * left + f"{C_GREY}|{R}" + " " * right + item
    return out


def fmt_tokens(n):
    if n is None:
        return "?"
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 10_000:
        return f"{n / 1000:.0f}k"
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def fmt_window(n):
    """Размер окна модели покороче: 1M, 200k."""
    if not n:
        return None
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:g}M"
    return f"{n // 1000}k"


def fmt_remaining(resets_at):
    try:
        rem = int(resets_at) - int(time.time())
    except (TypeError, ValueError):
        return None
    if rem <= 0:
        return "now"
    d, rem2 = divmod(rem, 86400)
    h, rem2 = divmod(rem2, 3600)
    m = rem2 // 60
    if d > 0:
        return f"{d}d {h}h"
    if h > 0:
        return f"{h}h {m:02d}m"
    return f"{m} min"


MODEL_WINDOW_RE = re.compile(
    r"\s*\((?:[^)]*\b(?:context|tokens?)\b[^)]*|[\d.]+\s*[MmKk])\)\s*$")


def model_name(display_name):
    """«Opus 5 (1M context)» → «Opus 5»: размер окна дорисуем сами."""
    return MODEL_WINDOW_RE.sub("", display_name).strip() or display_name


def usage_color(pct):
    if pct is None:
        return C_GREY
    if pct >= 80:
        return C_BAD
    if pct >= 50:
        return C_WARN
    return C_OK


def bar(pct):
    if pct is None:
        return f"{C_GREY}{'░' * BAR_W}{R}"
    pct = max(0.0, min(100.0, float(pct)))
    filled = round(pct / 100 * BAR_W)
    return f"{usage_color(pct)}{'█' * filled}{C_GREY}{'░' * (BAR_W - filled)}{R}"


# --------------------------------------------------------------------------- #
#  контекст
# --------------------------------------------------------------------------- #

def compact_window(fallback):
    """Порог автокомпакта из settings.json — реальный потолок контекста."""
    try:
        with open(SETTINGS) as fh:
            s = json.load(fh)
        if s.get("autoCompactEnabled") is False:
            return fallback
        win = s.get("autoCompactWindow")
        if win and fallback:
            return min(int(win), int(fallback))
        return int(win) if win else fallback
    except Exception:
        return fallback


def baseline_tokens(transcript_path, session_id):
    """Несжимаемая база: контекст на первом ответе модели в сессии.

    Это системный промпт + описания инструментов + CLAUDE.md + скиллы.
    Результат кэшируем — транскрипт может быть на десятки мегабайт.
    """
    if not transcript_path or not os.path.isfile(transcript_path):
        return None
    cache_file = os.path.join(CACHE_DIR, f"statusline-base-{session_id or 'x'}")
    try:
        with open(cache_file) as fh:
            return int(fh.read().strip())
    except Exception:
        pass
    base = None
    try:
        with open(transcript_path, errors="replace") as fh:
            for i, line in enumerate(fh):
                if i > 400:
                    break
                if '"usage"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("type") != "assistant":
                    continue
                u = (d.get("message") or {}).get("usage") or {}
                if not u:
                    continue
                base = (u.get("input_tokens", 0)
                        + u.get("cache_creation_input_tokens", 0)
                        + u.get("cache_read_input_tokens", 0))
                break
    except Exception:
        return None
    if base:
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(cache_file, "w") as fh:
                fh.write(str(base))
        except Exception:
            pass
    return base


def stacked_ctx(base, history, limit):
    """Бар на весь порог автокомпакта: base | hist | free + его расшифровка."""
    used = base + history
    hist_color = usage_color(100.0 * used / limit)

    def cells(value):
        if value <= 0:
            return 0
        return max(1, round(value / limit * CTX_BAR_W))

    n_base = cells(base)
    n_hist = cells(history)
    if n_base + n_hist > CTX_BAR_W:                 # не вылезаем за ширину бара
        n_hist = max(0, CTX_BAR_W - n_base)
        n_base = min(n_base, CTX_BAR_W)
    n_free = CTX_BAR_W - n_base - n_hist

    bar_s = (f"{C_BASE}{'█' * n_base}"
             f"{hist_color}{'█' * n_hist}"
             f"{C_FREE}{'░' * n_free}{R}")

    free = max(limit - used, 0)
    segments = [("hist", history, hist_color), ("free", free, C_FREE)]
    if base:                                        # база неизвестна — не врём про 0%
        segments.insert(0, ("base", base, C_BASE))
    items = [
        f"{color}{BOLD}{label} {value / limit * 100:.0f}%{R}"
        f" {C_GREY}·{R} {C_GREY}{fmt_tokens(value)}{R}"
        for label, value, color in segments
    ]
    return bar_s, items


# --------------------------------------------------------------------------- #
#  сборка строк
# --------------------------------------------------------------------------- #

def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}

    columns = []          # [(верх, низ), ...]
    cw = data.get("context_window") or {}

    # --- проект / модель ---
    proj = (data.get("workspace") or {}).get("project_dir") or data.get("cwd") or ""
    top = f"📁 {C_PROJECT}{BOLD}{os.path.basename(proj)}{R}" if proj else ""

    model = (data.get("model") or {}).get("display_name")
    bottom = ""
    if model:
        tags = [t for t in (fmt_window(cw.get("context_window_size")),
                            (data.get("effort") or {}).get("level"),
                            "fast" if data.get("fast_mode") else None) if t]
        bottom = f"⚡ {C_MODEL}{model_name(model)}{R}"
        if tags:
            bottom += f" {C_GREY}({' · '.join(tags)}){R}"
    if top or bottom:
        columns.append((top, bottom))

    # --- лимиты: 5h сверху, 7d снизу ---
    rl = data.get("rate_limits") or {}

    def limit_cell(key, icon, label):
        win = rl.get(key) or {}
        upct = win.get("used_percentage")
        if upct is None:
            return ""
        cell = (f"{icon} {C_GREY}{label}{R} {bar(upct)} "
                f"{usage_color(upct)}{BOLD}{upct:.0f}%{R}")
        rem = fmt_remaining(win.get("resets_at"))
        if rem:
            cell += f" {C_GREY}({R}{C_TIME}{rem}{R}{C_GREY}){R}"
        return cell

    top = limit_cell("five_hour", "⏳", "5h")
    bottom = limit_cell("seven_day", "📅", "7d")
    if top or bottom:
        columns.append((top, bottom))

    # --- контекст: меряем до порога автокомпакта, а не до окна модели ---
    total_in = cw.get("total_input_tokens")
    limit = compact_window(cw.get("context_window_size"))
    if total_in is not None and limit:
        pct = 100.0 * total_in / limit
        base = min(int(baseline_tokens(data.get("transcript_path"),
                                       data.get("session_id")) or 0), int(total_in))
        bar_s, items = stacked_ctx(base, max(int(total_in) - base, 0), int(limit))
        top = (f"🧠 {C_GREY}ctx{R} {bar_s} {usage_color(pct)}{BOLD}{pct:.0f}%{R} "
               f"{C_GREY}({fmt_tokens(total_in)}/{fmt_tokens(limit)}){R}")
        # разбор внизу растягиваем ровно на ширину строки контекста сверху
        columns.append((top, justify(items, vis_width(top))))

    # --- деньги: в самом конце первой строки ---
    cost = (data.get("cost") or {}).get("total_cost_usd")
    if cost:
        columns.append((f"💰 {C_COST}${cost:.2f}{R}", ""))

    tops, bottoms = [], []
    for top, bottom in columns:
        width = max(vis_width(top), vis_width(bottom))
        tops.append(pad_to(top, width))
        bottoms.append(pad_to(bottom, width))

    line1 = SEP.join(tops).rstrip()
    line2 = SEP.join(bottoms).rstrip()
    sys.stdout.write(line1 + ("\n" + line2 if line2.strip() else ""))


if __name__ == "__main__":
    main()
