import cv2
import numpy as np
from PIL import Image
import os
import tempfile
from tqdm import tqdm

class VideoProcessor:
    """
    Class for processing badminton videos.
    """
    def __init__(self, keypoints_detector, player_tracker):
        """
        Initialize the video processor.
        
        Args:
            keypoints_detector: Keypoints detector instance
            player_tracker: Player tracker instance
        """
        self.keypoints_detector = keypoints_detector
        self.player_tracker = player_tracker
        
    def process_video(self, video_path, output_path=None):
        """
        Process video to extract all needed information.
        
        Args:
            video_path (str): Path to the input video
            output_path (str, optional): Path to save the processed video
            
        Returns:
            dict: Dictionary containing all analysis results
        """
        print("Starting video processing...")
        
        # Extract court corners
        print("Detecting court corners...")
        corners = self.keypoints_detector.get_court_corners(video_path)
        print(f"Court corners detected: {corners}")

        # Calculate perspective matrix
        perspective_matrix = self.keypoints_detector.get_perspective_matrix(corners)
        print("Perspective matrix calculated")

        # Compute court bounds in image space and pass to tracker
        court_bounds = self.player_tracker.compute_court_bounds_from_corners(corners)
        print(f"Court bounds (pixels, with pad): {court_bounds}")
        self.player_tracker.court_bounds = court_bounds

        # Track players
        print("Tracking players...")
        players_dict = self.player_tracker.track_players(video_path)
        print(f"Players tracked in {len(players_dict)} frames")
        
        # Apply perspective transform to player positions
        transformed_players_dict = self.player_tracker.apply_perspective_transform(
            players_dict, perspective_matrix
        )
        
        # Verify and fix player positions
        corrected_players_dict = self.player_tracker.verify_and_fix_players(
            transformed_players_dict
        )
        print("Player positions corrected")
        
        # Generate visualized output video if requested
        if output_path:
            self.create_output_video(
                video_path, output_path, corners, corrected_players_dict
            )
            print(f"Output video saved to: {output_path}")
        
        # Get video frame rate for analysis
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        cap.release()
        
        return {
            'corners': corners,
            'perspective_matrix': perspective_matrix,
            'players_dict': players_dict,
            'transformed_players_dict': corrected_players_dict,
            'video_fps': fps
        }
    
    def create_output_video(self, input_path, output_path, corners, transformed_players_dict):
        """
        Create an output video with visualizations.
        
        Args:
            input_path (str): Path to the input video
            output_path (str): Path for the output video
            corners (np.ndarray): Court corner points
            transformed_players_dict (dict): Transformed player positions
        """
        # Open input video
        cap = cv2.VideoCapture(input_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        # Court overlay (empty badminton court image)
        court_overlay = np.zeros((1340, 610, 3), dtype=np.uint8)
        court_overlay[:, :, :] = 255  # White background
        
        # Draw court lines
        cv2.rectangle(court_overlay, (0, 0), (610, 1340), (0, 0, 0), 2)  # Court boundary
        cv2.line(court_overlay, (0, 670), (610, 670), (0, 0, 0), 2)  # Net line
        
        # Initialize video writer
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
        
        # Get total frame count for progress bar
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        frame_idx = 0
        
        # Process each frame
        for _ in tqdm(range(total_frames), desc="Creating output video"):
            ret, frame = cap.read()
            if not ret:
                break
                
            frame_idx += 1
            
            # Draw court corners on the frame
            for point in corners:
                cv2.circle(frame, (int(point[0]), int(point[1])), 5, (0, 255, 0), -1)
            
            # Draw player positions if available
            if frame_idx in transformed_players_dict:
                positions = transformed_players_dict[frame_idx]
                if len(positions) >= 2:
                    # Draw far player (red)
                    far_pos = positions[0]
                    cv2.circle(frame, (int(far_pos[0]), int(far_pos[1])), 10, (0, 0, 255), -1)
                    
                    # Draw near player (blue)
                    near_pos = positions[1]
                    cv2.circle(frame, (int(near_pos[0]), int(near_pos[1])), 10, (255, 0, 0), -1)
            
            # Add court overlay in the corner
            overlay_scale = 0.2
            overlay_width = int(610 * overlay_scale)
            overlay_height = int(1340 * overlay_scale)
            
            overlay_x = width - overlay_width - 10
            overlay_y = 10
            
            # Resize court overlay
            small_court = cv2.resize(court_overlay, (overlay_width, overlay_height))
            
            # Add court overlay to frame
            frame[overlay_y:overlay_y+overlay_height, overlay_x:overlay_x+overlay_width] = small_court
            
            # Draw player positions on the small court
            if frame_idx in transformed_players_dict:
                positions = transformed_players_dict[frame_idx]
                if len(positions) >= 2:
                    # Map player positions to small court
                    far_small_x = int(positions[0][0] * overlay_scale) + overlay_x
                    far_small_y = int(positions[0][1] * overlay_scale) + overlay_y
                    
                    near_small_x = int(positions[1][0] * overlay_scale) + overlay_x
                    near_small_y = int(positions[1][1] * overlay_scale) + overlay_y
                    
                    # Draw player dots on small court
                    cv2.circle(frame, (far_small_x, far_small_y), 3, (0, 0, 255), -1)
                    cv2.circle(frame, (near_small_x, near_small_y), 3, (255, 0, 0), -1)
            
            # Write frame to output video
            out.write(frame)
        
        # Release resources
        cap.release()
        out.release()