import json
import os
from decimal import Decimal
from bedrock_client import BedrockClient

import boto3

from github_client import GitHubClient

dynamodb = boto3.resource("dynamodb")
s3 = boto3.client("s3")
secrets = boto3.client("secretsmanager")

TABLE_NAME = os.environ["TABLE_NAME"]
BUCKET_NAME = os.environ["BUCKET_NAME"]

GITHUB_SECRET_NAME = os.environ["GITHUB_SECRET_NAME"]
GITHUB_REPO_OWNER = os.environ["GITHUB_REPO_OWNER"]
GITHUB_REPO_NAME = os.environ["GITHUB_REPO_NAME"]
MODEL_ID = os.environ["BEDROCK_MODEL_ID"]

table = dynamodb.Table(TABLE_NAME)


def get_github_client():

    secret = secrets.get_secret_value(
        SecretId=GITHUB_SECRET_NAME
    )

    token = json.loads(
        secret["SecretString"]
    )["GITHUB_TOKEN"]

    return GitHubClient(
        token=token,
        owner=GITHUB_REPO_OWNER,
        repo=GITHUB_REPO_NAME
    )


def lambda_handler(event, context):

    print(json.dumps(event, indent=2))
    event.setdefault("artifacts", {})

    workflow_id = event["workflowId"]
    ticket_id = event["ticketId"]

    github = get_github_client()

    branch = f"feature/{ticket_id}"

    github.ensure_branch(branch)

    client = BedrockClient(MODEL_ID)

    generated_files = []

    last_commit = None

    for file_path in event["planning"]["filesToGenerate"]:

        print(f"Generating {file_path}")

        code = client.generate_code(event, file_path)

        last_commit = github.commit_file(
            branch=branch,
            path=file_path,
            content=code,
            message=f"AI Generated {file_path}"
        )

        generated_files.append({
            "path": file_path,
            "size": len(code)
        })

    generated_code = {
        "language": "Angular",
        "files": generated_files
    }

    s3_key = f"artifacts/{workflow_id}-generated-code.json"

    s3.put_object(
        Bucket=BUCKET_NAME,
        Key=s3_key,
        Body=json.dumps(generated_code, indent=2),
        ContentType="application/json"
    )

    pr = github.ensure_pull_request(
        branch=branch,
        ticket_id=ticket_id,
        workflow_id=workflow_id
    )

    event["status"] = "DEVELOPMENT_COMPLETE"
    event["currentAgent"] = "development-agent"

    event["artifacts"]["generatedCode"] = s3_key
    event["artifacts"]["repository"] = f"{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}"
    event["artifacts"]["branch"] = branch
    event["artifacts"]["commitSha"] = (
        last_commit["commit"]["sha"]
        if last_commit
        else ""
    )
    event["artifacts"]["pullRequest"] = pr["url"]
    event["artifacts"]["pullRequestNumber"] = pr["number"]

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
            ":status": "DEVELOPMENT_COMPLETE",
            ":agent": "development-agent",
            ":artifacts": json.loads(
                json.dumps(event["artifacts"]),
                parse_float=Decimal
            )
        }
    )

    return event