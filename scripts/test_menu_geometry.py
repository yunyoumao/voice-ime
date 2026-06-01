"""纯函数验证环形菜单命中判定（无 GUI、零网络）。

运行： .venv/Scripts/python.exe scripts/test_menu_geometry.py
"""
from __future__ import annotations

import math
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

from desktop.radial_menu import MODES, MenuGeometry  # noqa: E402


def _pt(g: MenuGeometry, deg: float, r: float):
    a = math.radians(deg)
    return g.center_x + r * math.cos(a), g.center_y + r * math.sin(a)


def main() -> None:
    g = MenuGeometry(500, 300, inner_radius=55, outer_radius=160)
    fails = 0

    def check(name: str, cond: bool) -> None:
        nonlocal fails
        print(f"  {'OK  ' if cond else 'FAIL'} {name}")
        if not cond:
            fails += 1

    check("中心点 → None（取消）", g.hit_test(500, 300) is None)
    check("死区内(r=40) → None", g.hit_test(*_pt(g, 30, 40)) is None)
    check("环外(r=200) → None", g.hit_test(*_pt(g, 30, 200)) is None)
    check("正东 0° → seg0", g.hit_test(*_pt(g, 0, 100)) == 0)
    for i in range(6):
        seg = g.hit_test(*_pt(g, i * 60 + 30, 100))
        check(f"瓣中线 {i * 60 + 30:>3}° → seg{i} ({MODES[i]})", seg == i)
    # 边界附近不应抛异常且落在合法范围
    for deg in (59, 61, 119, 121, 359):
        seg = g.hit_test(*_pt(g, deg, 100))
        check(f"边界 {deg:>3}° → 合法瓣 {seg}", isinstance(seg, int) and 0 <= seg < 6)

    print("\nALL PASS ✓" if fails == 0 else f"\n{fails} FAIL ✗")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
