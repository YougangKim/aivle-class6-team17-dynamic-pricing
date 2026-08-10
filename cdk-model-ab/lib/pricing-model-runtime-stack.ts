import * as cdk from "aws-cdk-lib";
import * as ecr from "aws-cdk-lib/aws-ecr";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as sagemaker from "aws-cdk-lib/aws-sagemaker";
import * as sqs from "aws-cdk-lib/aws-sqs";
import { Construct } from "constructs";


export interface PricingModelRuntimeStackProps extends cdk.StackProps {
  artifactBucket: s3.IBucket;
  modelARepository: ecr.IRepository;
  resultQueue: sqs.IQueue;
}


export class PricingModelRuntimeStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: PricingModelRuntimeStackProps) {
    super(scope, id, props);

    const modelBCodeKey = new cdk.CfnParameter(this, "ModelBCodeKey", {
      type: "String",
      description: "Versioned S3 key for the verified Model B Lambda ZIP",
      allowedPattern: ".+\\.zip",
    });
    const modelAImageTag = new cdk.CfnParameter(this, "ModelAImageTag", {
      type: "String",
      description: "Immutable Model A ECR image tag or digest-qualified tag",
      allowedPattern: "[A-Za-z0-9._-]+",
    });
    const modelBCodeVersion = new cdk.CfnParameter(this, "ModelBCodeVersion", {
      type: "String",
      description: "S3 Version ID for the verified Model B Lambda ZIP",
      minLength: 1,
    });

    const modelBFunctionName = "aivle-dev-lambda-model-b-candidate";
    const modelBLogGroup = new logs.LogGroup(this, "ModelBLogGroup", {
      logGroupName: `/aws/lambda/${modelBFunctionName}`,
      retention: logs.RetentionDays.TWO_WEEKS,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    const modelBFunction = new lambda.Function(this, "ModelBFunction", {
      functionName: modelBFunctionName,
      runtime: lambda.Runtime.PYTHON_3_12,
      architecture: lambda.Architecture.X86_64,
      handler: "lambda_function.lambda_handler",
      code: lambda.Code.fromBucket(
        props.artifactBucket,
        modelBCodeKey.valueAsString,
        modelBCodeVersion.valueAsString,
      ),
      memorySize: 1024,
      timeout: cdk.Duration.seconds(60),
      environment: { RESULT_QUEUE_URL: props.resultQueue.queueUrl },
    });
    modelBFunction.node.addDependency(modelBLogGroup);
    props.resultQueue.grantSendMessages(modelBFunction);
    props.artifactBucket.grantRead(modelBFunction, modelBCodeKey.valueAsString);

    const modelAExecutionRole = new iam.Role(this, "ModelAExecutionRole", {
      assumedBy: new iam.ServicePrincipal("sagemaker.amazonaws.com"),
    });
    props.modelARepository.grantPull(modelAExecutionRole);
    modelAExecutionRole.addToPolicy(new iam.PolicyStatement({
      actions: ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
      resources: [`arn:${cdk.Aws.PARTITION}:logs:${cdk.Aws.REGION}:${cdk.Aws.ACCOUNT_ID}:log-group:/aws/sagemaker/Endpoints/*`],
    }));
    modelAExecutionRole.addToPolicy(new iam.PolicyStatement({
      actions: ["cloudwatch:PutMetricData"],
      resources: ["*"],
      conditions: { StringEquals: { "cloudwatch:namespace": "aws/sagemaker/Endpoints" } },
    }));

    const modelA = new sagemaker.CfnModel(this, "ModelAModel", {
      modelName: "aivle-dev-model-a-candidate",
      executionRoleArn: modelAExecutionRole.roleArn,
      primaryContainer: {
        image: cdk.Fn.join(":", [props.modelARepository.repositoryUri, modelAImageTag.valueAsString]),
        mode: "SingleModel",
      },
    });

    const endpointConfig = new sagemaker.CfnEndpointConfig(this, "ModelAEndpointConfig", {
      endpointConfigName: "aivle-dev-model-a-serverless-candidate-config",
      productionVariants: [{
        modelName: modelA.attrModelName,
        variantName: "AllTraffic",
        serverlessConfig: { memorySizeInMb: 2048, maxConcurrency: 1 },
      }],
    });

    const endpoint = new sagemaker.CfnEndpoint(this, "ModelAEndpoint", {
      endpointName: "aivle-dev-model-a-serverless-candidate",
      endpointConfigName: endpointConfig.attrEndpointConfigName,
    });

    new cdk.CfnOutput(this, "ModelBFunctionName", { value: modelBFunction.functionName });
    new cdk.CfnOutput(this, "ModelBFunctionArn", { value: modelBFunction.functionArn });
    new cdk.CfnOutput(this, "ModelAEndpointName", { value: endpoint.attrEndpointName });
  }
}
