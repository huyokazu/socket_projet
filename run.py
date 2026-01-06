import sys, subprocess, time, os, socket, glob

PY = sys.executable or "python"
HERE = os.path.abspath(os.path.dirname(__file__))

def find_video_file():
    # prefer explicit movie.Mjpeg if present
    candidate = os.path.join(HERE, "movie.Mjpeg")
    if os.path.exists(candidate):
        return "movie.Mjpeg"
    # else try common extensions
    for ext in ["*.mjpeg","*.Mjpeg","*.mp4","*.MP4","*.mkv","*.MKV","*.avi","*.AVI","*.mov","*.MOV"]:
        found = glob.glob(os.path.join(HERE, ext))
        if found:
            return os.path.basename(found[0])
    return None

def start_server(python, server_script, port, video):
    logfile = os.path.join(HERE, "server.log")
    # open logfile for append so we can inspect errors
    f = open(logfile, "ab")
    cmd = [python, server_script, "--port", str(port), "--video", video]
    # write both stdout and stderr into server.log
    proc = subprocess.Popen(cmd, stdout=f, stderr=f, shell=False)
    return proc, f

def wait_for_port(host, port, timeout=6.0, interval=0.2):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            s = socket.create_connection((host, port), timeout=0.6)
            s.close()
            return True
        except Exception:
            time.sleep(interval)
    return False
                                                
def start_client(python, client_script, host, rtsp_port, rtp_port, video):
    cmd = [python, client_script, host, str(rtsp_port), str(rtp_port), video]
    return subprocess.Popen(cmd, shell=False)

def main():
    rtsp_port = 8554
    rtp_port = 25000
    host = "127.0.0.1"

    server_script = os.path.join(HERE, "Server.py")
    client_script = os.path.join(HERE, "ClientLauncher.py")

    video = find_video_file()
    if not video:
        print("No video file found in folder. Put movie file (e.g. .mjpeg, .mp4) here and rerun.")
        sys.exit(1)

    srv, logfile_handle = start_server(PY, server_script, rtsp_port, video)
    ready = wait_for_port(host, rtsp_port, timeout=6.0)
    if not ready:
        try:
            srv.kill()
        except:
            pass
        logfile_handle.close()
        print("Server failed to start — see server.log for details.")
        sys.exit(1)

    cli = start_client(PY, client_script, host, rtsp_port, rtp_port, video)
    try:
        cli.wait()
    finally:
        try:
            if srv.poll() is None:
                srv.terminate()
        except:
            pass
        logfile_handle.close()

if __name__ == "__main__":
    main()
