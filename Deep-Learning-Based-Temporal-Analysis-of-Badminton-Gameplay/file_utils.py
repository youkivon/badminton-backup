import os
import tempfile
import json
import cv2
import numpy as np
from datetime import datetime

def ensure_dir(directory):
    """
    Create directory if it doesn't exist.
    
    Args:
        directory (str): Directory path
    """
    if not os.path.exists(directory):
        os.makedirs(directory)

def get_temp_path(filename):
    """
    Get a temporary file path.
    
    Args:
        filename (str): Base filename
        
    Returns:
        str: Full temporary file path
    """
    return os.path.join(tempfile.gettempdir(), filename)

def save_analysis_results(results, filename="analysis_results.json"):
    """
    Save analysis results to a JSON file.
    
    Args:
        results (dict): Analysis results
        filename (str): Output filename
        
    Returns:
        str: Path to saved file
    """
    # Make a copy of the results to avoid modifying the original
    results_copy = results.copy()
    
    # Convert numpy arrays to lists for JSON serialization
    for key, value in results_copy.items():
        if isinstance(value, np.ndarray):
            results_copy[key] = value.tolist()
        elif isinstance(value, dict):
            # Handle dictionaries that might contain numpy arrays
            for k, v in value.items():
                if isinstance(v, np.ndarray):
                    results_copy[key][k] = v.tolist()
    
    # Save to temp file
    temp_path = get_temp_path(filename)
    with open(temp_path, 'w') as f:
        json.dump(results_copy, f)
    
    return temp_path

def load_analysis_results(filepath):
    """
    Load analysis results from a JSON file.
    
    Args:
        filepath (str): Path to the JSON file
        
    Returns:
        dict: Analysis results
    """
    if not os.path.exists(filepath):
        return None
    
    with open(filepath, 'r') as f:
        results = json.load(f)
    
    # Convert lists back to numpy arrays where appropriate
    # This is a simplified version - you may need to adapt it based on your data structure
    for key in ['corners', 'speed_image', 'distance_image', 'acceleration_image', 'heatmap_image', 'far_heatmap']:
        if key in results and results[key] is not None:
            results[key] = np.array(results[key])
    
    return results

def get_video_info(video_path):
    """
    Get video information.
    
    Args:
        video_path (str): Path to the video file
        
    Returns:
        dict: Video information
    """
    if not os.path.exists(video_path):
        return None
    
    cap = cv2.VideoCapture(video_path)
    
    if not cap.isOpened():
        cap.release()
        return None
    
    # Get video properties
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count / fps if fps > 0 else 0
    
    # Get file size and creation date
    file_size = os.path.getsize(video_path)
    creation_time = os.path.getctime(video_path)
    creation_date = datetime.fromtimestamp(creation_time).strftime('%Y-%m-%d %H:%M:%S')
    
    cap.release()
    
    return {
        'width': width,
        'height': height,
        'fps': fps,
        'frame_count': frame_count,
        'duration': duration,
        'file_size': file_size,
        'creation_date': creation_date
    }