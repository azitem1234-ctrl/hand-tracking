import cv2
import mediapipe as mp
import numpy as np
import math
import time

# ── Try to import optional libs ──────────────────────────────────────────────
try:
    import pyautogui
    MOUSE_AVAILABLE = True
    pyautogui.FAILSAFE = False
except ImportError:
    MOUSE_AVAILABLE = False

try:
    from ctypes import cast, POINTER
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    volume_ctrl = cast(interface, POINTER(IAudioEndpointVolume))
    vol_range = volume_ctrl.GetVolumeRange()
    MIN_VOL, MAX_VOL = vol_range[0], vol_range[1]
    VOLUME_AVAILABLE = True
except Exception:
    VOLUME_AVAILABLE = False

# ── MediaPipe setup ───────────────────────────────────────────────────────────
mp_hands = mp.solutions.hands
mp_draw  = mp.solutions.drawing_utils
mp_style = mp.solutions.drawing_styles
hands    = mp_hands.Hands(max_num_hands=1,
                          min_detection_confidence=0.7,
                          min_tracking_confidence=0.6)

# ── Constants ─────────────────────────────────────────────────────────────────
MODES        = ["MOUSE", "VOLUME", "DRAW", "GESTURE"]
MODE_KEYS    = {ord('1'): 0, ord('2'): 1, ord('3'): 2, ord('4'): 3}
MODE_COLORS  = [(0,200,255), (0,255,150), (255,100,200), (255,200,0)]
MODE_ICONS   = ["🖱 MOUSE", "🔊 VOLUME", "✏ DRAW", "✌ GESTURE"]

TIP_IDS      = [4, 8, 12, 16, 20]   # thumb, index, middle, ring, pinky

# ── State ─────────────────────────────────────────────────────────────────────
mode         = 0
draw_canvas  = None
prev_draw_x  = None
prev_draw_y  = None
draw_color   = (0, 100, 255)
draw_colors  = [(0,100,255),(0,255,100),(255,50,50),(255,200,0),(200,0,255)]
color_idx    = 0
draw_thick   = 6
smoothX      = smoothY = 0
pTime        = 0
gesture_text = ""
gesture_time = 0
vol_bar_val  = 0
vol_percent  = 0

# ── Helper: distance between two landmarks ────────────────────────────────────
def dist(lm, i, j, w, h):
    x1,y1 = int(lm[i].x*w), int(lm[i].y*h)
    x2,y2 = int(lm[j].x*w), int(lm[j].y*h)
    return math.hypot(x2-x1, y2-y1), (x1,y1), (x2,y2)

# ── Helper: which fingers are up ─────────────────────────────────────────────
def fingers_up(lm):
    fingers = []
    # Thumb (compare x)
    fingers.append(1 if lm[4].x < lm[3].x else 0)
    # Other four fingers
    for tip in [8,12,16,20]:
        fingers.append(1 if lm[tip].y < lm[tip-2].y else 0)
    return fingers

# ── Gesture recognition ───────────────────────────────────────────────────────
def recognize_gesture(lm):
    f = fingers_up(lm)
    d_thumb_index,_,_ = dist(lm, 4, 8, 1, 1)

    if f == [0,0,0,0,0]:           return "✊  FIST"
    if f == [1,1,1,1,1]:           return "🖐  OPEN HAND"
    if f == [0,1,0,0,0]:           return "☝  POINTING"
    if f == [0,1,1,0,0]:           return "✌  PEACE"
    if f == [1,0,0,0,0]:           return "👍  THUMBS UP"
    if f == [0,1,1,1,1]:           return "🤟  FOUR FINGERS"
    if f == [1,1,0,0,1]:           return "🤘  ROCK ON"
    if f == [0,0,0,0,1]:           return "🤙  PINKY"
    if d_thumb_index < 0.07:       return "👌  OK / PINCH"
    return ""

# ── Draw HUD ──────────────────────────────────────────────────────────────────
def draw_hud(img, fps):
    h, w = img.shape[:2]

    # Top bar background
    cv2.rectangle(img, (0,0), (w, 52), (20,20,20), -1)
    cv2.rectangle(img, (0,52), (w, 54), MODE_COLORS[mode], -1)

    # Mode tabs
    tab_w = w // len(MODES)
    for i, label in enumerate(["1:MOUSE","2:VOLUME","3:DRAW","4:GESTURE"]):
        x = i * tab_w
        if i == mode:
            cv2.rectangle(img, (x,0), (x+tab_w, 52), MODE_COLORS[i], -1)
            cv2.putText(img, label, (x+8, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0,0,0), 2)
        else:
            cv2.putText(img, label, (x+8, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (120,120,120), 1)

    # FPS
    cv2.putText(img, f"FPS:{int(fps)}", (w-80, h-12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180,180,180), 1)

# ── Main ──────────────────────────────────────────────────────────────────────
cap = cv2.VideoCapture(0)
cam_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
cam_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

draw_canvas = np.zeros((cam_h, cam_w, 3), np.uint8)

print("=" * 50)
print("  HAND TRACKING — ALL IN ONE")
print("  Keys: 1=Mouse  2=Volume  3=Draw  4=Gesture")
print("  Draw mode: C=change color  E=erase  Q=quit")
print("=" * 50)
if not MOUSE_AVAILABLE:
    print("  ⚠  pyautogui not installed — Mouse mode disabled")
    print("     Run: pip install pyautogui")
if not VOLUME_AVAILABLE:
    print("  ⚠  pycaw not installed — Volume mode disabled")
    print("     Run: pip install pycaw comtypes")
print()

import pygetwindow  # just for screen size fallback
SCREEN_W, SCREEN_H = 1920, 1080
try:
    import pyautogui as _pag
    SCREEN_W, SCREEN_H = _pag.size()
except Exception:
    pass

while cap.isOpened():
    ok, frame = cap.read()
    if not ok:
        break

    frame = cv2.flip(frame, 1)
    h, w = frame.shape[:2]
    rgb   = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    res   = hands.process(rgb)

    # FPS
    cTime = time.time()
    fps   = 1 / (cTime - pTime + 1e-9)
    pTime = cTime

    lm_list = []
    if res.multi_hand_landmarks:
        for hl in res.multi_hand_landmarks:
            mp_draw.draw_landmarks(frame, hl,
                mp_hands.HAND_CONNECTIONS,
                mp_style.get_default_hand_landmarks_style(),
                mp_style.get_default_hand_connections_style())
            lm_list = hl.landmark

    # ── MODE 0: MOUSE ──────────────────────────────────────────────────────
    if mode == 0:
        if not MOUSE_AVAILABLE:
            cv2.putText(frame, "Install pyautogui to enable mouse control",
                        (20, h//2), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,100,255), 2)
        elif lm_list:
            f = fingers_up(lm_list)
            ix = int(lm_list[8].x * w)
            iy = int(lm_list[8].y * h)

            # Map camera -> screen (use inner 80% of frame to avoid edge jitter)
            mx = np.interp(ix, [int(w*0.1), int(w*0.9)], [0, SCREEN_W])
            my = np.interp(iy, [int(h*0.1), int(h*0.9)], [0, SCREEN_H])

            # Smooth
            smoothX = smoothX + (mx - smoothX) / 5
            smoothY = smoothY + (my - smoothY) / 5

            if f[1] and not f[2]:          # index only → move
                pyautogui.moveTo(int(smoothX), int(smoothY))
                cv2.circle(frame, (ix,iy), 12, (0,200,255), cv2.FILLED)
                cv2.putText(frame, "MOVE", (20, h-20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,200,255), 2)

            if f[1] and f[2]:              # index+middle → click check
                d,p1,p2 = dist(lm_list, 8, 12, w, h)
                cv2.line(frame, p1, p2, (0,255,150), 2)
                if d < 35:
                    pyautogui.click()
                    cv2.putText(frame, "CLICK!", (20, h-20),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0,255,150), 2)

    # ── MODE 1: VOLUME ─────────────────────────────────────────────────────
    elif mode == 1:
        if not VOLUME_AVAILABLE:
            cv2.putText(frame, "Install pycaw to enable volume control",
                        (20, h//2), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,150), 2)
        elif lm_list:
            d, p1, p2 = dist(lm_list, 4, 8, w, h)
            cx,cy = (p1[0]+p2[0])//2, (p1[1]+p2[1])//2

            cv2.line(frame,  p1, p2, (0,255,150), 3)
            cv2.circle(frame, p1, 10, (0,255,150), cv2.FILLED)
            cv2.circle(frame, p2, 10, (0,255,150), cv2.FILLED)
            cv2.circle(frame, (cx,cy), 8, (255,255,255), cv2.FILLED)

            vol = np.interp(d, [20, 200], [MIN_VOL, MAX_VOL])
            vol_bar_val = np.interp(d, [20, 200], [h-80, 120])
            vol_percent = np.interp(d, [20, 200], [0, 100])
            volume_ctrl.SetMasterVolumeLevel(vol, None)

            # Volume bar
            cv2.rectangle(frame, (50, 120), (85, h-80), (50,50,50), cv2.FILLED)
            cv2.rectangle(frame, (50, int(vol_bar_val)), (85, h-80),
                          (0,255,150), cv2.FILLED)
            cv2.putText(frame, f"{int(vol_percent)}%", (38, h-55),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,150), 2)

    # ── MODE 2: DRAW ───────────────────────────────────────────────────────
    elif mode == 2:
        if lm_list:
            f = fingers_up(lm_list)
            ix = int(lm_list[8].x * w)
            iy = int(lm_list[8].y * h)

            if f[1] and not f[2] and not f[0]:   # only index → draw
                if prev_draw_x is None:
                    prev_draw_x, prev_draw_y = ix, iy
                cv2.line(draw_canvas, (prev_draw_x, prev_draw_y),
                         (ix, iy), draw_color, draw_thick)
                prev_draw_x, prev_draw_y = ix, iy
                cv2.circle(frame, (ix,iy), draw_thick//2+2,
                           draw_color, cv2.FILLED)
            else:
                prev_draw_x = prev_draw_y = None

        # Blend canvas onto frame
        gray = cv2.cvtColor(draw_canvas, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(gray, 10, 255, cv2.THRESH_BINARY)
        frame[mask > 0] = draw_canvas[mask > 0]

        # Color swatches
        for i, c in enumerate(draw_colors):
            bx = 20 + i*45
            cv2.rectangle(frame, (bx, h-45), (bx+35, h-10), c, -1)
            if i == color_idx:
                cv2.rectangle(frame, (bx-2, h-47), (bx+37, h-8),
                              (255,255,255), 2)

        cv2.putText(frame, "Index=draw  C=color  E=erase",
                    (20, h-55), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200,200,200), 1)

    # ── MODE 3: GESTURE ────────────────────────────────────────────────────
    elif mode == 3:
        if lm_list:
            g = recognize_gesture(lm_list)
            if g:
                gesture_text = g
                gesture_time = time.time()

        if gesture_text and (time.time() - gesture_time < 2):
            # Big centered text
            (tw, th), _ = cv2.getTextSize(gesture_text,
                          cv2.FONT_HERSHEY_SIMPLEX, 1.4, 3)
            tx = (w - tw) // 2
            ty = h // 2 + 20
            cv2.putText(frame, gesture_text, (tx+2, ty+2),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0,0,0), 4)
            cv2.putText(frame, gesture_text, (tx, ty),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.4,
                        MODE_COLORS[3], 3)

        # Finger status bar
        if lm_list:
            f = fingers_up(lm_list)
            names = ["Thumb","Index","Middle","Ring","Pinky"]
            for i,(up,name) in enumerate(zip(f,names)):
                col = (0,255,150) if up else (60,60,60)
                cv2.rectangle(frame, (20+i*70, h-45),
                              (80+i*70, h-10), col, -1)
                cv2.putText(frame, name[:3], (25+i*70, h-18),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0,0,0), 1)

    # ── HUD ────────────────────────────────────────────────────────────────
    draw_hud(frame, fps)

    cv2.imshow("Hand Tracking — All In One", frame)

    key = cv2.waitKey(1) & 0xFF
    if key == ord('q'):
        break
    elif key in MODE_KEYS:
        mode = MODE_KEYS[key]
        prev_draw_x = prev_draw_y = None
    elif key == ord('c') and mode == 2:
        color_idx = (color_idx + 1) % len(draw_colors)
        draw_color = draw_colors[color_idx]
    elif key == ord('e') and mode == 2:
        draw_canvas = np.zeros((cam_h, cam_w, 3), np.uint8)

cap.release()
cv2.destroyAllWindows()
