import struct

import tkinter as tk
from tkinter import filedialog

import numpy
import numpy as np

class LogFileReader:

    def __init__(self, fileName:str):
        self.file = open(fileName,'rb')
        self.fileName = fileName
        self.entries = {}
        self.entriesArray = np.zeros(1000, dtype='U256')
        self.entriesType = np.zeros(1000, dtype='U256')
        self.data = list()
        if not self.readHeader():
            self.file.close()
            self.file = None
            print(f'{fileName} is not a valid WPILOG file')
        else:
            self.readAll()

    def readAll(self):
        t = 1
        l = 1
        while t != 0 and l != 0:
            r, t, l = self.readRecord()
            if r == 0:
                self.readControlRecord(l)
            else:
                d = self.readData(r, l)
                if d != None:
                    self.data.append((r,d,t))

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

    def readRecord(self):
        b = self.readInt(1)
        idLength = (b & 3) + 1
        payloadLength = (b >> 2 & 3) + 1
        timestampLength = (b >> 4 & 7) + 1
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
            self.entries[name] = (entryId, entryType, meta)
            self.entriesArray[entryId] = name
            self.entriesType[entryId] = entryType
        elif recordType == 1: # end
            entryId = self.readInt(4)
            name = self.entriesArray[entryId]
            self.entries.pop(name)
            self.entriesArray[entryId] = ''
        elif recordType == 2: # udate meta
            entryId = self.readInt(4)
            metaLength = self.readInt(4)
            meta = self.readStr(metaLength)
            name = self.entriesArray[entryId]
            self.entries[name][3] = meta

    def readData(self, entryId, length):
        b = self.file.read(length)
        t = self.entriesType[entryId]
        if t == 'double':
            d = struct.unpack('d',b)[0]
            return d
        else:
            return None
    def getGroups(self) -> set:
        res = set()
        for entry in self.entries.keys():
            i = entry.rfind('/')
            if i > 0:
                res.add(entry[0:i])
        return res




def select_file():
    return filedialog.askopenfilename(initialdir='./')

def selectEntries():
    selected_items = [listBox.get(i) for i in listBox.curselection()]
    for s in selected_items:
        entryList = list()
        for t in ['Velocity', 'Acceleration', 'Voltage']:
            d = log.entries[s + '/' + t]
            if d:
                entryList.append(d[0])
        analyzeData(entryList, s)

def analyzeData(entryList, name):
    lastV = 0
    lastA = 0
    lastVolt = 0
    lastVTime = 0
    lastATime = 0
    lastVoltTime = 0
    n = 0
    volts = list()
    pre = list()
    for data in log.data:
        if data[0] in entryList:
            if data[0] == entryList[0]:
                lastV = data[1]
                lastVTime = data[2]
            elif data[0] == entryList[1]:
                lastA = data[1]
                lastATime = data[2]
            elif data[0] == entryList[2]:
                lastVolt = data[1]
                lastVoltTime = data[2]
            if abs(lastVoltTime - lastATime) < 10 and abs(lastVoltTime-lastVTime) < 10 and abs(lastVolt) > 1 and abs(lastVolt) < 9:
                n = n + 1
                volts.append(lastVolt)
                pre.append((1 if lastV > 0 else -1, lastV, lastA))
    if n < 10:
        print(f'got only {n} lines for {name}')
        return
    V = numpy.array(volts)
    B = numpy.array(pre)
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


rootk = tk.Tk()
root = tk.Frame(master=rootk,width=500,height=500)
root.pack()
listBox = tk.Listbox(root, selectmode=tk.MULTIPLE, width=200, height=300)
button = tk.Button(root, text='Do Selection', command=selectEntries)
button.pack()

filename = select_file()

log = LogFileReader(filename)
print(f'log read - {len(log.data)}')
s = log.getGroups()
for e in s:
    listBox.insert(tk.END,e)
listBox.pack()
root.mainloop()









