import subprocess
import time

print("Starting RTSP Server...")
subprocess.Popen(["python", "Server.py", "--port", "8554", "--video", "video.mp4"])

time.sleep(2)

print("Starting RTSP Client...")
subprocess.Popen(["python", "Client.py", "--server", "127.0.0.1",
                  "--rtsp-port", "8554", "--rtp-port", "25000", "--fps", "25"])
