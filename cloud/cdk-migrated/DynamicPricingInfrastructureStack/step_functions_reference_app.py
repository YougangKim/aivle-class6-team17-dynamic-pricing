#!/usr/bin/env python3
"""Draw a separate reference architecture including Step Functions."""

import aws_cdk as cdk
from aws_pdk.cdk_graph import FilterPreset, Filters, FilterValue, IFilter, IGraphFilterPlan, CdkGraph
from aws_pdk.cdk_graph_plugin_diagram import CdkGraphDiagramPlugin, IDiagramConfigBase

from dynamic_pricing_infrastructure_stack.reference_architecture_stack import (
    DynamicPricingReferenceArchitectureStack,
)


app = cdk.App(outdir="cdk.out-step-functions")
DynamicPricingReferenceArchitectureStack(
    app,
    "DynamicPricingStepFunctionsArchitecture",
    include_step_functions=True,
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
