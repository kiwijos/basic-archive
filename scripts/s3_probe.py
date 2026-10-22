"""Shows what an S3 access key may do, by trying. Run inside the cluster with the key id and the
secret on two lines of stdin: python -c "$(cat s3_probe.py)" < keys"""

import json
import os
import sys

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

key, secret = (sys.stdin.readline().strip() for _ in range(2))
s3 = boto3.client(
    "s3",
    endpoint_url=os.environ["S3_ENDPOINT_URL"],
    aws_access_key_id=key,
    aws_secret_access_key=secret,
    region_name="garage",
    config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 1}),
)


def attempt(action) -> str:
    try:
        action()
    except ClientError as error:
        code = error.response["Error"]["Code"]
        return "denied" if code in ("AccessDenied", "403") else f"error:{code}"
    return "allowed"


results = {
    "write masters": attempt(lambda: s3.put_object(Bucket="masters", Key="probe", Body=b"x")),
    "read masters": attempt(lambda: s3.list_objects_v2(Bucket="masters", MaxKeys=1)),
    "write derivatives": attempt(lambda: s3.put_object(Bucket="derivatives", Key="probe", Body=b"x")),
    "read derivatives": attempt(lambda: s3.list_objects_v2(Bucket="derivatives", MaxKeys=1)),
}
if results["write masters"] == "allowed":
    s3.delete_object(Bucket="masters", Key="probe")
print(json.dumps(results, sort_keys=True))
