#!/usr/bin/env python3
import aws_cdk as cdk
from vpc_endpoints_tester.vpc_endpoints_tester_stack import VpcEndpointsTesterStack

app = cdk.App()

VpcEndpointsTesterStack(
    app,
    "VpcEndpointsTesterStack",
    env=cdk.Environment(
        account=app.node.try_get_context("account"),
        region=app.node.try_get_context("region"),
    ),
)

app.synth()
