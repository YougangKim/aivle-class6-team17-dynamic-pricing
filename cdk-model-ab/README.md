# Stage 9 CDK candidate

The CDK app has two deployment boundaries:

- Foundation: result queue/DLQ, versioned S3 artifact bucket, ECR repository.
- Runtime: Model B Lambda and Model A SageMaker Serverless candidate endpoint.

Runtime uses `ModelBCodeKey`, `ModelBCodeVersion`, and `ModelAImageTag` CloudFormation parameters. It cannot be deployed until the verified ZIP and image are uploaded. Step Functions is intentionally absent until the isolated candidates pass AWS runtime checks.

Commands allowed in Stage 9:

```text
npm run build
npm test
npm run synth
```

`cdk diff` requires separate read-only AWS approval. `cdk deploy` is forbidden in Stage 9.

The fixed queue names come from the previously reviewed repository CDK candidate. Before any deployment, AWS read-only inventory/diff must confirm those names do not already exist outside the target CloudFormation stack.

This foundation uses `BootstraplessSynthesizer` because it has no file or Docker assets. It avoids creating a CDK bootstrap stack solely to deploy two queues. Later stacks containing Lambda ZIP or container assets must use an approved artifact/bootstrap strategy.
