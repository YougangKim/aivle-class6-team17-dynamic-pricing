import * as cdk from "aws-cdk-lib";
import * as ecr from "aws-cdk-lib/aws-ecr";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as sqs from "aws-cdk-lib/aws-sqs";
import { Construct } from "constructs";

export class PricingModelFoundationStack extends cdk.Stack {
  public readonly artifactBucket: s3.Bucket;
  public readonly modelARepository: ecr.Repository;
  public readonly resultQueue: sqs.Queue;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const resultDlq = new sqs.Queue(this, "PricingResultDlq", {
      queueName: "aivle-dev-pricing-result-dlq",
      encryption: sqs.QueueEncryption.SQS_MANAGED,
      retentionPeriod: cdk.Duration.days(14),
      visibilityTimeout: cdk.Duration.minutes(3),
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    this.resultQueue = new sqs.Queue(this, "PricingResultQueue", {
      queueName: "aivle-dev-pricing-result-queue",
      encryption: sqs.QueueEncryption.SQS_MANAGED,
      retentionPeriod: cdk.Duration.days(1),
      visibilityTimeout: cdk.Duration.minutes(3),
      deadLetterQueue: {
        queue: resultDlq,
        maxReceiveCount: 3,
      },
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    this.artifactBucket = new s3.Bucket(this, "PricingModelArtifactBucket", {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      versioned: true,
      lifecycleRules: [{ noncurrentVersionExpiration: cdk.Duration.days(30) }],
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      autoDeleteObjects: false,
    });

    this.modelARepository = new ecr.Repository(this, "ModelARepository", {
      repositoryName: "aivle-dev-model-a-candidate",
      imageScanOnPush: true,
      encryption: ecr.RepositoryEncryption.AES_256,
      lifecycleRules: [{ maxImageCount: 3 }],
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      emptyOnDelete: false,
    });

    new cdk.CfnOutput(this, "PricingResultQueueUrl", { value: this.resultQueue.queueUrl });
    new cdk.CfnOutput(this, "PricingResultQueueArn", { value: this.resultQueue.queueArn });
    new cdk.CfnOutput(this, "PricingResultDlqUrl", { value: resultDlq.queueUrl });
    new cdk.CfnOutput(this, "PricingResultDlqArn", { value: resultDlq.queueArn });
    new cdk.CfnOutput(this, "PricingModelArtifactBucketName", { value: this.artifactBucket.bucketName });
    new cdk.CfnOutput(this, "ModelARepositoryUri", { value: this.modelARepository.repositoryUri });
  }
}
