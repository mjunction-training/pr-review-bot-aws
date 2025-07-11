import json
import logging
import os
import asyncio

from github_utils import GitHubUtils
from mcp_client import MCPClient
from secret_utils import SecretUtils
from s3_utils import S3Utils

# Configure logging
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
numeric_log_level = getattr(logging, log_level, None)
if not isinstance(numeric_log_level, int):
    raise ValueError(f"Invalid log level: {log_level}")
logging.basicConfig(level=numeric_log_level, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
logger.setLevel(numeric_log_level)

logger.info(f"Lambda function initializing with log level: {log_level}")

# Global initialization for cold starts
SECRETS_MANAGER_SECRET_NAME = os.getenv('SECRETS_MANAGER_SECRET_NAME')
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
EXAMPLE_PROJECT_S3_BUCKET = os.getenv('EXAMPLE_PROJECT_S3_BUCKET') # New env var
EXAMPLE_PROJECT_S3_PREFIX = os.getenv('EXAMPLE_PROJECT_S3_PREFIX', '') # New env var

github_utils = None
mcp_client = None
secret_utils = None
s3_utils = None # Initialize s3_utils globally

try:
    if not SECRETS_MANAGER_SECRET_NAME:
        raise ValueError("SECRETS_MANAGER_SECRET_NAME environment variable not set.")

    secret_utils = SecretUtils(secret_name=SECRETS_MANAGER_SECRET_NAME, region_name=AWS_REGION)
    logger.info("SecretUtils initialized successfully.")

    # Initialize S3Utils
    if EXAMPLE_PROJECT_S3_BUCKET:
        s3_utils = S3Utils(bucket_name=EXAMPLE_PROJECT_S3_BUCKET, region_name=AWS_REGION)
        logger.info("S3Utils initialized successfully.")
    else:
        logger.warning("EXAMPLE_PROJECT_S3_BUCKET not set. S3 knowledge base will not be available.")

    github_utils = GitHubUtils(secret_utils=secret_utils)
    logger.info("GitHubUtils initialized successfully using secrets.")

    # Pass s3_utils to MCPClient
    mcp_client = MCPClient(github_utils=github_utils, secret_utils=secret_utils, s3_utils=s3_utils)
    logger.info("MCPClient (Bedrock integration) initialized successfully using secrets and S3Utils.")

except ValueError as e:
    logger.error(f"Failed to initialize core utilities: {e}. This will cause Lambda errors.", exc_info=True)
except Exception as e:
    logger.error(f"An unexpected error occurred during global initialization: {e}. This will cause Lambda errors.", exc_info=True)


def lambda_handler(event, context):
    logger.debug(f"Received Lambda event: {json.dumps(event)}")

    # Health check endpoint
    if event.get('path') == '/health' and event.get('httpMethod') == 'GET':
        logger.debug("Received health check request.")
        status = {
            "status": "ok",
            "services": {}
        }

        if github_utils:
            github_status = github_utils.check_github_api_health()
            status["services"]["github_api"] = github_status
            logger.debug(f"GitHub API health: {github_status}")
        else:
            status["services"]["github_api"] = "not_initialized"
            logger.warning("GitHubUtils not initialized, GitHub API health not checked.")

        if mcp_client:
            bedrock_status = mcp_client.check_bedrock_health()
            status["services"]["bedrock_connection"] = bedrock_status
            logger.debug(f"Bedrock connection health: {bedrock_status}")
        else:
            status["services"]["bedrock_connection"] = "not_initialized"
            logger.warning("MCPClient (Bedrock integration) not initialized, Bedrock connection health not checked.")

        if s3_utils:
            # A simple check for S3Utils initialization
            status["services"]["s3_knowledge_base"] = "initialized" if s3_utils else "not_initialized"
            logger.debug(f"S3 Knowledge Base status: {status['services']['s3_knowledge_base']}")
        else:
            status["services"]["s3_knowledge_base"] = "not_configured"
            logger.warning("S3Utils not configured, S3 knowledge base not checked.")


        overall_status = "ok"
        for service_name, service_status in status["services"].items():
            if "unreachable" in service_status or "error" in service_status or "not_initialized" in service_status:
                overall_status = "warning"
                logger.warning(f"Health check warning: Service '{service_name}' status is '{service_status}'.")
                break

        status["status"] = overall_status
        logger.info(f"Overall health status: {overall_status}")
        logger.debug(f"Full health status response: {status}")
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps(status)
        }

    # Webhook endpoint
    if event.get('path') == '/webhook' and event.get('httpMethod') == 'POST':
        if not github_utils or not mcp_client or not secret_utils:
            logger.error("Core utilities (GitHubUtils, MCPClient, SecretUtils) not initialized. Cannot process webhook.")
            return {
                'statusCode': 500,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({"error": "Internal Server Error", "message": "Bot not fully initialized"})
            }

        headers = event.get('headers', {})
        request_body = event.get('body', '')

        if event.get('isBase64Encoded'):
            import base64
            request_body = base64.b64decode(request_body).decode('utf-8')

        logger.debug(f"Received webhook request. Headers: {headers}")

        try:
            event_type = headers.get('X-GitHub-Event')
            signature = headers.get('X-Hub-Signature-256')

            payload = github_utils.parse_github_webhook(request_data=request_body.encode('utf-8'), signature=signature)
            logger.info(f"Webhook event '{event_type}' parsed successfully.")
            logger.debug(f"Webhook payload: {payload}")

        except json.JSONDecodeError as json_exception:
            logger.error(f"Failed to parse webhook payload as JSON: {json_exception}", exc_info=True)
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({"error": "Bad Request", "message": "Invalid JSON payload"})
            }
        except ValueError as validation_exception:
            logger.warning(f"Webhook validation failed: {validation_exception}", exc_info=True)
            return {
                'statusCode': 401,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({"error": "Unauthorized"})
            }
        except Exception as exception:
            logger.error(f"Unexpected error during webhook parsing: {exception}", exc_info=True)
            return {
                'statusCode': 500,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({"error": "Internal Server Error", "message": "An unexpected error occurred"})
            }

        if event_type == "pull_request" and payload.get("action") in ["opened", "reopened", "synchronize", "review_requested"]:
            logger.info(
                f"Processing pull_request event for PR #{payload['pull_request']['number']} (action: {payload['action']}).")

            requested_teams = payload.get('requested_teams', [])
            requested_team = payload.get('requested_team')

            is_team_requested = any(
                team['slug'] == github_utils.trigger_team_slug for team in requested_teams
            ) or (requested_team and requested_team['slug'] == github_utils.trigger_team_slug)

            if not is_team_requested:
                logger.info(
                    f"Review not requested for team '{github_utils.trigger_team_slug}'. Ignoring PR #{payload['pull_request']['number']}.")
                return {
                    'statusCode': 200,
                    'headers': {'Content-Type': 'application/json'},
                    'body': json.dumps({"status": "ignored", "reason": "Review not requested for trigger team"})
                }

            pr_details = {
                "pr_id": payload['pull_request']['number'],
                "diff_url": payload['pull_request']['diff_url'],
                "repo_name": payload['repository']['name'],
                "repo_owner": payload['repository']['owner']['login'],
                "installation_id": payload['installation']['id']
            }
            logger.debug(f"PR Details extracted: {pr_details}")

            try:
                review_output = asyncio.run(mcp_client.send_review_request(pr_details))
            except Exception as ex:
                logger.error(f"Error during async review request for PR #{pr_details['pr_id']}: {ex}", exc_info=True)
                return {
                    'statusCode': 500,
                    'headers': {'Content-Type': 'application/json'},
                    'body': json.dumps({"status": "error", "message": f"Failed to process review request: {ex}"})
                }

            if review_output:
                logger.info(f"Received review output from Bedrock for PR #{pr_details['pr_id']}.")
                logger.debug(
                    f"Review Output: Summary='{review_output.summary[:100]}...' "
                    f"Line Comments={len(review_output.line_comments)} "
                    f"General Comments={len(review_output.general_comments)} "
                    f"Security Issues={len(review_output.security_issues)}")
                try:
                    github_utils.add_pr_review_comments(
                        repo_full_name=f"{pr_details['repo_owner']}/{pr_details['repo_name']}",
                        pr_number=pr_details['pr_id'],
                        summary=review_output.summary,
                        line_comments=review_output.line_comments,
                        general_comments=review_output.general_comments,
                        security_issues=review_output.security_issues,
                        installation_id=pr_details['installation_id']
                    )
                    logger.info(f"Successfully posted PR review comments for PR #{pr_details['pr_id']}.")
                    return {
                        'statusCode': 200,
                        'headers': {'Content-Type': 'application/json'},
                        'body': json.dumps({"status": "success", "message": "PR review comments posted."})
                    }
                except Exception as github_post_exception:
                    logger.error(
                        f"Failed to post PR review comments for PR #{pr_details['pr_id']}: {github_post_exception}",
                        exc_info=True)
                    return {
                        'statusCode': 500,
                        'headers': {'Content-Type': 'application/json'},
                        'body': json.dumps(
                            {"status": "error", "message": f"Failed to post PR review comments: {github_post_exception}"})
                    }
            else:
                logger.error(
                    f"Failed to get review payload for PR #{pr_details['pr_id']} from Bedrock. No comments will be posted.")
                return {
                    'statusCode': 500,
                    'headers': {'Content-Type': 'application/json'},
                    'body': json.dumps({"status": "error", "message": "Failed to get review from Bedrock"})
                }

        logger.info(
            f"Webhook event '{event_type}' with action '{payload.get('action')}' ignored (not a relevant pull_request event for review).")
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({"status": "ignored", "reason": "Not a relevant pull_request event"})
        }

    logger.warning(f"Unhandled path or method: {event.get('path')} {event.get('httpMethod')}")
    return {
        'statusCode': 404,
        'headers': {'Content-Type': 'application/json'},
        'body': json.dumps({"error": "Not Found", "message": "Endpoint not found"})
    }

