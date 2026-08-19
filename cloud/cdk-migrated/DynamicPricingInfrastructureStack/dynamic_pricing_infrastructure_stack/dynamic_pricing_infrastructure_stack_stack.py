from aws_cdk import Stack
import aws_cdk as cdk
import aws_cdk.aws_autoscaling as autoscaling
import aws_cdk.aws_cloudfront as cloudfront
import aws_cdk.aws_ec2 as ec2
import aws_cdk.aws_elasticloadbalancingv2 as elasticloadbalancingv2
import aws_cdk.aws_glue as glue
import aws_cdk.aws_iam as iam
import aws_cdk.aws_kms as kms
import aws_cdk.aws_lambda as aws_lambda
import aws_cdk.aws_logs as logs
import aws_cdk.aws_neptune as neptune
import aws_cdk.aws_rds as rds
import aws_cdk.aws_s3 as s3
import aws_cdk.aws_sqs as sqs
import aws_cdk.aws_scheduler as scheduler
import aws_cdk.aws_secretsmanager as secretsmanager
from constructs import Construct

class DynamicPricingInfrastructureStackStack(Stack):
  def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
    super().__init__(scope, construct_id, **kwargs)

    # Lambda deployment packages are write-only CloudFormation properties and
    # were not recoverable by IaC Generator. Keep them explicit as parameters
    # instead of inventing code locations in the migrated stack.
    lambdaDerivedFeatureCodeBucket = cdk.CfnParameter(self, 'LambdaDerivedFeatureCodeBucket', type='String')
    lambdaDerivedFeatureCodeKey = cdk.CfnParameter(self, 'LambdaDerivedFeatureCodeKey', type='String')
    lambdaInventoryExtractorCodeBucket = cdk.CfnParameter(self, 'LambdaInventoryExtractorCodeBucket', type='String')
    lambdaInventoryExtractorCodeKey = cdk.CfnParameter(self, 'LambdaInventoryExtractorCodeKey', type='String')
    lambdaModelInferenceCodeBucket = cdk.CfnParameter(self, 'LambdaModelInferenceCodeBucket', type='String')
    lambdaModelInferenceCodeKey = cdk.CfnParameter(self, 'LambdaModelInferenceCodeKey', type='String')
    lambdaMockErpRdsWriterCodeBucket = cdk.CfnParameter(self, 'LambdaMockErpRdsWriterCodeBucket', type='String')
    lambdaMockErpRdsWriterCodeKey = cdk.CfnParameter(self, 'LambdaMockErpRdsWriterCodeKey', type='String')

    # Resources
    autoScalingAutoScalingGroupAivlewebasg = autoscaling.CfnAutoScalingGroup(self, 'AutoScalingAutoScalingGroupAivlewebasg',
          service_linked_role_arn = 'arn:aws:iam::188876037193:role/aws-service-role/autoscaling.amazonaws.com/AWSServiceRoleForAutoScaling',
          target_group_arns = [
            'arn:aws:elasticloadbalancing:ap-northeast-2:188876037193:targetgroup/aivle-web-tg/29b9b53ee647669a',
          ],
          cooldown = '300',
          availability_zones = [
            'ap-northeast-2a',
            'ap-northeast-2c',
          ],
          desired_capacity = '2',
          health_check_grace_period = 300,
          max_size = '4',
          new_instances_protected_from_scale_in = False,
          min_size = '2',
          termination_policies = [
            'Default',
          ],
          launch_template = {
            'version': '$Default',
            'launchTemplateName': 'aivle-web-lt2',
            'launchTemplateId': 'lt-0e260b3f4ab0c3020',
          },
          auto_scaling_group_name = 'aivle-web-asg',
          vpc_zone_identifier = [
            'subnet-0f1ca9a5fcb1db9c3',
            'subnet-0795e706ec3c9515f',
          ],
          health_check_type = 'ELB',
        )
    autoScalingAutoScalingGroupAivlewebasg.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    cloudFrontCachePolicy = cloudfront.CfnCachePolicy(self, 'CloudFrontCachePolicy',
          cache_policy_config = {
            'comment': 'Policy with caching disabled',
            'minTtl': 0,
            'maxTtl': 0,
            'parametersInCacheKeyAndForwardedToOrigin': {
              'queryStringsConfig': {
                'queryStringBehavior': 'none',
              },
              'enableAcceptEncodingBrotli': False,
              'headersConfig': {
                'headerBehavior': 'none',
              },
              'cookiesConfig': {
                'cookieBehavior': 'none',
              },
              'enableAcceptEncodingGzip': False,
            },
            'defaultTtl': 0,
            'name': 'Managed-CachingDisabled',
          },
        )
    cloudFrontCachePolicy.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    cloudFrontOriginRequestPolicy = cloudfront.CfnOriginRequestPolicy(self, 'CloudFrontOriginRequestPolicy',
          origin_request_policy_config = {
            'queryStringsConfig': {
              'queryStringBehavior': 'all',
            },
            'comment': 'Policy to forward all parameters in viewer requests except for the Host header',
            'headersConfig': {
              'headerBehavior': 'allExcept',
              'headers': [
                'host',
              ],
            },
            'cookiesConfig': {
              'cookieBehavior': 'all',
            },
            'name': 'Managed-AllViewerExceptHostHeader',
          },
        )
    cloudFrontOriginRequestPolicy.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    ec2InstanceFr = ec2.CfnInstance(self, 'EC2InstanceFR',
          tenancy = 'default',
          private_ip_address = '10.0.20.153',
          user_data = 'IyEvYmluL2Jhc2gNCnNldCAtRWV1byBwaXBlZmFpbA0KDQpBV1NfUkVHSU9OPSJhcC1ub3J0aGVhc3QtMiINClMzX0JVQ0tFVD0iYWl2bGUtd2ViLWdpdC11cGRhdGUtczMtMTg4OC03NjAzLTcxOTMiDQoNCmZvciBhdHRlbXB0IGluICQoc2VxIDEgMzApOyBkbw0KICB3b3JrX2Rpcj0iJChta3RlbXAgLWQgL3RtcC9haXZsZS1ib290c3RyYXAuWFhYWFhYKSINCg0KICBpZiBhd3MgczMgY3AgInMzOi8vJHtTM19CVUNLRVR9L3JlbGVhc2VzL3dlYi1hcGktbGF0ZXN0LnppcCIgIiR7d29ya19kaXJ9L3dlYi1hcGkuemlwIiAtLXJlZ2lvbiAiJHtBV1NfUkVHSU9OfSIgXA0KICAgICYmIHVuemlwIC1xICIke3dvcmtfZGlyfS93ZWItYXBpLnppcCIgLWQgIiR7d29ya19kaXJ9L3dlYi1hcGkiIFwNCiAgICAmJiBiYXNoICIke3dvcmtfZGlyfS93ZWItYXBpL2RlcGxveS5zaCIgIiR7d29ya19kaXJ9L3dlYi1hcGkiICJib290c3RyYXAtJChkYXRlICslcykiIFwNCiAgICAmJiAvdXNyL2xvY2FsL2Jpbi9kZXBsb3ktYWl2bGUtd2ViIGZyb250ZW5kLWxhdGVzdC56aXA7IHRoZW4NCiAgICBybSAtcmYgIiR7d29ya19kaXJ9Ig0KICAgIGV4aXQgMA0KICBmaQ0KDQogIHJtIC1yZiAiJHt3b3JrX2Rpcn0iDQogIHNsZWVwIDEwDQpkb25lDQoNCmV4aXQgMQ0K',
          instance_initiated_shutdown_behavior = 'stop',
          block_device_mappings = [
            {
              'ebs': {
                'snapshotId': 'snap-00beee5acea576a73',
                'volumeType': 'gp3',
                'iops': 3000,
                'volumeSize': 8,
                'encrypted': False,
                'deleteOnTermination': True,
              },
              'deviceName': '/dev/xvda',
            },
          ],
          private_dns_name_options = {
            'enableResourceNameDnsARecord': False,
            'hostnameType': 'ip-name',
            'enableResourceNameDnsAaaaRecord': False,
          },
          security_group_ids = [
            'sg-08af1a5a646a2a66f',
          ],
          ebs_optimized = False,
          disable_api_termination = False,
          source_dest_check = True,
          placement_group_name = '',
          network_interfaces = [
            {
              'secondaryPrivateIpAddressCount': 0,
              'networkInterfaceId': 'eni-07fa852f94d630d05',
              'deviceIndex': '0',
            },
          ],
          image_id = 'ami-0cd3bfb1dfee6ae9a',
          instance_type = 't3.micro',
          monitoring = False,
          credit_specification = {
            'cpuCredits': 'unlimited',
          },
        )
    ec2InstanceFr.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    ec2InstanceRc = ec2.CfnInstance(self, 'EC2InstanceRc',
          tenancy = 'default',
          private_ip_address = '10.0.10.180',
          user_data = 'IyEvYmluL2Jhc2gKc2V0IC1lCgpmb3IgYXR0ZW1wdCBpbiAkKHNlcSAxIDMwKTsgZG8KICBpZiAvdXNyL2xvY2FsL2Jpbi9kZXBsb3ktYWl2bGUtd2ViIGZyb250ZW5kLWxhdGVzdC56aXA7IHRoZW4KICAgIGV4aXQgMAogIGZpCgogIHNsZWVwIDEwCmRvbmUKCmV4aXQgMQ==',
          instance_initiated_shutdown_behavior = 'stop',
          block_device_mappings = [
            {
              'ebs': {
                'snapshotId': 'snap-00beee5acea576a73',
                'volumeType': 'gp3',
                'iops': 3000,
                'volumeSize': 8,
                'encrypted': False,
                'deleteOnTermination': True,
              },
              'deviceName': '/dev/xvda',
            },
          ],
          private_dns_name_options = {
            'enableResourceNameDnsARecord': False,
            'hostnameType': 'ip-name',
            'enableResourceNameDnsAaaaRecord': False,
          },
          security_group_ids = [
            'sg-08af1a5a646a2a66f',
          ],
          ebs_optimized = False,
          disable_api_termination = False,
          source_dest_check = True,
          placement_group_name = '',
          network_interfaces = [
            {
              'secondaryPrivateIpAddressCount': 0,
              'networkInterfaceId': 'eni-02bcace25b86a9c61',
              'deviceIndex': '0',
            },
          ],
          image_id = 'ami-0cd3bfb1dfee6ae9a',
          instance_type = 't3.micro',
          monitoring = False,
          credit_specification = {
            'cpuCredits': 'unlimited',
          },
        )
    ec2InstanceRc.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    ec2NetworkInterfaceBd = ec2.CfnNetworkInterface(self, 'EC2NetworkInterfaceBd',
          source_dest_check = True,
          description = '',
          private_ip_addresses = [
            {
              'privateIpAddress': '10.0.20.153',
              'primary': True,
            },
          ],
          ipv6_prefix_count = 0,
          ipv4_prefix_count = 0,
          group_set = [
            'sg-08af1a5a646a2a66f',
          ],
          subnet_id = 'subnet-0f1ca9a5fcb1db9c3',
        )
    ec2NetworkInterfaceBd.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    ec2NetworkInterfaceYe = ec2.CfnNetworkInterface(self, 'EC2NetworkInterfaceYE',
          source_dest_check = True,
          description = '',
          private_ip_addresses = [
            {
              'privateIpAddress': '10.0.10.180',
              'primary': True,
            },
          ],
          ipv6_prefix_count = 0,
          ipv4_prefix_count = 0,
          group_set = [
            'sg-08af1a5a646a2a66f',
          ],
          subnet_id = 'subnet-0795e706ec3c9515f',
        )
    ec2NetworkInterfaceYe.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    ec2SecurityGroup = ec2.CfnSecurityGroup(self, 'EC2SecurityGroup',
          group_description = 'Allow PostgreSQL from AIVLE application services',
          group_name = 'aivle-rds-sg',
          vpc_id = 'vpc-062243d7d5b99e9b0',
          security_group_ingress = [
            {
              'ipProtocol': 'tcp',
              'fromPort': 5432,
              'sourceSecurityGroupId': 'sg-08af1a5a646a2a66f',
              'toPort': 5432,
              'sourceSecurityGroupOwnerId': '188876037193',
            },
            {
              'ipProtocol': 'tcp',
              'fromPort': 5432,
              'sourceSecurityGroupId': 'sg-0d9ec0878f9e798fd',
              'toPort': 5432,
              'sourceSecurityGroupOwnerId': '188876037193',
            },
            {
              'ipProtocol': 'tcp',
              'fromPort': 5432,
              'sourceSecurityGroupId': 'sg-063170d7eb76e9d79',
              'toPort': 5432,
              'sourceSecurityGroupOwnerId': '188876037193',
            },
            {
              'ipProtocol': 'tcp',
              'fromPort': 5432,
              'sourceSecurityGroupId': 'sg-01bbe87b6351a9b22',
              'toPort': 5432,
              'sourceSecurityGroupOwnerId': '188876037193',
            },
            {
              'ipProtocol': 'tcp',
              'fromPort': 5432,
              'sourceSecurityGroupId': 'sg-05961d8ea52fbe01f',
              'toPort': 5432,
              'sourceSecurityGroupOwnerId': '188876037193',
            },
            {
              'ipProtocol': 'tcp',
              'description': 'PostgreSQL from Mock ERP receiver Lambda',
              'fromPort': 5432,
              'sourceSecurityGroupId': 'sg-03980717daff09c63',
              'toPort': 5432,
              'sourceSecurityGroupOwnerId': '188876037193',
            },
            {
              'ipProtocol': 'tcp',
              'description': 'Allow candidate snapshot builder PostgreSQL access',
              'fromPort': 5432,
              'sourceSecurityGroupId': 'sg-0948557b61bdcb08e',
              'toPort': 5432,
              'sourceSecurityGroupOwnerId': '188876037193',
            },
            {
              'ipProtocol': 'tcp',
              'description': 'Temporary CloudShell PostgreSQL administration',
              'fromPort': 5432,
              'sourceSecurityGroupId': 'sg-06066a716ad342dae',
              'toPort': 5432,
              'sourceSecurityGroupOwnerId': '188876037193',
            },
            {
              'ipProtocol': 'tcp',
              'description': 'PostgreSQL from ERP price sync Lambdas',
              'fromPort': 5432,
              'sourceSecurityGroupId': 'sg-01ac1ee119035d56e',
              'toPort': 5432,
              'sourceSecurityGroupOwnerId': '188876037193',
            },
          ],
          security_group_egress = [
            {
              'cidrIp': '0.0.0.0/0',
              'ipProtocol': '-1',
            },
          ],
        )
    ec2SecurityGroup.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    ec2SecurityGroupM8 = ec2.CfnSecurityGroup(self, 'EC2SecurityGroupM8',
          group_description = 'alb - Web/API EC2',
          group_name = 'aivle-web-sg',
          vpc_id = 'vpc-062243d7d5b99e9b0',
          security_group_ingress = [
            {
              'ipProtocol': 'tcp',
              'fromPort': 80,
              'sourceSecurityGroupId': 'sg-0da77200d6a429c2b',
              'toPort': 80,
              'sourceSecurityGroupOwnerId': '188876037193',
            },
            {
              'ipProtocol': 'tcp',
              'fromPort': 5432,
              'sourceSecurityGroupId': 'sg-034317ebd1d603169',
              'toPort': 5432,
              'sourceSecurityGroupOwnerId': '188876037193',
            },
            {
              'ipProtocol': 'tcp',
              'fromPort': 22,
              'sourceSecurityGroupId': 'sg-0f959770bbedd5ac8',
              'toPort': 22,
              'sourceSecurityGroupOwnerId': '188876037193',
            },
          ],
          security_group_egress = [
            {
              'cidrIp': '0.0.0.0/0',
              'ipProtocol': '-1',
            },
          ],
        )
    ec2SecurityGroupM8.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    ec2Subnet = ec2.CfnSubnet(self, 'EC2Subnet',
          map_public_ip_on_launch = False,
          enable_dns64 = False,
          vpc_id = 'vpc-062243d7d5b99e9b0',
          private_dns_name_options_on_launch = {
            'EnableResourceNameDnsARecord': False,
            'HostnameType': 'ip-name',
            'EnableResourceNameDnsAAAARecord': False,
          },
          availability_zone = 'ap-northeast-2a',
          cidr_block = '10.0.30.0/24',
          ipv6_native = False,
          tags = [
            {
              'value': 'aivle-db-a',
              'key': 'Name',
            },
          ],
        )
    ec2Subnet.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    ec2SubnetDi = ec2.CfnSubnet(self, 'EC2SubnetDI',
          map_public_ip_on_launch = False,
          enable_dns64 = False,
          vpc_id = 'vpc-062243d7d5b99e9b0',
          private_dns_name_options_on_launch = {
            'EnableResourceNameDnsARecord': False,
            'HostnameType': 'ip-name',
            'EnableResourceNameDnsAAAARecord': False,
          },
          availability_zone = 'ap-northeast-2a',
          cidr_block = '10.0.1.0/24',
          ipv6_native = False,
          tags = [
            {
              'value': 'aivle-public-a',
              'key': 'Name',
            },
          ],
        )
    ec2SubnetDi.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    ec2SubnetGo = ec2.CfnSubnet(self, 'EC2SubnetGO',
          map_public_ip_on_launch = False,
          enable_dns64 = False,
          vpc_id = 'vpc-062243d7d5b99e9b0',
          private_dns_name_options_on_launch = {
            'EnableResourceNameDnsARecord': False,
            'HostnameType': 'ip-name',
            'EnableResourceNameDnsAAAARecord': False,
          },
          availability_zone = 'ap-northeast-2c',
          cidr_block = '10.0.2.0/24',
          ipv6_native = False,
          tags = [
            {
              'value': 'aivle-public-c',
              'key': 'Name',
            },
          ],
        )
    ec2SubnetGo.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    ec2SubnetHv = ec2.CfnSubnet(self, 'EC2SubnetHV',
          map_public_ip_on_launch = False,
          enable_dns64 = False,
          vpc_id = 'vpc-062243d7d5b99e9b0',
          private_dns_name_options_on_launch = {
            'EnableResourceNameDnsARecord': False,
            'HostnameType': 'ip-name',
            'EnableResourceNameDnsAAAARecord': False,
          },
          availability_zone = 'ap-northeast-2c',
          cidr_block = '10.0.40.0/24',
          ipv6_native = False,
          tags = [
            {
              'value': 'aivle-db-c',
              'key': 'Name',
            },
          ],
        )
    ec2SubnetHv.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    ec2SubnetS0 = ec2.CfnSubnet(self, 'EC2SubnetS0',
          map_public_ip_on_launch = False,
          enable_dns64 = False,
          vpc_id = 'vpc-062243d7d5b99e9b0',
          private_dns_name_options_on_launch = {
            'EnableResourceNameDnsARecord': False,
            'HostnameType': 'ip-name',
            'EnableResourceNameDnsAAAARecord': False,
          },
          availability_zone = 'ap-northeast-2a',
          cidr_block = '10.0.10.0/24',
          ipv6_native = False,
          tags = [
            {
              'value': 'aivle-private-a',
              'key': 'Name',
            },
          ],
        )
    ec2SubnetS0.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    ec2SubnetTc = ec2.CfnSubnet(self, 'EC2SubnetTC',
          map_public_ip_on_launch = False,
          enable_dns64 = False,
          vpc_id = 'vpc-062243d7d5b99e9b0',
          private_dns_name_options_on_launch = {
            'EnableResourceNameDnsARecord': False,
            'HostnameType': 'ip-name',
            'EnableResourceNameDnsAAAARecord': False,
          },
          availability_zone = 'ap-northeast-2c',
          cidr_block = '10.0.20.0/24',
          ipv6_native = False,
          tags = [
            {
              'value': 'aivle-private-c',
              'key': 'Name',
            },
          ],
        )
    ec2SubnetTc.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    ec2vpc = ec2.CfnVPC(self, 'EC2VPC',
          cidr_block = '10.0.0.0/16',
          enable_dns_support = True,
          instance_tenancy = 'default',
          enable_dns_hostnames = True,
          tags = [
            {
              'value': 'yk-aivle-vpc',
              'key': 'Name',
            },
          ],
        )
    ec2vpc.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    ec2VolumeAttachmentAx = ec2.CfnVolumeAttachment(self, 'EC2VolumeAttachmentAX',
          volume_id = 'vol-05f7e5448fb7dd77d',
          instance_id = 'i-06f07cb270b4c9c2c',
          device = '/dev/xvda',
        )
    ec2VolumeAttachmentAx.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    ec2VolumeAttachmentEv = ec2.CfnVolumeAttachment(self, 'EC2VolumeAttachmentEV',
          volume_id = 'vol-0e059f809ecf79a80',
          instance_id = 'i-0a4f5f01873c2bf22',
          device = '/dev/xvda',
        )
    ec2VolumeAttachmentEv.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    ec2VolumeVp = ec2.CfnVolume(self, 'EC2VolumeVP',
          multi_attach_enabled = False,
          snapshot_id = 'snap-00beee5acea576a73',
          volume_type = 'gp3',
          encrypted = False,
          size = 8,
          auto_enable_io = True,
          availability_zone = 'ap-northeast-2a',
          throughput = 125,
          iops = 3000,
        )
    ec2VolumeVp.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    ec2VolumeXj = ec2.CfnVolume(self, 'EC2VolumeXJ',
          multi_attach_enabled = False,
          snapshot_id = 'snap-00beee5acea576a73',
          volume_type = 'gp3',
          encrypted = False,
          size = 8,
          auto_enable_io = True,
          availability_zone = 'ap-northeast-2c',
          throughput = 125,
          iops = 3000,
        )
    ec2VolumeXj.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    elasticLoadBalancingV2LoadBalancerLoadbalancerappaivlewebalb25b1d8022c4b6043 = elasticloadbalancingv2.CfnLoadBalancer(self, 'ElasticLoadBalancingV2LoadBalancerLoadbalancerappaivlewebalb25b1d8022c4b6043',
          ip_address_type = 'ipv4',
          security_groups = [
            'sg-0da77200d6a429c2b',
          ],
          load_balancer_attributes = [
            {
              'value': '',
              'key': 'access_logs.s3.prefix',
            },
            {
              'value': 'append',
              'key': 'routing.http.xff_header_processing.mode',
            },
            {
              'value': 'true',
              'key': 'routing.http2.enabled',
            },
            {
              'value': 'false',
              'key': 'waf.fail_open.enabled',
            },
            {
              'value': '',
              'key': 'connection_logs.s3.bucket',
            },
            {
              'value': 'false',
              'key': 'access_logs.s3.enabled',
            },
            {
              'value': 'false',
              'key': 'zonal_shift.config.enabled',
            },
            {
              'value': 'defensive',
              'key': 'routing.http.desync_mitigation_mode',
            },
            {
              'value': '',
              'key': 'connection_logs.s3.prefix',
            },
            {
              'value': '',
              'key': 'health_check_logs.s3.prefix',
            },
            {
              'value': 'false',
              'key': 'routing.http.x_amzn_tls_version_and_cipher_suite.enabled',
            },
            {
              'value': 'false',
              'key': 'routing.http.preserve_host_header.enabled',
            },
            {
              'value': 'true',
              'key': 'load_balancing.cross_zone.enabled',
            },
            {
              'value': 'false',
              'key': 'health_check_logs.s3.enabled',
            },
            {
              'value': '',
              'key': 'health_check_logs.s3.bucket',
            },
            {
              'value': 'false',
              'key': 'routing.http.xff_client_port.enabled',
            },
            {
              'value': '',
              'key': 'access_logs.s3.bucket',
            },
            {
              'value': 'false',
              'key': 'deletion_protection.enabled',
            },
            {
              'value': '3600',
              'key': 'client_keep_alive.seconds',
            },
            {
              'value': 'false',
              'key': 'routing.http.drop_invalid_header_fields.enabled',
            },
            {
              'value': 'false',
              'key': 'connection_logs.s3.enabled',
            },
            {
              'value': '60',
              'key': 'idle_timeout.timeout_seconds',
            },
          ],
          subnets = [
            'subnet-02bc0d58e9ca0453a',
            'subnet-084b35b7192b72cd3',
          ],
          type = 'application',
          scheme = 'internet-facing',
          name = 'aivle-web-alb',
          subnet_mappings = [
            {
              'subnetId': 'subnet-02bc0d58e9ca0453a',
            },
            {
              'subnetId': 'subnet-084b35b7192b72cd3',
            },
          ],
        )
    elasticLoadBalancingV2LoadBalancerLoadbalancerappaivlewebalb25b1d8022c4b6043.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    glueJobAivlerdsconnectiontest = glue.CfnJob(self, 'GlueJobAivlerdsconnectiontest',
          connections = {
            'connections': [
              'aivle-rds-postgresql',
            ],
          },
          max_retries = 0,
          description = 'Read-only validation from aivle RDS PostgreSQL to S3 Parquet',
          timeout = 15,
          allocated_capacity = 2,
          name = 'aivle-rds-connection-test',
          role = 'arn:aws:iam::188876037193:role/AivleGlueSnapshotRole',
          default_arguments = {
            '--enable-metrics': 'true',
            '--job-language': 'python',
            '--TempDir': 's3://aivle-dynamic-pricing-ml-188876037193-dev/glue/temp/',
            '--enable-observability-metrics': 'true',
            '--enable-continuous-cloudwatch-log': 'true',
          },
          worker_type = 'G.1X',
          execution_class = 'STANDARD',
          command = {
            'scriptLocation': 's3://aivle-dynamic-pricing-ml-188876037193-dev/glue/scripts/aivle_rds_connection_test.py',
            'pythonVersion': '3',
            'name': 'glueetl',
          },
          glue_version = '5.0',
          execution_property = {
            'maxConcurrentRuns': 1,
          },
          number_of_workers = 2,
          tags = {
            'Project': 'aivle-dynamic-pricing',
            'Service': 'data-tier',
            'Environment': 'dev',
            'Purpose': 'rds-connection-test',
          },
          max_capacity = 2,
        )
    glueJobAivlerdsconnectiontest.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    iamGroupAivle = iam.CfnGroup(self, 'IAMGroupAivle',
          group_name = 'aivle',
          path = '/',
          managed_policy_arns = [
            'arn:aws:iam::aws:policy/PowerUserAccess',
          ],
        )
    iamGroupAivle.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    iamInstanceProfileAivleWebEc2Role = iam.CfnInstanceProfile(self, 'IAMInstanceProfileAivleWebEC2Role',
          path = '/',
          roles = [
            'AivleWebEC2Role',
          ],
          instance_profile_name = 'AivleWebEC2Role',
        )
    iamInstanceProfileAivleWebEc2Role.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    iamManagedPolicyPolicyAivleWebArtifactReadPolicy = iam.CfnManagedPolicy(self, 'IAMManagedPolicyPolicyAivleWebArtifactReadPolicy',
          managed_policy_name = 'AivleWebArtifactReadPolicy',
          path = '/',
          description = '',
          policy_document = {
            'Version': '2012-10-17',
            'Statement': [
              {
                'Condition': {
                  'StringLike': {
                    's3:prefix': [
                      'releases/*',
                    ],
                  },
                },
                'Resource': 'arn:aws:s3:::aivle-web-git-update-s3-1888-7603-7193',
                'Action': [
                  's3:ListBucket',
                ],
                'Effect': 'Allow',
                'Sid': 'ListArtifactBucket',
              },
              {
                'Resource': 'arn:aws:s3:::aivle-web-git-update-s3-1888-7603-7193/releases/*',
                'Action': [
                  's3:GetObject',
                ],
                'Effect': 'Allow',
                'Sid': 'ReadDeploymentArtifacts',
              },
            ],
          },
          roles = [
            'AivleWebEC2Role',
          ],
        )
    iamManagedPolicyPolicyAivleWebArtifactReadPolicy.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    iamManagedPolicyPolicyAivleWebGitHubDeployPolicy = iam.CfnManagedPolicy(self, 'IAMManagedPolicyPolicyAivleWebGitHubDeployPolicy',
          managed_policy_name = 'AivleWebGitHubDeployPolicy',
          path = '/',
          description = '',
          policy_document = {
            'Version': '2012-10-17',
            'Statement': [
              {
                'Resource': 'arn:aws:s3:::aivle-web-git-update-s3-1888-7603-7193/releases/*',
                'Action': [
                  's3:PutObject',
                ],
                'Effect': 'Allow',
                'Sid': 'UploadFrontendArtifact',
              },
              {
                'Resource': [
                  'arn:aws:ssm:ap-northeast-2:*:document/AWS-RunShellScript',
                  'arn:aws:ec2:ap-northeast-2:188876037193:instance/*',
                ],
                'Action': [
                  'ssm:SendCommand',
                ],
                'Effect': 'Allow',
                'Sid': 'SendFrontendDeploymentCommand',
              },
              {
                'Resource': '*',
                'Action': [
                  'ssm:GetCommandInvocation',
                  'ssm:ListCommandInvocations',
                ],
                'Effect': 'Allow',
                'Sid': 'ReadCommandResult',
              },
              {
                'Resource': 'arn:aws:cloudfront::188876037193:distribution/ELDUDUTC45Y21',
                'Action': [
                  'cloudfront:CreateInvalidation',
                ],
                'Effect': 'Allow',
                'Sid': 'InvalidateCloudFront',
              },
              {
                'Resource': '*',
                'Action': [
                  'autoscaling:DescribeAutoScalingGroups',
                ],
                'Effect': 'Allow',
                'Sid': 'ReadAutoScalingGroup',
              },
              {
                'Resource': '*',
                'Action': [
                  'ssm:DescribeInstanceInformation',
                ],
                'Effect': 'Allow',
                'Sid': 'DescribeSSMManagedInstances',
              },
            ],
          },
          roles = [
            'AivleWebGitHubDeployRole',
          ],
        )
    iamManagedPolicyPolicyAivleWebGitHubDeployPolicy.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    iamManagedPolicyPolicyAivleYkKimRoleReadPolicy = iam.CfnManagedPolicy(self, 'IAMManagedPolicyPolicyAivleYkKimRoleReadPolicy',
          managed_policy_name = 'AivleYkKimRoleReadPolicy',
          path = '/',
          description = '',
          policy_document = {
            'Version': '2012-10-17',
            'Statement': [
              {
                'Resource': [
                  'arn:aws:iam::188876037193:role/AWS-QuickSetup-SSM-LocalAdministrationRole',
                  'arn:aws:iam::188876037193:role/AWS-QuickSetup-SSM-LocalExecutionRole',
                  'arn:aws:iam::188876037193:role/AivleWebEC2Role',
                  'arn:aws:iam::188876037193:role/AivleWebGitHubDeployRole',
                ],
                'Action': [
                  'iam:GetRole',
                ],
                'Effect': 'Allow',
                'Sid': 'ReadRequiredIAMRoles',
              },
              {
                'Resource': '*',
                'Action': [
                  'iam:ListRoles',
                ],
                'Effect': 'Allow',
                'Sid': 'ListRolesInConsole',
              },
            ],
          },
          users = [
            'yk.kim',
          ],
        )
    iamManagedPolicyPolicyAivleYkKimRoleReadPolicy.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    iamManagedPolicyPolicyserviceroleAmazonEventBridgeSchedulerExecutionPolicy609bc86cd42a425d8b329c053106edfc = iam.CfnManagedPolicy(self, 'IAMManagedPolicyPolicyserviceroleAmazonEventBridgeSchedulerExecutionPolicy609bc86cd42a425d8b329c053106edfc',
          managed_policy_name = 'Amazon-EventBridge-Scheduler-Execution-Policy-609bc86c-d42a-425d-8b32-9c053106edfc',
          path = '/service-role/',
          description = '',
          policy_document = {
            'Version': '2012-10-17',
            'Statement': [
              {
                'Resource': [
                  'arn:aws:lambda:ap-northeast-2:188876037193:function:aivle-dev-lambda-inventory-extractor:*',
                  'arn:aws:lambda:ap-northeast-2:188876037193:function:aivle-dev-lambda-inventory-extractor',
                ],
                'Action': [
                  'lambda:InvokeFunction',
                ],
                'Effect': 'Allow',
              },
            ],
          },
          roles = [
            'Amazon_EventBridge_Scheduler_LAMBDA_6817b57ba0',
          ],
        )
    iamManagedPolicyPolicyserviceroleAmazonEventBridgeSchedulerExecutionPolicy609bc86cd42a425d8b329c053106edfc.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    iamRoleAivleGlueSnapshotRole = iam.CfnRole(self, 'IAMRoleAivleGlueSnapshotRole',
          path = '/',
          managed_policy_arns = [
            'arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole',
          ],
          max_session_duration = 3600,
          role_name = 'AivleGlueSnapshotRole',
          description = 'Glue role for RDS training snapshot export to S3',
          policies = [
            {
              'policyDocument': {
                'Version': '2012-10-17',
                'Statement': [
                  {
                    'Resource': 'arn:aws:s3:::aivle-dynamic-pricing-ml-188876037193-dev',
                    'Action': [
                      's3:ListBucket',
                      's3:GetBucketLocation',
                    ],
                    'Effect': 'Allow',
                    'Sid': 'ListMLBucket',
                  },
                  {
                    'Resource': [
                      'arn:aws:s3:::aivle-dynamic-pricing-ml-188876037193-dev/datasets/*',
                      'arn:aws:s3:::aivle-dynamic-pricing-ml-188876037193-dev/metadata/*',
                      'arn:aws:s3:::aivle-dynamic-pricing-ml-188876037193-dev/glue/*',
                    ],
                    'Action': [
                      's3:GetObject',
                      's3:PutObject',
                      's3:DeleteObject',
                    ],
                    'Effect': 'Allow',
                    'Sid': 'ReadWriteGlueData',
                  },
                  {
                    'Resource': 'arn:aws:secretsmanager:ap-northeast-2:188876037193:secret:aivle-rds-service-secret-E3klki',
                    'Action': [
                      'secretsmanager:GetSecretValue',
                      'secretsmanager:DescribeSecret',
                    ],
                    'Effect': 'Allow',
                    'Sid': 'ReadRDSSecret',
                  },
                ],
              },
              'policyName': 'AivleGlueSnapshotDataAccess',
            },
          ],
          assume_role_policy_document = {
            'Version': '2012-10-17',
            'Statement': [
              {
                'Action': 'sts:AssumeRole',
                'Effect': 'Allow',
                'Principal': {
                  'Service': 'glue.amazonaws.com',
                },
              },
            ],
          },
          tags = [
            {
              'value': 'aivle-dynamic-pricing',
              'key': 'Project',
            },
            {
              'value': 'dev',
              'key': 'Environment',
            },
            {
              'value': 'data-tier',
              'key': 'Service',
            },
          ],
        )
    iamRoleAivleGlueSnapshotRole.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    iamRoleAivleWebEc2Role = iam.CfnRole(self, 'IAMRoleAivleWebEC2Role',
          path = '/',
          managed_policy_arns = [
            'arn:aws:iam::188876037193:policy/AivleWebArtifactReadPolicy',
            'arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore',
          ],
          max_session_duration = 3600,
          role_name = 'AivleWebEC2Role',
          description = 'Allows EC2 instances to call AWS services on your behalf.',
          policies = [
            {
              'policyDocument': {
                'Version': '2012-10-17',
                'Statement': [
                  {
                    'Resource': 'arn:aws:lambda:ap-northeast-2:188876037193:function:aivle-dev-erp-price-outbox-publisher',
                    'Action': 'lambda:InvokeFunction',
                    'Effect': 'Allow',
                  },
                ],
              },
              'policyName': 'AivleInvokeErpPriceOutboxPublisher',
            },
            {
              'policyDocument': {
                'Version': '2012-10-17',
                'Statement': [
                  {
                    'Resource': 'arn:aws:lambda:ap-northeast-2:188876037193:function:aivle-dev-lambda-model-b-candidate',
                    'Action': 'lambda:InvokeFunction',
                    'Effect': 'Allow',
                  },
                ],
              },
              'policyName': 'AivleLambdaInvokeCandidatePolicy',
            },
            {
              'policyDocument': {
                'Version': '2012-10-17',
                'Statement': [
                  {
                    'Resource': 'arn:aws:sqs:ap-northeast-2:188876037193:aivle-dev-pricing-result-queue',
                    'Action': [
                      'sqs:ReceiveMessage',
                      'sqs:DeleteMessage',
                      'sqs:GetQueueAttributes',
                    ],
                    'Effect': 'Allow',
                  },
                ],
              },
              'policyName': 'AivlePricingResultQueueRead',
            },
            {
              'policyDocument': {
                'Version': '2012-10-17',
                'Statement': [
                  {
                    'Resource': [
                      'arn:aws:secretsmanager:ap-northeast-2:188876037193:secret:aivle-rds-service-secret-E3klki',
                    ],
                    'Action': [
                      'secretsmanager:GetSecretValue',
                      'secretsmanager:DescribeSecret',
                    ],
                    'Effect': 'Allow',
                    'Sid': 'ReadAivleRdsServiceSecret',
                  },
                ],
              },
              'policyName': 'AivleRdsServiceSecretRead',
            },
          ],
          assume_role_policy_document = {
            'Version': '2012-10-17',
            'Statement': [
              {
                'Action': 'sts:AssumeRole',
                'Effect': 'Allow',
                'Principal': {
                  'Service': 'ec2.amazonaws.com',
                },
              },
            ],
          },
        )
    iamRoleAivleWebEc2Role.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    iamRoleAivleWebGitHubDeployRole = iam.CfnRole(self, 'IAMRoleAivleWebGitHubDeployRole',
          path = '/',
          managed_policy_arns = [
            'arn:aws:iam::188876037193:policy/AivleWebGitHubDeployPolicy',
          ],
          max_session_duration = 3600,
          role_name = 'AivleWebGitHubDeployRole',
          description = '',
          assume_role_policy_document = {
            'Version': '2012-10-17',
            'Statement': [
              {
                'Condition': {
                  'StringEquals': {
                    'token.actions.githubusercontent.com:aud': 'sts.amazonaws.com',
                    'token.actions.githubusercontent.com:sub': 'repo:YougangKim@63978643/aivle-class6-team17-dynamic-pricing@1302430390:ref:refs/heads/main',
                  },
                },
                'Action': 'sts:AssumeRoleWithWebIdentity',
                'Effect': 'Allow',
                'Principal': {
                  'Federated': 'arn:aws:iam::188876037193:oidc-provider/token.actions.githubusercontent.com',
                },
              },
            ],
          },
        )
    iamRoleAivleWebGitHubDeployRole.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    iamRoleAivledevrolelambdaderivedfeature = iam.CfnRole(self, 'IAMRoleAivledevrolelambdaderivedfeature',
          path = '/',
          managed_policy_arns = [
            'arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole',
            'arn:aws:iam::aws:policy/service-role/AWSLambdaSQSQueueExecutionRole',
          ],
          max_session_duration = 3600,
          role_name = 'aivle-dev-role-lambda-derived-feature',
          description = 'Allows Lambda functions to call AWS services on your behalf.',
          policies = [
            {
              'policyDocument': {
                'Version': '2012-10-17',
                'Statement': [
                  {
                    'Resource': 'arn:aws:sqs:ap-northeast-2:188876037193:aivle-dev-model-input-queue',
                    'Action': [
                      'sqs:SendMessage',
                      'sqs:GetQueueAttributes',
                    ],
                    'Effect': 'Allow',
                    'Sid': 'SendModelInputMessages',
                  },
                ],
              },
              'policyName': 'aivle-dev-policy-derived-send-model-input',
            },
          ],
          assume_role_policy_document = {
            'Version': '2012-10-17',
            'Statement': [
              {
                'Action': 'sts:AssumeRole',
                'Effect': 'Allow',
                'Principal': {
                  'Service': 'lambda.amazonaws.com',
                },
              },
            ],
          },
        )
    iamRoleAivledevrolelambdaderivedfeature.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    iamRoleAivledevrolelambdaextractor = iam.CfnRole(self, 'IAMRoleAivledevrolelambdaextractor',
          path = '/',
          managed_policy_arns = [
            'arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole',
            'arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole',
          ],
          max_session_duration = 3600,
          role_name = 'aivle-dev-role-lambda-extractor',
          description = 'Allows Lambda functions to call AWS services on your behalf.',
          policies = [
            {
              'policyDocument': {
                'Version': '2012-10-17',
                'Statement': [
                  {
                    'Resource': 'arn:aws:secretsmanager:ap-northeast-2:188876037193:secret:aivle-rds-feature-lambda-app-RPPcEQ',
                    'Action': [
                      'secretsmanager:GetSecretValue',
                    ],
                    'Effect': 'Allow',
                    'Sid': 'ReadDatabaseSecret',
                  },
                  {
                    'Resource': 'arn:aws:sqs:ap-northeast-2:188876037193:aivle-dev-inventory-raw-queue',
                    'Action': [
                      'sqs:SendMessage',
                      'sqs:GetQueueAttributes',
                    ],
                    'Effect': 'Allow',
                    'Sid': 'SendInventoryMessages',
                  },
                ],
              },
              'policyName': 'aivle-dev-policy-extractor-access',
            },
          ],
          assume_role_policy_document = {
            'Version': '2012-10-17',
            'Statement': [
              {
                'Action': 'sts:AssumeRole',
                'Effect': 'Allow',
                'Principal': {
                  'Service': 'lambda.amazonaws.com',
                },
              },
            ],
          },
        )
    iamRoleAivledevrolelambdaextractor.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    iamRoleAivledevrolelambdamodelinference = iam.CfnRole(self, 'IAMRoleAivledevrolelambdamodelinference',
          path = '/',
          managed_policy_arns = [
            'arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole',
            'arn:aws:iam::aws:policy/service-role/AWSLambdaSQSQueueExecutionRole',
          ],
          max_session_duration = 3600,
          role_name = 'aivle-dev-role-lambda-model-inference',
          description = 'Allows Lambda functions to call AWS services on your behalf.',
          policies = [
            {
              'policyDocument': {
                'Version': '2012-10-17',
                'Statement': [
                  {
                    'Resource': 'arn:aws:sagemaker:ap-northeast-2:188876037193:endpoint/aivle-dev-pricing-serverless-endpoint',
                    'Action': [
                      'sagemaker:InvokeEndpoint',
                    ],
                    'Effect': 'Allow',
                    'Sid': 'InvokePricingEndpoint',
                  },
                ],
              },
              'policyName': 'aivle-dev-policy-invoke-pricing-endpoint',
            },
          ],
          assume_role_policy_document = {
            'Version': '2012-10-17',
            'Statement': [
              {
                'Action': 'sts:AssumeRole',
                'Effect': 'Allow',
                'Principal': {
                  'Service': 'lambda.amazonaws.com',
                },
              },
            ],
          },
        )
    iamRoleAivledevrolelambdamodelinference.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    iamRoleAivledevrolesagemakerexecution = iam.CfnRole(self, 'IAMRoleAivledevrolesagemakerexecution',
          path = '/',
          managed_policy_arns = [
            'arn:aws:iam::aws:policy/AmazonSageMakerFullAccess',
          ],
          max_session_duration = 3600,
          role_name = 'aivle-dev-role-sagemaker-execution',
          description = 'Allows SageMaker notebook instances, training jobs, and models to access S3, ECR, and CloudWatch on your behalf.',
          policies = [
            {
              'policyDocument': {
                'Version': '2012-10-17',
                'Statement': [
                  {
                    'Resource': [
                      'arn:aws:s3:::aivle-dev-sagemaker-artifacts-188876037193',
                      'arn:aws:s3:::aivle-dev-sagemaker-artifacts-188876037193/*',
                    ],
                    'Action': [
                      's3:GetObject',
                      's3:ListBucket',
                    ],
                    'Effect': 'Allow',
                    'Sid': 'ReadSageMakerArtifacts',
                  },
                ],
              },
              'policyName': 'SageMaker_S3_Allow',
            },
          ],
          assume_role_policy_document = {
            'Version': '2012-10-17',
            'Statement': [
              {
                'Action': 'sts:AssumeRole',
                'Effect': 'Allow',
                'Principal': {
                  'Service': 'sagemaker.amazonaws.com',
                },
                'Sid': '',
              },
            ],
          },
        )
    iamRoleAivledevrolesagemakerexecution.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    iamRoleAmazonEventBridgeSchedulerLambda6817b57ba0 = iam.CfnRole(self, 'IAMRoleAmazonEventBridgeSchedulerLAMBDA6817b57ba0',
          path = '/service-role/',
          managed_policy_arns = [
            'arn:aws:iam::188876037193:policy/service-role/Amazon-EventBridge-Scheduler-Execution-Policy-609bc86c-d42a-425d-8b32-9c053106edfc',
          ],
          max_session_duration = 3600,
          role_name = 'Amazon_EventBridge_Scheduler_LAMBDA_6817b57ba0',
          assume_role_policy_document = {
            'Version': '2012-10-17',
            'Statement': [
              {
                'Condition': {
                  'StringEquals': {
                    'aws:SourceAccount': '188876037193',
                  },
                },
                'Action': 'sts:AssumeRole',
                'Effect': 'Allow',
                'Principal': {
                  'Service': 'scheduler.amazonaws.com',
                },
              },
            ],
          },
        )
    iamRoleAmazonEventBridgeSchedulerLambda6817b57ba0.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    iamRoleMockerprdswriterrolecj75zvng = iam.CfnRole(self, 'IAMRoleMockerprdswriterrolecj75zvng',
          path = '/service-role/',
          managed_policy_arns = [
            'arn:aws:iam::188876037193:policy/service-role/AWSLambdaVPCAccessExecutionRole-d1e3bc2e-498d-4ae2-9738-6c4548f8158f',
            'arn:aws:iam::188876037193:policy/service-role/AWSLambdaBasicExecutionRole-ca72b042-6f4b-45d5-bbdc-0e4958a7840d',
          ],
          max_session_duration = 3600,
          role_name = 'mock-erp-rds-writer-role-cj75zvng',
          assume_role_policy_document = {
            'Version': '2012-10-17',
            'Statement': [
              {
                'Action': 'sts:AssumeRole',
                'Effect': 'Allow',
                'Principal': {
                  'Service': 'lambda.amazonaws.com',
                },
              },
            ],
          },
        )
    iamRoleMockerprdswriterrolecj75zvng.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    iamUserDylee = iam.CfnUser(self, 'IAMUserDylee',
          path = '/',
          user_name = 'dy.lee',
          groups = [
            'aivle',
          ],
          permissions_boundary = 'arn:aws:iam::aws:policy/PowerUserAccess',
        )
    iamUserDylee.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    iamUserHslee = iam.CfnUser(self, 'IAMUserHslee',
          path = '/',
          user_name = 'hs.lee',
          groups = [
            'aivle',
          ],
          permissions_boundary = 'arn:aws:iam::aws:policy/PowerUserAccess',
        )
    iamUserHslee.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    iamUserJulim = iam.CfnUser(self, 'IAMUserJulim',
          path = '/',
          user_name = 'julim',
          groups = [
            'aivle',
          ],
          permissions_boundary = 'arn:aws:iam::aws:policy/PowerUserAccess',
        )
    iamUserJulim.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    iamUserNypark = iam.CfnUser(self, 'IAMUserNypark',
          path = '/',
          managed_policy_arns = [
            'arn:aws:iam::aws:policy/IAMUserChangePassword',
          ],
          user_name = 'ny.park',
          groups = [
            'aivle',
          ],
        )
    iamUserNypark.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    iamUserSubin = iam.CfnUser(self, 'IAMUserSubin',
          path = '/',
          user_name = 'subin',
          groups = [
            'aivle',
          ],
          permissions_boundary = 'arn:aws:iam::aws:policy/PowerUserAccess',
        )
    iamUserSubin.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    iamUserYkkim = iam.CfnUser(self, 'IAMUserYkkim',
          path = '/',
          managed_policy_arns = [
            'arn:aws:iam::aws:policy/IAMUserChangePassword',
            'arn:aws:iam::188876037193:policy/AivleYkKimRoleReadPolicy',
            'arn:aws:iam::aws:policy/AdministratorAccess',
          ],
          user_name = 'yk.kim',
          groups = [
            'aivle',
          ],
          tags = [
            {
              'value': 'yk.kim CDK',
              'key': 'YOUR_ACCESS_KEY',
            },
          ],
        )
    iamUserYkkim.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    iamUserYskim = iam.CfnUser(self, 'IAMUserYskim',
          path = '/',
          user_name = 'ys.kim',
          groups = [
            'aivle',
          ],
          permissions_boundary = 'arn:aws:iam::aws:policy/PowerUserAccess',
        )
    iamUserYskim.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    kmsKey = kms.CfnKey(self, 'KMSKey',
          origin = 'AWS_KMS',
          multi_region = False,
          description = 'Default key that protects my RDS database volumes when no other key is defined',
          key_policy = {
            'Version': '2012-10-17',
            'Statement': [
              {
                'Condition': {
                  'StringEquals': {
                    'kms:ViaService': 'rds.ap-northeast-2.amazonaws.com',
                    'kms:CallerAccount': '188876037193',
                  },
                },
                'Resource': '*',
                'Action': [
                  'kms:Encrypt',
                  'kms:Decrypt',
                  'kms:ReEncrypt*',
                  'kms:GenerateDataKey*',
                  'kms:CreateGrant',
                  'kms:ListGrants',
                  'kms:DescribeKey',
                ],
                'Effect': 'Allow',
                'Principal': {
                  'AWS': '*',
                },
                'Sid': 'Allow access through RDS for all principals in the account that are authorized to use RDS',
              },
              {
                'Resource': '*',
                'Action': [
                  'kms:Describe*',
                  'kms:Get*',
                  'kms:List*',
                  'kms:RevokeGrant',
                ],
                'Effect': 'Allow',
                'Principal': {
                  'AWS': 'arn:aws:iam::188876037193:root',
                },
                'Sid': 'Allow direct access to key metadata to the account',
              },
            ],
            'Id': 'auto-rds-2',
          },
          key_spec = 'SYMMETRIC_DEFAULT',
          enabled = True,
          enable_key_rotation = True,
          key_usage = 'ENCRYPT_DECRYPT',
        )
    kmsKey.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    lambdaEventSourceMapping = aws_lambda.CfnEventSourceMapping(self, 'LambdaEventSourceMapping',
          batch_size = 1,
          function_name = 'arn:aws:lambda:ap-northeast-2:188876037193:function:aivle-dev-lambda-model-inference',
          scaling_config = {
            'maximumConcurrency': 2,
          },
          enabled = True,
          event_source_arn = 'arn:aws:sqs:ap-northeast-2:188876037193:aivle-dev-model-input-queue',
          function_response_types = [
            'ReportBatchItemFailures',
          ],
          maximum_batching_window_in_seconds = 0,
        )
    lambdaEventSourceMapping.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    lambdaEventSourceMappingVe = aws_lambda.CfnEventSourceMapping(self, 'LambdaEventSourceMappingVe',
          batch_size = 10,
          function_name = 'arn:aws:lambda:ap-northeast-2:188876037193:function:aivle-dev-lambda-derived-feature',
          enabled = True,
          event_source_arn = 'arn:aws:sqs:ap-northeast-2:188876037193:aivle-dev-inventory-raw-queue',
          function_response_types = [
            'ReportBatchItemFailures',
          ],
          maximum_batching_window_in_seconds = 0,
        )
    lambdaEventSourceMappingVe.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    lambdaFunctionAivledevlambdaderivedfeature = aws_lambda.CfnFunction(self, 'LambdaFunctionAivledevlambdaderivedfeature',
          memory_size = 256,
          description = '',
          tracing_config = {
            'mode': 'PassThrough',
          },
          timeout = 30,
          runtime_management_config = {
            'updateRuntimeOn': 'Auto',
          },
          handler = 'lambda_function.lambda_handler',
          code = {
            's3Bucket': lambdaDerivedFeatureCodeBucket.value_as_string,
            's3Key': lambdaDerivedFeatureCodeKey.value_as_string,
          },
          role = 'arn:aws:iam::188876037193:role/aivle-dev-role-lambda-derived-feature',
          function_name = 'aivle-dev-lambda-derived-feature',
          runtime = 'python3.14',
          package_type = 'Zip',
          logging_config = {
            'logFormat': 'Text',
            'logGroup': '/aws/lambda/aivle-dev-lambda-derived-feature',
          },
          environment = {
            'variables': {
              'MODEL_INPUT_QUEUE_URL': 'https://sqs.ap-northeast-2.amazonaws.com/188876037193/aivle-dev-model-input-queue',
            },
          },
          ephemeral_storage = {
            'size': 512,
          },
          architectures = [
            'x86_64',
          ],
        )
    lambdaFunctionAivledevlambdaderivedfeature.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    lambdaFunctionAivledevlambdainventoryextractor = aws_lambda.CfnFunction(self, 'LambdaFunctionAivledevlambdainventoryextractor',
          memory_size = 512,
          description = '',
          tracing_config = {
            'mode': 'PassThrough',
          },
          vpc_config = {
            'securityGroupIds': [
              'sg-05961d8ea52fbe01f',
            ],
            'subnetIds': [
              'subnet-0795e706ec3c9515f',
              'subnet-0f1ca9a5fcb1db9c3',
            ],
            'ipv6AllowedForDualStack': False,
          },
          timeout = 300,
          runtime_management_config = {
            'updateRuntimeOn': 'Auto',
          },
          handler = 'lambda_function.lambda_handler',
          code = {
            's3Bucket': lambdaInventoryExtractorCodeBucket.value_as_string,
            's3Key': lambdaInventoryExtractorCodeKey.value_as_string,
          },
          role = 'arn:aws:iam::188876037193:role/aivle-dev-role-lambda-extractor',
          function_name = 'aivle-dev-lambda-inventory-extractor',
          runtime = 'python3.14',
          package_type = 'Zip',
          logging_config = {
            'logFormat': 'Text',
            'logGroup': '/aws/lambda/aivle-dev-lambda-inventory-extractor',
          },
          environment = {
            'variables': {
              'QUEUE_URL': 'https://sqs.ap-northeast-2.amazonaws.com/188876037193/aivle-dev-inventory-raw-queue',
              'DB_SECRET_ARN': 'arn:aws:secretsmanager:ap-northeast-2:188876037193:secret:aivle-rds-feature-lambda-app-RPPcEQ',
              'EVENT_TYPE': 'inventory.UPSERT',
              'PIPELINE_NAME': 'inventory-feature-pipeline',
              'SOURCE_SYSTEM': 'mock-erp',
            },
          },
          ephemeral_storage = {
            'size': 512,
          },
          layers = [
            'arn:aws:lambda:ap-northeast-2:188876037193:layer:aivle-dev-pg8000-layer:1',
          ],
          architectures = [
            'x86_64',
          ],
        )
    lambdaFunctionAivledevlambdainventoryextractor.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    lambdaFunctionAivledevlambdamodelinference = aws_lambda.CfnFunction(self, 'LambdaFunctionAivledevlambdamodelinference',
          memory_size = 256,
          description = '',
          tracing_config = {
            'mode': 'PassThrough',
          },
          timeout = 300,
          runtime_management_config = {
            'updateRuntimeOn': 'Auto',
          },
          handler = 'lambda_function.lambda_handler',
          code = {
            's3Bucket': lambdaModelInferenceCodeBucket.value_as_string,
            's3Key': lambdaModelInferenceCodeKey.value_as_string,
          },
          role = 'arn:aws:iam::188876037193:role/aivle-dev-role-lambda-model-inference',
          function_name = 'aivle-dev-lambda-model-inference',
          runtime = 'python3.15',
          package_type = 'Zip',
          logging_config = {
            'logFormat': 'Text',
            'logGroup': '/aws/lambda/aivle-dev-lambda-model-inference',
          },
          environment = {
            'variables': {
              'SAGEMAKER_ENDPOINT_NAME': 'aivle-dev-pricing-serverless-endpoint',
            },
          },
          ephemeral_storage = {
            'size': 512,
          },
          architectures = [
            'x86_64',
          ],
        )
    lambdaFunctionAivledevlambdamodelinference.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    lambdaFunctionMockerprdswriter = aws_lambda.CfnFunction(self, 'LambdaFunctionMockerprdswriter',
          memory_size = 256,
          description = '',
          tracing_config = {
            'mode': 'PassThrough',
          },
          vpc_config = {
            'securityGroupIds': [
              'sg-01bfea33c4ed09c36',
            ],
            'subnetIds': [
              'subnet-00228edc0010713a8',
              'subnet-01974946b167eb88a',
            ],
            'ipv6AllowedForDualStack': False,
          },
          timeout = 30,
          runtime_management_config = {
            'updateRuntimeOn': 'Auto',
          },
          handler = 'lambda_function.lambda_handler',
          code = {
            's3Bucket': lambdaMockErpRdsWriterCodeBucket.value_as_string,
            's3Key': lambdaMockErpRdsWriterCodeKey.value_as_string,
          },
          role = 'arn:aws:iam::188876037193:role/service-role/mock-erp-rds-writer-role-cj75zvng',
          function_name = 'mock-erp-rds-writer',
          runtime = 'python3.12',
          package_type = 'Zip',
          logging_config = {
            'logFormat': 'Text',
            'logGroup': '/aws/lambda/mock-erp-rds-writer',
          },
          environment = {
            'variables': {
              'DB_NAME': 'mock_erp',
              'DB_PORT': '5432',
              'DB_HOST': 'mock-erp-postgres.cd2co2kos0oc.ap-northeast-2.rds.amazonaws.com',
              'DB_USER': 'erp_admin',
              'ERP_SHARED_TOKEN': 't10eKbpgzMTculfQuCDdiYPP25vzFfYKVhWzAnk+CSo=',
              'DB_PASSWORD': 'dpdlqmftmznf',
            },
          },
          ephemeral_storage = {
            'size': 512,
          },
          architectures = [
            'x86_64',
          ],
        )
    lambdaFunctionMockerprdswriter.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    lambdaPermissionFunctionaivledeverppriceoutboxpublisher = aws_lambda.CfnPermission(self, 'LambdaPermissionFunctionaivledeverppriceoutboxpublisher',
          function_name = 'arn:aws:lambda:ap-northeast-2:188876037193:function:aivle-dev-erp-price-outbox-publisher',
          action = 'lambda:InvokeFunction',
          source_arn = 'arn:aws:events:ap-northeast-2:188876037193:rule/aivle-dev-erp-price-publisher-every-minute',
          principal = 'events.amazonaws.com',
        )
    lambdaPermissionFunctionaivledeverppriceoutboxpublisher.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    lambdaPermissionFunctionaivleerpeventreceiver = aws_lambda.CfnPermission(self, 'LambdaPermissionFunctionaivleerpeventreceiver',
          function_name = 'arn:aws:lambda:ap-northeast-2:188876037193:function:aivle-erp-event-receiver',
          action = 'lambda:InvokeFunction',
          source_arn = 'arn:aws:execute-api:ap-northeast-2:188876037193:tzr0w5ahsh/*/POST/erp/events',
          principal = 'apigateway.amazonaws.com',
        )
    lambdaPermissionFunctionaivleerpeventreceiver.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    logsLogGroupawsrdsinstanceaivleproductpricerdspostgresql = logs.CfnLogGroup(self, 'LogsLogGroupawsrdsinstanceaivleproductpricerdspostgresql',
          log_group_class = 'STANDARD',
          log_group_name = '/aws/rds/instance/aivle-product-price-rds/postgresql',
        )
    logsLogGroupawsrdsinstanceaivleproductpricerdspostgresql.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    logsLogGroupawsrdsinstanceaivlerdspostgresql = logs.CfnLogGroup(self, 'LogsLogGroupawsrdsinstanceaivlerdspostgresql',
          log_group_class = 'STANDARD',
          log_group_name = '/aws/rds/instance/aivle-rds/postgresql',
        )
    logsLogGroupawsrdsinstanceaivlerdspostgresql.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    logsLogStreamAivleproductpricerds0 = logs.CfnLogStream(self, 'LogsLogStreamAivleproductpricerds0',
          log_stream_name = 'aivle-product-price-rds.0',
          log_group_name = '/aws/rds/instance/aivle-product-price-rds/postgresql',
        )
    logsLogStreamAivleproductpricerds0.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    logsLogStreamAivlerds = logs.CfnLogStream(self, 'LogsLogStreamAivlerds',
          log_stream_name = 'aivle-rds',
          log_group_name = '/aws/rds/instance/aivle-rds/postgresql',
        )
    logsLogStreamAivlerds.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    logsLogStreamAivlerds0 = logs.CfnLogStream(self, 'LogsLogStreamAivlerds0',
          log_stream_name = 'aivle-rds.0',
          log_group_name = '/aws/rds/instance/aivle-rds/postgresql',
        )
    logsLogStreamAivlerds0.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    neptuneDbInstance = neptune.CfnDBInstance(self, 'NeptuneDBInstance',
          db_parameter_group_name = 'default.postgres18',
          db_instance_class = 'db.t3.micro',
          availability_zone = 'ap-northeast-2a',
          preferred_maintenance_window = 'tue:17:05-tue:17:35',
          auto_minor_version_upgrade = True,
          db_subnet_group_name = 'aivle-db-subnet-group',
          db_instance_identifier = 'aivle-rds',
          tags = [
            {
              'value': 'aivle-rds',
              'key': 'Name',
            },
            {
              'value': 'data-tier',
              'key': 'Service',
            },
            {
              'value': 'aivle-dynamic-pricing',
              'key': 'Project',
            },
          ],
        )
    neptuneDbInstance.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    neptuneDbSubnetGroupAivledbsubnetgroup = neptune.CfnDBSubnetGroup(self, 'NeptuneDBSubnetGroupAivledbsubnetgroup',
          db_subnet_group_description = 'Private DB subnets for AIVLE Data Tier',
          subnet_ids = [
            'subnet-00228edc0010713a8',
            'subnet-01974946b167eb88a',
          ],
          db_subnet_group_name = 'aivle-db-subnet-group',
        )
    neptuneDbSubnetGroupAivledbsubnetgroup.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    rdsdbInstance = rds.CfnDBInstance(self, 'RDSDBInstance',
          storage_encrypted = True,
          port = '5432',
          storage_throughput = 125,
          preferred_backup_window = '18:35-19:05',
          monitoring_interval = 0,
          db_parameter_group_name = 'default.postgres18',
          network_type = 'IPV4',
          dedicated_log_volume = False,
          copy_tags_to_snapshot = True,
          multi_az = False,
          engine = 'postgres',
          tags = [
            {
              'value': 'aivle-dynamic-pricing',
              'key': 'Project',
            },
            {
              'value': 'data-tier',
              'key': 'Service',
            },
            {
              'value': 'aivle-rds',
              'key': 'Name',
            },
          ],
          performance_insights_kms_key_id = 'arn:aws:kms:ap-northeast-2:188876037193:key/b3670dbc-9ae9-45b5-b461-060af00130b4',
          license_model = 'postgresql-license',
          engine_version = '18.3',
          storage_type = 'gp3',
          kms_key_id = 'arn:aws:kms:ap-northeast-2:188876037193:key/b3670dbc-9ae9-45b5-b461-060af00130b4',
          db_instance_class = 'db.t3.micro',
          performance_insights_retention_period = 7,
          availability_zone = 'ap-northeast-2a',
          option_group_name = 'default:postgres-18',
          preferred_maintenance_window = 'tue:17:05-tue:17:35',
          enable_performance_insights = True,
          auto_minor_version_upgrade = True,
          db_subnet_group_name = 'aivle-db-subnet-group',
          deletion_protection = False,
          iops = 3000,
          db_instance_identifier = 'aivle-rds',
          allocated_storage = '20',
          ca_certificate_identifier = 'rds-ca-rsa2048-g1',
          manage_master_user_password = True,
          master_user_secret = {
            'kmsKeyId': 'arn:aws:kms:ap-northeast-2:188876037193:key/b833f516-9cd6-4ba2-ad1c-abb9844ebcb2',
          },
          vpc_security_groups = [
            'sg-034317ebd1d603169',
          ],
          master_username = 'db_admin',
          max_allocated_storage = 22,
          db_name = 'aivle_db',
          enable_iam_database_authentication = False,
          publicly_accessible = False,
          backup_retention_period = 1,
          enable_cloudwatch_logs_exports = [
            'postgresql',
            'upgrade',
          ],
        )
    rdsdbInstance.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    rdsdbParameterGroupDefaultpostgres18 = rds.CfnDBParameterGroup(self, 'RDSDBParameterGroupDefaultpostgres18',
          db_parameter_group_name = 'default.postgres18',
          family = 'postgres18',
          description = 'Default parameter group for postgres18',
        )
    rdsdbParameterGroupDefaultpostgres18.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    rdsdbSubnetGroupAivledbsubnetgroup = rds.CfnDBSubnetGroup(self, 'RDSDBSubnetGroupAivledbsubnetgroup',
          db_subnet_group_description = 'Private DB subnets for AIVLE Data Tier',
          subnet_ids = [
            'subnet-00228edc0010713a8',
            'subnet-01974946b167eb88a',
          ],
          db_subnet_group_name = 'aivle-db-subnet-group',
        )
    rdsdbSubnetGroupAivledbsubnetgroup.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    s3BucketAivledbreset188876037193apnortheast2 = s3.CfnBucket(self, 'S3BucketAivledbreset188876037193apnortheast2',
          public_access_block_configuration = {
            'restrictPublicBuckets': True,
            'ignorePublicAcls': True,
            'blockPublicPolicy': True,
            'blockPublicAcls': True,
          },
          bucket_name = 'aivle-db-reset-188876037193-ap-northeast-2',
          ownership_controls = {
            'rules': [
              {
                'objectOwnership': 'BucketOwnerEnforced',
              },
            ],
          },
          bucket_encryption = {
            'serverSideEncryptionConfiguration': [
              {
                'bucketKeyEnabled': True,
                'serverSideEncryptionByDefault': {
                  'sseAlgorithm': 'AES256',
                },
              },
            ],
          },
        )
    s3BucketAivledbreset188876037193apnortheast2.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    s3BucketAivledevsagemakerartifacts188876037193 = s3.CfnBucket(self, 'S3BucketAivledevsagemakerartifacts188876037193',
          public_access_block_configuration = {
            'restrictPublicBuckets': True,
            'ignorePublicAcls': True,
            'blockPublicPolicy': True,
            'blockPublicAcls': True,
          },
          bucket_name = 'aivle-dev-sagemaker-artifacts-188876037193',
          ownership_controls = {
            'rules': [
              {
                'objectOwnership': 'BucketOwnerEnforced',
              },
            ],
          },
          bucket_encryption = {
            'serverSideEncryptionConfiguration': [
              {
                'bucketKeyEnabled': True,
                'serverSideEncryptionByDefault': {
                  'sseAlgorithm': 'AES256',
                },
              },
            ],
          },
        )
    s3BucketAivledevsagemakerartifacts188876037193.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    s3BucketAivledynamicpricingml188876037193dev = s3.CfnBucket(self, 'S3BucketAivledynamicpricingml188876037193dev',
          public_access_block_configuration = {
            'restrictPublicBuckets': True,
            'ignorePublicAcls': True,
            'blockPublicPolicy': True,
            'blockPublicAcls': True,
          },
          bucket_name = 'aivle-dynamic-pricing-ml-188876037193-dev',
          ownership_controls = {
            'rules': [
              {
                'objectOwnership': 'BucketOwnerEnforced',
              },
            ],
          },
          bucket_encryption = {
            'serverSideEncryptionConfiguration': [
              {
                'bucketKeyEnabled': True,
                'serverSideEncryptionByDefault': {
                  'sseAlgorithm': 'AES256',
                },
              },
            ],
          },
          versioning_configuration = {
            'status': 'Enabled',
          },
          tags = [
            {
              'value': 'aivle-dynamic-pricing',
              'key': 'Project',
            },
            {
              'value': 'dev',
              'key': 'Environment',
            },
            {
              'value': 'data-tier',
              'key': 'Service',
            },
            {
              'value': 'ml-data-and-artifacts',
              'key': 'Purpose',
            },
            {
              'value': 'aivle-dynamic-pricing-ml-dev',
              'key': 'Name',
            },
          ],
        )
    s3BucketAivledynamicpricingml188876037193dev.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    s3BucketAivlewebgitupdates3188876037193 = s3.CfnBucket(self, 'S3BucketAivlewebgitupdates3188876037193',
          public_access_block_configuration = {
            'restrictPublicBuckets': True,
            'ignorePublicAcls': True,
            'blockPublicPolicy': True,
            'blockPublicAcls': True,
          },
          lifecycle_configuration = {
            'transitionDefaultMinimumObjectSize': 'all_storage_classes_128K',
            'rules': [
              {
                'status': 'Enabled',
                'id': 'delete-old-frontend-artifacts',
                'prefix': 'releases/',
                'expirationInDays': 14,
              },
            ],
          },
          bucket_name = 'aivle-web-git-update-s3-1888-7603-7193',
          ownership_controls = {
            'rules': [
              {
                'objectOwnership': 'BucketOwnerEnforced',
              },
            ],
          },
          bucket_encryption = {
            'serverSideEncryptionConfiguration': [
              {
                'bucketKeyEnabled': True,
                'serverSideEncryptionByDefault': {
                  'sseAlgorithm': 'AES256',
                },
              },
            ],
          },
        )
    s3BucketAivlewebgitupdates3188876037193.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    s3BucketPolicyAivledynamicpricingml188876037193dev = s3.CfnBucketPolicy(self, 'S3BucketPolicyAivledynamicpricingml188876037193dev',
          bucket = 'aivle-dynamic-pricing-ml-188876037193-dev',
          policy_document = {
            'Version': '2012-10-17',
            'Statement': [
              {
                'Condition': {
                  'Bool': {
                    'aws:SecureTransport': 'false',
                  },
                },
                'Resource': [
                  'arn:aws:s3:::aivle-dynamic-pricing-ml-188876037193-dev',
                  'arn:aws:s3:::aivle-dynamic-pricing-ml-188876037193-dev/*',
                ],
                'Action': 's3:*',
                'Effect': 'Deny',
                'Principal': '*',
                'Sid': 'DenyInsecureTransport',
              },
            ],
          },
        )
    s3BucketPolicyAivledynamicpricingml188876037193dev.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    s3BucketPolicyAivlepricingmodelfoundatipricingmodelartifactbuckqckoozxnjioi = s3.CfnBucketPolicy(self, 'S3BucketPolicyAivlepricingmodelfoundatipricingmodelartifactbuckqckoozxnjioi',
          bucket = 'aivlepricingmodelfoundati-pricingmodelartifactbuck-qckoozxnjioi',
          policy_document = {
            'Version': '2012-10-17',
            'Statement': [
              {
                'Condition': {
                  'Bool': {
                    'aws:SecureTransport': 'false',
                  },
                },
                'Resource': [
                  'arn:aws:s3:::aivlepricingmodelfoundati-pricingmodelartifactbuck-qckoozxnjioi',
                  'arn:aws:s3:::aivlepricingmodelfoundati-pricingmodelartifactbuck-qckoozxnjioi/*',
                ],
                'Action': 's3:*',
                'Effect': 'Deny',
                'Principal': {
                  'AWS': '*',
                },
              },
            ],
          },
        )
    s3BucketPolicyAivlepricingmodelfoundatipricingmodelartifactbuckqckoozxnjioi.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    s3BucketPolicyAwssamclimanageddefaultsamclisourcebucket4hjufpdzyyuw = s3.CfnBucketPolicy(self, 'S3BucketPolicyAwssamclimanageddefaultsamclisourcebucket4hjufpdzyyuw',
          bucket = 'aws-sam-cli-managed-default-samclisourcebucket-4hjufpdzyyuw',
          policy_document = {
            'Version': '2008-10-17',
            'Statement': [
              {
                'Condition': {
                  'StringEquals': {
                    'aws:SourceAccount': '188876037193',
                  },
                },
                'Resource': 'arn:aws:s3:::aws-sam-cli-managed-default-samclisourcebucket-4hjufpdzyyuw/*',
                'Action': 's3:GetObject',
                'Effect': 'Allow',
                'Principal': {
                  'Service': 'serverlessrepo.amazonaws.com',
                },
              },
              {
                'Condition': {
                  'Bool': {
                    'aws:SecureTransport': 'false',
                  },
                },
                'Resource': [
                  'arn:aws:s3:::aws-sam-cli-managed-default-samclisourcebucket-4hjufpdzyyuw',
                  'arn:aws:s3:::aws-sam-cli-managed-default-samclisourcebucket-4hjufpdzyyuw/*',
                ],
                'Action': 's3:*',
                'Effect': 'Deny',
                'Principal': '*',
              },
            ],
          },
        )
    s3BucketPolicyAwssamclimanageddefaultsamclisourcebucket4hjufpdzyyuw.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    s3BucketPolicyCdkhnb659fdsassets188876037193apnortheast2 = s3.CfnBucketPolicy(self, 'S3BucketPolicyCdkhnb659fdsassets188876037193apnortheast2',
          bucket = 'cdk-hnb659fds-assets-188876037193-ap-northeast-2',
          policy_document = {
            'Version': '2012-10-17',
            'Statement': [
              {
                'Condition': {
                  'Bool': {
                    'aws:SecureTransport': 'false',
                  },
                },
                'Resource': [
                  'arn:aws:s3:::cdk-hnb659fds-assets-188876037193-ap-northeast-2',
                  'arn:aws:s3:::cdk-hnb659fds-assets-188876037193-ap-northeast-2/*',
                ],
                'Action': 's3:*',
                'Effect': 'Deny',
                'Principal': '*',
                'Sid': 'AllowSSLRequestsOnly',
              },
            ],
            'Id': 'AccessControl',
          },
        )
    s3BucketPolicyCdkhnb659fdsassets188876037193apnortheast2.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    sqsQueueAivledevinventoryrawqueue = sqs.CfnQueue(self, 'SQSQueueAivledevinventoryrawqueue',
          sqs_managed_sse_enabled = True,
          receive_message_wait_time_seconds = 20,
          delay_seconds = 0,
          redrive_policy = {
            'deadLetterTargetArn': 'arn:aws:sqs:ap-northeast-2:188876037193:aivle-dev-inventory-raw-dlq',
            'maxReceiveCount': 3,
          },
          message_retention_period = 86400,
          maximum_message_size = 1048576,
          visibility_timeout = 180,
          queue_name = 'aivle-dev-inventory-raw-queue',
        )
    sqsQueueAivledevinventoryrawqueue.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    sqsQueueAivledevmodelinputqueue = sqs.CfnQueue(self, 'SQSQueueAivledevmodelinputqueue',
          sqs_managed_sse_enabled = True,
          receive_message_wait_time_seconds = 0,
          delay_seconds = 0,
          redrive_policy = {
            'deadLetterTargetArn': 'arn:aws:sqs:ap-northeast-2:188876037193:aivle-dev-model-input-dlq',
            'maxReceiveCount': 3,
          },
          message_retention_period = 86400,
          maximum_message_size = 1048576,
          visibility_timeout = 720,
          queue_name = 'aivle-dev-model-input-queue',
        )
    sqsQueueAivledevmodelinputqueue.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    schedulerScheduleAivledevscheduleinventoryextractor = scheduler.CfnSchedule(self, 'SchedulerScheduleAivledevscheduleinventoryextractor',
          group_name = 'default',
          schedule_expression = 'rate(10 minutes)',
          target = {
            'input': '{\"trigger\":\"scheduled\"}',
            'arn': 'arn:aws:lambda:ap-northeast-2:188876037193:function:aivle-dev-lambda-inventory-extractor',
            'retryPolicy': {
              'maximumEventAgeInSeconds': 600,
              'maximumRetryAttempts': 1,
            },
            'roleArn': 'arn:aws:iam::188876037193:role/service-role/Amazon_EventBridge_Scheduler_LAMBDA_6817b57ba0',
          },
          state = 'DISABLED',
          flexible_time_window = {
            'mode': 'OFF',
          },
          schedule_expression_timezone = 'Asia/Seoul',
          name = 'aivle-dev-schedule-inventory-extractor',
        )
    schedulerScheduleAivledevscheduleinventoryextractor.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    secretsManagerSecret = secretsmanager.CfnSecret(self, 'SecretsManagerSecret',
          description = 'Shared PostgreSQL credentials for AIVLE Application and AI services',
          tags = [
            {
              'value': 'aivle-rds',
              'key': 'Database',
            },
            {
              'value': 'aivle-dynamic-pricing',
              'key': 'Project',
            },
          ],
          name = 'aivle-rds-service-secret',
        )
    secretsManagerSecret.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

    secretsManagerSecretTargetAttachment = secretsmanager.CfnSecretTargetAttachment(self, 'SecretsManagerSecretTargetAttachment',
          target_type = 'AWS::RDS::DBInstance',
          target_id = 'aivle-rds',
          secret_id = 'arn:aws:secretsmanager:ap-northeast-2:188876037193:secret:aivle-rds-service-secret-E3klki',
        )
    secretsManagerSecretTargetAttachment.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN
