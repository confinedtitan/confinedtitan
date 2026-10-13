#!/usr/bin/env python3
"""
Minecraft contribution cave generator (v3).

The contribution graph becomes an underground world: dirt and gravel for empty
days, occasional lava, and diamond ore on every day with at least one contribution. Steve tunnels
to the ore on a random route, pausing to mine each block, while a Creeper trails
his tunnel and blows up at the end. The route is different on every run.

Pure stdlib. Outputs animated SVGs (SMIL) that work inside a GitHub README <img>.

Env vars:
  GH_USER        GitHub username (or pass as argv[1])
  GITHUB_TOKEN   token for the GraphQL API (omit + set DEMO=1 for fake data)
  OUT_DIR        output folder (default: dist)
  STEP_SECONDS   seconds per step Steve takes (default: 0.22, higher = slower)
  MAX_SECONDS    cap on the total loop length (default: 110)
  SEED           fix the random route (default: new route every run)
"""
import html
import json
import math
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
STEP = float(os.environ.get("STEP_SECONDS", "0.22"))
MAX_SECONDS = float(os.environ.get("MAX_SECONDS", "110"))
SEED = os.environ.get("SEED")

CELL, GAP, PX = 16, 2, 2
PITCH = CELL + GAP
M = 24
GY = 52
MINE_STEPS = 3.0     # how long Steve stands still to mine an ore block
DELAY = 12.0         # the Creeper trails Steve by this many steps
EXTRA = 10.0         # idle steps after the explosion before the loop resets

LEVELS = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2,
          "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}
ORES = {
    1: ("Coal",    ["#1c1c1c", "#2b2b2b", "#111111"]),
    2: ("Iron",    ["#d8af93", "#c49a7c", "#e8c8b0"]),
    3: ("Gold",    ["#fcee4b", "#e8c500", "#fff7a0"]),
    4: ("Diamond", ["#5decf5", "#2bc4d0", "#b8fbff"]),
}
STONE = ["#7d7d7d", "#8a8a8a", "#6f6f6f", "#777777", "#848484"]
DIRT = ["#866043", "#79553a", "#6b4a31", "#8f6a4a", "#7a5a3e"]
DIRT_SPECKS = [("#5a3d27", 7), ("#a07850", 3)]
GRAVEL = ["#857f7d", "#7a7573", "#948f8d", "#6d6866", "#8b8685"]
GRAVEL_SPECKS = [("#5b5755", 8), ("#b3aeac", 4)]

THEMES = {
    "light": dict(bg="#ffffff", border="#d0d7de", text="#24292f", shadow="#c9d1d9",
                  slot="#c6c6c6", slot_edge="#555555"),
    "dark":  dict(bg="#0d1117", border="#30363d", text="#e6edf3", shadow="#000000",
                  slot="#3a3f47", slot_edge="#8b949e"),
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
            lvl = rnd.choices(names, weights=[85, 6, 4, 3, 2])[0]
            c = LEVELS[lvl] * rnd.randint(1, 4)
            total += c
            days.append({"weekday": d, "contributionLevel": lvl, "contributionCount": c})
        weeks.append({"contributionDays": days})
    return total, weeks


# ---------------------------------------------------------------- textures
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


def _symbol(sid, pix):
    rects = "".join(f'<rect x="{x*PX}" y="{y*PX}" width="{PX}" height="{PX}" fill="{pix[y][x]}"/>'
                    for y in range(8) for x in range(8))
    edge = f'<rect x=".5" y=".5" width="{CELL-1}" height="{CELL-1}" fill="none" stroke="#000" stroke-opacity=".4"/>'
    return f'<g id="{sid}">{rects}{edge}</g>'


def ground_symbol(sid, palette, specks, seed):
    rnd = random.Random(seed)
    pix = [[rnd.choice(palette) for _ in range(8)] for _ in range(8)]
    for col, count in specks:
        for _ in range(count):
            pix[rnd.randrange(8)][rnd.randrange(8)] = col
    return _symbol(sid, pix)


def ore_symbol(level):
    rnd = random.Random(level * 101)
    pix = [[rnd.choice(STONE) for _ in range(8)] for _ in range(8)]
    cols = ORES[level][1]
    for _ in range(4):
        cx, cy = rnd.randint(1, 6), rnd.randint(1, 6)
        for dx, dy in [(0, 0), (1, 0), (0, 1), (1, 1)][: rnd.randint(2, 4)]:
            if cx + dx < 8 and cy + dy < 8:
                pix[cy + dy][cx + dx] = rnd.choice(cols)
    return _symbol(f"o{level}", pix)


def lava_symbol():
    rnd = random.Random(808)
    pix = [[rnd.choice(["#402018", "#57251b", "#2c1a1a"]) for _ in range(8)] for _ in range(8)]
    for _ in range(22):
        pix[rnd.randrange(8)][rnd.randrange(8)] = rnd.choice(["#ff6a00", "#ff9d00", "#ffd447", "#c93600"])
    return _symbol("lava", pix)


def all_symbols():
    return "".join([
        ground_symbol("d0", DIRT, DIRT_SPECKS, 11), ground_symbol("d1", DIRT, DIRT_SPECKS, 12),
        ground_symbol("g0", GRAVEL, GRAVEL_SPECKS, 21), ground_symbol("g1", GRAVEL, GRAVEL_SPECKS, 22),
        lava_symbol(),
    ] + [ore_symbol(l) for l in range(1, 5)])


def block_kind(cell, level):
    """symbol id for a cell; stable per cell so the world looks the same on every run"""
    if level == -1:
        return "lava"
    if level > 0:
        return f"o{level}"
    r = random.Random(cell[0] * 1000 + cell[1])
    prefix = "g" if r.random() < 0.32 else "d"
    return f"{prefix}{r.randrange(2)}"


FLASH = {"o": ("#ffffff", .85), "d": ("#e0c9a6", .55), "g": ("#eeeeee", .55), "l": ("#ff6a00", .9)}


# ---------------------------------------------------------------- route planning
def plan(grid, rnd):
    """Random tunnelling route. Returns timeline data in 'steps' (1 step = 1 block of walking)."""
    cells = sorted(grid)
    targets = {c for c in cells if grid[c] > 0} or set(rnd.sample(cells, min(6, len(cells))))
    pos = (0, rnd.randrange(7))
    if pos not in grid:
        pos = cells[0]
    start = pos
    t = 0.0
    frames = [(0.0, pos)]
    dug, swings, mined = {}, [], []

    def visit(c):
        nonlocal t
        if c in dug or c not in grid:
            return
        lvl = grid[c]
        if lvl > 0:                          # diamond: stop and mine it
            t0 = t
            swings.append(t0)
            t += MINE_STEPS
            frames.append((t, c))
            dug[c] = t0 + 0.85 * MINE_STEPS
            mined.append((dug[c], lvl))
        else:                                # dirt / gravel: dig straight through
            dug[c] = t + 0.3
        targets.discard(c)

    visit(pos)
    while targets:
        cur = pos
        ranked = sorted(targets, key=lambda c: (abs(c[0] - cur[0]) + abs(c[1] - cur[1]), rnd.random()))
        near = ranked[:3]
        tgt = rnd.choices(near, weights=[5, 3, 1][:len(near)])[0]
        while pos != tgt:
            dx, dy = tgt[0] - pos[0], tgt[1] - pos[1]
            opts = []
            if dx:
                opts.append((int(math.copysign(1, dx)), 0))
            if dy:
                opts.append((0, int(math.copysign(1, dy))))
            sx, sy = rnd.choice(opts)
            pos = (pos[0] + sx, pos[1] + sy)
            t += 1.0
            frames.append((t, pos))
            visit(pos)
            if rnd.random() < 0.07:          # looks around for a moment
                t += rnd.uniform(0.6, 2.0)
                frames.append((t, pos))

    t_end = t
    te = t_end + DELAY
    total_steps = te + EXTRA
    frames.append((total_steps, pos))

    vanish = dict(dug)                        # blocks near the blast also disappear
    for c in grid:
        if c not in vanish and (c[0] - pos[0]) ** 2 + (c[1] - pos[1]) ** 2 <= 9:
            vanish[c] = te + 0.3

    return dict(frames=frames, start=start, last=pos, vanish=vanish, swings=swings,
                mined=sorted(mined), te=te, total=total_steps)


# ---------------------------------------------------------------- svg helpers
def f(x):
    return f"{x:.5f}".rstrip("0").rstrip(".") or "0"


def text(x, y, s, size, fill, shadow, anchor="start"):
    s = html.escape(str(s))
    base = (f'font-family="\'Courier New\',monospace" font-weight="700" '
            f'font-size="{size}" text-anchor="{anchor}"')
    return (f'<text x="{x+1}" y="{y+1}" {base} fill="{shadow}">{s}</text>'
            f'<text x="{x}" y="{y}" {base} fill="{fill}">{s}</text>')


def build(theme_name, total, weeks, grid, P):
    th = THEMES[theme_name]
    nweeks = len(weeks)
    T = P["total"]
    te = P["te"]
    step_s = min(STEP, MAX_SECONDS / T)
    dur = T * step_s
    d_attr = f'dur="{dur:.2f}s" repeatCount="indefinite"'

    def fr(t):
        return min(1.0, t / T)

    eps = fr(0.2)
    back = fr(T - 2)

    def opacity_anim(a):
        return (f'<animate attributeName="opacity" values="1;1;0;0;1" '
                f'keyTimes="0;{f(a)};{f(a+eps)};{f(back)};1" {d_attr}/>')

    def cell_xy(c):
        return M + c[0] * PITCH, GY + c[1] * PITCH

    def sprite_pos(c):
        x, y = cell_xy(c)
        return x + CELL / 2 - 8, y + CELL - 22

    W = 2 * M + nweeks * PITCH - GAP
    H = GY + 7 * PITCH + 100
    ore_total = sum(1 for v in grid.values() if v > 0)
    counts = Counter(v for v in grid.values() if v > 0)

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
         f'role="img" aria-label="Minecraft contribution graph for {html.escape(USER)}">',
         f'<title>{html.escape(USER)}\'s contribution cave</title>',
         f'<defs>{all_symbols()}</defs>',
         f'<rect width="{W}" height="{H}" rx="12" fill="{th["bg"]}" stroke="{th["border"]}"/>',
         text(M, 32, f"{USER}'s Minecraft Contribution Cave", 16, th["text"], th["shadow"]),
         text(W - M, 32, f"{total} blocks mined this year", 12, th["text"], th["shadow"], "end")]

    # world blocks
    for cell in sorted(grid):
        lvl = grid[cell]
        x, y = cell_xy(cell)
        sid = block_kind(cell, lvl)
        t_gone = P["vanish"].get(cell)
        if t_gone is None:
            o.append(f'<use href="#{sid}" x="{x}" y="{y}"/>')
            continue
        a = fr(t_gone)
        o.append(f'<use href="#{sid}" x="{x}" y="{y}">{opacity_anim(a)}</use>')
        col, peak = FLASH[sid[0]]
        k = fr(0.6)
        o.append(f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" fill="{col}" opacity="0">'
                 f'<animate attributeName="opacity" values="0;0;{peak};0;0" '
                 f'keyTimes="0;{f(a)};{f(a+k/2)};{f(a+k*2)};1" {d_attr}/></rect>')

    # Steve: walk keyframes
    fs = P["frames"]
    sv = ";".join("{:.1f} {:.1f}".format(*sprite_pos(c)) for _, c in fs)
    sk = ";".join(f(fr(t)) for t, _ in fs)
    # pickaxe swings only while mining
    ang = [(0.0, -30)]
    for t0 in P["swings"]:
        ang += [(t0, -30), (t0 + .15 * MINE_STEPS, -75), (t0 + .4 * MINE_STEPS, 15),
                (t0 + .65 * MINE_STEPS, -75), (t0 + .9 * MINE_STEPS, 15), (t0 + MINE_STEPS, -30)]
    ang.append((T, -30))
    av = ";".join(str(a) for _, a in ang)
    ak = ";".join(f(fr(t)) for t, _ in ang)
    o.append(
        '<g>'
        f'<animateTransform attributeName="transform" type="translate" values="{sv}" keyTimes="{sk}" {d_attr}/>'
        f'{opacity_anim(fr(te))}'
        f'{sprite(STEVE, STEVE_PAL)}'
        '<g transform="translate(14 12)"><g transform="rotate(-30)">'
        f'<animateTransform attributeName="transform" type="rotate" values="{av}" keyTimes="{ak}" {d_attr}/>'
        '<rect x="0" y="-1" width="11" height="2" fill="#8b5a2b"/>'
        '<rect x="9" y="-6" width="3" height="12" fill="#5decf5"/>'
        '<rect x="12" y="-4" width="1" height="8" fill="#2bc4d0"/>'
        '</g></g></g>')

    # Creeper: follows Steve's tunnel DELAY steps later
    cf = [(0.0, P["start"])] + [(t + DELAY, c) for t, c in fs[:-1]] + [(T, P["last"])]
    cv = ";".join("{:.1f} {:.1f}".format(*sprite_pos(c)) for _, c in cf)
    ck = ";".join(f(fr(t)) for t, _ in cf)
    fuse = [fr(te - 6 + j) for j in range(6)] + [fr(te + 1)]
    o.append(
        '<g>'
        f'<animateTransform attributeName="transform" type="translate" values="{cv}" keyTimes="{ck}" {d_attr}/>'
        f'{opacity_anim(fr(te))}'
        f'{sprite(CREEPER, CREEPER_PAL)}'
        '<rect width="16" height="24" fill="#fff" opacity="0">'
        f'<animate attributeName="opacity" calcMode="discrete" values="0;0;1;0;1;0;1;0;0" '
        f'keyTimes="0;{";".join(f(k) for k in fuse)};1" {d_attr}/>'
        '</rect></g>')

    # explosion
    lx, ly = cell_xy(P["last"])
    cx, cy = lx + CELL / 2, ly + CELL / 2
    a = fr(te)
    for size, col in [(76, "#ff9800"), (46, "#fff3b0")]:
        h = size / 2
        o.append(
            f'<g transform="translate({cx} {cy})"><rect x="{-h}" y="{-h}" width="{size}" height="{size}" fill="{col}" opacity="0">'
            f'<animateTransform attributeName="transform" type="scale" values="0;0;1;1.25;1.25" '
            f'keyTimes="0;{f(a)};{f(a+fr(2))};{f(a+fr(4))};1" {d_attr}/>'
            f'<animate attributeName="opacity" values="0;0;.95;0;0" '
            f'keyTimes="0;{f(a)};{f(a+fr(1.5))};{f(a+fr(4))};1" {d_attr}/>'
            '</rect></g>')

    # ---- HUD
    hy = GY + 7 * PITCH + 24
    hearts = "".join(f'<g transform="translate({M + i*16} {hy+14})">{sprite(HEART, HEART_PAL)}</g>' for i in range(10))
    o.append(f'<g>{opacity_anim(fr(te))}{hearts}</g>')

    # XP bar fills as ore is mined
    bw, bx, by = 300, (W - 300) / 2, hy + 34
    o.append(text(W / 2, hy + 24, total, 16, "#7efc20", "#143300", "middle"))
    o.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="8" fill="#1e1e1e" stroke="{th["slot_edge"]}"/>')
    xp, cnt = [(0.0, 0.0)], 0
    for tm, _ in P["mined"]:
        xp.append((tm - 0.8, cnt / ore_total))
        cnt += 1
        xp.append((tm, cnt / ore_total))
    xp += [(T - 2, cnt / ore_total if ore_total else 0), (T, 0.0)]
    o.append(f'<rect x="{bx}" y="{by}" width="0" height="8" fill="#7efc20">'
             f'<animate attributeName="width" values="{";".join(f"{v*bw:.1f}" for _, v in xp)}" '
             f'keyTimes="{";".join(f(fr(t)) for t, _ in xp)}" {d_attr}/></rect>')

    # hotbar with counters that tick up as each ore is mined
    hx = W - M - 4 * 40
    for i, lvl in enumerate([1, 2, 3, 4]):
        sx = hx + i * 40
        o.append(f'<rect x="{sx}" y="{hy}" width="40" height="40" fill="{th["slot"]}" stroke="{th["slot_edge"]}" stroke-width="2"/>')
        o.append(f'<use href="#o{lvl}" transform="translate({sx+4} {hy+4}) scale(2)"/>')
        times = [tm for tm, l in P["mined"] if l == lvl]
        for k in range(len(times) + 1):
            fa = 0.0 if k == 0 else fr(times[k - 1])
            fb = fr(times[k]) if k < len(times) else 1.0
            pairs = [(0.0, 1 if fa == 0 else 0)]
            if fa > 0:
                pairs.append((fa, 1))
            if fb < 1:
                pairs.append((fb, 0))
            o.append(
                f'<g opacity="0"><animate attributeName="opacity" calcMode="discrete" '
                f'values="{";".join(str(v) for _, v in pairs)}" keyTimes="{";".join(f(t) for t, _ in pairs)}" {d_attr}/>'
                f'{text(sx + 37, hy + 36, k, 12, "#ffffff", "#000000", "end")}</g>')

    o.append('</svg>')
    return "".join(o), dur


def main():
    total, weeks = demo_data() if DEMO else fetch(USER, TOKEN)
    if DEMO:
        print("DEMO mode: using fake contribution data", file=sys.stderr)
    # Any contribution that day = diamond. Contribution intensity does not change the block.
    grid = {(w, d["weekday"]): (4 if d["contributionCount"] > 0 else 0)
            for w, wk in enumerate(weeks) for d in wk["contributionDays"]}
    # Add occasional lava to non-contribution days. Dirt/gravel remains the default
    # texture for every other empty day. The random seed changes each workflow run.
    rnd = random.Random(SEED) if SEED else random.Random()
    for cell, level in list(grid.items()):
        if level == 0 and rnd.random() < 0.055:
            grid[cell] = -1
    P = plan(grid, rnd)           # one route, shared by the light and dark versions
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fname in [("light", "minecraft-snake.svg"), ("dark", "minecraft-snake-dark.svg")]:
        svg, dur = build(name, total, weeks, grid, P)
        (OUT / fname).write_text(svg, encoding="utf-8")
        print(f"wrote {OUT / fname} ({len(svg)//1024} KB, {dur:.0f}s loop)")


if __name__ == "__main__":
    main()
