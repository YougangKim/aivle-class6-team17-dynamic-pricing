import * as cdk from "aws-cdk-lib";
import * as ecr from "aws-cdk-lib/aws-ecr";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as sqs from "aws-cdk-lib/aws-sqs";
import { Template } from "aws-cdk-lib/assertions";
import { PricingModelRuntimeStack } from "../lib/pricing-model-runtime-stack";

test("creates one Model B Lambda and one Model A serverless endpoint", () => {
  const app = new cdk.App();
  const support = new cdk.Stack(app, "Support");
  const stack = new PricingModelRuntimeStack(app, "Runtime", {
    artifactBucket: new s3.Bucket(support, "Artifacts"),
    modelARepository: new ecr.Repository(support, "Repository"),
    resultQueue: new sqs.Queue(support, "Results"),
  });
  const template = Template.fromStack(stack);

  template.resourceCountIs("AWS::Lambda::Function", 1);
  template.resourceCountIs("AWS::SageMaker::Model", 1);
  template.resourceCountIs("AWS::SageMaker::EndpointConfig", 1);
  template.resourceCountIs("AWS::SageMaker::Endpoint", 1);
  template.resourceCountIs("AWS::StepFunctions::StateMachine", 0);
});
