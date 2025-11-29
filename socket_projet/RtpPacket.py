import struct

class RtpPacket:
    HEADER_SIZE = 12

    def __init__(self):
        self.header = bytearray(self.HEADER_SIZE)
        self.payload = b''

    def encode(self, payload_type, seqnum, timestamp, payload, marker=0, ssrc=0):
        self.header[0] = 0x80
        self.header[1] = ((marker & 0x01) << 7) | (payload_type & 0x7F)
        struct.pack_into("!H", self.header, 2, seqnum & 0xFFFF)
        struct.pack_into("!I", self.header, 4, timestamp & 0xFFFFFFFF)
        struct.pack_into("!I", self.header, 8, ssrc & 0xFFFFFFFF)
        self.payload = payload

    def getPacket(self):
        return bytes(self.header) + self.payload

    def decode(self, byteStream):
        self.header = bytearray(byteStream[:self.HEADER_SIZE])
        self.payload = byteStream[self.HEADER_SIZE:]

    def getPayload(self):
        return self.payload

    def getSequence(self):
        return struct.unpack("!H", self.header[2:4])[0]

    def getTimestamp(self):
        return struct.unpack("!I", self.header[4:8])[0]

    def getPayloadType(self):
        return self.header[1] & 0x7F
