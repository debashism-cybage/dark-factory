import json
import boto3


class BedrockClient:

    def __init__(self, model_id):
        self.model_id = model_id
        self.client = boto3.client("bedrock-runtime")

    def converse(self, system_prompt, user_prompt):

        response = self.client.converse(
            modelId=self.model_id,
            system=[
                {
                    "text": system_prompt
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "text": user_prompt
                        }
                    ]
                }
            ]
        )

        return response["output"]["message"]["content"][0]["text"]

    def generate_plan(self, workflow):

        prompt = f"""
Generate a detailed implementation plan.

Return ONLY a valid JSON object.

Use EXACTLY the schema below.
Do not add extra fields.
Do not rename fields.
Do not wrap the response in markdown.

Ticket ID:
{workflow.get("ticketId")}

Summary:
{workflow.get("summary")}

Description:
{workflow.get("description")}

Priority:
{workflow.get("priority")}

Issue Type:
{workflow.get("issueType")}

Schema:

{{
  "summary": "",
  "requirements": [],
  "acceptanceCriteria": [],
  "implementationPlan": [],
  "testCases": [],
  "affectedModules": [],
  "technologies": [],
  "filesToGenerate": []
}}
"""

        response = self.converse(
            "You are a senior software architect.",
            prompt
        )

        response = response.strip()

        if response.startswith("```"):
            response = response.split("\n", 1)[1]
            response = response.rsplit("```", 1)[0]

        return json.loads(response.strip())

    def generate_code(self, workflow, file_path):

        planning = workflow["planning"]

        prompt = f"""
You are a senior Angular developer.

Generate COMPLETE production-ready code.

File to generate:

{file_path}

Project Summary:
{planning["summary"]}

Requirements:
{json.dumps(planning["requirements"], indent=2)}

Acceptance Criteria:
{json.dumps(planning["acceptanceCriteria"], indent=2)}

Implementation Plan:
{json.dumps(planning["implementationPlan"], indent=2)}

Technologies:
{json.dumps(planning["technologies"], indent=2)}

Return ONLY the file contents.

Do not wrap in markdown.
Do not use ``` fences.
Do not explain the code.
"""

        return self.converse(
            "You are an expert software engineer.",
            prompt
        ).strip()