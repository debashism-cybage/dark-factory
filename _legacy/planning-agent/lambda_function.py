import json
import os
from decimal import Decimal

import boto3

from bedrock_client import BedrockClient

dynamodb = boto3.resource("dynamodb")
s3 = boto3.client("s3")

table = dynamodb.Table(os.environ["TABLE_NAME"])

BUCKET = os.environ["S3_BUCKET"]
MODEL_ID = os.environ["BEDROCK_MODEL_ID"]


def lambda_handler(event, context):

    print(json.dumps(event, indent=2))

    workflow = event

    workflow_id = workflow.get("workflowId")

    if not workflow_id:
        raise ValueError(f"workflowId missing. Event: {json.dumps(workflow)}")

    client = BedrockClient(MODEL_ID)

    try:
        planning = client.generate_plan(workflow)

        planning["confidence"] = Decimal("0.95")

        planning["estimatedFiles"] = max(
            len(planning.get("filesToGenerate", [])),
            len(planning.get("affectedModules", [])) * 2,
            1
        )

    except Exception as e:

        print(e)

        planning = {
            "summary": workflow.get("summary", ""),
            "requirements": [],
            "acceptanceCriteria": [],
            "implementationPlan": [],
            "testCases": [],
            "affectedModules": [],
            "technologies": [],
            "filesToGenerate": [],
            "confidence": Decimal("0.50"),
            "estimatedFiles": 0,
            "error": str(e)
        }

    table.update_item(
        Key={
            "WorkflowId": workflow_id
        },
        UpdateExpression="""
            SET
                #s = :s,
                planning = :p
        """,
        ExpressionAttributeNames={
            "#s": "status"
        },
        ExpressionAttributeValues={
            ":s": "PLANNED",
            ":p": planning
        }
    )

    s3.put_object(
        Bucket=BUCKET,
        Key=f"plans/{workflow_id}.json",
        Body=json.dumps(planning, default=str, indent=2),
        ContentType="application/json"
    )

    workflow["planning"] = planning
    workflow["status"] = "PLANNED"

    return workflow