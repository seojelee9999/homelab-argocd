"""Create missing database passwords in SSM without printing secret values.

Run on the control plane with boto3 and the homelab-eso AWS profile.
Existing parameters are never overwritten. Use --create to create missing ones.
"""
import argparse
import secrets

import boto3
from botocore.exceptions import ClientError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', default='homelab-eso')
    parser.add_argument('--region', default='ap-northeast-2')
    parser.add_argument('--create', action='store_true')
    args = parser.parse_args()
    client = boto3.Session(profile_name=args.profile, region_name=args.region).client('ssm')
    for name in ('/homelab/diet-app/DB_PASSWORD', '/homelab/diet-app/POSTGRES_ADMIN_PASSWORD'):
        try:
            parameter = client.get_parameter(Name=name, WithDecryption=False)['Parameter']
            if parameter['Type'] != 'SecureString':
                raise SystemExit(f'{name}: expected SecureString; refusing to overwrite')
            print(f'{name}: exists, unchanged')
        except client.exceptions.ParameterNotFound:
            if args.create:
                client.put_parameter(Name=name, Value=secrets.token_urlsafe(36),
                                     Type='SecureString', Overwrite=False)
                print(f'{name}: created SecureString')
            else:
                print(f'{name}: missing (use --create)')


if __name__ == '__main__':
    try:
        main()
    except ClientError as exc:
        raise SystemExit(f"SSM request failed: {exc.response['Error']['Code']}") from None
