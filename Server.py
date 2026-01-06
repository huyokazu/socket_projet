import argparse
import socket
import threading
import os
import sys
import traceback

try:
    from ServerWorker import ServerWorker
except Exception as e:
    print("Failed to import ServerWorker:", e)
    raise

def handle_client_connection(conn, addr):
    clientInfo = {}
    clientInfo['rtspSocket'] = (conn, addr)
    try:
        worker = ServerWorker(clientInfo)
    except TypeError:
        # fallback if constructor signature differs
        worker = ServerWorker(clientInfo, "movie.Mjpeg")
    t = threading.Thread(target=worker.run, daemon=True)
    t.start()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8554)
    parser.add_argument('--host', default='')
    parser.add_argument('--video', default=None)
    args = parser.parse_args()

    HOST = args.host
    PORT = args.port

    try:
        serverSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        serverSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        serverSocket.bind((HOST, PORT))
        serverSocket.listen(5)
    except Exception as e:
        print(f"Failed to bind {HOST}:{PORT} -> {e}")
        traceback.print_exc()
        sys.exit(1)

    try:
        while True:
            try:
                conn, addr = serverSocket.accept()
            except KeyboardInterrupt:
                break
            except Exception:
                continue
            handle_client_connection(conn, addr)
    finally:
        try:
            serverSocket.close()
        except:
            pass

if __name__ == "__main__":
    main()
