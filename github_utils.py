import hashlib
import hmac
import json
import logging
import os

from typing import List, Optional

import requests
from github import Github, Auth
from github import GithubIntegration as LegacyGithubIntegration
from github.PullRequest import ReviewComment

# Removed: from github import PullRequestReviewComment # This import causes the error

# Import SecretUtils (assuming its updated version is available)
from secret_utils import SecretUtils

logger = logging.getLogger(__name__)


# Re-define Pydantic models here for type hinting, matching mcp_client.py's output
# This avoids circular imports if mcp_client and github_utils were in separate modules.
# In a real project, these might be in a shared 'models.py' file.
# These are simplified dataclasses/classes to match the structure from mcp_client's Pydantic models.
class InlineComment:
    def __init__(self, file: str, line: Optional[int], start_line: Optional[int], end_line: Optional[int],
                 severity: str, suggestion: str, example_fix: Optional[str] = None):
        self.file = file
        self.line = line
        self.start_line = start_line
        self.end_line = end_line
        self.severity = severity
        self.suggestion = suggestion
        self.example_fix = example_fix


class FileComment:
    def __init__(self, file: str, line: Optional[int], severity: str, suggestion: str, improvement_description: str):
        self.file = file
        self.line = line
        self.severity = severity
        self.suggestion = suggestion
        self.improvement_description = improvement_description


class SecurityIssue:
    def __init__(self, file: str, line: int, issue: str, severity: str):
        self.file = file
        self.line = line
        self.issue = issue
        self.severity = severity


class GitHubUtils:
    def __init__(self, secret_utils: SecretUtils):
        self.secret_utils = secret_utils

        # Retrieve secrets using SecretUtils
        self.app_id = self.secret_utils.get_github_app_id()
        self.private_key = self.secret_utils.get_github_private_key()
        self.webhook_secret = self.secret_utils.get_github_webhook_secret()

        # trigger_team_slug can remain an environment variable or be moved to secrets if preferred
        self.trigger_team_slug = os.getenv('TRIGGER_TEAM_SLUG', 'ai-review-bots')

        if not self.webhook_secret:
            logger.error("WEBHOOK_SECRET not retrieved from Secrets Manager or not provided.")
            raise ValueError("Webhook secret must be provided.")

        if not self.app_id:
            logger.error("GITHUB_APP_ID not retrieved from Secrets Manager.")
            raise ValueError("GitHub App ID must be provided.")

        if not self.private_key:
            logger.error("GITHUB_PRIVATE_KEY not retrieved from Secrets Manager.")
            raise ValueError("GitHub Private Key must be provided.")

        try:
            # The private key from Secrets Manager should already be in the correct format
            # (i.e., with actual newline characters, not escaped \\n)
            auth = Auth.AppAuth(
                app_id=int(self.app_id),
                private_key=self.private_key
            )
            self.integration = LegacyGithubIntegration(auth=auth)
            logger.info("GitHubIntegration initialized successfully using secrets.")
        except Exception as e:
            logger.error(f"GithubIntegration init failed: {e}", exc_info=True)
            raise

    def get_installation_token(self, installation_id: int) -> str:
        try:
            access_token = self.integration.get_access_token(installation_id).token
            return access_token
        except Exception as e:
            logger.error(f"Failed to get installation token for installation {installation_id}: {e}", exc_info=True)
            raise RuntimeError(f"Could not retrieve installation token: {e}")

    def get_installation_client(self, installation_id: int) -> Github:
        try:
            token = self.get_installation_token(installation_id)
            return Github(login_or_token=token)
        except Exception as e:
            logger.error(f"Failed to create installation client: {e}", exc_info=True)
            raise

    def validate_webhook_signature(self, payload: bytes, signature: str) -> bool:
        if not signature or not self.webhook_secret:
            logger.warning("Error: Missing signature header or webhook secret.")
            return False

        try:
            sha_name, hex_digest = signature.split('=')
        except ValueError:
            logger.warning("Error: X-Hub-Signature-256 header is not in the expected 'sha256=HEX_DIGEST' format.")
            return False

        if sha_name != 'sha256':
            logger.warning(f"Error: Signature algorithm is '{sha_name}', expected 'sha256'.")
            return False

        # Use the webhook_secret retrieved from Secrets Manager
        mac = hmac.new(self.webhook_secret.encode('utf-8'), msg=payload, digestmod=hashlib.sha256)
        calculated_digest = mac.hexdigest()

        return hmac.compare_digest(calculated_digest, hex_digest)

    def parse_github_webhook(self, request_data: bytes, signature: str) -> dict:
        if not self.validate_webhook_signature(request_data, signature):
            logger.warning("Invalid webhook signature")
            raise ValueError("Invalid webhook signature")

        payload = json.loads(request_data)
        return payload

    def process_pull_request_review_requested(self, payload: dict) -> dict | None:
        pull_request = payload.get('pull_request')
        logger.info(f"Received GitHub event: pull_request {pull_request}")
        if not pull_request:
            logger.error("Missing 'pull_request' object in payload.")
            return None

        repo_full_name = pull_request['base']['repo']['full_name']
        pr_number = pull_request['number']
        diff_url = pull_request['diff_url']
        commit_sha = pull_request['head']['sha']
        installation_id = payload['installation']['id']

        requested_teams = payload.get('requested_teams', [])
        requested_team = payload.get('requested_team')

        is_team_requested = any(
            team['slug'] == self.trigger_team_slug for team in requested_teams
        ) or (requested_team and requested_team['slug'] == self.trigger_team_slug)

        if not is_team_requested:
            logger.info(f"Review not requested for team '{self.trigger_team_slug}'. Ignoring PR #{pr_number}.")
            return None

        logger.info(f"Review requested for PR #{pr_number} in {repo_full_name} by team '{self.trigger_team_slug}'.")

        return {
            "repo": repo_full_name,
            "pr_id": pr_number,
            "diff_url": diff_url,
            "commit_sha": commit_sha,
            "installation_id": installation_id,
            "repo_owner": pull_request['base']['repo']['owner']['login'],  # Added for get_file_content_at_pr_head
            "repo_name": pull_request['base']['repo']['name']  # Added for get_file_content_at_pr_head
        }

    @staticmethod
    def get_pr_diff(diff_url: str, access_token: str) -> str:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github.v3.diff",
            "X-GitHub-Api-Version": "2022-11-28"
        }

        try:
            response = requests.get(diff_url, headers=headers, timeout=10)
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch diff from {diff_url}: {str(e)}", exc_info=True)
            raise

    @staticmethod
    def get_changed_file_paths_from_diff(diff_content: str) -> List[str]:
        """
        Parses a diff content to extract paths of changed files.
        This is a simple heuristic and might not catch all cases.
        """
        file_paths = set()
        # Regex to find lines starting with '--- a/' or '+++ b/'
        # and extract the path following it.
        # This handles cases like '--- a/path/to/file.py'
        # and '+++ b/path/to/file.py'
        for line in diff_content.splitlines():
            if line.startswith('--- a/') or line.startswith('+++ b/'):
                # Extract path, remove 'a/' or 'b/' prefix
                path = line[line.find('/') + 1:].strip()
                if path:
                    file_paths.add(path)
        return list(file_paths)

    def get_file_content_at_pr_head(self, repo_owner: str, repo_name: str, file_path: str, commit_sha: str,
                                    access_token: str) -> Optional[str]:
        """
        Fetches the content of a specific file at the PR's head commit.
        """
        url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{file_path}?ref={commit_sha}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github.v3.raw",  # Request raw content
            "X-GitHub-Api-Version": "2022-11-28"
        }
        print(f"Repo name - {self.app_id}")
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch content for file {file_path} at commit {commit_sha}: {e}", exc_info=True)
            return None

    @staticmethod
    def get_file_from_diff_line(diff_content: str, diff_line_number: int) -> str:
        """
        Attempts to find the file associated with a given line number in a diff.
        This is a heuristic and might not be perfectly accurate for all diff formats.
        It assumes the diff_line_number refers to the line number within the raw diff string.
        """
        current_file = "unknown_file"
        line_count = 0
        for line in diff_content.splitlines():
            line_count += 1
            if line.startswith('--- a/') or line.startswith('+++ b/'):
                # Update current file path when a new file block starts
                current_file = line[line.find('/') + 1:].strip()

            # If the target line number is reached, return the current file.
            # This is a simplification; a true mapping requires parsing diff hunks.
            if line_count == diff_line_number:
                return current_file
        return current_file  # Fallback if line number exceeds diff or file not found

    def add_pr_review_comments(self, repo_full_name: str, pr_number: int, summary: str,
                               inline_comments: List[InlineComment],  # Type hint changed
                               file_comments: List[FileComment],  # Type hint changed
                               security_issues: List[SecurityIssue],  # Type hint changed
                               installation_id: int):
        pull_request = None
        try:
            logger.info(f"Attempting to add review comments for PR #{pr_number} in {repo_full_name}.")
            token = self.get_installation_token(installation_id)  # Use get_installation_token
            github_client = Github(token)
            repo = github_client.get_repo(repo_full_name)
            pull_request = repo.get_pull(pr_number)

            # --- Prepare comments for GitHub Review API (for inline comments) ---
            comments_for_github_review: List[ReviewComment] = []  # Changed type hint to Dict
            for lc in inline_comments:
                comment_body = (
                    f"**Severity:** {lc.severity}\n\n"
                    f"**Suggestion:** {lc.suggestion}\n\n"
                    f"**Example Fix:**\n```\n{lc.example_fix or 'No example fix provided.'}\n```"
                )

                # GitHub's Review Comments API `position` refers to the Nth line in the diff.
                # The LLM's `line` output is assumed to be this diff line number as per pr_review.py's prompt.
                # If `start_line` and `end_line` were used for multi-line, PyGithub's PullRequestReviewComment
                # supports `start_line`, `start_side`, `line`, `side`.

                # For now, adhering to the original pr_review.py's prompt which only gives 'line'.
                # If multi-line comments are desired, the LLM prompt and parsing need to be updated
                # to provide 'start_line' and 'end_line'.

                # Constructing the dictionary directly as expected by create_review
                comment_dict : ReviewComment = {
                    "path": lc.file,
                    "body": comment_body
                }

                if lc.start_line is not None and lc.end_line is not None:
                    # Multi-line comment
                    comment_dict["start_line"] = lc.start_line
                    comment_dict["start_side"] = "RIGHT"  # Assuming changes are on the right side of the diff
                    comment_dict["line"] = lc.end_line
                    comment_dict["side"] = "RIGHT"  # Assuming changes are on the right side of the diff
                    logger.debug(f"Prepared multi-line comment for {lc.file} L{lc.start_line}-{lc.end_line}")
                elif lc.line is not None:
                    # Single-line comment
                    comment_dict[
                        "position"] = lc.line  # This is the line in the diff, as per original pr_review.py prompt
                    logger.debug(f"Prepared single-line comment for {lc.file} L{lc.line}")
                else:
                    logger.warning(
                        f"Skipping malformed inline comment (missing line/start_line/end_line): {lc.__dict__}")
                    continue  # Skip this comment if it's malformed

                comments_for_github_review.append(comment_dict)

            # --- Construct the main PR comment body (for summary, file-level, security issues) ---
            main_pr_comment_body_parts = [summary, ""]

            # Add summary

            # Add security issues
            if security_issues:
                main_pr_comment_body_parts.append("### Security Issues 🚨")
                severity_emoji = {"SEVERE": "🔴", "MODERATE": "🟠", "LOW": "🟡"}
                # Sort security issues by severity
                sorted_security_issues = sorted(security_issues,
                                                key=lambda x: severity_emoji.get(x.severity.upper(), 0), reverse=True)
                for issue in sorted_security_issues:
                    emoji = severity_emoji.get(issue.severity.upper(), "⚪")
                    main_pr_comment_body_parts.append(
                        f"- {emoji} **{issue.file}:L{issue.line}** ({issue.severity.upper()}): {issue.issue}")
                main_pr_comment_body_parts.append("")  # Add a newline

            # Add file-level general comments
            if file_comments:
                main_pr_comment_body_parts.append("### File-Specific General Comments 📄")
                # Group file-level comments by file for better readability
                file_comments_grouped = {}
                for fc in file_comments:
                    if fc.file not in file_comments_grouped:
                        file_comments_grouped[fc.file] = []
                    file_comments_grouped[fc.file].append(fc)

                for file_path, comments in file_comments_grouped.items():
                    main_pr_comment_body_parts.append(f"**File: `{file_path}`**")
                    for fc in comments:
                        line_info = f" (Line {fc.line})" if fc.line is not None else ""
                        main_pr_comment_body_parts.append(
                            f"  - **{fc.severity}**: {fc.suggestion}{line_info} - {fc.improvement_description}")
                main_pr_comment_body_parts.append("")  # Add a newline

            # --- Post comments to GitHub ---

            # First, submit the review with inline comments
            if comments_for_github_review:
                try:
                    pull_request.create_review(
                        body="Automated review: See inline comments for detailed code-level feedback.",
                        event="COMMENT",  # Can be 'APPROVE', 'REQUEST_CHANGES', 'COMMENT'
                        comments=comments_for_github_review
                    )
                    logger.info(
                        f"Submitted review with {len(comments_for_github_review)} inline comments for PR #{pr_number}.")
                except Exception as e:
                    logger.error(f"Failed to submit review with inline comments for PR #{pr_number}: {e}",
                                 exc_info=True)
                    main_pr_comment_body_parts.insert(0,
                                                      f"**Warning:** Failed to post some inline comments due to an error: `{e}`. Please check logs.")
            else:
                logger.info("No inline comments to submit as a review.")

            # Then, post the main PR comment (summary, security, file-level general)
            if main_pr_comment_body_parts:
                final_main_comment = "\n".join(main_pr_comment_body_parts)
                pull_request.create_issue_comment(final_main_comment)
                logger.info(f"Posted main PR comment for PR #{pr_number}.")
            else:
                logger.info("No main PR comment content to post (no summary, security, file-level general comments).")

        except Exception as e:
            logger.error(f"Failed to add PR review comments for {repo_full_name} PR #{pr_number}: {e}", exc_info=True)
            if pull_request:
                try:
                    pull_request.create_issue_comment(
                        f"## PR Review Commenting Failed ❌\n\n"
                        f"An error occurred while posting review comments: `{e}`\n"
                        f"Please check the application logs for more details."
                    )
                except Exception as comment_e:
                    logger.error(f"Could not post error comment about commenting failure: {comment_e}")

    @staticmethod
    def check_github_api_health() -> str:
        try:
            response = requests.get("https://api.github.com/", timeout=3)
            if response.ok:
                return "reachable"
            else:
                return f"unreachable (status: {response.status_code})"  # This is the line in the diff, as per original pr_review.py prompt
        except requests.exceptions.RequestException as e:
            logger.error(f"GitHub API health check failed: {e}", exc_info=True)
            return f"unreachable (error: {e})"
        except Exception as e:
            logger.error(f"Unexpected error during GitHub API health check: {e}", exc_info=True)
            return f"unreachable (unexpected error: {e})"

