import cv2
import numpy as np
import os
from ultralytics import YOLO

class PlayerTracker:
    """
    Class for tracking players in badminton videos.
    """
    def __init__(self, model_path, court_bounds=None):
        """
        Initialize the player tracker.

        Args:
            model_path (str): Path to the YOLO model file
            court_bounds (tuple): (x_min, y_min, x_max, y_max) in pixels —
                                  main court region; detections outside are discarded
        """
        # Check if model file exists
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model file not found: {model_path}")

        # Load YOLO model
        try:
            self.model = YOLO(model_path)
            print(f"Player detection model loaded successfully from {model_path}")
        except Exception as e:
            raise RuntimeError(f"Failed to load YOLO model: {str(e)}")

        # Court boundary filter (pixels, image-space)
        # (x_min, y_min, x_max, y_max); None means no filtering
        self.court_bounds = court_bounds

    @staticmethod
    def compute_court_bounds_from_corners(corners, pad=50):
        """
        Compute an axis-aligned bounding box from the four court corner points,
        with optional padding in pixels.

        Args:
            corners (np.ndarray): shape (4, 2), court corner coordinates in image space
            pad (int): padding in pixels to slightly expand the region

        Returns:
            tuple: (x_min, y_min, x_max, y_max)
        """
        xs = corners[:, 0]
        ys = corners[:, 1]
        return (int(xs.min() - pad), int(ys.min() - pad),
                int(xs.max() + pad), int(ys.max() + pad))
    
    def track_players(self, video_path):
        """
        Track players in a video and extract their positions.
        
        Args:
            video_path (str): Path to the video file
            
        Returns:
            dict: Dictionary mapping frame numbers to player positions
        """
        # Check if video file exists
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")
            
        # Open the video
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Could not open video: {video_path}")
            
        # Dictionary to store player positions
        players_dict = {}
        frame_number = 0
        
        try:
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break
                
                frame_number += 1
                
                # Track players in the current frame
                results = self.model.track(frame, persist=True)
                
                # Extract bounding boxes
                boxes = results[0].boxes.xyxy.cpu().numpy() if len(results) > 0 else []

                midpoints = []
                for box in boxes:
                    x1, y1, x2, y2 = map(int, box[:4])

                    # Court boundary filter: skip if center is outside court_bounds
                    cx = (x1 + x2) // 2
                    cy = (y1 + y2) // 2
                    if self.court_bounds is not None:
                        bx_min, by_min, bx_max, by_max = self.court_bounds
                        if not (bx_min <= cx <= bx_max and by_min <= cy <= by_max):
                            continue

                    # Calculate midpoint of the bottom line (player's feet)
                    midpoint_x = (x1 + x2) // 2
                    midpoint_y = y2

                    midpoints.append([midpoint_x, midpoint_y])
                
                # Store midpoints for this frame
                players_dict[frame_number] = midpoints
                
                # Log progress
                if frame_number % 100 == 0:
                    print(f"Processed {frame_number} frames")
        finally:
            cap.release()
            
        return players_dict
    
    def apply_perspective_transform(self, players_dict, M):
        """
        Apply perspective transformation to player positions.
        
        Args:
            players_dict (dict): Dictionary of player positions
            M (np.ndarray): Perspective transformation matrix
            
        Returns:
            dict: Dictionary of transformed player positions
        """
        transformed_dict = {}
        
        for frame_id, positions in players_dict.items():
            if len(positions) > 0:
                transformed_positions = []
                
                for pos in positions:
                    # Convert position to homogeneous coordinates
                    homogeneous_pos = np.array([pos[0], pos[1], 1])
                    
                    # Apply perspective transformation
                    transformed_pos = M.dot(homogeneous_pos)
                    
                    # Normalize
                    if transformed_pos[2] != 0:
                        transformed_pos = transformed_pos / transformed_pos[2]
                    
                    transformed_positions.append(transformed_pos[:2].tolist())
                
                transformed_dict[frame_id] = transformed_positions
        
        return transformed_dict
    
    def verify_and_fix_players(self, transformed_players_dict):
        """
        Verify and fix player positions based on court position.
        
        Args:
            transformed_players_dict (dict): Dictionary of transformed player positions
            
        Returns:
            dict: Dictionary of corrected player positions
        """
        # Net position on the court
        net_y_position = 670
        
        corrected_dict = {}
        
        for frame_id, positions in transformed_players_dict.items():
            # Skip frames with != 2 players
            if len(positions) != 2:
                continue
            
            far_player_pos = positions[0]
            near_player_pos = positions[1]
            
            # Check if players are on the correct sides
            if far_player_pos[1] <= net_y_position and near_player_pos[1] >= net_y_position:
                # Need to swap positions
                corrected_dict[frame_id] = [near_player_pos, far_player_pos]
            else:
                corrected_dict[frame_id] = [far_player_pos, near_player_pos]
        
        return corrected_dict