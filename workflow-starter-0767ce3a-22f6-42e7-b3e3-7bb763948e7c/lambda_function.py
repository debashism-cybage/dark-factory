import json
import boto3
import os
import uuid

stepfunctions = boto3.client("stepfunctions")

STATE_MACHINE_ARN = os.environ["STATE_MACHINE_ARN"]


def lambda_handler(event, context):

    print("Incoming Event:")
    print(json.dumps(event, indent=2))

    body = event

    # API Gateway sends body as a string
    if "body" in event:
        body = json.loads(event["body"], strict=False)

    ticket_id = body.get("ticketId")

    if not ticket_id:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "message": "ticketId is required"
            })
        }

    workflow = {
        "workflowId": f"WF-{uuid.uuid4().hex[:8].upper()}",
        "ticketId": ticket_id,
        "summary": body.get("summary", ""),
        "description": body.get("description", ""),
        "priority": body.get("priority", ""),
        "issueType": body.get("issueType", ""),
        "project": body.get("project", ""),
        "assignee": body.get("assignee", ""),
        "status": "STARTED"
    }

    response = stepfunctions.start_execution(
        stateMachineArn=STATE_MACHINE_ARN,
        input=json.dumps(workflow)
    )

    print("Execution Started:")
    print(response["executionArn"])

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Workflow Started",
            "workflowId": workflow["workflowId"],
            "executionArn": response["executionArn"]
        })
    }