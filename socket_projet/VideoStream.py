import cv2

class VideoStream:
    def __init__(self, filename, target_size=(1280,720), jpeg_quality=60):
        self.filename = filename
        self.cap = cv2.VideoCapture(self.filename)
        if not self.cap.isOpened():
            raise IOError(f"Cannot open video file {filename}")
        self.frameRate = self.cap.get(cv2.CAP_PROP_FPS) or 25.0
        self.frameCount = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.current_frame = 0
        self.target_size = target_size
        self.jpeg_quality = jpeg_quality

    def nextFrame(self):
        ret, frame = self.cap.read()
        if not ret:
            return None
        if self.target_size is not None:
            try:
                frame = cv2.resize(frame, self.target_size, interpolation=cv2.INTER_AREA)
            except Exception:
                pass
        self.current_frame += 1
        ret2, jpeg = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
        if not ret2:
            return None
        return (self.current_frame, jpeg.tobytes())

    def getFrameByIndex(self, index):
        if index < 1:
            index = 1
        if index > self.frameCount:
            return None
        try:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, index - 1)
            ret, frame = self.cap.read()
            if not ret:
                return None
            if self.target_size is not None:
                try:
                    frame = cv2.resize(frame, self.target_size, interpolation=cv2.INTER_AREA)
                except Exception:
                    pass
            self.current_frame = index
            ret2, jpeg = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
            if not ret2:
                return None
            return (self.current_frame, jpeg.tobytes())
        except Exception as e:
            print("[VideoStream] getFrameByIndex error:", e)
            return None

    def frameRateMs(self):
        return 1.0 / self.frameRate

    def restart(self):
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        self.current_frame = 0

    def release(self):
        self.cap.release()

    def seek_to_seconds(self, seconds):
        if seconds < 0:
            seconds = 0.0
        target_frame = int(seconds * self.frameRate)
        if target_frame >= self.frameCount:
            target_frame = max(0, self.frameCount - 1)
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        self.current_frame = target_frame + 1

    def seek_by_seconds(self, delta_seconds):
        current_sec = max(0.0, (self.current_frame - 1) / self.frameRate)
        self.seek_to_seconds(current_sec + delta_seconds)

    def current_time(self):
        return max(0.0, (self.current_frame - 1) / self.frameRate)
