#!/bin/bash

# This script automates the deployment of the PR Review Bot Lambda function.
# Prerequisites:
# - AWS CLI configured with appropriate credentials.
# - Zip utility installed.
# - Python 3.9+ installed locally with pip.
# - All project files (app.py, github_utils.py, mcp_client.py, lambda_function.py, guidelines.md, secret_utils.py, rag_utils.py)
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
DESCRIPTION="GitHub PR Review Bot powered by AWS Bedrock (Secrets Manager & RAG KB enabled)"
REQUIREMENTS_FILE="requirements.txt"
ZIP_FILE="pr_review_bot.zip"

# IAM Role ARN for the Lambda function.
# This role must have permissions for:
# - AWSLambdaBasicExecutionRole (CloudWatch Logs)
# - bedrock:InvokeModel, bedrock:ListFoundationModels (for Bedrock LLM access)
# - secretsmanager:GetSecretValue (for retrieving secrets)
# - bedrock:Retrieve, bedrock:RetrieveAndGenerate (for Bedrock Knowledge Base access)
LAMBDA_ROLE_ARN="arn:aws:iam::YOUR_AWS_ACCOUNT_ID:role/pr-review-bot-lambda-role" # !!! IMPORTANT: REPLACE THIS WITH YOUR ACTUAL IAM ROLE ARN !!!

# --- Environment Variables for Lambda ---
# These are configurations for the Lambda function. Secrets will be retrieved from Secrets Manager.
TRIGGER_TEAM_SLUG="ai-review-bots" # Default from github_utils.py
LOG_LEVEL="INFO" # DEBUG, INFO, WARNING, ERROR

# --- Secrets Manager Configuration ---
# This is the name of the secret in AWS Secrets Manager that holds your GitHub App credentials.
# It can also optionally hold BEDROCK_MODEL_ID and BEDROCK_KNOWLEDGE_BASE_ID.
SECRETS_MANAGER_SECRET_NAME="github/pr-review-bot-secrets" # !!! IMPORTANT: REPLACE THIS WITH YOUR ACTUAL SECRETS MANAGER SECRET NAME !!!

# --- Bedrock Knowledge Base Configuration (Optional - can also be in Secrets Manager) ---
# If you want to specify the Knowledge Base ID via an environment variable instead of Secrets Manager
# BEDROCK_KNOWLEDGE_BASE_ID="YOUR_BEDROCK_KNOWLEDGE_BASE_ID" # !!! IMPORTANT: REPLACE THIS IF NOT IN SECRETS MANAGER !!!
BEDROCK_KNOWLEDGE_BASE_ID="" # Leave empty if pulling from Secrets Manager


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
cp secret_utils.py package/
cp rag_utils.py package/ # Copy the new rag_utils.py

# --- 4. Create deployment package (ZIP file) ---
echo "--- Creating deployment package ($ZIP_FILE) ---"
(cd package && zip -r ../"$ZIP_FILE" .)

# --- 5. Deploy or Update Lambda Function ---
echo "--- Deploying/Updating Lambda function ---"

# Check if the Lambda function already exists
FUNCTION_EXISTS=$(aws lambda get-function --function-name "$LAMBDA_FUNCTION_NAME" --region "$AWS_REGION" 2>/dev/null)

# Build environment variables string dynamically
LAMBDA_ENV_VARS="TRIGGER_TEAM_SLUG=$TRIGGER_TEAM_SLUG,AWS_REGION=$AWS_REGION,LOG_LEVEL=$LOG_LEVEL,SECRETS_MANAGER_SECRET_NAME=$SECRETS_MANAGER_SECRET_NAME"
if [ -n "$BEDROCK_KNOWLEDGE_BASE_ID" ]; then
    LAMBDA_ENV_VARS="${LAMBDA_ENV_VARS},BEDROCK_KNOWLEDGE_BASE_ID=$BEDROCK_KNOWLEDGE_BASE_ID"
fi
# BEDROCK_MODEL_ID is now primarily sourced from Secrets Manager, no need to explicitly pass here unless as fallback

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

