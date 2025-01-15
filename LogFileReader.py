from __future__ import annotations
import math
import struct
import typing
from typing import Optional

import tkinter as tk
from tkinter import filedialog

import numpy
import numpy as np

CALCULATE_THEORETICAL_KV = False
GEAR_RATIO = 150.0 / 7.0
MOTOR_FREE_RPM = 6380   # use 6000 for Kraken
MOTOR_MAX_VOLT = 12*(255/257)   # use 12*(344/366)
CALCULATE_ACCELERATION = True
MAX_A = 200
MAX_CALCULATED_A_DIFF = 100
PRINT_DATA = False
PRINT_CSV = True


class DataRecord:
    def __init__(self, entry: EntryDescription, value: float, timestamp: int):
        self.entry = entry
        self.timestamp = timestamp
        self.value = value
        self.next: Optional[DataRecord] = None
        self.prev: Optional[DataRecord] = None

    def getToTime(self, time):
        ret = self
        while ret.next and ret.next.timestamp < time + 15:
            ret = ret.next
        return ret


class EntryDescription:
    def __init__(self, entryId: int, name: str, entryType: str, meta: str):
        self.entryId = entryId
        self.name = name
        self.entryType = entryType
        self.meta = meta
        self.firstData:Optional[DataRecord] = None
        self.lastData:Optional[DataRecord] = None
        self.isDouble = entryType == 'double'
        self.length = 0

    def add(self, value:float, time:int):
        if self.lastData:
            record = DataRecord(self,value,time)
            record.prev = self.lastData
            self.lastData.next = record
            self.lastData = record
        else:
            self.firstData = DataRecord(self,value,time)
            self.lastData = self.firstData
        self.length += 1

    def dataLength(self):
        return self.length


class LogFileReader:

    def __init__(self, fileName:str):
        self.file = open(fileName,'rb')
        self.fileName = fileName
        self.entriesDefinition: dict[int, EntryDescription] = {}
        if not self.readHeader():
            self.file.close()
            self.file = None
            print(f'{fileName} is not a valid WPILOG file')
        else:
            self.readAll()

    def readAll(self):
        numRead = 0
        try:
            timestamp = 1
            payloadLength = 1
            while timestamp != 0 and payloadLength != 0:
                recordId, timestamp, payloadLength = self.readRecordHeader()
                if recordId == 0:   # control
                    self.readControlRecord(payloadLength)
                else:
                    desc = self.entriesDefinition[recordId]
                    if desc.isDouble:
                        desc.add(self.readDouble(payloadLength), timestamp)
                        numRead += 1
                    else:
                        self.skip(payloadLength)
        finally:
            self.file.close()
            self.file = None
            print(f' read {numRead} lines')

    def readInt(self, n):
        return int.from_bytes(self.file.read(n), byteorder='little')

    def readStr(self, n):
        return self.file.read(n).decode('utf-8')

    def readDouble(self, length) -> float:
        b = self.file.read(length)
        return struct.unpack('d', b)[0]

    def skip(self, length):
        self.file.read(length)

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
            self.entriesDefinition[entryId] = EntryDescription(entryId, name, entryType, meta)
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

    def getGroups(self) -> set:
        res = set()
        for entryDesc in self.entriesDefinition.values():
            entryName = entryDesc.name
            i = entryName.rfind('/')
            if i > 0:
                res.add(entryName[0:i])
        return res

    def getEntryDefinition(self, name):
        for entryDesc in self.entriesDefinition.values():
            if entryDesc.name == name:
                return entryDesc
        return None

    def getEntryId(self, name):
        desc = self.getEntryDefinition(name)
        if desc:
            return desc.entryId
        return -1


def select_file():
    return filedialog.askopenfilename(initialdir='./')


def analyzeSelectedGroups():
    selected_items = [listBox.get(i) for i in listBox.curselection()]
    print(selected_items)
    k = []
    for s in selected_items:
        vData = log.getEntryDefinition(s + '/Velocity')
        aData = log.getEntryDefinition(s + '/Acceleration')
        voltData = log.getEntryDefinition(s + '/Voltage')
        k.append(analyzeData(vData, aData, voltData, s))
    l = len(selected_items)
    if l > 1:
        k = np.average(k, axis=0)
        print(f'avg KS={k[0]:5.3f}')
        print(f'avg KV={k[1]:5.3f}')
        print(f'avg KA={k[2]:7.5f}')



def printSelectedGroups():
    selected_items = [listBox.get(i) for i in listBox.curselection()]
    items = ('Voltage', 'Velocity', 'Position', 'Acceleration')
    for s in selected_items:
        data = []
        master = None
        time = 0
        for t in items:
            name = s + '/' + t
            entry = log.getEntryDefinition(name)
            if not entry:
                print(f'Can not find data {name}')
                quit()
            record = entry.firstData
            if t == 0:
                time = record.timestamp
            else:
                record.getToTime(time)
            data.append(record)
        while data[0].next:
            maxTime = max((r.timestamp for r in data))
            str = f'{maxTime/1000:8.4f}'
            for i, r in enumerate(data):
                data[i] = data[i].getToTime(maxTime)
                if not data[i]:
                    break
                if PRINT_CSV:
                    str += f', {data[i].value:10.4f}'
                else:
                    str += f'   {items[i]: >10}:{data[i].value:10.4f}'
            if data[0].value != 0:
                print(str)
            data[0] = data[0].next

def analyzeData(vId, aId, voltId, name):
    n = 0
    volts = list()
    dataArray = list()
    data:typing.List[DataRecord] = [vId.firstData.next, aId.firstData.next, voltId.firstData.next]
    kv = MOTOR_MAX_VOLT / MOTOR_FREE_RPM * 60 * GEAR_RATIO / 2 / math.pi
    while data[0].next:
        maxTime = max((r.timestamp for r in data))
        for i, r in enumerate(data):
            data[i] = data[i].getToTime(maxTime)
            if not data[i]:
                break
        if 1 < abs(data[2].value) < 9:   # valid volts
            vel = data[0]
            acc = data[1].next
            if not acc:
                break
            vol = data[2]
            a = (vel.value - vel.prev.value)*1000/(vel.timestamp - vel.prev.timestamp)
            a = (acc.value + a) / 2
            if not CALCULATE_ACCELERATION or (abs(a - acc.value) < MAX_CALCULATED_A_DIFF and abs(a) < MAX_A):
                n = n + 1
                if CALCULATE_THEORETICAL_KV:
                    volts.append(vol.value - vel.value * kv)
                    dataArray.append((1 if vel.value > 0 else -1, a if CALCULATE_ACCELERATION else acc.value))
                else:
                    volts.append(vol.value)
                    dataArray.append((1 if vel.value > 0 else -1, vel.value, a if CALCULATE_ACCELERATION else acc.value))
                if PRINT_DATA:
                    print(f'{vol.timestamp/1000:8.3f} '
                          f'volt={vol.value:5.2f} '
                          f'v={vel.value:6.2f} '
                          f'a={acc.value:7.2f} / {a:7.2f} '
                          f'prevV={vel.prev.value:6.2f} / {vel.prev.timestamp/1000:8.3f}')
        data[0] = data[0].next
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
    if CALCULATE_THEORETICAL_KV:
        print(f'KV = {kv}')
        print(f'KA = {R[1]}')
        return (R[0], kv, R[1])
    else:
        print(f'KV = {R[1]} / {kv}')
        print(f'KA = {R[2]}')
        return (R[0], R[1], R[2])


def setKv():
    global CALCULATE_THEORETICAL_KV
    CALCULATE_THEORETICAL_KV = kvVar.get() == 1
    print(f'CALCULATE_THEORETICAL_KV = {CALCULATE_THEORETICAL_KV}')

def setPrint():
    global PRINT_DATA
    PRINT_DATA = printVar.get() == 1
    print(f'PRINT_DATA = {PRINT_DATA}')

def setCalcAccelration():
    global CALCULATE_ACCELERATION
    CALCULATE_ACCELERATION = calcAccVar.get() == 1
    print(f'CALCULATE_ACCELERATION = {CALCULATE_ACCELERATION}')

if __name__ == '__main__':
    rootWindow = tk.Tk()
    root = tk.Frame(master=rootWindow, width=500, height=500)
    root.pack()
    listBox = tk.Listbox(root, selectmode=tk.MULTIPLE, width=200, height=300)
    analyzeB = tk.Button(root, text='Analyze', command=analyzeSelectedGroups)
    endB = tk.Button(root, text='Exit', command=lambda: quit(0))
    printB = tk.Button(root, text='Print', command=printSelectedGroups)
    kvVar = tk.IntVar()
    kvVar.set(1 if CALCULATE_THEORETICAL_KV else 0)
    kvCheck = tk.Checkbutton(root, text="Use Theoretical KV", variable=kvVar, onvalue=1, offvalue=0, command=setKv)
    kvCheck.pack()
    printVar = tk.IntVar()
    printVar.set(1 if PRINT_DATA else 0)
    printCheck = tk.Checkbutton(root,text="Print", variable=printVar, onvalue=1, offvalue=0, command=setPrint)
    printCheck.pack()
    calcAccVar = tk.IntVar()
    calcAccVar.set(1 if CALCULATE_ACCELERATION else 0)
    calcAccCheck = tk.Checkbutton(root,text="Calculate our Acceleration",
                                  variable=calcAccVar, onvalue=1, offvalue=0, command=setCalcAccelration)
    calcAccCheck.pack()
    analyzeB.pack()
    endB.pack()
    printB.pack()

    filename = select_file()
    log = LogFileReader(filename)
    s = log.getGroups()
    s = list(s)
    s.sort()
    for e in s:
        listBox.insert(tk.END,e)
    listBox.pack()
    root.mainloop()









