import hashlib
import hmac
import json
import logging
import os

import requests
from github import Github, Auth
from github import GithubIntegration as LegacyGithubIntegration

# Import SecretUtils
from secret_utils import SecretUtils

logger = logging.getLogger(__name__)


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
            "installation_id": installation_id
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

    def add_pr_review_comments(self, repo_full_name: str, pr_number: int, summary: str,
                               line_comments: list, general_comments: list, security_issues: list,
                               installation_id: int):
        pull_request = None
        try:
            logger.info(f"Attempting to add review comments for PR #{pr_number} in {repo_full_name}.")
            token = self.integration.get_access_token(installation_id).token
            github_client = Github(token)
            repo = github_client.get_repo(repo_full_name)
            pull_request = repo.get_pull(pr_number)

            # --- Construct the main PR comment body ---
            body = f"## PR Review by CodeGuardian 🛡️\n\n### PR Review Summary 📝\n\n{summary}\n\n"

            if security_issues:
                body += "### Security Issues 🚨\n"
                # Sort security issues by severity
                severity_order = {"SEVERE": 3, "MODERATE": 2, "LOW": 1}
                sorted_security_issues = sorted(security_issues, key=lambda x: severity_order.get(x.severity.upper(), 0), reverse=True)

                for issue in sorted_security_issues:
                    severity_emoji = {
                        "SEVERE": "🔴",
                        "MODERATE": "🟠",
                        "LOW": "🟡"
                    }.get(issue.severity.upper(), "⚪")
                    body += f"- {severity_emoji} **{issue.file}:L{issue.line}** ({issue.severity.upper()}): {issue.issue}\n"
                body += "\n"

            if general_comments:
                body += "### General Comments 💬\n"
                for comment_data in general_comments:
                    body += f"- {comment_data.comment}\n"
                body += "\n"

            if line_comments:
                body += "### Line-Specific Comments 📄\n"
                # Group line comments by file for better readability
                comments_by_file = {}
                for lc in line_comments:
                    if lc.file not in comments_by_file:
                        comments_by_file[lc.file] = []
                    comments_by_file[lc.file].append(lc)

                for file, comments_list in comments_by_file.items():
                    body += f"**File: `{file}`**\n"
                    # Sort comments within a file by line number
                    sorted_comments_list = sorted(comments_list, key=lambda x: x.line)
                    for lc in sorted_comments_list:
                        body += f"  - Line {lc.line}: {lc.comment}\n"
                body += "\n"

            if not summary and not security_issues and not general_comments and not line_comments:
                body += "No specific issues or comments found, but the review process was completed."

            pull_request.create_issue_comment(body)
            logger.info(f"Posted main review summary comment for PR #{pr_number}.")

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
                return f"unreachable (status: {response.status_code})"
        except requests.exceptions.RequestException as e:
            logger.error(f"GitHub API health check failed: {e}", exc_info=True)
            return f"unreachable (error: {e})"
        except Exception as e:
            logger.error(f"Unexpected error during GitHub API health check: {e}", exc_info=True)
            return f"unreachable (unexpected error: {e})"

