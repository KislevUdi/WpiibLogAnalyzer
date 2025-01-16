from __future__ import annotations
import math
import os.path
import struct
import typing
from typing import Optional

import tkinter as tk
from tkinter import filedialog

import numpy
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker

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
            msg(f'{fileName} is not a valid WPILOG file')
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
            msg(f' read {numRead} lines')

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
    global fileName, log, listBox, fileText
    dir = os.path.dirname(fileName)
    if not dir :
        fileName = filedialog.askopenfilename(initialdir='./')
    else:
        fileName = filedialog.askopenfilename(initialdir=dir)
    if fileName:
        log = LogFileReader(fileName)
        s = log.getGroups()
        s = list(s)
        s.sort()
        listBox.delete(0,tk.END)
        for e in s:
            listBox.insert(tk.END,e)
        listBox.pack()
        fileText.configure(state=tk.NORMAL)
        fileText.delete(0,tk.END)
        fileText.insert(0,fileName)
        fileText.configure(state=tk.DISABLED)


def analyzeSelectedGroups():
    selected_items = [listBox.get(i) for i in listBox.curselection()]
    msg(str(selected_items))
    k = []
    for s in selected_items:
        vData = log.getEntryDefinition(s + '/Velocity')
        aData = log.getEntryDefinition(s + '/Acceleration')
        voltData = log.getEntryDefinition(s + '/Voltage')
        k.append(analyzeData(vData, aData, voltData, s))
    l = len(selected_items)
    if l > 1:
        k = np.average(k, axis=0)
        msg(f'avg KS={k[0]:5.3f}')
        msg(f'avg KV={k[1]:5.3f}')
        msg(f'avg KA={k[2]:7.5f}')


def plotSelectedGroups():
    selected_items = [listBox.get(i) for i in listBox.curselection()]
    for s in selected_items:
        entries = [log.getEntryDefinition(s + '/Velocity'),
                   log.getEntryDefinition(s + '/Acceleration'),
                   log.getEntryDefinition(s + '/Voltage'),
                   log.getEntryDefinition(s + '/Position')]
        if None not in entries:
            times = []
            values = []
            firstTime = 0
            lastTime = 0
            data = [x.firstData for x in entries]
            while data[0].next:
                maxTime = max((r.timestamp for r in data))
                for i, r in enumerate(data):
                    data[i] = data[i].getToTime(maxTime)
                    if not data[i]:
                        break
                if data[2].value != 0:
                    if firstTime == 0:
                        firstTime = data[0].timestamp
                    else:
                        lastTime = (data[0].timestamp - firstTime) / 1000
                    times.append(lastTime)
                    values.append((data[0].value*2, data[1].value, data[2].value*12.5, math.degrees(data[3].value)))
                data[0] = data[0].next
            fig, ax = plt.subplots()
            ax.plot(times, values)
            ax.set_title(s)
            ax.set_xlabel("Time")
            ax.legend(('Vel(rad*2)','Acc(rad)','Volt(%)','Pos(deg'))
            ax.minorticks_on()
            ax.xaxis.set_minor_locator(matplotlib.ticker.AutoMinorLocator(10))
            ax.grid(visible=True, which='major', color='b', linestyle='-', axis='x')
            ax.grid(visible=True, which='minor', color='r', linestyle='--', axis='x')
            ax.grid(visible=True, which='major', color='g', linestyle='-', axis='y')
            plt.show()


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
                msg(f'Can not find data {name}')
                quit()
            record = entry.firstData
            if time == 0:
                time = record.timestamp
            else:
                record.getToTime(time)
            data.append(record)
        msg('   Time  ,   Voltage , Velocity , Position ,  Acceleration')
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
                msg(str)
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
                    dataArray.append((1 if vel.value > 0 else -1,
                                      vel.value, a if CALCULATE_ACCELERATION else acc.value))
                if PRINT_DATA:
                    msg(f'{vol.timestamp/1000:8.3f} '
                        f'volt={vol.value:5.2f} '
                        f'v={vel.value:6.2f} '
                        f'a={acc.value:7.2f} / {a:7.2f} '
                        f'prevV={vel.prev.value:6.2f} / {vel.prev.timestamp/1000:8.3f}')
        data[0] = data[0].next
    if n < 10:
        msg(f'got only {n} lines for {name}')
        return
    V = numpy.array(volts)
    B = numpy.array(dataArray)
    C = numpy.linalg.lstsq(B,V)
    R = C[0]
    E = V - numpy.matmul(B,R)
    EE = numpy.abs(E)
    E1 = numpy.max(EE)
    E2 = numpy.average(EE)
    msg(f'Data analyzed for {name} max abs error {E1} average abs error {E2} - based on {n} lines')
    msg(f'KS = {R[0]}')
    if CALCULATE_THEORETICAL_KV:
        msg(f'KV = {kv}')
        msg(f'KA = {R[1]}')
        return (R[0], kv, R[1])
    else:
        msg(f'KV = {R[1]} / {kv}')
        msg(f'KA = {R[2]}')
        return (R[0], R[1], R[2])


def setKv():
    global CALCULATE_THEORETICAL_KV
    CALCULATE_THEORETICAL_KV = kvVar.get() == 1
    msg(f'CALCULATE_THEORETICAL_KV = {CALCULATE_THEORETICAL_KV}')


def setPrint():
    global PRINT_DATA
    PRINT_DATA = printVar.get() == 1
    msg(f'PRINT_DATA = {PRINT_DATA}')


def setCalcAcceleration():
    global CALCULATE_ACCELERATION
    CALCULATE_ACCELERATION = calcAccVar.get() == 1
    msg(f'CALCULATE_ACCELERATION = {CALCULATE_ACCELERATION}')


def msg(msg:str):
    resultText.configure(state=tk.NORMAL)
    resultText.insert(tk.END,'\n' + msg)
    resultText.configure(state=tk.DISABLED)


if __name__ == '__main__':
    rootWindow = tk.Tk()
    rootWindow.geometry('1500x600')
    fileName = ''
    buttonFrame = tk.Frame(master=rootWindow, width=10, height=50)
    listFrame = tk.Frame(master=rootWindow, width=10, height=50)
    resultFrame = tk.Frame(master=rootWindow, width=10, height=50)
    buttonFrame.pack(padx=10, pady=10, side=tk.LEFT, fill=tk.NONE, expand=False)
    listFrame.pack(padx=10, pady=10, side=tk.LEFT, fill=tk.NONE, expand=False)
    resultFrame.pack(padx=10, pady=10, side=tk.LEFT, fill=tk.BOTH, expand=True)

    fileB = tk.Button(buttonFrame, text='Select File', command=select_file)
    fileText = tk.Entry(buttonFrame, state=tk.DISABLED, width=50)

    listBox = tk.Listbox(listFrame, selectmode=tk.MULTIPLE, width=40, height=100)

    analyzeB = tk.Button(buttonFrame, text='Analyze', command=analyzeSelectedGroups)
    endB = tk.Button(buttonFrame, text='Exit', command=lambda: quit(0))
    printB = tk.Button(buttonFrame, text='Print', command=printSelectedGroups)
    plotB = tk.Button(buttonFrame, text='Plot', command=plotSelectedGroups)
    kvVar = tk.IntVar()
    kvVar.set(1 if CALCULATE_THEORETICAL_KV else 0)
    kvCheck = tk.Checkbutton(buttonFrame, text="Use Theoretical KV",
                             variable=kvVar, onvalue=1, offvalue=0, command=setKv)
    printVar = tk.IntVar()
    printVar.set(1 if PRINT_DATA else 0)
    printCheck = tk.Checkbutton(buttonFrame,text="Print", variable=printVar, onvalue=1, offvalue=0, command=setPrint)
    calcAccVar = tk.IntVar()
    calcAccVar.set(1 if CALCULATE_ACCELERATION else 0)
    calcAccCheck = tk.Checkbutton(buttonFrame, text="Calculate our Acceleration",
                                  variable=calcAccVar, onvalue=1, offvalue=0, command=setCalcAcceleration)

    resultText = tk.Text(resultFrame)
    resultText.configure(state=tk.DISABLED)
    resultText.pack(padx=10, pady=10, side=tk.LEFT, fill=tk.BOTH, expand=True)
    scroll = tk.Scrollbar(resultFrame)
    scroll.pack(side=tk.RIGHT, fill=tk.Y)
    resultText.config(yscrollcommand=scroll.set)
    scroll.config(command=resultText.yview)

    fileB.pack(padx=10, pady=10, side=tk.TOP, anchor=tk.NW, fill=tk.NONE, expand=False)
    fileText.pack(padx=10, pady=10, side=tk.TOP, anchor=tk.NW, fill=tk.NONE, expand=False)
    listBox.pack(padx=10, pady=10, side=tk.LEFT, anchor=tk.NE, fill=tk.NONE, expand=False)
    printCheck.pack(padx=10, pady=10, side=tk.TOP, anchor=tk.NW, fill=tk.NONE, expand=False)
    kvCheck.pack(padx=10, pady=10, side=tk.TOP, anchor=tk.NW, fill=tk.NONE, expand=False)
    calcAccCheck.pack(padx=10, pady=10, side=tk.TOP, anchor=tk.NW, fill=tk.NONE, expand=False)
    analyzeB.pack(padx=10, pady=10, side=tk.TOP, anchor=tk.NW, fill=tk.NONE, expand=False)
    endB.pack(padx=10, pady=10, side=tk.BOTTOM, anchor=tk.S, fill=tk.NONE, expand=False)
    printB.pack(padx=10, pady=10, side=tk.TOP, anchor=tk.NW, fill=tk.NONE, expand=False)
    plotB.pack(padx=10, pady=10, side=tk.TOP, anchor=tk.NW, fill=tk.NONE, expand=False)

    rootWindow.mainloop()









