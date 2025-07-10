import requests
import json
import sys

def exchange_code_for_token(authorization_code, client_id, client_secret, redirect_uri):
    """Exchange the authorization code for refresh and access tokens"""
    token_url = "https://accounts.zoho.com/oauth/v2/token"
    
    payload = {
        "code": authorization_code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"
    }
    
    print(f"Sending token request with payload: {json.dumps(payload, indent=2)}")
    
    try:
        response = requests.post(token_url, data=payload)
        response_json = response.json()
        
        print(f"Response status code: {response.status_code}")
        
        if response.status_code == 200 and "refresh_token" in response_json:
            print("\n=== Success! Tokens Received ===")
            print(f"Access Token: {response_json.get('access_token')[:10]}...")
            print(f"Refresh Token: {response_json.get('refresh_token')}")
            print("\nIMPORTANT: Save the refresh_token in your .env file as ZOHO_REFRESH_TOKEN")
            print("This token includes both CRM and WorkDrive scopes")
            return response_json
        else:
            print("\n=== Error Retrieving Tokens ===")
            print(f"Response: {json.dumps(response_json, indent=2)}")
            return None
    
    except Exception as e:
        print(f"Exception occurred: {str(e)}")
        return None

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python exchange_code_for_token.py <authorization_code> <client_id> <client_secret>")
        print("\nExample:")
        print("python exchange_code_for_token.py 1000.abcd1234... 1000.CLIENTID123... clientsecretxyz...")
        sys.exit(1)
    
    # Get parameters from command line
    authorization_code = sys.argv[1]
    client_id = sys.argv[2]
    client_secret = sys.argv[3]
    redirect_uri = sys.argv[4] if len(sys.argv) > 4 else "http://localhost:8000/callback"
    
    print(f"Authorization Code: {authorization_code[:10]}...")
    print(f"Client ID: {client_id}")
    print(f"Client Secret: {client_secret[:5]}...")
    print(f"Redirect URI: {redirect_uri}")
    
    # Exchange the authorization code for tokens
    token_response = exchange_code_for_token(authorization_code, client_id, client_secret, redirect_uri)
