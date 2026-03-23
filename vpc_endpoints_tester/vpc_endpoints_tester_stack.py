from aws_cdk import (
    Stack,
    Duration,
    CfnOutput,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_lambda as lambda_,
)
from constructs import Construct


class VpcEndpointsTesterStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        vpc_id = self.node.try_get_context("vpc_id")
        if not vpc_id:
            raise ValueError(
                "vpc_id context variable is required. "
                "Pass it with: cdk deploy -c vpc_id=vpc-xxxxxxxx"
            )

        # Look up existing VPC
        vpc = ec2.Vpc.from_lookup(self, "Vpc", vpc_id=vpc_id)

        # Security group: allow all outbound HTTPS, no inbound needed
        sg = ec2.SecurityGroup(
            self,
            "LambdaSG",
            vpc=vpc,
            description="VPC endpoints tester Lambda - egress HTTPS only",
            allow_all_outbound=False,
        )
        sg.add_egress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(443),
            description="Allow outbound HTTPS to VPC endpoints",
        )

        # IAM role
        role = iam.Role(
            self,
            "LambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaVPCAccessExecutionRole"
                ),
            ],
        )

        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "sagemaker:ListModelPackageGroups",
                    "sagemaker:DescribeModelPackageGroup",
                    "sagemaker:ListModelPackages",
                    "sagemaker:DescribeModelPackage",
                ],
                resources=["*"],
            )
        )

        # Lambda function
        fn = lambda_.Function(
            self,
            "VpcEndpointsTester",
            function_name="vpc-endpoints-tester",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("lambda"),
            role=role,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            security_groups=[sg],
            timeout=Duration.seconds(30),
            description="Tests DNS, TCP, and TLS connectivity to AWS VPC endpoints",
        )

        CfnOutput(self, "FunctionName", value=fn.function_name)
        CfnOutput(self, "FunctionArn", value=fn.function_arn)
