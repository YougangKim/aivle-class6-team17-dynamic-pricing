#!/usr/bin/env python3
"""Render the separate right-angled diagram that includes Step Functions."""

from pathlib import Path
import base64
import re
import shutil
import subprocess


root = Path(__file__).resolve().parent
source = root / "cdk.out-step-functions" / "cdkgraph" / "diagram.dot"
architecture = root / "architecture"
directed_dot = architecture / "dynamic-pricing-step-functions-directed.dot"
directed_svg = architecture / "dynamic-pricing-step-functions-directed.svg"
undirected_dot = architecture / "dynamic-pricing-step-functions-undirected.dot"
undirected_svg = architecture / "dynamic-pricing-step-functions-undirected.svg"


def embed_svg_images(svg_path: Path) -> int:
    """Inline local AWS icon SVGs so README renderers cannot block them."""
    svg = svg_path.read_text(encoding="utf-8")
    embedded = 0

    def replace_href(match: re.Match) -> str:
        nonlocal embedded
        href = match.group(1)
        if href.startswith(("data:", "http:", "https:")):
            return match.group(0)
        icon_path = architecture / href
        if not icon_path.is_file():
            return match.group(0)
        encoded = base64.b64encode(icon_path.read_bytes()).decode("ascii")
        embedded += 1
        return f'xlink:href="data:image/svg+xml;base64,{encoded}"'

    svg = re.sub(r'xlink:href="([^"]+)"', replace_href, svg)
    svg_path.write_text(svg, encoding="utf-8")
    return embedded

text = source.read_text(encoding="utf-8")
text = text.replace('style = "dotted";', 'style = "solid";')
text = text.replace('style = "dashed";', 'style = "solid";')
text = text.replace('concentrate = true;', 'concentrate = false;')
text = text.replace('splines = "ortho";', 'splines = "ortho";')
text = text.replace('nodesep = 0.8;', 'nodesep = 0.9;')
text = text.replace('ranksep = 0.75;', 'ranksep = 0.85;')
text = text.replace('forcelabels = true;', 'forcelabels = false;')
text = text.replace(
    '  bgcolor = "#FFFFFF";',
    '  outputorder = "edgesfirst";\n  newrank = true;\n  bgcolor = "#FFFFFF";',
)
text = text.replace('dir = "both";', 'dir = "back";')
text = text.replace('arrowhead = "odot";', 'arrowhead = "none";')
text = text.replace('arrowhead = "normal";', 'arrowhead = "none";')
text = text.replace('arrowtail = "none";', 'arrowtail = "normal";')


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

# Use the checked-in icon assets instead of a temporary jsii cache. This keeps
# Graphviz rendering reproducible after the cache has been removed.
image_path = architecture.as_posix()
text = re.sub(r'  imagepath = ".*?";', f'  imagepath = "{image_path}";', text, count=1)

# Dependency edges normally point from a resource to the resource it depends
# on. `dir=back` presents them as prerequisite -> consumer. These AI pipeline
# edges are execution/data-flow relationships, so retain their source -> target
# direction: Scheduler -> State Machine -> tasks, Lambda -> queues/endpoints.
flow_sources = (
    "InventorySchedule",
    "DynamicPricingWorkflow",
    "InventoryExtractorFunction",
    "DerivedFeatureFunction",
    "ModelInferenceFunction",
    "WebDistribution",
)


def preserve_flow_direction(match: re.Match) -> str:
    block = match.group(0)
    source_id = match.group(1)
    if any(name in source_id for name in flow_sources):
        block = block.replace('penwidth = 0.75;', 'penwidth = 0.75;\n    dir = "forward";')
        block = block.replace('arrowhead = "none";', 'arrowhead = "normal";')
        block = block.replace('arrowtail = "normal";', 'arrowtail = "none";')
    return block


text = re.sub(
    r'"([^"]+)"\s*->\s*"[^"]+"\s*\[.*?\n\s*\];',
    preserve_flow_direction,
    text,
    flags=re.DOTALL,
)

directed_dot.write_text(text, encoding="utf-8")

undirected_text = text.replace('dir = "back";', 'dir = "none";')
undirected_text = undirected_text.replace('dir = "forward";', 'dir = "none";')
undirected_text = undirected_text.replace('arrowhead = "normal";', 'arrowhead = "none";')
undirected_text = undirected_text.replace('arrowtail = "normal";', 'arrowtail = "none";')
undirected_dot.write_text(undirected_text, encoding="utf-8")

dot = shutil.which("dot") or r"C:\Program Files\Graphviz\bin\dot.exe"
subprocess.run([dot, "-Tsvg", str(directed_dot), "-o", str(directed_svg)], check=True)
subprocess.run([dot, "-Tsvg", str(undirected_dot), "-o", str(undirected_svg)], check=True)
print(f"wrote {directed_svg} ({embed_svg_images(directed_svg)} icons embedded)")
print(f"wrote {undirected_svg} ({embed_svg_images(undirected_svg)} icons embedded)")
