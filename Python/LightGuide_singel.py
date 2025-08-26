# to compile to deployable executable use pyinstaller LightGuide.py
import tkinter
from tkinter.filedialog import askopenfilename
from tkinter import *
import serial
import serial.tools.list_ports
import pandas as pd
import time
from pandastable import Table, TableModel

def get_available_ports():
    """取得所有可用的 COM ports"""
    ports = serial.tools.list_ports.comports()
    return [port.device for port in ports]

class SerialConnection:
    def __init__(self):
        self.connection = None
    
    def connect(self, port):
        """連接指定的 COM port"""
        try:
            if self.connection:
                self.connection.close()
            self.connection = serial.Serial(port, '500000', timeout=0, stopbits=serial.STOPBITS_TWO)
            return True
        except Exception as e:
            print(f"連接失敗: {str(e)}")
            return False
    
    def write(self, data):
        """寫入資料到串口"""
        if self.connection and self.connection.is_open:
            self.connection.write(data)
    
    def close(self):
        """關閉串口連接"""
        if self.connection:
            self.connection.close()

# 建立全域串口連接物件
serial_connection = SerialConnection()

def getRowNameFromWell(well):
    rowName = well[0:1]  # for row
    return rowName

def getColumnNumberFromWell(well):
    columnNumber = well[1:3]
    return columnNumber

def sendSerialCommand(wellName, barcode):
    rowName = getRowNameFromWell(wellName)
    columnNumber = getColumnNumberFromWell(wellName)
    serialString = "<" + rowName + "," + columnNumber + ",S," + barcode +">"
    serialString = bytes(serialString, 'us-ascii')
    print(serialString)
    serial_connection.write(serialString)

def turnPanelOff():
    serialString = "<A,1,X,empty>"
    serialString = bytes(serialString, 'us-ascii')
    print(serialString)
    serial_connection.write(serialString)
    time.sleep(1)  # 等待一段時間以確保命令被處理
    
def blankPanel():
    serialString = "<A,1,X, >"
    serialString = bytes(serialString, 'us-ascii')
    print(serialString)
    serial_connection.write(serialString)

def parseCommands(self):
    # update the row currently highlighted in the pandastable
    pt.setSelectedRow(self.currentCsvPosition)
    pt.redraw()

    # 只需要處理一個孔位
    wellName = self.csvData.at[self.currentCsvPosition, 'Well']
    barcode = self.csvData.at[self.currentCsvPosition, 'Barcode']
    blankPanel()
    sendSerialCommand(wellName, barcode)

def onClosing():
    turnPanelOff()
    serial_connection.close()
    print("Closing serial port!")
    mainWindow.destroy()
    exit()

class lightPanelGUI(Frame):
    def __init__(self,master):
        self.csvData = pd.DataFrame()
        self.currentCsvPosition=0
        self.csvRecordCount=0

        self.master = master
        self.master.title("Single Microplate Light Guide")
        self.master.maxsize(500,500)
        self.master.minsize(500,500)

        c = Canvas(self.master)
        c.configure(yscrollincrement='10c')

        # 建立頂部框架
        top_frame = Frame(self.master, bg='#f0f0f0', width=450, height=50,pady=3)
        
        # COM Port 選擇框架
        com_frame = Frame(self.master, bg='#f0f0f0', width=450, height=50,pady=3)

        # 建立中央框架用於顯示表格
        self.center_frame = Frame(self.master, bg='white', width=450, height=500, pady=3)

        # 佈局設定
        self.master.grid_rowconfigure(3,weight=1)  # 修改為3列
        self.master.grid_columnconfigure(0, weight=1)
        com_frame.grid(row=0, sticky="ew")
        top_frame.grid(row=1, sticky="ew")
        self.center_frame.grid(row=2, sticky="nsew")  # 表格框架放在第3列

        # 建立 COM port 選擇元件
        Label(com_frame, text="選擇 COM Port:", bg='#f0f0f0').grid(row=0, column=0, padx=5)
        self.port_var = StringVar(self.master)
        self.port_list = get_available_ports()
        if self.port_list:
            # 必須傳入一個初始 value 參數給 OptionMenu
            self.port_var.set(self.port_list[0])
            self.port_menu = OptionMenu(com_frame, self.port_var, self.port_list[0], *self.port_list[1:])
            self.port_menu.config(state='normal')
        else:
            # 若沒有可用的 COM port，建立一個 disabled 的 OptionMenu 並給空字串作為 value
            self.port_var.set("")
            self.port_menu = OptionMenu(com_frame, self.port_var, "")
            self.port_menu.config(state='disabled')
        self.port_menu.grid(row=0, column=1, padx=5)
        
        # 新增重新整理和連接按鈕
        self.refresh_button = Button(com_frame, text="重新整理", command=self.refresh_ports)
        self.refresh_button.grid(row=0, column=2, padx=5)
        self.connect_button = Button(com_frame, text="連接", command=self.connect_port)
        self.connect_button.grid(row=0, column=3, padx=5)

        # 建立其他控制元件
        self.fileButton = tkinter.Button(top_frame, text="選擇檔案", command=self.openFile)
        self.backButton = tkinter.Button(top_frame, text="上一個孔位", command=self.previousWell, state='disabled')
        self.nextButton = tkinter.Button(top_frame, text="下一個孔位", command=self.nextWell, state='disabled')

        # 佈局控制元件
        self.fileButton.grid(row=0, column=1)
        top_frame.grid_columnconfigure(2,weight=3)
        self.backButton.grid(row=0, column=3)
        self.nextButton.grid(row=0, column=4)

    def refresh_ports(self):
        """重新整理可用的 COM ports"""
        self.port_list = get_available_ports()
        menu = self.port_menu["menu"]
        menu.delete(0, "end")
        for port in self.port_list:
            menu.add_command(label=port, 
                           command=lambda p=port: self.port_var.set(p))
        if self.port_list:
            self.port_var.set(self.port_list[0])
        self.connect_button.config(text="連接")
        self.connect_button.config(state='active')
        self.port_menu.config(state='active')

    def connect_port(self):
        """連接選擇的 COM port"""
        selected_port = self.port_var.get()
        if serial_connection.connect(selected_port):
            print(f"成功連接到 {selected_port}")
            self.connect_button.config(text="已連接")
            self.connect_button.config(state='disabled')
            self.port_menu.config(state='disabled')
            self.backButton.config(state='active')
            self.nextButton.config(state='active')
        else:
            print(f"無法連接到 {selected_port}")
            self.connect_button.config(text="連接失敗")

    def nextWell(self):
        pt.setRowColors(rows=self.currentCsvPosition,clr="#D3D3D3",cols='all')
        pt.redraw()
        if self.currentCsvPosition < self.csvRecordCount - 1:
            self.currentCsvPosition=self.currentCsvPosition+1
        parseCommands(self)

    def previousWell(self):
        if self.currentCsvPosition > 0:
            self.currentCsvPosition = self.currentCsvPosition - 1
        parseCommands(self)

    def openFile(self):
        global pt
        self.fileName = askopenfilename()
        # 修改CSV檔案格式，只需要Well和Barcode兩個欄位
        self.csvData = pd.read_csv(self.fileName,names=['Barcode','Well','Transfer_volume'],header=0)
        self.csvRecordCount=len(self.csvData.index)
        self.currentCsvPosition=0

        # 如果已經存在表格，先移除
        for widget in self.center_frame.winfo_children():
            widget.destroy()

        # 在中央框架中建立新表格
        pt = Table(self.center_frame, dataframe=self.csvData, 
                  showtoolbar=False, showstatusbar=False, height=450)
        pt.adjustColumnWidths(30)
        pt.show()
        parseCommands(self)

if __name__ == '__main__':
    mainWindow = tkinter.Tk()
    lightPanelGUIinstance = lightPanelGUI(mainWindow)
    mainWindow.protocol("WM_DELETE_WINDOW", onClosing)
    mainWindow.mainloop()