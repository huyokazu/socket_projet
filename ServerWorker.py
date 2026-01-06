# ServerWorker.py
import threading, socket, time
from random import randint
from VideoStream import VideoStream
from RtpPacket import RtpPacket


class ServerWorker:

    SETUP = 'SETUP'
    PLAY = 'PLAY'
    PAUSE = 'PAUSE'
    TEARDOWN = 'TEARDOWN'
    SET_SPEED = 'SET_SPEED'
    SEEK = 'SEEK'

    INIT = 0
    READY = 1
    PLAYING = 2

    OK_200 = 0
    FILE_NOT_FOUND_404 = 1
    CON_ERR_500 = 2

    def __init__(self, clientInfo, videoFile=None):
        self.clientInfo = clientInfo
        self.state = self.INIT
        self.seqnum = 0
        self.play_speed = 1.0             # only positive speed now
        self.base_delay = 0.04
        self.paused_at_edge = False       # for EOF/BOF pause

    def run(self):
        threading.Thread(target=self.recvRtspRequest, daemon=True).start()

    def recvRtspRequest(self):
        conn = self.clientInfo['rtspSocket'][0]
        while True:
            try:
                data = conn.recv(4096)
            except:
                break
            if data:
                try:
                    self.processRtspRequest(data.decode())
                except:
                    pass

    def processRtspRequest(self, data):
        lines = data.split('\n')
        if len(lines) < 1:
            return
        request = lines[0].split(' ')
        requestType = request[0]
        filename = request[1]

        seq = "0"
        try:
            seq = lines[1].split(' ')[1]
        except:
            pass

        headers = {}
        for ln in lines:
            if ":" in ln:
                k, v = ln.split(":", 1)
                headers[k.strip()] = v.strip()

        # ---------- SETUP ----------
        if requestType == self.SETUP:
            if self.state == self.INIT:
                try:
                    self.clientInfo['videoStream'] = VideoStream(filename)
                except:
                    self.replyRtsp(self.FILE_NOT_FOUND_404, seq)
                    return

                self.state = self.READY
                self.clientInfo['session'] = randint(100000, 999999)

                # parse client RTP port
                transport = headers.get("Transport", "")
                if "client_port" in transport:
                    try:
                        p = transport.split("client_port=")[1]
                        self.clientInfo["rtpPort"] = int(p.split("-")[0])
                    except:
                        self.clientInfo["rtpPort"] = 25000

                self.replyRtsp(self.OK_200, seq)
            

        # ---------- PLAY ----------
        elif requestType == self.PLAY:
            if self.state == self.READY:
                self.state = self.PLAYING
                self.clientInfo['event'] = threading.Event()

                try:
                    self.clientInfo['rtpSocket'] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                except:
                    pass

                self.clientInfo['worker'] = threading.Thread(target=self.sendRtp, daemon=True)
                self.clientInfo['worker'].start()

                self.replyRtsp(self.OK_200, seq)

        # ---------- PAUSE ----------
        elif requestType == self.PAUSE:
            if self.state == self.PLAYING:
                self.state = self.READY
                ev = self.clientInfo.get("event", None)
                if ev:
                    ev.set()
                self.replyRtsp(self.OK_200, seq)

        # ---------- TEARDOWN ----------
        elif requestType == self.TEARDOWN:
            ev = self.clientInfo.get("event", None)
            if ev:
                ev.set()
            try:
                self.clientInfo["rtpSocket"].close()
            except:
                pass
            self.replyRtsp(self.OK_200, seq)

        # ---------- SET_SPEED (NO REVERSE) ----------
        elif requestType == self.SET_SPEED:
            if "Speed" in headers:
                try:
                    s = float(headers["Speed"])
                except:
                    s = None
                if s and s > 0:      # only positive speeds allowed
                    self.play_speed = s
                    self.replyRtsp(self.OK_200, seq)
                else:
                    self.replyRtsp(self.CON_ERR_500, seq)

        # ---------- SEEK +5s / -5s ----------
        elif requestType == self.SEEK:
            vs = self.clientInfo.get('videoStream', None)
            if not vs:
                self.replyRtsp(self.CON_ERR_500, seq)
                return

            try:
                if "Position-Relative" in headers:
                    delta = float(headers["Position-Relative"])
                    vs.seek_by_seconds(delta)
                elif "Position" in headers:
                    target = float(headers["Position"])
                    vs.seek_to_seconds(target)
                else:
                    self.replyRtsp(self.CON_ERR_500, seq)
                    return
            except:
                self.replyRtsp(self.CON_ERR_500, seq); return

            # clear pause due to EOF
            self.paused_at_edge = False
            self.clientInfo["event"] = threading.Event()

            # ensure worker is running if in PLAYING
            if self.state == self.PLAYING:
                th = self.clientInfo.get("worker", None)
                if (not th) or (not th.is_alive()):
                    self.clientInfo['worker'] = threading.Thread(target=self.sendRtp, daemon=True)
                    self.clientInfo['worker'].start()

            self.replyRtsp(self.OK_200, seq)

        else:
            self.replyRtsp(self.CON_ERR_500, seq)

    # ========== RTP SEND LOOP ==========
    def sendRtp(self):
        vs = self.clientInfo.get('videoStream', None)
        if not vs:
            return

        while True:

            ev = self.clientInfo.get("event", None)

            timeout = self.base_delay / self.play_speed
            if timeout < 0.001: timeout = 0.001

            if ev:
                if ev.wait(timeout=timeout):
                    break
            else:
                time.sleep(timeout)

            if self.paused_at_edge:
                time.sleep(0.05)
                continue

            # always forward only
            frame_info = vs.nextFrame()

            if not frame_info:
                # hit EOF
                self.paused_at_edge = True
                continue

            frameNo, jpgBytes = frame_info

            # chunk + send
            MTU = 1400
            offset = 0
            total = len(jpgBytes)

            while offset < total:
                chunk = jpgBytes[offset:offset+MTU]
                offset += MTU
                marker = 1 if offset >= total else 0

                try:
                    self.seqnum = (self.seqnum + 1) % 65536
                    pkt = RtpPacket()
                    # encode(version, padding, extension, cc, seqnum, marker, pt, timestamp, ssrc, payload)
                    # put frameNo into timestamp field so client can compute progress
                    pkt.encode(2, 0, 0, 0, self.seqnum, marker, 26, frameNo, 0, chunk)
                    data = pkt.getPacket()

                    addr = self.clientInfo["rtspSocket"][1][0]
                    port = int(self.clientInfo["rtpPort"])

                    self.clientInfo["rtpSocket"].sendto(data, (addr, port))

                except:
                    if ev: ev.set()
                    break

                time.sleep(0.001)

    # ========== RTSP RESPONSE ==========
    def replyRtsp(self, code, seq):
        conn = self.clientInfo["rtspSocket"][0]

        if code == self.OK_200:
            vs = self.clientInfo.get('videoStream', None)
            total = vs.total_frames if (vs and hasattr(vs, 'total_frames')) else 0
            reply = (
                f"RTSP/1.0 200 OK\n"
                f"CSeq: {seq}\n"
                f"Session: {self.clientInfo.get('session',0)}\n"
                f"Total-Frames: {total}\n"
            )
        elif code == self.FILE_NOT_FOUND_404:
            reply = f"RTSP/1.0 404 NOT FOUND\nCSeq: {seq}\n"
        else:
            reply = f"RTSP/1.0 500 ERROR\nCSeq: {seq}\n"

        try:
            conn.send(reply.encode())
        except:
            pass
