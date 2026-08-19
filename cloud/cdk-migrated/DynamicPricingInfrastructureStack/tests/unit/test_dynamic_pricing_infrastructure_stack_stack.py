import aws_cdk as core
import aws_cdk.assertions as assertions

from dynamic_pricing_infrastructure_stack.dynamic_pricing_infrastructure_stack_stack import DynamicPricingInfrastructureStackStack

# example tests. To run these tests, uncomment this file along with the example
# resource in dynamic_pricing_infrastructure_stack/dynamic_pricing_infrastructure_stack_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = DynamicPricingInfrastructureStackStack(app, "dynamic-pricing-infrastructure-stack")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
