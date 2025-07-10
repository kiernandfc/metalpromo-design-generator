import streamlit as st
import base64 
import io     
import requests
import fitz  # PyMuPDF
from PIL import Image # Pillow for image type detection if needed, though mimetypes or extension is fine
import base64
import json
import os
import sys
import time
import logging
from datetime import datetime
from PIL import Image  # For image processing

# Import the logging configuration
from logging_config import configure_logging

# Configure logging before importing other modules
configure_logging()

# Import from shared config module
from config import ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN, OPENAI_API_KEY
from zoho_adapter import (
    get_note_from_zoho, 
    get_access_token, 
    get_miscellaneous_folder,
    upload_file_to_workdrive,
    create_note_with_file_links,
    batch_upload_designs_to_workdrive
)
from openai_adapter import generate_image_with_multiple_inputs

IMAGE_ROLE_OPTIONS = ["Ignore", "Front of coin mockup", "Back of coin mockup", "Logo to include", "Other reference image"]

# Helper function to get file content, convert if PDF, and prepare for OpenAI
def get_file_data_for_display_and_openai(file_url):
    """Downloads a file, converts PDF to PNG, and returns image bytes for display and base64 data URI for OpenAI."""
    if not file_url:
        return None, None, None
    try:
        response = requests.get(file_url, timeout=10)
        response.raise_for_status() # Raise an exception for bad status codes
        content_type = response.headers.get('content-type', '').lower()
        file_extension = file_url.split('.')[-1].lower()

        image_bytes_for_display = None
        base64_data_uri = None
        mime_type = None
        max_height = 500  # Maximum height for preview images

        if 'pdf' in content_type or file_extension == 'pdf':
            # Convert PDF to image (first page)
            doc = fitz.open(stream=response.content, filetype="pdf")
            page = doc.load_page(0)  # First page
            pix = page.get_pixmap(dpi=150) # Render at 150 DPI
            image_bytes_for_display = pix.tobytes("png")
            mime_type = "image/png"
            
            # Resize if needed to meet max height
            image = Image.open(io.BytesIO(image_bytes_for_display))
            if image.height > max_height:
                # Calculate new width to maintain aspect ratio
                new_width = int((max_height / image.height) * image.width)
                image = image.resize((new_width, max_height), Image.LANCZOS)
                # Convert back to bytes
                img_byte_arr = io.BytesIO()
                image.save(img_byte_arr, format=image.format or 'PNG')
                image_bytes_for_display = img_byte_arr.getvalue()
            
            # Generate base64 from the possibly resized image
            base64_str = base64.b64encode(image_bytes_for_display).decode('utf-8')
            base64_data_uri = f"data:{mime_type};base64,{base64_str}"
            doc.close()
        elif file_extension in ['png', 'jpg', 'jpeg', 'gif', 'webp'] or 'image' in content_type:
            image_bytes_for_display = response.content
            if 'png' in content_type or file_extension == 'png': mime_type = "image/png"
            elif 'jpeg' in content_type or file_extension in ['jpg', 'jpeg']: mime_type = "image/jpeg"
            elif 'gif' in content_type or file_extension == 'gif': mime_type = "image/gif"
            elif 'webp' in content_type or file_extension == 'webp': mime_type = "image/webp"
            else: # Fallback, try to guess or default
                mime_type = f"image/{file_extension}" # Simple guess
            
            # Resize if needed to meet max height
            try:
                image = Image.open(io.BytesIO(image_bytes_for_display))
                if image.height > max_height:
                    # Calculate new width to maintain aspect ratio
                    new_width = int((max_height / image.height) * image.width)
                    image = image.resize((new_width, max_height), Image.LANCZOS)
                    # Convert back to bytes
                    img_byte_arr = io.BytesIO()
                    image_format = image.format or 'PNG'
                    image.save(img_byte_arr, format=image_format)
                    image_bytes_for_display = img_byte_arr.getvalue()
            except Exception as e:
                st.warning(f"Error resizing image: {e}. Using original size instead.")
                # Continue with original image if resize fails
            
            # Generate base64 from the possibly resized image
            base64_str = base64.b64encode(image_bytes_for_display).decode('utf-8')
            base64_data_uri = f"data:{mime_type};base64,{base64_str}"
        else:
            st.warning(f"Unsupported file type for preview/processing: {file_url} (Content-Type: {content_type})")
            return None, None, None

        return image_bytes_for_display, base64_data_uri, mime_type

    except requests.exceptions.RequestException as e:
        st.error(f"Error downloading {file_url}: {e}")
        return None, None, None
    except fitz.fitz.FZ_ERROR_GENERIC as e:
        st.error(f"Error processing PDF {file_url} with PyMuPDF: {e}. Ensure it's a valid PDF.")
        return None, None, None
    except Exception as e:
        st.error(f"An unexpected error occurred while processing {file_url}: {e}")
        return None, None, None

def main():
    st.set_page_config(
        page_title="MetalPromo Coin Design Inspiration Generator",
        page_icon="🪙",
        layout="wide"
    )
    # Title moved down to avoid duplication with the one in main logic

    # --- Main App Logic ---
    if not all([ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN]):
        st.error("Zoho CRM credentials are not configured. Please set them in your .env file.")
        st.stop()

    st.title("MetalPromo Coin Design Inspiration Generator")
    
    query_params = st.query_params
    order_id = query_params.get("order_id")
    
    # Initialize session state for upload trigger if order ID exists
    if order_id and f"designs_{order_id}" in st.session_state:
        if f"upload_trigger_{order_id}" not in st.session_state:
            st.session_state[f"upload_trigger_{order_id}"] = False
        
        designs_key = f"designs_{order_id}"
        
        # Process upload if the trigger is set - moved outside generation block to execute on page load
        if st.session_state.get(f"upload_trigger_{order_id}", False):
            st.session_state[f"upload_trigger_{order_id}"] = False  # Reset the trigger
            
            # Process the upload in the info box
            with st.info("📤 **Uploading Designs to Zoho WorkDrive**"):
                # Check if we have designs to upload
                if st.session_state[designs_key] and len(st.session_state[designs_key]['successful_designs']) > 0:
                    # Create Streamlit UI elements for progress and status
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    # Define callback functions for progress and status updates
                    def update_progress(progress_value):
                        progress_bar.progress(progress_value)
                    
                    def update_status(status_message):
                        if status_message:
                            status_text.text(status_message)
                        else:
                            status_text.empty()
                    
                    # Call the batch upload function from zoho_adapter
                    success, uploaded_designs, message = batch_upload_designs_to_workdrive(
                        order_id=order_id,
                        designs=st.session_state[designs_key]['successful_designs'],
                        progress_callback=update_progress,
                        status_callback=update_status
                    )
                    
                    # Handle the results
                    if success:
                        st.success(message)
                        
                        # Set a flag in session state to indicate successful upload
                        st.session_state[f"upload_success_{order_id}"] = True
                        st.session_state[f"upload_count_{order_id}"] = len(uploaded_designs)
                    else:
                        st.error(message)


    # Allow manual order_id entry if not present in URL
    if not order_id:
        st.info("No order ID found in URL parameters.")
        
        # Initialize session state for manual order_id if not exists
        if "manual_order_id" not in st.session_state:
            st.session_state.manual_order_id = ""
        
        # Create a form for order_id entry
        with st.form("order_id_form"):
            entered_order_id = st.text_input("Enter Order ID:", value=st.session_state.manual_order_id)
            submitted = st.form_submit_button("Load Order Data")
            
            if submitted and entered_order_id.strip():
                order_id = entered_order_id.strip()
                st.session_state.manual_order_id = order_id
                # Update query params to include the order_id for URL sharing
                st.query_params.update(order_id=order_id)
                st.success(f"Order ID {order_id} submitted. Processing...")
                st.rerun()
            elif submitted and not entered_order_id.strip():
                st.error("Please enter a valid Order ID")
                st.stop()
        
        # Sample Order IDs for testing
        st.markdown("### Sample Order IDs for Testing")
        st.markdown("""
        You can use these sample IDs for testing:
        - `3252550000507549272` - YMCA department logo
        - `3252550000485072160` - Vermont Fraternal Order of Police
        - `3252550000482448702` - Eagle coin design
        """)
        
        if not order_id:  # Still no order_id after form handling
            st.stop()

    # Initialize session state for roles if not already present for this order_id
    if f"roles_{order_id}" not in st.session_state:
        st.session_state[f"roles_{order_id}"] = {
            'file1_role': 'Ignore',
            'file2_role': 'Ignore',
            'file1_b64': None, # To store base64 data
            'file2_b64': None  # To store base64 data
        }
    
    # Initialize session state for designs if not present for this order_id
    if f"designs_{order_id}" not in st.session_state:
        st.session_state[f"designs_{order_id}"] = None
        
    # Initialize session state for upload trigger if not present
    if f"upload_trigger_{order_id}" not in st.session_state:
        st.session_state[f"upload_trigger_{order_id}"] = False
    
    roles_key = f"roles_{order_id}"
    designs_key = f"designs_{order_id}"

    # Fetch note data (this will now be a dictionary)
    note_data_dict = get_note_from_zoho(order_id)

    if not note_data_dict or 'error' in note_data_dict or 'info' in note_data_dict:
        st.error(f"Could not retrieve valid note data from Zoho for order ID {order_id}.")
        if note_data_dict and ('error' in note_data_dict or 'info' in note_data_dict):
            st.error(f"Details: {note_data_dict.get('error') or note_data_dict.get('info')}")
        st.stop()
    
    # --- Display Customer & Order Details ---
    st.subheader("📝 Customer & Order Details")
    first_name = note_data_dict.get('first_name', '')
    last_name = note_data_dict.get('last_name', '')
    full_name = f"{first_name} {last_name}".strip()

    details_md = f"""
    | Field               | Value                                                |
    |---------------------|------------------------------------------------------|
    | **Full Name**       | {full_name if full_name else 'N/A'}                  |
    | **Organization**    | {note_data_dict.get('organization_name', 'N/A')}          |
    | **Date**            | {note_data_dict.get('date', 'N/A')}                       |
    | **Type**            | {note_data_dict.get('type_1', 'N/A')}                     |
    | **Lead Source**     | {note_data_dict.get('lead_source', 'N/A')}                |
    | **Challenge Size**  | {note_data_dict.get('challenge_size', 'N/A')}            |
    """
    st.markdown(details_md)
    st.divider()

    # Display and edit note content (challenge_notes)
    st.subheader("Challenge Notes")
    challenge_notes_initial = note_data_dict.get('challenge_notes', '')
    if f"challenge_notes_edited_{order_id}" not in st.session_state:
        st.session_state[f"challenge_notes_edited_{order_id}"] = challenge_notes_initial
    
    edited_challenge_notes = st.text_area(
        "Edit Challenge Notes:", 
        value=st.session_state[f"challenge_notes_edited_{order_id}"], 
        height=150,
        key=f"challenge_notes_text_area_{order_id}"
    )
    st.session_state[f"challenge_notes_edited_{order_id}"] = edited_challenge_notes

    # --- File Display and Role Assignment ---
    st.subheader("Uploaded Files")
    first_file_url = note_data_dict.get('first_file')
    second_file_url = note_data_dict.get('second_file')

    role_options = IMAGE_ROLE_OPTIONS # Using the global constant

    col1, col2 = st.columns(2)

    # Process and display first file
    if first_file_url:
        with col1:
            st.write("File 1:")
            # First set the role with the dropdown
            st.session_state[roles_key]['file1_role'] = st.selectbox(
                "Assign role to File 1:", 
                role_options, 
                index=role_options.index(st.session_state[roles_key].get('file1_role', 'Ignore')),
                key=f"file1_role_select_{order_id}"
            )
            
            # Then display the image preview
            # Get image bytes for display and base64 for OpenAI, only if not already processed and stored
            # or if URL changed (though unlikely for a stable order_id's note)
            # For simplicity, let's re-process if needed or if b64 is not in session state for this file yet.
            # A more robust approach might cache based on URL if performance becomes an issue.
            img_bytes_1, b64_data_1, mime_type_1 = get_file_data_for_display_and_openai(first_file_url)
            st.session_state[roles_key]['file1_b64'] = b64_data_1 # Store for backend

            if img_bytes_1:
                st.image(img_bytes_1, caption="First File Preview")
            elif first_file_url: # If conversion failed but URL exists
                st.markdown(f"[View Original File 1]({first_file_url})")
                st.warning("Could not generate preview for File 1.")
    else:
        with col1:
            st.info("No first file provided in the notes.")
            st.session_state[roles_key]['file1_b64'] = None # Ensure it's None if no file

    # Process and display second file
    if second_file_url:
        with col2:
            st.write("File 2:")
            # First set the role with the dropdown
            st.session_state[roles_key]['file2_role'] = st.selectbox(
                "Assign role to File 2:", 
                role_options,
                index=role_options.index(st.session_state[roles_key].get('file2_role', 'Ignore')),
                key=f"file2_role_select_{order_id}"
            )
            
            # Then display the image preview
            img_bytes_2, b64_data_2, mime_type_2 = get_file_data_for_display_and_openai(second_file_url)
            st.session_state[roles_key]['file2_b64'] = b64_data_2 # Store for backend

            if img_bytes_2:
                st.image(img_bytes_2, caption="Second File Preview")
            elif second_file_url: # If conversion failed but URL exists
                st.markdown(f"[View Original File 2]({second_file_url})")
                st.warning("Could not generate preview for File 2.")
    else:
        with col2:
            st.info("No second file provided in the notes.")
            st.session_state[roles_key]['file2_b64'] = None # Ensure it's None if no file

    # --- AI Design Generation ---
    st.subheader("AI Design Generation")
    
    # Prepare image data with roles for the backend
    image_data_for_backend = []
    file1_role = st.session_state[roles_key]['file1_role']
    file1_b64_data = st.session_state[roles_key]['file1_b64']
    if file1_b64_data and file1_role != 'Ignore':
        image_data_for_backend.append({
            "image_data_uri": file1_b64_data, # This will be the base64 data URI
            "role": file1_role,
            "original_url": first_file_url # Keep original URL for reference if needed
        })

    file2_role = st.session_state[roles_key]['file2_role']
    file2_b64_data = st.session_state[roles_key]['file2_b64']
    if file2_b64_data and file2_role != 'Ignore':
        image_data_for_backend.append({
            "image_data_uri": file2_b64_data, # This will be the base64 data URI
            "role": file2_role,
            "original_url": second_file_url # Keep original URL for reference if needed
        })

    # Simplified preview
    st.markdown("**AI Design Generation Input (preview):**")
    st.markdown(f"- **Challenge Notes:** {st.session_state[f'challenge_notes_edited_{order_id}'][:100]}...") 
    if image_data_for_backend:
        st.markdown("- **Files to include:**")
        for item in image_data_for_backend:
            st.markdown(f"  - {item['role']} (Source: ...{item['original_url'][-30:]}, Type: {item['image_data_uri'].split(':')[1].split(';')[0]})")
    else:
        st.markdown("- No files selected to include.")
    
    # Check if we have designs stored in session state
    has_designs = st.session_state[designs_key] is not None and \
                 'successful_designs' in st.session_state[designs_key] and \
                 len(st.session_state[designs_key]['successful_designs']) > 0
    
    # Display designs from session state if they exist
    if has_designs:
        st.subheader("Stored Design Variations")
        st.write("Previously generated designs are displayed below. Click 'Regenerate' to create new designs.")
        
        # Create tabs for the different design styles
        successful_designs = st.session_state[designs_key]['successful_designs']
        tab_labels = [result.get("style", "Unknown") for result in successful_designs]
        tabs = st.tabs(tab_labels)
        
        for i, (tab, result) in enumerate(zip(tabs, successful_designs)):
            with tab:
                st.write(f"**Style: {result.get('style', 'Unknown')}**")
                
                # Display the image
                b64_json = result.get("b64_json")
                
                if b64_json:  # If we have base64 JSON data
                    try:
                        image_bytes = base64.b64decode(b64_json)
                        # Create a PIL Image to resize to 400x400 pixels
                        img = Image.open(io.BytesIO(image_bytes))
                        # Resize to maintain aspect ratio with max dimensions 400x400
                        img.thumbnail((400, 400), Image.LANCZOS)
                        img_byte_arr = io.BytesIO()
                        img.save(img_byte_arr, format=img.format or 'PNG')
                        img_byte_arr.seek(0)
                        st.image(img_byte_arr, caption=f"Design Variation {i+1}: {result.get('style', 'Unknown')}", width=400)
                    except Exception as e:
                        st.error(f"Failed to decode or display b64_json image: {e}")
                        st.text_area("Raw b64_json response (first 100 chars):", value=str(b64_json)[:100], height=70)
        
        # Upload to Zoho button
        st.subheader("Save Designs to Zoho CRM")
        
        # Check if we have already successfully uploaded in this session
        upload_success = st.session_state.get(f"upload_success_{order_id}", False)
        upload_count = st.session_state.get(f"upload_count_{order_id}", 0)
        
        # Show different messages based on upload status
        if upload_success:
            st.write(f"✅ {upload_count} designs were already uploaded in this session. You can upload again if needed.")
        else:
            st.write(f"Click the button below to upload all {len(successful_designs)} generated designs to Zoho WorkDrive.")
        
        # Create columns for button and status
        col1, col2 = st.columns([1, 2])
        
        with col1:
            if st.button("Upload All Designs to Zoho WorkDrive", key=f"upload_designs_{order_id}"):
                # Set the upload trigger for the next run
                st.session_state[f"upload_trigger_{order_id}"] = True
                st.rerun()
    
    # Button text depends on whether we already have designs
    button_text = "Regenerate Design Variations with OpenAI" if has_designs else "Generate Design Variations with OpenAI"
    
    if st.button(button_text, key=f"generate_button_{order_id}"):
        if not OPENAI_API_KEY:
            st.error("OpenAI API key is not configured. Please set it in your .env file or secrets.")
        elif not edited_challenge_notes.strip() and not image_data_for_backend:
             st.warning("Please provide some design notes or at least one reference image (PDF or image file) with a role other than 'Ignore'.")
        else:
            # Create a placeholder for real-time status updates
            status_placeholder = st.empty()
            error_placeholder = st.empty()
            
            with st.spinner("Generating design variations... (may take ~60 seconds)"):
                # Get the prompt modifiers to show in the UI
                from prompt_modifiers import load_prompt_modifiers
                prompt_styles = load_prompt_modifiers()
                style_names = [style[0] for style in prompt_styles]
                
                # Pass the edited notes and the list of image data dicts to generate multiple variations
                status_placeholder.info("Starting design generation with OpenAI. This may take up to 60 seconds...")
                try:
                    image_response_list = generate_image_with_multiple_inputs(
                        prompt_text=edited_challenge_notes, 
                        input_images_data=image_data_for_backend,
                        parallel=True  # Enable parallel generation of multiple variations
                    )
                    # Clear the status message when done
                    status_placeholder.empty()
                except Exception as e:
                    status_placeholder.empty()  # Clear the status message
                    error_placeholder.error(f"❌ Error during design generation: {str(e)}")
                    import traceback
                    error_details = traceback.format_exc()
                    with st.expander("Technical Error Details"):
                        st.code(error_details, language="python")
                    image_response_list = []
                
                if image_response_list and len(image_response_list) > 0:
                    # Get successful designs first
                    successful_designs = [result for result in image_response_list if result.get("success", False)]
                    
                    if successful_designs:
                        # Store the designs in session state
                        st.session_state[designs_key] = {
                            'successful_designs': successful_designs,
                            'generated_at': datetime.now().isoformat()
                        }
                        
                        # Display a brief success message
                        st.success(f"Successfully generated {len(successful_designs)} design variations!")
                        
                        # Display any errors that occurred
                        failed_designs = [result for result in image_response_list if not result.get("success", False)]
                        if failed_designs:
                            st.warning(f"Some design variations failed to generate ({len(failed_designs)} out of {len(image_response_list)}).")
                            with st.expander("View Errors"):
                                for i, result in enumerate(failed_designs):
                                    st.write(f"**Style {result.get('style', 'Unknown')} Error:** {result.get('error', 'Unknown error')}")
                        
                        # Trigger a rerun of the app to display designs through the session state section
                        st.rerun()
                        
                else:
                    # Get any error information from failed designs
                    failed_designs = [result for result in image_response_list if not result.get("success", False)]
                    
                    # Display a prominent error message
                    if failed_designs:
                        # Get the most common or first error message
                        first_error = failed_designs[0].get('error', 'Unknown error')
                        error_placeholder.error(f"⚠️ OpenAI API Error: {first_error}")
                        
                        if len(failed_designs) > 1:
                            st.warning(f"All {len(failed_designs)} design variations failed to generate.")
                        else:
                            st.warning("Design generation failed.")
                    else:
                        error_placeholder.error("⚠️ Failed to generate any design variations.")
                    
                    # Display detailed error information in an expanded section
                    with st.expander("View Error Details", expanded=True): # Auto-expand error details
                        st.write("### Error Information")
                        st.write("No successful design variations were generated. Here's what we know:")
                        
                        # Show all failed designs with their specific errors
                        if failed_designs:
                            st.write(f"Found {len(failed_designs)} failed design attempts:")
                            for i, result in enumerate(failed_designs):
                                style = result.get('style', 'Unknown')
                                error_msg = result.get('error', 'Unknown error')
                                st.error(f"**Style: {style}**\n{error_msg}")
                                
                                # If it's a 500 error, add more specific guidance
                                if "500" in error_msg:
                                    st.info("ℹ️ This is a server error from OpenAI. It's not caused by your inputs but rather an issue on OpenAI's side. You can try again in a few minutes.")
                        else:
                            st.write("No specific error information was returned from the OpenAI adapter.")
                            
                        # Display input information for debugging
                        st.write("### Input Information")
                        st.write(f"Prompt text length: {len(edited_challenge_notes)} characters")
                        st.write(f"Number of input images: {len(image_data_for_backend)}")
                        for i, img_data in enumerate(image_data_for_backend):
                            st.write(f"Image {i+1} - Role: {img_data.get('role', 'N/A')}, Data URI length: {len(img_data.get('image_data_uri', ''))}")
                    

if __name__ == '__main__':
    main()
