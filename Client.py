# Client.py
from tkinter import *
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
	
	# Initiation..
	def __init__(self, master, serveraddr, serverport, rtpport, filename):
		self.master = master
		self.master.protocol("WM_DELETE_WINDOW", self.handler)

		# --- ensure playback-related attributes exist BEFORE building widgets ---
		self.play_speed = 1.0  # playback speed: 0.25,0.5,1,1.25,1.5,2
		self.fps = 25  # assumed fps for seek calculations (used for SEEK ±seconds)
		self.display_interval = int(1000 / (self.fps * self.play_speed))  # ms between playout ticks
		self.rtsp_lock = threading.Lock()

		# build UI (original code called createWidgets here)
		self.createWidgets()

		self.createWidgets()  # preserve original call if present in original code
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

		# start playout scheduling (non-blocking)
		try:
			self.master.after(self.display_interval, self.playout)
		except:
			pass

		
	def createWidgets(self):
		"""Build GUI."""

		# Create Setup button
		self.setup = Button(self.master, width=20, padx=3, pady=3)
		self.setup["text"] = "Setup"
		self.setup["command"] = self.setupMovie
		self.setup.grid(row=1, column=0, padx=2, pady=2)
		
		# Create Play button		
		self.start = Button(self.master, width=20, padx=3, pady=3)
		self.start["text"] = "Play"
		self.start["command"] = self.playMovie
		self.start.grid(row=1, column=1, padx=2, pady=2)
		
		# Create Pause button			
		self.pause = Button(self.master, width=20, padx=3, pady=3)
		self.pause["text"] = "Pause"
		self.pause["command"] = self.pauseMovie
		self.pause.grid(row=1, column=2, padx=2, pady=2)
		
		# Create Teardown button
		self.teardown = Button(self.master, width=20, padx=3, pady=3)
		self.teardown["text"] = "Teardown"
		self.teardown["command"] =  self.exitClient
		self.teardown.grid(row=1, column=3, padx=2, pady=2)
		
		# Create a label to display the movie
		self.label = Label(self.master, height=19)
		self.label.grid(row=0, column=0, columnspan=6, sticky=W+E+N+S, padx=5, pady=5) 

		# ---------- new controls: seek ±5s and speed combobox ----------
		# "<< -5s"
		self.back5 = Button(self.master, width=12)
		self.back5["text"] = "<< -5s"
		self.back5["command"] = lambda: threading.Thread(target=self.seek_relative, args=(-5,), daemon=True).start()
		self.back5.grid(row=2, column=0, padx=2, pady=2)

		# "+5s >>"
		self.forward5 = Button(self.master, width=12)
		self.forward5["text"] = "+5s >>"
		self.forward5["command"] = lambda: threading.Thread(target=self.seek_relative, args=(5,), daemon=True).start()
		self.forward5.grid(row=2, column=1, padx=2, pady=2)

		# Speed label + combobox
		Label(self.master, text="Speed:").grid(row=2, column=2, padx=2)
		self.speed_values = ["0.25","0.5","1","1.25","1.5","2"]
		self.speed_var = StringVar()
		self.speed_var.set("1")
		# Use OptionMenu (Tk's lightweight) to avoid dependency
		self.speed_menu = OptionMenu(self.master, self.speed_var, *self.speed_values, command=lambda v: threading.Thread(target=self.send_speed, args=(float(v),), daemon=True).start())
		self.speed_menu.config(width=6)
		self.speed_menu.grid(row=2, column=3, padx=2, pady=2)

		self.speed_label = Label(self.master, text=f"{self.play_speed}x")
		self.speed_label.grid(row=2, column=4, padx=2, pady=2)
		# ----------------------------------------------------------------
	
	def toggle_reverse(self):
    # invert current speed sign and send to server
		try:
			new_speed = -self.play_speed if self.play_speed != 0 else -1.0
			# update local
			self.play_speed = new_speed
			self.display_interval = int(1000 / (self.fps * abs(self.play_speed))) if self.fps>0 else self.display_interval
			try:
				self.speed_label.config(text=f"{self.play_speed}x")
			except:
				pass
		except:
			pass

		# send to server (best-effort) using same method as send_speed
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
		"""Setup button handler. Run RTSP SETUP in background and start reply listener."""
		if self.state == self.INIT:
			# start RTSP reply reader thread first so reply isn't lost
			threading.Thread(target=self.recvRtspReply, daemon=True).start()
			# then send SETUP in background
			threading.Thread(target=lambda: self.sendRtspRequest(self.SETUP), daemon=True).start()

	
	def exitClient(self):
		"""Teardown button handler."""
		self.sendRtspRequest(self.TEARDOWN)
		try:
			self.master.destroy() # Close the gui window
		except:
			pass
		try:
			cname = CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT
			if os.path.exists(cname):
				os.remove(cname) # Delete the cache image from video
		except:
			pass

	def pauseMovie(self):
		"""Pause button handler."""
		if self.state == self.PLAYING:
			self.sendRtspRequest(self.PAUSE)
	
	def playMovie(self):
		"""Play button handler — ensure RTP listener thread and send PLAY non-blocking."""
		# Only act if state allows
		if self.state == self.READY:
			# Ensure RTP listening thread exists and is running
			if not hasattr(self, 'listen_thread') or (self.listen_thread and not self.listen_thread.is_alive()):
				self.listen_thread = threading.Thread(target=self.listenRtp, daemon=True)
				self.listen_thread.start()

			# Ensure playEvent exists (used to stop listener on pause)
			try:
				self.playEvent = threading.Event()
				self.playEvent.clear()
			except:
				pass

			# Send PLAY via RTSP in a background thread to avoid blocking GUI
			try:
				threading.Thread(target=lambda: self.sendRtspRequest(self.PLAY), daemon=True).start()
			except Exception:
				# fallback: synchronous send
				self.sendRtspRequest(self.PLAY)

	
	def listenRtp(self):
		"""Listen for RTP packets and assemble frames (marker=1 signals end of frame)."""
		buffer = bytearray()
		while True:
			try:
				data, addr = self.rtpSocket.recvfrom(65536)
			except Exception:
				# if socket timeout or error, check teardownAcked or playEvent
				try:
					if getattr(self, 'teardownAcked', 0) == 1:
						break
					if hasattr(self, 'playEvent') and self.playEvent.isSet():
						break
				except:
					pass
				continue
			if not data:
				continue
			try:
				rtpPacket = RtpPacket()
				rtpPacket.decode(data)
				seq = rtpPacket.seqNum()
				payload = rtpPacket.getPayload()
				# marker bit: top bit of header[1]
				marker = (rtpPacket.header[1] >> 7) & 0x01 if hasattr(rtpPacket, 'header') else 0
				buffer.extend(payload)
				if marker == 1:
					# full JPEG frame assembled
					path = self.writeFrame(bytes(buffer))
					buffer = bytearray()
					# update GUI on main thread
					try:
						self.master.after(0, lambda p=path: self.updateMovie(p))
					except:
						self.updateMovie(path)
			except Exception:
				# ignore broken packets
				continue

					
	def writeFrame(self, data):
		"""Write the received frame to a temp image file. Return the image file."""
		cachename = CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT
		file = open(cachename, "wb")
		file.write(data)
		file.close()
		
		return cachename
	
	def updateMovie(self, imageFile):
		"""Update the image file as video frame in the GUI."""
		try:
			photo = ImageTk.PhotoImage(Image.open(imageFile))
			self.label.configure(image = photo, height=288) 
			self.label.image = photo
		except:
			pass
		
	def connectToServer(self):
		"""Connect to the Server. Start a new RTSP/TCP session."""
		self.rtspSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		try:
			self.rtspSocket.connect((self.serverAddr, self.serverPort))
		except:
			try:
				tkinter.messagebox.showwarning('Connection Failed', 'Connection to \'%s\' failed.' %self.serverAddr)
			except:
				pass
	
	def sendRtspRequest(self, requestCode):
		"""Send RTSP request to the server (quick, minimal format expected by ServerWorker)."""
		# Build request according to requestCode
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
			# use lock to prevent concurrent RTSP writes
			try:
				self.rtsp_lock
			except AttributeError:
				self.rtsp_lock = threading.Lock()
			with self.rtsp_lock:
				self.rtspSocket.send(request.encode())
		except Exception as e:
			# show small popup once
			try:
				tkinter.messagebox.showwarning('RTSP send error', str(e))
			except:
				pass

	
	def recvRtspReply(self):
		"""Continuously receive RTSP replies and parse minimal fields."""
		while True:
			try:
				reply = self.rtspSocket.recv(4096)
			except Exception:
				break
			if not reply:
				break
			data = reply.decode('utf-8', errors='ignore')
			lines = data.split('\n')
			# minimal parsing: get CSeq and Session
			seq = None
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
			# apply reply to client state if cseq matches
			# (we accept replies even if seq missing)
			if status == 200:
				# handle based on last requestSent
				if self.requestSent == self.SETUP:
					self.state = self.READY
					# ensure session set
					if sess:
						self.sessionId = sess
					# open RTP port now
					try:
						self.openRtpPort()
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
			# reset requestSent marker to avoid reprocessing
			self.requestSent = -1

	def parseRtspReply(self, data):
		"""Parse the RTSP reply from the server."""
		lines = data.split('\n')
		# minimal safe parsing
		try:
			seqNum = int(lines[1].split(' ')[1])
		except:
			return
		
		# Process only if the server reply's sequence number is the same as the request's
		if seqNum == self.rtspSeq:
			try:
				session = int(lines[2].split(' ')[1])
			except:
				session = 0
			# New RTSP session ID
			if self.sessionId == 0 and session != 0:
				self.sessionId = session
			
			# Process only if the session ID is the same (or not set yet)
			if self.sessionId == session or self.sessionId == 0:
				status = 0
				try:
					status = int(lines[0].split(' ')[1])
				except:
					pass
				if status == 200:
					if self.requestSent == self.SETUP:
						# Update RTSP state.
						self.state = self.READY
						# Open RTP port.
						self.openRtpPort()
					elif self.requestSent == self.PLAY:
						self.state = self.PLAYING
					elif self.requestSent == self.PAUSE:
						self.state = self.READY
						# The play thread exits. A new thread is created on resume.
						try:
							self.playEvent.set()
						except:
							pass
					elif self.requestSent == self.TEARDOWN:
						self.state = self.INIT
						# Flag the teardownAcked to close the socket.
						self.teardownAcked = 1 
	
	def openRtpPort(self):
		"""Open RTP socket to receive UDP packets."""
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
		"""Handler on explicitly closing the GUI window."""
		self.pauseMovie()
		try:
			if tkinter.messagebox.askokcancel("Quit?", "Are you sure you want to quit?"):
				self.exitClient()
			else: # When the user presses cancel, resume playing.
				self.playMovie()
		except:
			pass

	# ---------- new helper methods for speed and seek ----------
	def send_speed(self, speed_value):
		"""Update local speed display and notify server (background thread)."""
		# update label and playout interval locally
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

		# notify server (best-effort)
		if not hasattr(self, 'rtspSocket') or self.rtspSocket is None:
			return
		try:
			req = f"SET_SPEED {self.fileName} RTSP/1.0\nCSeq: {self.rtspSeq+1}\nSpeed: {speed_value}\nSession: {self.sessionId}\n"
			with self.rtsp_lock:
				self.rtspSeq += 1
				self.requestSent = -1
				self.rtspSocket.send(req.encode())
				# optionally recv reply; server may reply but it's optional here
		except Exception as e:
			print("[Client] send_speed network error:", e)

	def seek_relative(self, delta_seconds):
		"""Send SEEK request (Position-Relative) to server. Runs in a separate thread."""
		if not hasattr(self, 'rtspSocket') or self.rtspSocket is None:
			print("[Client] Need SETUP first to seek")
			return
		try:
			with self.rtsp_lock:
				self.rtspSeq += 1
				self.requestSent = -1
				req = f"SEEK {self.fileName} RTSP/1.0\nCSeq: {self.rtspSeq}\nPosition-Relative: {float(delta_seconds)}\nSession: {self.sessionId}\n"
				self.rtspSocket.send(req.encode())
			# clear cache frame to avoid showing old frames
			try:
				cname = CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT
				if os.path.exists(cname):
					os.remove(cname)
			except:
				pass
		except Exception as e:
			print("[Client] SEEK error:", e)
