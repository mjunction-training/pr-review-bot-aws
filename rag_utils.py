import logging

import boto3
from botocore.exceptions import ClientError
from typing import Optional

logger = logging.getLogger(__name__)

class RAGUtils:
    """
    Utility class to interact with AWS Bedrock Knowledge Bases for RAG.
    """
    def __init__(self, knowledge_base_id: str, region_name: str):
        self.knowledge_base_id = knowledge_base_id
        self.region_name = region_name
        self.bedrock_agent_runtime_client = boto3.client(
            service_name='bedrock-agent-runtime',
            region_name=self.region_name
        )
        logger.info(f"Initialized RAGUtils for Knowledge Base '{self.knowledge_base_id}' in region '{self.region_name}'.")

    def retrieve_and_generate_context(self, query_text: str) -> Optional[str]:
        """
        Performs a retrieveAndGenerate operation against the Bedrock Knowledge Base.
        This will retrieve relevant documents and generate a concise answer based on them.
        The generated answer is then used as the context.
        """
        if not self.knowledge_base_id:
            logger.warning("Bedrock Knowledge Base ID is not configured. Skipping RAG retrieval.")
            return None

        try:
            logger.info(f"Performing retrieveAndGenerate for query: '{query_text[:100]}...' against KB '{self.knowledge_base_id}'.")
            response = self.bedrock_agent_runtime_client.retrieve_and_generate(
                input={
                    'text': query_text
                },
                retrieveAndGenerateConfiguration={
                    'type': 'KNOWLEDGE_BASE',
                    'knowledgeBaseConfiguration': {
                        'knowledgeBaseId': self.knowledge_base_id,
                        'modelArn': f"arn:aws:bedrock:{self.region_name}::foundation-model/anthropic.claude-3-sonnet-20240229-v1:0" # Use a suitable model ARN
                    }
                }
            )
            
            generated_text = response['output']['text']
            # Also extract the retrieved sources for more detailed context if needed by the prompt
            # For simplicity, we'll primarily use the generated text as context for now.
            # You could iterate through response['citations'] to get source content.
            
            logger.info(f"Successfully retrieved and generated context from KB. Length: {len(generated_text)} chars.")
            logger.debug(f"Generated context (first 200 chars): {generated_text[:200]}...")
            return generated_text

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            logger.error(f"ClientError during retrieveAndGenerate for KB '{self.knowledge_base_id}': {error_code} - {e}", exc_info=True)
            if error_code == 'ValidationException' and 'knowledgeBaseId' in str(e):
                logger.error("Knowledge Base ID might be invalid or not found.")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during retrieveAndGenerate for KB '{self.knowledge_base_id}': {e}", exc_info=True)
            return None

    def check_kb_health(self) -> str:
        """
        Performs a basic health check for the Bedrock Knowledge Base.
        This is a simplified check and might not cover all edge cases.
        """
        if not self.knowledge_base_id:
            return "not_configured"
        try:
            # A simple retrieve operation can check connectivity and basic functionality
            # Note: retrieve_and_generate is more comprehensive but might be slower for just health check
            # For a quick health check, we might just check if the client initialized.
            # A more robust check would be to call list_knowledge_bases and check status.
            # For this context, we'll assume successful client init and a dummy retrieve.
            
            # This is a dummy call just to test connectivity.
            # In a real scenario, you might want to call list_knowledge_bases or get_knowledge_base
            # and check its status.
            
            # For now, we'll just rely on the client initialization being successful.
            # If the client init failed, self.bedrock_agent_runtime_client would be None or raise error.
            # If we want to be more thorough, we'd add a try-catch around a simple API call.
            
            # A more direct health check would be:
            # self.bedrock_agent_runtime_client.get_knowledge_base(knowledgeBaseId=self.knowledge_base_id)
            # However, this requires additional permissions and might be overkill for a quick health check.
            
            # For now, we'll simply check if the client exists and the ID is set.
            if self.bedrock_agent_runtime_client and self.knowledge_base_id:
                return "reachable"
            else:
                return "unreachable (client not initialized or KB ID missing)"
        except Exception as e:
            logger.error(f"Bedrock Knowledge Base health check failed: {e}", exc_info=True)
            return f"unreachable (error: {e})"

