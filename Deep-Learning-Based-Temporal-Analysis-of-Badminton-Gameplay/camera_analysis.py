import numpy as np

def calculate_view_parameters(points):
    """
    Calculate camera view parameters based on court keypoints.
    
    Args:
        points (np.ndarray): Array of shape (4, 2) containing court corner points
        
    Returns:
        dict: Camera parameters including height, angle, and distance
    """
    # Unpack the points
    top_left, top_right, bottom_left, bottom_right = points
    
    # Calculate average Y-coordinates for top and bottom edges
    y_top = (top_left[1] + top_right[1]) / 2
    y_bottom = (bottom_left[1] + bottom_right[1]) / 2
    
    # Calculate image height
    h_image = y_bottom - y_top
    
    # Actual height of the rectangle (badminton court length in cm)
    H = 1340
    
    # Calculate scaling factor
    scaling_factor = H / h_image
    
    # Estimate actual height above ground (rough approximation)
    h_actual = scaling_factor * h_image / 2
    
    # Calculate horizontal distance between top corners
    d_horizontal = np.linalg.norm(top_right - top_left)
    
    # Calculate angle of inclination in degrees
    theta = np.arctan2(h_actual, d_horizontal) * (180 / np.pi)
    
    # Calculate distance from shorter edge (approximate)
    d_shorter_edge = np.linalg.norm(top_left - bottom_left) / 2
    
    return {
        "height_above_ground": round(h_actual, 2),
        "angle_of_inclination": round(theta, 2),
        "distance_from_shorter_edge": round(d_shorter_edge, 2)
    }