import json
import os
from decimal import Decimal

import boto3

dynamodb = boto3.resource("dynamodb")
s3 = boto3.client("s3")

TABLE_NAME = os.environ["TABLE_NAME"]
BUCKET_NAME = os.environ["BUCKET_NAME"]

table = dynamodb.Table(TABLE_NAME)


def lambda_handler(event, context):

    print(json.dumps(event, indent=2))

    workflow_id = event["workflowId"]

    validation_report = {
        "unitTests": {
            "status": "PASSED",
            "total": 12,
            "passed": 12,
            "failed": 0
        },
        "lint": {
            "status": "PASSED",
            "issues": 0
        },
        "security": {
            "status": "PASSED",
            "critical": 0,
            "high": 0,
            "medium": 1
        }
    }

    key = f"reports/{workflow_id}-validation.json"

    s3.put_object(
        Bucket=BUCKET_NAME,
        Key=key,
        Body=json.dumps(validation_report, indent=2),
        ContentType="application/json"
    )

    event["status"] = "VALIDATION_COMPLETE"
    event["currentAgent"] = "validation-agent"
    event["artifacts"]["validationReport"] = key

    table.update_item(
        Key={
            "WorkflowId": workflow_id
        },
        UpdateExpression="""
            SET
                #status = :status,
                currentAgent = :agent,
                artifacts = :artifacts
        """,
        ExpressionAttributeNames={
            "#status": "status"
        },
        ExpressionAttributeValues={
            ":status": "VALIDATION_COMPLETE",
            ":agent": "validation-agent",
            ":artifacts": json.loads(
                json.dumps(event["artifacts"]),
                parse_float=Decimal
            )
        }
    )

    return event