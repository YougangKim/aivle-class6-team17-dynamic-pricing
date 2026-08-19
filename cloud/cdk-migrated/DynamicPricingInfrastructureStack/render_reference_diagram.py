#!/usr/bin/env python3
"""Finalize the PDK diagram with solid relationship edges.

PDK deliberately renders dependency/reference edges as dotted lines and does
not expose that edge style through DiagramOptions. This small post-processor
keeps the PDK-generated graph and only changes its visual edge style.
"""

from pathlib import Path
import re
import shutil
import subprocess


root = Path(__file__).resolve().parent
source = root / "cdk.out-reference" / "cdkgraph" / "diagram.dot"
architecture = root / "architecture"
target_dot = architecture / "dynamic-pricing-reference.dot"
target_svg = architecture / "dynamic-pricing-reference.svg"

text = source.read_text(encoding="utf-8")
text = text.replace('style = "dotted";', 'style = "solid";')
text = text.replace('style = "dashed";', 'style = "solid";')

# Improve readability for a dense, clustered architecture graph. Keep the
# orthogonal style, but stop `concentrate` from merging unrelated routes into
# the same corridor so arrowheads remain easier to distinguish.
text = text.replace('concentrate = true;', 'concentrate = false;')
text = text.replace('splines = "ortho";', 'splines = "ortho";')
text = text.replace('nodesep = 0.8;', 'nodesep = 0.9;')
text = text.replace('ranksep = 0.75;', 'ranksep = 0.85;')
text = text.replace('forcelabels = true;', 'forcelabels = false;')
text = text.replace('  bgcolor = "#FFFFFF";', '  outputorder = "edgesfirst";\n  newrank = true;\n  bgcolor = "#FFFFFF";')

# Use a single conventional arrowhead. PDK's normal+circle two-ended marker is
# useful for graph semantics but adds visual noise where many edges converge.
text = text.replace('dir = "both";', 'dir = "forward";')
text = text.replace('arrowhead = "none";', 'arrowhead = "normal";')
text = text.replace('arrowhead = "odot";', 'arrowhead = "normal";')
text = text.replace('arrowtail = "normal";', 'arrowtail = "none";')

# PDK 0.26.15 has no icon mapping for AWS::Scheduler::Schedule. Reuse the
# official EventBridge rule glyph, which is the closest AWS architecture icon
# for a scheduled EventBridge invocation.
def add_scheduler_icon(match: re.Match) -> str:
    block = match.group(0)
    if "AWS::Scheduler::Schedule" not in block or "image =" in block:
        return block
    block = block.replace('labelloc = "c";', 'labelloc = "b";')
    return block.replace(
        'penwidth = 0.25;',
        'penwidth = 0;\n'
        '        imagepos = "tc";\n'
        '        fillcolor = "transparent";\n'
        '        image = "application_integration/eventbridge/rule.svg";\n'
        '        height = 1.46;',
    )


text = re.sub(
    r'"node_[^"]*InventorySchedule[^"]*" \[.*?\n\s*\];',
    add_scheduler_icon,
    text,
    flags=re.DOTALL,
)

# The jsii temp directory disappears when synth exits. Point DOT at the stable
# PDK package cache; SVG consumers use the copied relative icon assets.
cache_root = root.parents[2] / ".codex-temp" / "jsii-cache" / "@aws" / "pdk" / "0.26.15"
asset_roots = list(cache_root.glob("*/assets/aws-arch"))
if asset_roots:
    image_path = asset_roots[0].as_posix()
    text = re.sub(r'  imagepath = ".*?";', f'  imagepath = "{image_path}";', text, count=1)

target_dot.write_text(text, encoding="utf-8")

dot = shutil.which("dot") or r"C:\Program Files\Graphviz\bin\dot.exe"
subprocess.run([dot, "-Tsvg", str(target_dot), "-o", str(target_svg)], check=True)

print(f"wrote {target_svg}")
