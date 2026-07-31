import json
import os
import traceback

from bedrock_client import BedrockClient
from github_client import GitHubClient
from s3_helper import S3Helper

MODEL_ID = os.environ["BEDROCK_MODEL_ID"]
BUCKET_NAME = os.environ["BUCKET_NAME"]


def lambda_handler(event, context):

    print("=" * 80)
    print("Architecture Agent Started")
    print(json.dumps(event, indent=2))
    print("=" * 80)

    github = GitHubClient()
    s3 = S3Helper(BUCKET_NAME)
    bedrock = BedrockClient(MODEL_ID)

    try:

        print("Reading repository...")

        repository_summary = github.get_repository_summary()

        repository_tree = github.get_repository_tree()

        project_context = github.get_project_context()

        print(
            f"Repository contains {repository_summary['totalFiles']} files."
        )

        print("Generating architecture...")

        result = bedrock.generate_architecture(
            repository_summary=repository_summary,
            repository_tree=repository_tree,
            project_context=project_context
        )

        print("Uploading documents to S3...")

        s3.upload_architecture_documents(
            result["documents"]
        )

        print("Architecture generation completed successfully.")

        return {
            "status": "SUCCESS",
            "repository": repository_summary["repository"],
            "documents": list(result["documents"].keys())
        }

    except Exception as ex:

        print("Architecture Agent Failed")
        print(str(ex))
        traceback.print_exc()

        return {
            "status": "FAILED",
            "error": str(ex)
        }