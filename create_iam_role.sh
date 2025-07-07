#!/bin/bash

# This script automates the creation of an IAM Role and policies
# required for the AWS Lambda function for the PR Review Bot.
# Prerequisites:
# - AWS CLI configured with appropriate credentials.

# --- Configuration Variables ---
ROLE_NAME="pr-review-bot-lambda-role"
POLICY_NAME_BEDROCK_LLM="pr-review-bot-bedrock-llm-policy" # Renamed for clarity
POLICY_NAME_SECRETS="pr-review-bot-secrets-policy"
POLICY_NAME_BEDROCK_KB="pr-review-bot-bedrock-kb-policy" # New policy name for Bedrock Knowledge Base
AWS_REGION="us-east-1" # Ensure this matches your Lambda and Bedrock region


# --- 1. Create IAM Role for Lambda ---
echo "--- Creating IAM Role: $ROLE_NAME ---"
# Define the trust policy for the Lambda service
TRUST_POLICY='{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}'

ROLE_ARN=$(aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "$TRUST_POLICY" \
    --description "IAM role for GitHub PR Review Bot Lambda function" \
    --query 'Role.Arn' \
    --output text)

if [ -z "$ROLE_ARN" ]; then
    echo "Failed to create IAM role. Exiting."
    exit 1
fi
echo "IAM Role '$ROLE_NAME' created with ARN: $ROLE_ARN"

# --- 2. Attach AWS Managed Policy for Basic Lambda Execution (CloudWatch Logs) ---
echo "--- Attaching AWS Managed Policy: AWSLambdaBasicExecutionRole ---"
aws iam attach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"

# --- 3. Create Inline Policy for Bedrock LLM Access ---
echo "--- Creating Inline Policy for Bedrock LLM Access: $POLICY_NAME_BEDROCK_LLM ---"
# Policy to allow invoking Bedrock foundation models
BEDROCK_LLM_POLICY_DOCUMENT='{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "bedrock:InvokeModel",
                "bedrock:ListFoundationModels"
            ],
            "Resource": "*"
        }
    ]
}'

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "$POLICY_NAME_BEDROCK_LLM" \
    --policy-document "$BEDROCK_LLM_POLICY_DOCUMENT"

echo "Inline policy '$POLICY_NAME_BEDROCK_LLM' attached to role '$ROLE_NAME'."

# --- 4. Create Inline Policy for Secrets Manager Access ---
echo "--- Creating Inline Policy for Secrets Manager Access: $POLICY_NAME_SECRETS ---"
# Policy to allow retrieving secrets from Secrets Manager
# IMPORTANT: For production, narrow down the Resource to specific secret ARNs if possible.
SECRETS_POLICY_DOCUMENT='{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "secretsmanager:GetSecretValue"
            ],
            "Resource": "arn:aws:secretsmanager:*:*:secret:github/pr-review-bot-secrets-*"
        }
    ]
}'

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "$POLICY_NAME_SECRETS" \
    --policy-document "$SECRETS_POLICY_DOCUMENT"

echo "Inline policy '$POLICY_NAME_SECRETS' attached to role '$ROLE_NAME'."

# --- 5. Create Inline Policy for Bedrock Knowledge Base Access ---
echo "--- Creating Inline Policy for Bedrock Knowledge Base Access: $POLICY_NAME_BEDROCK_KB ---"
# Policy to allow interacting with Bedrock Knowledge Bases
BEDROCK_KB_POLICY_DOCUMENT='{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "bedrock:Retrieve",
                "bedrock:RetrieveAndGenerate"
            ],
            "Resource": "arn:aws:bedrock:*:*:knowledge-base/*" # All knowledge bases. Narrow down if possible.
        }
    ]
}'

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "$POLICY_NAME_BEDROCK_KB" \
    --policy-document "$BEDROCK_KB_POLICY_DOCUMENT"

echo "Inline policy '$POLICY_NAME_BEDROCK_KB' attached to role '$ROLE_NAME'."


echo "IAM Role and policies setup finished."
echo "Please use the following ARN for your Lambda function: $ROLE_ARN"
echo "You can now proceed with deploying your Lambda function using this role."

