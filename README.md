# **GitHub PR Review Bot with AWS Lambda and Bedrock**

This project implements a GitHub Pull Request (PR) review bot that leverages AWS Lambda to handle webhooks and AWS Bedrock (specifically the Claude Sonnet model) to generate automated code reviews.

## **Features**

* **Automated PR Reviews**: Automatically reviews pull requests when they are opened, reopened, synchronized, or a review is requested for a specific team.  
* **Bedrock Integration**: Utilizes AWS Bedrock's Claude Sonnet model for comprehensive code analysis and review generation.  
* **Structured Output**: Provides a summary, line-specific comments, and identified security issues directly in GitHub PR comments.  
* **Secure Secret Management**: Retrieves sensitive credentials (GitHub App private key, webhook secret) from AWS Secrets Manager, enhancing security.  
* **Configurable**: Easy to configure GitHub App details, webhook secrets, and the target team for reviews via environment variables and Secrets Manager.  
* **Serverless Deployment**: Deploys as an AWS Lambda function, triggered by AWS API Gateway, offering scalability and cost-effectiveness.

## **Architecture**

1. **GitHub Webhook**: When a relevant PR event occurs (opened, reopened, synchronize, review requested), GitHub sends a webhook payload to an AWS API Gateway endpoint.  
2. **API Gateway**: Receives the webhook, validates the signature, and acts as a proxy to trigger the AWS Lambda function.  
3. **AWS Lambda**:  
   * The lambda\_function.py serves as the entry point.  
   * It initializes SecretUtils to securely retrieve credentials from AWS Secrets Manager.  
   * It then initializes GitHubUtils (using secrets from SecretUtils) to interact with the GitHub API (fetching diffs, posting comments) and MCPClient (which now directly interfaces with AWS Bedrock, potentially using model IDs from secrets).  
   * It processes the GitHub webhook payload.  
   * If the PR is relevant and a review is requested for the configured team, it fetches the PR diff.  
   * It constructs a detailed prompt using the diff and predefined guidelines.md.  
   * It invokes the specified AWS Bedrock model (e.g., Claude Sonnet) to generate the code review.  
   * It then invokes Bedrock again to summarize the review.  
   * Finally, it uses GitHubUtils to post the review summary, comments, and security issues back to the GitHub PR.  
4. **AWS Bedrock**: Provides the large language model capabilities (Claude Sonnet) for generating the code review and summary.  
5. **AWS Secrets Manager**: Securely stores sensitive credentials like the GitHub App private key and webhook secret.  
6. **AWS IAM**: Manages permissions for the Lambda function to interact with Bedrock, Secrets Manager, and CloudWatch Logs.

## **Prerequisites**

Before deploying, ensure you have:

* **AWS Account**: An active AWS account.  
* **AWS CLI**: Configured with credentials that have sufficient permissions to create/manage IAM roles, Lambda functions, API Gateway, and Secrets Manager.  
* **Python 3.9+**: Installed locally for packaging dependencies.  
* **pip**: Python package installer.  
* **zip**: Command-line utility for creating zip archives.  
* **GitHub App**:  
  * Create a new GitHub App in your organization/account settings.  
  * **Permissions**:  
    * Pull requests: Read & Write  
    * Contents: Read  
    * Metadata: Read  
  * **Webhook**: Enable webhooks and set the webhook secret.  
  * **Subscribe to events**: Pull requests.  
  * Generate a **private key** and download it (.pem file).  
  * Note down your **App ID**.

## **Deployment Steps**

Follow these step-by-step instructions to deploy the PR Review Bot to AWS.

### **1\. Prepare Your Project Files**

Ensure all your project files are in the same directory:

* app.py  
* github\_utils.py  
* mcp\_client.py  
* lambda\_function.py  
* guidelines.md  
* requirements.txt  
* secret\_utils.py **(New File)**  
* deploy\_lambda.sh  
* create\_api\_gateway.sh  
* create\_iam\_role.sh

### **2\. Create and Store Secrets in AWS Secrets Manager**

You need to create a secret in AWS Secrets Manager that will store your GitHub App credentials.

1. Prepare your secret content:  
   Create a JSON string containing your GitHub App ID, private key, and webhook secret.  
   Important: The GITHUB\_PRIVATE\_KEY should include actual newline characters (\\n), not escaped \\\\n.  
   {  
     "GITHUB\_APP\_ID": "YOUR\_GITHUB\_APP\_ID",  
     "GITHUB\_PRIVATE\_KEY": "-----BEGIN RSA PRIVATE KEY-----\\n...\\n-----END RSA PRIVATE KEY-----\\n",  
     "GITHUB\_WEBHOOK\_SECRET": "your\_webhook\_secret\_string",  
     "BEDROCK\_MODEL\_ID": "anthropic.claude-3-sonnet-20240229-v1:0"  
   }

   * Replace YOUR\_GITHUB\_APP\_ID with your GitHub App's ID.  
   * Replace \-----BEGIN RSA PRIVATE KEY-----\\n...\\n-----END RSA PRIVATE KEY-----\\n with the *actual content* of your .pem private key file, ensuring newlines are preserved.  
   * Replace your\_webhook\_secret\_string with your GitHub webhook secret.  
   * BEDROCK\_MODEL\_ID is optional here; if provided, mcp\_client.py will use it from Secrets Manager. Otherwise, it falls back to the environment variable.  
2. **Store the secret using AWS CLI**:  
   aws secretsmanager create-secret \\  
       \--name github/pr-review-bot-secrets \\  
       \--description "GitHub App credentials for PR Review Bot" \\  
       \--secret-string '{"GITHUB\_APP\_ID":"YOUR\_GITHUB\_APP\_ID","GITHUB\_PRIVATE\_KEY":"-----BEGIN RSA PRIVATE KEY-----\\n...\\n-----END RSA PRIVATE KEY-----\\n","GITHUB\_WEBHOOK\_SECRET":"your\_webhook\_secret\_string","BEDROCK\_MODEL\_ID":"anthropic.claude-3-sonnet-20240229-v1:0"}' \\  
       \--region YOUR\_AWS\_REGION

   * **IMPORTANT**: Replace YOUR\_GITHUB\_APP\_ID, the private key content, your\_webhook\_secret\_string, and YOUR\_AWS\_REGION with your actual values.  
   * The \--name (github/pr-review-bot-secrets) is the value you will use for SECRETS\_MANAGER\_SECRET\_NAME in your environment variables.

### **3\. Set Up Environment Variables**

Create a .env file in your project root (or set these directly in your shell/CI/CD environment) with the following:

\# .env example  
SECRETS\_MANAGER\_SECRET\_NAME="github/pr-review-bot-secrets" \# The name of the secret created in AWS Secrets Manager  
TRIGGER\_TEAM\_SLUG="ai-review-bots" \# The slug of the GitHub team that triggers reviews (e.g., 'ai-review-bots')  
AWS\_REGION="us-east-1" \# Your desired AWS region for Lambda and Bedrock (must match region of your secret)  
BEDROCK\_MODEL\_ID="anthropic.claude-3-sonnet-20240229-v1:0" \# Optional: Only needed if not stored in Secrets Manager  
LOG\_LEVEL="INFO" \# Logging level: DEBUG, INFO, WARNING, ERROR

### **4\. Create IAM Role for Lambda**

This step creates an IAM role that your Lambda function will assume. This role grants the necessary permissions to execute, write logs to CloudWatch, invoke Bedrock models, and **retrieve secrets from Secrets Manager**.

1. **Make the script executable**:  
   chmod \+x create\_iam\_role.sh

2. **Run the script**:  
   ./create\_iam\_role.sh

3. **Output**: The script will output the ARN of the newly created role (e.g., arn:aws:iam::YOUR\_AWS\_ACCOUNT\_ID:role/pr-review-bot-lambda-role). **Copy this ARN**, as you will need it in the next step.

### **5\. Deploy Lambda Function**

This step packages your Python code and its dependencies into a ZIP file and deploys it as an AWS Lambda function.

1. **Update deploy\_lambda.sh**:  
   * Open deploy\_lambda.sh in a text editor.  
   * **Replace LAMBDA\_ROLE\_ARN**: Paste the IAM Role ARN you copied from the previous step.  
   * **Replace SECRETS\_MANAGER\_SECRET\_NAME**: Ensure this matches the name you used when creating the secret in AWS Secrets Manager.  
   * **Verify Region**: Ensure AWS\_REGION matches your desired region.  
   * **Note**: GITHUB\_APP\_ID, GITHUB\_PRIVATE\_KEY, and GITHUB\_WEBHOOK\_SECRET are now read from Secrets Manager, so they are removed from the explicit environment variable list in this script.  
2. **Make the script executable**:  
   chmod \+x deploy\_lambda.sh

3. **Run the script**:  
   ./deploy\_lambda.sh

4. **Output**: The script will confirm the creation or update of your Lambda function.

### **6\. Create API Gateway Endpoint**

This step sets up an AWS API Gateway REST API that will serve as the public endpoint for your GitHub webhook and health checks.

1. **Update create\_api\_gateway.sh**:  
   * Open create\_api\_gateway.sh in a text editor.  
   * **Verify Lambda Function Name and Region**: Ensure LAMBDA\_FUNCTION\_NAME and AWS\_REGION match the values used when deploying your Lambda function.  
2. **Make the script executable**:  
   chmod \+x create\_api\_gateway.sh

3. **Run the script**:  
   ./create\_api\_gateway.sh

4. **Output**: The script will output your API Gateway **Webhook URL** (e.g., https://\<api-id\>.execute-api.\<region\>.amazonaws.com/\<stage\>/webhook) and **Health Check URL**. **Copy the Webhook URL**, as you will need it for configuring GitHub.

### **7\. Configure GitHub Webhook**

This final step tells GitHub where to send the PR events.

1. **Go to your GitHub repository settings**: In your web browser, navigate to the GitHub repository where you want the bot to operate.  
2. **Access Webhooks**: Click on "Settings" \-\> "Webhooks" in the left sidebar.  
3. **Add Webhook**: Click the "Add webhook" button.  
4. **Fill in details**:  
   * **Payload URL**: Paste the **Webhook URL** you copied from the output of create\_api\_gateway.sh.  
   * **Content type**: Select application/json.  
   * **Secret**: Paste your GITHUB\_WEBHOOK\_SECRET (the same value you stored in Secrets Manager).  
   * **Which events would you like to trigger this webhook?**: Select "Let me select individual events" and ensure only Pull requests is checked.  
   * **Active**: Ensure the "Active" checkbox is ticked.  
5. Click "Add webhook".

### **8\. Test the Bot**

1. **Create a new pull request**: In your GitHub repository, create a new pull request.  
2. **Request Review (Optional but Recommended)**: To ensure the bot is triggered, ensure the pull request has a review requested for the team specified in your TRIGGER\_TEAM\_SLUG environment variable (e.g., ai-review-bots).  
3. **Check Webhook Deliveries**: Go back to your GitHub webhook settings for the repository. In the "Recent Deliveries" section, you should see new deliveries with an HTTP 200 status code, indicating successful invocation of your Lambda function.  
4. **Monitor CloudWatch Logs**: Open the AWS CloudWatch console, navigate to "Log groups", and find the log group for your Lambda function (e.g., /aws/lambda/pr-review-bot-lambda). Monitor the logs for execution details, any errors, or messages indicating the review process.  
5. **Observe PR Comments**: Check the comments section of your pull request on GitHub. You should see the automated review summary, general comments, and security issues posted by the bot.

## **Project Structure**

* app.py: (Original Flask app, now mostly superseded by lambda\_function.py for Lambda deployment, but contains core logic for webhook handling that lambda\_function.py adapts).  
* github\_utils.py: Handles GitHub API interactions, including webhook validation, fetching diffs, and posting comments.  
* mcp\_client.py: **(Modified)** Now directly integrates with AWS Bedrock to invoke LLMs for review generation and summarization.  
* \`lambda\_function