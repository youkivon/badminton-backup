# import sys
# from streamlit.web.server import watch_init

# # Add torch.classes to the ignored modules
# if "torch.classes" not in watch_init.IGNORED_MODULES:
#     watch_init.IGNORED_MODULES.append("torch.classes")

import streamlit as st
import os
import cv2
import numpy as np
import time
import json
import sys
import tempfile

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import backend modules
from backend.keypoints_detector import KeypointsDetector
from backend.player_tracker import PlayerTracker
from backend.video_processor import VideoProcessor
from backend.data_analysis import movement_analysis, position_analysis
from backend.camera_analysis import calculate_view_parameters

# Import frontend components
from frontend.components.video_display import upload_video, play_video, show_results_video
from frontend.components.data_display import display_metrics, display_visualizations

def get_model_paths():
    """Get paths to model files."""
    # Check if running via streamlit cloud
    if os.path.exists('/app/sports_analyzer/models'):
        base_path = '/app/sports_analyzer/models'
    else:
        # Use relative path for local development
        base_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'models')
    
    keypoints_model_path = os.path.join(base_path, 'keypoints_model_19.pth')
    player_model_path = os.path.join(base_path, 'player_detection_18_Nov.pt')
    
    return keypoints_model_path, player_model_path

def process_video_and_analyze(video_path):
    """Process video and run analysis."""
    # Get model paths
    keypoints_model_path, player_model_path = get_model_paths()
    
    # Initialize components
    keypoints_detector = KeypointsDetector(keypoints_model_path)
    player_tracker = PlayerTracker(player_model_path)
    video_processor = VideoProcessor(keypoints_detector, player_tracker)
    
    # Create a data directory in the project folder if it doesn't exist
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(project_dir, 'data')
    os.makedirs(data_dir, exist_ok=True)
    
    # Define paths for processed video and cache in project directory
    output_video_path = os.path.join(data_dir, "processed_video.mp4")
    cache_file = os.path.join(data_dir, "analysis_results.json")
    
    # Check if we already have cached results
    if os.path.exists(cache_file) and os.path.exists(output_video_path):
        video_creation_time = os.path.getmtime(output_video_path)
        current_time = time.time()
        
        # If the cache is less than 30 minutes old, use it
        if (current_time - video_creation_time) < 1:
            try:
                with open(cache_file, 'r') as f:
                    serializable_results = json.load(f)
                    st.success("Using cached analysis results")
                    return serializable_results, output_video_path
            except:
                pass

    # Process the video
    with st.spinner("Processing video and tracking players..."):
        results = video_processor.process_video(video_path, output_video_path)
    
    # Run movement analysis
    with st.spinner("Analyzing player movement..."):
        movement_results = movement_analysis(results['transformed_players_dict'], results['video_fps'])
        
    # Run position analysis
    with st.spinner("Analyzing player positioning..."):
        position_results = position_analysis(results['transformed_players_dict'])
    
    # Calculate camera parameters
    with st.spinner("Calculating camera parameters..."):
        camera_params = calculate_view_parameters(results['corners'])
    
    # Combine all results
    combined_results = {
        **movement_results,
        **position_results,
        **camera_params,
        'corners': results['corners'].tolist()  # Convert numpy arrays to lists for JSON serialization
    }
    
    # Save results to cache
    serializable_results = {
        key: value.tolist() if isinstance(value, np.ndarray) else value 
        for key, value in combined_results.items()
    }
    
    # Handle nested numpy arrays
    for key, value in serializable_results.items():
        if isinstance(value, dict):
            serializable_results[key] = {
                k: v.tolist() if isinstance(v, np.ndarray) else v
                for k, v in value.items()
            }
    
    # Write cache file to project directory
    try:
        with open(cache_file, 'w') as f:
            json.dump(serializable_results, f)
    except Exception as e:
        st.warning(f"Could not cache results: {str(e)}")
    
    return combined_results, output_video_path

def main():
    """Main Streamlit application."""
    st.set_page_config(
        page_title="Sports Performance Analyzer",
        page_icon="🏸",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    st.title("🏸 Badminton Performance Analyzer")
    
    # Sidebar for navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.radio("Go to", ["Upload & Process", "View Analysis", "About"])
    
    if page == "Upload & Process":
        st.header("Upload a Badminton Video")
        st.write("""
        Upload a video of a badminton match to analyze player movement and performance.
        The video should have a static camera position with a clear view of the court.
        """)
        
        # Video upload component
        video_path = upload_video()
        
        if video_path:
            st.session_state['video_path'] = video_path
            
            # Process button
            if st.button("Process Video"):
                try:
                    # Process video and run analysis
                    results, output_video_path = process_video_and_analyze(video_path)
                    
                    # Store results in session state
                    st.session_state['analysis_results'] = results
                    st.session_state['output_video_path'] = output_video_path
                    
                    st.success("Video processed successfully! Go to 'View Analysis' to see the results.")
                except Exception as e:
                    st.error(f"Error processing video: {str(e)}")
    
    elif page == "View Analysis":
        st.header("Analysis Results")
        
        if 'analysis_results' not in st.session_state:
            st.warning("No analysis results available. Please upload and process a video first.")
        else:
            # Show results
            results = st.session_state['analysis_results']
            output_video_path = st.session_state['output_video_path']
            
            # Display the processed video with overlays
            st.subheader("Processed Video with Player Tracking")
            play_video(output_video_path)
                
            # Display metrics and visualizations
            display_metrics(results)
            display_visualizations(results)
    
    elif page == "About":
        st.header("About the Sports Performance Analyzer")
        
        st.write("""
        ## How it Works
        
        This application analyzes badminton matches to provide insights into player performance:
        
        1. **Court Detection**: We identify the court corners using a deep learning model
        2. **Player Tracking**: We track players throughout the match using YOLO object detection
        3. **Perspective Transform**: We transform coordinates to get accurate player positions on the court
        4. **Movement Analysis**: We calculate speed, distance, and acceleration metrics
        5. **Position Analysis**: We analyze court coverage and positioning patterns
        
        ## Tips for Best Results
        
        - Use a static camera positioned at the side of the court
        - Ensure good lighting conditions
        - Avoid occlusions that block the view of the court or players
        - Record at least 1-2 minutes of gameplay for accurate analysis
        
        ## Technical Details
        
        - Court keypoint detection: ResNet50 model
        - Player detection: YOLOv8 model
        - Movement analysis: Time-series analysis of player positions
        - Court coverage: Spatial density analysis using heatmaps
        """)

if __name__ == "__main__":
    main()