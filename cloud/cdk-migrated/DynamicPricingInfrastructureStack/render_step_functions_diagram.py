#!/usr/bin/env python3
"""Render the separate right-angled diagram that includes Step Functions."""

from pathlib import Path
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

cache_root = root.parents[2] / ".codex-temp" / "jsii-cache" / "@aws" / "pdk" / "0.26.15"
asset_roots = list(cache_root.glob("*/assets/aws-arch"))
if asset_roots:
    image_path = asset_roots[0].as_posix()
    text = re.sub(r'  imagepath = ".*?";', f'  imagepath = "{image_path}";', text, count=1)
    step_icon_source = asset_roots[0] / "application_integration" / "step_functions" / "service_icon.svg"
    step_icon_target = architecture / "application_integration" / "step_functions" / "service_icon.svg"
    step_icon_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(step_icon_source, step_icon_target)

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
print(f"wrote {directed_svg}")
print(f"wrote {undirected_svg}")
