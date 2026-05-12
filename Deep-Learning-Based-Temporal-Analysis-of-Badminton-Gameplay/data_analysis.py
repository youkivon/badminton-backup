import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.figure import Figure

def fig_to_numpy(fig):
    """
    Convert a matplotlib figure to a numpy array image.
    
    Args:
        fig: matplotlib figure
        
    Returns:
        np.ndarray: RGB image as numpy array
    """
    # Draw the figure to the canvas
    fig.canvas.draw()
    
    # Get width and height
    width, height = fig.canvas.get_width_height()
    
    # Get the RGB buffer directly from the renderer
    buffer = fig.canvas.renderer.buffer_rgba()
    
    # Convert to a numpy array with the right shape
    image = np.frombuffer(buffer, dtype=np.uint8)
    
    try:
        # Reshape based on actual dimensions
        return image.reshape(height, width, 4)[:,:,:3]  # Convert RGBA to RGB
    except ValueError as e:
        # Fall back to alternative method if reshape fails
        print(f"Warning: Reshape failed with error: {e}")
        print(f"Buffer size: {len(image)}, Expected size for shape ({height}, {width}, 4): {height * width * 4}")
        
        # Try getting the array directly from the figure
        return np.array(fig.canvas.renderer._renderer)[:,:,:3]  # Convert RGBA to RGB

def movement_analysis(transformed_players_dict, frame_rate=30):
    """
    Analyze player movement data to calculate speed, distance, and acceleration metrics.
    
    Args:
        transformed_players_dict (dict): A dictionary containing player positions over frames
        frame_rate (int): The frame rate of the video
        
    Returns:
        dict: Analysis results including metrics and visualization images
    """
    # Constants
    time_per_frame = 1 / frame_rate

    # Initialize dictionaries for metrics
    distance_traveled = {1: [], 2: []}
    speed = {1: [], 2: []}
    acceleration = {1: [], 2: []}

    # Calculate distances and speeds
    for i in range(1, len(transformed_players_dict)):
        if i+1 not in transformed_players_dict or i not in transformed_players_dict:
            continue
            
        frame_1 = transformed_players_dict[i]
        frame_2 = transformed_players_dict[i + 1]
        
        # Ensure we have at least two players in each frame
        if len(frame_1) < 2 or len(frame_2) < 2:
            continue
        
        for player in range(2):
            x1, y1 = frame_1[player]
            x2, y2 = frame_2[player]
            
            # Calculate distance using Euclidean formula
            dist = np.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
            distance_traveled[player + 1].append(dist)
            
            # Calculate speed (distance / time)
            speed_value = dist / time_per_frame
            speed[player + 1].append(speed_value)

    # Calculate acceleration
    for player in range(1, 3):
        if len(speed[player]) < 2:
            continue
            
        for i in range(1, len(speed[player])):
            accel = (speed[player][i] - speed[player][i - 1]) / time_per_frame
            acceleration[player].append(accel)

    # Function for moving average smoothing
    def moving_average(data, window_size=3):
        if not data or len(data) < window_size:
            return data
        return np.convolve(data, np.ones(window_size)/window_size, mode='valid')

    # Smooth the data using moving average
    window_size = min(3, min([len(speed[p]) for p in speed if len(speed[p]) > 0], default=1))
    
    smoothed_speed = {player: moving_average(speed[player], window_size) if len(speed[player]) >= window_size else speed[player] 
                     for player in range(1, 3) if len(speed[player]) > 0}
    
    smoothed_distance = {player: moving_average(distance_traveled[player], window_size) if len(distance_traveled[player]) >= window_size else distance_traveled[player]
                        for player in range(1, 3) if len(distance_traveled[player]) > 0}
    
    smoothed_acceleration = {player: moving_average(acceleration[player], window_size) if len(acceleration[player]) >= window_size else acceleration[player]
                           for player in range(1, 3) if len(acceleration[player]) > 0}

    # Average calculations
    average_speed = {player: np.mean(smoothed_speed[player]) if player in smoothed_speed and len(smoothed_speed[player]) > 0 else 0 
                   for player in range(1, 3)}
    
    total_distance = {player: np.sum(smoothed_distance[player]) if player in smoothed_distance and len(smoothed_distance[player]) > 0 else 0
                    for player in range(1, 3)}
    
    average_acceleration = {player: np.mean(smoothed_acceleration[player]) if player in smoothed_acceleration and len(smoothed_acceleration[player]) > 0 else 0
                         for player in range(1, 3)}

    # Generate visualization plots
    frames = list(range(1, len(transformed_players_dict) + 1))
    
    # Speed plot
    fig_speed = plt.figure(figsize=(10, 6))

    for player in smoothed_speed:
        player_frames = frames[1:len(smoothed_speed[player]) + 1]
        if len(player_frames) == len(smoothed_speed[player]):
            plt.plot(player_frames, smoothed_speed[player], 
                   label=f'Player {player} Speed', marker='o', 
                   linestyle='-', markersize=3)

    plt.title('Player Speed Over Time')
    plt.xlabel('Frame Number')
    plt.ylabel('Speed (cm/s)')
    plt.legend()
    plt.grid(True)

    speed_image = fig_to_numpy(fig_speed)
    plt.close(fig_speed)

    # Distance plot
    fig_distance = plt.figure(figsize=(10, 6))

    for player in smoothed_distance:
        player_frames = frames[1:len(smoothed_distance[player]) + 1]
        if len(player_frames) == len(smoothed_distance[player]):
            plt.plot(player_frames, smoothed_distance[player], 
                   label=f'Player {player} Distance', marker='o', 
                   linestyle='-', markersize=3)

    plt.title('Player Distance Over Time')
    plt.xlabel('Frame Number')
    plt.ylabel('Distance (cm)')
    plt.legend()
    plt.grid(True)

    distance_image = fig_to_numpy(fig_distance)
    plt.close(fig_distance)

    # Acceleration plot
    fig_accel = plt.figure(figsize=(10, 6))

    for player in smoothed_acceleration:
        player_frames = frames[2:len(smoothed_acceleration[player]) + 2]
        if len(player_frames) == len(smoothed_acceleration[player]):
            plt.plot(player_frames, smoothed_acceleration[player], 
                   label=f'Player {player} Acceleration', marker='o', 
                   linestyle='-', markersize=3)

    plt.title('Player Acceleration Over Time')
    plt.xlabel('Frame Number')
    plt.ylabel('Acceleration (cm/s²)')
    plt.legend()
    plt.grid(True)

    acceleration_image = fig_to_numpy(fig_accel)
    plt.close(fig_accel)

    return {
        'average_speed': average_speed,
        'total_distance': total_distance,
        'average_acceleration': average_acceleration,
        'speed_image': speed_image,
        'distance_image': distance_image,
        'acceleration_image': acceleration_image
    }

def position_analysis(transformed_players_dict):
    """
    Analyze player positioning and court coverage.
    
    Args:
        transformed_players_dict (dict): A dictionary containing player positions over frames
        
    Returns:
        dict: Position analysis results including coverage metrics and heatmaps
    """
    # Initialize storage for player positions
    far_player_positions = []
    near_player_positions = []
    
    # Court dimensions
    court_width = 610
    court_length = 1340
    court_area = court_width * court_length
    
    # Net position (y-coordinate)
    net_y_position = 670
    net_proximity_threshold = 50  # Distance to net to be considered "near net"
    
    # Collect player positions for all frames
    for frame_id, frame_data in transformed_players_dict.items():
        if len(frame_data) >= 2:
            far_player = frame_data[0]
            near_player = frame_data[1]
            
            far_player_positions.append(far_player)
            near_player_positions.append(near_player)
    
    # Convert to numpy arrays for easier processing
    far_player_positions = np.array(far_player_positions)
    near_player_positions = np.array(near_player_positions)
    
    # Create coverage maps (binary masks)
    far_coverage_map = np.zeros((court_width, court_length))
    near_coverage_map = np.zeros((court_width, court_length))
    
    # Count net proximity
    far_net_proximity_count = 0
    near_net_proximity_count = 0
    total_frames = len(transformed_players_dict)
    
    # Process positions for coverage and net proximity
    for frame_id, frame_data in transformed_players_dict.items():
        if len(frame_data) >= 2:
            far_x, far_y = frame_data[0]
            near_x, near_y = frame_data[1]
            
            # Mark coverage (ensure coordinates are in bounds)
            if 0 <= int(far_x) < court_width and 0 <= int(far_y) < court_length:
                far_coverage_map[int(far_x), int(far_y)] = 1
                
                # Check net proximity
                if abs(far_y - net_y_position) <= net_proximity_threshold:
                    far_net_proximity_count += 1
            
            if 0 <= int(near_x) < court_width and 0 <= int(near_y) < court_length:
                near_coverage_map[int(near_x), int(near_y)] = 1
                
                # Check net proximity
                if abs(near_y - net_y_position) <= net_proximity_threshold:
                    near_net_proximity_count += 1
    
    # Calculate coverage percentages
    far_coverage_percentage = (np.sum(far_coverage_map) / court_area) * 100
    near_coverage_percentage = (np.sum(near_coverage_map) / court_area) * 100
    
    # Calculate net proximity percentages
    far_net_proximity_percentage = (far_net_proximity_count / total_frames) * 100 if total_frames > 0 else 0
    near_net_proximity_percentage = (near_net_proximity_count / total_frames) * 100 if total_frames > 0 else 0
    
    # Create heatmaps
    fig = plt.figure(figsize=(12, 6))

    # Generate heatmap for far player
    ax1 = fig.add_subplot(1, 2, 1)
    if far_player_positions.size > 0:
        far_heatmap, xedges, yedges = np.histogram2d(
            far_player_positions[:, 0], far_player_positions[:, 1],
            bins=[range(0, court_width, 10), range(0, court_length, 10)]
        )
        sns.heatmap(far_heatmap.T, cmap='Blues', ax=ax1)
        ax1.set_title('Far Player Court Coverage')
        ax1.set_xlabel('X Position')
        ax1.set_ylabel('Y Position')
    else:
        ax1.text(0.5, 0.5, 'No data available', horizontalalignment='center', verticalalignment='center')
    
    # Generate heatmap for near player
    ax2 = fig.add_subplot(1, 2, 2)
    if near_player_positions.size > 0:
        near_heatmap, xedges, yedges = np.histogram2d(
            near_player_positions[:, 0], near_player_positions[:, 1],
            bins=[range(0, court_width, 10), range(0, court_length, 10)]
        )
        sns.heatmap(near_heatmap.T, cmap='Reds', ax=ax2)
        ax2.set_title('Near Player Court Coverage')
        ax2.set_xlabel('X Position')
        ax2.set_ylabel('Y Position')
    else:
        ax2.text(0.5, 0.5, 'No data available', horizontalalignment='center', verticalalignment='center')

    plt.tight_layout()

    # Convert figure to image
    heatmap_image = fig_to_numpy(fig)
    plt.close(fig)
    
    return {
        'far_coverage_percentage': far_coverage_percentage,
        'near_coverage_percentage': near_coverage_percentage,
        'far_net_proximity_percentage': far_net_proximity_percentage,
        'near_net_proximity_percentage': near_net_proximity_percentage,
        'heatmap_image': heatmap_image
    }