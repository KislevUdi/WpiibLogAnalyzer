import struct
import typing

import tkinter as tk
from tkinter import filedialog

import numpy

class dataRecord:
    def __init__(self, entryId: int, value: float, timestamp: int):
        self.entryId = entryId
        self.timestamp = timestamp
        self.value = value

class entryDescription:
    def __init__(self, entryId: int, name: str, entryType: str, meta: str):
        self.entryId = entryId
        self.name = name
        self.entryType = entryType
        self.meta = meta

class LogFileReader:

    type

    def __init__(self, fileName:str):
        self.file = open(fileName,'rb')
        self.fileName = fileName
        self.entriesDefinition: dict[int, entryDescription] = {}
        self.data: typing.List[dataRecord] = []
        if not self.readHeader():
            self.file.close()
            self.file = None
            print(f'{fileName} is not a valid WPILOG file')
        else:
            self.readAll()

    def readAll(self):
        try:
            timestamp = 1
            payloadLength = 1
            while timestamp != 0 and payloadLength != 0:
                recordId, timestamp, payloadLength = self.readRecordHeader()
                if recordId == 0:   # control
                    self.readControlRecord(payloadLength)
                else:
                    doubleValue = self.readData(recordId, payloadLength)
                    if doubleValue:
                        self.data.append(dataRecord(recordId,doubleValue,timestamp))
        finally:
            self.file.close()
            self.file = None

    def readInt(self, n):
        return int.from_bytes(self.file.read(n), byteorder='little')

    def readStr(self, n):
        return self.file.read(n).decode('utf-8')

    def readHeader(self) -> bool:
        s = self.readStr(6)
        if s != 'WPILOG':
            return False
        ver = self.readInt(2)
        extraLength = self.readInt(4)
        data = str(self.file.read(extraLength)) if extraLength > 0 else ''
        return True

    def readRecordHeader(self):
        b = self.readInt(1)
        idLength = (b & 0x3) + 1
        payloadLength = (b >> 2 & 0x3) + 1
        timestampLength = (b >> 4 & 0x7) + 1
        recordId = self.readInt(idLength)
        payloadSize = self.readInt(payloadLength)
        timeStamp = self.readInt(timestampLength)
        return recordId, timeStamp, payloadSize

    def readControlRecord(self, payloadLength:int):
        recordType = self.readInt(1)
        if recordType == 0: # start record
            entryId = self.readInt(4)
            nameLength = self.readInt(4)
            name = self.readStr(nameLength)
            typeLength = self.readInt(4)
            entryType = self.readStr(typeLength)
            metaLength = self.readInt(4)
            meta = self.readStr(metaLength)
            self.entriesDefinition[entryId] = entryDescription(entryId, name, entryType, meta)
        elif recordType == 1:   # end
            entryId = self.readInt(4)
            del self.entriesDefinition[entryId]
        elif recordType == 2:   # update meta
            entryId = self.readInt(4)
            metaLength = self.readInt(4)
            meta = self.readStr(metaLength)
            entry = self.entriesDefinition[entryId]
            if entry:
                entry.meta = meta

    def readData(self, entryId, length) -> float | None:
        b = self.file.read(length)
        t = self.entriesDefinition[entryId].entryType
        if t == 'double':
            d = struct.unpack('d', b)[0]
            return d
        else:
            return None

    def getGroups(self) -> set:
        res = set()
        for entryDesc in self.entriesDefinition.values():
            entryName = entryDesc.name
            i = entryName.rfind('/')
            if i > 0:
                res.add(entryName[0:i])
        return res

    def getEntryId(self, name):
        for entryDesc in self.entriesDefinition.values():
            if entryDesc.name == name:
                return entryDesc.entryId
        return -1


def select_file():
    return filedialog.askopenfilename(initialdir='./')


def analyzeSelectedGroups():
    selected_items = [listBox.get(i) for i in listBox.curselection()]
    for s in selected_items:
        vId = log.getEntryId(s + '/Velocity')
        aId = log.getEntryId(s + '/Acceleration')
        voltId = log.getEntryId(s + '/Voltage')
        analyzeData(vId, aId, voltId, s)


def analyzeData(vId, aId, voltId, name):
    lastV = 0
    lastA = 0
    lastVolt = 0
    lastVTime = 0
    lastATime = 0
    lastVoltTime = 0
    prevV = 0
    n = 0
    volts = list()
    dataArray = list()
    for data in log.data:
        found = True
        if data.entryId == vId:
            lastV = data.value
            lastVTime = data.timestamp
        elif data.entryId == aId:
            lastA = data.value
            lastATime = data.timestamp
        elif data.entryId == voltId:
            lastVolt = data.value
            lastVoltTime = data.timestamp
        else:
            found = False
        if found and abs(lastVTime - lastATime) < 10 and abs(lastVTime - lastVoltTime) < 10 and 1 < abs(lastVolt) < 9:
            n = n + 1
            volts.append(lastVolt)
            dataArray.append((1 if lastV > 0 else -1, lastV, lastA))
            prevV = lastV
            print(f'{lastVoltTime} volt={lastVolt} v={lastV} a={lastA}')
    if n < 10:
        print(f'got only {n} lines for {name}')
        return
    V = numpy.array(volts)
    B = numpy.array(dataArray)
    C = numpy.linalg.lstsq(B,V)
    R = C[0]
    E = V - numpy.matmul(B,R)
    EE = numpy.abs(E)
    E1 = numpy.max(EE)
    E2 = numpy.average(EE)
    print(f'Data analyzed for {name} max abs error {E1} average abs error {E2} - based on {n} lines')
    print(f'KS = {R[0]}')
    print(f'KV = {R[1]}')
    print(f'KA = {R[2]}')


if __name__ == '__main__':
    rootWindow = tk.Tk()
    root = tk.Frame(master=rootWindow, width=500, height=500)
    root.pack()
    listBox = tk.Listbox(root, selectmode=tk.MULTIPLE, width=200, height=300)
    button = tk.Button(root, text='Analyze', command=analyzeSelectedGroups)
    bEnd = tk.Button(root, text='Exit', command=lambda: quit(0))
    button.pack()
    bEnd.pack()

    filename = select_file()

    log = LogFileReader(filename)
    print(f'log read - {len(log.data)}')
    s = log.getGroups()
    s = list(s)
    s.sort()
    for e in s:
        listBox.insert(tk.END,e)
    listBox.pack()
    root.mainloop()









