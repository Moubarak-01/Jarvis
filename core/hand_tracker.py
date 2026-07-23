import math
import mediapipe as mp
import pyautogui

class HandTracker:
    def __init__(self, smoothing=0.4, pinch_threshold=0.04):
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision
        import os
        model_path = os.path.join(os.path.dirname(__file__), 'hand_landmarker.task')
        
        base_options = python.BaseOptions(model_asset_path=model_path)
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            num_hands=1,
            min_hand_detection_confidence=0.7,
            min_hand_presence_confidence=0.7,
            min_tracking_confidence=0.7,
        )
        self.landmarker = vision.HandLandmarker.create_from_options(options)
        
        self.screen_w, self.screen_h = pyautogui.size()
        
        # Smoothing settings
        self.smoothing = smoothing
        self.prev_x, self.prev_y = 0, 0
        
        # Pinch states
        self.pinch_threshold = pinch_threshold
        self.is_left_clicking = False
        self.is_right_clicking = False
        self.is_double_clicking = False
        
        # Swipe tracking
        import collections
        import time
        self.history = collections.deque(maxlen=15)
        self.last_swipe_time = 0
        
        # Disable pyautogui fail-safe (corner movement abort) to prevent crashes if hands move wildly
        pyautogui.FAILSAFE = False

    def process_frame(self, rgb_frame):
        """
        Process an RGB frame to find hand landmarks and control the mouse.
        Draws landmarks on rgb_frame in place and returns it.
        """
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        results = self.landmarker.detect(mp_image)
        
        if results.hand_landmarks:
            # We only care about the first hand detected
            hand_landmarks = results.hand_landmarks[0]
            
            # Draw landmarks manually since drawing_utils is missing
            import cv2
            h, w, ch = rgb_frame.shape
            for landmark in hand_landmarks:
                cx, cy = int(landmark.x * w), int(landmark.y * h)
                cv2.circle(rgb_frame, (cx, cy), 5, (0, 255, 0), -1)
            
            lm = hand_landmarks
            
            # Check finger extension (True if extended)
            # Tips: 4, 8, 12, 16, 20
            # PIP/MCP for comparison
            index_extended = lm[8].y < lm[6].y
            middle_extended = lm[12].y < lm[10].y
            ring_extended = lm[16].y < lm[14].y
            pinky_extended = lm[20].y < lm[18].y
            
            # Thumb check
            thumb_extended = lm[4].x < lm[3].x if lm[5].x > lm[17].x else lm[4].x > lm[3].x
            
            gesture = "None"
            
            if index_extended and middle_extended and ring_extended and pinky_extended:
                gesture = "Open Palm"
            elif not index_extended and not middle_extended and not ring_extended and not pinky_extended:
                gesture = "Closed Fist"
            elif index_extended and not middle_extended and not ring_extended and not pinky_extended:
                # Directional Pointing Logic
                tip = lm[8]
                mcp = lm[5]
                dx = tip.x - mcp.x
                dy = tip.y - mcp.y
                if abs(dy) > abs(dx):
                    gesture = "Point Up" if dy < 0 else "Point Down"
                else:
                    gesture = "Point Right" if dx > 0 else "Point Left"
            elif index_extended and middle_extended and not ring_extended and not pinky_extended:
                gesture = "Peace Sign"
                
            # Pinch checks (Thumb tip to other tips)
            pinch_dist_index = math.hypot(lm[4].x - lm[8].x, lm[4].y - lm[8].y)
            pinch_dist_middle = math.hypot(lm[4].x - lm[12].x, lm[4].y - lm[12].y)
            pinch_dist_ring = math.hypot(lm[4].x - lm[16].x, lm[4].y - lm[16].y)
            
            if pinch_dist_index < self.pinch_threshold:
                gesture = "Left Pinching"
            elif pinch_dist_middle < self.pinch_threshold:
                gesture = "Right Pinching"
            elif pinch_dist_ring < self.pinch_threshold:
                gesture = "Double Pinching"
                
            # Improve pointing accuracy by using a smaller interaction box
            margin = 0.20
            # Normalize x and y within the inner 60% of the frame
            # Use Middle Finger MCP (lm[9]) for stable tracking
            effective_x = (lm[9].x - margin) / (1.0 - 2 * margin)
            effective_y = (lm[9].y - margin) / (1.0 - 2 * margin)
            
            raw_x = effective_x * self.screen_w
            raw_y = effective_y * self.screen_h
            
            raw_x = max(0, min(self.screen_w, raw_x))
            raw_y = max(0, min(self.screen_h, raw_y))
            
            if self.prev_x == 0 and self.prev_y == 0:
                self.prev_x, self.prev_y = raw_x, raw_y
            
            smooth_x = self.prev_x + (raw_x - self.prev_x) * (1.0 - self.smoothing)
            smooth_y = self.prev_y + (raw_y - self.prev_y) * (1.0 - self.smoothing)
            self.prev_x, self.prev_y = smooth_x, smooth_y
            
            # Move mouse if pointing or pinching (to allow dragging)
            if gesture in ["Point Up", "Open Palm", "Double Pinching", "Right Pinching", "Left Pinching", "Closed Fist"] or index_extended:
                pyautogui.moveTo(int(smooth_x), int(smooth_y), _pause=False)
                
            # --- Swipe Logic ---
            import time
            current_time = time.time()
            self.history.append((lm[9].x, lm[9].y, current_time))
            
            # Check for swipe if hand is open and cooldown has passed
            if gesture == "Open Palm" and (current_time - self.last_swipe_time) > 1.0:
                if len(self.history) == self.history.maxlen:
                    old_x, old_y, _ = self.history[0]
                    curr_x, curr_y, _ = self.history[-1]
                    
                    dx = curr_x - old_x
                    dy = curr_y - old_y
                    
                    velocity_x = dx
                    velocity_y = dy
                    
                    swipe_threshold = 0.15 # 15% of the frame
                    
                    if abs(velocity_x) > swipe_threshold or abs(velocity_y) > swipe_threshold:
                        if abs(velocity_x) > abs(velocity_y):
                            # Horizontal Swipe
                            if velocity_x > swipe_threshold:
                                # Swipe Right
                                pyautogui.hotkey('ctrl', 'win', 'right')
                            elif velocity_x < -swipe_threshold:
                                # Swipe Left
                                pyautogui.hotkey('ctrl', 'win', 'left')
                        else:
                            # Vertical Swipe
                            if velocity_y > swipe_threshold:
                                # Swipe Down
                                pyautogui.hotkey('win', 'd')
                            elif velocity_y < -swipe_threshold:
                                # Swipe Up
                                pyautogui.hotkey('win', 'tab')
                        
                        self.last_swipe_time = current_time
                        self.history.clear()
            # -------------------
            
            # Left Click & Drag logic (Fist or Index Pinch)
            if gesture in ["Left Pinching", "Closed Fist"]:
                if not self.is_left_clicking:
                    pyautogui.mouseDown(button='left', _pause=False)
                    self.is_left_clicking = True
            else:
                if self.is_left_clicking:
                    pyautogui.mouseUp(button='left', _pause=False)
                    self.is_left_clicking = False
                    
            # Right Click logic
            if gesture == "Right Pinching":
                if not self.is_right_clicking:
                    pyautogui.click(button='right', _pause=False)
                    self.is_right_clicking = True
            else:
                self.is_right_clicking = False
                
            # Double Click logic
            if gesture == "Double Pinching":
                if not self.is_double_clicking:
                    pyautogui.doubleClick(_pause=False)
                    self.is_double_clicking = True
            else:
                self.is_double_clicking = False

        return rgb_frame

    def close(self):
        self.landmarker.close()
