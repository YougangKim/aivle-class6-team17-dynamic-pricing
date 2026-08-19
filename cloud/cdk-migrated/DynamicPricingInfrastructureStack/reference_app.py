#!/usr/bin/env python3
"""Synthesize and draw the reference-aware architecture without deploying it."""

import aws_cdk as cdk
from aws_pdk.cdk_graph import (
    CdkGraph,
    FilterPreset,
    Filters,
    FilterValue,
    IFilter,
    IGraphFilterPlan,
)
from aws_pdk.cdk_graph_plugin_diagram import CdkGraphDiagramPlugin, IDiagramConfigBase

from dynamic_pricing_infrastructure_stack.reference_architecture_stack import (
    DynamicPricingReferenceArchitectureStack,
)


app = cdk.App()
DynamicPricingReferenceArchitectureStack(
    app,
    "DynamicPricingReferenceArchitecture",
    env=cdk.Environment(account="188876037193", region="ap-northeast-2"),
)
graph = CdkGraph(
    app,
    plugins=[CdkGraphDiagramPlugin(defaults=IDiagramConfigBase(
        filter_plan=IGraphFilterPlan(
            preset=FilterPreset.NONE,
            filters=[IFilter(graph=Filters.exclude_cfn_type([
                FilterValue(value="AWS::IAM::Role"),
                FilterValue(value="AWS::IAM::InstanceProfile"),
            ]))],
        ),
        theme="light",
    ))],
)
app.synth()
graph.report()
