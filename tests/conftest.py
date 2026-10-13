import boto3
import pytest
from moto import mock_aws

from escapadinha.storage.s3 import S3ObjectStore


@pytest.fixture
def s3_store():
    """S3ObjectStore on moto's in-process S3 mock (no network). moto honours the
    conditional headers (If-None-Match / If-Match) the lock relies on."""
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1", aws_access_key_id="test",
                              aws_secret_access_key="test")
        client.create_bucket(Bucket="escapadinha")
        yield S3ObjectStore(client, "escapadinha")
