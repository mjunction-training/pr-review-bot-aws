import json
import logging
import os
import re
from typing import List, Dict

import boto3
from pydantic import BaseModel

from github_utils import GitHubUtils # Assuming github_utils.py is available in the Lambda deployment package
from secret_utils import SecretUtils # Import SecretUtils

logger = logging.getLogger(__name__)


class Comment(BaseModel):
    file: str
    line: int
    comment: str


class SecurityIssue(BaseModel):
    file: str
    line: int
    issue: str


class ParsedReviewOutput(BaseModel):
    summary: str
    comments: List[Comment]
    security_issues: List[SecurityIssue]


class MCPClient:
    def __init__(self, github_utils: GitHubUtils, secret_utils: SecretUtils):
        self.github_utils = github_utils
        self.secret_utils = secret_utils

        # Retrieve AWS region from environment or secrets (if configured there)
        self.aws_region = os.getenv('AWS_REGION', 'us-east-1') # Default to env var, can be moved to secrets if desired
        
        # Retrieve Bedrock model ID from environment or secrets
        # Prioritize secret if available, otherwise fallback to environment variable
        self.bedrock_model_id = self.secret_utils.get_bedrock_model_id() or \
                                os.getenv('BEDROCK_MODEL_ID', 'anthropic.claude-3-sonnet-20240229-v1:0')
        
        self.bedrock_client = boto3.client(
            service_name='bedrock-runtime',
            region_name=self.aws_region
        )
        logger.info(f"Initialized Bedrock client for region: {self.aws_region} with model: {self.bedrock_model_id}")


    @staticmethod
    def load_guidelines() -> str:
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            guidelines_path = os.path.join(current_dir, "guidelines.md")
            with open(guidelines_path, "r") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to load guidelines in mcp_client: {str(e)}", exc_info=True)
            return ""


    @staticmethod
    def build_review_prompt(repo: str, pr_id: int, guidelines: str, diff: str) -> str:
        review_prompt_content = f"""
            Human: You are an expert code reviewer who reviews GitHub Pull Requests.
            Your task is to provide a comprehensive code review based on the provided guidelines and code changes.
            Focus on identifying potential bugs, security vulnerabilities, performance issues, and maintainability concerns.
            Provide actionable suggestions and code examples where appropriate.

            <review_guidelines>
            {guidelines}
            </review_guidelines>

            <pr_details>
            Repository: {repo}
            Pull Request ID: {pr_id}
            </pr_details>

            <diff>
            {diff}
            </diff>

            Please provide your review in the following format:
            For regular comments: <file>:<line number>:<comment>
            For security issues: SECURITY:<file>:<line number>:<issue description>

            Assistant:
            """
        return review_prompt_content


    @staticmethod
    def build_summary_prompt(review_raw_text: str) -> str:
        summary_prompt_content = f"""
            Human: Summarize the review comments for the following pull request.
            The comments and security issues to be summarized are provided below.

            <review_raw_text>
            {review_raw_text}
            </review_raw_text>

            Assistant:
            """
        return summary_prompt_content


    @staticmethod
    def parse_review_output(text: str) -> tuple[List[Dict], List[Dict]]:
        comments = []
        security_issues = []

        lines = text.strip().split('\n')

        for line in lines:
            line = line.strip()
            security_match = re.match(r"SECURITY:([^:]+):(\d+):(.+)", line)
            comment_match = re.match(r"([^:]+):(\d+):(.+)", line)

            if security_match:
                try:
                    file, line_num, issue = security_match.groups()
                    security_issues.append({
                        "file": file.strip(),
                        "line": int(line_num.strip()),
                        "issue": issue.strip()
                    })
                except ValueError:
                    logger.warning(f"Could not parse security issue line: {line}")
            elif comment_match:
                try:
                    file, line_num, comment = comment_match.groups()
                    comments.append({
                        "file": file.strip(),
                        "line": int(line_num.strip()),
                        "comment": comment.strip()
                    })
                except ValueError:
                    logger.warning(f"Could not parse comment line: {line}")
            else:
                logger.warning(f"Line did not match expected comment or security issue format: {line}")
        return comments, security_issues


    async def send_review_request(self, pr_details: dict) -> ParsedReviewOutput | None:
        pr_id = pr_details.get('pr_id', 0)
        repo = f"{pr_details.get('repo_owner', 'N/A')}/{pr_details.get('repo_name', 'N/A')}"
        try:
            installation_id = pr_details['installation_id']
            access_token = self.github_utils.get_installation_token(installation_id)

            if not access_token:
                logger.error(f"No access token available for fetching diff for PR #{pr_id}.")
                return None

            diff_content = self.github_utils.get_pr_diff(pr_details['diff_url'], access_token)

            if not diff_content:
                logger.warning(f"Diff content for PR #{pr_id} is empty. Skipping review.")
                return None

            guidelines = self.load_guidelines()
            if not guidelines:
                logger.warning(f"Guidelines content for PR #{pr_id} is empty. Review might be less effective.")

            logger.info(f"Building review prompt for PR #{pr_id}.")
            review_prompt_string = self.build_review_prompt(
                repo=repo,
                pr_id=pr_id,
                guidelines=guidelines,
                diff=diff_content
            )
            logger.debug(f"Review prompt built. Length: {len(review_prompt_string)} chars.")

            try:
                body = json.dumps({
                    "prompt": review_prompt_string,
                    "max_tokens_to_sample": 4000,
                    "temperature": 0.2,
                    "top_p": 0.9
                })
                response = self.bedrock_client.invoke_model(
                    modelId=self.bedrock_model_id,
                    contentType="application/json",
                    accept="application/json",
                    body=body
                )
                review_raw_text = json.loads(response['body'].read().decode('utf-8'))['completion']
                logger.info(
                    f"Received raw review text from Bedrock for PR #{pr_id}. Length: {len(review_raw_text)} chars.")
                logger.debug(f"Raw review text (first 200 chars): {review_raw_text[:200]}...")

            except Exception as e:
                logger.error(f"Failed to invoke Bedrock for review generation for PR #{pr_id}: {e}", exc_info=True)
                return ParsedReviewOutput(
                    summary="PR review summary - none",
                    comments=[],
                    security_issues=[]
                )

            if not review_raw_text:
                logger.error(
                    f"Failed to get valid raw review text from Bedrock for PR #{pr_id}.")
                return ParsedReviewOutput(
                    summary="PR review summary - none",
                    comments=[],
                    security_issues=[]
                )

            logger.info(f"Building summary prompt for PR #{pr_id}.")
            summary_prompt_string = self.build_summary_prompt(review_raw_text=review_raw_text)
            logger.debug(f"Summary prompt built. Length: {len(summary_prompt_string)} chars.")

            summary_final_text = "No summary generated."
            try:
                body = json.dumps({
                    "prompt": summary_prompt_string,
                    "max_tokens_to_sample": 1000,
                    "temperature": 0.2,
                    "top_p": 0.9
                })
                response = self.bedrock_client.invoke_model(
                    modelId=self.bedrock_model_id,
                    contentType="application/json",
                    accept="application/json",
                    body=body
                )
                summary_final_text = json.loads(response['body'].read().decode('utf-8'))['completion'].strip()
                logger.info(f"Received summary text from Bedrock for PR #{pr_id}.")
                logger.debug(f"Summary text (first 100 chars): {summary_final_text[:100]}...")
            except Exception as e:
                logger.warning(f"Failed to invoke Bedrock for summary generation for PR #{pr_id}: {e}", exc_info=True)


            logger.info(f"Parsing review output for PR #{pr_id}.")
            comments, security_issues = self.parse_review_output(review_raw_text)
            logger.info(f"Parsed {len(comments)} comments and {len(security_issues)} security issues for PR #{pr_id}.")

            return ParsedReviewOutput(
                summary=summary_final_text,
                comments=[Comment(**c) for c in comments],
                security_issues=[SecurityIssue(**s) for s in security_issues]
            )

        except Exception as e:
            logger.error(f"Failed to get review payload for PR #{pr_id} from Bedrock: {str(e)}", exc_info=True)
        return ParsedReviewOutput(
                summary="PR review summary - none",
                comments=[],
                security_issues=[]
            )


    def check_bedrock_health(self) -> str:
        try:
            self.bedrock_client.list_foundation_models(maxResults=1)
            logger.info("Bedrock service health check successful.")
            return "reachable"
        except Exception as e:
            logger.error(f"Bedrock service health check failed: {e}", exc_info=True)
            return f"unreachable (error: {e})"

