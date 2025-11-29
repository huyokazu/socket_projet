
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

    def run(self):
        conn = self.clientInfo['rtspSocket'][0]
        addr = self.clientInfo['rtspSocket'][1]
        print(f"[Server] Handling client {addr}")
        while True:
            try:
                data = conn.recv(4096).decode()
            except Exception as e:
                print("[Server] RTSP recv error:", e)
                break
            if not data:
                print("[Server] RTSP connection closed by client")
                break
            print("[Server] Received RTSP request:\n", data)
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
                print(f"[Server] Parsed client RTP port: {client_port}")
                self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    # create VideoStream instance (resize+quality inside)
                    self.video = VideoStream(self.videoFile)
                except Exception as e:
                    print("[Server] Cannot open video:", e)
                    reply = f"RTSP/1.0 454 Session Not Found\r\nCSeq: {headers.get('CSeq','1')}\r\n\r\n"
                    try:
                        conn.send(reply.encode())
                    except:
                        pass
                    break
                self.state = ServerWorker.READY
                reply = f"RTSP/1.0 200 OK\r\nCSeq: {headers.get('CSeq','1')}\r\nTransport: RTP/UDP; client_port={client_port}\r\nSession: {self.sessionId}\r\n\r\n"
                conn.send(reply.encode())
                print("[Server] Sent SETUP reply")
            elif request_type == 'PLAY':
                print("[Server] PLAY request received")
                if self.state == ServerWorker.READY:
                    self.state = ServerWorker.PLAYING
                    self.isStreaming = True
                    self.streamThread = threading.Thread(target=self.streamVideo, daemon=True)
                    self.streamThread.start()
                    reply = f"RTSP/1.0 200 OK\r\nCSeq: {headers.get('CSeq','1')}\r\nSession: {self.sessionId}\r\n\r\n"
                    conn.send(reply.encode())
            elif request_type == 'PAUSE':
                print("[Server] PAUSE request received")
                if self.state == ServerWorker.PLAYING:
                    self.isStreaming = False
                    self.state = ServerWorker.READY
                    reply = f"RTSP/1.0 200 OK\r\nCSeq: {headers.get('CSeq','1')}\r\nSession: {self.sessionId}\r\n\r\n"
                    conn.send(reply.encode())
            elif request_type == 'TEARDOWN':
                print("[Server] TEARDOWN request received")
                self.isStreaming = False
                reply = f"RTSP/1.0 200 OK\r\nCSeq: {headers.get('CSeq','1')}\r\nSession: {self.sessionId}\r\n\r\n"
                try:
                    conn.send(reply.encode())
                except:
                    pass
                break
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
        print("[Server] Connection closed")

    def streamVideo(self):
        clientAddress = self.clientInfo['rtspSocket'][1][0]
        clientRtpPort = self.clientInfo.get('rtpPort', 0)
        print(f"[Server] Streaming to {clientAddress}:{clientRtpPort}")
        if clientRtpPort == 0:
            print("[Server] No RTP port, aborting")
            return
        frame_delay = self.video.frameRateMs()
        payload_type = 26  
        MTU = 1400  
        first_frame_saved = False

        while self.isStreaming:
            frame_info = self.video.nextFrame()
            if frame_info is None:
                print("[Server] Video finished")
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
                    print(f"[Server] Sent RTP seq={self.seqnum} size={len(packet)} marker={marker}")
                except Exception as e:
                    print("[Server] Failed to send RTP packet:", e)
                    self.isStreaming = False
                    break
                time.sleep(0.001)
            time.sleep(frame_delay)

def startRtspServer(listen_addr='', port=RTSP_PORT, videoFile='video.mp4'):
    serverSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    serverSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    serverSocket.bind((listen_addr, port))
    serverSocket.listen(5)
    print(f"RTSP server listening on port {port}")
    try:
        while True:
            conn, addr = serverSocket.accept()
            print("[Server] Client connected from", addr)
            clientInfo = {}
            clientInfo['rtspSocket'] = (conn, addr)
            worker = ServerWorker(clientInfo, videoFile)
            worker.start()
    except KeyboardInterrupt:
        print("Server shutting down")
    finally:
        serverSocket.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=RTSP_PORT)
    parser.add_argument('--video', type=str, default='video.mp4')
    args = parser.parse_args()
    startRtspServer(port=args.port, videoFile=args.video)
