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

    def frameRateMs(self):
        return 1.0 / self.frameRate

    def restart(self):
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        self.current_frame = 0

    def release(self):
        self.cap.release()
