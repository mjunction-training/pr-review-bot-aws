import json
import logging

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

class SecretUtils:
    """
    Utility class to retrieve secrets from AWS Secrets Manager.
    """
    def __init__(self, secret_name: str, region_name: str):
        self.secret_name = secret_name
        self.region_name = region_name
        self.client = boto3.client('secretsmanager', region_name=self.region_name)
        self._secrets_cache = None # Cache the secrets after first retrieval

    def get_secret(self) -> dict:
        """
        Retrieves the secret string from AWS Secrets Manager and parses it as JSON.
        Caches the result after the first successful retrieval.
        """
        if self._secrets_cache:
            logger.debug("Returning secrets from cache.")
            return self._secrets_cache

        try:
            logger.info(f"Attempting to retrieve secret '{self.secret_name}' from AWS Secrets Manager in region '{self.region_name}'.")
            get_secret_value_response = self.client.get_secret_value(
                SecretId=self.secret_name
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            if error_code == 'DecryptionFailureException':
                # Secrets Manager can't decrypt the protected secret text using the provided KMS key.
                logger.error(f"DecryptionFailureException: The secret can't be decrypted. {e}")
                raise ValueError(f"Failed to decrypt secret: {e}")
            elif error_code == 'InternalServiceErrorException':
                # An error occurred on the server side.
                logger.error(f"InternalServiceErrorException: An internal error occurred. {e}")
                raise ValueError(f"Internal service error: {e}")
            elif error_code == 'InvalidParameterException':
                # You provided an invalid value for a parameter.
                logger.error(f"InvalidParameterException: Invalid parameter provided. {e}")
                raise ValueError(f"Invalid parameter for secret retrieval: {e}")
            elif error_code == 'InvalidRequestException':
                # You provided a parameter value that is not valid for the current state of the resource.
                logger.error(f"InvalidRequestException: Invalid request for secret retrieval. {e}")
                raise ValueError(f"Invalid request for secret retrieval: {e}")
            elif error_code == 'ResourceNotFoundException':
                # We can't find the resource that you asked for.
                logger.error(f"ResourceNotFoundException: Secret '{self.secret_name}' not found. {e}")
                raise ValueError(f"Secret '{self.secret_name}' not found: {e}")
            else:
                logger.error(f"An unexpected ClientError occurred: {e}", exc_info=True)
                raise ValueError(f"AWS Secrets Manager ClientError: {e}")
        except Exception as e:
            logger.error(f"An unexpected error occurred during secret retrieval: {e}", exc_info=True)
            raise ValueError(f"Unexpected error retrieving secret: {e}")
        else:
            # Decrypts secret using the associated KMS key.
            # Depending on whether the secret is a string or binary, one of these fields will be populated.
            if 'SecretString' in get_secret_value_response:
                secret = get_secret_value_response['SecretString']
                try:
                    self._secrets_cache = json.loads(secret)
                    logger.info("Successfully retrieved and parsed secret.")
                    return self._secrets_cache
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to decode JSON from secret string: {e}. Raw secret: {secret[:100]}...", exc_info=True)
                    raise ValueError(f"Secret is not valid JSON: {e}")
            else:
                # If the secret is binary, you would handle it here.
                # For this application, we expect string secrets.
                logger.error(f"Secret '{self.secret_name}' does not contain 'SecretString'. Binary secrets are not supported.")
                raise ValueError("Secret does not contain a string value.")

    def get_github_app_id(self) -> str:
        """Retrieves GitHub App ID from the secret."""
        return self.get_secret().get("GITHUB_APP_ID")

    def get_github_private_key(self) -> str:
        """Retrieves GitHub Private Key from the secret."""
        return self.get_secret().get("GITHUB_PRIVATE_KEY")

    def get_github_webhook_secret(self) -> str:
        """Retrieves GitHub Webhook Secret from the secret."""
        return self.get_secret().get("GITHUB_WEBHOOK_SECRET")

    def get_bedrock_model_id(self) -> str:
        """Retrieves Bedrock Model ID from the secret (optional, if stored there)."""
        # This is optional. If BEDROCK_MODEL_ID is still an env var, this method won't be used.
        return self.get_secret().get("BEDROCK_MODEL_ID")

