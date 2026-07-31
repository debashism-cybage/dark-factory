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
Do not include Ticket ID, Summary, Description, Priority or Issue Type.
Do not wrap the response in markdown.

Populate EVERY field.

For filesToGenerate, include all source files that should be created or modified with realistic filenames.

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

        system_prompt = (
            "You are a senior software architect. "
            "Return only valid JSON. "
            "Do not use markdown or code fences."
        )

        response = self.converse(system_prompt, prompt)

        try:
            response = response.strip()

            if response.startswith("```"):
                response = response.split("\n", 1)[1]
                response = response.rsplit("```", 1)[0]

            response = response.strip()

            return json.loads(response)

        except Exception:
            raise Exception(f"Invalid JSON returned by Bedrock:\n{response}")