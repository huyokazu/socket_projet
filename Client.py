from tkinter import *
from tkinter.ttk import Progressbar
import tkinter.messagebox
from PIL import Image, ImageTk
import socket, threading, sys, traceback, os

from RtpPacket import RtpPacket

CACHE_FILE_NAME = "cache-"
CACHE_FILE_EXT = ".jpg"

class Client:
	INIT = 0
	READY = 1
	PLAYING = 2
	state = INIT
	
	SETUP = 0
	PLAY = 1
	PAUSE = 2
	TEARDOWN = 3
	
	def __init__(self, master, serveraddr, serverport, rtpport, filename):
		self.total_frames = None
		self.current_frame = 0
		self.master = master
		self.master.protocol("WM_DELETE_WINDOW", self.handler)

		self.play_speed = 1.0
		self.fps = 25
		self.display_interval = int(1000 / (self.fps * self.play_speed))
		self.rtsp_lock = threading.Lock()

		self.createWidgets()

		self.serverAddr = serveraddr
		self.serverPort = int(serverport)
		self.rtpPort = int(rtpport)
		self.fileName = filename
		self.rtspSeq = 0
		self.sessionId = 0
		self.requestSent = -1
		self.teardownAcked = 0
		self.connectToServer()
		self.frameNbr = 0
		
		# Removed the self.playout call here as it caused an error 
		# and is handled by listenRtp instead.

	def createWidgets(self):
		self.setup = Button(self.master, width=20, padx=3, pady=3, text="Setup", command=self.setupMovie)
		self.setup.grid(row=1, column=0, padx=2, pady=2)
		self.start = Button(self.master, width=20, padx=3, pady=3, text="Play", command=self.playMovie)
		self.start.grid(row=1, column=1, padx=2, pady=2)
		self.pause = Button(self.master, width=20, padx=3, pady=3, text="Pause", command=self.pauseMovie)
		self.pause.grid(row=1, column=2, padx=2, pady=2)
		self.teardown = Button(self.master, width=20, padx=3, pady=3, text="Teardown", command=self.exitClient)
		self.teardown.grid(row=1, column=3, padx=2, pady=2)
		
		self.label = Label(self.master, height=19)
		self.label.grid(row=0, column=0, columnspan=6, sticky=W+E+N+S, padx=5, pady=5) 

		self.back5 = Button(self.master, width=12, text="<< -5s", command=lambda: threading.Thread(target=self.seek_relative, args=(-5,), daemon=True).start())
		self.back5.grid(row=2, column=0, padx=2, pady=2)
		self.forward5 = Button(self.master, width=12, text="+5s >>", command=lambda: threading.Thread(target=self.seek_relative, args=(5,), daemon=True).start())
		self.forward5.grid(row=2, column=1, padx=2, pady=2)
		Label(self.master, text="Speed:").grid(row=2, column=2, padx=2)
		self.speed_values = ["0.25","0.5","1","1.25","1.5","2"]
		self.speed_var = StringVar()
		self.speed_var.set("1")
		self.speed_menu = OptionMenu(self.master, self.speed_var, *self.speed_values, command=lambda v: threading.Thread(target=self.send_speed, args=(float(v),), daemon=True).start())
		self.speed_menu.config(width=6)
		self.speed_menu.grid(row=2, column=3, padx=2, pady=2)
		self.speed_label = Label(self.master, text=f"{self.play_speed}x")
		self.speed_label.grid(row=2, column=4, padx=2, pady=2)

		self.progress = Progressbar(self.master, orient=HORIZONTAL, length=500, mode='determinate')
		self.progress.grid(row=4, column=0, columnspan=6, pady=2)
		self.progress.bind("<B1-Motion>", self.on_progress_drag)
		self.progress.bind("<ButtonRelease-1>", self.on_progress_release)
		
	def on_progress_drag(self, event):
		if not self.total_frames:
			return
		
		width = self.progress.winfo_width()
		if width == 0: return

		click_x = event.x
		
		if click_x < 0: click_x = 0
		if click_x > width: click_x = width
		
		percent = click_x / width
		
		self.progress["value"] = percent * 100
		
	def on_progress_release(self, event):
		if not self.total_frames:
			return

		width = self.progress.winfo_width()
		if width == 0: return
		
		click_x = event.x
		
		if click_x < 0: click_x = 0
		if click_x > width: click_x = width

		percent = click_x / width
		
		self.progress["value"] = percent * 100

		target_frame = int(percent * self.total_frames)
		target_sec = target_frame / self.fps

		print(f"[SEEK-RELEASE] Seek to {target_sec:.2f}s")

		try:
			with self.rtsp_lock:
				self.rtspSeq += 1
				req = (
					f"SEEK {self.fileName} RTSP/1.0\n"
					f"CSeq: {self.rtspSeq}\n"
					f"Position: {target_sec}\n"
					f"Session: {self.sessionId}\n"
				)
				self.rtspSocket.send(req.encode())
			
			# Dọn dẹp cache
			try:
				cname = CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT
				if os.path.exists(cname):
					os.remove(cname)
			except:
				pass
				
		except Exception as e:
			print("[Client] Progress bar seek error:", e)

	def update_progress_by_frame(self):
		try:
			if not self.total_frames or not getattr(self, 'progress', None):
				return
			percent = (float(self.current_frame) / float(self.total_frames)) * 100.0
			if percent < 0: percent = 0
			if percent > 100: percent = 100
			self.progress["value"] = percent
			try:
				self.progress.update()
			except:
				pass
		except:
			pass
	
	def toggle_reverse(self):
		try:
			new_speed = -self.play_speed if self.play_speed != 0 else -1.0
			self.play_speed = new_speed
			self.display_interval = int(1000 / (self.fps * abs(self.play_speed))) if self.fps>0 else self.display_interval
			try:
				self.speed_label.config(text=f"{self.play_speed}x")
			except:
				pass
		except:
			pass

		if not hasattr(self, 'rtspSocket') or self.rtspSocket is None:
			return
		try:
			req = f"SET_SPEED {self.fileName} RTSP/1.0\nCSeq: {self.rtspSeq+1}\nSpeed: {self.play_speed}\nSession: {self.sessionId}\n"
			with self.rtsp_lock:
				self.rtspSeq += 1
				self.requestSent = -1
				self.rtspSocket.send(req.encode())
		except Exception as e:
			print("[Client] toggle_reverse network error:", e)


	def setupMovie(self):
		if self.state == self.INIT:
			threading.Thread(target=self.recvRtspReply, daemon=True).start()
			threading.Thread(target=lambda: self.sendRtspRequest(self.SETUP), daemon=True).start()

	
	def exitClient(self):
		self.sendRtspRequest(self.TEARDOWN)
		try:
			self.master.destroy()
		except:
			pass
		try:
			cname = CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT
			if os.path.exists(cname):
				os.remove(cname)
		except:
			pass

	def pauseMovie(self):
		if self.state == self.PLAYING:
			self.sendRtspRequest(self.PAUSE)
	
	def playMovie(self):
		if self.state == self.READY:
			if not hasattr(self, 'listen_thread') or (self.listen_thread and not self.listen_thread.is_alive()):
				self.listen_thread = threading.Thread(target=self.listenRtp, daemon=True)
				self.listen_thread.start()

			try:
				self.playEvent = threading.Event()
				self.playEvent.clear()
			except:
				pass

			threading.Thread(target=lambda: self.sendRtspRequest(self.PLAY), daemon=True).start()

	def listenRtp(self):
		buffer = bytearray()
		while True:
			try:
				data = self.rtpSocket.recv(65536)
			except Exception:
				try:
					if getattr(self, 'teardownAcked', 0) == 1:
						break
					if hasattr(self, 'playEvent') and self.playEvent.is_set():
						break
				except:
					pass
				continue
			if not data:
				continue
			try:
				rtpPacket = RtpPacket()
				rtpPacket.decode(data)

				try:
					frame_no = int(rtpPacket.timestamp())
				except:
					try:
						frame_no = int(rtpPacket.seqNum())
					except:
						frame_no = None

				payload = rtpPacket.getPayload()
				marker = (rtpPacket.header[1] >> 7) & 0x01 if hasattr(rtpPacket, 'header') else 0
				buffer.extend(payload)
				if marker == 1:
					if frame_no and frame_no > 0:
						self.current_frame = frame_no
					else:
						self.current_frame += 1

					if getattr(self, 'total_frames', None):
						try:
							self.master.after(0, self.update_progress_by_frame)
						except:
							self.update_progress_by_frame()

					path = self.writeFrame(bytes(buffer))
					buffer = bytearray()
					try:
						self.master.after(0, lambda p=path: self.updateMovie(p))
					except:
						self.updateMovie(path)
			except Exception:
				continue

					
	def writeFrame(self, data):
		cachename = CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT
		file = open(cachename, "wb")
		file.write(data)
		file.close()
		
		return cachename
	
	def updateMovie(self, imageFile):
		try:
			photo = ImageTk.PhotoImage(Image.open(imageFile))
			self.label.configure(image = photo, height=288) 
			self.label.image = photo
		except:
			pass
		
	def connectToServer(self):
		self.rtspSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		try:
			self.rtspSocket.connect((self.serverAddr, self.serverPort))
		except:
			try:
				tkinter.messagebox.showwarning('Connection Failed', 'Connection to \'%s\' failed.' %self.serverAddr)
			except:
				pass
	
	def sendRtspRequest(self, requestCode):
		if requestCode == self.SETUP and self.state == self.INIT:
			self.rtspSeq += 1
			self.requestSent = self.SETUP
			request = f"SETUP {self.fileName} RTSP/1.0\nCSeq: {self.rtspSeq}\nTransport: RTP/UDP; client_port= {self.rtpPort}\n"
		elif requestCode == self.PLAY and self.state == self.READY:
			self.rtspSeq += 1
			self.requestSent = self.PLAY
			request = f"PLAY {self.fileName} RTSP/1.0\nCSeq: {self.rtspSeq}\nSession: {self.sessionId}\n"
		elif requestCode == self.PAUSE and self.state == self.PLAYING:
			self.rtspSeq += 1
			self.requestSent = self.PAUSE
			request = f"PAUSE {self.fileName} RTSP/1.0\nCSeq: {self.rtspSeq}\nSession: {self.sessionId}\n"
		elif requestCode == self.TEARDOWN and self.state != self.INIT:
			self.rtspSeq += 1
			self.requestSent = self.TEARDOWN
			request = f"TEARDOWN {self.fileName} RTSP/1.0\nCSeq: {self.rtspSeq}\nSession: {self.sessionId}\n"
		else:
			return

		try:
			try:
				self.rtsp_lock
			except AttributeError:
				self.rtsp_lock = threading.Lock()
			with self.rtsp_lock:
				self.rtspSocket.send(request.encode())
		except Exception as e:
			try:
				tkinter.messagebox.showwarning('RTSP send error', str(e))
			except:
				pass

	
	def recvRtspReply(self):
		while True:
			try:
				reply = self.rtspSocket.recv(4096)
			except Exception:
				break
			if not reply:
				break
			data = reply.decode('utf-8', errors='ignore')
			lines = data.split('\n')
			sess = None
			status = None
			for ln in lines:
				ln = ln.strip()
				if ln.startswith('CSeq'):
					try:
						seq = int(ln.split(':',1)[1].strip())
					except:
						pass
				elif ln.startswith('Session'):
					try:
						sess = int(ln.split(':',1)[1].strip())
					except:
						pass
				elif ln.startswith('RTSP/1.0'):
					try:
						status = int(ln.split(' ')[1])
					except:
						pass
				elif "Total-Frames" in ln:
					try:
						self.total_frames = int(ln.split(":")[1].strip())
					except:
						self.total_frames = None

			if status == 200:
				if self.requestSent == self.SETUP:
					self.state = self.READY
					if sess:
						self.sessionId = sess
					try:
						self.openRtpPort()
					except:
						pass
					try:
						self.current_frame = 0
						if getattr(self, 'progress', None):
							self.progress["value"] = 0
					except:
						pass
				elif self.requestSent == self.PLAY:
					self.state = self.PLAYING
				elif self.requestSent == self.PAUSE:
					self.state = self.READY
					try:
						self.playEvent.set()
					except:
						pass
				elif self.requestSent == self.TEARDOWN:
					self.state = self.INIT
					self.teardownAcked = 1
			self.requestSent = -1

	def parseRtspReply(self, data):
		lines = data.split('\n')
		try:
			seqNum = int(lines[1].split(' ')[1])
		except:
			return
		
		if seqNum == self.rtspSeq:
			try:
				session = int(lines[2].split(' ')[1])
			except:
				session = 0
			if self.sessionId == 0 and session != 0:
				self.sessionId = session
			
			if self.sessionId == session or self.sessionId == 0:
				status = 0
				try:
					status = int(lines[0].split(' ')[1])
				except:
					pass
				if status == 200:
					if self.requestSent == self.SETUP:
						self.state = self.READY
						self.openRtpPort()
					elif self.requestSent == self.PLAY:
						self.state = self.PLAYING
					elif self.requestSent == self.PAUSE:
						self.state = self.READY
						try:
							self.playEvent.set()
						except:
							pass
					elif self.requestSent == self.TEARDOWN:
						self.state = self.INIT
						self.teardownAcked = 1 
	def openRtpPort(self):
		try:
			self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
			self.rtpSocket.settimeout(0.5)
			self.rtpSocket.bind(('', self.rtpPort))
		except Exception as e:
			try:
				tkinter.messagebox.showwarning('RTP bind failed', f'Cannot bind RTP port {self.rtpPort}: {e}')
			except:
				pass


	def handler(self):
		self.pauseMovie()
		try:
			if tkinter.messagebox.askokcancel("Quit?", "Are you sure you want to quit?"):
				self.exitClient()
			else:
				self.playMovie()
		except:
			pass

	def send_speed(self, speed_value):
		try:
			if speed_value <= 0:
				return
			self.play_speed = speed_value
			self.display_interval = int(1000 / (self.fps * self.play_speed)) if self.fps>0 else self.display_interval
			try:
				self.speed_label.config(text=f"{self.play_speed}x")
			except:
				pass
		except:
			pass

		if not hasattr(self, 'rtspSocket') or self.rtspSocket is None:
			return
		try:
			req = f"SET_SPEED {self.fileName} RTSP/1.0\nCSeq: {self.rtspSeq+1}\nSpeed: {speed_value}\nSession: {self.sessionId}\n"
			with self.rtsp_lock:
				self.rtspSeq += 1
				self.requestSent = -1
				self.rtspSocket.send(req.encode())
		except Exception as e:
			print("[Client] send_speed network error:", e)

	def _start_seek(self):
		self.user_seeking = True

	# Fixed: Added 'event' argument here
	def on_seek_release(self, event):
		"""User thả thanh tua → gửi SEEK tới server"""
		if not self.total_frames:
			return

		percent = self.seek_var.get()
		target_frame = int((percent / 100.0) * self.total_frames)
		target_sec = target_frame / self.fps

		print(f"[SEEK] to {target_sec:.2f}s")

		try:
			with self.rtsp_lock:
				self.rtspSeq += 1
				req = (
					f"SEEK {self.fileName} RTSP/1.0\n"
					f"CSeq: {self.rtspSeq}\n"
					f"Position: {target_sec}\n"
					f"Session: {self.sessionId}\n"
				)
				self.rtspSocket.send(req.encode())
		except Exception as e:
			print("Seek send error:", e)

		self.user_seeking = False

	def seek_relative(self, delta_seconds):
		if not hasattr(self, 'rtspSocket') or self.rtspSocket is None:
			print("[Client] Need SETUP first to seek")
			return
		try:
			with self.rtsp_lock:
				self.rtspSeq += 1
				self.requestSent = -1
				req = f"SEEK {self.fileName} RTSP/1.0\nCSeq: {self.rtspSeq}\nPosition-Relative: {float(delta_seconds)}\nSession: {self.sessionId}\n"
				self.rtspSocket.send(req.encode())
			try:
				cname = CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT
				if os.path.exists(cname):
					os.remove(cname)
			except:
				pass
			try:
				self.current_frame = 0
				if getattr(self, 'progress', None):
					self.progress["value"] = 0
			except:
				pass
		except Exception as e:
			print("[Client] SEEK error:", e)