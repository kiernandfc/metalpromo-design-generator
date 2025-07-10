"""
Logging configuration for the application.
"""
import logging

def configure_logging():
    """Configure logging levels for different modules"""
    
    # Set root logger to INFO
    logging.basicConfig(level=logging.INFO)
    
    # Reduce verbose logging for specific modules
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('PIL').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    
    # Keep our application logs at DEBUG level
    logging.getLogger('openai_adapter').setLevel(logging.DEBUG)
    logging.getLogger('zoho_adapter').setLevel(logging.DEBUG)
    logging.getLogger('streamlit_app').setLevel(logging.DEBUG)
