# openai_adapter.py

import openai
import requests # For downloading images from URLs
import io       # For handling byte streams
import base64   # For handling b64_json response
import concurrent.futures # For parallel processing
import time  # For tracking parallel requests
from typing import List, Union, Dict, Tuple, Any
import json
import random
import logging

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('openai_adapter')

# Import the prompt modifiers
from prompt_modifiers import load_prompt_modifiers

# Import credentials from shared config module (works with both Streamlit secrets and .env)
from config import OPENAI_API_KEY

# Set up OpenAI client
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY
else:
    print("Warning: OPENAI_API_KEY not found in Streamlit secrets or .env file.")

client = None
if openai.api_key:
    client = openai.OpenAI()

# System prompt to guide the AI model
SYSTEM_PROMPT_FOR_IMAGE_GENERATION = "Please generate a design for custom challenge coin front side only using the below input from the customer and attached images.  The attached images may contain initial designs for either the front or back of a coin as well as reference images and logos"

# Load the prompt modifiers for variation in generated designs
PROMPT_MODIFIERS = load_prompt_modifiers()

def generate_image_with_multiple_inputs(prompt_text: str, input_images_data: List[Dict], parallel: bool = True) -> Union[List[Dict[str, Any]], str, None]:
    """
    Generates or edits an image based on a prompt and multiple input images (with roles),
    using OpenAI's 'gpt-image-1' model (as per user specification).

    Args:
        prompt_text (str): The textual description for the generation/editing.
        input_images_data (list[dict]): List of dictionaries, where each dict contains
                                      'image_data_uri' (str) and 'role' (str) for an input image.

    Returns:
        Union[str, None]: The URL of the generated image if available, 
                          otherwise the b64_json string of the image data, 
                          or None if an error occurred or no data was found.
    """
    if not client:
        print("Error: OpenAI client not initialized. Check API key.")
        return None
    if not prompt_text or not prompt_text.strip():
        print("Error: Prompt text cannot be empty.")
        return None

    if parallel and PROMPT_MODIFIERS:
        return _generate_multiple_variations(prompt_text, input_images_data)
    else:
        return _generate_single_image(prompt_text, input_images_data)

def _generate_single_image(prompt_text: str, input_images_data: List[Dict], prompt_modifier: Tuple[str, str] = None) -> Union[Dict[str, Any], None]:
    """
    Generate a single image with the given prompt and input images.
    
    Args:
        prompt_text: The user's prompt text
        input_images_data: List of image data dictionaries
        prompt_modifier: Optional tuple of (title, prompt_text) to modify the base prompt
        
    Returns:
        Dictionary with image data or None if failed
    """
    if not client:
        print("Error: OpenAI client not initialized. Check API key.")
        return None
    if not prompt_text or not prompt_text.strip():
        print("Error: Prompt text cannot be empty.")
        return None

    # Start with the system prompt
    full_prompt = SYSTEM_PROMPT_FOR_IMAGE_GENERATION
    
    # Add the prompt modifier if provided
    modifier_title = None
    if prompt_modifier:
        modifier_title, modifier_text = prompt_modifier
        full_prompt += f"\n\nStyle Directive: {modifier_title}\n{modifier_text}"
    
    # Add the user's request
    full_prompt += f"\n\nUser's request: {prompt_text}"

    # Append image role information to the prompt (without the actual data URIs)
    if input_images_data:
        full_prompt += "\n\nProvided Images:"
        for i, img_data in enumerate(input_images_data):
            full_prompt += f"\n- Image {i+1} (Role: {img_data.get('role', 'N/A')})"

    # Check if input images are provided, but don't require them
    if not input_images_data:
        print("Note: No input images provided. Proceeding with text-only prompt.")
        # Continue with text-only prompt instead of returning None

    image_bytes_list = []
    for i, image_item in enumerate(input_images_data):
        image_data_uri = image_item.get('image_data_uri')
        role = image_item.get('role', 'N/A') # Get role for context, though not directly used in download

        if not image_data_uri or not image_data_uri.strip():
            print(f"Skipping empty image_data_uri for image {i+1} (Role: {role})")
            continue
        try:
            print(f"Processing input image {i+1} (Role: {role})")
            # Assuming image_data_uri is a base64 data URI
            # Remove the data URI prefix and decode the base64 string
            mime_type, encoded_string = image_data_uri.split(',', 1)
            img_bytes = base64.b64decode(encoded_string)
            img_bytes = io.BytesIO(img_bytes)
            # OpenAI library might need a name attribute, or it might infer from the bytes object directly.
            # For safety, assign a generic name if needed, though for a list of BytesIO, it might not be critical.
            img_bytes.name = f"input_image_{i+1}.png" 
            image_bytes_list.append(img_bytes)
        except Exception as e:
            print(f"Failed to process input image from image_data_uri: {e}")
            continue # Skip this image but try to continue with others handle partial failures differently, e.g., by skipping the image

    # If no valid images could be processed, we'll use the images.generate endpoint instead of images.edit
    use_generate_endpoint = len(image_bytes_list) == 0
    if use_generate_endpoint:
        print("No valid images could be processed. Using images.generate endpoint instead of images.edit.")
        # We'll continue with the text-only prompt

    try:
        style_info = f" Style: {modifier_title}" if modifier_title else ""
        
        # Log more details about the request
        request_id = f"req_{int(time.time())}_{random.randint(1000, 9999)}"
        logger.info(f"[{request_id}] Starting OpenAI request - {style_info}")
        print(f"Full prompt (truncated): {full_prompt[:200]}{'...' if len(full_prompt) > 200 else ''}")
        
        # Compute and log prompt length for debugging
        prompt_length = len(full_prompt)
        total_bytes = sum([img.getbuffer().nbytes for img in image_bytes_list]) if image_bytes_list else 0
        logger.info(f"[{request_id}] Request stats - Prompt length: {prompt_length} chars, Total image bytes: {total_bytes}")
        
        if use_generate_endpoint:
            # Use the images.generate endpoint when no images are provided
            print(f"Calling OpenAI images.generate with 'gpt-image-1'.{style_info}")
            logger.info(f"[{request_id}] About to make API call to OpenAI using images.generate - model: gpt-image-1")
            response = client.images.generate(
                model="gpt-image-1", # Using GPT Image model for improved image generation
                prompt=full_prompt, # Use the combined prompt
                n=1, # Number of images to generate
                size="1024x1024", # Specify a supported size
                quality="medium",
                background='transparent'
            )
        else:
            # Use the images.edit endpoint when images are provided
            print(f"Calling OpenAI images.edit with 'gpt-image-1'.{style_info} Number of images: {len(image_bytes_list)}")
            print(f"Image bytes list contains {len(image_bytes_list)} images")
            
            # Detailed image logging
            image_details = []
            for i, img_bytes in enumerate(image_bytes_list):
                size_bytes = img_bytes.getbuffer().nbytes
                name = getattr(img_bytes, 'name', 'unnamed')
                print(f"  Image {i+1} - Size: {size_bytes} bytes, Name: {name}")
                image_details.append({"index": i+1, "size_bytes": size_bytes, "name": name})
            
            logger.info(f"[{request_id}] About to make API call to OpenAI using images.edit - model: gpt-image-1")
            logger.info(f"[{request_id}] Image details: {json.dumps(image_details)}")
            
            response = client.images.edit(
                model="gpt-image-1", # As specified by user
                image=image_bytes_list, # List of image byte streams
                prompt=full_prompt, # Use the combined prompt
                n=1, # Number of images to generate
                size="1024x1024", # Specify a supported size
                quality="medium",
                background='transparent'
            )
        
        logger.info(f"[{request_id}] API call to OpenAI completed successfully")
        print("API call to OpenAI completed successfully")

        # print(f"Full OpenAI API response object: {response}")
        if response.data and len(response.data) > 0:
            image_data_obj = response.data[0]
            # print(f"OpenAI API response.data[0] content: {image_data_obj}")

            result = {
                "style": modifier_title if modifier_title else "Standard",
                "success": True,
                "error": None
            }
            
            if image_data_obj.url:
                print(f"Successfully received image URL from OpenAI: {image_data_obj.url}")
                result["url"] = image_data_obj.url
                result["b64_json"] = None
                return result
            elif image_data_obj.b64_json:
                print("Received b64_json data from OpenAI. URL was None.")
                result["url"] = None
                result["b64_json"] = image_data_obj.b64_json
                return result
            else:
                print("Neither URL nor b64_json found in the response data.")
                return None
        else:
            print("OpenAI API response.data is empty or missing.")
            return None

    except openai.APIConnectionError as e:
        logger.error(f"OpenAI API request failed to connect: {e}")
        print(f"OpenAI API request failed to connect: {e}")
        return {"style": modifier_title if modifier_title else "Standard", "success": False, "error": str(e)}
            
    except openai.RateLimitError as e:
        logger.error(f"OpenAI API request exceeded rate limit: {e}")
        print(f"OpenAI API request exceeded rate limit: {e}")
        return {"style": modifier_title if modifier_title else "Standard", "success": False, "error": str(e)}
            
    except openai.APIStatusError as e:
        logger.error(f"OpenAI API returned an API Error: {e.status_code} - {e.response}")
        print(f"OpenAI API returned an API Error: {e.status_code} - {e.response}")
        
        error_message = ""
        try:
            error_details = e.response.json() # Attempt to parse JSON response
            logger.debug(f"Error details (JSON): {error_details}")
            print(f"Error details (JSON): {error_details}")
            
            # Extract more specific error information if available
            if isinstance(error_details, dict):
                if 'error' in error_details:
                    error_obj = error_details['error']
                    if isinstance(error_obj, dict):
                        error_type = error_obj.get('type', 'unknown')
                        error_code = error_obj.get('code', 'unknown')
                        error_param = error_obj.get('param', 'unknown')
                        error_msg = error_obj.get('message', 'No specific message')
                        logger.debug(f"Detailed error info - Type: {error_type}, Code: {error_code}, Param: {error_param}, Message: {error_msg}")
                        print(f"Detailed error info - Type: {error_type}, Code: {error_code}, Param: {error_param}, Message: {error_msg}")
                        
                        # Special handling for 500 errors
                        if e.status_code == 500:
                            logger.warning(f"Server error detected. Diagnostic information:\n" + 
                                          f"  - Request ID: {request_id}\n" +
                                          f"  - Error type: {error_type}\n" +
                                          f"  - Server message: {error_msg}\n" +
                                          f"  - Prompt length: {prompt_length} chars\n" +
                                          f"  - Image count: {len(image_bytes_list)}\n" +
                                          f"  - Total image bytes: {total_bytes}\n")
            error_message = str(error_details)
        except Exception as json_e:
            logger.error(f"Could not parse error response as JSON: {json_e}")
            print(f"Could not parse error response as JSON: {json_e}")
            error_text = e.response.text if hasattr(e.response, 'text') else 'No text attribute'
            logger.debug(f"Raw error response text: {error_text}")
            print(f"Raw error response text: {error_text}")
            error_message = error_text

        # Check for specific error conditions
        if e.status_code == 404 and "model_not_found" in str(e.response).lower():
            logger.error("Error: The model 'gpt-image-1' was not found. Please ensure it's available for your API key and correctly named.")
            print("Error: The model 'gpt-image-1' was not found. Please ensure it's available for your API key and correctly named.")
        elif e.status_code == 400:
            logger.error(f"Error: Invalid request (400). This could be due to incorrect parameters for 'gpt-image-1', image format issues, or other input problems.")
            print(f"Error: Invalid request (400). This could be due to incorrect parameters for 'gpt-image-1', image format issues, or other input problems.")
            # Check for common image-related errors
            if "invalid_image" in str(e.response).lower():
                logger.error("The error appears to be related to invalid image format or content.")
                print("The error appears to be related to invalid image format or content.")
            elif "content_policy_violation" in str(e.response).lower():
                logger.error("The error appears to be related to content policy violation.")
                print("The error appears to be related to content policy violation.")
        elif e.status_code == 429:
            logger.error("Error: Rate limit exceeded. You may need to wait before making more requests.")
            print("Error: Rate limit exceeded. You may need to wait before making more requests.")
        elif e.status_code == 500:
            logger.error(f"Error: OpenAI server error (500). This is an issue on OpenAI's side.")
            print(f"Error: OpenAI server error (500). This is an issue on OpenAI's side.")
            print(f"This appears to be a temporary issue with OpenAI's servers.")
            print(f"Request details: Style: {modifier_title or 'Standard'}, Images: {len(image_bytes_list)}, Prompt length: {prompt_length}")
        
        return {"style": modifier_title if modifier_title else "Standard", "success": False, "error": error_message}
        
    except Exception as e:
        # Handle other exceptions
        logger.error(f"An unexpected error occurred: {e}")
        print(f"An unexpected error occurred: {e}")
        import traceback
        logger.error(traceback.format_exc())
        traceback.print_exc()
        return {"style": modifier_title if modifier_title else "Standard", "success": False, "error": str(e)}


def _generate_multiple_variations(prompt_text: str, input_images_data: List[Dict], max_concurrent_requests=5) -> List[Dict[str, Any]]:
    """
    Generate multiple image variations with different prompt modifiers in parallel.
{{ ... }}
    Args:
        prompt_text: The user's prompt text
        input_images_data: List of image data dictionaries
        max_concurrent_requests: Maximum number of concurrent API requests to make
        
    Returns:
        List of dictionaries with image data for each variation
    """
    results = []

    # Implement a semaphore to limit concurrent API requests
    import threading
    request_semaphore = threading.Semaphore(max_concurrent_requests)

    # Function to acquire semaphore before making API request and release after
    def limited_api_request(prompt_text, input_images_data, modifier):
        with request_semaphore:
            return _generate_single_image(prompt_text, input_images_data, modifier)

    if not PROMPT_MODIFIERS:
        print("No prompt modifiers found. Falling back to single image generation.")
        result = _generate_single_image(prompt_text, input_images_data)
        return [result] if result else []

    results = []
    max_workers = min(5, len(PROMPT_MODIFIERS))  # Limit to 5 concurrent requests
    print(f"Generating {len(PROMPT_MODIFIERS)} design variations in parallel...")
    
    # Log input data for debugging
    print(f"Input prompt text: {prompt_text[:100]}{'...' if len(prompt_text) > 100 else ''}")
    print(f"Number of input images: {len(input_images_data)}")
    for i, img_data in enumerate(input_images_data):
        print(f"  Image {i+1} - Role: {img_data.get('role', 'N/A')}, Data URI length: {len(img_data.get('image_data_uri', ''))}")
    
    # Assign the different prompt modifiers from the file
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for i, modifier in enumerate(PROMPT_MODIFIERS):
            print(f"Submitting generation task for style: {modifier[0]}")
            # Submit each generation task to the executor
            future = executor.submit(_generate_single_image, prompt_text, input_images_data, modifier)
            futures.append((future, modifier))
        
        # Collect results as they complete
        for future, modifier in [(f, m) for f, m in futures]:
            try:
                print(f"Waiting for result from style: {modifier[0]}...")
                result = future.result()
                if result:
                    print(f"Successfully generated design for style: {modifier[0]}")
                    results.append(result)
                else:
                    print(f"Failed to generate design for style: {modifier[0]} - result was None")
                    results.append({"style": modifier[0], "success": False, "error": "Generation returned None"})
            except Exception as e:
                print(f"Error in parallel image generation for style {modifier[0]}: {e}")
                import traceback
                traceback.print_exc()
                # Create a result entry for the failed generation
                results.append({"style": modifier[0], "success": False, "error": str(e)})
    
    print(f"Generated {len(results)} design variations.")
    print(f"Successful designs: {len([r for r in results if r.get('success', False)])}")
    print(f"Failed designs: {len([r for r in results if not r.get('success', False)])}")
    
    # If all designs failed, log a more detailed error
    if len([r for r in results if r.get('success', False)]) == 0:
        logger.critical("All design variations failed to generate!")
        print("CRITICAL ERROR: All design variations failed to generate!")
        
        # Check for pattern of failures
        server_errors = 0
        rate_limit_errors = 0
        other_errors = 0
        for i, result in enumerate(results):
            error_str = str(result.get('error', 'Unknown error'))
            print(f"  Failure {i+1} - Style: {result.get('style', 'Unknown')}, Error: {error_str}")
            
            if "server_error" in error_str.lower() or "500" in error_str:
                server_errors += 1
            elif "rate_limit" in error_str.lower() or "429" in error_str:
                rate_limit_errors += 1
            else:
                other_errors += 1
        
        # Provide aggregate error statistics and suggestions
        logger.error(f"Error breakdown - Server errors: {server_errors}, Rate limit: {rate_limit_errors}, Other: {other_errors}")
        if server_errors > 0:
            print(f"\nDetected {server_errors} server errors (500). This indicates an issue on OpenAI's side.")
            print("Suggestion: Wait a few minutes and try again later.")
        if rate_limit_errors > 0:
            print(f"\nDetected {rate_limit_errors} rate limit errors. You may be sending too many requests.")
            print("Suggestion: Reduce the number of parallel requests or add delays between requests.")
        if len(image_bytes_list) > 0:
            total_image_size = sum([img.getbuffer().nbytes for img in image_bytes_list])
            print(f"\nTotal image size: {total_image_size/1024/1024:.2f} MB across {len(image_bytes_list)} images")
            if total_image_size > 15 * 1024 * 1024:  # 15 MB threshold
                print("Images may be too large. Try resizing images to be smaller.")
    
    return results

if __name__ == '__main__':
    if not OPENAI_API_KEY:
        print("CRITICAL: OPENAI_API_KEY not found. Please set it in your .env file or environment variables.")
    else:
        print("OpenAI API key loaded.")

        # Test the prompt modifiers are loaded correctly
        print("\n--- Available Prompt Modifiers ---")
        for i, (title, text) in enumerate(PROMPT_MODIFIERS, 1):
            print(f"{i}. {title}: {text[:50]}...")

        # You'll need publicly accessible image URLs to test this directly.
        print("\n--- Testing 'gpt-image-1' with Multiple Inputs (Example) ---")
        test_input_images_with_roles = [
            {"image_data_uri": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==", "role": "Logo to include"},
            {"image_data_uri": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==", "role": "Other reference image"}
        ]
        test_multi_prompt = "Our team name is Texas Sandlot, so I was thinking our logo over the state of Texas with baseball bats, balls around the side our the sandlot dog incorporated. We could also incorporate the sandlot dog as the main focus. I am open to design suggestions. We do not want player numbers. I have attached our artwork and I have a couple other dog designs if needed."

        # Test with a single variation
        print("\n--- Testing Single Variation ---")
        result_data = generate_image_with_multiple_inputs(test_multi_prompt, test_input_images_with_roles, parallel=False)
        if result_data:
            print(f"Single variation test successful.")
        else:
            print("Single variation test failed.")
            
        # Test parallel variations
        print("\n--- Testing Parallel Variations ---")
        result_data_list = generate_image_with_multiple_inputs(test_multi_prompt, test_input_images_with_roles, parallel=True)
        if result_data_list and len(result_data_list) > 0:
            print(f"Parallel variations test successful. Generated {len(result_data_list)} variations.")
        else:
            print("Parallel variations test failed.")
