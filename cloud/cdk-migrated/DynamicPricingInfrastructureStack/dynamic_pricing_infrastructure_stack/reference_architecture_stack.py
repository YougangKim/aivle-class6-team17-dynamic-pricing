"""Reference-aware, visualization-only view of the deployed architecture.

The values and names in this stack come from the CloudFormation IaC Generator
export in ``cloud/iac-export``.  It is deliberately separate from the migrated
deployment stack: its purpose is to replace exported physical IDs/ARNs with CDK
tokens so cdk-graph can recover the relationships between resources.
"""

from aws_cdk import Stack
from aws_cdk import aws_autoscaling as autoscaling
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_rds as rds
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sagemaker as sagemaker
from aws_cdk import aws_scheduler as scheduler
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_sqs as sqs
from aws_cdk import aws_stepfunctions as stepfunctions
from constructs import Construct


class DynamicPricingReferenceArchitectureStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        include_step_functions: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Use concrete L1 classes rather than generic CfnResource. AWS PDK uses
        # the construct class (not only the CloudFormation Type string) to select
        # the official AWS architecture icon.
        current_scope = [self]
        factories = {
            "AWS::EC2::VPC": lambda i: ec2.CfnVPC(current_scope[0], i),
            "AWS::EC2::Subnet": lambda i: ec2.CfnSubnet(current_scope[0], i, vpc_id="placeholder"),
            "AWS::EC2::SecurityGroup": lambda i: ec2.CfnSecurityGroup(current_scope[0], i, group_description="placeholder"),
            "AWS::EC2::Instance": lambda i: ec2.CfnInstance(current_scope[0], i),
            "AWS::ElasticLoadBalancingV2::LoadBalancer": lambda i: elbv2.CfnLoadBalancer(current_scope[0], i),
            "AWS::ElasticLoadBalancingV2::TargetGroup": lambda i: elbv2.CfnTargetGroup(current_scope[0], i),
            "AWS::ElasticLoadBalancingV2::Listener": lambda i: elbv2.CfnListener(
                current_scope[0], i, default_actions=[], load_balancer_arn="placeholder", port=80
            ),
            "AWS::IAM::Role": lambda i: iam.CfnRole(current_scope[0], i, assume_role_policy_document={}),
            "AWS::IAM::InstanceProfile": lambda i: iam.CfnInstanceProfile(current_scope[0], i, roles=[]),
            "AWS::EC2::LaunchTemplate": lambda i: ec2.CfnLaunchTemplate(
                current_scope[0], i, launch_template_data=ec2.CfnLaunchTemplate.LaunchTemplateDataProperty()
            ),
            "AWS::AutoScaling::AutoScalingGroup": lambda i: autoscaling.CfnAutoScalingGroup(
                current_scope[0], i, min_size="0", max_size="0"
            ),
            "AWS::CloudFront::Distribution": lambda i: cloudfront.CfnDistribution(
                current_scope[0],
                i,
                distribution_config=cloudfront.CfnDistribution.DistributionConfigProperty(
                    enabled=True,
                    default_cache_behavior=cloudfront.CfnDistribution.DefaultCacheBehaviorProperty(
                        target_origin_id="placeholder", viewer_protocol_policy="allow-all"
                    ),
                ),
            ),
            "AWS::RDS::DBSubnetGroup": lambda i: rds.CfnDBSubnetGroup(
                current_scope[0], i, db_subnet_group_description="placeholder", subnet_ids=[]
            ),
            "AWS::RDS::DBInstance": lambda i: rds.CfnDBInstance(current_scope[0], i),
            "AWS::SecretsManager::Secret": lambda i: secretsmanager.CfnSecret(current_scope[0], i),
            "AWS::SecretsManager::SecretTargetAttachment": lambda i: secretsmanager.CfnSecretTargetAttachment(
                current_scope[0], i, secret_id="placeholder", target_id="placeholder", target_type="AWS::RDS::DBInstance"
            ),
            "AWS::SQS::Queue": lambda i: sqs.CfnQueue(current_scope[0], i),
            "AWS::S3::Bucket": lambda i: s3.CfnBucket(current_scope[0], i),
            "AWS::SageMaker::Endpoint": lambda i: sagemaker.CfnEndpoint(
                current_scope[0], i, endpoint_config_name="account-managed-endpoint-config"
            ),
            "AWS::Lambda::Function": lambda i: lambda_.CfnFunction(
                current_scope[0], i, code=lambda_.CfnFunction.CodeProperty(zip_file="placeholder"), role="placeholder"
            ),
            "AWS::Lambda::EventSourceMapping": lambda i: lambda_.CfnEventSourceMapping(
                current_scope[0], i, function_name="placeholder"
            ),
            "AWS::Scheduler::Schedule": lambda i: scheduler.CfnSchedule(
                current_scope[0],
                i,
                flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(mode="OFF"),
                schedule_expression="rate(1 day)",
                target=scheduler.CfnSchedule.TargetProperty(arn="placeholder", role_arn="placeholder"),
            ),
            "AWS::StepFunctions::StateMachine": lambda i: stepfunctions.CfnStateMachine(
                current_scope[0],
                i,
                role_arn="placeholder",
                definition_string='{"StartAt":"Placeholder","States":{"Placeholder":{"Type":"Succeed"}}}',
            ),
        }

        def resource(logical_id: str, resource_type: str, properties=None):
            construct = factories[resource_type](logical_id)
            construct.add_override("Properties", properties or {})
            return construct

        network_group = Construct(self, "NetworkInfrastructure")
        web_group = Construct(self, "WebDeliveryInfrastructure")
        data_group = Construct(self, "DatabaseInfrastructure")
        ai_group = Construct(self, "AiPricingPipeline")
        workflow_group = Construct(self, "StepFunctionsInfrastructure") if include_step_functions else None

        # Network recovered from vpc-062243d7d5b99e9b0 and its six exported
        # subnets.  References are intentional: they are what produce graph edges.
        current_scope[0] = network_group
        vpc = resource("Vpc", "AWS::EC2::VPC", {"CidrBlock": "10.0.0.0/16"})
        public_a = resource("PublicSubnetA", "AWS::EC2::Subnet", {
            "VpcId": vpc.ref, "CidrBlock": "10.0.1.0/24", "AvailabilityZone": "ap-northeast-2a"
        })
        public_c = resource("PublicSubnetC", "AWS::EC2::Subnet", {
            "VpcId": vpc.ref, "CidrBlock": "10.0.2.0/24", "AvailabilityZone": "ap-northeast-2c"
        })
        app_a = resource("ApplicationSubnetA", "AWS::EC2::Subnet", {
            "VpcId": vpc.ref, "CidrBlock": "10.0.10.0/24", "AvailabilityZone": "ap-northeast-2a"
        })
        app_c = resource("ApplicationSubnetC", "AWS::EC2::Subnet", {
            "VpcId": vpc.ref, "CidrBlock": "10.0.20.0/24", "AvailabilityZone": "ap-northeast-2c"
        })
        db_a = resource("DatabaseSubnetA", "AWS::EC2::Subnet", {
            "VpcId": vpc.ref, "CidrBlock": "10.0.30.0/24", "AvailabilityZone": "ap-northeast-2a"
        })
        db_c = resource("DatabaseSubnetC", "AWS::EC2::Subnet", {
            "VpcId": vpc.ref, "CidrBlock": "10.0.40.0/24", "AvailabilityZone": "ap-northeast-2c"
        })

        web_sg = resource("WebSecurityGroup", "AWS::EC2::SecurityGroup", {
            "GroupDescription": "aivle web tier", "VpcId": vpc.ref
        })
        db_sg = resource("DatabaseSecurityGroup", "AWS::EC2::SecurityGroup", {
            "GroupDescription": "aivle database tier",
            "VpcId": vpc.ref,
            "SecurityGroupIngress": [{
                "IpProtocol": "tcp", "FromPort": 5432, "ToPort": 5432,
                "SourceSecurityGroupId": web_sg.get_att("GroupId").to_string(),
            }],
        })

        # Web delivery path: CloudFront -> ALB -> target group -> ASG.
        current_scope[0] = web_group
        load_balancer = resource("WebApplicationLoadBalancer", "AWS::ElasticLoadBalancingV2::LoadBalancer", {
            "Name": "aivle-web-alb",
            "Scheme": "internet-facing",
            "Subnets": [public_a.ref, public_c.ref],
            "SecurityGroups": [web_sg.get_att("GroupId").to_string()],
        })
        target_group = resource("WebTargetGroup", "AWS::ElasticLoadBalancingV2::TargetGroup", {
            "Name": "aivle-web-tg", "Port": 80, "Protocol": "HTTP", "VpcId": vpc.ref,
        })
        listener = resource("WebListener", "AWS::ElasticLoadBalancingV2::Listener", {
            "LoadBalancerArn": load_balancer.ref,
            "Port": 80,
            "Protocol": "HTTP",
            "DefaultActions": [{"Type": "forward", "TargetGroupArn": target_group.ref}],
        })
        instance_role = resource("WebEc2Role", "AWS::IAM::Role", {
            "RoleName": "AivleWebEC2Role",
            "AssumeRolePolicyDocument": {"Version": "2012-10-17", "Statement": []},
        })
        instance_profile = resource("WebInstanceProfile", "AWS::IAM::InstanceProfile", {
            "InstanceProfileName": "AivleWebEC2Role", "Roles": [instance_role.ref],
        })
        launch_template = resource("WebLaunchTemplate", "AWS::EC2::LaunchTemplate", {
            "LaunchTemplateName": "aivle-web-lt2",
            "LaunchTemplateData": {
                "IamInstanceProfile": {"Arn": instance_profile.get_att("Arn").to_string()},
                "SecurityGroupIds": [web_sg.get_att("GroupId").to_string()],
            },
        })
        auto_scaling = resource("WebAutoScalingGroup", "AWS::AutoScaling::AutoScalingGroup", {
            "AutoScalingGroupName": "aivle-web-asg",
            "MinSize": "2", "MaxSize": "4", "DesiredCapacity": "2",
            "VPCZoneIdentifier": [app_a.ref, app_c.ref],
            "TargetGroupARNs": [target_group.ref],
            "LaunchTemplate": {"LaunchTemplateId": launch_template.ref, "Version": "$Latest"},
        })
        web_instance_a = resource("WebEc2InstanceA", "AWS::EC2::Instance", {
            "ImageId": "ami-0cd3bfb1dfee6ae9a",
            "InstanceType": "t3.micro",
            "PrivateIpAddress": "10.0.10.180",
            "SubnetId": app_a.ref,
            "SecurityGroupIds": [web_sg.get_att("GroupId").to_string()],
        })
        web_instance_c = resource("WebEc2InstanceC", "AWS::EC2::Instance", {
            "ImageId": "ami-0cd3bfb1dfee6ae9a",
            "InstanceType": "t3.micro",
            "PrivateIpAddress": "10.0.20.153",
            "SubnetId": app_c.ref,
            "SecurityGroupIds": [web_sg.get_att("GroupId").to_string()],
        })
        distribution = resource("WebDistribution", "AWS::CloudFront::Distribution", {
            "DistributionConfig": {
                "Enabled": True,
                "Origins": [{
                    "Id": "aivle-web-alb",
                    "DomainName": load_balancer.get_att("DNSName").to_string(),
                    "CustomOriginConfig": {"OriginProtocolPolicy": "http-only"},
                }],
                "DefaultCacheBehavior": {
                    "TargetOriginId": "aivle-web-alb",
                    "ViewerProtocolPolicy": "redirect-to-https",
                    "CachePolicyId": "4135ea2d-6df8-44a3-9df3-4b5a84be39ad",
                },
            }
        })

        # PostgreSQL and credentials. IaC Generator also emitted a false Neptune
        # duplicate for this same identifier; it is intentionally not reproduced.
        current_scope[0] = data_group
        db_subnets = resource("DatabaseSubnetGroup", "AWS::RDS::DBSubnetGroup", {
            "DBSubnetGroupDescription": "aivle-db-subnet-group",
            "DBSubnetGroupName": "aivle-db-subnet-group",
            "SubnetIds": [db_a.ref, db_c.ref],
        })
        database = resource("PostgreSqlDatabase", "AWS::RDS::DBInstance", {
            "DBInstanceIdentifier": "aivle-rds",
            "Engine": "postgres",
            "DBInstanceClass": "db.t3.micro",
            "AllocatedStorage": "20",
            "DBSubnetGroupName": db_subnets.ref,
            "VPCSecurityGroups": [db_sg.get_att("GroupId").to_string()],
        })
        secret = resource("DatabaseSecret", "AWS::SecretsManager::Secret", {
            "Name": "aivle-rds-service-secret",
            "Description": "Shared PostgreSQL credentials for application and AI services",
        })
        secret_attachment = resource("DatabaseSecretAttachment", "AWS::SecretsManager::SecretTargetAttachment", {
            "SecretId": secret.ref, "TargetId": database.ref, "TargetType": "AWS::RDS::DBInstance",
        })
        mock_erp_writer = resource("MockErpRdsWriterFunction", "AWS::Lambda::Function", {
            "FunctionName": "mock-erp-rds-writer",
            "Runtime": "python3.12",
            "Handler": "lambda_function.lambda_handler",
            "Role": "arn:aws:iam::188876037193:role/service-role/mock-erp-rds-writer-role-cj75zvng",
            "Code": {"ZipFile": "def lambda_handler(event, context): return {}"},
            "Environment": {"Variables": {
                "SECRET_ARN": secret.ref,
                "DB_ENDPOINT": database.get_att("Endpoint.Address").to_string(),
            }},
        })

        # AI inventory pipeline recovered from Scheduler and Lambda event source
        # mappings: Scheduler -> extractor -> raw queue -> feature -> model queue -> inference.
        current_scope[0] = ai_group
        raw_queue = resource("InventoryRawQueue", "AWS::SQS::Queue", {
            "QueueName": "aivle-dev-inventory-raw-queue"
        })
        model_queue = resource("ModelInputQueue", "AWS::SQS::Queue", {
            "QueueName": "aivle-dev-model-input-queue"
        })
        ml_bucket = resource("MachineLearningBucket", "AWS::S3::Bucket", {
            "BucketName": "aivle-dynamic-pricing-ml-188876037193-dev"
        })
        sagemaker_bucket = resource("SageMakerArtifactBucket", "AWS::S3::Bucket", {
            "BucketName": "aivle-dev-sagemaker-artifacts-188876037193"
        })
        pricing_endpoint = resource("PricingServerlessEndpoint", "AWS::SageMaker::Endpoint", {
            "EndpointName": "aivle-dev-pricing-serverless-endpoint",
            "EndpointConfigName": "account-managed-endpoint-config",
        })

        extractor_role = resource("InventoryExtractorRole", "AWS::IAM::Role", {
            "RoleName": "aivle-dev-role-lambda-extractor",
            "AssumeRolePolicyDocument": {"Version": "2012-10-17", "Statement": []},
        })
        feature_role = resource("DerivedFeatureRole", "AWS::IAM::Role", {
            "RoleName": "aivle-dev-role-lambda-derived-feature",
            "AssumeRolePolicyDocument": {"Version": "2012-10-17", "Statement": []},
        })
        inference_role = resource("ModelInferenceRole", "AWS::IAM::Role", {
            "RoleName": "aivle-dev-role-lambda-model-inference",
            "AssumeRolePolicyDocument": {"Version": "2012-10-17", "Statement": []},
        })
        lambda_code = {"S3Bucket": ml_bucket.ref, "S3Key": "visualization-only/not-deployable.zip"}
        extractor = resource("InventoryExtractorFunction", "AWS::Lambda::Function", {
            "FunctionName": "aivle-dev-lambda-inventory-extractor", "Runtime": "python3.12",
            "Handler": "lambda_function.lambda_handler", "Role": extractor_role.get_att("Arn").to_string(),
            "Code": lambda_code,
            "Environment": {"Variables": {"OUTPUT_QUEUE_URL": raw_queue.ref}},
        })
        feature = resource("DerivedFeatureFunction", "AWS::Lambda::Function", {
            "FunctionName": "aivle-dev-lambda-derived-feature", "Runtime": "python3.12",
            "Handler": "lambda_function.lambda_handler", "Role": feature_role.get_att("Arn").to_string(),
            "Code": lambda_code,
            "Environment": {"Variables": {"OUTPUT_QUEUE_URL": model_queue.ref}},
        })
        inference = resource("ModelInferenceFunction", "AWS::Lambda::Function", {
            "FunctionName": "aivle-dev-lambda-model-inference", "Runtime": "python3.12",
            "Handler": "lambda_function.lambda_handler", "Role": inference_role.get_att("Arn").to_string(),
            "Code": lambda_code,
            "Environment": {"Variables": {
                "SECRET_ARN": secret.ref,
                "DB_ENDPOINT": database.get_att("Endpoint.Address").to_string(),
                "SAGEMAKER_ENDPOINT_NAME": pricing_endpoint.ref,
            }},
        })
        raw_mapping = resource("InventoryRawEventSource", "AWS::Lambda::EventSourceMapping", {
            "EventSourceArn": raw_queue.get_att("Arn").to_string(), "FunctionName": feature.get_att("Arn").to_string(),
            "BatchSize": 10,
        })
        model_mapping = resource("ModelInputEventSource", "AWS::Lambda::EventSourceMapping", {
            "EventSourceArn": model_queue.get_att("Arn").to_string(), "FunctionName": inference.get_att("Arn").to_string(),
            "BatchSize": 1,
        })
        scheduler_role = resource("InventorySchedulerRole", "AWS::IAM::Role", {
            "RoleName": "Amazon_EventBridge_Scheduler_LAMBDA_6817b57ba0",
            "AssumeRolePolicyDocument": {"Version": "2012-10-17", "Statement": []},
        })

        pricing_workflow = None
        if include_step_functions:
            current_scope[0] = workflow_group
            workflow_role = resource("PricingWorkflowRole", "AWS::IAM::Role", {
                "RoleName": "aivle-dev-role-step-functions-pricing-workflow",
                "AssumeRolePolicyDocument": {"Version": "2012-10-17", "Statement": [{
                    "Effect": "Allow",
                    "Principal": {"Service": ["states.amazonaws.com"]},
                    "Action": ["sts:AssumeRole"],
                }]},
            })
            pricing_workflow = resource("DynamicPricingWorkflow", "AWS::StepFunctions::StateMachine", {
                "StateMachineName": "aivle-dev-dynamic-pricing-workflow",
                "StateMachineType": "STANDARD",
                "RoleArn": workflow_role.get_att("Arn").to_string(),
                "DefinitionString": {
                    "Fn::Sub": [
                        '{"StartAt":"ExtractInventory","States":{'
                        '"ExtractInventory":{"Type":"Task","Resource":"${ExtractorArn}","Next":"DeriveFeatures"},'
                        '"DeriveFeatures":{"Type":"Task","Resource":"${FeatureArn}","Next":"RunInference"},'
                        '"RunInference":{"Type":"Task","Resource":"${InferenceArn}","End":true}}}',
                        {
                            "ExtractorArn": extractor.get_att("Arn").to_string(),
                            "FeatureArn": feature.get_att("Arn").to_string(),
                            "InferenceArn": inference.get_att("Arn").to_string(),
                        },
                    ]
                },
            })

        current_scope[0] = ai_group
        schedule_target = pricing_workflow if pricing_workflow is not None else extractor
        schedule = resource("InventorySchedule", "AWS::Scheduler::Schedule", {
            "Name": "aivle-dev-schedule-inventory-extractor",
            "ScheduleExpression": "rate(10 minutes)", "State": "DISABLED",
            "FlexibleTimeWindow": {"Mode": "OFF"},
            "Target": {"Arn": schedule_target.get_att("Arn").to_string(), "RoleArn": scheduler_role.get_att("Arn").to_string()},
        })

        # cdk-graph renders construct dependencies. CloudFormation tokens alone
        # are sufficient for deployment ordering, but generic CfnResource nodes do
        # not expose those relationships to the diagram plugin. Mirror them as
        # explicit construct dependencies so the reference diagram is complete.
        def depends(child, *parents):
            for parent in parents:
                child.add_resource_dependency(parent)

        for subnet in (public_a, public_c, app_a, app_c, db_a, db_c):
            depends(subnet, vpc)
        depends(web_sg, vpc)
        depends(db_sg, vpc, web_sg)
        depends(load_balancer, public_a, public_c, web_sg)
        depends(target_group, vpc)
        depends(listener, load_balancer, target_group)
        depends(instance_profile, instance_role)
        depends(launch_template, instance_profile, web_sg)
        depends(auto_scaling, app_a, app_c, target_group, launch_template)
        depends(web_instance_a, auto_scaling, app_a, web_sg)
        depends(web_instance_c, auto_scaling, app_c, web_sg)
        depends(distribution, load_balancer)
        depends(db_subnets, db_a, db_c)
        depends(database, db_subnets, db_sg)
        depends(secret_attachment, secret, database)
        depends(mock_erp_writer, secret, database)
        depends(extractor, extractor_role, ml_bucket, raw_queue)
        depends(feature, feature_role, ml_bucket, model_queue)
        depends(pricing_endpoint, sagemaker_bucket)
        depends(inference, inference_role, ml_bucket, secret, database, pricing_endpoint)
        depends(raw_mapping, raw_queue, feature)
        depends(model_mapping, model_queue, inference)
        if pricing_workflow is not None:
            depends(pricing_workflow, workflow_role, extractor, feature, inference)
            depends(schedule, scheduler_role, pricing_workflow)
        else:
            depends(schedule, scheduler_role, extractor)

        # Keep variables referenced so linters make the intended terminal nodes clear.
        _ = (listener, auto_scaling, distribution, secret_attachment, raw_mapping, model_mapping, schedule)
