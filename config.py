"""
Shared configuration module for cloud and local environments.
Attempts to load from Streamlit secrets first, then falls back to .env file for local development.
"""
import os
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# Try to import Streamlit
try:
    import streamlit as st
    STREAMLIT_AVAILABLE = True
except ImportError:
    STREAMLIT_AVAILABLE = False

# Load environment variables from .env (used as fallback in local environment)
load_dotenv()

def get_credential(key: str, default: Any = None) -> Any:
    """
    Gets a credential value from Streamlit secrets (if in cloud) or environment variables (if local).
    
    Args:
        key: The key to look up
        default: Default value if key is not found
    
    Returns:
        The credential value or default if not found
    """
    # First try Streamlit secrets (for cloud deployment)
    if STREAMLIT_AVAILABLE:
        try:
            # Check if secret exists in Streamlit secrets
            if key in st.secrets:
                return st.secrets[key]
            
            # Also check if secret exists in nested dictionaries
            # For example, st.secrets["zoho"]["client_id"]
            for section in st.secrets:
                if isinstance(st.secrets[section], dict) and key in st.secrets[section]:
                    return st.secrets[section][key]
        except Exception:
            # Fall back to environment variables if any errors occur
            pass
    
    # Fall back to environment variables (for local development)
    return os.getenv(key, default)

# Main credential constants
OPENAI_API_KEY = get_credential("OPENAI_API_KEY")
ZOHO_CLIENT_ID = get_credential("ZOHO_CLIENT_ID")
ZOHO_CLIENT_SECRET = get_credential("ZOHO_CLIENT_SECRET")
ZOHO_REFRESH_TOKEN = get_credential("ZOHO_REFRESH_TOKEN")
ZOHO_API_BASE_URL = get_credential("ZOHO_API_BASE_URL", "https://www.zohoapis.com")
ZOHO_TOKEN_URL = get_credential("ZOHO_TOKEN_URL", "https://accounts.zoho.com/oauth/v2/token")

if __name__ == "__main__":
    # Test the credential loading
    print(f"OpenAI API Key available: {bool(OPENAI_API_KEY)}")
    print(f"Zoho credentials available: {all([ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN])}")
