import boto3
import os
import zipfile
import requests
import json

codecommit = boto3.client('codecommit')
s3 = boto3.client('s3')

bucket_name = os.environ['BUCKET_NAME']

# Authorizer API
API_ENDPOINT = os.environ.get("AUTHORIZER_ENDPOINT_URL")

def get_token_data(token):
    """
    Fetch data associated with a given token from a predefined API endpoint.
    Args:
    - token (str): The token for which data needs to be fetched.
    Returns:
    - response (Response): The full response from the API. This includes the status code, 
                           headers, and a response containing the data from decoded token.
    """
    
    headers = {
        "Authorization": f"Bearer {token}"
    }

    # Make the request to the API
    response = requests.get(API_ENDPOINT, headers=headers)
    
    # Return the whole response
    return response


def lambda_handler(event, context):
    
    # Get user token
    authorization_header = event.get("headers", {}).get("authorization", "")
    if authorization_header.startswith("Bearer "):
        userToken = authorization_header[7:]  # Remove "Bearer " prefix
    else:
        userToken = None
    
    # Get data from the user token
    auth_response = get_token_data(userToken)
    
    # Check if the response is not successful
    if auth_response.status_code != 200:
        return {
            'statusCode':auth_response.status_code,
            'headers':{
                "Access-Control-Allow-Headers": 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token',
                "Access-Control-Allow-Origin":"*",
                "Access-Control-Allow-Methods":"*",
            },
            'body':auth_response.text
            
        }
    
    # Get the user sub from the response
    response_json = json.loads(auth_response.text)
    user_sub = response_json.get('sub', 'Sub not found')
    
    # Get the full repo name
    repository_name = user_sub + event['queryStringParameters']['Repository']
    
    # Get branch name 
    branch_name = event['queryStringParameters'].get('branch_name', 'main')  # default to 'main' branch
    
    #s3_key = event.get('s3_key', f'{repository_name}.zip')  # default to repository_name.zip
    s3_key = user_sub + '/' + 'download artifacts' + '/' + event['queryStringParameters']['Repository'] + '.zip'

    # Get the latest commit ID of the branch
    response = codecommit.get_branch(
        repositoryName=repository_name,
        branchName=branch_name
    )
    latest_commit_id = response['branch']['commitId']

    # Start with the root folder
    folder_paths = ['/']

    zip_file_path = '/tmp/repository_files.zip'
    with zipfile.ZipFile(zip_file_path, 'w') as zipped_files:
        while folder_paths:
            current_folder = folder_paths.pop()
            response = codecommit.get_folder(
                repositoryName=repository_name,
                folderPath=current_folder,
                commitSpecifier=latest_commit_id  # Specify the latest commit ID
            )

            # Add subfolders to the list to traverse
            for subfolder in response.get('subFolders', []):
                folder_paths.append(subfolder['absolutePath'])

            # Save file contents to the zip
            for file_entry in response.get('files', []):
                file_path = file_entry['absolutePath']
                zipped_files.writestr(file_path, file_entry['blobId'])  # Using blobId as placeholder for actual content. Adjust as needed.

    # Upload the zip file to S3
    with open(zip_file_path, 'rb') as zipped_files:
        s3.upload_fileobj(zipped_files, bucket_name, s3_key)
    
    # Generate a presigned URL for temporary download
    url = s3.generate_presigned_url(
        'get_object',
        Params={'Bucket': bucket_name, 'Key': s3_key},
        ExpiresIn=3600  # 1 hour expiry
    )
    
    return {
        'statusCode': 200,
        'body': f"Temporary download link for {event['queryStringParameters']['Repository']} (branch: {branch_name}, commit: {latest_commit_id}): {url}"
    }