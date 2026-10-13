#!/usr/bin/env python3
"""
Minecraft contribution graph generator.

Steve mines through your GitHub contribution graph (coal -> iron -> gold -> diamond),
a Creeper chases him, and blows up at the end of the loop. Pure stdlib, outputs
animated SVGs (SMIL) that work inside a GitHub README <img>.

Env vars:
  GH_USER        GitHub username (or pass as argv[1])
  GITHUB_TOKEN   token for the GraphQL API (omit + set DEMO=1 for fake data)
  OUT_DIR        output folder (default: dist)
  STEP_SECONDS   seconds Steve spends per block (default: 0.09)
"""
import html
import json
import os
import random
import sys
import urllib.request
from collections import Counter
from pathlib import Path

USER = os.environ.get("GH_USER") or (sys.argv[1] if len(sys.argv) > 1 else "steve")
TOKEN = os.environ.get("GITHUB_TOKEN")
DEMO = os.environ.get("DEMO") == "1" or not TOKEN
OUT = Path(os.environ.get("OUT_DIR", "dist"))
STEP = float(os.environ.get("STEP_SECONDS", "0.09"))

CELL, GAP, PX = 16, 2, 2          # block size, gap, texture pixel size
PITCH = CELL + GAP
M = 24                            # outer margin
GY = 52                           # grid top
CHASE = 9                         # how many blocks the Creeper trails Steve by
EXTRA = 8                         # idle steps after the explosion before reset

LEVELS = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2,
          "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}
ORES = {  # level -> (name, ore colours)
    1: ("Coal",    ["#1c1c1c", "#2b2b2b", "#111111"]),
    2: ("Iron",    ["#d8af93", "#c49a7c", "#e8c8b0"]),
    3: ("Gold",    ["#fcee4b", "#e8c500", "#fff7a0"]),
    4: ("Diamond", ["#5decf5", "#2bc4d0", "#b8fbff"]),
}
STONE = ["#7d7d7d", "#8a8a8a", "#6f6f6f", "#777777", "#848484"]

THEMES = {
    "light": dict(bg="#ffffff", border="#d0d7de", empty="#e4e8ed",
                  text="#24292f", shadow="#c9d1d9", slot="#c6c6c6", slot_edge="#555555"),
    "dark":  dict(bg="#0d1117", border="#30363d", empty="#1b222c",
                  text="#e6edf3", shadow="#000000", slot="#3a3f47", slot_edge="#8b949e"),
}

STEVE = [
    ".hhhhhh.", ".hhhhhh.", ".ssssss.", ".sWBBWs.",
    ".ssnnss.", "..tttt..", "ssttttss", "ssttttss", "ssttttss",
    "..pp.pp.", "..pp.pp.", "..bb.bb.",
]
STEVE_PAL = {"h": "#4a2f1a", "s": "#c68f6b", "W": "#ffffff", "B": "#3b3bb8",
             "n": "#8a5a3c", "t": "#00a8a8", "p": "#3c44aa", "b": "#555555"}
CREEPER = [
    "GGgGGgGG", "GddGGddG", "GddGGddG", "gGGddGGG", "GGddddGG", "GGddddGg",
    "..GGgG..", "..gGGG..", "..GGGg..", "GGg..gGG", "GGG..GGG", "gGG..GGg",
]
CREEPER_PAL = {"G": "#4caf50", "g": "#2e7d32", "d": "#101010"}
HEART = [".rr.rr.", "rwrrrrr", "rrrrrrr", ".rrrrr.", "..rrr..", "...r..."]
HEART_PAL = {"r": "#d81e1e", "w": "#ff8a8a"}


# ---------------------------------------------------------------- data
def fetch(user, token):
    q = ("query($login:String!){user(login:$login){contributionsCollection{"
         "contributionCalendar{totalContributions weeks{contributionDays{"
         "contributionCount contributionLevel weekday}}}}}}")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": q, "variables": {"login": user}}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json",
                 "User-Agent": "minecraft-contrib-snake"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    if data.get("errors") or not data["data"]["user"]:
        sys.exit(f"GraphQL error: {data.get('errors') or 'user not found'}")
    cal = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    return cal["totalContributions"], cal["weeks"]


def demo_data():
    rnd = random.Random(7)
    names = list(LEVELS)
    weeks, total = [], 0
    for w in range(53):
        days = []
        for d in range(7):
            if w == 52 and d > 3:
                break
            lvl = rnd.choices(names, weights=[40, 25, 18, 10, 7])[0]
            c = LEVELS[lvl] * rnd.randint(1, 4)
            total += c
            days.append({"weekday": d, "contributionLevel": lvl, "contributionCount": c})
        weeks.append({"contributionDays": days})
    return total, weeks


# ---------------------------------------------------------------- drawing helpers
def fr(t, steps):
    """time fraction (0..1) of step t"""
    return t / steps


def f(x):
    return f"{x:.5f}".rstrip("0").rstrip(".") or "0"


def sprite(rows, pal, px=PX):
    out = []
    for y, row in enumerate(rows):
        x = 0
        while x < len(row):
            c = row[x]
            if c == ".":
                x += 1
                continue
            x2 = x
            while x2 < len(row) and row[x2] == c:
                x2 += 1
            out.append(f'<rect x="{x*px}" y="{y*px}" width="{(x2-x)*px}" height="{px}" fill="{pal[c]}"/>')
            x = x2
    return "".join(out)


def block_symbol(level):
    rnd = random.Random(level * 101)
    pix = [[rnd.choice(STONE) for _ in range(8)] for _ in range(8)]
    if level:
        _, cols = ORES[level]
        for _ in range(4):  # ore clusters
            cx, cy = rnd.randint(1, 6), rnd.randint(1, 6)
            for dx, dy in [(0, 0), (1, 0), (0, 1), (1, 1)][: rnd.randint(2, 4)]:
                if cx + dx < 8 and cy + dy < 8:
                    pix[cy + dy][cx + dx] = rnd.choice(cols)
    rects = "".join(f'<rect x="{x*PX}" y="{y*PX}" width="{PX}" height="{PX}" fill="{pix[y][x]}"/>'
                    for y in range(8) for x in range(8))
    edge = f'<rect x=".5" y=".5" width="{CELL-1}" height="{CELL-1}" fill="none" stroke="#000" stroke-opacity=".4"/>'
    return f'<g id="b{level}">{rects}{edge}</g>'


def opacity_anim(a, b, eps, dur):
    """visible -> hidden at a -> visible again fading in between b and the loop end"""
    return (f'<animate attributeName="opacity" values="1;1;0;0;1" '
            f'keyTimes="0;{f(a)};{f(a+eps)};{f(b)};1" dur="{dur:.2f}s" repeatCount="indefinite"/>')


def text(x, y, s, size, fill, shadow, anchor="start"):
    s = html.escape(str(s))
    base = (f'font-family="\'Courier New\',monospace" font-weight="700" '
            f'font-size="{size}" text-anchor="{anchor}"')
    return (f'<text x="{x+1}" y="{y+1}" {base} fill="{shadow}">{s}</text>'
            f'<text x="{x}" y="{y}" {base} fill="{fill}">{s}</text>')


# ---------------------------------------------------------------- build
def build(theme_name, total, weeks):
    th = THEMES[theme_name]
    grid = {(w, d["weekday"]): LEVELS[d["contributionLevel"]]
            for w, wk in enumerate(weeks) for d in wk["contributionDays"]}
    nweeks = len(weeks)

    # serpentine path, column by column
    path = []
    for w in range(nweeks):
        ds = [d for d in range(7) if (w, d) in grid]
        if w % 2:
            ds.reverse()
        path += [(w, d) for d in ds]
    n = len(path)

    S = n + CHASE + EXTRA          # total timeline steps
    steps = S - 1
    dur = steps * STEP
    te = n - 1 + CHASE             # explosion step
    eps = fr(0.2, steps)
    back = fr(steps - 2, steps)    # reset begins here

    W = 2 * M + nweeks * PITCH - GAP
    H = GY + 7 * PITCH + 100
    counts = Counter(v for v in grid.values() if v)

    def cell_xy(w, d):
        return M + w * PITCH, GY + d * PITCH

    def sprite_pos(w, d):
        x, y = cell_xy(w, d)
        return x + CELL / 2 - 8, y + CELL - 22

    o = []
    o.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
             f'role="img" aria-label="Minecraft contribution graph for {html.escape(USER)}">')
    o.append(f'<title>{html.escape(USER)}\'s contribution cave</title>')
    o.append('<defs>' + "".join(block_symbol(l) for l in range(5)) + '</defs>')
    o.append(f'<rect width="{W}" height="{H}" rx="12" fill="{th["bg"]}" stroke="{th["border"]}"/>')
    o.append(text(M, 32, f"{USER}'s Contribution Cave", 16, th["text"], th["shadow"]))
    o.append(text(W - M, 32, f"{total} blocks mined this year", 12, th["text"], th["shadow"], "end"))

    # blocks
    order = {p: i for i, p in enumerate(path)}
    for (w, d), lvl in sorted(grid.items()):
        x, y = cell_xy(w, d)
        if lvl == 0:
            o.append(f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2" fill="{th["empty"]}"/>')
            continue
        i = order[(w, d)]
        a = fr(i + 0.3, steps)
        o.append(f'<use href="#b{lvl}" x="{x}" y="{y}">{opacity_anim(a, back, eps, dur)}</use>')
        # mining flash
        k = fr(0.6, steps)
        o.append(f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" fill="#fff" opacity="0">'
                 f'<animate attributeName="opacity" values="0;0;.85;0;0" '
                 f'keyTimes="0;{f(a)};{f(a+k/2)};{f(a+k*2)};1" dur="{dur:.2f}s" repeatCount="indefinite"/></rect>')

    # Steve
    sv = ";".join("{:.1f} {:.1f}".format(*sprite_pos(*path[min(t, n - 1)])) for t in range(S))
    o.append(
        '<g>'
        f'<animateTransform attributeName="transform" type="translate" values="{sv}" '
        f'dur="{dur:.2f}s" repeatCount="indefinite"/>'
        f'{opacity_anim(fr(te, steps), back, eps, dur)}'
        f'{sprite(STEVE, STEVE_PAL)}'
        '<g transform="translate(14 12)"><g>'
        '<animateTransform attributeName="transform" type="rotate" values="-70;15;-70" dur="0.32s" repeatCount="indefinite"/>'
        '<rect x="0" y="-1" width="11" height="2" fill="#8b5a2b"/>'
        '<rect x="9" y="-6" width="3" height="12" fill="#5decf5"/>'
        '<rect x="12" y="-4" width="1" height="8" fill="#2bc4d0"/>'
        '</g></g></g>')

    # Creeper (flashes white right before exploding)
    cv = ";".join("{:.1f} {:.1f}".format(*sprite_pos(*path[max(0, min(t - CHASE, n - 1))])) for t in range(S))
    ks = [fr(te - 6 + j, steps) for j in range(6)] + [fr(te + 1, steps)]
    o.append(
        '<g>'
        f'<animateTransform attributeName="transform" type="translate" values="{cv}" '
        f'dur="{dur:.2f}s" repeatCount="indefinite"/>'
        f'{opacity_anim(fr(te, steps), back, eps, dur)}'
        f'{sprite(CREEPER, CREEPER_PAL)}'
        '<rect width="16" height="24" fill="#fff" opacity="0">'
        f'<animate attributeName="opacity" calcMode="discrete" values="0;0;1;0;1;0;1;0;0" '
        f'keyTimes="0;{";".join(f(k) for k in ks)};1" dur="{dur:.2f}s" repeatCount="indefinite"/>'
        '</rect></g>')

    # Explosion
    lx, ly = cell_xy(*path[-1])
    cx, cy = lx + CELL / 2, ly + CELL / 2
    a = fr(te, steps)
    for size, col, grow in [(70, "#ff9800", 1), (44, "#fff3b0", 1)]:
        h = size / 2
        o.append(
            f'<g transform="translate({cx} {cy})"><rect x="{-h}" y="{-h}" width="{size}" height="{size}" fill="{col}" opacity="0">'
            f'<animateTransform attributeName="transform" type="scale" values="0;0;1;1.25;1.25" '
            f'keyTimes="0;{f(a)};{f(a+fr(2,steps))};{f(a+fr(4,steps))};1" dur="{dur:.2f}s" repeatCount="indefinite"/>'
            f'<animate attributeName="opacity" values="0;0;.95;0;0" '
            f'keyTimes="0;{f(a)};{f(a+fr(1.5,steps))};{f(a+fr(4,steps))};1" dur="{dur:.2f}s" repeatCount="indefinite"/>'
            '</rect></g>')

    # HUD ------------------------------------------------------------
    hy = GY + 7 * PITCH + 24
    # hearts (vanish when the Creeper blows up)
    hearts = "".join(f'<g transform="translate({M + i*16} {hy+14})">{sprite(HEART, HEART_PAL)}</g>' for i in range(10))
    o.append(f'<g>{opacity_anim(fr(te, steps), back, eps, dur)}{hearts}</g>')

    # XP bar
    bw, bx, by = 300, (W - 300) / 2, hy + 34
    o.append(text(W / 2, hy + 24, total, 16, "#7efc20", "#143300", "middle"))
    o.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="8" fill="#1e1e1e" stroke="{th["slot_edge"]}"/>')
    o.append(f'<rect x="{bx}" y="{by}" width="0" height="8" fill="#7efc20">'
             f'<animate attributeName="width" values="0;{bw};{bw};0" '
             f'keyTimes="0;{f(fr(n-1, steps))};{f(back)};1" dur="{dur:.2f}s" repeatCount="indefinite"/></rect>')

    # Hotbar
    hx = W - M - 4 * 40
    for i, lvl in enumerate([1, 2, 3, 4]):
        sx = hx + i * 40
        o.append(f'<rect x="{sx}" y="{hy}" width="40" height="40" fill="{th["slot"]}" stroke="{th["slot_edge"]}" stroke-width="2"/>')
        o.append(f'<use href="#b{lvl}" transform="translate({sx+4} {hy+4}) scale(2)"/>')
        o.append(text(sx + 37, hy + 36, counts.get(lvl, 0), 12, "#ffffff", "#000000", "end"))

    o.append('</svg>')
    return "".join(o)


def main():
    total, weeks = demo_data() if DEMO else fetch(USER, TOKEN)
    if DEMO:
        print("DEMO mode: using fake contribution data", file=sys.stderr)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fname in [("light", "minecraft-snake.svg"), ("dark", "minecraft-snake-dark.svg")]:
        svg = build(name, total, weeks)
        (OUT / fname).write_text(svg, encoding="utf-8")
        print(f"wrote {OUT / fname} ({len(svg)//1024} KB)")


if __name__ == "__main__":
    main()
