class VideoStream:
    def __init__(self, filename):
        self.filename = filename
        self.file = open(filename, 'rb')
        self.fps = 25.0
        self.frameNum = 0

        # ==== Đếm tổng số frame ====
        self.total_frames = 0
        while True:
            header = self.file.read(5)
            if not header:
                break
            try:
                frame_len = int(header)
            except:
                break

            self.file.read(frame_len)
            self.total_frames += 1

        # Mở lại file cho playback
        self.file.close()
        self.file = open(filename, 'rb')
        self.frameNum = 0

    def nextFrame(self):
        header = self.file.read(5)
        if not header:
            return None

        try:
            frame_len = int(header)
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
        self.file.close()
        self.file = open(self.filename, 'rb')
        self.frameNum = 0

        for _ in range(int(n)):
            if not self.nextFrame():
                break

    def seek_to_seconds(self, s):
        frame = int(s * self.fps)
        self.seek_to_frame(frame)

    def seek_by_seconds(self, d):
        cur = self.frameNum / self.fps
        self.seek_to_seconds(cur + d)
