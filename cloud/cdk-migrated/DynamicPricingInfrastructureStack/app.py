#!/usr/bin/env python3
import os

import aws_cdk as cdk
from aws_pdk.cdk_graph import CdkGraph
from aws_pdk.cdk_graph_plugin_diagram import CdkGraphDiagramPlugin

from dynamic_pricing_infrastructure_stack.dynamic_pricing_infrastructure_stack_stack import DynamicPricingInfrastructureStackStack


app = cdk.App()
DynamicPricingInfrastructureStackStack(app, "DynamicPricingInfrastructureStack",
    # If you don't specify 'env', this stack will be environment-agnostic.
    # Account/Region-dependent features and context lookups will not work,
    # but a single synthesized template can be deployed anywhere.

    # Uncomment the next line to specialize this stack for the AWS Account
    # and Region that are implied by the current CLI configuration.

    #env=cdk.Environment(account=os.getenv('CDK_DEFAULT_ACCOUNT'), region=os.getenv('CDK_DEFAULT_REGION')),

    # Uncomment the next line if you know exactly what Account and Region you
    # want to deploy the stack to. */

    #env=cdk.Environment(account='123456789012', region='us-east-1'),

    # For more information, see https://docs.aws.amazon.com/cdk/latest/guide/environments.html
    )

# Register the graph after every stack and construct has been added. The
# compact default diagram is emitted to cdk.out as DOT, SVG, and PNG.
graph = CdkGraph(
    app,
    plugins=[CdkGraphDiagramPlugin()],
)

app.synth()
graph.report()
