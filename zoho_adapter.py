# zoho_adapter.py
import requests # Will be used for actual API calls
import json # For pretty printing and the new parser
from typing import Optional, Dict, Any # For type hinting

# Import credentials from shared config module (works with both Streamlit secrets and .env)
from config import (
    ZOHO_CLIENT_ID,
    ZOHO_CLIENT_SECRET,
    ZOHO_REFRESH_TOKEN,
    ZOHO_API_BASE_URL,
    ZOHO_TOKEN_URL
)

def get_access_token():
    """
    Refreshes and returns the Zoho API access token using the refresh token.
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

    try:
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

if __name__ == '__main__':
    # Example usage for direct testing (optional)
    print("--- Testing get_access_token() directly ---")
    token = get_access_token()
    if token:
        print(f"Received Access Token (first 10 chars): {token[:10]}...")
    else:
        print("Failed to retrieve access token.")
    print("-------------------------------------------")

    test_deal_id = "3252550000497103850" 
    print(f"\n--- Testing get_note_from_zoho with Deal ID: {test_deal_id} ---")
    parsed_note = get_note_from_zoho(test_deal_id)
    print(f"\nReceived parsed note data from get_note_from_zoho for Deal ID {test_deal_id}:")
    print("-------------------------------------------")
    if parsed_note:
        print(json.dumps(parsed_note, indent=2))
    else:
        print("No data returned or error occurred.")
    print("-------------------------------------------")