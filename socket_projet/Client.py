import socket
import threading
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
from RtpPacket import RtpPacket
import io
import argparse
import queue
import time

RTSP_PORT = 8554

class ClientApp:
    def __init__(self, master, serverAddr='127.0.0.1', serverPort=RTSP_PORT, rtpPort=25000, fps=25):
        self.running = True
        self.master = master
        self.serverAddr = serverAddr
        self.serverPort = serverPort
        self.rtpPort = rtpPort
        self.rtspSocket = None
        self.session = None
        self.cseq = 1
        self.rtpSocket = None
        self.playing = False
        self.receiveThread = None
        self.frameLabel = None

        self.frame_queue = queue.Queue(maxsize=10)
        self.fps = fps
        self.play_speed = 1.0
        self.display_interval = max(1, int(1000 / (self.fps * self.play_speed)))

        self.rtsp_lock = threading.Lock()

        self.setupGUI()
        self.master.after(self.display_interval, self.playout)

    def setupGUI(self):
        self.master.title("RTSP/RTP Client (seek ±5s & speed)")
        main = ttk.Frame(self.master, padding="5")
        main.grid(row=0, column=0, sticky='nsew')
        self.frameLabel = ttk.Label(main)
        self.frameLabel.grid(row=0, column=0, columnspan=6)

        btnSetup = ttk.Button(main, text="SETUP", command=lambda: threading.Thread(target=self.setupRtsp, daemon=True).start())
        btnPlay = ttk.Button(main, text="PLAY", command=lambda: threading.Thread(target=self.playRtsp, daemon=True).start())
        btnPause = ttk.Button(main, text="PAUSE", command=lambda: threading.Thread(target=self.pauseRtsp, daemon=True).start())
        btnTeardown = ttk.Button(main, text="TEARDOWN", command=lambda: threading.Thread(target=self.teardownRtsp, daemon=True).start())

        btnSetup.grid(row=1, column=0, padx=3, pady=3)
        btnPlay.grid(row=1, column=1, padx=3, pady=3)
        btnPause.grid(row=1, column=2, padx=3, pady=3)
        btnTeardown.grid(row=1, column=3, padx=3, pady=3)

        btnBack5 = ttk.Button(main, text="<< -5s", command=lambda: threading.Thread(target=self.seek_relative, args=(-5,), daemon=True).start())
        btnForward5 = ttk.Button(main, text="+5s >>", command=lambda: threading.Thread(target=self.seek_relative, args=(5,), daemon=True).start())
        btnBack5.grid(row=2, column=0, padx=3, pady=4)
        btnForward5.grid(row=2, column=1, padx=3, pady=4)

        ttk.Label(main, text="Speed:").grid(row=2, column=2, padx=3)
        self.speed_values = ["0.25","0.5","1","1.25","1.5","2"]
        self.speed_combo = ttk.Combobox(main, values=self.speed_values, state="readonly", width=6)
        self.speed_combo.set("1")
        self.speed_combo.grid(row=2, column=3, padx=3)
        self.speed_combo.bind("<<ComboboxSelected>>", lambda e: threading.Thread(target=self.send_speed, args=(float(self.speed_combo.get()),), daemon=True).start())

        self.speed_label = ttk.Label(main, text=f"Speed: {self.play_speed}x")
        self.speed_label.grid(row=2, column=4, padx=6)

        self.master.rowconfigure(0, weight=1)
        self.master.columnconfigure(0, weight=1)

    def connectRtsp(self):
        if self.rtspSocket:
            return
        self.rtspSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        print(f"[Client] Connecting to RTSP server {self.serverAddr}:{self.serverPort} ...")
        self.rtspSocket.connect((self.serverAddr, self.serverPort))
        print("[Client] Connected to RTSP server")

    def setupRtsp(self):
        try:
            self.connectRtsp()
            with self.rtsp_lock:
                request = f"SETUP rtsp://{self.serverAddr}:{self.serverPort}/video RTSP/1.0\r\nCSeq: {self.cseq}\r\nTransport: RTP/UDP; client_port={self.rtpPort}\r\n\r\n"
                print("[Client] Sending SETUP:\n", request)
                self.rtspSocket.send(request.encode())
                self.cseq += 1
                reply = self.rtspSocket.recv(4096).decode()
            print("[Client] SETUP reply:\n", reply)
            for line in reply.split('\r\n'):
                if line.startswith('Session:'):
                    self.session = line.split(':',1)[1].strip()
            self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.rtpSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.rtpSocket.bind(('', self.rtpPort))
            self.rtpSocket.settimeout(1.0)
            print(f"[Client] Listening for RTP on port {self.rtpPort}")
        except Exception as e:
            print("[Client] SETUP error:", e)

    def playRtsp(self):
        if not self.rtspSocket:
            print("[Client] Call SETUP first")
            return
        try:
            with self.rtsp_lock:
                request = f"PLAY rtsp://{self.serverAddr}:{self.serverPort}/video RTSP/1.0\r\nCSeq: {self.cseq}\r\nSession: {self.session}\r\n\r\n"
                print("[Client] Sending PLAY")
                self.rtspSocket.send(request.encode())
                self.cseq += 1
                reply = self.rtspSocket.recv(4096).decode()
            print("[Client] PLAY reply:\n", reply)

            self.playing = True
            if (self.receiveThread is None) or (not getattr(self.receiveThread, "is_alive", lambda: False)()):
                self.receiveThread = threading.Thread(target=self.receiveRtp, daemon=True)
                self.receiveThread.start()
        except Exception as e:
            print("[Client] PLAY error:", e)

    def pauseRtsp(self):
        if not self.rtspSocket:
            return
        try:
            with self.rtsp_lock:
                request = f"PAUSE rtsp://{self.serverAddr}:{self.serverPort}/video RTSP/1.0\r\nCSeq: {self.cseq}\r\nSession: {self.session}\r\n\r\n"
                self.rtspSocket.send(request.encode())
                self.cseq += 1
                reply = self.rtspSocket.recv(4096).decode()
            print("[Client] PAUSE reply:\n", reply)
            self.playing = False
        except Exception as e:
            print("[Client] PAUSE error:", e)

    def teardownRtsp(self):
        if not self.rtspSocket:
            return
        try:
            with self.rtsp_lock:
                request = f"TEARDOWN rtsp://{self.serverAddr}:{self.serverPort}/video RTSP/1.0\r\nCSeq: {self.cseq}\r\nSession: {self.session}\r\n\r\n"
                self.rtspSocket.send(request.encode())
                self.cseq += 1
                reply = self.rtspSocket.recv(4096).decode()
            print("[Client] TEARDOWN reply:\n", reply)
        except Exception:
            pass
        self.playing = False
        try:
            if self.rtpSocket:
                self.rtpSocket.close()
                self.rtpSocket = None
        except:
            pass
        if self.receiveThread:
            try:
                self.receiveThread.join(timeout=0.5)
            except:
                pass
        self.receiveThread = None

        with self.frame_queue.mutex:
            self.frame_queue.queue.clear()

        self.running = False
        try:
            self.master.destroy()
        except:
            pass
        print("[Client] Teardown complete")

    def send_speed(self, speed_value):
        def _send():
            try:
                if speed_value <= 0:
                    print("[Client] invalid speed (<=0), ignoring")
                    return
                self.play_speed = speed_value
                new_interval = int(1000 / (self.fps * self.play_speed))
                if new_interval < 1:
                    new_interval = 1
                self.display_interval = new_interval
                self.master.after(0, lambda: self.speed_label.config(text=f"Speed: {self.play_speed}x"))
            except Exception as e:
                print("[Client] local speed update error:", e)

            if not self.rtspSocket or not self.session:
                print("[Client] Need SETUP first to send speed change to server")
                return
            try:
                with self.rtsp_lock:
                    request = f"SET_SPEED rtsp://{self.serverAddr}:{self.serverPort}/video RTSP/1.0\r\nCSeq: {self.cseq}\r\nSession: {self.session}\r\nSpeed: {speed_value}\r\n\r\n"
                    print("[Client] Sending SET_SPEED:", speed_value)
                    self.rtspSocket.send(request.encode())
                    self.cseq += 1
                    reply = self.rtspSocket.recv(4096).decode()
                print("[Client] SET_SPEED reply:\n", reply)
            except Exception as e:
                print("[Client] SET_SPEED error (network):", e)

        threading.Thread(target=_send, daemon=True).start()

    def receiveRtp(self):
        buffer = bytearray()
        while self.running:
            if not self.playing:
                time.sleep(0.02)
                continue
            try:
                data, addr = self.rtpSocket.recvfrom(65536)
            except socket.timeout:
                continue
            except Exception as e:
                print("[Client] RTP recv error (closing thread):", e)
                break
            if not data:
                continue
            rtpPacket = RtpPacket()
            try:
                rtpPacket.decode(data)
            except Exception as e:
                print("[Client] RTP decode error:", e)
                continue
            try:
                payload = rtpPacket.getPayload()
            except Exception as e:
                print("[Client] Cannot get payload:", e)
                continue
            try:
                marker = (rtpPacket.header[1] >> 7) & 0x01
            except Exception:
                marker = 0
            buffer.extend(payload)
            if marker == 1:
                try:
                    if self.frame_queue.full():
                        try:
                            _ = self.frame_queue.get_nowait()
                        except:
                            pass
                    self.frame_queue.put_nowait(bytes(buffer))
                except Exception as e_q:
                    print("[Client] Queue put error:", e_q)
                buffer = bytearray()

    def playout(self):
        try:
            if not self.frame_queue.empty():
                frame_bytes = self.frame_queue.get_nowait()
                try:
                    image = Image.open(io.BytesIO(frame_bytes))
                    imgtk = ImageTk.PhotoImage(image=image)
                    self.frameLabel.imgtk = imgtk
                    self.frameLabel.config(image=imgtk)
                except Exception as e:
                    print("[Client] Failed to decode/display in playout:", e)
        except Exception as e:
            print("[Client] Playout error:", e)
        finally:
            self.master.after(self.display_interval, self.playout)

    def seek_relative(self, delta_seconds):
        if not self.rtspSocket or not self.session:
            print("[Client] Need SETUP first to seek")
            return
        try:
            with self.rtsp_lock:
                request = f"SEEK rtsp://{self.serverAddr}:{self.serverPort}/video RTSP/1.0\r\nCSeq: {self.cseq}\r\nSession: {self.session}\r\nPosition-Relative: {float(delta_seconds)}\r\n\r\n"
                print("[Client] Sending SEEK:", delta_seconds)
                self.rtspSocket.send(request.encode())
                self.cseq += 1
                reply = self.rtspSocket.recv(8192).decode()
            print("[Client] SEEK reply:\n", reply)
            with self.frame_queue.mutex:
                self.frame_queue.queue.clear()
        except Exception as e:
            print("[Client] SEEK error:", e)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--server', default='127.0.0.1')
    parser.add_argument('--rtsp-port', type=int, default=RTSP_PORT)
    parser.add_argument('--rtp-port', type=int, default=25000)
    parser.add_argument('--fps', type=int, default=25)
    args = parser.parse_args()
    root = tk.Tk()
    app = ClientApp(root, serverAddr=args.server, serverPort=args.rtsp_port, rtpPort=args.rtp_port, fps=args.fps)
    root.protocol("WM_DELETE_WINDOW", app.teardownRtsp)
    root.mainloop()
