import streamlit as st
import tempfile
import os
from pathlib import Path
import subprocess
import cv2
import time

def play_video(video_path):
    """
    Display a video player in Streamlit.
    
    Args:
        video_path (str): Path to the video file
    """
    # Display video player
    video_file = open(video_path, 'rb')
    video_bytes = video_file.read()
    st.video(video_bytes)

def upload_video():
    """
    Provide a file uploader widget for video files.
    
    Returns:
        str or None: Path to the uploaded video file, or None if no file was uploaded
    """
    uploaded_file = st.file_uploader("Upload a badminton video", type=["mp4", "avi", "mov"])
    
    if uploaded_file is not None:
        # Create a temporary file to save the uploaded video
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp_file:
            # Write the uploaded file content to the temporary file
            tmp_file.write(uploaded_file.read())
            tmp_file_path = tmp_file.name
        
        return tmp_file_path
    
    return None

def show_results_video(input_video_path, results):
    """
    Process and show the analysis results video.
    
    Args:
        input_video_path (str): Path to the input video
        results (dict): Results from the video analysis
        
    Returns:
        str: Path to the output video
    """
    # Create a temporary file for the output video
    output_video_path = os.path.join(tempfile.gettempdir(), "processed_video.mp4")
    
    # Check if we already have an output video
    if os.path.exists(output_video_path):
        # Check if the video is from the current session
        video_creation_time = os.path.getmtime(output_video_path)
        current_time = time.time()
        
        # If the video is older than 30 minutes, recreate it
        if (current_time - video_creation_time) > 1800:
            os.remove(output_video_path)
        else:
            st.info("Using cached processed video")
            return output_video_path
    
    # Show processing status
    with st.spinner("Processing video... This may take several minutes"):
        # Use OpenCV to create an output video with overlays
        cap = cv2.VideoCapture(input_video_path)
        
        # Get video properties
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        
        # Define the codec and create VideoWriter object
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_video_path, fourcc, fps, (width, height))
        
        frame_idx = 0
        
        # Process each frame of the video
        progress_bar = st.progress(0)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        corners = results.get('corners', [])
        transformed_players_dict = results.get('transformed_players_dict', {})
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            frame_idx += 1
            progress_bar.progress(min(frame_idx / total_frames, 1.0))
            
            # Draw court corners
            for point in corners:
                cv2.circle(frame, (int(point[0]), int(point[1])), 5, (0, 255, 0), -1)
            
            # Draw player positions
            if frame_idx in transformed_players_dict:
                positions = transformed_players_dict[frame_idx]
                if len(positions) >= 2:
                    # Draw far player (red)
                    far_pos = positions[0]
                    cv2.circle(frame, (int(far_pos[0]), int(far_pos[1])), 10, (0, 0, 255), -1)
                    
                    # Draw near player (blue)
                    near_pos = positions[1]
                    cv2.circle(frame, (int(near_pos[0]), int(near_pos[1])), 10, (255, 0, 0), -1)
            
            # Write the frame to the output video
            out.write(frame)
        
        # Release resources
        cap.release()
        out.release()
    
    return output_video_path