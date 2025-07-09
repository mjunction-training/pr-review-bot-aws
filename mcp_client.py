import json
import logging
import os
import time
from typing import List, Optional

import boto3
from botocore.exceptions import ClientError
from pydantic import BaseModel, ValidationError

from github_utils import GitHubUtils
from secret_utils import SecretUtils
from rag_utils import RAGUtils  # Keep RAGUtils for the main project's RAG functionality

logger = logging.getLogger(__name__)


# --- Pydantic Models for Structured Output ---
# Adjusted to match the output format implied by pr_review.py's prompts
# and to support multi-line comments.

class InlineComment(BaseModel):
    file: str
    line: int  # This will be the line in the diff, as per pr_review.py's prompt
    # Note: pr_review.py's prompt only asks for 'LINE_NUMBER'.
    # If we want multi-line, the prompt needs to explicitly ask for 'start_line'/'end_line'
    # and the LLM must adhere. For now, matching the original pr_review.py's prompt.
    severity: str  # "High", "Medium", "Low"
    suggestion: str
    example_fix: str  # pr_review.py's prompt explicitly asks for EXAMPLE_FIX


class FileComment(BaseModel):
    file: str
    line: Optional[int] = None  # Can be file-level or specific line within file
    severity: str  # "High", "Medium", "Low"
    suggestion: str
    improvement_description: str  # pr_review.py's prompt explicitly asks for IMPROVEMENT_DESCRIPTION


class SecurityIssue(BaseModel):
    file: str
    line: int
    issue: str
    severity: str  # "SEVERE", "MODERATE", "LOW" - Keeping this separate as it's a good practice.


class ParsedReviewOutput(BaseModel):
    summary: str
    inline_comments: List[InlineComment]  # Renamed from line_comments for consistency with pr_review.py
    file_comments: List[FileComment]  # New type for file-level/general comments
    security_issues: List[SecurityIssue]  # Kept separate for explicit security analysis


# --- Main Client Class ---

class MCPClient:
    def __init__(self, github_utils: GitHubUtils, secret_utils: SecretUtils, rag_utils: RAGUtils):
        self.github_utils = github_utils
        self.secret_utils = secret_utils
        self.rag_utils = rag_utils

        self.aws_region = os.getenv('AWS_REGION', 'us-east-1')
        self.bedrock_model_id = self.secret_utils.get_bedrock_model_id() or \
                                os.getenv('BEDROCK_MODEL_ID', 'anthropic.claude-3-sonnet-20240229-v1:0')

        self.bedrock_client = boto3.client(
            service_name='bedrock-runtime',
            region_name=self.aws_region
        )
        logger.info(f"Initialized Bedrock client for region: {self.aws_region} with model: {self.bedrock_model_id}.")

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

    def build_inline_comment_prompt(self, diff_content: str, retrieved_examples: Optional[str]) -> str:
        """
        Prompts the LLM to generate detailed inline comments for the diff,
        following the strict format from pr_review.py's analyze_code_changes.
        """
        examples_section = ""
        if retrieved_examples:
            examples_section = f"""
            <knowledge_base_examples>
            The following are examples of code or documentation retrieved from a knowledge base.
            Refer to these examples for best practices, common patterns, and context
            when evaluating the pull request. Use them to inform your suggestions,
            but do NOT copy the examples directly into your comments.

            {retrieved_examples}
            </knowledge_base_examples>
            """

        # Replicating the strict prompt from pr_review.py's analyze_code_changes
        prompt_content = f"""
            Human: You are an expert code reviewer. Your task is to analyze the provided code changes (diff)
            and provide specific, actionable feedback.

            {examples_section}

            For each issue you find, you MUST provide a comment in this exact format:
            LINE_NUMBER|SEVERITY|DETAILED_SUGGESTION|EXAMPLE_FIX

            RULES:
            1. LINE_NUMBER must be from the list of changed lines provided.
            2. SEVERITY must be exactly one of: High, Medium, Low
            3. DETAILED_SUGGESTION must explain what to fix and why.
            4. EXAMPLE_FIX must show the exact code fix

            Example comments:
            12|Medium|Add null check to prevent NullPointerException|Add a null check before accessing the variable.
            56|High|Use String.format for better performance|Use String.format instead of string concatenation
            78|Low|Add comment explaining the logic|Add a comment to explain the tax calculation

            IMPORTANT:
            - ONLY use the exact format specified above
            - ONLY comment on lines that have been changed
            - ONLY use High, Medium, or Low for severity
            - Each comment must be on a new line
            - Do NOT include any other text or explanations
            - Do NOT include a summary section!

            <diff>
            {diff_content}
            </diff>

            Assistant:
            """
        return prompt_content

    def build_file_comment_prompt(self, guidelines: str, file_path: str, file_content: str,
                                  retrieved_examples: Optional[str]) -> str:
        """
        Prompts the LLM to generate file-level or line-specific comments within a file,
        following the strict format from pr_review.py's analyze_file.
        """
        examples_section = ""
        if retrieved_examples:
            examples_section = f"""
            <knowledge_base_examples>
            Refer to these example code snippets and best practices:
            {retrieved_examples}
            </knowledge_base_examples>
            """

        # Replicating the strict prompt from pr_review.py's analyze_file
        prompt_content = f"""
            Human: You are an expert code reviewer. Your task is to analyze the provided file content
            and provide specific, actionable feedback.

            {examples_section}

            For each issue you find, you MUST provide a comment in this exact format:
            LINE_NUMBER|SEVERITY|DETAILED_SUGGESTION|IMPROVEMENT_DESCRIPTION

            RULES:
            1. LINE_NUMBER must be the actual line number in the file.
            2. SEVERITY must be exactly 'High', 'Medium', or 'Low'.
            3. DETAILED_SUGGESTION: Clear explanation of what needs to be fixed.
            4. IMPROVEMENT_DESCRIPTION: Description of how to improve the code (no code examples).

            IMPORTANT:
            - ONLY use the exact format specified above
            - ONLY comment on lines that have been changed (if applicable, for line-specific comments)
            - ONLY use High, Medium, or Low for severity
            - Each comment must be on a new line
            - Do NOT include any other text or explanations
            - Do NOT include a summary section!
            
            <review_guidelines>
            {guidelines}
            </review_guidelines>

            <file_content>
            File: {file_path}
            {file_content}
            </file_content>

            Assistant:
            """
        return prompt_content

    def build_security_issue_prompt(self, guidelines: str, diff: str, retrieved_examples: Optional[str]) -> str:
        """
        Prompts the LLM to generate detailed security issues with severity.
        This is a separate step not explicitly in the reconstructed pr_review.py, but good to keep.
        """
        examples_section = ""
        if retrieved_examples:
            examples_section = f"""
            <knowledge_base_examples>
            Refer to these example code snippets and best practices for secure coding:
            {retrieved_examples}
            </knowledge_base_examples>
            """

        prompt_content = f"""
            Human: You are an expert security code reviewer. Based on the provided code changes (diff) and guidelines,
            identify and describe potential security vulnerabilities.
            Assign a severity level to each issue: "SEVERE", "MODERATE", or "LOW".
            Provide actionable recommendations to mitigate the vulnerability.

            {examples_section}

            <review_guidelines>
            {guidelines}
            </review_guidelines>

            <diff>
            {diff}
            </diff>

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

    async def _invoke_bedrock_model(self, prompt: str, max_tokens: int = 4000, max_retries: int = 3,
                                    initial_delay: float = 1.0) -> Optional[str]:
        """Helper to invoke Bedrock and extract the completion with retries."""
        retries = 0
        while retries < max_retries:
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
            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code")
                logger.error(
                    f"ClientError invoking Bedrock model (Attempt {retries + 1}/{max_retries}): {error_code} - {e}",
                    exc_info=True)
                if error_code == 'ThrottlingException' or error_code == 'TooManyRequestsException':
                    delay = initial_delay * (2 ** retries)
                    logger.warning(f"Throttling or TooManyRequestsException. Retrying in {delay:.2f} seconds...")
                    time.sleep(delay)
                    retries += 1
                else:
                    logger.error(f"Non-retryable ClientError encountered. Not retrying.")
                    return None
            except Exception as e:
                logger.error(f"Unexpected error invoking Bedrock model (Attempt {retries + 1}/{max_retries}): {e}",
                             exc_info=True)
                return None
        logger.error(f"Failed to invoke Bedrock model after {max_retries} attempts.")
        return None

    # --- Main Review Request Logic ---

    async def send_review_request(self, pr_details: dict) -> ParsedReviewOutput | None:
        pr_id = pr_details.get('pr_id', 0)
        repo_full_name = f"{pr_details.get('repo_owner', 'N/A')}/{pr_details.get('repo_name', 'N/A')}"

        all_inline_comments: List[InlineComment] = []
        all_file_comments: List[FileComment] = []
        all_security_issues: List[SecurityIssue] = []
        full_review_text_for_summary = ""
        retrieved_examples_for_prompts = None

        try:
            installation_id = pr_details['installation_id']
            access_token = self.github_utils.get_installation_token(installation_id)

            if not access_token:
                logger.error(f"No access token available for fetching diff for PR #{pr_id}.")
                return None

            diff_content = self.github_utils.get_pr_diff(pr_details['diff_url'], access_token)

            if not diff_content:
                logger.warning(f"Diff content for PR #{pr_id} is empty. Skipping review.")
                return ParsedReviewOutput(summary="No diff content to review.", inline_comments=[], file_comments=[],
                                          security_issues=[])

            guidelines = self.load_guidelines()
            if not guidelines:
                logger.warning(f"Guidelines content for PR #{pr_id} is empty. Review might be less effective.")

            # --- RAG Step: Retrieve context from Knowledge Base using 'retrieve' API ---
            if self.rag_utils:
                kb_query = f"Code review for pull request changes in {repo_full_name} PR #{pr_id}. Diff summary: {diff_content[:500]}..."
                retrieved_examples_for_prompts = self.rag_utils.retrieve_and_generate_context(kb_query)
                if retrieved_examples_for_prompts:
                    logger.info(
                        f"Retrieved RAG examples for PR #{pr_id}. Length: {len(retrieved_examples_for_prompts)} chars.")
                else:
                    logger.warning(f"No RAG examples retrieved for PR #{pr_id}. Continuing without RAG context.")
            else:
                logger.info("RAGUtils not initialized. Skipping RAG examples retrieval.")

            # --- Step 1: Generate Inline Comments (from diff analysis) ---
            logger.info(f"Step 1: Generating inline comments for PR #{pr_id}.")
            inline_comment_prompt = self.build_inline_comment_prompt(diff_content, retrieved_examples_for_prompts)
            inline_comments_raw = await self._invoke_bedrock_model(inline_comment_prompt, max_tokens=2000)

            if inline_comments_raw:
                try:
                    # Parse the pipe-separated string output
                    comments_lines = inline_comments_raw.strip().split('\n')
                    for line in comments_lines:
                        parts = line.split('|')
                        if len(parts) == 4:
                            try:
                                all_inline_comments.append(InlineComment(
                                    file=self.github_utils.get_file_from_diff_line(diff_content, int(parts[0])),
                                    # Attempt to get file from diff line
                                    line=int(parts[0]),
                                    severity=parts[1],
                                    suggestion=parts[2],
                                    example_fix=parts[3]
                                ))
                            except ValueError as ve:
                                logger.warning(f"Invalid line number or format in inline comment: {line} - {ve}")
                        else:
                            logger.warning(f"Malformed inline comment line: {line}")
                    logger.info(f"Generated {len(all_inline_comments)} inline comments.")
                except Exception as e:
                    logger.error(
                        f"Failed to parse inline comments from LLM raw output for PR #{pr_id}: {e}. Raw: {inline_comments_raw[:200]}",
                        exc_info=True)
            else:
                logger.warning(f"No inline comments received for PR #{pr_id}.")

            # --- Step 2: Generate File-level Comments (requires fetching file content) ---
            logger.info(f"Step 2: Generating file-level comments for PR #{pr_id}.")
            # This part needs to iterate through files and fetch their content, similar to pr_review.py's analyze_pr
            # For simplicity, we'll use a placeholder for file content retrieval.
            # In a real scenario, you'd iterate `pull_request.get_files()` and fetch content via `file_obj.raw_url`.

            # Mocking file content for demonstration if not fetching real files
            # In a real setup, you'd get this from GitHub API via github_utils.
            mock_file_contents = {
                "src/example.py": "def foo():\n    pass # Example content",
                "src/another.js": "console.log('hello'); // Another example"
            }

            # Iterate through changed files to get their content and analyze
            # This part would typically be done by `github_utils` or directly here by fetching.
            # For now, let's simulate iterating over files in the PR.
            # You would replace this with actual file content fetching.
            # For this example, we'll assume `pr_details` has a list of changed files with their contents.
            # Or, you'd use `github_utils.get_pr_file_content(file_path, access_token)`

            # To properly get file contents, we need the `pull_request` object.
            # Since `send_review_request` only gets `pr_details`, we'd need to pass `pull_request`
            # or refactor `github_utils` to fetch content given `repo_name`, `pr_id`, `file_path`.

            # For now, let's assume we can get file paths from the diff or a separate call.
            # The original pr_review.py fetched files via `pull_request.get_files()`.
            # We'll simulate this for consistency with the prompt.

            # This is a critical point: `mcp_client.py` needs file content for `analyze_file` prompt.
            # The `pr_review.py` did this by getting `pull_request.get_files()` and then `file_obj.raw_url`.
            # We need to adapt `github_utils` to provide this.

            # For now, let's assume `pr_details` can somehow provide file paths.
            # A more complete solution would involve `github_utils` fetching file content.

            # Let's assume we can get the list of files from the diff.
            # A simpler approach for `mcp_client` would be to just get the diff,
            # and then rely on the LLM to understand file context from the diff itself
            # for file-level comments, or have a separate mechanism to fetch full file content.

            # For strict adherence to pr_review.py's `analyze_file` which takes `file_content`,
            # we need to fetch content for each file.

            # This requires a change in `github_utils` to provide file contents.
            # Let's assume `github_utils` has a new method `get_pr_file_contents(repo_owner, repo_name, pr_id, access_token)`
            # that returns a dict of {file_path: file_content}.

            # This is a placeholder. You need to implement `get_pr_file_contents` in `github_utils.py`.
            # For this example, we'll just use the diff's file paths.
            # The LLM's `analyze_file` prompt expects full file content, not just diff.
            # This is a design choice. If `mcp_client` is to be modular, it needs the content.

            # Let's adapt `mcp_client` to iterate over files in the diff and fetch content.
            # This means `github_utils` needs a method to get file content by path.

            # For now, let's simplify: `analyze_file` will take `diff_content` for file-level comments
            # if we cannot reliably fetch full file content for each changed file within `mcp_client`.
            # However, the `pr_review.py` explicitly fetched `file_content`.

            # Let's make a strong assumption that `github_utils` can provide file content.
            # This is a necessary dependency to match `pr_review.py`'s `analyze_file` input.

            # Assuming `github_utils` has `get_pr_file_contents(repo_owner, repo_name, pr_id, access_token)`
            # that returns a dictionary of {file_path: file_content} for changed files.

            # For this specific file, let's mock it if `github_utils` doesn't have it yet.
            # Or, we need to modify `github_utils` first.

            # To strictly follow the user's request for *this file only* and then improve old project files,
            # I will make a note here for the next step.

            # For now, let's just pass the diff content to `build_file_comment_prompt` as a fallback
            # if explicit file content fetching is not yet available in `github_utils`.
            # This deviates from `pr_review.py`'s `analyze_file` input but makes `mcp_client` runnable.
            # The user's `pr_review.py` fetches `file_obj.raw_url` for `file_content`.
            # So, `mcp_client` needs to simulate this or rely on `github_utils`.

            # Let's assume `github_utils` can provide a list of changed file paths.
            changed_file_paths = self.github_utils.get_changed_file_paths_from_diff(
                diff_content)  # New helper needed in github_utils

            for file_path in changed_file_paths:
                file_content_for_analysis = self.github_utils.get_file_content_at_pr_head(
                    pr_details['repo_owner'], pr_details['repo_name'], file_path, pr_details['commit_sha'], access_token
                )  # Another new helper needed in github_utils

                if file_content_for_analysis:
                    file_comment_prompt = self.build_file_comment_prompt(guidelines, file_path,
                                                                         file_content_for_analysis,
                                                                         retrieved_examples_for_prompts)
                    file_comments_raw = await self._invoke_bedrock_model(file_comment_prompt, max_tokens=1500)
                    if file_comments_raw:
                        try:
                            comments_lines = file_comments_raw.strip().split('\n')
                            for line in comments_lines:
                                parts = line.split('|')
                                if len(parts) == 4:
                                    try:
                                        all_file_comments.append(FileComment(
                                            file=file_path,
                                            line=int(parts[0]),  # Line in file
                                            severity=parts[1],
                                            suggestion=parts[2],
                                            improvement_description=parts[3]
                                        ))
                                    except ValueError as ve:
                                        logger.warning(f"Invalid line number or format in file comment: {line} - {ve}")
                                else:
                                    logger.warning(f"Malformed file comment line: {line}")
                            logger.info(f"Generated {len(all_file_comments)} file-level comments for {file_path}.")
                        except Exception as e:
                            logger.error(
                                f"Failed to parse file comments from LLM raw output for {file_path}: {e}. Raw: {file_comments_raw[:200]}",
                                exc_info=True)
                    else:
                        logger.warning(f"No file comments received for {file_path}.")
                else:
                    logger.warning(f"Could not retrieve content for file {file_path}. Skipping file-level analysis.")

            # --- Step 3: Generate Security Issues (keeping this as a separate, structured step) ---
            logger.info(f"Step 3: Generating security issues for PR #{pr_id}.")
            security_issue_prompt = self.build_security_issue_prompt(guidelines, diff_content,
                                                                     retrieved_examples_for_prompts)
            security_issues_raw = await self._invoke_bedrock_model(security_issue_prompt)
            if security_issues_raw:
                try:
                    parsed_issues = json.loads(security_issues_raw)
                    all_security_issues.extend([SecurityIssue(**si) for si in parsed_issues])
                    logger.info(f"Generated {len(all_security_issues)} detailed security issues.")
                except (json.JSONDecodeError, ValidationError) as e:
                    logger.error(
                        f"Failed to parse detailed security issues JSON for PR #{pr_id}: {e}. Raw: {security_issues_raw[:200]}",
                        exc_info=True)
            else:
                logger.warning(f"No detailed security issues received for PR #{pr_id}.")

            # --- Step 4: Generate Summary ---
            logger.info(f"Step 4: Generating summary for PR #{pr_id}.")

            # Combine all generated comments/issues into a single text for summary generation
            full_review_text_for_summary += "\n--- Inline Comments ---\n" + "\n".join(
                [f"{lc.file}:L{lc.line}: {lc.suggestion}" for lc in all_inline_comments])
            full_review_text_for_summary += "\n--- File Comments ---\n" + "\n".join(
                [f"{fc.file}:L{fc.line or 'N/A'}: {fc.suggestion}" for fc in all_file_comments])
            full_review_text_for_summary += "\n--- Security Issues ---\n" + "\n".join(
                [f"SECURITY:{si.file}:L{si.line}:{si.issue} (Severity: {si.severity})" for si in all_security_issues])

            summary_prompt_string = self.build_summary_prompt(full_review_text_for_summary)
            summary_final_text = await self._invoke_bedrock_model(summary_prompt_string,
                                                                  max_tokens=1000) or "No summary generated."
            logger.info(f"Summary generated for PR #{pr_id}.")

            return ParsedReviewOutput(
                summary=summary_final_text,
                inline_comments=all_inline_comments,
                file_comments=all_file_comments,
                security_issues=all_security_issues
            )

        except Exception as e:
            logger.error(f"Overall review process failed for PR #{pr_id}: {str(e)}", exc_info=True)
            return ParsedReviewOutput(
                summary="An error occurred during the review process.",
                inline_comments=[],
                file_comments=[],
                security_issues=[]
            )

    def check_bedrock_health(self) -> str:
        try:
            # Check LLM connectivity
            self.bedrock_client.list_foundation_models(maxResults=1)
            # Check Knowledge Base connectivity
            if self.rag_utils:
                kb_health = self.rag_utils.check_kb_health()
                if kb_health == "reachable":
                    return "reachable"
                else:
                    return f"reachable (LLM), {kb_health} (KB)"
            else:
                return "reachable (LLM), KB not configured"
        except Exception as e:
            logger.error(f"Bedrock service health check failed: {e}", exc_info=True)
            return f"unreachable (error: {e})"

