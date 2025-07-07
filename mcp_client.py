import json
import logging
import os
from typing import List, Dict, Optional

import boto3
from pydantic import BaseModel, ValidationError

from github_utils import GitHubUtils
from secret_utils import SecretUtils
from s3_utils import S3Utils

logger = logging.getLogger(__name__)


# --- Pydantic Models for Structured Output ---

class LineComment(BaseModel):
    file: str
    line: int
    comment: str


class GeneralComment(BaseModel):
    comment: str


class SecurityIssue(BaseModel):
    file: str
    line: int
    issue: str
    severity: str  # "SEVERE", "MODERATE", "LOW"


class ParsedReviewOutput(BaseModel):
    summary: str
    line_comments: List[LineComment]
    general_comments: List[GeneralComment]
    security_issues: List[SecurityIssue]


# --- Main Client Class ---

class MCPClient:
    def __init__(self, github_utils: GitHubUtils, secret_utils: SecretUtils, s3_utils: S3Utils):
        self.github_utils = github_utils
        self.secret_utils = secret_utils
        self.s3_utils = s3_utils  # Store S3Utils instance

        self.aws_region = os.getenv('AWS_REGION', 'us-east-1')
        self.bedrock_model_id = self.secret_utils.get_bedrock_model_id() or \
                                os.getenv('BEDROCK_MODEL_ID', 'anthropic.claude-3-sonnet-20240229-v1:0')

        self.bedrock_client = boto3.client(
            service_name='bedrock-runtime',
            region_name=self.aws_region
        )
        logger.info(f"Initialized Bedrock client for region: {self.aws_region} with model: {self.bedrock_model_id}")

        # S3 Knowledge Base configuration
        self.example_projects_s3_prefix = os.getenv('EXAMPLE_PROJECT_S3_PREFIX')
        self.knowledge_base_content = ""
        if self.example_projects_s3_prefix:
            logger.info(f"Loading knowledge base from S3 prefix: {self.example_projects_s3_prefix}")
            self.knowledge_base_content = self.s3_utils.read_project_knowledge_base(self.example_projects_s3_prefix)
            if not self.knowledge_base_content:
                logger.warning("Failed to load knowledge base content from S3. Review quality might be impacted.")
        else:
            logger.info("EXAMPLE_PROJECT_S3_PREFIX not set. Knowledge base from S3 will not be used.")

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

    # --- Prompt Building Functions ---

    def build_initial_analysis_prompt(self, guidelines: str, diff: str) -> str:
        """
        Prompts the LLM to perform an initial analysis of the PR diff
        and identify potential areas for line comments, general comments,
        and security issues. The output should be a JSON structure.
        Includes optional knowledge base.
        """
        knowledge_base_section = ""
        if self.knowledge_base_content:
            knowledge_base_section = f"""
            <knowledge_base_examples>
            You are provided with example project code from a knowledge base.
            Refer to these examples for best practices, common patterns, and context
            when evaluating the pull request. Do NOT copy the examples directly,
            but use them to inform your review and suggestions.

            {self.knowledge_base_content}
            </knowledge_base_examples>
            """

        prompt_content = f"""
            Human: You are an expert code reviewer. Your task is to analyze the provided code changes (diff)
            against the given code review guidelines. Identify potential issues and categorize them.
            Do NOT generate the full comment text yet, just identify the areas.
            {knowledge_base_section}

            <review_guidelines>
            {guidelines}
            </review_guidelines>

            <diff>
            {diff}
            </diff>

            Provide your analysis as a JSON object with the following structure:
            {{
              "potential_line_comments": [
                {{"file": "file_path", "line": line_number, "reason": "brief reason for comment"}}
              ],
              "potential_general_comments": [
                {{"topic": "brief topic for general comment"}}
              ],
              "potential_security_issues": [
                {{"file": "file_path", "line": line_number, "description": "brief description of potential issue"}}
              ]
            }}
            Ensure the output is valid JSON.

            Assistant:
            """
        return prompt_content

    def build_line_comment_prompt(self, guidelines: str, diff: str, identified_issues: List[Dict]) -> str:
        """
        Prompts the LLM to generate detailed line comments for specific identified issues.
        Includes optional knowledge base.
        """
        issues_str = "\n".join(
            [f"- File: {issue['file']}, Line: {issue['line']}, Reason: {issue['reason']}" for issue in
             identified_issues])

        knowledge_base_section = ""
        if self.knowledge_base_content:
            knowledge_base_section = f"""
            <knowledge_base_examples>
            Refer to these example project codes for context and best practices:
            {self.knowledge_base_content}
            </knowledge_base_examples>
            """

        prompt_content = f"""
            Human: You are an expert code reviewer. Based on the provided code changes (diff) and guidelines,
            generate detailed, actionable line-specific comments for the following identified issues.
            Focus on clarity, conciseness, and providing solutions or best practices.
            {knowledge_base_section}

            <review_guidelines>
            {guidelines}
            </review_guidelines>

            <diff>
            {diff}
            </diff>

            <identified_issues>
            {issues_str}
            </identified_issues>

            Provide your detailed line comments as a JSON array of objects, with each object having "file", "line", and "comment" fields.
            Example:
            [
              {{"file": "src/main.py", "line": 15, "comment": "Consider using a context manager here for file handling."}},
              {{"file": "src/utils.js", "line": 30, "comment": "This variable name is ambiguous. Please rename to `userCount`."}}
            ]
            Ensure the output is valid JSON.

            Assistant:
            """
        return prompt_content

    def build_general_comment_prompt(self, guidelines: str, diff: str, identified_topics: List[Dict]) -> str:
        """
        Prompts the LLM to generate detailed general PR comments for specific identified topics.
        Includes optional knowledge base.
        """
        topics_str = "\n".join([f"- Topic: {topic['topic']}" for topic in identified_topics])

        knowledge_base_section = ""
        if self.knowledge_base_content:
            knowledge_base_section = f"""
            <knowledge_base_examples>
            Refer to these example project codes for context and best practices:
            {self.knowledge_base_content}
            </knowledge_base_examples>
            """

        prompt_content = f"""
            Human: You are an expert code reviewer. Based on the provided code changes (diff) and guidelines,
            generate detailed, actionable general comments for the following identified topics.
            These comments should apply to the PR as a whole, not specific lines.
            {knowledge_base_section}

            <review_guidelines>
            {guidelines}
            </review_guidelines>

            <diff>
            {diff}
            </diff>

            <identified_topics>
            {topics_str}
            </identified_topics>

            Provide your general comments as a JSON array of objects, with each object having a "comment" field.
            Example:
            [
              {{"comment": "Overall, the changes introduce a new feature, but consider adding more unit tests for edge cases."}},
              {{"comment": "The commit messages could be more descriptive following Conventional Commits."}}
            ]
            Ensure the output is valid JSON.

            Assistant:
            """
        return prompt_content

    def build_security_issue_prompt(self, guidelines: str, diff: str, identified_issues: List[Dict]) -> str:
        """
        Prompts the LLM to generate detailed security issues with severity for specific identified issues.
        Includes optional knowledge base.
        """
        issues_str = "\n".join(
            [f"- File: {issue['file']}, Line: {issue['line']}, Description: {issue['description']}" for issue in
             identified_issues])

        knowledge_base_section = ""
        if self.knowledge_base_content:
            knowledge_base_section = f"""
            <knowledge_base_examples>
            Refer to these example project codes for context and best practices:
            {self.knowledge_base_content}
            </knowledge_base_examples>
            """

        prompt_content = f"""
            Human: You are an expert security code reviewer. Based on the provided code changes (diff) and guidelines,
            generate detailed security issues for the following identified potential vulnerabilities.
            Assign a severity level to each issue: "SEVERE", "MODERATE", or "LOW".
            Provide actionable recommendations to mitigate the vulnerability.
            {knowledge_base_section}

            <review_guidelines>
            {guidelines}
            </review_guidelines>

            <diff>
            {diff}
            </diff>

            <identified_security_issues>
            {issues_str}
            </identified_security_issues>

            Provide your security issues as a JSON array of objects, with each object having "file", "line", "issue", and "severity" fields.
            Example:
            [
              {{"file": "api/user.py", "line": 25, "issue": "Unsanitized user input used in SQL query, leading to potential SQL Injection.", "severity": "SEVERE"}},
              {{"file": "frontend/auth.js", "line": 100, "issue": "Client-side password validation without server-side validation.", "severity": "MODERATE"}}
            ]
            Ensure the output is valid JSON.

            Assistant:
            """
        return prompt_content

    def build_summary_prompt(self, all_review_text: str) -> str:
        """
        Prompts the LLM to generate a concise summary of all review comments and security issues.
        """
        prompt_content = f"""
            Human: Summarize the following code review comments and security issues into a concise, high-level overview.
            Highlight the most critical points and overall sentiment.

            <all_review_comments>
            {all_review_text}
            </all_review_comments>

            Assistant:
            """
        return prompt_content

    # --- LLM Invocation Helper ---

    async def _invoke_bedrock_model(self, prompt: str, max_tokens: int = 4000) -> Optional[str]:
        """Helper to invoke Bedrock and extract the completion."""
        try:
            body = json.dumps({
                "prompt": prompt,
                "max_tokens_to_sample": max_tokens,
                "temperature": 0.2,
                "top_p": 0.9
            })
            response = self.bedrock_client.invoke_model(
                modelId=self.bedrock_model_id,
                contentType="application/json",
                accept="application/json",
                body=body
            )
            completion = json.loads(response['body'].read().decode('utf-8'))['completion']
            return completion
        except Exception as e:
            logger.error(f"Error invoking Bedrock model: {e}", exc_info=True)
            return None

    # --- Main Review Request Logic ---

    async def send_review_request(self, pr_details: dict) -> ParsedReviewOutput | None:
        pr_id = pr_details.get('pr_id', 0)
        repo = f"{pr_details.get('repo_owner', 'N/A')}/{pr_details.get('repo_name', 'N/A')}"

        all_line_comments = []
        all_general_comments = []
        all_security_issues = []
        full_review_text_for_summary = ""

        try:
            installation_id = pr_details['installation_id']
            access_token = self.github_utils.get_installation_token(installation_id)

            if not access_token:
                logger.error(f"No access token available for fetching diff for PR #{pr_id}.")
                return None

            diff_content = self.github_utils.get_pr_diff(pr_details['diff_url'], access_token)

            if not diff_content:
                logger.warning(f"Diff content for PR #{pr_id} is empty. Skipping review.")
                return ParsedReviewOutput(summary="No diff content to review.", line_comments=[], general_comments=[],
                                          security_issues=[])

            guidelines = self.load_guidelines()
            if not guidelines:
                logger.warning(f"Guidelines content for PR #{pr_id} is empty. Review might be less effective.")

            # --- Step 1: Initial Analysis ---
            logger.info(f"Step 1: Performing initial analysis for PR #{pr_id}.")
            initial_analysis_prompt = self.build_initial_analysis_prompt(guidelines, diff_content)
            initial_analysis_raw = await self._invoke_bedrock_model(initial_analysis_prompt, max_tokens=2000)

            identified_line_comments = []
            identified_general_comments = []
            identified_security_issues = []

            if initial_analysis_raw:
                try:
                    analysis_data = json.loads(initial_analysis_raw)
                    identified_line_comments = analysis_data.get("potential_line_comments", [])
                    identified_general_comments = analysis_data.get("potential_general_comments", [])
                    identified_security_issues = analysis_data.get("potential_security_issues", [])
                    logger.info(
                        f"Initial analysis identified: {len(identified_line_comments)} line comments, {len(identified_general_comments)} general comments, {len(identified_security_issues)} security issues.")
                except json.JSONDecodeError as e:
                    logger.error(
                        f"Failed to parse initial analysis JSON for PR #{pr_id}: {e}. Raw: {initial_analysis_raw[:200]}",
                        exc_info=True)
                except ValidationError as e:
                    logger.error(f"Validation error in initial analysis for PR #{pr_id}: {e}", exc_info=True)
            else:
                logger.warning(f"No initial analysis received for PR #{pr_id}.")

            # --- Step 2: Generate Detailed Line Comments ---
            if identified_line_comments:
                logger.info(f"Step 2: Generating detailed line comments for PR #{pr_id}.")
                line_comment_prompt = self.build_line_comment_prompt(guidelines, diff_content, identified_line_comments)
                line_comments_raw = await self._invoke_bedrock_model(line_comment_prompt)
                if line_comments_raw:
                    try:
                        parsed_comments = json.loads(line_comments_raw)
                        for lc in parsed_comments:
                            all_line_comments.append(LineComment(**lc))
                        logger.info(f"Generated {len(all_line_comments)} detailed line comments.")
                    except (json.JSONDecodeError, ValidationError) as e:
                        logger.error(
                            f"Failed to parse detailed line comments JSON for PR #{pr_id}: {e}. Raw: {line_comments_raw[:200]}",
                            exc_info=True)
                else:
                    logger.warning(f"No detailed line comments received for PR #{pr_id}.")

            # --- Step 3: Generate Detailed General Comments ---
            if identified_general_comments:
                logger.info(f"Step 3: Generating detailed general comments for PR #{pr_id}.")
                general_comment_prompt = self.build_general_comment_prompt(guidelines, diff_content,
                                                                           identified_general_comments)
                general_comments_raw = await self._invoke_bedrock_model(general_comment_prompt)
                if general_comments_raw:
                    try:
                        parsed_comments = json.loads(general_comments_raw)
                        for gc in parsed_comments:
                            all_general_comments.append(GeneralComment(**gc))
                        logger.info(f"Generated {len(all_general_comments)} detailed general comments.")
                    except (json.JSONDecodeError, ValidationError) as e:
                        logger.error(
                            f"Failed to parse detailed general comments JSON for PR #{pr_id}: {e}. Raw: {general_comments_raw[:200]}",
                            exc_info=True)
                else:
                    logger.warning(f"No detailed general comments received for PR #{pr_id}.")

            # --- Step 4: Generate Detailed Security Issues ---
            if identified_security_issues:
                logger.info(f"Step 4: Generating detailed security issues for PR #{pr_id}.")
                security_issue_prompt = self.build_security_issue_prompt(guidelines, diff_content,
                                                                         identified_security_issues)
                security_issues_raw = await self._invoke_bedrock_model(security_issue_prompt)
                if security_issues_raw:
                    try:
                        parsed_issues = json.loads(security_issues_raw)
                        for si in parsed_issues:
                            all_security_issues.append(SecurityIssue(**si))
                        logger.info(f"Generated {len(all_security_issues)} detailed security issues.")
                    except (json.JSONDecodeError, ValidationError) as e:
                        logger.error(
                            f"Failed to parse detailed security issues JSON for PR #{pr_id}: {e}. Raw: {security_issues_raw[:200]}",
                            exc_info=True)
                else:
                    logger.warning(f"No detailed security issues received for PR #{pr_id}.")

            # --- Step 5: Generate Summary ---
            logger.info(f"Step 5: Generating summary for PR #{pr_id}.")
            # Combine all generated comments/issues into a single text for summary generation
            full_review_text_for_summary += "\n--- Line Comments ---\n" + "\n".join(
                [f"{lc.file}:{lc.line}: {lc.comment}" for lc in all_line_comments])
            full_review_text_for_summary += "\n--- General Comments ---\n" + "\n".join(
                [gc.comment for gc in all_general_comments])
            full_review_text_for_summary += "\n--- Security Issues ---\n" + "\n".join(
                [f"SECURITY:{si.file}:{si.line}:{si.issue} (Severity: {si.severity})" for si in all_security_issues])

            summary_prompt_string = self.build_summary_prompt(full_review_text_for_summary)
            summary_final_text = await self._invoke_bedrock_model(summary_prompt_string,
                                                                  max_tokens=1000) or "No summary generated."
            logger.info(f"Summary generated for PR #{pr_id}.")

            return ParsedReviewOutput(
                summary=summary_final_text,
                line_comments=all_line_comments,
                general_comments=all_general_comments,
                security_issues=all_security_issues
            )

        except Exception as e:
            logger.error(f"Overall review process failed for PR #{pr_id}: {str(e)}", exc_info=True)
            return ParsedReviewOutput(
                summary="An error occurred during the review process.",
                line_comments=[],
                general_comments=[],
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

