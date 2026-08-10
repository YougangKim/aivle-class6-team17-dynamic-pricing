import * as cdk from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { PricingModelFoundationStack } from "../lib/pricing-model-foundation-stack";

test("creates retained encrypted queues, artifact bucket, and ECR repository", () => {
  const app = new cdk.App();
  const stack = new PricingModelFoundationStack(app, "TestStack");
  const template = Template.fromStack(stack);

  template.resourceCountIs("AWS::SQS::Queue", 2);
  template.resourceCountIs("AWS::IAM::Role", 0);
  template.resourceCountIs("AWS::IAM::Policy", 0);
  template.resourceCountIs("AWS::S3::Bucket", 1);
  template.resourceCountIs("AWS::ECR::Repository", 1);
  template.hasResource("AWS::SQS::Queue", {
    DeletionPolicy: "Retain",
    UpdateReplacePolicy: "Retain",
    Properties: Match.objectLike({ SqsManagedSseEnabled: true }),
  });
});
