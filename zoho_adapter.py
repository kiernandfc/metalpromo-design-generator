# zoho_adapter.py
import requests # Will be used for actual API calls
import json # For pretty printing and the new parser
import os
import time
import base64 # For encoding file data
import logging
import io # For file handling
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple # For type hinting
from PIL import Image # For image processing

# Import credentials from shared config module (works with both Streamlit secrets and .env)
from config import (
    ZOHO_CLIENT_ID,
    ZOHO_CLIENT_SECRET,
    ZOHO_REFRESH_TOKEN,
    ZOHO_API_BASE_URL,
    ZOHO_TOKEN_URL,
    ZOHO_WORKDRIVE_API_URL
)

def get_access_token(scope: str = None):
    """
    Refreshes and returns the Zoho API access token using the refresh token.
    Optionally requests specific scopes for the access token.
    
    Args:
        scope: Optional scope to request for the access token (e.g., 'ZohoCRM.modules.ALL,WorkDrive.files.ALL')
    """
    if not all([ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN, ZOHO_TOKEN_URL]):
        print("DEBUG: Zoho credentials (client ID, secret, refresh token, token URL) not fully configured in .env")
        return None

    payload = {
        'refresh_token': ZOHO_REFRESH_TOKEN,
        'client_id': ZOHO_CLIENT_ID,
        'client_secret': ZOHO_CLIENT_SECRET,
        'grant_type': 'refresh_token',
    }
    
    # Add scope if specified
    if scope:
        print(f"DEBUG: Requesting access token with scope: {scope}")
        payload['scope'] = scope

    try:
        print(f"DEBUG: Token request payload: {payload}")
        print(f"DEBUG: Requesting access token from {ZOHO_TOKEN_URL}")
        response = requests.post(ZOHO_TOKEN_URL, data=payload)
        response.raise_for_status()  # Raises HTTPError for bad responses (4XX or 5XX)
        
        token_data = response.json()
        access_token = token_data.get('access_token')
        
        if access_token:
            print("DEBUG: Successfully obtained new access token from Zoho.")
            # The token typically expires in 1 hour (3600 seconds). 
            # You might want to store it with its expiry time if making frequent calls.
            # For this app's lifecycle (single run per design request), fetching it once is likely fine.
            return access_token
        else:
            print(f"DEBUG: 'access_token' not found in Zoho's response. Response: {token_data}")
            return None
            
    except requests.exceptions.HTTPError as http_err:
        print(f"DEBUG: HTTP error occurred while requesting Zoho token: {http_err} - Response: {response.text}")
        return None
    except requests.exceptions.RequestException as req_err:
        print(f"DEBUG: Request exception occurred while requesting Zoho token: {req_err}")
        return None
    except ValueError as json_err: # Includes JSONDecodeError
        print(f"DEBUG: JSON decoding error occurred while parsing Zoho token response: {json_err} - Response: {response.text}")
        return None

def _parse_note_content_to_dict(note_content_str: str) -> Dict[str, Optional[str]]:
    """
    Parses a string of key-value pairs (separated by ': ') into a dictionary.
    Extracts a predefined set of keys.
    Specifically handles challenge_notes by extracting all content between 
    'challenge_notes:' and '\nchallenge_shape_notes:' markers.
    If the content isn't in key-value format, treats it as challenge_notes.
    """
    parsed_data: Dict[str, Optional[str]] = {}
    raw_fields: Dict[str, str] = {}
    non_kv_lines = []

    if not note_content_str or not isinstance(note_content_str, str):
        print("DEBUG: _parse_note_content_to_dict received empty or invalid content.")
        # Initialize target keys with None if content is bad
        for key in [
            "first_name", "last_name", "type_1", "lead_source", "date", 
            "organization_name", "challenge_notes", "challenge_size", 
            "first_file", "second_file"
        ]:
            parsed_data[key] = None
        return parsed_data
    
    # First, extract challenge_notes specially since it may contain newlines
    challenge_notes = None
    challenge_notes_start = note_content_str.find("challenge_notes:")
    if challenge_notes_start != -1:
        # Find the start of the challenge_notes value (after the colon)
        value_start = challenge_notes_start + len("challenge_notes:")
        
        # Find the next marker after challenge_notes
        next_marker = note_content_str.find("\nchallenge_shape_notes:", value_start)
        if next_marker != -1:
            challenge_notes = note_content_str[value_start:next_marker].strip()
            print(f"DEBUG: Extracted challenge_notes with newlines. First 50 chars: {challenge_notes[:50]}...")
            raw_fields["challenge_notes"] = challenge_notes
            
            # Create a modified string for the rest of the parsing by removing the challenge_notes section
            # We'll replace it with a simple placeholder that won't be processed again
            note_content_str = (note_content_str[:challenge_notes_start] + 
                               "challenge_notes: [EXTRACTED]" + 
                               note_content_str[next_marker:])
    
    # Check for URLs in the content which might be files
    for line in note_content_str.strip().split('\n'):
        # Skip the placeholder we inserted
        if line.strip() == "challenge_notes: [EXTRACTED]":
            continue
            
        if "http" in line and "." in line:
            # This could be a file URL, check for common patterns
            if "first_file:" not in line.lower() and "second_file:" not in line.lower():
                if "first_file" not in raw_fields:
                    url_start = line.find("http")
                    url_end = len(line)
                    for suffix in [" ", "\n", "\r"]:
                        pos = line.find(suffix, url_start)
                        if pos != -1 and pos < url_end:
                            url_end = pos
                    url = line[url_start:url_end].strip()
                    print(f"DEBUG: Found URL in content, treating as first_file: {url}")
                    raw_fields["first_file"] = url
                    continue
                elif "second_file" not in raw_fields:
                    url_start = line.find("http")
                    url_end = len(line)
                    for suffix in [" ", "\n", "\r"]:
                        pos = line.find(suffix, url_start)
                        if pos != -1 and pos < url_end:
                            url_end = pos
                    url = line[url_start:url_end].strip()
                    print(f"DEBUG: Found URL in content, treating as second_file: {url}")
                    raw_fields["second_file"] = url
                    continue

        # Try to parse as key-value
        parts = line.split(':', 1) # Split only on the first colon
        if len(parts) == 2:
            key = parts[0].strip().lower()
            value = parts[1].strip()
            
            # Map to our expected keys - handle common variations
            if key in ["first name", "firstname", "first_name"]:
                raw_fields["first_name"] = value
            elif key in ["last name", "lastname", "last_name"]:
                raw_fields["last_name"] = value
            elif key in ["type", "type_1"]:
                raw_fields["type_1"] = value
            elif key in ["source", "lead source", "lead_source"]:
                raw_fields["lead_source"] = value
            elif key in ["date"]:
                raw_fields["date"] = value
            elif key in ["organization", "org", "company", "organization_name", "organization name"]:
                raw_fields["organization_name"] = value
            # Skip challenge_notes key-value processing as we've already handled it specially
            elif key in ["notes", "challenge notes", "challenge_notes"]:
                # Only set if we haven't extracted it specially earlier
                if "challenge_notes" not in raw_fields:
                    raw_fields["challenge_notes"] = value
            elif key in ["size", "challenge size", "challenge_size"]:
                raw_fields["challenge_size"] = value
            elif key in ["file1", "first file", "first_file"]:
                raw_fields["first_file"] = value
            elif key in ["file2", "second file", "second_file"]:
                raw_fields["second_file"] = value
            else:
                # Unknown key, but still in key:value format
                raw_fields[key] = value
        else:
            # Not a key-value pair, collect for potential challenge_notes
            print(f"DEBUG: Collecting non key-value line for challenge_notes: '{line}'")
            non_kv_lines.append(line)

    # Define the specific keys we want to extract
    target_keys = [
        "first_name", "last_name", "type_1", "lead_source", "date", 
        "organization_name", "challenge_notes", "challenge_size", 
        "first_file", "second_file"
    ]

    for key in target_keys:
        parsed_data[key] = raw_fields.get(key) # Use .get() to default to None if key is missing
    
    # If we have non-key-value lines and no challenge_notes were set,
    # use the collected non-KV lines as challenge_notes
    if non_kv_lines and not parsed_data.get("challenge_notes"):
        parsed_data["challenge_notes"] = "\n".join(non_kv_lines)
        print(f"DEBUG: Set challenge_notes from non key-value content: {parsed_data['challenge_notes']}")

    return parsed_data

def get_note_from_zoho(order_id: str) -> Optional[Dict[str, Any]]: # Return type changed
    """
    Fetches the first created note for a given order_id (Deal ID) from Zoho CRM,
    parses its content, and returns a dictionary of key fields.
    Assumes the last note in the API's default returned list is the first one submitted.
    """
    if not order_id:
        print("DEBUG: get_note_from_zoho called with no order_id.")
        return {"error": "order_id is required."}

    print(f"DEBUG: Attempting to fetch notes for Deal ID: {order_id} to find the first submitted (assuming last in default API list).")
    
    access_token = get_access_token()
    if not access_token:
        print("DEBUG: Failed to obtain Zoho access token. Cannot proceed with API call.")
        return {"error": "Could not authenticate with Zoho."}
    
    print(f"DEBUG: Obtained Zoho access token. Proceeding to fetch notes for Deal ID: {order_id}")

    notes_url = f"{ZOHO_API_BASE_URL}/crm/v2/Deals/{order_id}/Notes"
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}"
    }
    params = {
        "per_page": 50 
    }

    try:
        print(f"DEBUG: Calling Zoho API: GET {notes_url} with params {params}")
        response = requests.get(notes_url, headers=headers, params=params)
        response.raise_for_status()  

        response_data = response.json()
        notes_list = response_data.get('data')

        if notes_list and len(notes_list) > 0:
            print(f"DEBUG: Fetched {len(notes_list)} notes from Zoho API. Looking for a note with title 'Form(WEBHOOK) FIELD VALUES'.")
            
            # Try to find a note with title "Form(WEBHOOK) FIELD VALUES"
            webhook_form_note = None
            
            # Check the last few notes (if available) to find our target note
            notes_to_check = notes_list[-5:] if len(notes_list) >= 5 else notes_list
            
            for note in reversed(notes_to_check):  # Check from most recent to oldest
                note_title = note.get('Note_Title', '')
                if note_title and 'Form(WEBHOOK) FIELD VALUES' in note_title:
                    webhook_form_note = note
                    print(f"DEBUG: Found note with title '{note_title}'")
                    break
            
            # If we didn't find a specific note, fall back to the last note
            if not webhook_form_note and len(notes_list) > 0:
                webhook_form_note = notes_list[-1]
                print(f"DEBUG: Did not find a note with 'Form(WEBHOOK) FIELD VALUES' title. Using the last note instead.")
            
            if webhook_form_note:
                print("\nDEBUG: Full data for the selected note:")
                print(json.dumps(webhook_form_note, indent=2))
                print("--------------------------------------------------\n")

                note_content_str = webhook_form_note.get('Note_Content')
                
                if note_content_str:
                    parsed_note_data = _parse_note_content_to_dict(note_content_str)
                    print(f"DEBUG: Parsed note content: {json.dumps(parsed_note_data, indent=2)}")
                    return parsed_note_data
                else:
                    note_title = webhook_form_note.get('Note_Title', 'N/A')
                    print(f"DEBUG: Selected note (Title: '{note_title}') has no content string.")
                    # Return a dict with None for all target keys if content is missing
                    return _parse_note_content_to_dict(None) # Will initialize target keys to None
            else:
                print("DEBUG: No notes found to process.")
                return {"info": "No suitable notes found for this order ID."}
        else:
            print(f"DEBUG: No notes found for Deal ID: {order_id}. Response: {response_data}")
            return {"info": "No notes found for this order ID."}
            
    except requests.exceptions.HTTPError as http_err:
        error_response_text = "N/A"
        try:
            error_response_text = response.text
        except: pass
        print(f"DEBUG: HTTP error occurred while fetching Zoho note: {http_err} - Response: {error_response_text}")
        try:
            error_json = response.json()
            if 'message' in error_json:
                return {"error": f"Zoho API error - {error_json['message']} (Code: {error_json.get('code')})"}
        except ValueError:
            pass 
        return {"error": f"HTTP error {response.status_code} while fetching note from Zoho."}
    except requests.exceptions.RequestException as req_err:
        print(f"DEBUG: Request exception occurred while fetching Zoho note: {req_err}")
        return {"error": f"Network issue while contacting Zoho: {req_err}"}
    except ValueError as json_err: 
        print(f"DEBUG: JSON decoding error occurred while parsing Zoho note response: {json_err} - Response: {response.text if 'response' in locals() else 'N/A'}")
        return {"error": "Could not parse response from Zoho."}


def get_miscellaneous_folder(order_id: str) -> Optional[Dict[str, str]]:
    """
    Fetches the "Miscellaneous Folder" field from the specified order/deal in Zoho CRM.
    Returns a dictionary with folder ID and folder URL, or None if not found.
    
    Args:
        order_id: The Zoho CRM Deal ID
        
    Returns:
        Dictionary with keys 'id' and 'url' for the folder, or None if not found
    """
    print(f"DEBUG: Getting miscellaneous folder for order {order_id}")
    
    # First, get access token
    access_token = get_access_token()
    if not access_token:
        print("DEBUG: Failed to get access token for retrieving miscellaneous folder")
        return None
    
    # Define API endpoint for getting Deal details
    deal_endpoint = f"{ZOHO_API_BASE_URL}/crm/v2/Deals/{order_id}"
    
    # Set up headers with access token
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json"
    }
    
    try:
        # Make request to get deal details
        response = requests.get(deal_endpoint, headers=headers)
        response.raise_for_status()
        
        # Parse response
        deal_data = response.json()
        
        # Check if we have data
        if 'data' in deal_data and len(deal_data['data']) > 0:
            deal = deal_data['data'][0]
            
            # Check if 'Miscellaneous_Folder' field exists
            misc_folder = deal.get('Miscellaneous_Folder')
            if misc_folder:
                print(f"DEBUG: Found Miscellaneous_Folder: {misc_folder}")
                
                # The field might be just a folder ID or a full URL
                # If it's a URL, parse out the ID
                folder_id = misc_folder
                folder_url = misc_folder
                
                # If it looks like a URL
                if '/' in misc_folder:
                    # Try to extract the folder ID from the URL
                    # Example URL: https://workdrive.zoho.com/folder/abc123
                    parts = misc_folder.split('/')
                    folder_id = parts[-1]  # Last part is typically the ID
                    folder_url = misc_folder
                else:
                    # It's just an ID, so construct a URL
                    folder_url = f"https://workdrive.zoho.com/folder/{misc_folder}"
                
                return {
                    'id': folder_id,
                    'url': folder_url
                }
            else:
                print("DEBUG: No Miscellaneous_Folder field found in the deal")
        else:
            print(f"DEBUG: No deal data found for ID {order_id}")
            
    except requests.exceptions.HTTPError as http_err:
        print(f"DEBUG: HTTP error getting deal details: {http_err}")
    except requests.exceptions.RequestException as req_err:
        print(f"DEBUG: Request exception getting deal details: {req_err}")
    except ValueError as json_err:
        print(f"DEBUG: JSON parsing error getting deal details: {json_err}")
    except Exception as e:
        print(f"DEBUG: Unexpected error getting miscellaneous folder: {str(e)}")
    
    return None


def upload_file_to_workdrive(folder_id: str, file_data, file_name: str, access_token: str = None, max_retries: int = 3) -> Optional[Dict[str, str]]:
    """
    Uploads a file to a specified Zoho WorkDrive folder with retry logic.
    
    Args:
        folder_id: The WorkDrive folder ID to upload to
        file_data: Binary data of the file to upload
        file_name: The name to give the file in WorkDrive
        access_token: Optional existing access token to reuse
        max_retries: Maximum number of retry attempts for rate limiting issues
        
    Returns:
        Dictionary with file metadata if successful, None otherwise
    """
    print(f"DEBUG: Uploading {file_name} to WorkDrive folder {folder_id}")
    print(f"DEBUG: File size: {len(file_data)} bytes")
    
    # Get an access token if one wasn't provided
    if not access_token:
        # We need CREATE to upload files and READ to get file details
        access_token = get_access_token(scope="WorkDrive.files.CREATE WorkDrive.files.READ")
        if not access_token:
            print("DEBUG: Failed to get access token for WorkDrive upload")
            return None
        
    # Create the upload endpoint URL
    upload_endpoint = f"{ZOHO_WORKDRIVE_API_URL}/upload"
    print(f"DEBUG: Using WorkDrive API endpoint: {upload_endpoint}")
    
    # Prepare headers
    headers = {
        'Authorization': f'Zoho-oauthtoken {access_token}'
    }
    print(f"DEBUG: Request headers: {headers}")
    
    # Prepare files payload
    files = {
        'content': (file_name, file_data, 'application/octet-stream')
    }
    print(f"DEBUG: Using filename: {file_name}")
    
    # Extract the folder ID string if it's a dictionary
    if isinstance(folder_id, dict) and 'id' in folder_id:
        folder_id = folder_id['id']
        print(f"DEBUG: Extracted folder ID {folder_id} from folder_id dictionary")
    
    # Create the params dictionary with just the folder ID string
    params = {
        'parent_id': folder_id
    }
    print(f"DEBUG: Request parameters: {params}")
    
    retry_count = 0
    retry_delay = 1  # Start with 1 second delay
    response = None  # Initialize outside the loop
    
    while retry_count <= max_retries:
        try:
            # Make request to upload file
            if retry_count == 0:
                print("DEBUG: Sending upload request...")
            else:
                print(f"DEBUG: Retry attempt {retry_count}/{max_retries} after waiting {retry_delay:.1f}s...")
            
            response = requests.post(upload_endpoint, headers=headers, params=params, files=files)
            
            # Log response status and headers before raising for status
            print(f"DEBUG: Response status code: {response.status_code}")
            
            # Try to get response body even if status code indicates error
            try:
                response_body = response.json()
                if retry_count == 0:  # Only log detailed response on first attempt
                    print(f"DEBUG: Response body: {response_body}")
            except Exception as json_err:
                print(f"DEBUG: Could not parse response as JSON: {str(json_err)}")
                print(f"DEBUG: Raw response text: {response.text[:100]}..." if len(response.text) > 100 else response.text)
                response_body = {}
            
            # Check for rate limiting or specific errors that warrant a retry
            if response.status_code == 429 or \
               (response.status_code == 500 and \
                response_body.get('errors', [{}])[0].get('title') == 'MORE_THAN_MAX_OCCURANCE'):
                
                if retry_count < max_retries:
                    # Exponential backoff with jitter
                    import random
                    import time
                    retry_count += 1
                    jitter = random.uniform(0.5, 1.5)  # Add 50% jitter
                    retry_delay = min(60, retry_delay * 2 * jitter)  # Double delay with each retry, max 60s
                    print(f"DEBUG: Rate limit or API error detected. Retrying in {retry_delay:.1f} seconds...")
                    time.sleep(retry_delay)
                    continue
            
            # For other status codes, raise exception as usual
            response.raise_for_status()
            
            # If we got here, request was successful, break out of retry loop
            break
            
        except requests.exceptions.HTTPError as http_err:
            if response and response.status_code == 429:  # Rate limiting
                if retry_count < max_retries:
                    retry_count += 1
                    print(f"DEBUG: Rate limited (429). Retrying {retry_count}/{max_retries}...")
                    import time
                    time.sleep(retry_delay)
                    retry_delay = min(60, retry_delay * 2)  # Double delay with each retry, max 60s
                    continue
            
            # For non-retryable errors or max retries reached
            print(f"DEBUG: HTTP error during file upload: {http_err}")
            return None
            
        except requests.exceptions.RequestException as req_err:
            print(f"DEBUG: Request exception during file upload: {req_err}")
            return None
    
    try:
        # Parse response for successful upload
        upload_data = response.json()
        
        # Extract file ID and get a shareable link
        # Based on the actual response structure from Zoho WorkDrive
        if ('data' in upload_data and isinstance(upload_data['data'], list) and 
                len(upload_data['data']) > 0 and 'attributes' in upload_data['data'][0]):
            
            attributes = upload_data['data'][0]['attributes']
            
            # The resource_id contains the file ID we need
            if 'resource_id' in attributes:
                file_id = attributes['resource_id']
                print(f"DEBUG: File uploaded successfully with ID: {file_id}")
                
                shareable_link = get_workdrive_file_link(file_id, access_token)
                print(f"DEBUG: Generated shareable link: {shareable_link}")
                
                # Return metadata
                return {
                    'id': file_id,
                    'name': file_name,
                    'url': shareable_link,
                    'timestamp': datetime.now().isoformat()
                }
            else:
                print(f"DEBUG: File resource_id not found in attributes: {attributes}")
        else:
            print(f"DEBUG: Upload appeared to succeed but unexpected response structure")
    except Exception as e:
        print(f"DEBUG: Error processing successful response: {str(e)}")
        import traceback
        print(f"DEBUG: Error traceback: {traceback.format_exc()[:200]}...")  # Truncate traceback to avoid excessive logging
    
    return None


def get_workdrive_file_link(file_id: str, access_token: str = None) -> str:
    """
    Helper function to get a direct link for a WorkDrive file.
    
    Args:
        file_id: The WorkDrive file ID
        access_token: Valid Zoho access token (optional, will fetch one with WorkDrive scope if None)
        
    Returns:
        Direct link URL for the file
    """
    print(f"DEBUG: Getting link for file {file_id}")
    
    # Note: URL Rule Configuration Error
    # To create shareable links via API, the WorkDrive account needs URL Rules configured
    # in the Zoho WorkDrive admin panel. Without this configuration, the /share endpoint
    # will return a "URL Rule is not configured" error.
    #
    # For now, we'll use the direct file URL format which should work without URL Rules
    
    # Return the direct file URL
    direct_link = f"https://workdrive.zoho.com/file/{file_id}"
    print(f"DEBUG: Using direct file link: {direct_link}")
    return direct_link
    
    # The code below is left commented for future use if URL Rules are configured
    """
    # If no access token provided, get a new one with WorkDrive scopes
    # Need READ to view file details and UPDATE to create share link
    if not access_token:
        access_token = get_access_token(scope="WorkDrive.files.READ WorkDrive.files.UPDATE")
        if not access_token:
            print("DEBUG: Failed to get access token for creating WorkDrive share link")
            return f"https://workdrive.zoho.com/file/{file_id}"  # Fallback to generic link
    
    # Define API endpoint for creating share link
    share_endpoint = f"{ZOHO_WORKDRIVE_API_URL}/files/{file_id}/share"
    
    # Set up headers with access token
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json"
    }
    
    # Settings for share link
    payload = {
        "permission_type": "view",  # Read-only access
        "shared_type": "anyone"      # Anyone with the link can access
    }
    
    try:
        # Make request to create share link
        response = requests.post(share_endpoint, headers=headers, json=payload)
        response.raise_for_status()
        
        # Parse response
        share_data = response.json()
        
        # Extract the share URL
        if 'data' in share_data and 'share_url' in share_data['data']:
            return share_data['data']['share_url']
    except Exception as e:
        print(f"DEBUG: Error getting shareable link: {str(e)}")
    
    # Return a generic link as fallback
    return f"https://workdrive.zoho.com/file/{file_id}"
    """


def create_note_with_file_links(order_id: str, links: List[Dict[str, str]]) -> bool:
    """
    Creates a new note on the specified order with links to the uploaded files.
    Each link dict should have 'name', 'url', and optional 'description'.
    
    Args:
        order_id: The Zoho CRM Deal ID
        links: List of dictionaries, each containing file link information
        
    Returns:
        True if successful, False otherwise
    """
    print(f"DEBUG: Creating note with file links for order {order_id}")
    
    # First, get access token
    access_token = get_access_token()
    if not access_token:
        print("DEBUG: Failed to get access token for creating note")
        return False
    
    # Define API endpoint for creating a note
    notes_endpoint = f"{ZOHO_API_BASE_URL}/crm/v2/Deals/{order_id}/Notes"
    
    # Set up headers with access token
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json"
    }
    
    # Format the note content
    current_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    note_content = f"Generated Design Ideas\n\n"
    
    # Add each file link to the note content
    for idx, link in enumerate(links, 1):
        note_content += f"{idx}. {link['name']}: {link['url']}"
        if 'description' in link and link['description']:
            note_content += f" - {link['description']}"
        note_content += "\n"
    
    # Prepare the note data
    note_data = {
        "data": [{
            "Note_Title": f"Design Inspiration Generator - {current_date}",
            "Note_Content": note_content,
            "Parent_Id": order_id,
            "se_module": "Deals"
        }]
    }
    
    try:
        # Make request to create the note
        response = requests.post(notes_endpoint, headers=headers, json=note_data)
        response.raise_for_status()
        
        # Parse response
        result = response.json()
        
        # Check if note creation was successful
        if 'data' in result and len(result['data']) > 0 and 'code' in result['data'][0] and result['data'][0]['code'] == 'SUCCESS':
            note_id = result['data'][0].get('details', {}).get('id')
            print(f"DEBUG: Successfully created note with ID: {note_id}")
            return True
        else:
            print(f"DEBUG: Note creation unsuccessful: {result}")
            
    except requests.exceptions.HTTPError as http_err:
        print(f"DEBUG: HTTP error creating note: {http_err}")
    except requests.exceptions.RequestException as req_err:
        print(f"DEBUG: Request exception creating note: {req_err}")
    except ValueError as json_err:
        print(f"DEBUG: JSON parsing error creating note: {json_err}")
    except Exception as e:
        print(f"DEBUG: Unexpected error creating note: {str(e)}")
    
    return False


def optimize_image_for_upload(image_data: bytes) -> Tuple[bytes, float, float]:
    """
    Optimizes an image for upload by resizing and compressing it.
    
    Args:
        image_data: Raw bytes of the image file
        
    Returns:
        Tuple of (optimized_image_bytes, original_size_kb, new_size_kb)
    """
    try:
        # Calculate original size in KB
        original_size = len(image_data) / 1024
        
        # Open the image using PIL
        img = Image.open(io.BytesIO(image_data))
        
        # Resize to exactly 400x400px (matching Streamlit thumbnail size)
        target_size = (400, 400)
        
        # Convert to RGB if it has alpha channel (for better JPEG compression)
        if img.mode == 'RGBA':
            # Create white background
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])  # 3 is the alpha channel
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Resize the image with a high-quality resampling method
        img = img.resize(target_size, Image.LANCZOS)
        
        # Save as JPEG with significant compression for much smaller file size
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", optimize=True, quality=70)
        optimized_image_data = buffer.getvalue()
        
        # Calculate new size in KB
        new_size = len(optimized_image_data) / 1024
        
        return optimized_image_data, original_size, new_size
    except Exception as e:
        print(f"DEBUG: Error optimizing image: {str(e)}. Returning original image.")
        # Return original image if optimization fails
        return image_data, len(image_data) / 1024, len(image_data) / 1024


def batch_upload_designs_to_workdrive(order_id: str, designs: List[Dict], progress_callback=None, status_callback=None):
    """
    Processes a batch of designs and uploads them to Zoho WorkDrive with optimization.
    
    Args:
        order_id: The Zoho CRM Deal ID
        designs: List of design dictionaries with 'style', 'url' or 'b64_json' keys
        progress_callback: Optional function to call with progress updates (0.0-1.0)
        status_callback: Optional function to call with status message updates
    
    Returns:
        A tuple of (success_flag, list_of_successful_uploads, error_message)
    """
    successful_uploads = []
    
    # Update status if callback provided
    if status_callback:
        status_callback("Uploading all designs to Zoho WorkDrive...")
    
    # Step 1: Get the Miscellaneous Folder ID from Zoho CRM
    folder_id = get_miscellaneous_folder(order_id)
    if not folder_id:
        return False, [], "Failed to get Miscellaneous Folder ID from Zoho CRM."
    
    # Get a single access token to use for all uploads
    if status_callback:
        status_callback("Getting Zoho access token for batch uploads...")
        
    access_token = get_access_token(scope="WorkDrive.files.CREATE WorkDrive.files.READ")
    if not access_token:
        return False, [], "Failed to get Zoho access token for uploads."
    
    # Prepare for batch uploads
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    total_designs = len(designs)
    
    for idx, selected_design in enumerate(designs):
        design_style = selected_design.get('style', f'variation_{idx}')
        filename = f"design_{design_style}_{timestamp}.png"
        
        # Update progress if callback provided
        if progress_callback:
            progress = (idx) / total_designs
            progress_callback(progress)
            
        if status_callback:
            status_callback(f"Processing design {idx+1}/{total_designs}: {design_style}")
        
        # Get image data - either from URL or base64
        image_data = None
        if selected_design.get("url"):
            try:
                response = requests.get(selected_design.get("url"), timeout=10)
                response.raise_for_status()
                image_data = response.content
            except Exception as e:
                print(f"DEBUG: Failed to download image for {design_style} from URL: {e}")
                continue
        elif selected_design.get("b64_json"):
            try:
                image_data = base64.b64decode(selected_design.get("b64_json"))
            except Exception as e:
                print(f"DEBUG: Failed to decode base64 image data for {design_style}: {e}")
                continue
        
        if not image_data:
            print(f"DEBUG: Failed to get image data for {design_style}.")
            continue
        
        # Optimize the image
        if status_callback:
            status_callback(f"Optimizing image {idx+1}/{total_designs}: {design_style} for upload")
            
        optimized_data, original_size, new_size = optimize_image_for_upload(image_data)
        
        # Log the size reduction
        reduction = (1 - (new_size / original_size)) * 100 if original_size > 0 else 0
        print(f"DEBUG: Image resized from {original_size:.1f}KB to {new_size:.1f}KB ({reduction:.1f}% reduction)")
        
        # Upload the file to WorkDrive using the shared token and with retry logic
        if status_callback:
            status_callback(f"Uploading design {idx+1}/{total_designs}: {design_style} to Zoho WorkDrive")
            
        upload_result = upload_file_to_workdrive(
            folder_id=folder_id, 
            file_data=optimized_data, 
            file_name=filename,
            access_token=access_token,  # Reuse the token for all uploads
            max_retries=3  # Allow up to 3 retries with exponential backoff
        )
        
        if not upload_result:
            print(f"DEBUG: Failed to upload {design_style} to Zoho WorkDrive.")
            continue
        
        # Add to successful uploads
        successful_uploads.append({
            'name': filename,
            'url': upload_result['url'],
            'id': upload_result['id'],
            'style': design_style
        })
    
    # Complete the progress
    if progress_callback:
        progress_callback(1.0)
    
    if status_callback:
        status_callback("")
    
    # Create a note with links if we have successful uploads
    if successful_uploads:
        if status_callback:
            status_callback("Creating a note with design links in Zoho CRM...")
            
        note_result = create_note_with_file_links(order_id, successful_uploads)
        if not note_result:
            return True, successful_uploads, "Designs uploaded successfully, but failed to create a note in Zoho CRM."
            
        return True, successful_uploads, f"Successfully uploaded {len(successful_uploads)} designs to Zoho WorkDrive."
    else:
        return False, [], "No designs were successfully uploaded to Zoho WorkDrive."


if __name__ == '__main__':
    import os
    from PIL import Image
    import io
    
    # Example usage for direct testing (optional)
    print("--- Testing get_access_token() directly ---")
    token = get_access_token("WorkDrive.files.CREATE WorkDrive.files.READ")
    if token:
        print(f"Received Access Token (first 10 chars): {token[:10]}...")
    else:
        print("Failed to retrieve access token.")
    print("-------------------------------------------")

    # Set test deal ID - use a real ID from your Zoho CRM for testing
    test_deal_id = "3252550000497103850" 
    
    # Test the note retrieval function
    print(f"\n--- Testing get_note_from_zoho with Deal ID: {test_deal_id} ---")
    parsed_note = get_note_from_zoho(test_deal_id)
    print(f"\nReceived parsed note data from get_note_from_zoho for Deal ID {test_deal_id}:")
    print("-------------------------------------------")
    if parsed_note:
        print(json.dumps(parsed_note, indent=2))
    else:
        print("No data returned or error occurred.")
    print("-------------------------------------------")
    
    # Test getting miscellaneous folder
    print(f"\n--- Testing get_miscellaneous_folder with Deal ID: {test_deal_id} ---")
    folder_info = get_miscellaneous_folder(test_deal_id)
    print("Folder information:")
    print("-------------------------------------------")
    if folder_info:
        print(json.dumps(folder_info, indent=2))
        
        # If folder info was found, test file upload
        test_upload = input("\nDo you want to test file upload? (y/n): ")
        if test_upload.lower() == 'y':
            print("\n--- Testing upload_file_to_workdrive ---")
            try:
                # Try uploading the specific PNG file mentioned by the user
                specific_file_path = os.path.join(os.path.dirname(__file__), 
                                                 "37673091a304e9f1328cdec1fad5220368259fe34a86db02ed64ec5f.png")
                
                if os.path.exists(specific_file_path):
                    print(f"Found specific PNG file at {specific_file_path}")
                    
                    # First test: upload original file
                    with open(specific_file_path, 'rb') as f:
                        img_data = f.read()
                    
                    file_size_kb = len(img_data) / 1024
                    print(f"Original file size: {file_size_kb:.1f}KB")
                    
                    # Second test: resize and compress file before upload
                    img = Image.open(specific_file_path)
                    print(f"Original dimensions: {img.size}")
                    
                    # Resize to 400x400px and convert to JPEG
                    target_size = (400, 400)
                    
                    # Convert to RGB if needed (for JPEG format)
                    if img.mode == 'RGBA':
                        background = Image.new('RGB', img.size, (255, 255, 255))
                        background.paste(img, mask=img.split()[3])
                        img = background
                    elif img.mode != 'RGB':
                        img = img.convert('RGB')
                    
                    # Resize the image
                    img = img.resize(target_size, Image.LANCZOS)
                    
                    # Save as JPEG with compression
                    img_byte_arr = io.BytesIO()
                    img.save(img_byte_arr, format='JPEG', optimize=True, quality=70)
                    img_data = img_byte_arr.getvalue()
                    
                    new_size_kb = len(img_data) / 1024
                    print(f"After resizing/compression: {new_size_kb:.1f}KB (reduced by {(1 - new_size_kb/file_size_kb) * 100:.1f}%)")
                else:
                    print(f"Specific PNG file not found at {specific_file_path}, creating a test image instead")
                    # Create a simple test image as fallback
                    img = Image.new('RGB', (100, 100), color=(73, 109, 137))
                    img_byte_arr = io.BytesIO()
                    img.save(img_byte_arr, format='PNG')
                    img_data = img_byte_arr.getvalue()
                
                # Upload test image
                upload_result = upload_file_to_workdrive(
                    folder_info['id'], 
                    img_data, 
                    f"test_upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                )
                
                print("Upload result:")
                print("-------------------------------------------")
                if upload_result:
                    print(json.dumps(upload_result, indent=2))
                    
                    # Test creating note with file link
                    test_note = input("\nDo you want to test creating a note with the file link? (y/n): ")
                    if test_note.lower() == 'y':
                        print("\n--- Testing create_note_with_file_links ---")
                        note_result = create_note_with_file_links(
                            test_deal_id,
                            [{
                                'name': 'Test File Upload',
                                'url': upload_result['url'],
                                'description': 'This is a test file uploaded via the WorkDrive API'
                            }]
                        )
                        
                        print("Note creation result:", "Success" if note_result else "Failed")
                else:
                    print("File upload failed.")
            except Exception as e:
                print(f"Error during file upload test: {str(e)}")
    else:
        print("No folder information found or error occurred.")
    print("-------------------------------------------")