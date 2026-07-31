import json
import os
from decimal import Decimal
from datetime import datetime, timezone

import boto3

dynamodb = boto3.resource("dynamodb")
s3 = boto3.client("s3")

TABLE_NAME = os.environ["TABLE_NAME"]
BUCKET_NAME = os.environ["BUCKET_NAME"]

table = dynamodb.Table(TABLE_NAME)


def current_time():
    return datetime.now(timezone.utc).isoformat()


def lambda_handler(event, context):

    print(json.dumps(event, indent=2))

    workflow_id = event["workflowId"]

    release_notes = {
        "workflowId": workflow_id,
        "ticketId": event["ticketId"],
        "releasedAt": current_time(),
        "version": "v1.0.0",
        "summary": event["planning"]["summary"],
        "artifacts": event["artifacts"],
        "deployment": {
            "status": "SUCCESS",
            "environment": "DEV"
        }
    }

    key = f"release-notes/{workflow_id}-release.json"

    s3.put_object(
        Bucket=BUCKET_NAME,
        Key=key,
        Body=json.dumps(release_notes, indent=2),
        ContentType="application/json"
    )

    event["status"] = "COMPLETED"
    event["currentAgent"] = "release-agent"
    event["completedAt"] = current_time()
    event["artifacts"]["releaseNotes"] = key

    table.update_item(
        Key={
            "WorkflowId": workflow_id
        },
        UpdateExpression="""
            SET
                #status = :status,
                currentAgent = :agent,
                completedAt = :completedAt,
                artifacts = :artifacts
        """,
        ExpressionAttributeNames={
            "#status": "status"
        },
        ExpressionAttributeValues={
            ":status": "COMPLETED",
            ":agent": "release-agent",
            ":completedAt": event["completedAt"],
            ":artifacts": json.loads(
                json.dumps(event["artifacts"]),
                parse_float=Decimal
            )
        }
    )

    return event