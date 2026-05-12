import streamlit as st
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image

def display_metrics(analysis_results):
    """
    Display movement and position metrics.
    
    Args:
        analysis_results (dict): Results from the movement and position analysis
    """
    st.subheader("Player Performance Metrics")
    
    # Create columns for layout
    col1, col2 = st.columns(2)
    
    with col1:
        st.write("### Movement Analysis")
        
        # Speed metrics
        avg_speed = analysis_results.get('average_speed', {})
        if avg_speed:
            st.write("**Average Speed (cm/s):**")
            player1_speed = avg_speed.get(1, 0)
            player2_speed = avg_speed.get(2, 0)
            
            data = {
                'Player': ['Near Player (Blue)', 'Far Player (Red)'],
                'Average Speed (cm/s)': [player1_speed, player2_speed]
            }
            
            st.dataframe(pd.DataFrame(data))
        
        # Distance metrics
        total_distance = analysis_results.get('total_distance', {})
        if total_distance:
            st.write("**Total Distance (cm):**")
            player1_distance = total_distance.get(1, 0)
            player2_distance = total_distance.get(2, 0)
            
            data = {
                'Player': ['Near Player (Blue)', 'Far Player (Red)'],
                'Total Distance (cm)': [player1_distance, player2_distance]
            }
            
            st.dataframe(pd.DataFrame(data))
        
        # Acceleration metrics
        avg_accel = analysis_results.get('average_acceleration', {})
        if avg_accel:
            st.write("**Average Acceleration (cm/s²):**")
            player1_accel = avg_accel.get(1, 0)
            player2_accel = avg_accel.get(2, 0)
            
            data = {
                'Player': ['Near Player (Blue)', 'Far Player (Red)'],
                'Average Acceleration (cm/s²)': [player1_accel, player2_accel]
            }
            
            st.dataframe(pd.DataFrame(data))
    
    with col2:
        st.write("### Court Positioning")
        
        # Court coverage metrics
        far_coverage = analysis_results.get('far_coverage_percentage', 0)
        near_coverage = analysis_results.get('near_coverage_percentage', 0)
        
        st.write("**Court Coverage (% of court area):**")
        data = {
            'Player': ['Near Player (Blue)', 'Far Player (Red)'],
            'Court Coverage (%)': [near_coverage, far_coverage]
        }
        
        st.dataframe(pd.DataFrame(data))
        
        # Net proximity metrics
        far_net_proximity = analysis_results.get('far_net_proximity_percentage', 0)
        near_net_proximity = analysis_results.get('near_net_proximity_percentage', 0)
        
        st.write("**Net Proximity (% of time near net):**")
        data = {
            'Player': ['Near Player (Blue)', 'Far Player (Red)'],
            'Net Proximity (%)': [near_net_proximity, far_net_proximity]
        }
        
        st.dataframe(pd.DataFrame(data))
        
    # Camera parameters
    st.write("### Camera Parameters")
    
    height_of_camera = analysis_results.get('height_of_camera', 'N/A')
    angle_of_camera = analysis_results.get('angle_of_camera', 'N/A')
    distance_of_camera = analysis_results.get('distance_of_camera', 'N/A')
    
    camera_data = {
        'Parameter': ['Height Above Ground (cm)', 'Angle of Inclination (degrees)', 'Distance from Court Edge (cm)'],
        'Value': [height_of_camera, angle_of_camera, distance_of_camera]
    }
    
    st.dataframe(pd.DataFrame(camera_data))

def display_visualizations(analysis_results):
    """
    Display visualization images from the analysis.
    
    Args:
        analysis_results (dict): Results containing visualization images
    """
    st.subheader("Performance Visualizations")
    
    # Create tabs for different visualizations
    tabs = st.tabs(["Speed Analysis", "Distance Analysis", "Acceleration Analysis", "Court Coverage"])
    
    # Speed visualization
    with tabs[0]:
        speed_image = analysis_results.get('speed_image')
        if speed_image is not None:
            st.image(speed_image, caption="Player Speed Analysis", use_container_width=True)
        else:
            st.error("Speed visualization not available")
    
    # Distance visualization
    with tabs[1]:
        distance_image = analysis_results.get('distance_image')
        if distance_image is not None:
            st.image(distance_image, caption="Player Distance Analysis", use_container_width=True)
        else:
            st.error("Distance visualization not available")
    
    # Acceleration visualization
    with tabs[2]:
        acceleration_image = analysis_results.get('acceleration_image')
        if acceleration_image is not None:
            st.image(acceleration_image, caption="Player Acceleration Analysis", use_container_width=True)
        else:
            st.error("Acceleration visualization not available")
    
    # Heatmap visualization
    with tabs[3]:
        heatmap_image = analysis_results.get('heatmap_image', analysis_results.get('far_heatmap'))
        if heatmap_image is not None:
            st.image(heatmap_image, caption="Court Coverage Heatmap", use_container_width=True)
        else:
            st.error("Court coverage heatmap not available")