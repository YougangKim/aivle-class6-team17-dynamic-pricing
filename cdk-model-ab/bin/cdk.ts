#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";
import { PricingModelFoundationStack } from "../lib/pricing-model-foundation-stack";
import { PricingModelRuntimeStack } from "../lib/pricing-model-runtime-stack";

const app = new cdk.App();

const environment = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION ?? "ap-northeast-2",
};

const foundation = new PricingModelFoundationStack(app, "AivlePricingModelFoundationCandidate", {
  synthesizer: new cdk.BootstraplessSynthesizer(),
  env: environment,
  description: "Candidate foundation for pricing model artifacts and results",
});

new PricingModelRuntimeStack(app, "AivlePricingModelRuntimeCandidate", {
  synthesizer: new cdk.BootstraplessSynthesizer(),
  env: environment,
  artifactBucket: foundation.artifactBucket,
  modelARepository: foundation.modelARepository,
  resultQueue: foundation.resultQueue,
  description: "Candidate Model A SageMaker endpoint and Model B Lambda; no orchestration",
});
