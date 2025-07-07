#!/bin/bash

# This script automates the deployment of the PR Review Bot Lambda function.
# Prerequisites:
# - AWS CLI configured with appropriate credentials.
# - Zip utility installed.
# - Python 3.9+ installed locally with pip.
# - All project files (app.py, github_utils.py, mcp_client.py, lambda_function.py, guidelines.md, secret_utils.py)
#   and requirements.txt in the same directory.

# --- Configuration Variables ---
# Replace with your desired values
LAMBDA_FUNCTION_NAME="pr-review-bot-lambda"
AWS_REGION="us-east-1" # Ensure this matches the region configured in mcp_client.py
HANDLER_FILE="lambda_function.py"
HANDLER_FUNCTION="lambda_handler"
RUNTIME="python3.9" # Or python3.10, python3.11 etc.
TIMEOUT=600 # Maximum execution time for Lambda (in seconds) - PR reviews can take time
MEMORY=512 # Memory for Lambda (in MB)
DESCRIPTION="GitHub PR Review Bot powered by AWS Bedrock (Secrets Manager enabled)"
REQUIREMENTS_FILE="requirements.txt"
ZIP_FILE="pr_review_bot.zip"

# IAM Role ARN for the Lambda function.
# This role must have permissions for:
# - AWSLambdaBasicExecutionRole (CloudWatch Logs)
# - bedrock:InvokeModel, bedrock:ListFoundationModels (for Bedrock access)
# - secretsmanager:GetSecretValue (for retrieving secrets)
# - (Optional) s3:GetObject if guidelines.md or other assets are loaded from S3
LAMBDA_ROLE_ARN="arn:aws:iam::YOUR_AWS_ACCOUNT_ID:role/pr-review-bot-lambda-role" # !!! IMPORTANT: REPLACE THIS WITH YOUR ACTUAL IAM ROLE ARN !!!

# --- Environment Variables for Lambda ---
# These are configurations for the Lambda function. Secrets will be retrieved from Secrets Manager.
TRIGGER_TEAM_SLUG="ai-review-bots" # Default from github_utils.py
BEDROCK_MODEL_ID="anthropic.claude-3-sonnet-20240229-v1:0" # Default from mcp_client.py (can be overridden by secret)
LOG_LEVEL="INFO" # DEBUG, INFO, WARNING, ERROR

# --- Secrets Manager Configuration ---
# This is the name of the secret in AWS Secrets Manager that holds your GitHub App credentials.
# The secret should be a JSON string with keys: GITHUB_APP_ID, GITHUB_PRIVATE_KEY, GITHUB_WEBHOOK_SECRET
# Example secret value:
# {
#   "GITHUB_APP_ID": "123456",
#   "GITHUB_PRIVATE_KEY": "-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----\n",
#   "GITHUB_WEBHOOK_SECRET": "your_webhook_secret_string",
#   "BEDROCK_MODEL_ID": "anthropic.claude-3-sonnet-20240229-v1:0" # Optional: if you want to manage model ID as a secret
# }
SECRETS_MANAGER_SECRET_NAME="github/pr-review-bot-secrets" # !!! IMPORTANT: REPLACE THIS WITH YOUR ACTUAL SECRETS MANAGER SECRET NAME !!!


# --- 1. Clean up previous build artifacts ---
echo "--- Cleaning up previous build artifacts ---"
rm -rf package/
rm -f "$ZIP_FILE"

# --- 2. Install dependencies into a package directory ---
echo "--- Installing Python dependencies ---"
mkdir -p package
pip install -r "$REQUIREMENTS_FILE" --target package/

# --- 3. Copy application files into the package directory ---
echo "--- Copying application files ---"
cp "$HANDLER_FILE" package/
cp github_utils.py package/
cp mcp_client.py package/
cp guidelines.md package/
cp secret_utils.py package/ # Copy the new secret_utils.py

# --- 4. Create deployment package (ZIP file) ---
echo "--- Creating deployment package ($ZIP_FILE) ---"
(cd package && zip -r ../"$ZIP_FILE" .)

# --- 5. Deploy or Update Lambda Function ---
echo "--- Deploying/Updating Lambda function ---"

# Check if the Lambda function already exists
FUNCTION_EXISTS=$(aws lambda get-function --function-name "$LAMBDA_FUNCTION_NAME" --region "$AWS_REGION" 2>/dev/null)

# Define environment variables to pass to Lambda
LAMBDA_ENV_VARS="TRIGGER_TEAM_SLUG=$TRIGGER_TEAM_SLUG,AWS_REGION=$AWS_REGION,BEDROCK_MODEL_ID=$BEDROCK_MODEL_ID,LOG_LEVEL=$LOG_LEVEL,SECRETS_MANAGER_SECRET_NAME=$SECRETS_MANAGER_SECRET_NAME"

if [ -z "$FUNCTION_EXISTS" ]; then
    echo "Creating new Lambda function: $LAMBDA_FUNCTION_NAME"
    aws lambda create-function \
        --function-name "$LAMBDA_FUNCTION_NAME" \
        --runtime "$RUNTIME" \
        --role "$LAMBDA_ROLE_ARN" \
        --handler "$HANDLER_FILE"."$HANDLER_FUNCTION" \
        --zip-file "fileb://$ZIP_FILE" \
        --timeout "$TIMEOUT" \
        --memory "$MEMORY" \
        --description "$DESCRIPTION" \
        --environment "Variables={${LAMBDA_ENV_VARS}}" \
        --region "$AWS_REGION"
else
    echo "Updating existing Lambda function: $LAMBDA_FUNCTION_NAME"
    aws lambda update-function-code \
        --function-name "$LAMBDA_FUNCTION_NAME" \
        --zip-file "fileb://$ZIP_FILE" \
        --region "$AWS_REGION"

    aws lambda update-function-configuration \
        --function-name "$LAMBDA_FUNCTION_NAME" \
        --runtime "$RUNTIME" \
        --role "$LAMBDA_ROLE_ARN" \
        --handler "$HANDLER_FILE"."$HANDLER_FUNCTION" \
        --timeout "$TIMEOUT" \
        --memory "$MEMORY" \
        --description "$DESCRIPTION" \
        --environment "Variables={${LAMBDA_ENV_VARS}}" \
        --region "$AWS_REGION"
fi

echo "Lambda deployment script finished. Function: $LAMBDA_FUNCTION_NAME in $AWS_REGION"
echo "Remember to configure API Gateway and IAM permissions separately."

