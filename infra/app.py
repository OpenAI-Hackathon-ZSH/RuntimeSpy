"""CDK application entry point for the RuntimeSpy commerce demo."""

from __future__ import annotations

import os

from aws_cdk import App, Environment

from runtime_spy_demo_stack import RuntimeSpyDemoStack


app = App()
RuntimeSpyDemoStack(
    app,
    "RuntimeSpyDemo",
    env=Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION"),
    ),
)
app.synth()
