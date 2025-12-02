# VideoStream.py — forward-only MJPEG reader
class VideoStream:
    def __init__(self, filename):
        self.filename = filename
        self.file = open(filename, 'rb')
        self.frameNum = 0
        self.fps = 25.0

    def nextFrame(self):
        header = self.file.read(5)
        if not header:
            return None
        try:
            frame_len = int(header)
        except:
            try:
                frame_len = int(header.decode().strip())
            except:
                return None

        frame = self.file.read(frame_len)
        if not frame:
            return None

        self.frameNum += 1
        return (self.frameNum, frame)

    def frameNbr(self):
        return self.frameNum

    def seek_to_frame(self, n):
        if n < 0: n = 0
        try: self.file.close()
        except: pass
        self.file = open(self.filename, 'rb')
        self.frameNum = 0
        for _ in range(int(n)):
            if not self.nextFrame():
                break

    def seek_to_seconds(self, s):
        if s < 0: s = 0
        self.seek_to_frame(int(s * self.fps))

    def seek_by_seconds(self, d):
        cur = self.frameNum / self.fps
        self.seek_to_seconds(cur + d)

    def current_time(self):
        return self.frameNum / self.fps

    def release(self):
        try: self.file.close()
        except: pass
