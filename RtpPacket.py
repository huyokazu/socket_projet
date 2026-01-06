import time
HEADER_SIZE = 12

class RtpPacket:
    def __init__(self):
        self.header = bytearray(HEADER_SIZE)
        self.payload = b''

    def encode(self, version, padding, extension, cc, seqnum, marker, pt, timestamp, ssrc, payload):
        header = bytearray(HEADER_SIZE)
        header[0] = ((version & 0x03) << 6) | ((padding & 0x01) << 5) | ((extension & 0x01) << 4) | (cc & 0x0F)
        header[1] = ((marker & 0x01) << 7) | (pt & 0x7F)
        header[2] = (seqnum >> 8) & 0xFF
        header[3] = seqnum & 0xFF
        header[4] = (timestamp >> 24) & 0xFF
        header[5] = (timestamp >> 16) & 0xFF
        header[6] = (timestamp >> 8) & 0xFF
        header[7] = timestamp & 0xFF
        header[8] = (ssrc >> 24) & 0xFF
        header[9] = (ssrc >> 16) & 0xFF
        header[10] = (ssrc >> 8) & 0xFF
        header[11] = ssrc & 0xFF
        self.header = header
        self.payload = payload

    def decode(self, byteStream):
        self.header = bytearray(byteStream[:HEADER_SIZE])
        self.payload = byteStream[HEADER_SIZE:]

    def seqNum(self):
        return (self.header[2] << 8) | self.header[3]

    def timestamp(self):
        return (
            (self.header[4] << 24)
            | (self.header[5] << 16)
            | (self.header[6] << 8)
            | self.header[7]
        )

    def getPayload(self):
        return self.payload

    def getPacket(self):
        return bytes(self.header) + self.payload
