import urllib.parse

# Use your client ID from Zoho Developer Console
client_id = "1000.4E3DV0QS7N0NQQUW0SAMNN547A662X"  # Replace with your actual client ID

# Define the redirect URI (must match what you registered in Zoho Developer Console)
redirect_uri = "http://localhost:8000/callback"

# Define the scopes needed for both CRM and WorkDrive
# CRM scopes
crm_scopes = [
    "ZohoCRM.modules.ALL",
    "ZohoCRM.settings.ALL",
    "ZohoCRM.users.ALL", 
    "ZohoCRM.org.ALL"
]

# WorkDrive scopes
workdrive_scopes = [
    "WorkDrive.files.CREATE", 
    "WorkDrive.files.READ",
    "WorkDrive.files.UPDATE",
    "WorkDrive.files.DELETE"
]

# Combine all scopes
all_scopes = " ".join(crm_scopes + workdrive_scopes)

# Generate the authorization URL
params = {
    "scope": all_scopes,
    "client_id": client_id,
    "response_type": "code",
    "access_type": "offline",
    "redirect_uri": redirect_uri
}

base_url = "https://accounts.zoho.com/oauth/v2/auth"
auth_url = f"{base_url}?{urllib.parse.urlencode(params)}"

print("\n=== Zoho OAuth Authorization URL ===")
print("Copy this URL into your browser to authorize the application:")
print(f"\n{auth_url}\n")
print("After authorization, you will be redirected to your callback URL with a 'code' parameter.")
print("Extract this code from the URL for the next step.")
