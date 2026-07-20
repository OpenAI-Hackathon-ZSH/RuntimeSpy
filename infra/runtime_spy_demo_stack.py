"""Public EC2 infrastructure for the RuntimeSpy commerce demo."""

from __future__ import annotations

import os
from pathlib import Path
import shlex

from aws_cdk import (
    CfnOutput,
    Stack,
    Tags,
    aws_ec2 as ec2,
    aws_ecr_assets as ecr_assets,
)
from constructs import Construct


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_ENDPOINT = "http://34.226.45.56:8000"


class RuntimeSpyDemoStack(Stack):
    """Build the demo image and run it on a public EC2 instance."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs: object) -> None:
        super().__init__(scope, construct_id, **kwargs)

        image = ecr_assets.DockerImageAsset(
            self,
            "CommerceDemoImage",
            directory=str(REPOSITORY_ROOT),
            file="demo/Dockerfile",
            platform=ecr_assets.Platform.LINUX_AMD64,
        )

        vpc = ec2.Vpc(
            self,
            "CommerceDemoVpc",
            ip_addresses=ec2.IpAddresses.cidr("10.42.0.0/16"),
            max_azs=1,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                )
            ],
            restrict_default_security_group=True,
        )

        report_endpoint = (
            os.environ.get("RUNTIMESPY_REPORT_ENDPOINT", "").strip()
            or DEFAULT_REPORT_ENDPOINT
        )
        endpoint_environment = shlex.quote(
            f"RUNTIMESPY_REPORT_ENDPOINT={report_endpoint}"
        )

        security_group = ec2.SecurityGroup(
            self,
            "CommerceDemoSecurityGroup",
            vpc=vpc,
            description="Allow public HTTP access to the RuntimeSpy commerce demo",
            allow_all_outbound=True,
        )
        security_group.add_ingress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(80),
            "Public HTTP",
        )

        user_data = ec2.UserData.for_linux()
        user_data.add_commands(
            "set -euxo pipefail",
            "dnf install -y docker",
            "systemctl enable --now docker",
            (
                f"aws ecr get-login-password --region {Stack.of(self).region} "
                f"| docker login --username AWS --password-stdin "
                f"{image.repository.repository_uri}"
            ),
            f"docker pull {image.image_uri}",
            "docker rm --force runtimespy-commerce-demo || true",
            (
                "docker run --detach "
                "--name runtimespy-commerce-demo "
                "--restart unless-stopped "
                "--publish 80:8080 "
                f"--env {endpoint_environment} "
                f"{image.image_uri}"
            ),
        )

        instance = ec2.Instance(
            self,
            "CommerceDemoInstance",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.T3,
                ec2.InstanceSize.MICRO,
            ),
            machine_image=ec2.MachineImage.latest_amazon_linux2023(
                cpu_type=ec2.AmazonLinuxCpuType.X86_64,
            ),
            security_group=security_group,
            associate_public_ip_address=True,
            require_imdsv2=True,
            ssm_session_permissions=True,
            user_data=user_data,
            user_data_causes_replacement=True,
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/xvda",
                    volume=ec2.BlockDeviceVolume.ebs(
                        8,
                        encrypted=True,
                        volume_type=ec2.EbsDeviceVolumeType.GP3,
                    ),
                )
            ],
        )
        image.repository.grant_pull(instance.role)

        elastic_ip = ec2.CfnEIP(
            self,
            "CommerceDemoElasticIp",
            domain="vpc",
            instance_id=instance.instance_id,
        )
        elastic_ip.node.add_dependency(vpc.internet_connectivity_established)

        Tags.of(self).add("Project", "RuntimeSpy")

        CfnOutput(
            self,
            "InstanceId",
            value=instance.instance_id,
            description="RuntimeSpy commerce demo EC2 instance ID",
        )
        CfnOutput(
            self,
            "PublicIp",
            value=elastic_ip.ref,
            description="Static public IPv4 address",
        )
        CfnOutput(
            self,
            "ServiceUrl",
            value=f"http://{elastic_ip.ref}",
            description="Public RuntimeSpy commerce demo URL",
        )
        CfnOutput(
            self,
            "SwaggerUrl",
            value=f"http://{elastic_ip.ref}/docs/",
            description="Swagger UI for the deployed commerce demo",
        )
