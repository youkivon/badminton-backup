import torch
import torchvision.models as models
import torchvision.transforms as transforms
from PIL import Image
import numpy as np
import cv2
import os

class KeypointsDetector:
    """
    Class for detecting court keypoints in badminton videos.
    """
    def __init__(self, model_path):
        """
        Initialize the keypoints detector.
        
        Args:
            model_path (str): Path to the keypoints model file
        """
        # Set up device (GPU if available, otherwise CPU)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
        # Load the model
        self.model = self._load_model(model_path)
        
        # Set up image transformation
        self.transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
        ])
    
    def _load_model(self, model_path):
        """
        Load the keypoint detection model.
        
        Args:
            model_path (str): Path to the model file
            
        Returns:
            torch.nn.Module: Loaded model
        """
        # Check if model file exists
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model file not found: {model_path}")
        
        # Initialize model architecture
        model = models.resnet50(weights=None)
        model.fc = torch.nn.Linear(model.fc.in_features, 30 * 2)  # 30 keypoints with (x, y) coordinates
        
        # Load weights
        try:
            model.load_state_dict(torch.load(model_path, map_location=self.device, weights_only=True))
            model.to(self.device)
            model.eval()
            print(f"Keypoints model loaded successfully from {model_path}")
            return model
        except Exception as e:
            raise RuntimeError(f"Failed to load model: {str(e)}")
    
    def detect_keypoints(self, image):
        """
        Detect keypoints in an image.
        
        Args:
            image (PIL.Image): Input image
            
        Returns:
            np.ndarray: Array of detected keypoints
        """
        with torch.no_grad():
            # Transform and process the image
            input_img = self.transform(image).unsqueeze(0).to(self.device)
            output = self.model(input_img)
            
            # Process the output
            keypoints = output.cpu().numpy().reshape(-1, 2)
            
            # Scale keypoints back to the original image dimensions
            img_width, img_height = image.size
            keypoints[:, 0] *= img_width / 224
            keypoints[:, 1] *= img_height / 224
            
            # Round down the keypoint coordinates
            keypoints = self._round_down(keypoints)
            
            return keypoints
    
    def _round_down(self, arr, decimals=2):
        """
        Round down array values to specified decimal places.
        
        Args:
            arr (np.ndarray): Input array
            decimals (int): Number of decimal places
            
        Returns:
            np.ndarray: Array with rounded-down values
        """
        factor = 10 ** decimals
        return np.floor(arr * factor) / factor
    
    def get_court_corners(self, video_path, interval=50):
        """
        Extract and average court corner keypoints from a video.
        
        Args:
            video_path (str): Path to the video file
            interval (int): Sampling interval for frames
            
        Returns:
            np.ndarray: Array of averaged corner keypoints
        """
        # Check if video file exists
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")
        
        # Open the video
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Could not open video: {video_path}")
        
        frame_count = 0
        sum_keypoints = {
            1: np.array([0.0, 0.0]),
            5: np.array([0.0, 0.0]),
            26: np.array([0.0, 0.0]),
            30: np.array([0.0, 0.0])
        }
        count = 0
        
        try:
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break
                
                frame_count += 1
                
                # Sample frames at the specified interval
                if frame_count % interval == 1:
                    # Convert frame to PIL image
                    pil_image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                    
                    # Detect all keypoints
                    all_keypoints = self.detect_keypoints(pil_image)
                    
                    # Extract corner keypoints (indices 0, 4, 25, 29 since array is zero-indexed)
                    sum_keypoints[1] += all_keypoints[0]
                    sum_keypoints[5] += all_keypoints[4]
                    sum_keypoints[26] += all_keypoints[25]
                    sum_keypoints[30] += all_keypoints[29]
                    count += 1
                    
                    # Log progress
                    if frame_count % (interval * 10) == 1:
                        print(f"Processed {frame_count} frames")
        finally:
            cap.release()
        
        # Calculate averages
        if count > 0:
            avg_keypoints = np.array([
                sum_keypoints[1] / count,
                sum_keypoints[5] / count,
                sum_keypoints[26] / count,
                sum_keypoints[30] / count
            ])
            
            return self._round_down(avg_keypoints)
        else:
            raise ValueError("No keypoints were detected in the video")
    
    def get_perspective_matrix(self, corner_points):
        """
        Calculate perspective transformation matrix.
        
        Args:
            corner_points (np.ndarray): Array of court corner points
            
        Returns:
            np.ndarray: Perspective transformation matrix
        """
        # Source points (detected court corners)
        src_points = np.array(corner_points, dtype=np.float32)
        
        # Destination points (standard badminton court dimensions in cm)
        dst_points = np.float32([
            [0, 0],         # Top-left
            [610, 0],       # Top-right
            [0, 1340],      # Bottom-left
            [610, 1340]     # Bottom-right
        ])
        
        # Calculate the perspective transform matrix
        M = cv2.getPerspectiveTransform(src_points, dst_points)
        
        return M