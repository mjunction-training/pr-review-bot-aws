import logging
from typing import List, Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

class S3Utils:
    """
    Utility class to interact with AWS S3 for reading project files.
    """
    def __init__(self, bucket_name: str, region_name: str):
        self.bucket_name = bucket_name
        self.region_name = region_name
        self.s3_client = boto3.client('s3', region_name=self.region_name)
        logger.info(f"Initialized S3Utils for bucket '{self.bucket_name}' in region '{self.region_name}'.")

    def _list_objects_in_prefix(self, prefix: str) -> List[str]:
        """
        Lists all object keys within a given S3 prefix.
        """
        keys = []
        paginator = self.s3_client.get_paginator('list_objects_v2')
        try:
            pages = paginator.paginate(Bucket=self.bucket_name, Prefix=prefix)
            for page in pages:
                if "Contents" in page:
                    for obj in page['Contents']:
                        keys.append(obj['Key'])
            logger.debug(f"Found {len(keys)} objects under s3://{self.bucket_name}/{prefix}")
            return keys
        except ClientError as e:
            logger.error(f"Failed to list objects in s3://{self.bucket_name}/{prefix}: {e}", exc_info=True)
            raise ValueError(f"S3 list objects error: {e}")
        except Exception as e:
            logger.error(f"Unexpected error listing S3 objects: {e}", exc_info=True)
            raise

    def _get_object_content(self, key: str) -> Optional[str]:
        """
        Downloads the content of a single S3 object as a string.
        """
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            content = response['Body'].read().decode('utf-8')
            logger.debug(f"Successfully read content from s3://{self.bucket_name}/{key}")
            return content
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                logger.warning(f"S3 object s3://{self.bucket_name}/{key} not found.")
                return None
            logger.error(f"Failed to get object s3://{self.bucket_name}/{key}: {e}", exc_info=True)
            raise ValueError(f"S3 get object error: {e}")
        except Exception as e:
            logger.error(f"Unexpected error getting S3 object: {e}", exc_info=True)
            raise

    def read_project_knowledge_base(self, project_prefix: str) -> str:
        """
        Reads all text files under a given S3 project prefix and
        compiles them into a single string formatted as a knowledge base.
        Binary files will be skipped.
        """
        knowledge_base_content = []
        logger.info(f"Building knowledge base from s3://{self.bucket_name}/{project_prefix}")

        try:
            file_keys = self._list_objects_in_prefix(project_prefix)
            if not file_keys:
                logger.warning(f"No files found in s3://{self.bucket_name}/{project_prefix} to build knowledge base.")
                return ""

            for key in file_keys:
                # Skip directories and non-text files (basic heuristic)
                if key.endswith('/') or not (key.endswith('.py') or key.endswith('.js') or key.endswith('.html') or key.endswith('.css') or key.endswith('.md') or key.endswith('.txt') or key.endswith('.json') or key.endswith('.yaml') or key.endswith('.yml')):
                    logger.debug(f"Skipping non-text or directory object: {key}")
                    continue

                file_content = self._get_object_content(key)
                if file_content is not None:
                    # Format: <file_path>content_of_file</file_path>
                    # Using XML-like tags for clear separation in the prompt
                    knowledge_base_content.append(f"<file_path>{key}</file_path>\n<file_content>\n{file_content}\n</file_content>\n")
                else:
                    logger.warning(f"Could not retrieve content for {key}, skipping.")

            if not knowledge_base_content:
                logger.warning(f"No readable text files found in s3://{self.bucket_name}/{project_prefix} for knowledge base.")
                return ""

            final_knowledge_base = "\n".join(knowledge_base_content)
            logger.info(f"Knowledge base built successfully. Total size: {len(final_knowledge_base)} characters.")
            return final_knowledge_base

        except Exception as e:
            logger.error(f"Failed to build knowledge base from S3: {e}", exc_info=True)
            return ""

