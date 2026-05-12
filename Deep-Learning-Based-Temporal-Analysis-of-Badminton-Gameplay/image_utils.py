import numpy as np
import cv2
from PIL import Image
import matplotlib.pyplot as plt

def convert_pil_to_cv2(pil_image):
    """
    Convert PIL image to OpenCV format (BGR).
    
    Args:
        pil_image (PIL.Image): PIL image
        
    Returns:
        numpy.ndarray: OpenCV image
    """
    return cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)

def convert_cv2_to_pil(cv2_image):
    """
    Convert OpenCV image (BGR) to PIL format (RGB).
    
    Args:
        cv2_image (numpy.ndarray): OpenCV image
        
    Returns:
        PIL.Image: PIL image
    """
    return Image.fromarray(cv2.cvtColor(cv2_image, cv2.COLOR_BGR2RGB))

def draw_keypoints(image, keypoints, radius=5, color=(0, 255, 0), thickness=-1):
    """
    Draw keypoints on an image.
    
    Args:
        image (numpy.ndarray): OpenCV image
        keypoints (numpy.ndarray): Array of keypoint coordinates
        radius (int): Circle radius
        color (tuple): BGR color tuple
        thickness (int): Line thickness (-1 for filled circle)
        
    Returns:
        numpy.ndarray: Image with keypoints
    """
    image_copy = image.copy()
    
    for point in keypoints:
        cv2.circle(
            image_copy,
            (int(point[0]), int(point[1])),
            radius,
            color,
            thickness
        )
    
    return image_copy

def draw_court_overlay(image, corners, transformed_players=None, overlay_scale=0.2):
    """
    Draw a court overlay on the image with optional player positions.
    
    Args:
        image (numpy.ndarray): OpenCV image
        corners (numpy.ndarray): Court corner points
        transformed_players (list, optional): List of player positions
        overlay_scale (float): Scale of the overlay
        
    Returns:
        numpy.ndarray: Image with court overlay
    """
    image_copy = image.copy()
    height, width = image_copy.shape[:2]
    
    # Create court overlay (white background with black lines)
    court_overlay = np.ones((1340, 610, 3), dtype=np.uint8) * 255
    
    # Draw court boundary
    cv2.rectangle(court_overlay, (0, 0), (610, 1340), (0, 0, 0), 2)
    
    # Draw net line
    cv2.line(court_overlay, (0, 670), (610, 670), (0, 0, 0), 2)
    
    # Calculate overlay dimensions and position
    overlay_width = int(610 * overlay_scale)
    overlay_height = int(1340 * overlay_scale)
    
    overlay_x = width - overlay_width - 10
    overlay_y = 10
    
    # Resize court overlay
    small_court = cv2.resize(court_overlay, (overlay_width, overlay_height))
    
    # Add overlay to image
    image_copy[overlay_y:overlay_y+overlay_height, overlay_x:overlay_x+overlay_width] = small_court
    
    # Draw player positions on overlay if provided
    if transformed_players:
        for i, player_pos in enumerate(transformed_players):
            # Calculate position on small court
            x_small = int(player_pos[0] * overlay_scale) + overlay_x
            y_small = int(player_pos[1] * overlay_scale) + overlay_y
            
            # Use different colors for different players
            color = (0, 0, 255) if i == 0 else (255, 0, 0)
            
            # Draw dot on small court
            cv2.circle(image_copy, (x_small, y_small), 3, color, -1)
    
    # Draw corners on main image
    for corner in corners:
        cv2.circle(image_copy, (int(corner[0]), int(corner[1])), 5, (0, 255, 0), -1)
    
    return image_copy

def fig_to_image(fig):
    """
    Convert matplotlib figure to image.
    
    Args:
        fig (matplotlib.figure.Figure): Matplotlib figure
        
    Returns:
        numpy.ndarray: Image as numpy array
    """
    fig.canvas.draw()
    
    # Get the RGB buffer from the figure
    w, h = fig.canvas.get_width_height()
    buf = np.fromstring(fig.canvas.tostring_argb(), dtype=np.uint8)
    buf.shape = (h, w, 3)
    
    return buf