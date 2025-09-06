import tkinter as tk
from tkinter import Frame,colorchooser
import serial
import serial.tools.list_ports
from threading import Thread, Lock
import queue
from threading import Event
import time

# LED板基本參數設定
boxRow = 8 # 8 rows
boxColumn = 12 # 12 columns

# 取得可用 COM ports
def get_available_ports():
    ports = serial.tools.list_ports.comports()
    return [port.device for port in ports]

# 串口連接類別
class SerialConnection:
    def __init__(self):
        self.connection = None
        self._lock = Lock()  # 保證同時間只有一個 write

    # 連接指定的 COM port
    def connect(self, port):
        try:
            if self.connection:
                self.connection.close()
            self.connection = serial.Serial(
                port,
                500000,
                timeout=0,            # 非阻塞讀
                write_timeout=1.0,    # 寫入逾時避免死等
                stopbits=serial.STOPBITS_TWO,
                # 視硬體情況可開：rtscts=True 或 xonxoff=True
            )
            # 確認連接成功
            try:
                self.connection.reset_input_buffer()
                self.connection.reset_output_buffer()
            except Exception:
                pass
            return True
        # 連接失敗
        except Exception as e:
            print(f"Connect fail: {str(e)}")
            return False
    
    # 安全寫入並排空輸出佇列
    def write_and_drain(self, data: bytes, inter_delay: float = 0.001):
        """
        安全寫入：write -> flush -> out_waiting 清空 -> 可選間隔
        不要在 UI 執行緒大量呼叫；建議搭配 SerialSender 佇列背景送。
        """
        if not (self.connection and self.connection.is_open):
            return False
        with self._lock:
            self.connection.write(data)
            # 1) 等待 Driver/OS 緩衝送出
            self.connection.flush()
            # 2) 確認輸出佇列已空（有些平台 out_waiting 可能一直是 0，也沒關係）
            while getattr(self.connection, "out_waiting", 0) > 0:
                time.sleep(0.001)
            # 3) 留一點處理縫隙給對端 MCU（必要時可調大）
            if inter_delay > 0:
                time.sleep(inter_delay)
        return True
    #  write不等待的版本（保留）
    def write(self, data):
        if self.connection and self.connection.is_open:
            self.connection.write(data)
    
    # 關閉COM port連接
    def close(self):
        if self.connection:
            try:
                self.connection.close()
            except Exception:
                pass
            self.connection = None

# 專責安序（序列化）送資料的背景執行緒
class SerialSender:
    """
    專責安序（序列化）送資料的背景執行緒。
    UI 呼叫 send(payload) -> 背景逐筆 write_and_drain -> (可選) 等 ACK
    """
    def __init__(self, ser_conn: SerialConnection,
                 inter_delay: float = 0.001,
                 wait_ack: bool = False, ack_token: bytes = b"<ACK>", ack_timeout: float = 0.3):
        self.ser_conn = ser_conn
        self.q = queue.Queue()
        self.stop_evt = Event()
        self.inter_delay = inter_delay
        self.wait_ack = wait_ack
        self.ack_token = ack_token
        self.ack_timeout = ack_timeout
        self.thread = Thread(target=self._run, daemon=True)
    
    # 啟動背景執行緒
    def start(self):
        if not self.thread.is_alive():
            self.thread.start()

    # 停止背景執行緒
    def stop(self):
        self.stop_evt.set()
        self.q.put(None)  # 喚醒
        self.thread.join(timeout=1)

    # 放入佇列等待送出
    def send(self, payload: bytes):
        self.q.put(payload)

    # 等待 ACK 標記
    def _wait_for_ack(self) -> bool:
        """
        等待直到讀到一段以 '>' 結尾的資料，且內容含有 ack_token（例如 <ACK>）。
        若超時則回 False。
        """
        conn = self.ser_conn.connection
        if not (conn and conn.is_open):
            return False
        deadline = time.monotonic() + float(self.ack_timeout)
        buf = b""
        # 設置臨時讀逾時
        old_to = conn.timeout
        conn.timeout = min(self.ack_timeout, 0.5)
        try:
            while time.monotonic() < deadline:
                # 裝置會用 println("<ACK>")，所以讀到 '>' 為止即可湊齊一個標記
                chunk = conn.read_until(b'>')
                if chunk:
                    buf += chunk
                    if self.ack_token in buf:
                        # print("ACK:", buf)  # 需要除錯可打開
                        return True
                else:
                    # 沒資料就小睡一下，避免空轉
                    time.sleep(0.001)
        finally:
            conn.timeout = old_to
        print("WARN: missing ACK, got:", buf)
        return False
    
    # 主要執行緒函式
    def _run(self):
        while not self.stop_evt.is_set():
            item = self.q.get()
            if item is None:
                break
            # 等待串口連接
            if self.wait_ack and self.ser_conn.connection:
                try:
                    self.ser_conn.connection.reset_input_buffer()
                except Exception:
                    pass
            # 寫出 + 排空 + 小延遲
            self.ser_conn.write_and_drain(item, inter_delay=self.inter_delay)
            # 等 ACK
            if self.wait_ack:
                _ok = self._wait_for_ack()
            self.q.task_done()

# 建立全域串口連接物件
serial_connection = SerialConnection()

# 統一的送指令介面
def sendSerialCommand(command="S", s_row='A', s_col=1, textNote="empty", rgb=(0, 0, 255), bright=None):
    """
    L: <A,1,L,empty,0,0,0,BRIGHT>   只送一次（全域亮度）
    S: <ROW,COL,S,NOTE,R,G,B>       逐孔位顏色（不帶亮度）
    X: <A,1,X,empty>
    """
    # L:設定亮度指令處理
    if command == "L":
        if bright is None:
            raise ValueError("sendSerialCommand(L): bright is required")
        br = int(max(0, min(255, bright)))
        serialString = f"<A,1,L,empty,0,0,0,{br}>"
    # M:LED陣列資料傳送指令處理
    elif command == "M":
        # textNote 這裡放 mask_hex（24 hex chars）
        r, g, b = [int(max(0, min(255, v))) for v in rgb]
        mask_hex = textNote
        if not isinstance(mask_hex, str) or len(mask_hex) != 24:
            raise ValueError("sendSerialCommand(M): mask_hex must be 24 hex chars")
        serialString = f"<A,1,M,{mask_hex.upper()},{r},{g},{b}>"
    # S:單孔位資料傳送指令處理
    elif command == "S":
        r, g, b = [int(max(0, min(255, v))) for v in rgb]
        serialString = f"<{s_row},{s_col},S,{textNote},{r},{g},{b}>"
    # X:關閉面板指令處理
    elif command == "X":
        serialString = "<A,1,X,empty>"
    # 其他指令不支援
    else:
        raise ValueError("Invalid parameters for sendSerialCommand()")
    
    print(serialString)
    payload = serialString.encode("us-ascii")

    # 優先用背景 sender；沒有的話就同步送（含排空）
    if 'lightPanelGUIinstance' in globals() and hasattr(lightPanelGUIinstance, 'sender') and lightPanelGUIinstance.sender:
        lightPanelGUIinstance.sender.send(payload)
    else:
        serial_connection.write_and_drain(payload, inter_delay=0.005)

# 統一透過 sender 送出 X 指令，並等待 ACK
def turnPanelOff():
    sendSerialCommand(command="X")

# 關閉視窗時的清理工作
def onClosing():
    try:
        if lightPanelGUIinstance and lightPanelGUIinstance.timer_job is not None:
            lightPanelGUIinstance.after_cancel(lightPanelGUIinstance.timer_job)
            lightPanelGUIinstance.timer_job = None
    except Exception:
        pass

    # 先送 X 指令關閉面板
    try:
        turnPanelOff()
        # 等佇列清空，避免關太快丟包
        if lightPanelGUIinstance and hasattr(lightPanelGUIinstance, 'sender') and lightPanelGUIinstance.sender:
            lightPanelGUIinstance.sender.q.join()
    except Exception:
        pass

    # 再停 sender
    try:
        if lightPanelGUIinstance and hasattr(lightPanelGUIinstance, 'sender') and lightPanelGUIinstance.sender:
            lightPanelGUIinstance.sender.stop()
            lightPanelGUIinstance.sender = None
    except Exception:
        pass
    # 最後關串口
    serial_connection.close()
    print("Closing serial port!")
    mainWindow.destroy()

# 主視窗類別
class lightPanelGUI(Frame):
    checkboxes = [] # 96 個 checkbox 的 IntVar
    row_checkboxes = [] # 8 個列 checkbox 的 IntVar
    column_checkboxes = [] # 12 個行 checkbox 的 IntVar

    # 初始化 
    def __init__(self, master=None):
        super().__init__(master)
        self.master = master
        self.pack()
        # 倒數狀態
        self.remaining = 0
        self.timer_job = None
        self.create_widgets()
    # 建立元件
    def create_widgets(self):
        # 第一排 COM port 選單與連接按鈕
        fm1 = tk.LabelFrame(self.master)
        fm1.config(text="Serial Port")
        fm1.pack(side="top", fill="x", padx=6, pady=3)
        # COM port 選單
        self.port_var = tk.StringVar(self)
        self.port_list = get_available_ports()
        # COM port 標籤
        self.port_label = tk.Label(fm1, text="Select COM Port:")
        self.port_label.pack(side="left", fill="y", expand=False, padx=2, pady=2)
        # COM port 下拉選單
        if self.port_list:
            self.port_var.set(self.port_list[0])
            self.port_menu = tk.OptionMenu(fm1, self.port_var, *self.port_list)
        else:
            self.port_var.set("No COM ports available")
            self.port_menu = tk.OptionMenu(fm1, self.port_var, "No COM ports available")
            self.port_menu.config(state='disabled')
        self.port_menu.pack(side="left", fill="y", expand=False, padx=2, pady=2)
        # 連接按鈕
        self.connect_button = tk.Button(fm1, text="Connect", command=self.connect_serial)
        if not self.port_list:
            self.connect_button.config(state='disabled')
        self.connect_button.pack(side="left", fill="y", expand=False, padx=2, pady=2)
        # 斷開按鈕
        self.disconnect_button = tk.Button(fm1, text="Disconnect", command=self.disconnect_serial)
        self.disconnect_button.config(state='disabled')
        self.disconnect_button.pack(side="left", fill="y", expand=False, padx=2, pady=2)
        # 第二排 顏色與亮度
        fm2 = tk.LabelFrame(self.master)
        fm2.config(text="LED Color and Brightness")
        fm2.pack(side="top", fill="x", padx=6, pady=3)
        # 顏色選擇按鈕
        self.color_button = tk.Button(fm2, text="Pick LED Color", command=lambda: self.color_pick_box())
        self.color_button.pack(side="left", fill="y", expand=False, padx=2, pady=2)
        # 顏色顯示標籤
        self.color_label=tk.Label(fm2, text="LED color:")
        self.color_label.pack(side="left", fill="y", expand=False, padx=2, pady=2)
        # 顏色顯示方塊
        self.color_var = tk.StringVar(value="#0000FF")
        self.color_display = tk.Label(fm2, textvariable=self.color_var, bg=self.color_var.get(), width=10)
        self.color_display.pack(side="left", fill="y", expand=False, padx=2, pady=2)
        self._apply_color(self.color_var.get())
        # 亮度調整 Spinbox
        self.bright_label=tk.Label(fm2, text="LED brightness:")
        self.bright_label.pack(side="left", fill="y", expand=False, padx=12, pady=2)
        # 亮度 Spinbox
        self.bright_var = tk.IntVar(value=255)
        self.bright_spinbox = tk.Spinbox(fm2, from_=0, to=255, width=4, textvariable=self.bright_var)
        self.bright_spinbox.pack(side="left", fill="y", expand=False, padx=2, pady=2)
        # 第三排 倒數計時器
        fm3 = tk.LabelFrame(self.master)
        fm3.config(text="Timer")
        fm3.pack(side="top", fill="x", padx=6, pady=3)
        # 倒數標籤
        self.timer_label = tk.Label(fm3, text="Countdown time(seconds):")
        self.timer_label.pack(side="left", fill="y", expand=False, padx=2, pady=2)
        # 倒數 Spinbox
        self.countDownTime_var = tk.IntVar(value=5)
        self.timer_spinbox = tk.Spinbox(
            fm3, from_=1, to=3600, width=6, textvariable=self.countDownTime_var,
            command=self.timer_sprinbox_changed
        )
        self.timer_spinbox.pack(side="left", fill="y", expand=False, padx=2, pady=2)
        # 開始按鈕
        self.start_button = tk.Button(
            fm3, text="Start", fg="blue", padx= 20, command=self.start_countdown, state='disabled'
        )
        self.start_button.pack(side="left", fill="y", expand=False, padx=2, pady=2)
        # 停止按鈕
        self.stop_button = tk.Button(
            fm3, text="Stop", fg="red", padx=20, command=self.stop_countdown, state='disabled'
        )
        self.stop_button.pack(side="left", fill="y", expand=False, padx=2, pady=2)

        # 倒數狀態Label
        self.countdown_var = tk.StringVar(value="No connect")
        self.countdown_label = tk.Label(fm3, textvariable=self.countdown_var)
        self.countdown_label.pack(side="left", padx=12, pady=2)
        
        # 第四排 96 個 checkbox
        fm4 = tk.LabelFrame(self.master)
        fm4.config(text="LED Select")
        fm4.pack(side="top", fill="x", padx=6, pady=6)

        # 建立 96 個 checkbox（8x12）+ 左側列標頭 + 上方欄標頭
        for i in range(boxRow + 1):
            for j in range(boxColumn + 1):
                var = tk.IntVar()
                if i == 0 and j == 0:
                    continue
                elif i == 0:
                # 欄表頭（1..boxColumn）
                    cb = tk.Checkbutton(
                        fm4, variable=var, text=f"{j}",
                        command=lambda column=j, v=var: self.column_checkbox_clicked(column, v)
                    )
                    cb.grid(row=i, column=j, padx=2, pady=2)
                    self.column_checkboxes.append(var)
                elif j == 0:
                # 列表頭（A..H）
                    cb = self.make_left_text_checkbutton(
                        fm4, text=chr(ord('A') + i - 1), var=var,
                        command=lambda row=i, v=var: self.row_checkbox_clicked(row, v)
                    )
                    cb.grid(row=i, column=j, padx=2, pady=2)
                    self.row_checkboxes.append(var)
                else:
                    cb = tk.Checkbutton(fm4, text= f"{chr(ord('A') + i - 1)}{j:02d}", variable=var)
                    cb.grid(row=i, column=j, padx=2, pady=2)
                    self.checkboxes.append(var)
    
    # 建立文字朝左的 Checkbutton
    def make_left_text_checkbutton(self, parent, text, var, command=None):
        wrapper = tk.Frame(parent)
        lbl = tk.Label(wrapper, text=text)
        cb  = tk.Checkbutton(wrapper, variable=var, command=command)
        lbl.pack(side="left", padx=(0,4))
        cb.pack(side="left")

        # 讓點文字也能切換勾選
        def toggle(_event=None, v=var):
            v.set(0 if v.get() else 1)
            if command:
                command()
        lbl.bind("<Button-1>", toggle)

        return wrapper
    
    # 建立COM port連接
    def connect_serial(self):
        port = self.port_var.get()
        if serial_connection.connect(port):
            print(f"Connected to {port}")
            self.countdown_var.set(f"{port} connected")
            self.connect_button.config(state='disabled')
            self.disconnect_button.config(state='normal')
            self.start_button.config(state='normal')

            if not hasattr(self, 'sender') or self.sender is None:
                self.sender = SerialSender(
                    serial_connection,
                    inter_delay=0.002,     # 1~5ms 視裝置負載可調
                    wait_ack=True,         # 等 <ACK>
                    ack_token=b"<ACK>",
                    ack_timeout=0.5        # 0.2~0.5 視需求調整
                )
                self.sender.start()
        else:
            print(f"Failed to connect to {port}")

    # 斷開COM port連接
    def disconnect_serial(self):
        # 先停 sender
        if hasattr(self, 'sender') and self.sender:
            try:
                self.sender.stop()
            except Exception:
                pass
            self.sender = None

        serial_connection.close()
        print("Disconnected from serial port")
        self.countdown_var.set("Device disconnected")
        self.connect_button.config(state='normal')
        self.disconnect_button.config(state='disabled')
        self.start_button.config(state='disabled')
    
    # 處理列 checkbox 點擊事件
    def row_checkbox_clicked(self, row_index, row_var):
        state = row_var.get()
        print(f"Row {row_index} clicked, state: {state}")
        print(f"Total checkboxes: {len(self.checkboxes)}")
        base = (row_index - 1) * boxColumn
        for j in range(boxColumn):
            index = base +j
            if index < len(self.checkboxes):
                self.checkboxes[index].set(state)
    # 處理行 checkbox 點擊事件
    def column_checkbox_clicked(self, column_index, column_var):
        state = column_var.get()
        print(f"Column {column_index} clicked, state: {state}")
        print(f"Total checkboxes: {len(self.checkboxes)}")
        for i in range(boxRow):
            index = i * boxColumn + (column_index - 1)
            if index < len(self.checkboxes):
                self.checkboxes[index].set(state)
    
    # 顏色選擇器
    def color_pick_box(self):
        color_code = colorchooser.askcolor(
            initialcolor=self.color_var.get(), title="Choose color"
        )
        hex_color = color_code[1]
        if hex_color:  # 只有有選到顏色才套用
            self._apply_color(hex_color)

    # 處理倒數 Spinbox 變更事件
    def timer_sprinbox_changed(self):
        try:
            # 僅更新預設值，不立刻改變顯示
            _ = int(self.timer_spinbox.get())
        except ValueError:
            print("Invalid input for timer")

    # 倒數啟動
    def start_countdown(self):
        """開始倒數：使用 after() 每秒更新一次，避免 UI 卡住"""
        if self.timer_job is not None:
            return  # 已在倒數中，避免重複啟動

        try:
            self.remaining = int(self.timer_spinbox.get())
        except ValueError:
            self.remaining = 5
            self.countDownTime_var.set(self.remaining)

        if self.remaining <= 0:
            return
        self.setallwell()
        self.timer_spinbox.config(state='disabled')
        self.start_button.config(state='disabled')
        self.disconnect_button.config(state='disabled')
        self.stop_button.config(state='normal')
        self._update_countdown_label()
        self.timer_job = self.after(1000, self._countdown_tick)

    # 每秒倒數更新 
    def _countdown_tick(self):
        self.remaining -= 1
        if self.remaining <= 0:
            self.countdown_var.set("Time's up!")
            # 這裡可加入時間到的動作，例如：
            # turnPanelOff() 或 sendSerialCommand(...)
            turnPanelOff()
            self._finish_countdown_ui()
            self.timer_job = None
            return

        self._update_countdown_label()
        self.timer_job = self.after(1000, self._countdown_tick)

    # 手動停止倒數
    def stop_countdown(self):
        if self.timer_job is not None:
            self.after_cancel(self.timer_job)
            self.timer_job = None
        turnPanelOff()
        self.countdown_var.set("Stopped")
        self._finish_countdown_ui()

    # 倒數結束/停止後恢復 UI 狀態
    def _finish_countdown_ui(self):
        self.timer_spinbox.config(state='normal')
        self.start_button.config(state='normal')
        self.disconnect_button.config(state='normal')
        self.stop_button.config(state='disabled')

    # 更新倒數顯示標籤
    def _update_countdown_label(self):
        self.countdown_var.set(f"{self.remaining} seconds remaining...")

    # 顏色工具：依背景自動選擇文字顏色（黑/白）
    def _hex_to_rgb(self, hex_color: str):
        hc = hex_color.lstrip('#')
        return tuple(int(hc[i:i+2], 16) for i in (0, 2, 4))  # (r,g,b) 0~255

    # 依 WCAG 相對亮度選擇黑(#000)或白(#FFF)
    def _best_text_color(self, hex_color: str) -> str:
        r, g, b = self._hex_to_rgb(hex_color)

        def _srgb_to_lin(c):
            c = c / 255.0
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

        R, G, B = _srgb_to_lin(r), _srgb_to_lin(g), _srgb_to_lin(b)
        L = 0.2126 * R + 0.7152 * G + 0.0722 * B  # relative luminance

        contrast_white = (1.05) / (L + 0.05)
        contrast_black = (L + 0.05) / 0.05
        return "#FFFFFF" if contrast_white >= contrast_black else "#000000"

    # 套用背景色並自動設定可讀的文字顏色
    def _apply_color(self, hex_color: str):
         if not hex_color or not isinstance(hex_color, str):
            return
         fg = self._best_text_color(hex_color)
         self.color_var.set(hex_color.upper())
         self.color_display.config(bg=hex_color, fg=fg, textvariable=self.color_var)

    # 取得目前選擇的 RGB 顏色（0~255）
    def get_current_rgb255(self):
        return self._hex_to_rgb(self.color_var.get())

    # 取得目前顏色與亮度的組合字串
    def get_color_payload(self):
        r, g, b = self._hex_to_rgb(self.color_var.get())
        bright = int(self.bright_var.get())
        return f"{r:02X}{g:02X}{b:02X}", bright

    # 產生目前勾選的孔位遮罩字串
    def _selected_mask_hex(self) -> str:
        """
        依 row-major 映射產生 96-bit 遮罩（A01 為 bit0, A02 為 bit1, …, H12 為 bit95）
        回傳 12 bytes 的十六進位字串（24 chars, 大寫）。
        """
        total_bits = boxRow * boxColumn  # 96
        mask = bytearray((total_bits + 7) // 8)  # 12 bytes
        # self.checkboxes 的順序就是 row-major：i 往下、j 往右
        for i in range(1, boxRow + 1):          # A..H
            for j in range(1, boxColumn + 1):   # 01..12
                idx = (i - 1) * boxColumn + (j - 1)  # 0..95
                if idx < len(self.checkboxes) and self.checkboxes[idx].get():
                    byte_i = idx // 8
                    bit_i  = idx % 8             # LSB-first：bit0=A01
                    mask[byte_i] |= (1 << bit_i)
        return mask.hex().upper()
    
    # 送出目前設定的全域亮度與選擇的孔位顏色
    def setallwell(self):
        """
        L：只送一次全域亮度
        S：逐孔位送顏色（只針對已勾選的孔位）
        """
        # 取得 UI 的顏色與亮度
        r, g, b = self._hex_to_rgb(self.color_var.get())
        bright = int(max(0, min(255, self.bright_var.get())))

        # 1) 先送一次全域亮度（只需一次）
        sendSerialCommand(command="L", bright=bright)

        # 2) 逐孔位送顏色（只處理勾選的）
        mask_hex = self._selected_mask_hex()
        if int(mask_hex, 16) != 0:  # 有至少一顆要亮
            sendSerialCommand(command="M", textNote=mask_hex, rgb=(r, g, b))
# 主程式 入口
if __name__ == '__main__':
    mainWindow = tk.Tk()
    mainWindow.title("Timing Light Panel Controller")
    lightPanelGUIinstance = lightPanelGUI(mainWindow)
    mainWindow.protocol("WM_DELETE_WINDOW", onClosing)
    mainWindow.mainloop()
