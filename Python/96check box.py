import tkinter as tk
from tkinter import Frame
import serial
import serial.tools.list_ports
import time

rowName = "A"
columnNumber = "1"
boxRow = 8
boxColumn = 12

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
            self.connection = serial.Serial(port, 500000, timeout=0, stopbits=serial.STOPBITS_TWO)
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

def sendSerialCommand(wellName, barcode):
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

def onClosing():
    turnPanelOff()
    serial_connection.close()
    print("Closing serial port!")
    mainWindow.destroy()
    exit()

class lightPanelGUI(Frame):
    checkboxes = []
    row_checkboxes = []
    column_checkboxes = []

    def __init__(self, master=None):
        super().__init__(master)
        self.master = master
        self.pack()
        self.create_widgets()

    def create_widgets(self):
        fm1 = tk.Frame(self.master)
        fm1.pack(side="top", fill="x")

        self.port_var = tk.StringVar(self)
        self.port_list = get_available_ports()

        self.port_label = tk.Label(fm1, text="Select COM Port:")
        self.port_label.pack(side="left",fill="y",expand=False)

        if self.port_list:
            self.port_var.set(get_available_ports()[0])
            self.port_menu = tk.OptionMenu(fm1, self.port_var, *get_available_ports())
        else:
            self.port_var.set("No COM ports available")
            self.port_menu = tk.OptionMenu(fm1, self.port_var, "No COM ports available")
            self.port_menu.config(state='disabled')
        self.port_menu.pack(side="left",fill="y",expand=False)

        self.connect_button = tk.Button(fm1, text="Connect", command=self.connect_serial)
        if not self.port_list:
            self.connect_button.config(state='disabled')
        self.connect_button.pack(side="left",fill="y",expand=False)

        self.disconnect_button = tk.Button(fm1, text="Disconnect", command=self.disconnect_serial)
        if not self.port_list:
            self.disconnect_button.config(state='disabled')
        self.disconnect_button.pack(side="left",fill="y",expand=False)

        fm2 = tk.Frame(self.master)
        fm2.pack(side="top", fill="x")

        for i in range(boxColumn + 1):
            for j in range(boxRow + 1):
                var = tk.IntVar()
                if i == 0 and j == 0:
                    # 跳過第一個位置
                    continue
                elif i == 0:
                    cb = tk.Checkbutton(fm2, variable=var, 
                                      command=lambda row=j, v=var: self.row_checkbox_clicked(row, v))
                    cb.grid(row=i, column=j, padx=2, pady=2)
                    self.row_checkboxes.append(var)
                elif j == 0:
                    cb = tk.Checkbutton(fm2, variable=var,
                                        command=lambda column=i, v=var: self.column_checkbox_clicked(column, v))
                    cb.grid(row=i, column=j, padx=2, pady=2)
                    self.column_checkboxes.append(var)
                else:
                    cb = tk.Checkbutton(fm2, text=f"LED {(i-1)*8+j}", variable=var)
                    cb.grid(row=i, column=j, padx=2, pady=2)
                    self.checkboxes.append(var)

    def connect_serial(self):
        port = self.port_var.get()
        if serial_connection.connect(port):
            print(f"Connected to {port}")
        else:
            print(f"Failed to connect to {port}")

    def disconnect_serial(self):
        serial_connection.close()
        print("Disconnected from serial port")

    def row_checkbox_clicked(self, row_index, row_var):
        """處理列 checkbox 點擊事件"""
        state = row_var.get()
        print(f"Row {row_index} clicked, state: {state}")
        print(f"Total checkboxes: {len(self.checkboxes)}")
        
        for i in range(boxColumn):
            index = (i * boxRow) + (row_index - 1)
            print(f"Trying to set checkbox at index: {index}")
            if index < len(self.checkboxes):
                self.checkboxes[index].set(state)
    
    def column_checkbox_clicked(self, column_index, column_var):
        """處理行 checkbox 點擊事件"""
        state = column_var.get()
        print(f"Column {column_index} clicked, state: {state}")
        print(f"Total checkboxes: {len(self.checkboxes)}")
        
        for i in range(boxRow):
            index = ((column_index - 1) * boxRow) + i
            print(f"Trying to set checkbox at index: {index}")
            if index < len(self.checkboxes):
             self.checkboxes[index].set(state)


if __name__ == '__main__':
    mainWindow = tk.Tk()
    mainWindow.title("Light Guide Control")
    lightPanelGUIinstance = lightPanelGUI(mainWindow)
    mainWindow.protocol("WM_DELETE_WINDOW", onClosing)
    mainWindow.mainloop()