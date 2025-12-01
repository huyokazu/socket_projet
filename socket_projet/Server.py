import socket
import threading
import random
import time
import argparse
from RtpPacket import RtpPacket
from VideoStream import VideoStream

RTSP_PORT = 8554

class ServerWorker(threading.Thread):
    INIT = 0
    READY = 1
    PLAYING = 2

    def __init__(self, clientInfo, videoFile):
        threading.Thread.__init__(self, daemon=True)
        self.clientInfo = clientInfo
        self.state = ServerWorker.INIT
        self.videoFile = videoFile
        self.sessionId = random.randint(100000, 999999)
        self.rtpSocket = None
        self.streamThread = None
        self.isStreaming = False
        self.video = None
        self.seqnum = 0
        self.play_speed = 1.0
        self.video_lock = threading.Lock()

    def run(self):
        conn = self.clientInfo['rtspSocket'][0]
        addr = self.clientInfo['rtspSocket'][1]
        while True:
            try:
                data = conn.recv(4096).decode()
            except Exception as e:
                break
            if not data:
                break
            lines = data.split('\r\n')
            request_line = lines[0]
            parts = request_line.split(' ')
            if len(parts) < 1:
                continue
            request_type = parts[0]
            headers = {}
            for ln in lines[1:]:
                if ': ' in ln:
                    k, v = ln.split(': ', 1)
                    headers[k] = v

            if request_type == 'SETUP':
                transport = headers.get('Transport','')
                client_port = 0
                if 'client_port' in transport:
                    try:
                        p = transport.split('client_port=')[1]
                        client_port = int(p.split('-')[0])
                    except:
                        client_port = 0
                self.clientInfo['rtpPort'] = client_port
                self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    self.video = VideoStream(self.videoFile)
                except Exception as e:
                    reply = f"RTSP/1.0 454 Session Not Found\r\nCSeq: {headers.get('CSeq','1')}\r\n\r\n"
                    try:
                        conn.send(reply.encode())
                    except:
                        pass
                    break
                self.state = ServerWorker.READY
                reply = f"RTSP/1.0 200 OK\r\nCSeq: {headers.get('CSeq','1')}\r\nTransport: RTP/UDP; client_port={client_port}\r\nSession: {self.sessionId}\r\nPosition: {self.video.current_time():.3f}\r\n\r\n"
                conn.send(reply.encode())

            elif request_type == 'PLAY':
                if self.state == ServerWorker.READY:
                    self.state = ServerWorker.PLAYING
                    self.isStreaming = True
                    self.streamThread = threading.Thread(target=self.streamVideo, daemon=True)
                    self.streamThread.start()
                    reply = f"RTSP/1.0 200 OK\r\nCSeq: {headers.get('CSeq','1')}\r\nSession: {self.sessionId}\r\nPosition: {self.video.current_time():.3f}\r\n\r\n"
                    conn.send(reply.encode())

            elif request_type == 'PAUSE':
                if self.state == ServerWorker.PLAYING:
                    self.isStreaming = False
                    self.state = ServerWorker.READY
                    reply = f"RTSP/1.0 200 OK\r\nCSeq: {headers.get('CSeq','1')}\r\nSession: {self.sessionId}\r\nPosition: {self.video.current_time():.3f}\r\n\r\n"
                    conn.send(reply.encode())

            elif request_type == 'TEARDOWN':
                self.isStreaming = False
                reply = f"RTSP/1.0 200 OK\r\nCSeq: {headers.get('CSeq','1')}\r\nSession: {self.sessionId}\r\n\r\n"
                try:
                    conn.send(reply.encode())
                except:
                    pass
                break

            elif request_type == 'SET_SPEED':
                speed_str = headers.get('Speed', None)
                if speed_str is not None:
                    try:
                        s = float(speed_str)
                        if s <= 0:
                            raise ValueError("speed must be positive")
                        self.play_speed = s
                        reply = f"RTSP/1.0 200 OK\r\nCSeq: {headers.get('CSeq','1')}\r\nSession: {self.sessionId}\r\nSpeed: {self.play_speed}\r\nPosition: {self.video.current_time():.3f}\r\n\r\n"
                        conn.send(reply.encode())
                    except Exception as e:
                        reply = f"RTSP/1.0 400 Bad Request\r\nCSeq: {headers.get('CSeq','1')}\r\nSession: {self.sessionId}\r\n\r\n"
                        conn.send(reply.encode())
                else:
                    reply = f"RTSP/1.0 400 Bad Request\r\nCSeq: {headers.get('CSeq','1')}\r\nSession: {self.sessionId}\r\n\r\n"
                    conn.send(reply.encode())

            elif request_type == 'SEEK':
                if self.video is None:
                    reply = f"RTSP/1.0 455 Method Not Valid in This State\r\nCSeq: {headers.get('CSeq','1')}\r\nSession: {self.sessionId}\r\n\r\n"
                    conn.send(reply.encode())
                    continue
                try:
                    if 'Position-Relative' in headers:
                        delta = float(headers.get('Position-Relative', '0'))
                        with self.video_lock:
                            self.video.seek_by_seconds(delta)
                        newpos = self.video.current_time()
                        reply = f"RTSP/1.0 200 OK\r\nCSeq: {headers.get('CSeq','1')}\r\nSession: {self.sessionId}\r\nPosition: {newpos:.3f}\r\n\r\n"
                        conn.send(reply.encode())
                    elif 'Position' in headers:
                        abspos = float(headers.get('Position', '0'))
                        with self.video_lock:
                            self.video.seek_to_seconds(abspos)
                        newpos = self.video.current_time()
                        reply = f"RTSP/1.0 200 OK\r\nCSeq: {headers.get('CSeq','1')}\r\nSession: {self.sessionId}\r\nPosition: {newpos:.3f}\r\n\r\n"
                        conn.send(reply.encode())
                    else:
                        reply = f"RTSP/1.0 400 Bad Request\r\nCSeq: {headers.get('CSeq','1')}\r\nSession: {self.sessionId}\r\n\r\n"
                        conn.send(reply.encode())
                except Exception as e:
                    reply = f"RTSP/1.0 500 Internal Server Error\r\nCSeq: {headers.get('CSeq','1')}\r\nSession: {self.sessionId}\r\n\r\n"
                    conn.send(reply.encode())

            else:
                reply = f"RTSP/1.0 400 Bad Request\r\nCSeq: {headers.get('CSeq','1')}\r\n\r\n"
                conn.send(reply.encode())

        try:
            if self.rtpSocket:
                self.rtpSocket.close()
            if self.video:
                self.video.release()
        except:
            pass
        try:
            conn.close()
        except:
            pass

    def streamVideo(self):
        clientAddress = self.clientInfo['rtspSocket'][1][0]
        clientRtpPort = self.clientInfo.get('rtpPort', 0)
        if clientRtpPort == 0:
            return
        base_frame_delay = self.video.frameRateMs()
        payload_type = 26
        MTU = 1400

        next_frame_time = time.perf_counter()
        while self.isStreaming:
            speed = self.play_speed if self.play_speed > 0 else 1.0
            frame_delay = base_frame_delay / speed

            now = time.perf_counter()
            if next_frame_time > now:
                sleep_for = next_frame_time - now
                time.sleep(sleep_for)
            else:
                pass
            next_frame_time += frame_delay

            with self.video_lock:
                frame_info = self.video.nextFrame()
            if frame_info is None:
                self.isStreaming = False
                break

            frameNo, jpgBytes = frame_info
            timestamp = int(frameNo * 1000)
            payload = jpgBytes
            offset = 0
            total_len = len(payload)
            while offset < total_len and self.isStreaming:
                chunk = payload[offset: offset + MTU]
                offset += MTU
                is_last = (offset >= total_len)
                self.seqnum = (self.seqnum + 1) % 65536
                marker = 1 if is_last else 0
                rtpPacket = RtpPacket()
                rtpPacket.encode(payload_type, self.seqnum, timestamp, chunk, marker=marker)
                packet = rtpPacket.getPacket()
                try:
                    self.rtpSocket.sendto(packet, (clientAddress, clientRtpPort))
                except Exception as e:
                    self.isStreaming = False
                    break
                time.sleep(0.0008)
                
def startRtspServer(listen_addr='', port=RTSP_PORT, videoFile='video.mp4'):
    serverSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    serverSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    serverSocket.bind((listen_addr, port))
    serverSocket.listen(5)
    try:
        while True:
            conn, addr = serverSocket.accept()
            clientInfo = {}
            clientInfo['rtspSocket'] = (conn, addr)
            worker = ServerWorker(clientInfo, videoFile)
            worker.start()
    except KeyboardInterrupt:
        pass
    finally:
        serverSocket.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=RTSP_PORT)
    parser.add_argument('--video', type=str, default='video.mp4')
    args = parser.parse_args()
    startRtspServer(port=args.port, videoFile=args.video)
