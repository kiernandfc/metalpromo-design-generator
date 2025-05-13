"""
Module to load and parse prompt modifiers from the sample file.
"""
import os
from typing import List, Dict, Tuple

def load_prompt_modifiers(file_path: str = None) -> List[Tuple[str, str]]:
    """
    Loads prompt modifiers from a file.
    
    Args:
        file_path: Path to the file containing prompt modifiers.
                   If None, uses the default file in the same directory.
    
    Returns:
        List of tuples (title, prompt_text) for each prompt modifier.
    """
    if file_path is None:
        # Use the default file in the same directory
        current_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(current_dir, 'sample_prompt_modifiers.txt')
    
    modifiers = []
    current_title = None
    current_text = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # Check if this is a title line
            if line.startswith('🎯') or line.startswith('🧠') or line.startswith('🖼️') or line.startswith('🔧') or line.startswith('🎖️'):
                # If we already had a title, save the previous entry
                if current_title and current_text:
                    modifiers.append((current_title, ' '.join(current_text)))
                
                # Extract the title, e.g., "Prompt 1: "Heritage & Symbolism""
                parts = line.split(':', 1)
                if len(parts) > 1:
                    current_title = parts[1].strip().strip('"')
                else:
                    current_title = line
                
                current_text = []
                i += 1
            elif line:
                # Add non-empty lines to the current text
                current_text.append(line)
                i += 1
            else:
                # Skip empty lines
                i += 1
        
        # Add the last prompt if there is one
        if current_title and current_text:
            modifiers.append((current_title, ' '.join(current_text)))
        
    except Exception as e:
        print(f"Error loading prompt modifiers: {e}")
        # Return some default modifiers if loading fails
        return [
            ("Heritage & Symbolism", "Design a custom coin with traditional elements and symbolism."),
            ("Modern Minimalist", "Create a sleek, modern coin design with clean lines."),
            ("Illustrative & Detailed", "Generate an intricate, artistically rich coin design."),
            ("Functional + Industrial", "Design a coin that looks purpose-built and engineered."),
            ("Military Commemorative", "Create a military-themed custom coin that honors service.")
        ]
    
    return modifiers

if __name__ == "__main__":
    # Test loading modifiers
    modifiers = load_prompt_modifiers()
    for i, (title, text) in enumerate(modifiers, 1):
        print(f"Prompt {i}: {title}")
        print(text[:100] + "..." if len(text) > 100 else text)
        print()
